"""v4 fixes: no Maya sign-off, a real greeting, full forwards, useful handoff notes."""

from __future__ import annotations
from unittest import mock
import os

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402
from agents import forward, publictext  # noqa: E402
from agents.loop import _apply_signature, _hello  # noqa: E402

ZENDESK_SIG = "To your success,\nCustomer Service Team\nSuccess Resources UK Limited"

YUSUF = """Hi team, please see below.

Zina Miteva
Customer Service | Success Resources

---------- Forwarded message ---------
From: Yusuf İpek <mail@yusufipek.me>
Date: Fri, 23 Oct 2026 at 10:12
Subject: MMI Rome ticket
To: <info.uk@srglobal.com>

Hello,

I bought a Standard ticket for MMI Rome. I have a few questions:

1. How much does it cost to upgrade my Standard ticket to VIP?
2. If my visa is refused, can I get a refund?
3. Can I transfer my ticket to a later event instead?
4. Is there Turkish interpretation?

Best,
Yusuf İpek
"""


class SignoffTests(unittest.TestCase):
    def test_double_signature_is_stripped(self) -> None:
        text = "Hello Mahesh,\n\nThanks for waiting.\n\nWarm regards,\nMaya - your AI assistant\nSuccess Resources Support\n\n" + ZENDESK_SIG
        out = publictext.clean_public(text, "Hi Mahesh,")
        self.assertEqual(out, "Hi Mahesh,\n\nThanks for waiting.")

    def test_quinn_library_signoff_is_stripped(self) -> None:
        out = _apply_signature("Hello,\n\nHere are the dates.\n\nAll the best,\nEvelin", "quinn")
        self.assertNotIn("Evelin", out)
        self.assertTrue(out.endswith("Here are the dates."))

    @mock.patch.dict(os.environ, {"SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES": "false"})
    def test_quinn_answer_posted_by_maya_has_greeting_and_no_signoff(self) -> None:
        ctx = _ctx(requester_name="Maria Faustino")
        draft = _draft(agent="quinn", public_body="Here are the QL dates.\n\nWarm regards,\nQuinn\nSuccess Resources Support")
        _o, posted, _s = SolveRun()._run(ctx, draft)
        body = posted[0].public_body
        self.assertTrue(body.startswith("Hi Maria,\n\n"), body)
        self.assertNotIn("Warm regards", body)
        self.assertNotIn("Quinn", body)
        self.assertNotIn("Success Resources", body)


class GreetingTests(unittest.TestCase):
    def test_signed_name_wins(self) -> None:
        self.assertEqual(publictext.greeting("mahesh m", ["Any update?\n\nRegards\n\nMahesh Makkimane"]), "Hi Mahesh,")

    def test_company_and_handle_fall_back(self) -> None:
        self.assertEqual(publictext.greeting("Acme Trading Ltd"), "Hi there,")
        self.assertEqual(publictext.greeting("Roellamyecampos"), "Hi there,")
        self.assertEqual(publictext.greeting("Support Team"), "Hi there,")

    def test_two_word_name(self) -> None:
        self.assertEqual(_hello("Maria Faustino"), "Hi Maria,")

    def test_llm_greeting_with_account_name_is_replaced(self) -> None:
        out = publictext.clean_public("Dear Acme Trading Ltd,\n\nYour e-ticket is attached.", "Hello,")
        self.assertEqual(out, "Hello,\n\nYour e-ticket is attached.")


class HandoffNoteTests(unittest.TestCase):
    def test_note_never_says_needed_ok(self) -> None:
        d = flow.decide(
            agent="maya", lane="mmi", needs_human=True, matched="generated_needs_human",
            public_body="", note_body="", assignee_email="meda.c@srglobal.com", reason="ok",
            greeting="Hi Mahesh,", customer_text="I still can't access the recordings, the link does not work.",
            customer_name="Mahesh Makkimane", customer_email="m@example.com",
        )
        self.assertEqual(d.action, "handoff")
        self.assertNotIn("Needed: ok", d.internal_note)
        self.assertFalse(d.internal_note.startswith("Needed"))
        self.assertIn("What to check", d.internal_note)
        self.assertIn("m@example.com", d.internal_note)
        self.assertTrue(d.public_body.startswith("Hi Mahesh,\n\n"))
        self.assertNotIn("Warm regards", d.public_body)
        self.assertNotIn("Maya", d.public_body)

    def test_holding_reply_has_no_reasoning(self) -> None:
        d = flow.decide(
            agent="maya", lane="mmi", needs_human=True, matched="generated_needs_human",
            public_body="", note_body="KB has no price for upgrades, so a person must reply.",
            assignee_email="meda.c@srglobal.com", reason="no KB price", greeting="Hello,",
            customer_text="How much is VIP?", customer_name="", customer_email="x@example.com",
        )
        self.assertNotIn("KB", d.public_body)
        self.assertNotIn("a person must", d.public_body)


class ForwardTests(unittest.TestCase):
    def test_parse_keeps_customer_and_every_question(self) -> None:
        fwd = forward.parse(YUSUF)
        self.assertEqual(fwd.sender_email, "mail@yusufipek.me")
        self.assertIn("Yusuf", fwd.sender_name)
        self.assertEqual(len(fwd.questions), 4)
        note = forward.note(fwd, staff_email="info.uk@srglobal.com", subject="Fwd: MMI Rome ticket",
                            assignee="meda.c@srglobal.com", lane="mmi")
        for part in ("mail@yusufipek.me", "upgrade", "visa", "transfer", "Turkish", "Suggested:", "ccysEJGM"):
            self.assertIn(part, note)
        self.assertNotIn("Needed: ok", note)

    def test_app_forward_note_is_full_and_silent(self) -> None:
        ctx = _ctx(
            subject="Fwd: MMI Rome ticket",
            description=YUSUF,
            recipient="info.uk@srglobal.com",
            requester_email="info.uk@srglobal.com",
            requester_name="Zina Miteva",
            comments=[_comment("1", "10", YUSUF)],
        )

        def drafter(**_kw):
            raise AssertionError("forwards are not drafted publicly")

        outcome, posted, _s = SolveRun()._run(ctx, drafter, live=False)
        self.assertEqual(outcome["action"], "handoff")
        self.assertEqual(outcome["reply"], "")
        self.assertEqual(outcome["assignee"], "meda.c@srglobal.com")
        note = outcome["internal_note"]
        self.assertIn("mail@yusufipek.me", note)
        self.assertIn("4.", note)
        self.assertIn("Forwarded original", note)
        self.assertIn("Turkish interpretation", note)


import test_maya_flow as _tmf  # noqa: E402


class SolveRun:
    """Reuse the ProcessTests runner without collecting its tests twice."""

    def _run(self, ctx, draft, **kwargs):
        return _tmf.ProcessTests._run(self, ctx, draft, **kwargs)


if __name__ == "__main__":
    unittest.main()
