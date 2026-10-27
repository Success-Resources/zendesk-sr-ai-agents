"""v5: v4 live-test failures (#110401 reasoning posted, #110357 refund read as access, Marina greeting)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import flow  # noqa: E402
from agents import guardrails, publictext  # noqa: E402

Q110401 = (
    "Hello,\n\nCustomer (Diamond Dream Team / Marina Mursic) purchased Quantum Leap but will not attend TTT, EWC, "
    "or NWA and wants to transfer those three tickets to someone else. This is a standard transfer/name change "
    "request. Per hub policy, send https://sr-event.typeform.com/to/ccysEJGM and note one form is needed per ticket. "
    "No order number is required. This does not involve a refund, so it can be resolved directly without further "
    "verification. Needed: Maya to reply with the transfer typeform link."
)
R110357 = (
    "Despite enabling the Spanish translation option in Zoom, the subtitles continued to appear in English, and I "
    "was unable to access the content in Spanish. For these reasons, I would kindly like to request a full refund."
)


class V5Tests(unittest.TestCase):
    def test_third_person_reasoning_is_never_public(self) -> None:
        self.assertTrue(flow.public_is_unsafe(Q110401))
        d = flow.decide(
            agent="quinn", lane="mmi", needs_human=False, matched="generated", public_body=Q110401,
            note_body="", assignee_email="meda.c@srglobal.com", reason="ok", greeting="Hi Marina,",
            customer_text="can I sell these 3 tickets?", customer_name="Marina Mursic", customer_email="d@example.com",
        )
        self.assertNotIn("Customer (", d.public_body)
        self.assertNotIn("hub policy", d.public_body)
        self.assertNotEqual(d.action, "solve")

    def test_guardrail_blocks_reasoning(self) -> None:
        self.assertTrue(guardrails._META.search(Q110401))

    def test_normal_reply_is_not_flagged(self) -> None:
        ok = ("Hi Marina,\n\nYes, you can transfer each ticket to someone else. Please use this form, one per ticket: "
              "https://sr-event.typeform.com/to/ccysEJGM. You do not need an order number.")
        self.assertFalse(flow.public_is_unsafe(ok))
        self.assertFalse(guardrails._META.search(ok))

    def test_refund_with_access_words_is_not_an_access_issue(self) -> None:
        self.assertFalse(flow.is_access_issue(R110357))
        self.assertNotIn("working link", flow.holding_reply("Hi Raquel,", R110357))
        needed, _check = flow._needed_for("ok", "rafa", R110357)
        self.assertIn("payment request", needed)  # v7: the note avoids the "refund" trigger word
        self.assertTrue(flow.is_access_issue("I cannot log in to the replay, the link does not work."))

    def test_markdown_signature_name(self) -> None:
        text = "can I sell this 3 tickets? Thank you\n\n_Best Regards,_\n**_Marina Mursic_**\n_Helping People_"
        self.assertEqual(publictext.greeting("Diamond Dream Team", [text]), "Hi Marina,")


if __name__ == "__main__":
    unittest.main()
