"""Demonstração da Fase 1 (observação) — não toca no LYNX.

Uso:
    python demo_phase1.py <project_id> <revision>

1. Analisa um groove sintético de bateria (4 compassos, com fill).
2. Propõe o mesmo groove como notas a adicionar ao Pattern 1 (vazio no LYNX).
3. Guarda a proposta na cache de sessão e valida a recarga:
   - recarga válida (mesma revisão);
   - recusa se a revisão mudou;
   - recusa se o conteúdo foi adulterado.
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .../agent

from lynx_agent.analysis import analyze_notes  # noqa: E402
from lynx_agent.proposals import (  # noqa: E402
    ProposalCache,
    ProposalStale,
    format_diff,
    new_proposal,
)

PPQ = 960
BAR = 4 * PPQ
SESSION = "demo-phase1"


def groove() -> list[dict]:
    """Four-on-the-floor + claps 2/4 + offbeat hats; fill de semicolcheias no fim."""
    notes = []
    for bar in range(4):
        for beat in range(4):
            notes.append(dict(key=36, start=bar * BAR + beat * PPQ, length=240, velocity=112, channel=0))
            if beat in (1, 3):
                notes.append(dict(key=39, start=bar * BAR + beat * PPQ, length=240, velocity=96, channel=1))
            notes.append(dict(key=42, start=bar * BAR + beat * PPQ + PPQ // 2, length=120, velocity=72, channel=2))
    for i in range(8):  # fill no compasso 4
        notes.append(dict(key=[38, 38, 41, 38, 39, 39, 41, 43][i], start=3 * BAR + i * 240, length=120,
                          velocity=88 + i * 4, channel=1))
    return notes


def main() -> None:
    project_id, revision = sys.argv[1], int(sys.argv[2])
    notes = groove()

    print("== analyze_midi ==")
    analysis = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR, bars=4)
    print(json.dumps(analysis, ensure_ascii=False, indent=1))

    print("== propose_midi_edit ==")
    proposal = new_proposal(
        session_id=SESSION,
        project_id=project_id,
        expected_revision=revision,
        target={
            "pattern_id": "0000010000000006",
            "channel_index": 0,
            "affected_instances": [],
            "range": {"start": 0, "end_exclusive": 4 * BAR},
        },
        operation="add_notes",
        before={"notes_in_range": []},
        after={"notes_in_range": notes},
        reason="Groove de bateria four-on-the-floor com fill de semicolcheias no compasso 4.",
        ppq=PPQ,
        warnings=analysis["warnings"],
    )
    cache = ProposalCache(SESSION)
    path = cache.save(proposal)
    print(f"guardada em {path}")
    print(format_diff(proposal))

    print("== validações de recarga ==")
    loaded = cache.load(proposal["proposal_id"], project_id=project_id, expected_revision=revision)
    assert loaded == proposal
    print("OK: recarga válida na mesma revisão")
    try:
        cache.load(proposal["proposal_id"], project_id=project_id, expected_revision=revision + 1)
    except ProposalStale as exc:
        print(f"OK: revisão mudada recusada -> {exc}")
    path.write_text(path.read_text(encoding="utf-8").replace('"velocity":112', '"velocity":1'), encoding="utf-8")
    try:
        cache.load(proposal["proposal_id"], project_id=project_id, expected_revision=revision)
    except Exception as exc:
        print(f"OK: conteúdo adulterado recusado -> {type(exc).__name__}: {exc}")
    path.unlink()
    print("cache limpa; o LYNX não foi tocado")


if __name__ == "__main__":
    main()
