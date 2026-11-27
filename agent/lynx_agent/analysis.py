"""Analisador musical estrutural (Fase 1).

Avalia apenas estrutura: densidade, extensão, repetição, ritmo, acentos,
sobreposições e notas fora de escala (quando há hipótese de tonalidade).
Não infere qualidade nem tonalidade com certeza — o produtor ouve e decide.

Notas: dicts no formato nativo do LYNX (960 PPQ, ticks relativos ao início
do pattern). Campos mínimos usados: start, length, key, velocity, channel.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Optional

MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 0.59, 0.62, 3.07, 0.39, 2.75, 3.98]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.94, 3.98, 2.07, 3.32, 2.68]
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

DEFAULT_MAX_WARNINGS = 16


def _sorted_notes(notes: Iterable[dict]) -> list[dict]:
    return sorted(notes, key=lambda n: (n.get("start", 0), n.get("key", 0)))


def detect_key_hypothesis(notes: list[dict]) -> Optional[dict]:
    """Hipótese de tonalidade por histograma de pitch-classes (Krumhansl).

    Devolve {"tonic": "A", "mode": "minor", "confidence": 0.0..1.0} ou None
    se não houver dados suficientes. É SEMPRE uma hipótese, nunca um facto.
    """
    pcs = [0] * 12
    for n in notes:
        key = n.get("key")
        if isinstance(key, int) and 0 <= key <= 127:
            pcs[key % 12] += 1
    total = sum(pcs)
    if total < 8:  # dados insuficientes
        return None
    best: Optional[tuple[float, int, str]] = None
    for tonic in range(12):
        rotated = pcs[tonic:] + pcs[:tonic]
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            corr = _pearson(rotated, profile)
            if corr is None:
                continue
            if best is None or corr > best[0]:
                best = (corr, tonic, mode)
    if best is None or best[0] <= 0:
        return None
    corr, tonic, mode = best
    second = -2.0
    for t in range(12):
        rotated = pcs[t:] + pcs[:t]
        for profile in (MAJOR_PROFILE, MINOR_PROFILE):
            c = _pearson(rotated, profile)
            if c is not None and c < corr and c > second:
                second = c
    confidence = max(0.0, min(1.0, corr - max(second, 0.0)))
    return {
        "tonic": PITCH_NAMES[tonic],
        "mode": mode,
        "confidence": round(confidence, 3),
    }


def _pearson(xs: list[int], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n != len(ys) or n == 0:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def analyze_notes(
    notes: Iterable[dict],
    *,
    ppq: int,
    bar_ticks: int,
    bars: Optional[int] = None,
    key: Optional[str] = None,
) -> dict:
    """Análise estrutural de um trecho (pattern-relative ticks).

    key: tonalidade fornecida pelo produtor (ex.: "A minor") — tem prioridade
    sobre a deteção automática (que é apenas hipótese).
    bars: nº de compassos do trecho; se dado, avalia densidade contra o total.
    """
    notes = _sorted_notes(notes)
    warnings: list[str] = []
    result: dict[str, Any] = {"note_count": len(notes)}

    if not notes:
        result["warnings"] = ["pattern vazio — não é necessariamente um erro"]
        return result

    # Extensão temporal e densidade por compasso
    first_start = notes[0]["start"]
    last_end = max(n["start"] + n.get("length", 0) for n in notes)
    result["span"] = {"start": first_start, "end": last_end, "ticks": last_end - first_start}
    total_bars = bars if bars is not None else (last_end + bar_ticks - 1) // bar_ticks
    density = [0] * max(total_bars, 1)
    for n in notes:
        density[min(n["start"] // bar_ticks, len(density) - 1)] += 1
    result["density_per_bar"] = density
    result["density"] = {
        "per_bar": density,
        "mean": round(len(notes) / len(density), 2),
    }
    if density and max(density) >= 4 * max(len(notes) / len(density), 1):
        warnings.append("densidade muito irregular entre compassos")

    # Extensão tonal
    keys = [n["key"] for n in notes if isinstance(n.get("key"), int)]
    if keys:
        result["pitch"] = {
            "min": min(keys),
            "max": max(keys),
            "extension": max(keys) - min(keys),
            "mean": round(statistics.fmean(keys), 1),
        }
        if max(keys) - min(keys) > 36:
            warnings.append("extensão tonal muito larga (>3 oitavas)")

    # Ritmo: alinhamento à grelha de semicolcheias (derivado, nunca fonte de verdade)
    grid = ppq // 4
    off_grid = [n for n in notes if n["start"] % grid != 0]
    eighth = ppq // 2
    on_eighth_or_stronger = sum(1 for n in notes if n["start"] % eighth == 0)
    result["rhythm"] = {
        "grid_ticks": grid,
        "off_grid_count": len(off_grid),
        "off_grid_ratio": round(len(off_grid) / len(notes), 3),
        "syncopation_ratio": round(1 - on_eighth_or_stronger / len(notes), 3),
    }
    if len(off_grid) / len(notes) > 0.5:
        warnings.append("maioria das notas fora da grelha de semicolcheias")

    # Acentos
    velocities = [n.get("velocity", 100) for n in notes]
    mean_vel = statistics.fmean(velocities)
    accents = [
        {"key": n["key"], "start": n["start"]}
        for n in notes
        if n.get("velocity", 100) >= mean_vel * 1.2
    ]
    result["accents"] = {"mean_velocity": round(mean_vel, 1), "count": len(accents)}

    # Sobreposições na mesma altura (podem ser intencionais — apenas avisar)
    overlaps = []
    by_key: dict[int, list[dict]] = {}
    for n in notes:
        by_key.setdefault(n["key"], []).append(n)
    for k, group in by_key.items():
        group.sort(key=lambda n: n["start"])
        for prev, cur in zip(group, group[1:]):
            if prev["start"] + prev.get("length", 0) > cur["start"]:
                overlaps.append({"key": k, "first_start": prev["start"], "second_start": cur["start"]})
    result["overlaps"] = {"count": len(overlaps)}
    if overlaps:
        warnings.append(
            f"{len(overlaps)} sobreposição(ões) na mesma altura — pode ser intencional (sustain/slide)"
        )

    # Repetição: assinaturas por compasso (pitch+rítmo e só rítmo)
    def bar_signature(n: dict) -> tuple:
        return (n["key"], n["start"] % bar_ticks, n.get("length", 0))

    sigs: dict[int, list] = {}
    for n in notes:
        sigs.setdefault(int(n["start"] // bar_ticks), []).append(bar_signature(n))
    sigs = {b: sorted(v) for b, v in sigs.items()}
    seen: dict[tuple, int] = {}
    repeated: list[dict] = []
    for bar in sorted(sigs):
        sig = tuple(sigs[bar])
        if not sig:
            continue
        if sig in seen:
            repeated.append({"bars": [seen[sig], bar], "kind": "pitch+rhythm"})
        else:
            seen[sig] = bar
    rhythm_seen: dict[tuple, int] = {}
    for bar in sorted(sigs):
        sig = tuple((s[1], s[2]) for s in sigs[bar])
        if not sig:
            continue
        if sig in rhythm_seen and rhythm_seen[sig] != bar:
            repeated.append({"bars": [rhythm_seen[sig], bar], "kind": "rhythm-only"})
        else:
            rhythm_seen[sig] = bar
    result["repetition"] = {"repeated_bars": repeated}

    # Tonalidade: hipótese ou valor fornecido
    if key:
        result["key_assumed"] = key
        result["out_of_scale"] = _out_of_scale(notes, key)
        if result["out_of_scale"]["count"]:
            warnings.append(
                f"{result['out_of_scale']['count']} nota(s) fora da escala assumida ({key})"
            )
    else:
        hypothesis = detect_key_hypothesis(notes)
        if hypothesis:
            result["key_hypothesis"] = hypothesis
            result["out_of_scale"] = _out_of_scale(
                notes, f"{hypothesis['tonic']} {hypothesis['mode']}"
            )

    if bars is not None and len(notes) / bars < 1:
        warnings.append("densidade muito baixa para o trecho")

    result["warnings"] = warnings[:DEFAULT_MAX_WARNINGS]
    return result


def _out_of_scale(notes: list[dict], key: str) -> dict:
    pcs = _scale_pitch_classes(key)
    if pcs is None:
        return {"count": 0, "known": False}
    out = sorted({n["key"] for n in notes if isinstance(n.get("key"), int) and n["key"] % 12 not in pcs})
    return {"count": len(out), "known": True, "keys": out}


def _scale_pitch_classes(key: str) -> Optional[set[int]]:
    """Interpreta 'A minor', 'C# major', 'F#m'... Devolve pitch-classes ou None."""
    text = key.strip()
    tonic = text[:2] if text[1:2] in ("#", "b") else text[:1]
    tonic = tonic.replace("b", "#")  # apenas sustenidos no mapa
    if tonic not in PITCH_NAMES:
        return None
    base = PITCH_NAMES.index(tonic)
    rest = text[len(tonic):].strip().lower()
    if rest in ("m", "min", "minor"):
        steps = (0, 2, 3, 5, 7, 8, 10)
    elif rest in ("", "maj", "major"):
        steps = (0, 2, 4, 5, 7, 9, 11)
    else:
        return None
    return {(base + s) % 12 for s in steps}
