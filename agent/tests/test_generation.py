"""Testes da geração assistida (Fase 2C): templates de groove, fills."""

from __future__ import annotations

import unittest

from lynx_agent.apply import validate_note
from lynx_agent.generation import (
    BASS_TEMPLATES,
    DRUM_TEMPLATES,
    build_groove,
    make_fill,
    native_note,
)
from lynx_agent.transforms import TransformRejected


class TestNativeNote(unittest.TestCase):
    def test_full_native_note_passes_validation(self):
        validate_note(native_note(channel=2, key=36, start=960, length=240, velocity=0.8))

    def test_expression_has_exactly_three_lanes(self):
        n = native_note()
        self.assertEqual(set(n["expression"]), {"pitch", "timbre", "pressure"})


class TestBuildGroove(unittest.TestCase):
    def test_all_templates_produce_valid_notes(self):
        for name in DRUM_TEMPLATES:
            notes = build_groove(name, channel=2, ppq=960)
            self.assertGreater(len(notes), 0)
            for i, n in enumerate(notes):
                validate_note(n, index=i)

    def test_bass_templates(self):
        for name in BASS_TEMPLATES:
            notes = build_groove(name, channel=3, ppq=960, bass_key=33)
            for n in notes:
                self.assertEqual(n["key"], 33)
                validate_note(n)

    def test_deterministic_without_seed(self):
        a = build_groove("four_on_the_floor", channel=2, ppq=960)
        b = build_groove("four_on_the_floor", channel=2, ppq=960)
        self.assertEqual(a, b)

    def test_seeded_humanize_reproducible_and_bounded(self):
        a = build_groove(
            "boom_bap", channel=2, ppq=960, seed=99,
            humanize_timing_ticks=60, humanize_velocity_amount=0.1,
        )
        b = build_groove(
            "boom_bap", channel=2, ppq=960, seed=99,
            humanize_timing_ticks=60, humanize_velocity_amount=0.1,
        )
        self.assertEqual(a, b)
        plain = build_groove("boom_bap", channel=2, ppq=960)
        self.assertNotEqual(a, plain)

    def test_bars_extend_timeline(self):
        one = build_groove("four_on_the_floor", channel=2, ppq=960, bars=1)
        two = build_groove("four_on_the_floor", channel=2, ppq=960, bars=2, bar_start=3840)
        self.assertEqual(len(two), 2 * len(one))
        self.assertEqual(two[-1]["start"], 7680 + 14 * 240)  # último hat, passo 14

    def test_key_map_override(self):
        notes = build_groove(
            "four_on_the_floor", channel=2, ppq=960, key_map={"kick": 40}
        )
        kicks = [n for n in notes if n["key"] == 40]
        self.assertEqual(len(kicks), 4)

    def test_unknown_template(self):
        with self.assertRaises(TransformRejected):
            build_groove("nope", channel=0, ppq=960)

    def test_velocity_scale_clamped(self):
        notes = build_groove("four_on_the_floor", channel=2, ppq=960, velocity_scale=2.0)
        self.assertTrue(all(n["velocity"] <= 1.0 for n in notes))


class TestMakeFill(unittest.TestCase):
    def test_valid_notes_rising_velocity(self):
        notes = make_fill(channel=2, ppq=960, bar_start=2880)
        self.assertEqual(len(notes), 6)
        for n in notes:
            validate_note(n)
        vels = [n["velocity"] for n in notes]
        self.assertEqual(vels, sorted(vels))
        self.assertEqual(vels[-1], 1.0)

    def test_seeded_jitter_deterministic(self):
        a = make_fill(channel=2, ppq=960, bar_start=0, seed=5, jitter_velocity=0.1)
        b = make_fill(channel=2, ppq=960, bar_start=0, seed=5, jitter_velocity=0.1)
        self.assertEqual(a, b)

    def test_jitter_requires_seed(self):
        with self.assertRaises(TransformRejected):
            make_fill(channel=2, ppq=960, bar_start=0, jitter_velocity=0.1)

    def test_invalid_steps(self):
        with self.assertRaises(TransformRejected):
            make_fill(channel=2, ppq=960, bar_start=0, steps=(16,))


if __name__ == "__main__":
    unittest.main()
