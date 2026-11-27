"""Testes das transformações mecânicas (Fase 2B) e da operação transform_notes."""

from __future__ import annotations

import copy
import unittest

from lynx_agent.apply import ApplyRejected, compute_new_notes, verify_applied
from lynx_agent.transforms import (
    TransformRejected,
    adjust_velocity,
    displace,
    humanize,
    quantize,
    transpose,
    transform_notes,
    validate_transform,
)


def native_note(key=60, start=0, length=240, velocity=0.8, channel=0, **extra):
    n = {
        "start": start,
        "length": length,
        "channel": channel,
        "key": key,
        "velocity": velocity,
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
    n.update(extra)
    return n


class TestTranspose(unittest.TestCase):
    def test_transposes_selected_keys_only(self):
        notes = [native_note(key=60), native_note(key=36, start=960)]
        out = transpose(notes, 2, flt={"keys": [60]})
        self.assertEqual([n["key"] for n in out], [62, 36])

    def test_rejects_out_of_range_key(self):
        with self.assertRaises(TransformRejected):
            transpose([native_note(key=131)], 1)

    def test_preserves_other_attributes(self):
        n = native_note(key=60, velocity=0.7, pan=0.25)
        out = transpose([n], -12)
        self.assertEqual(out[0]["key"], 48)
        self.assertEqual(out[0]["velocity"], 0.7)
        self.assertEqual(out[0]["pan"], 0.25)
        self.assertEqual(out[0]["expression"], n["expression"])


class TestAdjustVelocity(unittest.TestCase):
    def test_delta_clamped(self):
        out = adjust_velocity([native_note(velocity=0.95)], delta=0.2)
        self.assertEqual(out[0]["velocity"], 1.0)

    def test_scale(self):
        out = adjust_velocity([native_note(velocity=0.5)], scale=1.2)
        self.assertAlmostEqual(out[0]["velocity"], 0.6)

    def test_target(self):
        out = adjust_velocity([native_note(velocity=0.5)], target=0.9)
        self.assertEqual(out[0]["velocity"], 0.9)

    def test_requires_exactly_one_mode(self):
        with self.assertRaises(TransformRejected):
            adjust_velocity([native_note()], delta=0.1, scale=2.0)


class TestQuantize(unittest.TestCase):
    def test_snaps_to_grid(self):
        out = quantize([native_note(start=970)], grid_ticks=240)
        self.assertEqual(out[0]["start"], 960)

    def test_strength_interpolates(self):
        out = quantize([native_note(start=970)], grid_ticks=240, strength=0.5)
        self.assertEqual(out[0]["start"], 965)

    def test_partial_strength_warns(self):
        _, warnings = transform_notes(
            [native_note(start=970)], {"quantize": {"grid_ticks": 240, "strength": 0.5}}
        )
        self.assertTrue(any("parcial" in w for w in warnings))

    def test_invalid_grid(self):
        with self.assertRaises(TransformRejected):
            quantize([native_note()], grid_ticks=0)


class TestHumanize(unittest.TestCase):
    def test_reproducible_same_seed(self):
        notes = [native_note(start=960 + i, velocity=0.8) for i in range(4)]
        a = humanize(copy.deepcopy(notes), seed=42, timing_ticks=30, velocity_amount=0.1)
        b = humanize(copy.deepcopy(notes), seed=42, timing_ticks=30, velocity_amount=0.1)
        self.assertEqual(a, b)

    def test_different_seed_differs(self):
        notes = [native_note(start=960 + i, velocity=0.8) for i in range(8)]
        a = humanize(copy.deepcopy(notes), seed=1, timing_ticks=60, velocity_amount=0.3)
        b = humanize(copy.deepcopy(notes), seed=2, timing_ticks=60, velocity_amount=0.3)
        self.assertNotEqual(a, b)

    def test_within_limits_and_non_negative(self):
        notes = [native_note(start=i, velocity=0.8) for i in range(20)]
        out = humanize(notes, seed=7, timing_ticks=100, velocity_amount=0.25)
        for n in out:
            self.assertGreaterEqual(n["start"], 0)
            self.assertTrue(0.0 <= n["velocity"] <= 1.0)
            self.assertLessEqual(abs(n["start"] - notes[0]["start"]), 101)

    def test_requires_limits(self):
        with self.assertRaises(TransformRejected):
            humanize([native_note()], seed=-1, timing_ticks=-5)


class TestValidateTransform(unittest.TestCase):
    def test_rejects_unknown_keys(self):
        with self.assertRaises(TransformRejected):
            validate_transform({"transpose": 1, "evil": True})

    def test_rejects_no_action(self):
        with self.assertRaises(TransformRejected):
            validate_transform({"filter": {"keys": [36]}})

    def test_humanize_requires_seed(self):
        with self.assertRaises(TransformRejected):
            validate_transform({"humanize": {"timing_ticks": 10}})

    def test_velocity_requires_exactly_one(self):
        with self.assertRaises(TransformRejected):
            validate_transform({"velocity": {"delta": 0.1, "target": 0.5}})

    def test_valid_spec_passes(self):
        validate_transform(
            {
                "transpose": -2,
                "quantize": {"grid_ticks": 240},
                "humanize": {"seed": 3, "timing_ticks": 20, "velocity_amount": 0.1},
                "filter": {"key_min": 36, "key_max": 42},
            }
        )


class TestTransformNotesOrder(unittest.TestCase):
    def test_fixed_order_humanize_after_quantize(self):
        # start fora da grelha + humanize timing: quantizar primeiro limita o
        # desvio final; com strength 1 e timing < metade da grelha, fica na grelha±timing.
        notes = [native_note(start=970)]
        out, _ = transform_notes(
            notes,
            {"quantize": {"grid_ticks": 240}, "humanize": {"seed": 1, "timing_ticks": 10}},
        )
        self.assertTrue(950 <= out[0]["start"] <= 970)


class TestTransformNotesOperation(unittest.TestCase):
    def test_compute_and_verify(self):
        before = [native_note(key=36, start=0), native_note(key=36, start=960)]
        proposal = {
            "operation": "transform_notes",
            "target": {"range": {"start": 0, "end_exclusive": 3840}},
            "after": {
                "transform": {"transpose": 2},
                "notes_in_range": [
                    native_note(key=38, start=0),
                    native_note(key=38, start=960),
                ],
            },
        }
        result = compute_new_notes(proposal, copy.deepcopy(before))
        self.assertEqual([n["key"] for n in result], [38, 38])
        ok, detail = verify_applied(proposal, before, result)
        self.assertTrue(ok, detail)

    def test_transform_requires_object(self):
        proposal = {
            "operation": "transform_notes",
            "target": {"range": {"start": 0, "end_exclusive": 10}},
            "after": {"transform": "x", "notes_in_range": []},
        }
        with self.assertRaises(ApplyRejected):
            compute_new_notes(proposal, [])


class TestDisplace(unittest.TestCase):
    def test_positive_and_negative(self):
        notes = [native_note(start=960)]
        self.assertEqual(displace(notes, 240)[0]["start"], 1200)
        self.assertEqual(displace(notes, -240)[0]["start"], 720)

    def test_rejects_negative_start(self):
        with self.assertRaises(TransformRejected):
            displace([native_note(start=10)], -240)


if __name__ == "__main__":
    unittest.main()
