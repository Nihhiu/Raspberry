import json
import tempfile
import time
import unittest
from pathlib import Path

from lynx_agent.proposals import (
    ProposalCache,
    ProposalError,
    ProposalExpired,
    ProposalInvalid,
    ProposalNotFound,
    ProposalStale,
    canonical_json,
    content_hash,
    format_diff,
    new_proposal,
)

SESSION = "ses_test"
PROJECT = "c5b84af9133d8243e708c6c64ffc60d6"
REVISION = 4


def sample_proposal(**overrides):
    base = dict(
        session_id=SESSION,
        project_id=PROJECT,
        expected_revision=REVISION,
        target={
            "pattern_id": "0000010000000006",
            "channel_index": 0,
            "affected_instances": [],
            "range": {"start": 7680, "end_exclusive": 11520},
        },
        operation="add_notes",
        before={"notes_in_range": []},
        after={"added_notes": [{"key": 36, "start": 7680, "length": 240, "velocity": 100}]},
        reason="Adicionar um kick no terceiro compasso.",
        ppq=960,
    )
    base.update(overrides)
    return new_proposal(**base)


class TestProposalRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = ProposalCache(SESSION, root=Path(self.tmp.name))
        self.proposal = sample_proposal()

    def tearDown(self):
        self.tmp.cleanup()

    def test_id_and_hash(self):
        p2 = sample_proposal()
        self.assertNotEqual(self.proposal["proposal_id"], p2["proposal_id"])
        self.assertEqual(len(self.proposal["proposal_id"]), len("prop-") + 12)
        h = content_hash(self.proposal)
        self.assertEqual(h, content_hash(json.loads(canonical_json(self.proposal))))

    def test_load_valid(self):
        self.cache.save(self.proposal)
        loaded = self.cache.load(
            self.proposal["proposal_id"], project_id=PROJECT, expected_revision=REVISION
        )
        self.assertEqual(loaded, self.proposal)

    def test_not_found(self):
        with self.assertRaises(ProposalNotFound):
            self.cache.load("prop-deadbeefdead", project_id=PROJECT, expected_revision=REVISION)

    def test_tampered_content_rejected(self):
        path = self.cache.save(self.proposal)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["proposal"]["after"]["added_notes"][0]["velocity"] = 1
        path.write_text(canonical_json(envelope), encoding="utf-8")
        with self.assertRaises(ProposalInvalid):
            self.cache.load(
                self.proposal["proposal_id"], project_id=PROJECT, expected_revision=REVISION
            )

    def test_revision_change_invalidates(self):
        self.cache.save(self.proposal)
        with self.assertRaises(ProposalStale):
            self.cache.load(
                self.proposal["proposal_id"], project_id=PROJECT, expected_revision=REVISION + 1
            )

    def test_project_change_invalidates(self):
        self.cache.save(self.proposal)
        with self.assertRaises(ProposalStale):
            self.cache.load(self.proposal["proposal_id"], project_id="outro", expected_revision=REVISION)

    def test_expiry(self):
        self.cache.save(self.proposal, ttl_s=60)
        with self.assertRaises(ProposalExpired):
            self.cache.load(
                self.proposal["proposal_id"],
                project_id=PROJECT,
                expected_revision=REVISION,
                now=time.time() + 61,
            )

    def test_unknown_version_rejected(self):
        bad = sample_proposal()
        bad["proposal_version"] = 999
        with self.assertRaises(ProposalInvalid):
            self.cache.save(bad)

    def test_sessions_isolated(self):
        self.cache.save(self.proposal)
        other = ProposalCache("ses_other", root=Path(self.tmp.name))
        with self.assertRaises(ProposalStale):
            other.load(
                self.proposal["proposal_id"], project_id=PROJECT, expected_revision=REVISION
            )


class TestFormatDiff(unittest.TestCase):
    def test_diff_shows_before_after_and_scale(self):
        proposal = sample_proposal(
            before={"notes_in_range": [{"key": 38, "start": 7680, "length": 240, "velocity": 90}]},
            warnings=["sobreposição possível"],
        )
        proposal["target"]["affected_instances"] = ["clip-4", "clip-9"]
        text = format_diff(proposal)
        self.assertIn("prop-", text)
        self.assertIn("+ key=36", text)
        self.assertIn("clip-4, clip-9", text)
        self.assertIn("sobreposição possível", text)
        self.assertIn("conservadas", text)
        # add_notes NÃO remove nada: nota existente aparece como mantida.
        self.assertNotIn("- key=38", text)
        self.assertIn("1 mantidas, 1 adicionadas, 0 removidas", text)

    def test_diff_replace_range_shows_removals(self):
        proposal = sample_proposal(
            operation="replace_range",
            before={"notes_in_range": [{"key": 38, "start": 7680, "length": 240, "velocity": 90}]},
            after={"notes_in_range": [{"key": 36, "start": 7680, "length": 240, "velocity": 100}]},
        )
        text = format_diff(proposal)
        self.assertIn("- key=38", text)
        self.assertIn("0 mantidas, 1 adicionadas, 1 removidas", text)


if __name__ == "__main__":
    unittest.main()
