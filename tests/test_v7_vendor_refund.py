"""v7 fixes (Akram, 27 Oct 2026), from the live run of a7bb064.

Fixtures are anonymised versions of the real tickets (names, emails, phones and
order numbers removed or replaced).

- 104055, 103650, 104052: Hyros (via Intercom) got a public answer or holding reply.
- 102967: Digistore24 got a holding reply and an off-topic draft.
- 104296, 103567: money-back intent without the word "refund" got a holding reply.
- Quinn/Rafa no-public path never wrote ai_quinn / ai_rafa / ai_no_public_reply / ...
- 102958: Maya's note words fired the refund and MMI triggers.
- long_wait_apology must be off unless the webhook body sets it.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402
from test_v6_catchup import _run  # noqa: E402
from agents import notewords, routing  # noqa: E402

HYROS_EMAIL = "jo@hyros-0000aaaa.intercom-mail.com"
HYROS_NAME = "Jo from Hyros"
T104055 = (
    "![](https://downloads.intercomcdn.com/i/o/x/abc/image.png)\n\n"
    "Hi Sam,\n\nAll your organic links have our el parameters added. Am I correct?\n\n"
    "![Hyros](https://static.intercomassets.com/avatars/1/square_128/hyros.png)\n"
    "[Intercom](https://www.intercom.com/intercom-link)"
)
T103650 = (
    "Hi Sam,\n\nNo worries at all, I'm happy to check this for you. Could you please share a screenshot "
    "of your ad spend from March 11 to March 17? That way I can compare it with what we see in your account."
)
T104052 = (
    "I checked your account and can confirm that you are receiving traffic from Facebook organic. "
    "Your organic links include **el parameters** (for example www.hyros.com?el=tag), which is how we "
    "attribute traffic to the right source within Hyros."
)
DIGI_EMAIL = "support@digistore24.com"
DIGI_SUBJECT = "[Digistore24 GmbH] Re: Speed Wealth E Book"
T102967 = (
    "I am reaching out to the product provider, which is why they are cc'd.\n\n"
    "Dear Support Team,\n\nPlease review and respond to the customer inquiry associated with the order number "
    "XXXX. Please assist the customer in accessing your product.\n\nPlease provide your feedback within 2 days "
    "in this email thread.\n\nKind regards\nDigistore24 Support\n\nDigistore24 GmbH, St.-Godehard-Strasse 32, "
    "31139 Hildesheim"
)
T104296 = (
    "Hello,\n\nI can't participate in this event and please for sending back the payment cause I based in term "
    "less than 14 days in Poland like a customer.\n\nPozdrawiam serdecznie\nA."
)
S103567 = "Cancelation this order I updated with VIP ticket"
T103567 = (
    "### Hello,\n\ncould you, please, cancel this $19 order, it should not be charged because I updated with "
    "VIP ticket.\n\nThank you.\n\n### Order Summary\nOrder ID: XXXX\nAmount: One time $19\nPayment method: PayPal"
)
T102958 = "Hello,\n\nI will need the invoice / bill for the accountant.\n\nBest regards\nMaria\nAcme Consulting S.L."

LANE_TAGS = {"ai_generated", "ai_no_public_reply", "ai_draft_only"}


def _vendor_ctx(email, name, body, subject="Re: tracking", recipient="info.eu@srglobal.com"):
    return _ctx(
        subject=subject, description=body, tags=[], recipient=recipient, requester_email=email,
        requester_name=name, comments=[_comment("1", "10", body)],
    )


def _customer_ctx(body, subject="Ticket", name="Anna", email="anna@example.com", tags=None):
    return _ctx(subject=subject, description=body, tags=tags or [], requester_email=email,
                requester_name=name, comments=[_comment("1", "10", body)])


def _no_triggers(test, text):
    test.assertEqual(notewords.trigger_hits(text), [], text)


class VendorSenderTests(unittest.TestCase):
    """Fix 1: vendors and platforms get a Meda note, never a public reply."""

    def _assert_vendor_handoff(self, posted):
        self.assertEqual(len(posted), 1)
        d = posted[0]
        self.assertEqual((d.action, d.status, d.public_body), ("handoff", "open", ""))
        self.assertEqual(d.assignee_email, "meda.c@srglobal.com")
        self.assertIn("ai_business_enquiry", d.tags)
        self.assertIn("ai_no_public_reply", d.tags)
        self.assertIn("ai_vendor_sender", d.tags)
        self.assertNotIn(flow.TAG_ANSWERED, d.tags)
        self.assertIn("No public reply was sent.", d.internal_note)
        self.assertIn("not a customer", d.internal_note)
        _no_triggers(self, d.internal_note)
        return d

    def test_hyros_threads_go_to_meda_without_a_public_reply(self) -> None:
        for tid, body in (("104055", T104055), ("103650", T103650), ("104052", T104052)):
            with self.subTest(ticket=tid):
                # The drafter must not even be asked: a confident public answer was the 104055 bug.
                draft = _draft(public_body="Hi there,\n\nYes, that is correct.", needs_human=False)
                _o, posted, seen = _run(_vendor_ctx(HYROS_EMAIL, HYROS_NAME, body), draft)
                d = self._assert_vendor_handoff(posted)
                self.assertEqual(seen, {})
                self.assertIn("hyros", d.reason)
                self.assertNotIn("![", d.internal_note)

    def test_102967_digistore24_goes_to_meda_with_no_draft(self) -> None:
        draft = _draft(public_body="Hi Lea,\n\nI do not have a confirmed venue for Nice yet.", needs_human=True)
        ctx = _vendor_ctx(DIGI_EMAIL, "Support", T102967, subject=DIGI_SUBJECT, recipient="mmo@srglobal.com")
        _o, posted, _seen = _run(ctx, draft)
        d = self._assert_vendor_handoff(posted)
        self.assertEqual(d.assignee_email, "meda.c@srglobal.com")  # not Alina, even on mmo@
        self.assertNotIn("Nice", d.internal_note)
        self.assertNotIn("draft (not sent", d.internal_note)

    def test_detection_is_by_sender(self) -> None:
        self.assertEqual(routing.vendor_sender(HYROS_EMAIL, HYROS_NAME), "hyros")
        self.assertEqual(routing.vendor_sender("x@other-0000.intercom-mail.com", "Lee"), "other")
        self.assertEqual(routing.vendor_sender(DIGI_EMAIL, "Support", DIGI_SUBJECT), "digistore24")
        self.assertEqual(routing.vendor_sender("noreply@mail.paypal.de", "PayPal"), "paypal")
        self.assertEqual(routing.vendor_sender("", "Kim from Kajabi"), "kajabi")
        self.assertEqual(routing.vendor_sender("a@agency.example", "", DIGI_SUBJECT), "digistore24")
        # Generic B2B platform wording, any domain.
        self.assertEqual(routing.vendor_sender("ops@shop.example", "Ops", "Order", T102967), "b2b")

    def test_customers_who_mention_a_platform_are_not_vendors(self) -> None:
        for email, name, subject, text in (
            ("anna@gmail.com", "Anna", "Digistore24 order", "I paid via Digistore24, where is my e-book?"),
            ("li@example.com", "Li", "Hyros", "I saw Hyros on your slides, which tool is it?"),
            ("max@stripe-design.example", "Max", "Ticket", "When is the next event?"),
            ("ana@example.com", "Ana from Berlin", "Ticket", "Dear Support Team, where is my ticket?"),
            ("m@srglobalhelp.zendesk.com", "Maya", "Ticket", "hello"),
        ):
            with self.subTest(email=email):
                self.assertEqual(routing.vendor_sender(email, name, subject, text), "")

    def test_customer_mentioning_digistore24_still_gets_maya(self) -> None:
        body = "Hello,\n\nI bought the e-book through Digistore24. When is the next event in Berlin?"
        draft = _draft(public_body="Hi Anna,\n\nThe next event is on the events page.")
        _o, posted, seen = _run(_customer_ctx(body, subject="Digistore24 order"), draft)
        self.assertEqual(posted[0].action, "solve")
        self.assertNotIn("ai_vendor_sender", posted[0].tags)
        self.assertIn("description", seen)

    def test_pure_vendor_notifications_stay_silent(self) -> None:
        # Automated mail keeps the existing noise rules (silent close, no note).
        body = "Your weekly report is ready. View it in your dashboard."
        ctx = _vendor_ctx("no-reply@hyros.com", "HYROS", body, subject="Weekly report")
        ctx["tags"] = []
        with mock.patch.object(app.noise, "classify", return_value="noise_system_alert"):
            _o, posted, _seen = _run(ctx, _draft())
        self.assertEqual(posted[0].action, "solve_silent")


class RefundIntentTests(unittest.TestCase):
    """Fix 2: money-back intent without the word "refund" goes to Rafa, internal only."""

    def test_104296_and_103567_go_to_rafa_without_public_reply(self) -> None:
        for tid, subject, body in (("104296", "Ticket", T104296), ("103567", S103567, T103567)):
            with self.subTest(ticket=tid):
                draft = _draft(public_body="Hi Anna,\n\nThank you, the team will look at this.", needs_human=True)
                _o, posted, _seen = _run(_customer_ctx(body, subject=subject), draft)
                d = posted[0]
                self.assertEqual((d.action, d.agent, d.public_body, d.status), ("handoff", "rafa", "", "open"))
                self.assertTrue({"ai_rafa", *LANE_TAGS} <= set(d.tags), d.tags)
                self.assertIn("payments lane (Rafa)", d.internal_note)
                _no_triggers(self, d.internal_note.split("Rafa draft")[0])

    def test_refund_intent_phrases(self) -> None:
        for text in (
            T104296, T103567, "I want my money back", "Please stop charging my card", "don't charge me again",
            "I am within the 14-day cooling-off period", "I want to use the 14 days right to cancel",
            "I want to withdraw from the purchase", "right of withdrawal", "please cancel my subscription",
            "cancel the order, I was charged 497 EUR", "I filed a chargeback", "Please reimburse me",
            "I was charged twice", "ik wil mijn geld terug", "herroepingsrecht", "Ich will mein Geld zurück",
            "Bitte um Rückerstattung", "Ich widerrufe den Kauf", "Je demande un remboursement",
            "droit de rétractation", "Quiero un reembolso", "devolver el dinero",
        ):
            with self.subTest(text=text):
                self.assertTrue(routing.refund_ask(text))
                self.assertEqual(routing.owner(text), "rafa")

    def test_normal_booking_questions_are_not_swallowed(self) -> None:
        for text in (
            "When is the next MMI in Berlin?", "How do I pay for the VIP ticket?", "Can I pay in instalments?",
            "The event is in 14 days, where is my ticket?", "Can I cancel my ticket and transfer it to a friend?",
            "Will my card be charged in euros?", "I paid but got no confirmation email",
            "Can I bring a guest? I already paid for mine.", "I need to cancel my hotel. Is breakfast included?",
            "Is the payment page secure?", "Do I need to bring my booking confirmation?",
        ):
            with self.subTest(text=text):
                self.assertFalse(routing.refund_ask(text))
                self.assertEqual(routing.owner(text), "maya")


class LaneTagWriteTests(unittest.TestCase):
    """Fix 3: the internal-only path writes the lane tags via the tags endpoint."""

    def _apply(self, disposition):
        tag_calls, puts = [], []
        with mock.patch.object(app, "assign_open_for_human", return_value=True), \
                mock.patch.object(app, "_put_ticket_raw", side_effect=lambda tid, t: (puts.append(t) or (True, "ok"))), \
                mock.patch.object(app, "_add_tags", side_effect=lambda tid, tags: (tag_calls.append(list(tags)) or (True, "ok"))):
            out = app._apply_handoff("104296", disposition)
        return out, tag_calls, puts

    def test_rafa_and_quinn_tags_are_written(self) -> None:
        for agent, text in (("rafa", T104296), ("quinn", "When are the next Quantum Leap dates?")):
            with self.subTest(agent=agent):
                d = flow.decide(agent=agent, lane="mmi", needs_human=True, matched="generated", public_body="",
                                note_body="Hello,\n\nDraft text for the team.", assignee_email="", reason="ok",
                                customer_text=text)
                self.assertEqual(d.public_body, "")
                out, tag_calls, puts = self._apply(d)
                self.assertTrue(out["posted"])
                self.assertEqual(len(puts), 1)
                self.assertFalse(puts[0]["comment"]["public"])
                written = set(tag_calls[0])
                self.assertTrue({f"ai_{agent}", "ai_handoff_note", flow.TAG_ASSIGNED, *LANE_TAGS} <= written, written)

    def test_tags_written_even_without_a_note(self) -> None:
        d = flow.Disposition(action="handoff", agent="rafa", reason="x", public_body="", internal_note="",
                             status="open", assignee_email="meda.c@srglobal.com", lane="mmi",
                             tags=["ai_rafa", "ai_no_public_reply"])
        _out, tag_calls, _puts = self._apply(d)
        self.assertEqual(tag_calls, [["ai_rafa", "ai_no_public_reply"]])


class NoteWordingTests(unittest.TestCase):
    """Fix 4: Maya's own note wording never fires a Zendesk keyword trigger."""

    def test_102958_invoice_note_has_no_trigger_words_in_maya_wording(self) -> None:
        d = flow.decide(agent="rafa", lane="mmi", needs_human=True, matched="generated", public_body="",
                        note_body="", assignee_email="meda.c@srglobal.com", reason="ok",
                        customer_text="I will need the bill for the accountant.", customer_name="Maria")
        _no_triggers(self, d.internal_note)
        self.assertIn("Handoff to Meda, payments lane (Rafa).", d.internal_note)
        self.assertNotIn("(mmi lane)", d.internal_note)

    def test_templates_for_every_lane_are_clean(self) -> None:
        cases = [
            ("rafa", "ok", "please send my money back"), ("quinn", "ok", "programme dates"),
            ("maya", "transfer_handoff", "transfer"), ("maya", "booking_change", "I bought the wrong ticket"),
            ("maya", "masterclass_handoff", "replay"), ("maya", "gdpr_handoff", "delete my data"),
            ("maya", "refund language blocked", "x"), ("maya", "vendor or platform sender (hyros)", "x"),
            ("maya", "needs_human", "cancel the order, I paid 19 EUR"), ("maya", "resend confirmation", "x"),
        ]
        for agent, reason, text in cases:
            for lane in ("mmi", "mmo"):
                with self.subTest(agent=agent, reason=reason, lane=lane):
                    note = flow.handoff_note(lane=lane, assignee_email="", reason=reason, agent=agent,
                                             customer_text=text, public_sent=False)
                    _no_triggers(self, note)

    def test_customer_quote_is_summarised_with_neutral_words(self) -> None:
        text = "I want a refund / my money back for Quantum Leap and the MMI, or a chargeback."
        note = flow.handoff_note(lane="mmi", assignee_email="meda.c@srglobal.com", reason="ok", agent="rafa",
                                 customer_text=text, public_sent=False)
        _no_triggers(self, note)
        self.assertIn("repayment", note)

    def test_draft_keeps_the_customers_own_words_only(self) -> None:
        draft = "Hello,\n\nWe received your refund request for the Millionaire Mind Intensive. The team will reply."
        kept = flow.handoff_note(lane="mmi", assignee_email="", reason="ok", agent="rafa",
                                 customer_text="refund please", public_sent=False, draft=draft)
        self.assertIn("refund request", kept)  # Rafa's lane word, and the customer said it
        self.assertNotIn("Millionaire", kept)  # the customer did not, so no mmi tag
        maya = flow.handoff_note(lane="mmo", assignee_email="", reason="needs_human", agent="maya",
                                 customer_text="When is the next event?", public_sent=True,
                                 draft="Hello,\n\nThe next Millionaire Mind Intensive is in Rome.")
        _no_triggers(self, maya)

    def test_forward_suggestions_are_clean(self) -> None:
        ctx = _ctx(requester_email="zina@srglobal.com", requester_name="Zina", subject="Fwd: question",
                   comments=[_comment("1", "10", "Can she get a refund? Also she needs an invoice for MMI.")])
        _o, posted, _seen = _run(ctx, _draft())
        note = posted[0].internal_note
        # The staff message is quoted in full on purpose (that quote is essential); Maya's own
        # suggestions and wording must be clean.
        suggested = [line for line in note.splitlines() if "Suggested:" in line or line.startswith("Needed:")]
        self.assertTrue(suggested)
        for line in suggested:
            _no_triggers(self, line)
        self.assertIn("Repayments are a staff decision", note)


