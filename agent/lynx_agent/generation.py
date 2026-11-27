"""Geração assistida (Fase 2C) — templates de groove, fills e variações.

Puro e determinístico: mesmos parâmetros + mesma semente ⇒ mesmas notas.
Todas as notas geradas são NATIVAS completas (20 campos + repeat) e passam
por validate_note antes de entrar numa proposta. A geração produz o
"after" concreto de uma proposta add_notes/replace_range — o pipeline de
aprovação e aplicação 2A é reutilizado sem alterações.
"""

from __future__ import annotations

from typing import Optional

from .transforms import TransformRejected, humanize

# Mapeamento General MIDI por omissão; o chamador pode sobrepôr (ex.: XO
# no projeto real usa keys 36–42). Nomes de papéis são sugestões.
DEFAULT_KEY_MAP = {
    "kick": 36,
    "snare": 38,
    "clap": 39,
    "hat_closed": 42,
    "hat_open": 46,
    "bass": 36,  # raiz; o chamador deve indicar a tonalidade real
}

# Templates de bateria: passos em semicolcheias dentro de 1 compasso 4/4.
# (role, step, velocity, length_em_semicolcheias)
DRUM_TEMPLATES: dict[str, list[tuple[str, int, float, int]]] = {
    "four_on_the_floor": [
        ("kick", 0, 0.95, 1),
        ("kick", 4, 0.95, 1),
        ("kick", 8, 0.95, 1),
        ("kick", 12, 0.95, 1),
        ("clap", 4, 0.8, 1),
        ("clap", 12, 0.8, 1),
        ("hat_closed", 2, 0.55, 1),
        ("hat_closed", 6, 0.55, 1),
        ("hat_closed", 10, 0.55, 1),
        ("hat_closed", 14, 0.55, 1),
    ],
    "boom_bap": [
        ("kick", 0, 0.9, 1),
        ("kick", 10, 0.75, 1),
        ("snare", 4, 0.85, 1),
        ("snare", 12, 0.85, 1),
        ("hat_closed", 0, 0.5, 1),
        ("hat_closed", 2, 0.4, 1),
        ("hat_closed", 4, 0.5, 1),
        ("hat_closed", 6, 0.4, 1),
        ("hat_closed", 8, 0.5, 1),
        ("hat_closed", 10, 0.4, 1),
        ("hat_closed", 12, 0.5, 1),
        ("hat_closed", 14, 0.4, 1),
    ],
    "trap_half_time": [
        ("kick", 0, 0.95, 1),
        ("kick", 7, 0.7, 1),
        ("snare", 8, 0.85, 1),
        ("hat_closed", 0, 0.45, 1),
        ("hat_closed", 1, 0.3, 1),
        ("hat_closed", 2, 0.45, 1),
        ("hat_closed", 3, 0.3, 1),
        ("hat_closed", 4, 0.45, 1),
        ("hat_closed", 5, 0.3, 1),
        ("hat_closed", 6, 0.45, 1),
        ("hat_closed", 7, 0.3, 1),
        ("hat_closed", 8, 0.45, 1),
        ("hat_closed", 9, 0.3, 1),
        ("hat_closed", 10, 0.45, 1),
        ("hat_closed", 11, 0.3, 1),
        ("hat_closed", 12, 0.45, 1),
        ("hat_closed", 13, 0.3, 1),
        ("hat_closed", 14, 0.45, 1),
        ("hat_closed", 15, 0.3, 1),
    ],
}

# Templates de baixo: passos em semicolcheias, nota = raiz indicada.
BASS_TEMPLATES: dict[str, list[tuple[int, float, int]]] = {
    "bass_root_quarters": [
        (0, 0.85, 4),
        (4, 0.75, 4),
        (8, 0.85, 4),
        (12, 0.75, 4),
    ],
    "bass_root_8ths": [
        (s, 0.7 if s % 4 else 0.85, 2) for s in range(0, 16, 2)
    ],
}


def native_note(
    *,
    channel: int = 0,
    key: int = 60,
    start: int = 0,
    length: int = 240,
    velocity: float = 0.8,
) -> dict:
    """Nota nativa completa com valores neutros em tudo o que não é visado."""
    return {
        "start": int(start),
        "length": int(length),
        "channel": int(channel),
        "key": int(key),
        "velocity": float(velocity),
        "pan": 0,
        "muted": False,
        "finePitch": 0,
        "slide": False,
        "porta": False,
        "release": 0,
        "modX": 0,
        "modY": 0,
        "colour": 0,
        "group": 0,
        "chance": 1,
        "velocityRange": 0,
        "chanceGroup": 0,
        "chanceOne": True,
        "expression": {"pitch": [], "timbre": [], "pressure": []},
        "repeat": 0,
    }


