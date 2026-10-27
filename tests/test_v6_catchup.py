"""v6 catch-up fixes (Akram, 27 Oct), from the first 2026 catch-up batch.

- 101496: the greeting took "Verstuurd" from "Verstuurd vanaf mijn iPhone".
- Quinn and Rafa tickets got a public holding reply (now off by default).
- Supplier, sponsor and partner enquiries got a customer holding reply.
- 2025 run: optional long-wait apology and a guard against stale dates and links.
- ai_* tags were never written (single-ticket PUT ignores additional_tags).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402
from agents import publictext, routing  # noqa: E402
from agents.loop import _hello  # noqa: E402

T101496 = "Hello,\n\nAn amount is paid from my account bit i didnt order anything fix yet..\n\nThank you\nVerstuurd vanaf mijn iPhone"
FACTS = (
    "Next MMI: Millionaire Mind Intensive Rome, 4-6 December 2026. "
    "Tickets: https://www.millionairemindevent.com/rome\n"
)


def _run(ctx, draft, hints=None):
    posted = []

    def poster(ticket_id, disposition):
        posted.append(disposition)
        return {"action": disposition.action, "posted": True, "reply": disposition.public_body, "detail": "ok"}

    seen = {}

    def drafter(**kw):
        seen["description"] = kw.get("description")
        return draft

    outcome = app._process_ticket(
        "101496", hints, live=True, backfill=False, loader=lambda _id: ctx, drafter=drafter,
        poster=poster, bot_email="bot@srglobal.com",
    )
    return outcome, posted, seen


def _decide(agent, text, *, subject="", tags=None, public="Hi there,\n\nHere is the answer.", lane="mmi",
            name="", email="x@example.com", stale_facts=None):
    return flow.decide(
        agent=agent, lane=lane, needs_human=False, matched="generated", public_body=public,
        note_body="draft note", greeting=publictext.greeting(name, [text]), customer_text=text,
        assignee_email="", reason="ok", customer_name=name, customer_email=email,
        subject=subject, tags=tags, stale_facts=stale_facts,
    )


class GreetingTests(unittest.TestCase):
    def test_101496_requester_name_beats_mobile_footer(self) -> None:
        self.assertEqual(publictext.greeting("Dion van der Meij", [T101496]), "Hi Dion,")
        self.assertEqual(_hello("Dion van der Meij", T101496), "Hi Dion,")

    def test_101496_footer_only_falls_back(self) -> None:
        self.assertEqual(publictext.greeting("", [T101496]), "Hi there,")
        self.assertEqual(publictext.greeting("Verstuurd", [T101496]), "Hi there,")

    def test_mobile_footers_in_other_languages(self) -> None:
        for footer in ("Sent from my iPhone", "Sent from my Android", "Envoyé de mon iPhone",
                       "Gesendet von meinem iPhone", "Von meinem iPhone gesendet", "Inviato da iPhone",
                       "Enviado desde mi iPhone", "Get Outlook for Android"):
            with self.subTest(footer=footer):
                body = f"Hello,\n\nWhen is the next event?\n\nThanks\n{footer}"
                self.assertEqual(publictext.greeting("", [body]), "Hi there,")
                self.assertEqual(publictext.greeting("Sara Rossi", [body]), "Hi Sara,")
                self.assertNotIn(footer, publictext.strip_mobile_footer(body))

    def test_real_signature_still_used_when_no_requester_name(self) -> None:
        body = "Hello,\n\nWhen is the next event?\n\nKind regards,\nMarco\nSent from my iPhone"
        self.assertEqual(publictext.greeting("", [body]), "Hi Marco,")

    def test_process_greets_101496_by_requester_name(self) -> None:
        ctx = _ctx(requester_name="Dion van der Meij", subject="Payment", description=T101496,
                   comments=[_comment("1", "10", T101496)])
        draft = _draft(public_body="Hi Verstuurd,\n\nWe can see the payment. The team will check it.",
                       needs_human=True, reason="payment check")
        _o, posted, _s = _run(ctx, draft)
        self.assertFalse(posted[0].public_body.startswith("Hi Verstuurd"))
        if posted[0].public_body:
            self.assertTrue(posted[0].public_body.startswith("Hi Dion,"), posted[0].public_body)


class InternalLaneTests(unittest.TestCase):
    QL_SUBJECT = "[QL Inquiry] Change of Payment Mode to One-Time $2995"
    QL_TEXT = "Hi, I would like to change how I pay. Can you help?"

    def test_101939_ql_subject_and_tag_route_to_quinn_with_no_public_reply(self) -> None:
        d = _decide("maya", self.QL_TEXT, subject=self.QL_SUBJECT, tags=["ql"], lane="mmo")
        self.assertEqual((d.action, d.status), ("handoff", "open"))
        self.assertEqual(d.public_body, "")
        self.assertEqual(d.agent, "quinn")
        self.assertEqual(d.assignee_email, "alina.last@srglobal.com")
        self.assertIn("No public reply", d.internal_note)
        self.assertIn("ai_no_public_reply", d.tags)
        self.assertNotIn("ai_public_reply", d.tags)

    def test_refund_goes_to_rafa_with_no_public_reply(self) -> None:
        d = _decide("maya", "I want a refund for my ticket, please.", name="Ana Silva")
        self.assertEqual((d.action, d.status, d.public_body), ("handoff", "open", ""))
        self.assertEqual(d.assignee_email, "meda.c@srglobal.com")

    def test_refund_tag_alone_routes_to_rafa(self) -> None:
        self.assertEqual(routing.owner("Please check my order.", "", ["refund_request"]), "rafa")

    @mock.patch.dict(os.environ, {"SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES": "false"})
    def test_flag_off_restores_the_holding_reply(self) -> None:
        d = _decide("maya", self.QL_TEXT, subject=self.QL_SUBJECT, tags=["ql"], name="Jo Bloggs")
        self.assertEqual(d.action, "handoff")
        self.assertTrue(d.public_body.startswith("Hi Jo,"), d.public_body)
        self.assertIn("ai_public_reply", d.tags)

    @mock.patch.dict(os.environ, {"SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES": "on"})
    def test_flag_values(self) -> None:
        self.assertTrue(flow.skip_holding_for_internal_lanes())
        for off in ("0", "false", "no", "off"):
            with mock.patch.dict(os.environ, {"SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES": off}):
                self.assertFalse(flow.skip_holding_for_internal_lanes())
        with mock.patch.dict(os.environ, {"SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES": ""}):
            self.assertTrue(flow.skip_holding_for_internal_lanes())


class BusinessTests(unittest.TestCase):
    CASES = [
        ("Quotation for AV equipment", "Dear team, please find our quotation for the AV equipment for your seminar."),
        ("Seminar in Malta", "We would like to organise a seminar in Malta with you and request T. Harv Eker as the speaker."),
        ("Sponsorship", "Would you be interested in a sponsorship package for your event? Media kit attached."),
        ("Partnership proposal", "We propose a partnership with Success Resources. Can we have a call?"),
    ]

    def test_101059_102681_business_enquiries_go_to_meda_without_public_reply(self) -> None:
        for subject, text in self.CASES:
            with self.subTest(subject=subject):
                d = _decide("maya", text, subject=subject, lane="mmo")
                self.assertEqual((d.action, d.status, d.public_body), ("handoff", "open", ""))
                self.assertEqual(d.assignee_email, "meda.c@srglobal.com")
                self.assertIn("ai_business_enquiry", d.tags)

    def test_partnership_pitch_is_a_meda_note_not_a_silent_close(self) -> None:
        text = "We would like to propose a partnership for your events in Malta. Our media kit is attached."
        ctx = _ctx(subject="Partnership proposal", description=text, requester_name="Paul Borg",
                   requester_email="paul@agency.example", comments=[_comment("1", "10", text)], tags=[])
        _o, posted, _s = _run(ctx, _draft(public_body="Hi Paul,\n\nThanks, we will look at it."))
        self.assertEqual((posted[0].action, posted[0].status, posted[0].public_body), ("handoff", "open", ""))
        self.assertEqual(posted[0].assignee_email, "meda.c@srglobal.com")

    def test_customer_questions_are_not_business(self) -> None:
        for text in ("When is the next MMI in Rome?", "Can I get a quote of the ticket price for 2 people?",
                     "Is the event in English?"):
            with self.subTest(text=text):
                self.assertFalse(routing.business_enquiry(text, "MMI"))


class ApologyTests(unittest.TestCase):
    def test_apology_goes_after_the_greeting_once(self) -> None:
        out = publictext.with_long_wait_apology("Hi Ana,\n\nSorry for the delay. The event is in English.")
        self.assertEqual(out, "Hi Ana,\n\n" + publictext.LONG_WAIT_APOLOGY + "\n\nThe event is in English.")
        self.assertEqual(publictext.with_long_wait_apology(out), out)

    def test_request_param_adds_apology(self) -> None:
        _o, posted, _s = _run(_ctx(), _draft(), hints={"long_wait_apology": True})
        body = posted[0].public_body
        self.assertTrue(body.startswith("Hi Ana,\n\n" + publictext.LONG_WAIT_APOLOGY), body)
        self.assertIn("ai_long_wait_apology", posted[0].tags)

    @mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": "true"})
    def test_env_adds_apology(self) -> None:
        _o, posted, _s = _run(_ctx(), _draft())
        self.assertIn(publictext.LONG_WAIT_APOLOGY, posted[0].public_body)

    @mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": ""})
    def test_off_by_default(self) -> None:
        _o, posted, _s = _run(_ctx(), _draft())
        self.assertNotIn(publictext.LONG_WAIT_APOLOGY, posted[0].public_body)

    def test_webhook_param_is_read(self) -> None:
        hints = app._hints_from_body({"ticket_id": "1", "long_wait_apology": "true"})
        self.assertTrue(hints.get("long_wait_apology"))


class StaleGuardTests(unittest.TestCase):
    def test_stale_content_rules(self) -> None:
        self.assertIn("2025", flow.stale_content("MMI Amsterdam was on 12-14 September 2025.", FACTS))
        self.assertTrue(flow.stale_content("It runs on 12 September.", FACTS))
        self.assertTrue(flow.stale_content("Book at https://example.com/mmi-2025-amsterdam", FACTS))
        self.assertEqual(flow.stale_content("The next MMI is in Rome, 4-6 December 2026.", FACTS), "")
        self.assertEqual(flow.stale_content("Tickets: https://www.millionairemindevent.com/rome", FACTS), "")
        self.assertEqual(flow.stale_content("See https://www.srglobal.com/ for more.", FACTS), "")

    def test_old_ticket_with_stale_date_is_handed_off(self) -> None:
        d = _decide("maya", "When is MMI Amsterdam?", name="Ana Silva", stale_facts=FACTS,
                    public="Hi Ana,\n\nMMI Amsterdam is on 12-14 September 2025.")
        self.assertEqual(d.action, "handoff")
        self.assertNotIn("2025", d.public_body)
        self.assertIn("ai_stale_blocked", d.tags)

    def test_old_ticket_with_current_facts_is_solved(self) -> None:
        d = _decide("maya", "When is MMI Amsterdam?", name="Ana Silva", stale_facts=FACTS,
                    public="Hi Ana,\n\nMMI Amsterdam is over. The next MMI is in Rome, 4-6 December 2026.")
        self.assertEqual(d.action, "solve")

    def test_process_old_ticket_briefs_the_drafter_and_blocks_stale_reply(self) -> None:
        ctx = _ctx(created_at="2025-03-02T10:00:00Z")
        draft = _draft(public_body="Hi Ana,\n\nThe next MMI is on 12 September 2025 in Amsterdam.")
        with mock.patch.object(app, "_current_facts", return_value=FACTS):
            _o, posted, seen = _run(ctx, draft)
        self.assertTrue(seen["description"].startswith("OLD TICKET"))
        self.assertEqual(posted[0].action, "handoff")
        self.assertNotIn("2025", posted[0].public_body)

    def test_2026_ticket_is_not_guarded(self) -> None:
        ctx = _ctx(created_at="2026-03-02T10:00:00Z")
        draft = _draft(public_body="Hi Ana,\n\nIt runs on 12 September.")
        _o, posted, seen = _run(ctx, draft)
        self.assertFalse(str(seen["description"]).startswith("OLD TICKET"))
        self.assertEqual(posted[0].action, "solve")


class TagWriteTests(unittest.TestCase):
    def test_additional_tags_go_to_the_tags_endpoint(self) -> None:
        calls = []

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(req, timeout=0):
            calls.append((req.get_method(), req.full_url, json.loads(req.data.decode())))
            return Resp()

        with mock.patch.object(app, "_zendesk_auth_header", return_value=("sub", "Basic x")), \
                mock.patch.object(app, "urlopen", fake_urlopen):
            ok, _detail = app._put_ticket("5", {"status": "solved", "additional_tags": ["ai_answered", "ai_maya"]})
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "https://sub.zendesk.com/api/v2/tickets/5.json")
        self.assertNotIn("additional_tags", calls[0][2]["ticket"])
        self.assertEqual(calls[1], ("PUT", "https://sub.zendesk.com/api/v2/tickets/5/tags.json",
                                    {"tags": ["ai_answered", "ai_maya"]}))


if __name__ == "__main__":
    unittest.main()