class LongWaitApologyTests(unittest.TestCase):
    """Fix 5: off unless the webhook body (or the env, when the body is silent) turns it on."""

    def test_absent_field_and_no_env_is_off(self) -> None:
        with mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": ""}):
            hints = app._hints_from_body({"ticket_id": "1"})
            self.assertIsNone(hints["long_wait_apology"])
            self.assertFalse(app._long_wait_apology(hints))
            _o, posted, _s = _run(_ctx(), _draft(), hints=hints)
        self.assertNotIn("ai_long_wait_apology", posted[0].tags)

    def test_explicit_false_beats_env(self) -> None:
        with mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": "true"}):
            for value in (False, "false", "0"):
                with self.subTest(value=value):
                    hints = app._hints_from_body({"ticket_id": "1", "long_wait_apology": value})
                    self.assertFalse(app._long_wait_apology(hints))

    def test_explicit_true_turns_it_on(self) -> None:
        with mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": ""}):
            hints = app._hints_from_body({"ticket_id": "1", "long_wait_apology": True})
            self.assertTrue(app._long_wait_apology(hints))

    def test_no_apology_on_internal_only_paths(self) -> None:
        _o, posted, _s = _run(_customer_ctx(T104296), _draft(needs_human=True), hints={"long_wait_apology": True})
        self.assertEqual(posted[0].public_body, "")
        self.assertNotIn("ai_long_wait_apology", posted[0].tags)


if __name__ == "__main__":
    unittest.main()
