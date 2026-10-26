"""Regression cases from the 26 Oct 2026 Maya update spec."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

import flow  # noqa: E402
import noise  # noqa: E402
from agents.loop import _CLAIM, _hello  # noqa: E402
from knowledge import route_agent  # noqa: E402


class RoutingTests(unittest.TestCase):
    def test_route_agent_word_boundaries(self) -> None:
        private = "I would like private sessions and a VIP Q&A."
        self.assertEqual(route_agent("refund_request finance_related", "VIP Q&A", private), "maya")
        quoted = (
            "Can you tell me the VIP benefits?\n\n"
            "On 1 Oct 2026 Maya wrote:\n"
            "Please see the refund policy and VAT No in the footer."
        )
        self.assertEqual(route_agent("refund_request invoice_request", "Question", quoted), "maya")
        signature = "Please send the recording.\n\n--\nVAT No 123\nRegistered office London\ninvoice attached"
        self.assertEqual(route_agent("", "Hello", signature), "maya")
        self.assertEqual(
            route_agent("", "Refund", "I want my money back for the ticket."),
            "rafa",
        )
        self.assertEqual(
            route_agent("", "Invoice", "Can I get a VAT invoice for the company?"),
            "rafa",
        )
        self.assertEqual(route_agent("ql", "Hello", "Thanks"), "quinn")

    def test_no_reply_ignores_quote(self) -> None:
        from agents.loop import is_marketing_or_automated

        quoted = (
            "Video is not available. Can you send a working link?\n\n"
            "On 1 Oct team@webinarkit.com wrote:\n"
            "Your webinar replay is ready."
        )
        self.assertFalse(is_marketing_or_automated("Re: Recording", quoted))
        self.assertTrue(
            is_marketing_or_automated(
                "Summary of failures for Google Apps Script",
                "Stripe transactions import failed",
            )
        )


class HygieneTests(unittest.TestCase):
    def test_claim_regex_presenter(self) -> None:
        self.assertEqual(_CLAIM.sub("", "SRLE Presenter"), "SRLE Presenter")
        self.assertNotIn("Presenter", _CLAIM.sub("", "The file was resent yesterday"))

    def test_single_signature(self) -> None:
        text = flow.single_signoff(
            "Hello,\n\nThe form is here.\n\nWarm regards,\nMaya\n\n"
            "To your success,\nCustomer Service Team\nSuccess Resources UK Limited"
        )
        self.assertEqual(text.count("Warm regards"), 1)
        self.assertNotIn("To your success", text)
        self.assertNotIn("Customer Service Team", text)
        self.assertIn("Maya - your AI assistant", text)

    def test_hello_uses_signed_name(self) -> None:
        self.assertEqual(_hello("Roellamyecampos"), "Hello,")
        self.assertEqual(_hello("Brunhildatan"), "Hello,")
        self.assertEqual(_hello("Maria Faustino"), "Hello Maria,")
        signed = "Please move my ticket.\n\nBest regards,\nMaria Faustino"
        self.assertEqual(_hello("Roellamyecampos", signed), "Hello Maria,")


class BehaviourTests(unittest.TestCase):
    def test_internal_forward_no_public(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=True,
            matched="forward",
            public_body="Hello Zina, here is Krakow.",
            note_body="Customer Yusuf. Visa question.",
            assignee_email="meda.c@srglobal.com",
            reason="internal_forward",
            forward=True,
        )
        self.assertEqual(disposition.action, "handoff")
        self.assertEqual(disposition.public_body, "")
        self.assertEqual(disposition.status, "open")
        self.assertEqual(disposition.assignee_email, "meda.c@srglobal.com")
        self.assertIn("Yusuf", disposition.internal_note)

    def test_handoff_always_assigns(self) -> None:
        mmi = flow.decide(
            agent="rafa",
            lane="mmi",
            needs_human=True,
            matched="generated_needs_human",
            public_body="We will refund you today.",
            note_body="Rafa draft",
            assignee_email="",
            reason="Rafa drafts only. A person sends.",
        )
        self.assertEqual(mmi.action, "handoff")
        self.assertEqual(mmi.assignee_email, "meda.c@srglobal.com")
        self.assertNotIn("refund you today", mmi.public_body.lower())
        mmo = flow.decide(
            agent="maya",
            lane="mmo",
            needs_human=True,
            matched="generated_needs_human",
            public_body="",
            note_body="Needed: access check",
            assignee_email="",
            reason="masterclass_handoff",
        )
        self.assertEqual(mmo.assignee_email, "alina.last@srglobal.com")
        self.assertEqual(mmo.status, "open")

    def test_translation_table(self) -> None:
        from agents.facts import interpretation_for

        rome = interpretation_for("Is there Italian interpretation in Rome?")
        self.assertIn("EUR 200", rome)
        self.assertIn("rome-translation-cart", rome)
        paris = interpretation_for("Is there French translation in Paris?")
        self.assertIn("EUR 99", paris)
        brussels = interpretation_for("Is there a headset in Brussels?")
        self.assertIn("no interpretation", brussels.lower())
        self.assertNotIn("EUR 200", brussels)

    def test_hub_and_bundle_agree_on_rome(self) -> None:
        phrase = "no translation or interpretation at any mmi event this year"
        for folder in (ROOT / "knowledge-hub", ROOT / "service" / "knowledge-hub"):
            blob = "\n".join(path.read_text(encoding="utf-8") for path in folder.rglob("*.md"))
            self.assertNotIn(phrase, blob.lower())
            self.assertIn("rome-translation-cart", blob)
            self.assertIn("EUR 99", blob)

    def test_ticket_110078_spam_is_silent(self) -> None:
        tag = noise.classify(
            sender="invite@email.apple.com",
            subject="Alex has invited you to test OpenAI Ads",
            text="Open this TestFlight invite.",
            tags="",
        )
        self.assertEqual(tag, "noise_spam_invite")
        disposition = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=False,
            matched="no_reply",
            public_body="I do not have a venue.",
            note_body="",
            assignee_email="meda.c@srglobal.com",
            noise_tag=tag,
        )
        self.assertEqual(disposition.action, "solve_silent")
        self.assertEqual(disposition.public_body, "")
        self.assertEqual(disposition.assignee_email, "")
        self.assertIn("auto_closed_noise", disposition.tags)
        self.assertIn("noise_spam_invite", disposition.tags)

    def test_ticket_110018_private_is_not_rafa(self) -> None:
        body = (
            "Hi, I bought VIP and I want to ask about private sessions.\n\n"
            "On Monday team@webinarkit.com wrote:\n"
            "Your webinar is ready. VAT No 999. Please request a refund in the portal."
        )
        self.assertEqual(route_agent("refund_request finance_related", "VIP Q&A", body), "maya")
        self.assertIsNone(
            noise.classify(
                sender="lynn@example.com",
                subject="VIP Q&A",
                text=flow.routing_text(body),
                tags="refund_request",
            )
        )

    def test_ticket_110009_masterclass_holding_has_no_reasoning(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="mmo",
            needs_human=True,
            matched="generated_needs_human",
            public_body=(
                "Hello Roellamyecampos,\n\n"
                "This is not an MMI ticket, so I will not send an MMI city page. "
                "I have also flagged the broken link."
            ),
            note_body="masterclass",
            assignee_email="alina.last@srglobal.com",
            reason="reasoning_blocked",
        )
        self.assertEqual(disposition.action, "handoff")
        self.assertNotIn("not an MMI", disposition.public_body)
        self.assertNotIn("flagged", disposition.public_body.lower())
        self.assertEqual(disposition.public_body.count("Warm regards"), 1)
        self.assertEqual(disposition.assignee_email, "alina.last@srglobal.com")
        self.assertEqual(disposition.status, "open")

    def test_ticket_109842_srv_gdpr_is_skipped(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="srv",
            needs_human=True,
            matched="generated",
            public_body="Your address has been unsubscribed and deleted.",
            note_body="GDPR",
            assignee_email="meda.c@srglobal.com",
            reason="gdpr_handoff",
        )
        self.assertEqual(disposition.action, "skip_srv")
        self.assertEqual(disposition.public_body, "")
        self.assertNotIn("unsubscribed", disposition.public_body)

    def test_ticket_110297_transfer_can_be_solved(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=False,
            matched="generated",
            public_body=(
                "Hello,\n\nRotterdam is in person only. "
                "Please use this form: https://sr-event.typeform.com/to/ccysEJGM. "
                "You do not need to send an order number."
            ),
            note_body="",
            assignee_email="meda.c@srglobal.com",
            reason="transfer_form",
        )
        self.assertEqual(disposition.action, "solve")
        self.assertEqual(disposition.status, "solved")
        self.assertIn("ccysEJGM", disposition.public_body)
        self.assertIn("do not need to send an order number", disposition.public_body.lower())
        self.assertNotRegex(
            disposition.public_body.lower(),
            r"(please|kindly|could you|can you).{0,40}order number",
        )
        self.assertEqual(disposition.public_body.count("Warm regards"), 1)
        self.assertEqual(disposition.internal_note, "")

    def test_noise_counterexamples_stay_open(self) -> None:
        cases = [
            ("110762", "lynn@example.com", "Re: Recording + Bonuses", "Video is not available", ""),
            ("110009", "a@example.com", "Masterclass link", "The link doesn't work. Can you help?", ""),
            ("110609", "a@example.com", "Re: Rome Italian", "How do I add the Italian interpretation?", ""),
            ("110375", "a@example.com", "SRLE Presenter", "Where is the Presenter replay?", ""),
            ("110071", "a@example.com", "Stop", "I am not Dianne. Please stop emailing me.", ""),
            ("109842", "a@example.com", "GDPR", "Please delete my data under Art. 17.", ""),
            ("110692", "a@example.com", "RE: AI that does the work", "Is a replay available?", ""),
            ("110469", "a@example.com", "RE: Your New LinkedIn Secret Weapon Is Here", "The payment link doesn't work.", ""),
            ("110732", "a@example.com", "Re: STANDARD BONUSES", "I can't attend Birmingham in person. Can I transfer?", ""),
            ("110345", "support@digistore24.com", "[Digistore24 GmbH] refund", "Customer payment is outstanding.", "refund"),
            ("110725", "person@msn.com", "Re: Just announced", "Automatic reply: I am away.", "ql"),
        ]
        for ticket_id, sender, subject, text, tags in cases:
            with self.subTest(ticket_id=ticket_id):
                self.assertIsNone(
                    noise.classify(sender=sender, subject=subject, text=text, tags=tags)
                )

    def test_noise_positive_examples(self) -> None:
        self.assertEqual(
            noise.classify(
                sender="bot@standardbank.co.za",
                subject="Before you register Case C-0030653966",
                text="This mailbox is not monitored.",
            ),
            "noise_autoreply",
        )
        self.assertEqual(
            noise.classify(
                sender="mailer-daemon@example.com",
                subject="Undeliverable: your mail",
                text="Delivery failed.",
            ),
            "noise_bounce",
        )
        self.assertEqual(
            noise.classify(
                sender="apps-script@google.com",
                subject="Summary of failures for Google Apps Script",
                text="Stripe transactions import failed",
            ),
            "noise_system_alert",
        )
        self.assertEqual(
            noise.classify(
                sender="rana@srglobal.com",
                subject="Office closed Friday",
                text="FYI the offices are closed on Friday.",
            ),
            "noise_internal_fyi",
        )
        self.assertEqual(
            noise.classify(
                sender="sales@vendor.example",
                subject="Partnership",
                text="We help companies with SEO and lead generation.",
            ),
            "noise_vendor",
        )


if __name__ == "__main__":
    unittest.main()
