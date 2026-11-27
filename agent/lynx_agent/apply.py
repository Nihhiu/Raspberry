"""Aplicação de propostas aprovadas (Fase 2A) — lógica pura, sem transporte.

A coreografia real (lynx_read fence, lynx_notes_replace, releitura, undo) fica
na skill; este módulo valida e calcula tudo o que é verificável offline:

- pré-condições de aplicação (identidade, revisão, transport parado);
- validação integral das notas nativas (todos os campos obrigatórios);
- fusão read-modify-write que preserva notas e atributos não visados;
- verificação exata do resultado re-lido contra o esperado.

Regra do plano: aplicar tudo ou nada; se a preservação não for provável,
rejeitar. O fence triplo do servidor fecha a janela validação↔aplicação —
se a revisão mudar entretanto, a escrita é recusada com `changed`.
"""

from __future__ import annotations

from typing import Any, Optional

from .proposals import ProposalStale, canonical_json

# Campos nativos obrigatórios numa nota (auditoria: docs/REMOTE_CONTROL.md).
# expression são as 3 lanes MPE; listas vazias = nenhuma curva.
REQUIRED_NOTE_FIELDS = (
    "start", "length", "channel", "key", "velocity", "pan", "muted",
    "finePitch", "slide", "porta", "release", "modX", "modY", "colour",
    "group", "chance", "velocityRange", "chanceGroup", "chanceOne",
    "expression",
)

EXPRESSION_LANES = ("pitch", "timbre", "pressure")

SUPPORTED_OPERATIONS = ("add_notes", "replace_range", "transform_notes")


class ApplyRejected(Exception):
    """A proposta não pode ser aplicada em segurança — recusar o lote inteiro."""


def check_prereqs(
    proposal: dict,
    *,
    project_id: str,
    revision: int,
    playing: bool = False,
    recording: bool = False,
) -> None:
    """Identidade e estado do projeto no momento da escrita.

    O fence server-side repete esta verificação de forma atómica; aqui falha
    cedo e com mensagem clara."""
    if proposal.get("project_id") != project_id:
        raise ProposalStale(
            f"projeto mudou: proposta esperava {proposal.get('project_id')}, atual {project_id}"
        )
    if proposal.get("expected_revision") != revision:
        raise ProposalStale(
            f"revisão mudou: proposta esperava {proposal.get('expected_revision')}, "
            f"atual {revision}"
        )
    if playing or recording:
        raise ApplyRejected("playback/gravação ativos — escritas recusadas")


def validate_note(note: dict, *, index: int = 0) -> None:
    """Uma nota tem de ser nativa completa — sem aproximações."""
    where = f"nota[{index}]"
    if not isinstance(note, dict):
        raise ApplyRejected(f"{where}: não é um objeto")
    missing = [f for f in REQUIRED_NOTE_FIELDS if f not in note]
    if missing:
        raise ApplyRejected(
            f"{where}: campos obrigatórios ausentes {missing} — read-first "
            "obrigatório; notas novas têm de trazer todos os campos nativos"
        )
    for f in ("start", "length", "channel", "key", "colour",
              "group", "chanceGroup"):
        if not isinstance(note[f], int) or isinstance(note[f], bool):
            raise ApplyRejected(f"{where}: campo '{f}' devia ser inteiro")
    for f in ("pan", "finePitch", "release", "modX", "modY"):
        if not isinstance(note[f], (int, float)) or isinstance(note[f], bool):
            raise ApplyRejected(f"{where}: campo '{f}' devia ser numérico")
    # velocity é flutuante normalizado no documento remoto (ex.: 0.756 = 75.6%)
    if not isinstance(note["velocity"], (int, float)) or isinstance(note["velocity"], bool):
        raise ApplyRejected(f"{where}: campo 'velocity' devia ser numérico")
    if not 0.0 <= note["velocity"] <= 1.0:
        raise ApplyRejected(f"{where}: velocity fora de 0..1")
    if note["start"] < 0:
        raise ApplyRejected(f"{where}: start negativo")
    if note["length"] <= 0:
        raise ApplyRejected(f"{where}: length tem de ser > 0")
    if not 0 <= note["key"] <= 131:
        raise ApplyRejected(f"{where}: key fora de 0..131")
    if not isinstance(note["muted"], bool) or not isinstance(note["chanceOne"], bool):
        raise ApplyRejected(f"{where}: muted/chanceOne têm de ser booleanos")
    if not isinstance(note["slide"], bool) or not isinstance(note["porta"], bool):
        raise ApplyRejected(f"{where}: slide/porta têm de ser booleanos (formato nativo)")
    if not 0.0 <= note["chance"] <= 1.0:
        raise ApplyRejected(f"{where}: chance fora de 0..1")
    if not -1.0 <= note["velocityRange"] <= 1.0:
        raise ApplyRejected(f"{where}: velocityRange fora de -1..1")
    expr = note["expression"]
    if not isinstance(expr, dict) or set(expr) != set(EXPRESSION_LANES):
        raise ApplyRejected(
            f"{where}: expression tem de ser objeto com exatamente as lanes "
            f"{list(EXPRESSION_LANES)} (listas vazias = nenhuma curva)"
        )
    for lane in EXPRESSION_LANES:
        points = expr[lane]
        if not isinstance(points, list):
            raise ApplyRejected(f"{where}: expression.{lane} não é lista")
        if len(points) > 4096:
            raise ApplyRejected(f"{where}: expression.{lane} excede 4096 pontos")


