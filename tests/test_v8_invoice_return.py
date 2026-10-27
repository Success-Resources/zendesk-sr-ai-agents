"""v8 fixes (Akram, 27 Oct 2026), from the live run of v7 (Success-Resources main 9f0ac7c).

Fixtures are anonymised versions of the real tickets (names, emails, phones, company
details and invoice numbers removed or replaced).

- 105726: Spanish "devolver la entrada" got a public holding reply (should be Rafa, internal only).
- 104954: invoice request written under a quote of itself ("> I need an invoice") got a holding reply.
- 105610: German "Rechnungen ... auf die Firma umschreiben" got a holding reply.
- 104450, 104711, 104791, 105542, 105647, 104334, 104776: the note's "Asked:" line fired triggers.
- 104334: a request for a copy of the book went to Rafa only because of our invoice-email subject.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402,F401
from test_v6_catchup import _run  # noqa: E402
from agents import forward, notewords, routing  # noqa: E402
from service import knowledge  # noqa: E402

LANE_TAGS = {"ai_generated", "ai_no_public_reply", "ai_draft_only"}

S105726 = "devolucion entrada"
T105726 = (
    "Muy srs. mios:\n\nNumero de identificacion fiscal para ventas: ES-X0000000X\n\nFactura SR-000000001\n\n"
    "Deseo devolver la entrada adquirida al observar que el curso no sera en Espanol.\n\nAtte:\n\nCliente"
)
T104954_FIRST = (
    "Good afternoon,\nI need an invoice for this purchase under my company date.\n\nFind the details below:\n\n"
    "ACME SL\n\nB00000000\n\nCALLE EJEMPLO 1\n\nCIUDAD, 00000"
)
T104954_LATEST = (
    "> Good afternoon,\n> I need an invoice for this purchase under my company date.\n>\n"
    "> Find the details below:\n\n> ACME SL\n>\n> B00000000\n>\n> CALLE EJEMPLO 1\n>\n> CIUDAD, 00000\n\n"
    "Thanks in advanced.\n\nCliente\n\n+00 000000000\n\n>"
)
S105610 = "Re: Rechnung 00001"
T105610 = (
    "Guten Tag,\n\nkoennten Sie bitte die Rechnungen fuer meine Tickets auf die Firma umschreiben?\n"
    "Firma Beispiel GmbH, Musterstrasse 1, 00000 Musterstadt.\n\nVielen Dank\nKunde"
)
S104334 = "Invoice invoice no. I-000000000-de - 03/18/2026 - (XML)"
T104334 = (
    "Hi,\n\nHope all is well on your end.\n\nMay I please request a copy of _Secrets of the Millionaire Mind: "
    "Mastering the Inner Game of Wealth_ by T. Harv Eker, as mentioned in the purchase.\n\n"
    "Thank you in advance for your assistance.\n\nKind regards,\nCustomer"
)
S104695 = "Re: Invoice 00002"
T104695 = (
    "Hi Good morning!\n\nI signed up for the Hanoi event (May 9-10, 2026)\n\nMay i get the details of the Hanoi "
    "event as I want to book my hotel also. I booked my airfare already.\n\nThank you,\nCustomer\n\n"
    " On Sunday, April 19, 2026 at 03:54:54 PM GMT+8, Success Resources <notifications@example.com> wrote:\n\n"
    "Dear customer, Here is the invoice 00002 for your purchase."
)
# Asked-line cases modelled on 104776, 104711, 105647 and 104450.
ASKED_CASES = (
    "I was charged for a second ticket, please send an invoice and apply the coupon.",
    "Please send the Invoice with our VAT number, the invoicing address is below.",
    "I never got the confirmation link and the access link is missing. Registration link please.",
    "Missing confirmation for Quantum Leap, and the leap dates? Also the Warrior camp, TTT, EWC, NWA, GBI.",
    "Refund the MMI please, the Millionaire Mind Intensive invoice was wrong, or I file a chargeback.",
    "confirmation missing for my invoices, I was invoiced twice",
)


def _customer_ctx(body, subject="Ticket", comments=None):
    return _ctx(subject=subject, description=body, tags=[], requester_email="cliente@example.com",
                requester_name="Cliente", comments=comments or [_comment("1", "10", body)])


def _no_triggers(test, text):
    test.assertEqual(notewords.trigger_hits(text), [], text)


def _holding():
    return _draft(public_body="Hi,\n\nThank you, the team will look at this.", needs_human=True)


class SpanishAndOtherReturnTests(unittest.TestCase):
    """Fix 1: return or refund wording in ES/PT/IT/EN goes to Rafa, internal only."""

    def test_105726_goes_to_rafa_without_public_reply(self) -> None:
        _o, posted, _seen = _run(_customer_ctx(T105726, subject=S105726), _holding())
        d = posted[0]
        self.assertEqual((d.action, d.agent, d.public_body), ("handoff", "rafa", ""))
        self.assertTrue({"ai_rafa", *LANE_TAGS} <= set(d.tags), d.tags)
        _no_triggers(self, d.internal_note.split("Rafa draft")[0])

    def test_return_phrases(self) -> None:
        for text in (
            "Deseo devolver la entrada adquirida", "Quiero la devolucion de mi entrada", "pido la devolución",
            "solicito el reembolso", "quiero reembolsar mi compra", "pido el reintegro del importe",
            "quiero cancelar el cobro", "cancelar el cargo de 497 EUR", "cancelar el pago",
            "Gostaria da devolução do valor", "pedido de reembolso", "quero o estorno", "devolver o ingresso",
            "vorrei il rimborso", "posso essere rimborsato?", "vorrei restituire il biglietto",
            "chiedo la restituzione", "I want to return my ticket", "can I return the two tickets I bought",
            "please give back the ticket", "I want to give my ticket back", "Pls reverse the charges",
        ):
            with self.subTest(text=text):
                self.assertTrue(routing.refund_ask(text))
                self.assertEqual(routing.owner(text), "rafa")
                self.assertEqual(knowledge.route_agent("", "Ticket", text), "rafa")

    def test_booking_questions_stay_with_maya(self) -> None:
        for text in (
            "I want to book a ticket for Madrid", "Can I change my booking to the next event?",
            "I bought a return ticket to London", "My return flight is on Sunday",
            "When do I return from the event?", "Quiero reservar una entrada para Madrid",
            "Quero comprar o ingresso", "Vorrei prenotare un posto", "I will return to the event next year",
            "Can I transfer my ticket to my wife?", "Please return the form by Friday",
            "Wo finde ich mein Ticket?", "¿Dónde está el evento?",
        ):
            with self.subTest(text=text):
                self.assertFalse(routing.refund_ask(text))
                self.assertFalse(routing.invoice_ask(text))
                self.assertEqual(routing.owner(text), "maya")


class InvoiceTests(unittest.TestCase):
    """Fix 2: invoice and receipt requests are Rafa, internal only, consistently."""

    def test_104954_quote_top_post_goes_to_rafa(self) -> None:
        ctx = _customer_ctx(T104954_FIRST, subject="", comments=[
            _comment("1", "10", T104954_FIRST), _comment("2", "10", T104954_LATEST)])
        _o, posted, _seen = _run(ctx, _holding())
        d = posted[0]
        self.assertEqual((d.action, d.agent, d.public_body), ("handoff", "rafa", ""))
        self.assertTrue({"ai_rafa", *LANE_TAGS} <= set(d.tags), d.tags)
        _no_triggers(self, d.internal_note)

    def test_routing_text_reads_a_reply_that_opens_with_a_quote(self) -> None:
        desc = f"Customer:\n{T104954_FIRST}\n\nCustomer:\n{T104954_LATEST}"
        text = flow.routing_text(desc)
        self.assertIn("I need an invoice", text)
        self.assertIn("Thanks in advanced", text)
        self.assertNotIn(">", text)
        # A normal reply above a quote is unchanged.
        self.assertEqual(flow.routing_text("Customer:\nHi, when is it?\n> old text"), "Hi, when is it?")

    def test_105610_german_rechnung_goes_to_rafa(self) -> None:
        _o, posted, _seen = _run(_customer_ctx(T105610, subject=S105610), _holding())
        d = posted[0]
        self.assertEqual((d.action, d.agent, d.public_body), ("handoff", "rafa", ""))
        self.assertTrue({"ai_rafa", *LANE_TAGS} <= set(d.tags), d.tags)
        _no_triggers(self, d.internal_note)

    def test_invoice_words_in_several_languages(self) -> None:
        for text in (
            "I need an invoice for this purchase", "Please send me a receipt", "Can I get a VAT invoice?",
            "Können Sie die Rechnungen auf die Firma umschreiben?", "Bitte eine Quittung",
            "Pouvez-vous envoyer la facture ?", "Necesito la factura a nombre de mi empresa",
            "Mi serve la fattura", "Preciso da fatura", "Kunt u de factuur sturen?", "un recibo por favor",
            "la ricevuta del pagamento",
        ):
            with self.subTest(text=text):
                self.assertTrue(routing.invoice_ask(text))
                self.assertEqual(routing.owner(text), "rafa")
                self.assertEqual(knowledge.route_agent("", "Ticket", text), "rafa")

    def test_receipt_of_an_email_is_not_an_ask(self) -> None:
        for text in ("Thank you for confirming receipt of my email", "upon receipt of payment"):
            with self.subTest(text=text):
                self.assertFalse(routing.invoice_ask(text))

    def test_our_invoice_email_subject_alone_is_not_an_ask(self) -> None:
        for subject in (S104334, S104695, "AW: Rechnung 00003", "Re: Example Ltd: Invoice SR-000000002",
                        "Your Example receipt [#1234-5678]"):
            with self.subTest(subject=subject):
                self.assertTrue(routing.system_invoice_subject(subject))
                self.assertFalse(routing.invoice_ask("When is the event?", subject))
        for subject in ("Invoice request", "Need invoice for company", "Rechnung bitte auf Firma", "Re: Invoice"):
            with self.subTest(subject=subject):
                self.assertFalse(routing.system_invoice_subject(subject))
                self.assertTrue(routing.invoice_ask("hello", subject))
                self.assertEqual(routing.owner("hello", subject), "rafa")

    def test_104334_book_copy_and_104695_event_details_are_not_rafa(self) -> None:
        for subject, body in ((S104334, T104334), (S104695, T104695)):
            with self.subTest(subject=subject):
                text = flow.routing_text(f"Customer:\n{body}")
                self.assertEqual(routing.owner(text, subject, ["invoice_request", "finance_related"]), "maya")
                self.assertEqual(knowledge.route_agent("invoice_request finance_related", subject, body), "maya")

    def test_invoice_with_money_words_in_body_still_rafa(self) -> None:
        self.assertEqual(routing.owner("I did not get the books. Pls reverse the charges.", "Re: Invoice 00004"),
                         "rafa")


class NoteQuoteTests(unittest.TestCase):
    """Fix 3: the customer's words in notes never fire a trigger; staff drafts keep theirs."""

    def test_asked_line_is_clean_for_every_lane(self) -> None:
        for text in ASKED_CASES:
            for agent in ("maya", "rafa", "quinn"):
                with self.subTest(text=text, agent=agent):
                    note = flow.handoff_note(lane="mmi", assignee_email="", reason="ok", agent=agent,
                                             customer_text=text, public_sent=False,
                                             customer_name="Cliente Invoice")
                    _no_triggers(self, note)
                    self.assertIn("Asked:", note)

    def test_neutral_words_keep_the_meaning(self) -> None:
        self.assertEqual(notewords.scrub("I need an invoice"), "I need a bill")
        self.assertEqual(notewords.scrub("Please send the Invoices"), "Please send the Bills")
        self.assertIn("confirmation URL", notewords.scrub("no confirmation link"))
        self.assertIn("access URL", notewords.scrub("the access link is broken"))
        self.assertIn("sign-up URL", notewords.scrub("registration link"))

    def test_book_title_is_not_turned_into_the_event(self) -> None:
        out = notewords.scrub("a copy of Secrets of the Millionaire Mind by T. Harv Eker")
        self.assertNotIn("Intensive", out)
        self.assertIn("M-Mind", out)
        _no_triggers(self, out)
        self.assertEqual(notewords.scrub("the Millionaire Mind Intensive"), "the MM-Intensive")

    def test_staff_drafts_keep_their_lane_words(self) -> None:
        rafa = flow.handoff_note(lane="mmi", assignee_email="", reason="ok", agent="rafa",
                                 customer_text="please send an invoice", public_sent=False,
                                 draft="Hello,\n\nWe will send the invoice for your purchase shortly.")
        self.assertIn("send the invoice", rafa.split("Rafa draft")[1])
        _no_triggers(self, rafa.split("Rafa draft")[0])
        quinn = flow.handoff_note(lane="mmi", assignee_email="", reason="ok", agent="quinn",
                                  customer_text="Quantum Leap dates?", public_sent=False,
                                  draft="Hello,\n\nThe next Quantum Leap dates are being confirmed.")
        self.assertIn("Quantum Leap", quinn.split("Quinn draft")[1])
        _no_triggers(self, quinn.split("Quinn draft")[0])

    def test_maya_draft_is_scrubbed(self) -> None:
        note = flow.handoff_note(lane="mmo", assignee_email="", reason="needs_human", agent="maya",
                                 customer_text="where do I log in?", public_sent=True,
                                 draft="Hello,\n\nHere is your access link and invoice.")
        _no_triggers(self, note)  # words the customer did not use are swapped (v7 keep_from rule)

    def test_forward_note_is_clean(self) -> None:
        ctx = _ctx(requester_email="staff@srglobal.com", requester_name="Staff", subject="Fwd: Invoice and refund",
                   comments=[_comment("1", "10", "Can she get a refund? Also she needs an invoice for MMI "
                                                 "and the access link.")])
        _o, posted, _seen = _run(ctx, _draft())
        note = posted[0].internal_note
        _no_triggers(self, note)
        self.assertIn("bill", note)

    def test_parsed_forward_original_is_clean(self) -> None:
        fwd = forward.Forward(sender_name="Cliente", sender_email="cliente@example.com", date="",
                              subject="Invoice for Quantum Leap",
                              body="Hello, I need an invoice and the confirmation link. Or a refund.",
                              questions=["Can I get an invoice?"])
        note = forward.note(fwd, staff_email="staff@srglobal.com", subject="Fwd: x",
                            assignee="meda.c@srglobal.com", lane="mmi")
        _no_triggers(self, note)
        self.assertIn("I need a bill", note)


if __name__ == "__main__":
    unittest.main()
