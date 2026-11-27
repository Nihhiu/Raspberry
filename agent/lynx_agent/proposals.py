"""Serviço de propostas (Fase 1) — cache local limitada à sessão.

Uma proposta NUNCA escreve no LYNX. É um documento estruturado legível com:
identidade de sessão/projeto/revisão, alvo, intervalo, antes/depois, razão e
avisos. É identificada por ID e resumo criptográfico (SHA-256 canónico) do
conteúdo integral. Expira ao fechar a sessão, mudar o projeto, mudar a
revisão ou ultrapassar o prazo. Não é fonte de verdade — antes de aplicar
(2A), reler o estado real via lynx_*.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

PROPOSAL_VERSION = 1
DEFAULT_TTL_S = 900  # 15 minutos


class ProposalError(Exception):
    """Base dos erros de proposta."""


class ProposalNotFound(ProposalError):
    pass


class ProposalInvalid(ProposalError):
    """Conteúdo alterado (hash não corresponde) ou versão desconhecida."""

    pass


class ProposalExpired(ProposalError):
    pass


class ProposalStale(ProposalError):
    """Projeto ou revisão mudaram desde a criação."""

    pass


def canonical_json(obj: Any) -> str:
    """Serialização canónica: chaves ordenadas, sem espaços, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(proposal: dict) -> str:
    return hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest()


def new_proposal(
    *,
    session_id: str,
    project_id: str,
    expected_revision: int,
    target: dict,
    operation: str,
    before: dict,
    after: dict,
    reason: str,
    ppq: int,
    preserve_unmentioned_events: bool = True,
    warnings: Optional[list[str]] = None,
) -> dict:
    """Cria o documento de proposta no contrato alinhado com a auditoria.

    Campos nativos do LYNX nas notas (key/start/length/velocity/...) — sem
    aproximações de nomes. Ticks são relativos ao início do pattern; o
    intervalo é [range.start, range.end_exclusive).
    """
    proposal = {
        "proposal_version": PROPOSAL_VERSION,
        "proposal_id": f"prop-{secrets.token_hex(6)}",
        "session_id": session_id,
        "project_id": project_id,
        "expected_revision": expected_revision,
        "target": {
            "time_reference": "pattern_relative",
            "ticks_per_quarter": ppq,
            **target,
        },
        "operation": operation,
        "before": before,
        "after": after,
        "preserve_unmentioned_events": preserve_unmentioned_events,
        "reason": reason,
        "warnings": warnings or [],
        "created_at": time.time(),
    }
    return proposal


class ProposalCache:
    """Cache em disco, raiz por sessão. Fica em %TEMP% — nada durável."""

    def __init__(self, session_id: str, root: Optional[Path] = None, ttl_s: int = DEFAULT_TTL_S):
        self.session_id = session_id
        self.ttl_s = ttl_s
        if root is None:
            safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "session"
            root = Path(tempfile.gettempdir()) / "lynx-agent-proposals" / safe
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:  # permissões owner-only quando o SO o permite
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def save(self, proposal: dict, *, ttl_s: Optional[int] = None) -> Path:
        if proposal.get("proposal_version") != PROPOSAL_VERSION:
            raise ProposalInvalid("proposal_version desconhecida")
        ttl = ttl_s if ttl_s is not None else self.ttl_s
        envelope = {
            "hash": content_hash(proposal),
            "session_id": self.session_id,
            "project_id": proposal["project_id"],
            "expected_revision": proposal["expected_revision"],
            "expires_at": time.time() + ttl,
            "proposal": proposal,
        }
        path = self.root / f"{proposal['proposal_id']}.json"
        path.write_text(canonical_json(envelope), encoding="utf-8")
        return path

    def load(
        self,
        proposal_id: str,
        *,
        project_id: str,
        expected_revision: int,
        now: Optional[float] = None,
    ) -> dict:
        path = self.root / f"{proposal_id}.json"
        if not path.is_file():
            raise ProposalNotFound(proposal_id)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProposalInvalid(f"proposta ilegível: {exc}") from exc
        proposal = envelope.get("proposal")
        if not isinstance(proposal, dict):
            raise ProposalInvalid("envelope sem proposta")
        if content_hash(proposal) != envelope.get("hash"):
            raise ProposalInvalid("conteúdo alterado após criação (hash não corresponde)")
        if proposal.get("proposal_version") != PROPOSAL_VERSION:
            raise ProposalInvalid("proposal_version desconhecida")
        if envelope.get("session_id") != self.session_id:
            raise ProposalStale("sessão diferente")
        if envelope.get("project_id") != project_id:
            raise ProposalStale("projeto mudou")
        if envelope.get("expected_revision") != expected_revision:
            raise ProposalStale(
                f"revisão mudou: proposta esperava {envelope.get('expected_revision')}, "
                f"atual {expected_revision}"
            )
        now_ts = time.time() if now is None else now
        if now_ts > envelope.get("expires_at", 0):
            raise ProposalExpired("prazo ultrapassado")
        return proposal


def format_diff(proposal: dict, *, max_lines: int = 40) -> str:
    """Diff legível antes/depois, com escala e todas as instâncias afetadas."""
    lines: list[str] = []
    t = proposal["target"]
    lines.append(f"Proposta {proposal['proposal_id']} — {proposal['operation']}")
    lines.append(
        f"Alvo: pattern {t.get('pattern_id', t.get('pattern_index'))}"
        + (f", canal {t['channel_index']}" if t.get("channel_index") is not None else "")
        + f", intervalo [{t.get('range', {}).get('start', 'início')}, "
        f"{t.get('range', {}).get('end_exclusive', 'fim')}) ticks, {t.get('ticks_per_quarter', '?')} PPQ"
    )
    affected = t.get("affected_instances") or []
    if affected:
        lines.append(f"Instâncias afetadas: {', '.join(map(str, affected))}")
    lines.append(f"Razão: {proposal['reason']}")
    transform = proposal["after"].get("transform")
    if transform:
        lines.append(f"Transformação (2B/2C): {canonical_json(transform)}")
    if proposal.get("warnings"):
        lines.append("Avisos: " + "; ".join(proposal["warnings"]))
    before = proposal["before"].get("notes_in_range", [])
    after = proposal["after"].get("notes_in_range", []) or proposal["after"].get("added_notes", [])
    if proposal["operation"] == "add_notes":
        # add_notes NÃO remove nada: as notas existentes ficam; só as novas
        # entram. Notas no `before` não listadas no `after` não são remoções.
        removed: list = []
        added = list(after)
        kept = len(before)
    else:
        removed = [n for n in before if n not in after]
        added = [n for n in after if n not in before]
        kept = len(before) - len(removed)
    lines.append(f"Notas conservadas fora do lote: {'sim' if proposal['preserve_unmentioned_events'] else 'NÃO'}")
    lines.append(f"Resumo: {kept} mantidas, {len(added)} adicionadas, {len(removed)} removidas")
    for n in added[:max_lines]:
        lines.append(f"  + {fmt_note(n)}")
    for n in removed[:max_lines]:
        lines.append(f"  - {fmt_note(n)}")
    total = len(added) + len(removed)
    if total > max_lines:
        lines.append(f"  … ({total - max_lines} linhas omitidas)")
    return "\n".join(lines)


def fmt_note(n: dict) -> str:
    keys = ("key", "start", "length", "velocity", "channel")
    parts = [f"{k}={n[k]}" for k in keys if k in n]
    extra = [f"{k}={n[k]}" for k in n if k not in keys]
    base = " ".join(parts)
    return f"{base} ({', '.join(extra)})" if extra else base