def _in_range(note: dict, start: int, end: int) -> bool:
    return start <= note["start"] < end


def compute_new_notes(proposal: dict, current_notes: list[dict]) -> list[dict]:
    """Fusão read-modify-write: notas não visadas ficam intactas, byte a byte."""
    operation = proposal.get("operation")
    target = proposal.get("target", {})
    rng = target.get("range") or {}
    if operation == "add_notes":
        added = proposal["after"].get("added_notes", [])
        start, end = rng.get("start", 0), rng.get("end_exclusive")
        for i, n in enumerate(added):
            validate_note(n, index=i)
            if end is not None and not _in_range(n, start, end):
                raise ApplyRejected(
                    f"nota[{i}] (start={n['start']}) fora do intervalo "
                    f"[{start}, {end}) — recusado"
                )
        return list(current_notes) + list(added)
    # transform_notes (2B/2C) tem a MESMA semântica de replace_range: o
    # "after.notes_in_range" é o conjunto concreto pós-transformação para
    # todo o intervalo (transformadas + intactas). O spec em after.transform
    # é descritivo (auditoria do diff) — a proposta guarda notas, não intenções.
    if operation in ("replace_range", "transform_notes"):
        start, end = rng.get("start"), rng.get("end_exclusive")
        if start is None or end is None or end <= start:
            raise ApplyRejected(f"intervalo inválido [{start}, {end})")
        if operation == "transform_notes" and not isinstance(
            proposal["after"].get("transform", {}), dict
        ):
            raise ApplyRejected("transform_notes: after.transform deve ser objeto")
        kept = [n for n in current_notes if not _in_range(n, start, end)]
        added = proposal["after"].get("notes_in_range", [])
        for i, n in enumerate(added):
            validate_note(n, index=i)
            if not _in_range(n, start, end):
                raise ApplyRejected(
                    f"nota[{i}] (start={n['start']}) fora do intervalo "
                    f"[{start}, {end}) — recusado"
                )
        return kept + list(added)
    raise ApplyRejected(
        f"operação '{operation}' não suportada ({list(SUPPORTED_OPERATIONS)})"
    )


def _note_sort_key(note: dict) -> tuple:
    n = _norm(note)
    return (
        n.get("start", 0), n.get("key", 0), n.get("length", 0),
        n.get("velocity", 0), n.get("channel", 0),
    )


def _norm(value):
    """Normaliza números para comparação: floats float32 do documento remoto
    (ex.: 0.8 → 0.800000011920929) e ints devolvidos onde foram enviados floats."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def verify_applied(
    proposal: dict,
    current_before: list[dict],
    reread_after: list[dict],
) -> tuple[bool, str]:
    """Verificação exata do resultado re-lido contra o esperado.

    A ordem física das notas pode diferir; compara como conjuntos ordenados
    de documentos canónicos. Devolve (ok, detalhe)."""
    try:
        expected = compute_new_notes(proposal, current_before)
    except ApplyRejected as exc:
        return False, f"proposta rejeitada na verificação: {exc}"
    exp = sorted((_note_sort_key(n), canonical_json(_norm(n))) for n in expected)
    got = sorted((_note_sort_key(n), canonical_json(_norm(n))) for n in reread_after)
    if exp == got:
        return True, f"{len(got)} notas confirmadas pela releitura"
    exp_hashes = {h for _, h in exp}
    got_hashes = {h for _, h in got}
    extra = len(got_hashes - exp_hashes)
    missing = len(exp_hashes - got_hashes)
    return False, (
        f"resultado divergente: {extra} notas inesperadas, {missing} em falta "
        f"(esperadas {len(exp)}, lidas {len(got)}) — não declarar sucesso"
    )


def summarize_apply(result_notes: list[dict], before_notes: list[dict]) -> dict:
    """Resumo estruturado para o resultado da escrita."""
    return {
        "before_count": len(before_notes),
        "after_count": len(result_notes),
        "added": len(result_notes) - len(before_notes),
        "preserved_unmentioned": True,
    }
