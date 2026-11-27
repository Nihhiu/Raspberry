"""Transformações mecânicas de notas (Fase 2B) — puras e determinísticas.

2B do plano: transposição, velocidade e quantização explícita sobre notas
selecionadas, com preservação integral dos restantes atributos; humanização
apenas com limites e semente reproduzível.

Estas funções correm no momento da PROPOSTA: produzem o conjunto concreto
"after" que entra na proposta (e no diff aprovado). A aplicação reusa o
pipeline 2A sem alterações, porque a proposta guarda notas explícitas —
nunca intenções.
"""

from __future__ import annotations

import random
from typing import Any, Optional


class TransformRejected(Exception):
    """A transformação não pode ser calculada em segurança."""


# Ordem fixa de aplicação — documentada no contrato e nunca reordenada:
# transpor → quantizar → velocidade → humanizar (humanizar por último,
# senão desfaz a quantização).
ACTION_KEYS = ("transpose", "quantize", "velocity", "humanize")
SPEC_KEYS = frozenset(ACTION_KEYS + ("filter",))


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_transform(transform: dict) -> None:
    """Valida o spec de transformação antes de entrar na proposta."""
    if not isinstance(transform, dict) or not transform:
        raise TransformRejected("transform tem de ser objeto não vazio")
    unknown = set(transform) - SPEC_KEYS
    if unknown:
        raise TransformRejected(f"chaves desconhecidas em transform: {sorted(unknown)}")
    if not (set(transform) & set(ACTION_KEYS)):
        raise TransformRejected(
            f"transform sem ações (uma de {list(ACTION_KEYS)})"
        )
    tr = transform.get("transpose")
    if tr is not None and not _is_int(tr):
        raise TransformRejected("transpose.semitones deve ser inteiro")
    q = transform.get("quantize")
    if q is not None:
        if not isinstance(q, dict) or not _is_int(q.get("grid_ticks")) or q["grid_ticks"] <= 0:
            raise TransformRejected("quantize.grid_ticks deve ser inteiro > 0")
        s = q.get("strength", 1.0)
        if not _is_num(s) or not 0.0 <= s <= 1.0:
            raise TransformRejected("quantize.strength fora de 0..1")
    v = transform.get("velocity")
    if v is not None:
        if not isinstance(v, dict):
            raise TransformRejected("velocity deve ser objeto")
        given = [k for k in ("delta", "scale", "target") if k in v]
        if len(given) != 1:
            raise TransformRejected(
                "velocity exige exatamente um de: delta, scale, target"
            )
        if not _is_num(v[given[0]]):
            raise TransformRejected(f"velocity.{given[0]} deve ser numérico")
        if given[0] == "scale" and v["scale"] < 0:
            raise TransformRejected("velocity.scale não pode ser negativo")
    h = transform.get("humanize")
    if h is not None:
        if not isinstance(h, dict) or not _is_int(h.get("seed")):
            raise TransformRejected("humanize.seed (inteiro) é obrigatório — semente reproduzível")
        t = h.get("timing_ticks", 0)
        if not _is_num(t) or t < 0:
            raise TransformRejected("humanize.timing_ticks deve ser >= 0 (limite obrigatório)")
        a = h.get("velocity_amount", 0.0)
        if not _is_num(a) or not 0.0 <= a <= 1.0:
            raise TransformRejected("humanize.velocity_amount fora de 0..1 (limite obrigatório)")
    f = transform.get("filter")
    if f is not None:
        if not isinstance(f, dict):
            raise TransformRejected("filter deve ser objeto")
        for k in ("key_min", "key_max"):
            if k in f and not _is_int(f[k]):
                raise TransformRejected(f"filter.{k} deve ser inteiro")
        if "keys" in f and (
            not isinstance(f["keys"], list)
            or not all(_is_int(k) for k in f["keys"])
        ):
            raise TransformRejected("filter.keys deve ser lista de inteiros")
        if "channel" in f and f["channel"] is not None and not _is_int(f["channel"]):
            raise TransformRejected("filter.channel deve ser inteiro")


def _selected(note: dict, flt: Optional[dict]) -> bool:
    if not flt:
        return True
    if "keys" in flt and note["key"] not in flt["keys"]:
        return False
    if "key_min" in flt and note["key"] < flt["key_min"]:
        return False
    if "key_max" in flt and note["key"] > flt["key_max"]:
        return False
    if flt.get("channel") is not None and note["channel"] != flt["channel"]:
        return False
    return True


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def transpose(
    notes: list[dict], semitones: int, *, flt: Optional[dict] = None
) -> list[dict]:
    """Sobe/desce a key das notas selecionadas. Fora de 0..131 → rejeitar
    (recusar em vez de tocar silenciosamente no limite)."""
    out: list[dict] = []
    for i, n in enumerate(notes):
        if not _selected(n, flt):
            out.append(n)
            continue
        new_key = n["key"] + semitones
        if not 0 <= new_key <= 131:
            raise TransformRejected(
                f"nota[{i}] (key {n['key']}) sairia de 0..131 com {semitones:+d} "
                "semitons — recusado"
            )
        m = dict(n)
        m["key"] = new_key
        out.append(m)
    return out


