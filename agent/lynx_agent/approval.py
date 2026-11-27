"""Portão de aprovação (Fase 2A) — diálogo local FORA do controlo do modelo.

Um texto no chat em que o modelo afirma ter aprovação não é autorização
verificável (plano, §Arquitetura). Aqui a aprovação nasce de um clique do
humano num diálogo local (tkinter) que mostra o diff exato. O clique cria um
token ligado ao hash SHA-256 do conteúdo integral da proposta, à sessão, ao
projeto, à revisão e a um prazo curto. O token é de **uso único**: aplicar
consome-o. Qualquer alteração à proposta muda o hash e invalida o token.

REGRAS INVIOlÁVEIS PARA O MODELO:
- NUNCA criar, editar ou apagar ficheiros de token em
  %TEMP%\\lynx-agent-approvals\\ — só o diálogo humano o faz.
- NUNCA conduzir o diálogo (teclado/rato) nem simular cliques.
- Se o token for recusado, expirado ou não existir, a escrita não acontece.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .proposals import (
    ProposalInvalid,
    ProposalStale,
    content_hash,
    format_diff,
)

DEFAULT_APPROVAL_TTL_S = 300  # 5 minutos — aprovações são para já


class ApprovalError(Exception):
    """Base dos erros do portão de aprovação."""


class ApprovalPending(ApprovalError):
    """Já existe uma aprovação não consumida para esta proposta."""


class ApprovalConsumed(ApprovalError):
    """A aprovação não existe ou já foi consumida (uso único)."""


class ApprovalGate:
    """Token de aprovação em disco, por sessão; o humano decide no diálogo."""

    def __init__(self, session_id: str, root: Optional[Path] = None,
                 ttl_s: int = DEFAULT_APPROVAL_TTL_S):
        self.session_id = session_id
        self.ttl_s = ttl_s
        if root is None:
            safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
            root = Path(tempfile.gettempdir()) / "lynx-agent-approvals" / safe
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:  # owner-only quando o SO permite
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _token_path(self, proposal_id: str) -> Path:
        return self.root / f"{proposal_id}.approval.json"

    # --- pedido -----------------------------------------------------------

    def request_approval(
        self,
        proposal: dict,
        diff_text: Optional[str] = None,
        *,
        confirm_fn: Optional[Callable[[dict, str], bool]] = None,
    ) -> Optional[Path]:
        """Mostra o diálogo e, se o humano aprovar, grava o token.

        Devolve o caminho do token ou None se recusado. `confirm_fn` existe
        só para testes; em produção é o diálogo tkinter."""
        pid = proposal.get("proposal_id")
        if not pid:
            raise ProposalInvalid("proposta sem proposal_id")
        token_path = self._token_path(pid)
        if token_path.is_file():
            raise ApprovalPending(
                f"aprovação de {pid} já pendente — consumir ou expirar antes de novo pedido"
            )
        diff = diff_text if diff_text is not None else format_diff(proposal)
        confirm = confirm_fn or _tk_confirm
        if not confirm(proposal, diff):
            return None
        token = {
            "approval_version": 1,
            "proposal_id": pid,
            "hash": content_hash(proposal),
            "session_id": self.session_id,
            "project_id": proposal.get("project_id"),
            "expected_revision": proposal.get("expected_revision"),
            "nonce": secrets.token_hex(16),
            "approved_at": time.time(),
            "expires_at": time.time() + self.ttl_s,
        }
        tmp = token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(token, indent=2), encoding="utf-8")
        tmp.replace(token_path)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
        return token_path

    # --- consumo (uso único) ---------------------------------------------

    def consume(self, proposal: dict, *, now: Optional[float] = None) -> dict:
        """Valida e destrói o token. Uma segunda chamada falha sempre."""
        pid = proposal.get("proposal_id")
        if not pid:
            raise ProposalInvalid("proposta sem proposal_id")
        token_path = self._token_path(pid)
        if not token_path.is_file():
            raise ApprovalConsumed(
                f"sem aprovação válida para {pid} — o humano tem de aprovar no diálogo"
            )
        try:
            token = json.loads(token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProposalInvalid(f"token ilegível: {exc}") from exc
        if token.get("hash") != content_hash(proposal):
            raise ProposalInvalid(
                "conteúdo mudou desde a aprovação (hash do token não corresponde)"
            )
        if token.get("session_id") != self.session_id:
            raise ProposalStale("aprovação de outra sessão")
        if token.get("project_id") != proposal.get("project_id"):
            raise ProposalStale("aprovação de outro projeto")
        if token.get("expected_revision") != proposal.get("expected_revision"):
            raise ProposalStale("aprovação de outra revisão")
        ts = time.time() if now is None else now
        if ts > token.get("expires_at", 0):
            raise ProposalInvalid("aprovação expirada — pedir de novo ao humano")
        token_path.unlink()  # uso único: consumido aqui
        return token


# --- diálogo local --------------------------------------------------------


def _tk_confirm(proposal: dict, diff_text: str) -> bool:
    """Diálogo tkinter: diff completo, botões Aprovar/Recusar. Bloqueia até
    o humano decidir. Fechar a janela conta como recusa."""
    import tkinter as tk

    approved = False
    root = tk.Tk()
    root.title("LYNX Agent — aprovação de escrita")
    root.attributes("-topmost", True)
    root.minsize(720, 480)

    head = tk.Frame(root)
    head.pack(fill="x", padx=12, pady=(12, 4))
    t = proposal.get("target", {})
    tk.Label(
        head,
        text=(
            f"{proposal.get('operation')} — proposta {proposal.get('proposal_id')}  "
            f"(revisão {proposal.get('expected_revision')}, projeto "
            f"{str(proposal.get('project_id'))[:12]}…, hash "
            f"{content_hash(proposal)[:12]}…)"
        ),
        font=("Segoe UI", 11, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        head,
        text="Aprovação de uso único, ligada a este conteúdo exato. O que escreveres no chat não substitui este diálogo.",
        wraplength=680,
        justify="left",
        fg="#555",
        anchor="w",
    ).pack(fill="x", pady=(2, 6))

    text = tk.Text(root, wrap="none", font=("Consolas", 10))
    text.insert("1.0", diff_text)
    text.configure(state="disabled")
    scroll_y = tk.Scrollbar(root, command=text.yview)
    text.configure(yscrollcommand=scroll_y.set)
    scroll_y.pack(side="right", fill="y", padx=(0, 12), pady=4)
    text.pack(fill="both", expand=True, padx=(12, 0), pady=4)

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=12, pady=(4, 12))

    def _approve() -> None:
        nonlocal approved
        approved = True
        root.destroy()

    def _refuse() -> None:
        root.destroy()

    tk.Button(buttons, text="Recusar", width=14, command=_refuse,
              font=("Segoe UI", 10)).pack(side="right", padx=4)
    tk.Button(buttons, text="Aprovar e aplicar", width=18, command=_approve,
              font=("Segoe UI", 10, "bold"), default="active").pack(side="right")
    root.bind("<Escape>", lambda e: _refuse())
    root.protocol("WM_DELETE_WINDOW", _refuse)
    root.lift()
    root.focus_force()
    root.mainloop()
    return approved


def main(argv: list[str]) -> int:
    """CLI: python -m lynx_agent.approval PROPOSTA.json [--diff DIFF.txt]

    O processo humano corre isto; o modelo apenas lê o resultado."""
    import argparse

    parser = argparse.ArgumentParser(description="Portão de aprovação LYNX Agent")
    parser.add_argument("proposal", help="ficheiro da proposta (envelope da cache ou proposta nua)")
    parser.add_argument("--diff", help="ficheiro com o diff a mostrar (default: format_diff)")
    parser.add_argument("--root", help="raiz de tokens (default: %TEMP%/lynx-agent-approvals/<sessão>)")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    proposal = raw.get("proposal", raw)
    diff = Path(args.diff).read_text(encoding="utf-8") if args.diff else None
    gate = ApprovalGate(proposal.get("session_id", "session"),
                        root=Path(args.root) if args.root else None)
    try:
        token = gate.request_approval(proposal, diff)
    except ApprovalPending as exc:
        print(f"REFUSED: {exc}")
        return 2
    print("APPROVED" if token else "REFUSED")
    return 0 if token else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
