"""v5 routing (Akram, 26 Oct), built from the v4 live tickets 110401, 110357 and 109655.

- QL family (Quantum Leap, TTT, EWC, NWA): Quinn drafts an internal note; open; lane human.
- Refund (even mixed with access/translation wording): Rafa drafts; open; lane human; no link promise.
- Ticket-type correction / swap / upgrade / booking change: handoff to a person; open; no transfer form.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import flow  # noqa: E402
from knowledge import route_agent  # noqa: E402
from agents import loop, routing  # noqa: E402

TYPEFORM = "typeform.com"

T110401 = (
    "I have a question, I purchased Quantum leap but I wont attend TTT, the Enlightened warrior and NWA so my "
    "question is can I sell this 3 tickets to someone else who would like to go? Thank you\n\n_Best Regards,_\n\n"
    "**_Marina Mursic_**\n\n_Helping People to Reach Their Dreams_"
)
Q110401_DRAFT = (
    "Hi Marina,\n\nYes, each ticket can be transferred to someone else. Please use this form once per ticket: "
    "https://sr-event.typeform.com/to/ccysEJGM. You do not need an order number."
)
T110357 = (
    "Dear Support Team,\n\nI recently purchased a course under the understanding that Spanish translation would be "
    "available through Zoom, as indicated in the ticket information.\n\nHowever, despite enabling the Spanish "
    "translation option in Zoom, the subtitles continued to appear in English, and I was unable to access the "
    "content in Spanish.\n\nFor these reasons, I would kindly like to request a full refund of the amount paid for "
    "the course.\n\nPlease let me know what information or documentation you require to process the refund to my "
    "original payment card.\n\nBest regards,\n\nRaquel Benítez"
)
T109655 = (
    "Dear sirs,\nin the month of August I bought two tickets for MMI for myself and my daughter, plus one extra "
    "ticket, which I used to invite my son.\n\nOnly today, while I was looking for the tickets in my mail box, I "
    "realized, that I had mistakenly bought 2 wrong tickets. This is how it is understood from further "
    "notifications.\n\nSince the price is the same, would you be so kind to change the tickets, so that they are "
    "valid for 2 + 1 person? It was an error during registration and I would really appreciate a correction if "
    "possible.\n\nI thank you in advance. We are really looking forward to attent this event.\n\nAna Fakin"
)
M109655_FORM = (
    "Hi Ana,\n\nTo correct the ticket details, please use this form, one submission per ticket: "
    "https://sr-event.typeform.com/to/ccysEJGM\n\nYou do not need an order number."
)


def _decide(agent, lane, public, text, name, email, assignee, note=""):
    return flow.decide(
        agent=agent, lane=lane, needs_human=False, matched="generated", public_body=public, note_body=note,
        assignee_email=assignee, reason="ok", greeting=f"Hi {name.split()[0]},", customer_text=text,
        customer_name=name, customer_email=email,
    )


class RoutingTests(unittest.TestCase):
    def test_router(self) -> None:
        self.assertEqual(route_agent("", "Quantum Leap", T110401), "quinn")
        self.assertEqual(route_agent("", "Assist Me On Millionaire Mind Hybrid", T110357), "rafa")
        self.assertEqual(route_agent("", "Fwd: error with the purchase", T109655), "maya")
        self.assertEqual(route_agent("", "TTT", "When is the next Train the Trainer?"), "quinn")
        self.assertEqual(route_agent("", "EWC", "Is the EWC online?"), "quinn")
        self.assertEqual(route_agent("", "Payment", "Can I get reimbursed for my ticket?"), "rafa")
        self.assertEqual(route_agent("", "Venue", "Where is the MMI Rome venue?"), "maya")

    def test_booking_change_detection(self) -> None:
        self.assertTrue(routing.booking_change(T109655))
        self.assertTrue(routing.booking_change("Can I upgrade my ticket to VIP?"))
        self.assertTrue(routing.booking_change("Please swap my tickets for the Sunday ones"))
        self.assertFalse(routing.booking_change("Can I change the name on the ticket to my husband?"))
        self.assertFalse(routing.booking_change("What ticket types are there for MMI Rome?"))
        self.assertFalse(routing.booking_change(T110357))


class DecideTests(unittest.TestCase):
    def test_110401_ql_family_goes_to_quinn_internal_only(self) -> None:
        d = _decide("quinn", "mmi", Q110401_DRAFT, T110401, "Marina Mursic", "d@example.com", "meda.c@srglobal.com")
        self.assertEqual(d.action, "handoff")
        self.assertEqual(d.status, "open")
        self.assertEqual(d.assignee_email, "meda.c@srglobal.com")
        self.assertNotIn(TYPEFORM, d.public_body)
        self.assertTrue(d.public_body.startswith("Hi Marina,"))
        self.assertIn("Quinn draft (not sent to the customer)", d.internal_note)
        self.assertIn(TYPEFORM, d.internal_note)
        self.assertIn("Needed: review Quinn's draft", d.internal_note)
        self.assertNotIn("Needed: ok", d.internal_note)

    def test_110401_even_if_maya_drafted_it(self) -> None:
        d = _decide("maya", "mmi", Q110401_DRAFT, T110401, "Marina Mursic", "d@example.com", "meda.c@srglobal.com")
        self.assertEqual(d.action, "handoff")
        self.assertNotIn(TYPEFORM, d.public_body)

    def test_ql_on_mmo_goes_to_alina(self) -> None:
        d = _decide("quinn", "mmo", "Hi Jo,\n\nQL dates are on the sheet.", "When is Quantum Leap?", "Jo Bloggs",
                    "j@example.com", "alina.last@srglobal.com")
        self.assertEqual((d.action, d.status, d.assignee_email), ("handoff", "open", "alina.last@srglobal.com"))

    def test_110357_refund_goes_to_rafa_no_link_promise(self) -> None:
        d = _decide("rafa", "mmo", "Hi Raquel,\n\nWe will refund you.", T110357, "Raquel Benítez",
                    "raquelbeni0977@gmail.com", "alina.last@srglobal.com",
                    note="Refund analysis: confirm event, purchase date, 14-day window; route to Finance.")
        self.assertEqual((d.action, d.status, d.assignee_email), ("handoff", "open", "alina.last@srglobal.com"))
        self.assertTrue(d.public_body.startswith("Hi Raquel,"))
        self.assertNotIn("link", d.public_body.lower())
        self.assertNotIn("access", d.public_body.lower())
        self.assertNotIn("refund", d.public_body.lower())
        self.assertIn("Rafa draft", d.internal_note)
        self.assertIn("Needed: review the refund", d.internal_note)
        self.assertNotIn("working link", d.internal_note)

    def test_refund_on_mmi_goes_to_meda_even_if_maya_drafted(self) -> None:
        d = _decide("maya", "mmi", "Hi Raquel,\n\nThank you.", T110357, "Raquel Benítez", "r@example.com",
                    "meda.c@srglobal.com")
        self.assertEqual((d.action, d.assignee_email), ("handoff", "meda.c@srglobal.com"))
        self.assertNotIn("link", d.public_body.lower())

    def test_109655_booking_change_to_meda_no_form(self) -> None:
        d = _decide("maya", "mmi", M109655_FORM, T109655, "Ana Fakin", "ana.fakin.af@gmail.com", "meda.c@srglobal.com")
        self.assertEqual((d.action, d.status, d.assignee_email), ("handoff", "open", "meda.c@srglobal.com"))
        self.assertTrue(d.public_body.startswith("Hi Ana,"))
        self.assertNotIn(TYPEFORM, d.public_body)
        self.assertIn("Needed: correct the ticket type or booking", d.internal_note)
        self.assertIn("ana.fakin.af@gmail.com", d.internal_note)

    def test_plain_kb_question_is_still_solved(self) -> None:
        reply = "Hi Tom,\n\nMMI Rome is at the Rome Marriott Park Hotel. Doors open at 8:00."
        d = _decide("maya", "mmi", reply, "Where is the MMI Rome venue and what time does it start?", "Tom Smith",
                    "t@example.com", "meda.c@srglobal.com")
        self.assertEqual((d.action, d.status), ("solve", "solved"))
        self.assertEqual(d.public_body, reply)

    def test_name_change_still_gets_the_form(self) -> None:
        reply = "Hi Tom,\n\nPlease use this form for the name change, one per ticket: https://sr-event.typeform.com/to/ccysEJGM"
        d = _decide("maya", "mmi", reply, "Can I change the name on my MMI ticket to my wife?", "Tom Smith",
                    "t@example.com", "meda.c@srglobal.com")
        self.assertEqual(d.action, "solve")
        self.assertIn(TYPEFORM, d.public_body)


class MayaCorrectionTests(unittest.TestCase):
    def test_109655_correction_never_sends_the_form(self) -> None:
        email, needs, reason = loop._correct_maya(
            M109655_FORM, False, "ok", "Fwd: error with the purchase", T109655, "Ana Fakin", ""
        )
        self.assertTrue(needs)
        self.assertEqual(reason, "booking_change")
        self.assertNotIn(TYPEFORM, email)


if __name__ == "__main__":
    unittest.main()