def adjust_velocity(
    notes: list[dict],
    *,
    delta: Optional[float] = None,
    scale: Optional[float] = None,
    target: Optional[float] = None,
    flt: Optional[dict] = None,
) -> list[dict]:
    """Ajusta velocity (0..1) por delta aditivo, escala multiplicativa ou
    valor alvo. Valores resultantes são limitados a 0..1."""
    given = [k for k in ("delta", "scale", "target") if locals()[k] is not None]
    if len(given) != 1:
        raise TransformRejected("exatamente um de: delta, scale, target")
    out: list[dict] = []
    for n in notes:
        if not _selected(n, flt):
            out.append(n)
            continue
        v = n["velocity"]
        if delta is not None:
            v = v + delta
        elif scale is not None:
            v = v * scale
        else:
            v = target
        m = dict(n)
        m["velocity"] = _clamp01(v)
        out.append(m)
    return out


def quantize(
    notes: list[dict],
    *,
    grid_ticks: int,
    strength: float = 1.0,
    flt: Optional[dict] = None,
) -> list[dict]:
    """Aproxima start à múltiplo mais próximo da grelha EXPLÍCITA (ticks).
    strength 0..1 interpola entre posição original e encaixe."""
    if grid_ticks <= 0:
        raise TransformRejected("grid_ticks deve ser > 0")
    out: list[dict] = []
    for n in notes:
        if not _selected(n, flt):
            out.append(n)
            continue
        start = n["start"]
        snapped = round(start / grid_ticks) * grid_ticks
        new_start = int(round(start + (snapped - start) * strength))
        m = dict(n)
        m["start"] = max(0, new_start)
        out.append(m)
    return out


def humanize(
    notes: list[dict],
    *,
    seed: int,
    timing_ticks: float = 0,
    velocity_amount: float = 0.0,
    flt: Optional[dict] = None,
) -> list[dict]:
    """Humanização com LIMITES e SEMENTE reproduzível: mesmo seed + mesmas
    entradas ⇒ mesma saída. timing_ticks limita o desvio de timing; 
    velocity_amount limita o desvio relativo de velocity."""
    if timing_ticks < 0 or not 0.0 <= velocity_amount <= 1.0:
        raise TransformRejected("limites de humanização inválidos")
    rng = random.Random(seed)
    out: list[dict] = []
    for n in notes:
        if not _selected(n, flt):
            out.append(n)
            continue
        m = dict(n)
        if timing_ticks:
            m["start"] = max(0, n["start"] + rng.randint(-int(timing_ticks), int(timing_ticks)))
        if velocity_amount:
            m["velocity"] = _clamp01(
                n["velocity"] * rng.uniform(1 - velocity_amount, 1 + velocity_amount)
            )
        out.append(m)
    return out


def transform_notes(
    notes: list[dict], transform: dict
) -> tuple[list[dict], list[str]]:
    """Aplica o spec na ordem fixa (transpor → quantizar → velocidade →
    humanizar) às notas selecionadas por `filter`. Devolve (notas, avisos).
    Notas não selecionadas ficam byte a byte."""
    validate_transform(transform)
    warnings: list[str] = []
    flt = transform.get("filter")
    current = list(notes)

    if "transpose" in transform:
        current = transpose(current, transform["transpose"], flt=flt)

    if "quantize" in transform:
        q = transform["quantize"]
        if q.get("strength", 1.0) < 1.0:
            warnings.append(
                f"quantização parcial (strength={q.get('strength')}) — "
                "posições podem não ficar exatamente na grelha"
            )
        current = quantize(
            current, grid_ticks=q["grid_ticks"], strength=q.get("strength", 1.0), flt=flt
        )

    if "velocity" in transform:
        v = transform["velocity"]
        current = adjust_velocity(
            current,
            delta=v.get("delta"),
            scale=v.get("scale"),
            target=v.get("target"),
            flt=flt,
        )
        warnings.append("velocity limitada a 0..1 onde necessário")

    if "humanize" in transform:
        h = transform["humanize"]
        current = humanize(
            current,
            seed=h["seed"],
            timing_ticks=h.get("timing_ticks", 0),
            velocity_amount=h.get("velocity_amount", 0.0),
            flt=flt,
        )
        warnings.append(
            f"humanização com semente {h['seed']} (reproduzível), limites "
            f"timing={h.get('timing_ticks', 0)} ticks, velocity=±{h.get('velocity_amount', 0.0)}"
        )

    return current, warnings


def displace(
    notes: list[dict],
    offset_ticks: int,
    *,
    flt: Optional[dict] = None,
) -> list[dict]:
    """Deslocamento rítmico (2C): move start das notas selecionadas por
    offset_ticks (positivo ou negativo). Saída negativa → rejeitar."""
    out: list[dict] = []
    for i, n in enumerate(notes):
        if not _selected(n, flt):
            out.append(n)
            continue
        new_start = n["start"] + offset_ticks
        if new_start < 0:
            raise TransformRejected(
                f"nota[{i}] (start={n['start']}) ficaria negativa com "
                f"offset {offset_ticks:+d} — recusado"
            )
        m = dict(n)
        m["start"] = new_start
        out.append(m)
    return out
