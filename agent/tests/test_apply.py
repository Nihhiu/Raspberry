"""Testes da lógica de aplicação da 2A (apply.py) — pura, sem transporte."""

import unittest

from lynx_agent.apply import (
    ApplyRejected,
    check_prereqs,
    compute_new_notes,
    verify_applied,
)
from lynx_agent.proposals import ProposalStale, new_proposal


def native_note(**over):
    """Nota nativa completa (20 campos, auditoria docs/REMOTE_CONTROL.md)."""
    note = {
        "start": 0, "length": 240, "channel": 0, "key": 36, "velocity": 0.8,
        "pan": 0.0, "muted": False, "finePitch": 0.0, "slide": False, "porta": False,
        "release": 0.0, "modX": 0.0, "modY": 0.0, "colour": 0, "group": 0,
        "chance": 1.0, "velocityRange": 0.0, "chanceGroup": 0, "chanceOne": False,
        "expression": {"pitch": [], "timbre": [], "pressure": []},
    }
    note.update(over)
    return note


TARGET = {"pattern_index": 0, "channel_index": 0,
          "range": {"start": 0, "end_exclusive": 3840}}


def add_proposal(notes, revision=4, target=TARGET):
    return new_proposal(
        session_id="s1", project_id="p1", expected_revision=revision,
        target=target, operation="add_notes",
        before={"notes_in_range": []},
        after={"added_notes": notes},
        reason="teste", ppq=960,
    )


class TestCheckPrereqs(unittest.TestCase):
    def test_ok(self):
        p = add_proposal([native_note()])
        check_prereqs(p, project_id="p1", revision=4, playing=False, recording=False)

    def test_project_mismatch(self):
        p = add_proposal([native_note()])
        with self.assertRaises(ProposalStale):
            check_prereqs(p, project_id="p2", revision=4)

    def test_revision_mismatch(self):
        p = add_proposal([native_note()])
        with self.assertRaises(ProposalStale):
            check_prereqs(p, project_id="p1", revision=5)

    def test_playing_rejected(self):
        p = add_proposal([native_note()])
        with self.assertRaises(ApplyRejected):
            check_prereqs(p, project_id="p1", revision=4, playing=True)
        with self.assertRaises(ApplyRejected):
            check_prereqs(p, project_id="p1", revision=4, recording=True)


class TestValidateNote(unittest.TestCase):
    def test_missing_field_rejected(self):
        bad = native_note()
        del bad["chanceOne"]
        with self.assertRaises(ApplyRejected) as ctx:
            compute_new_notes(add_proposal([bad]), [])
        self.assertIn("chanceOne", str(ctx.exception))

    def test_expression_wrong_shape_rejected(self):
        bad = native_note(expression={"pitch": []})
        with self.assertRaises(ApplyRejected):
            compute_new_notes(add_proposal([bad]), [])

    def test_bad_key_rejected(self):
        with self.assertRaises(ApplyRejected):
            compute_new_notes(add_proposal([native_note(key=200)]), [])

    def test_zero_length_rejected(self):
        with self.assertRaises(ApplyRejected):
            compute_new_notes(add_proposal([native_note(length=0)]), [])

    def test_chance_out_of_range(self):
        with self.assertRaises(ApplyRejected):
            compute_new_notes(add_proposal([native_note(chance=1.5)]), [])


class TestComputeNewNotes(unittest.TestCase):
    def test_add_preserves_existing(self):
        existing = native_note(key=38, start=960)
        new = native_note(key=36, start=0)
        result = compute_new_notes(add_proposal([new]), [existing])
        self.assertEqual(len(result), 2)
        # a nota existente sai intacta — mesmo objeto, todos os atributos
        self.assertIn(existing, result)
        self.assertIn(new, result)

    def test_add_outside_range_rejected(self):
        with self.assertRaises(ApplyRejected) as ctx:
            compute_new_notes(add_proposal([native_note(start=3840)]), [])
        self.assertIn("fora do intervalo", str(ctx.exception))

    def test_replace_range_keeps_outside(self):
        inside = native_note(start=0)
        outside = native_note(start=4800, key=45)  # fora de [0, 3840)
        new_inside = native_note(key=42, start=100)
        prop = new_proposal(
            session_id="s1", project_id="p1", expected_revision=4,
            target=dict(TARGET), operation="replace_range",
            before={"notes_in_range": [inside]},
            after={"notes_in_range": [new_inside]},
            reason="teste", ppq=960,
        )
        result = compute_new_notes(prop, [inside, outside])
        self.assertEqual(result, [outside, new_inside])

    def test_replace_notes_must_be_in_range(self):
        prop = new_proposal(
            session_id="s1", project_id="p1", expected_revision=4,
            target=dict(TARGET), operation="replace_range",
            before={"notes_in_range": []},
            after={"notes_in_range": [native_note(start=9999)]},
            reason="teste", ppq=960,
        )
        with self.assertRaises(ApplyRejected):
            compute_new_notes(prop, [])

    def test_unsupported_operation(self):
        prop = add_proposal([native_note()])
        prop["operation"] = "transpose_all"
        with self.assertRaises(ApplyRejected):
            compute_new_notes(prop, [])

    def test_expression_preserved_byte_for_byte(self):
        curve = {"pitch": [[0, 100], [240, -50]], "timbre": [], "pressure": []}
        existing = native_note(expression=curve)
        result = compute_new_notes(add_proposal([native_note(start=960)]), [existing])
        self.assertEqual(result[0]["expression"], curve)  # MPE intacto


class TestVerifyApplied(unittest.TestCase):
    def test_exact_match(self):
        new = native_note(start=0)
        prop = add_proposal([new])
        ok, detail = verify_applied(prop, [], [new])
        self.assertTrue(ok, detail)

    def test_order_insensitive(self):
        a, b = native_note(start=0), native_note(start=960, key=38)
        prop = add_proposal([a, b])
        ok, _ = verify_applied(prop, [], [b, a])  # ordem física pode diferir
        self.assertTrue(ok)

    def test_mismatch_detected(self):
        a = native_note(start=0)
        prop = add_proposal([a])
        ok, detail = verify_applied(prop, [], [native_note(start=0, velocity=0.99)])
        self.assertFalse(ok)
        self.assertIn("divergente", detail)


if __name__ == "__main__":
    unittest.main()
