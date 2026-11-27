"""Testes do portão de aprovação (approval.py) — token, uso único, hash."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from lynx_agent.approval import (
    ApprovalConsumed,
    ApprovalGate,
    ApprovalPending,
)
from lynx_agent.proposals import ProposalInvalid, ProposalStale, new_proposal


def make_proposal(revision=4):
    return new_proposal(
        session_id="s1", project_id="p1", expected_revision=revision,
        target={"pattern_index": 0, "range": {"start": 0, "end_exclusive": 3840}},
        operation="add_notes",
        before={"notes_in_range": []},
        after={"added_notes": [{"key": 36, "start": 0}]},
        reason="teste", ppq=960,
    )


class ApprovalTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gate = ApprovalGate("s1", root=Path(self.tmp.name) / "approvals")

    def tearDown(self):
        self.tmp.cleanup()


class TestRequestApproval(ApprovalTestBase):
    def test_approved_writes_token(self):
        p = make_proposal()
        path = self.gate.request_approval(p, "diff", confirm_fn=lambda pr, d: True)
        self.assertIsNotNone(path)
        token = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(token["proposal_id"], p["proposal_id"])
        self.assertEqual(token["project_id"], "p1")
        self.assertEqual(token["expected_revision"], 4)
        self.assertIn("nonce", token)

    def test_refused_no_token(self):
        self.assertIsNone(self.gate.request_approval(make_proposal(), "d",
                                                     confirm_fn=lambda pr, d: False))

    def test_second_request_pending(self):
        p = make_proposal()
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        with self.assertRaises(ApprovalPending):
            self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)


class TestConsume(ApprovalTestBase):
    def test_consume_valid_and_single_use(self):
        p = make_proposal()
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        token = self.gate.consume(p)
        self.assertEqual(token["proposal_id"], p["proposal_id"])
        with self.assertRaises(ApprovalConsumed):  # uso único
            self.gate.consume(p)

    def test_consume_without_approval(self):
        with self.assertRaises(ApprovalConsumed):
            self.gate.consume(make_proposal())

    def test_tampered_proposal_rejected(self):
        p = make_proposal()
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        p["after"]["added_notes"][0]["velocity"] = 1  # mudou após aprovação
        with self.assertRaises(ProposalInvalid):
            self.gate.consume(p)

    def test_revision_change_rejected(self):
        # mudar a revisão muda o conteúdo ⇒ o hash do token já não corresponde
        p = make_proposal(revision=4)
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        p2 = dict(p, expected_revision=5)
        with self.assertRaises(ProposalInvalid):
            self.gate.consume(p2)

    def test_revision_field_of_token_must_match(self):
        # token forjado/antigo com revisão diferente é recusado
        p = make_proposal(revision=4)
        path = self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        token = json.loads(path.read_text(encoding="utf-8"))
        token["expected_revision"] = 3
        path.write_text(json.dumps(token), encoding="utf-8")
        with self.assertRaises(ProposalStale):
            self.gate.consume(p)

    def test_other_session_rejected(self):
        p = make_proposal()
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        other = ApprovalGate("s2", root=Path(self.tmp.name) / "approvals")
        with self.assertRaises(ProposalStale):
            other.consume(p)

    def test_expired_rejected(self):
        p = make_proposal()
        self.gate.request_approval(p, "d", confirm_fn=lambda pr, d: True)
        future = time.time() + 10_000
        with self.assertRaises(ProposalInvalid):
            self.gate.consume(p, now=future)


if __name__ == "__main__":
    unittest.main()