def _step_ticks(ppq: int) -> float:
    """Semicolcheia em ticks (grelha de 16 passos por compasso 4/4)."""
    return ppq / 4


def build_groove(
    template: str,
    *,
    channel: int,
    ppq: int,
    bars: int = 1,
    bar_start: int = 0,
    key_map: Optional[dict[str, int]] = None,
    bass_key: Optional[int] = None,
    velocity_scale: float = 1.0,
    seed: Optional[int] = None,
    humanize_timing_ticks: float = 0,
    humanize_velocity_amount: float = 0.0,
) -> list[dict]:
    """Gera um groove a partir de um template de bateria ou baixo.

    Determinístico; se `seed` for dado, aplica humanização limitada e
    reproduzível (mesmo seed ⇒ mesma saída). bass_key sobrepõe a raiz do
    baixo (a tonalidade real é do produtor — nunca inferida com certeza).
    """
    keys = dict(DEFAULT_KEY_MAP)
    if key_map:
        keys.update(key_map)
    if bass_key is not None:
        keys["bass"] = int(bass_key)

    if template in DRUM_TEMPLATES:
        entries = DRUM_TEMPLATES[template]
        role_key = lambda role: keys[role]  # noqa: E731
    elif template in BASS_TEMPLATES:
        entries = [(s, v, ln) for (s, v, ln) in BASS_TEMPLATES[template]]
        role_key = None
    else:
        raise TransformRejected(
            f"template '{template}' desconhecido "
            f"(bateria: {sorted(DRUM_TEMPLATES)}; baixo: {sorted(BASS_TEMPLATES)})"
        )

    step = _step_ticks(ppq)
    notes: list[dict] = []
    for bar in range(bars):
        bar_offset = bar_start + bar * ppq * 4
        for entry in entries:
            if role_key is not None:
                role, s, vel, ln = entry
                key = role_key(role)
            else:
                s, vel, ln = entry
                key = keys["bass"]
            notes.append(
                native_note(
                    channel=channel,
                    key=key,
                    start=int(round(bar_offset + s * step)),
                    length=int(round(ln * step)),
                    velocity=max(0.0, min(1.0, vel * velocity_scale)),
                )
            )

    if seed is not None and (humanize_timing_ticks or humanize_velocity_amount):
        notes = humanize(
            notes,
            seed=seed,
            timing_ticks=humanize_timing_ticks,
            velocity_amount=humanize_velocity_amount,
        )
    return notes


def make_fill(
    *,
    channel: int,
    ppq: int,
    bar_start: int,
    key: int = DEFAULT_KEY_MAP["snare"],
    steps: tuple[int, ...] = (8, 10, 12, 13, 14, 15),
    base_velocity: float = 0.6,
    peak_velocity: float = 1.0,
    seed: Optional[int] = None,
    jitter_velocity: float = 0.0,
) -> list[dict]:
    """Fill de bateria num compasso: semicolcheias selecionadas com rampa
    de velocity ascendente. Com seed, jitter determinístico nos acentos."""
    import random

    if not steps or not all(isinstance(s, int) and 0 <= s <= 15 for s in steps):
        raise TransformRejected("fill.steps deve ser passos de semicolcheia 0..15")
    if not 0.0 <= base_velocity <= 1.0 or not 0.0 <= peak_velocity <= 1.0:
        raise TransformRejected("fill: velocities fora de 0..1")
    if jitter_velocity and seed is None:
        raise TransformRejected("fill: jitter exige seed (reprodutibilidade)")

    rng = random.Random(seed) if seed is not None else None
    step = _step_ticks(ppq)
    ordered = sorted(steps)
    notes: list[dict] = []
    for i, s in enumerate(ordered):
        frac = i / (len(ordered) - 1) if len(ordered) > 1 else 1.0
        vel = base_velocity + (peak_velocity - base_velocity) * frac
        if rng is not None and jitter_velocity:
            vel *= 1 + rng.uniform(-jitter_velocity, jitter_velocity)
        notes.append(
            native_note(
                channel=channel,
                key=key,
                start=int(round(bar_start + s * step)),
                length=max(1, int(round(step))),
                velocity=min(1.0, max(0.0, vel)),
            )
        )
    return notes
