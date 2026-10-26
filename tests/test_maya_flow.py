"""Maya's public reply, handoff, claim, and backfill decisions."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ["ZENDESK_MMI_ASSIGNEE_EMAIL"] = "meda.c@srglobal.com"
os.environ["ZENDESK_MMO_ASSIGNEE_EMAIL"] = "alina.last@srglobal.com"

import flow  # noqa: E402
import app  # noqa: E402
import backfill  # noqa: E402


def _comment(cid: str, author: str, body: str, *, public: bool = True, at: str = "2026-02-01T00:00:00Z") -> flow.Comment:
    return flow.Comment(id=cid, author_id=author, public=public, body=body, created_at=at)


def _ctx(**overrides) -> dict:
    ctx = {
        "subject": "MMI dates",
        "description": "When is the next one?",
        "tags": ["mmi", "ai_draft_only", "ai_generated"],
        "recipient": "info.eu@srglobal.com",
        "status": "open",
        "requester_id": "10",
        "requester_email": "ana@example.com",
        "requester_name": "Ana",
        "comments_ok": True,
        "comments": [_comment("1", "10", "When is the next MMI?")],
        "users": {},
    }
    ctx.update(overrides)
    return ctx


def _draft(**overrides) -> flow.Draft:
    data = dict(
        agent="maya",
        matched="generated",
        extra_tags=[],
        note_body="staff note",
        public_body="Hello Ana,\n\nAll sessions are in English.",
        needs_human=False,
        reason="ok",
    )
    data.update(overrides)
    return flow.Draft(**data)


class ParseAndClaimTests(unittest.TestCase):
    def test_missing_comma_is_repaired(self) -> None:
        raw = (
            '{"id":"48111","ticket_id":"48111","subject":"Help",'
            '"description":"Need a human","tags":"mmi",'
            '"requester_name":"Ana","requester_email":"ana@example.com"\n'
            '"latest_comment":"please call me"}'
        )
        body = flow.parse_webhook_payload(raw)
        self.assertEqual(flow.webhook_ticket_id(body), "48111")
        self.assertEqual(body.get("latest_comment"), "please call me")
        self.assertTrue(body.get("_json_repaired"))

    def test_raw_newline_still_yields_ticket_id(self) -> None:
        raw = '{"ticket_id": "42", "description": "line1\nline2"}'
        body = flow.parse_webhook_payload(raw)
        self.assertEqual(flow.webhook_ticket_id(body), "42")
        self.assertTrue(body.get("_partial"))

    def test_claim_expires_and_does_not_survive_a_new_book(self) -> None:
        book = flow.ClaimBook(ttl_seconds=10)
        self.assertTrue(book.claim("9", now=100))
        self.assertFalse(book.claim("9", now=105))
        self.assertTrue(book.claim("9", now=111))
        self.assertTrue(book.claim("8", now=0))
        book.release("8")
        self.assertTrue(book.claim("8", now=0))
        fresh = flow.ClaimBook(ttl_seconds=10)
        self.assertTrue(fresh.claim("9", now=0))

    def test_webhook_run_releases_the_claim(self) -> None:
        self.assertTrue(app._claim_ticket("88001"))
        original = app._process_ticket

        def fake(ticket_id, hints=None, **kwargs):
            return {"action": "solve", "posted": True, "assigned": False, "detail": "ok"}

        app._process_ticket = fake
        try:
            app._run_webhook("88001", {})
            self.assertTrue(app._claim_ticket("88001"))
        finally:
            app._process_ticket = original
            app._release_ticket("88001")


class DecideTests(unittest.TestCase):
    def test_confident_quinn_answer_is_posted_by_maya(self) -> None:
        disposition = flow.decide(
            agent="quinn",
            lane="mmi",
            needs_human=False,
            matched="generated",
            public_body="Hello,\n\nThe next Quantum Leap dates are on the sheet.\n\n---\nStaff only — ignore",
            note_body="staff",
            assignee_email="meda.c@srglobal.com",
            reason="ok",
        )
        self.assertEqual(disposition.action, "solve")
        self.assertEqual(disposition.status, "solved")
        self.assertEqual(disposition.assignee_email, "")
        self.assertIn("Quantum Leap dates", disposition.public_body)
        self.assertNotIn("Staff only", disposition.public_body)
        self.assertEqual(disposition.public_body.count("Warm regards"), 0)
        self.assertIn(flow.TAG_ANSWERED, disposition.tags)

    def test_rafa_draft_is_not_the_public_reply(self) -> None:
        disposition = flow.decide(
            agent="rafa",
            lane="mmo",
            needs_human=True,
            matched="generated_needs_human",
            public_body="I have passed this refund request to the team and they will refund you today.",
            note_body="FULL DRAFT stays internal",
            assignee_email="alina.last@srglobal.com",
            reason="Rafa drafts only. A person sends.",
        )
        self.assertEqual(disposition.action, "handoff")
        self.assertEqual(disposition.status, "open")
        self.assertEqual(disposition.assignee_email, "alina.last@srglobal.com")
        self.assertIn("FULL DRAFT", disposition.internal_note)
        self.assertNotIn("refund you today", disposition.public_body)
        self.assertIn("asked the team", disposition.public_body)
        self.assertIn("ai_draft_only", disposition.tags)
        self.assertIn("ai_rafa", disposition.tags)
        self.assertIn(flow.TAG_ASSIGNED, disposition.tags)
        text = flow.format_outcome(
            "2",
            {
                "action": disposition.action,
                "agent": disposition.agent,
                "assignee": disposition.assignee_email,
                "reply": disposition.public_body,
                "internal_note": disposition.internal_note,
                "posted": False,
            },
        )
        self.assertIn("action: handoff to alina.last@srglobal.com", text)
        self.assertNotIn("refund you today", text.split("internal note:")[0])

    def test_handoff_promise_is_not_solved(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=False,
            matched="generated",
            public_body="Hello,\n\nI have asked the team to resend your confirmation.",
            note_body="staff",
            assignee_email="meda.c@srglobal.com",
            reason="ok",
        )
        self.assertEqual(disposition.action, "handoff")
        self.assertIn("asked the team", disposition.public_body)
        self.assertTrue(disposition.claims_handoff)

    def test_staff_blocker_becomes_a_holding_reply(self) -> None:
        disposition = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=True,
            matched="generated_needs_human",
            public_body="A person must handle this. The draft tried to approve or process a refund.",
            note_body="blocked",
            assignee_email="meda.c@srglobal.com",
            reason="refund language blocked",
        )
        self.assertEqual(disposition.action, "handoff")
        self.assertNotIn("approve", disposition.public_body.lower())
        self.assertIn("asked the team", disposition.public_body)

    def test_unassigned_text_drops_the_handoff_claim(self) -> None:
        text = "The form is here: https://sr-event.typeform.com/to/ccysEJGM. I have passed this to the team."
        safe = flow.public_text_for_handoff(text, assigned=False)
        self.assertIn("typeform", safe)
        self.assertNotIn("passed this to the team", safe)
        self.assertEqual(flow.public_text_for_handoff(flow.HOLDING_REPLY, assigned=False).strip() != "", True)
        self.assertNotIn("teammate", flow.strip_handoff_claims(flow.HOLDING_REPLY))

    def test_srv_and_silent_cases(self) -> None:
        skipped = flow.decide(
            agent="maya",
            lane="srv",
            needs_human=False,
            matched="generated",
            public_body="Hello",
            note_body="",
            assignee_email="",
        )
        self.assertEqual(skipped.action, "skip_srv")
        silent = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=False,
            matched="no_reply",
            public_body="",
            note_body="",
            assignee_email="meda.c@srglobal.com",
            reason="no_reply",
        )
        self.assertEqual(silent.action, "solve_silent")
        self.assertEqual(silent.public_body, "")
        self.assertEqual(silent.assignee_email, "")
        self.assertIn("auto_closed_noise", silent.tags)
        alert = flow.decide(
            agent="maya",
            lane="mmi",
            needs_human=True,
            matched="none",
            public_body="",
            note_body="Stripe import failed",
            assignee_email="meda.c@srglobal.com",
            reason="internal_alert",
        )
        self.assertEqual(alert.action, "solve_silent")
        self.assertEqual(alert.public_body, "")
        self.assertEqual(alert.assignee_email, "")
        self.assertIn("noise_system_alert", alert.tags)


class ProcessTests(unittest.TestCase):
    def _run(self, ctx, draft, **kwargs):
        posted = []

        def poster(ticket_id, disposition):
            posted.append(disposition)
            return {
                "action": disposition.action,
                "posted": True,
                "assigned": disposition.action == "handoff",
                "reply": disposition.public_body,
                "assignee": disposition.assignee_email if disposition.action == "handoff" else "",
                "lane": disposition.lane,
                "agent": disposition.agent,
                "reason": disposition.reason,
                "tags": list(disposition.tags),
                "detail": "ok",
            }

        seen = {}

        def drafter(**kw):
            seen["description"] = kw.get("description")
            return draft() if callable(draft) else draft

        outcome = app._process_ticket(
            "100",
            live=kwargs.get("live", True),
            backfill=kwargs.get("backfill", False),
            loader=kwargs.get("loader", lambda ticket_id: ctx),
            drafter=drafter,
            poster=poster,
            bot_email=kwargs.get("bot_email", "bot@srglobal.com"),
        )
        return outcome, posted, seen

    def test_old_draft_tag_does_not_block_a_public_solve(self) -> None:
        outcome, posted, _seen = self._run(_ctx(), _draft(agent="maya"))
        self.assertEqual(posted[0].action, "solve")
        self.assertEqual(posted[0].status, "solved")
        self.assertIn("ai_answered", posted[0].tags)
        self.assertNotIn("ai_draft_only", posted[0].tags)
        self.assertEqual(outcome["posted"], True)

    def test_dry_run_posts_nothing(self) -> None:
        outcome, posted, _seen = self._run(_ctx(), _draft(), live=False)
        self.assertEqual(posted, [])
        self.assertEqual(outcome["action"], "solve")
        self.assertFalse(outcome["posted"])
        self.assertIn("English", outcome["reply"])
        self.assertEqual(outcome["assignee"], "")

    def test_rafa_on_mmo_hands_off_to_alina(self) -> None:
        ctx = _ctx(recipient="mmo@srglobal.com", tags=["mmo_event"])
        draft = _draft(
            agent="rafa",
            matched="generated_needs_human",
            needs_human=True,
            public_body="I have passed this refund request to the team and they will refund you today.",
            note_body="FULL DRAFT stays internal",
            reason="Rafa drafts only. A person sends.",
        )
        outcome, posted, _seen = self._run(ctx, draft, live=False)
        self.assertEqual(posted, [])
        self.assertEqual(outcome["action"], "handoff")
        self.assertNotIn("refund you today", outcome["reply"])
        self.assertEqual(outcome["assignee"], "alina.last@srglobal.com")
        self.assertIn("FULL DRAFT", outcome["internal_note"])
        self.assertIn("ai_draft_only", outcome["tags"])
        self.assertIn("ai_rafa", outcome["tags"])
        self.assertIn("action: handoff to alina.last@srglobal.com", flow.format_outcome("100", outcome))

    def test_quinn_confident_answer_is_solved_by_maya(self) -> None:
        draft = _draft(agent="quinn", public_body="Hello,\n\nHere are the QL dates.")
        _outcome, posted, _seen = self._run(_ctx(), draft)
        self.assertEqual(posted[0].action, "solve")
        self.assertEqual(posted[0].status, "solved")
        self.assertIn("QL dates", posted[0].public_body)
        self.assertEqual(posted[0].assignee_email, "")

    def test_srv_is_skipped(self) -> None:
        def drafter(**_kwargs):
            raise AssertionError("srv must not be drafted")

        outcome, posted, _seen = self._run(_ctx(recipient="srv@srglobal.com"), drafter)
        self.assertEqual(posted[0].action, "skip_srv")
        self.assertIn("ai_skipped_srv", posted[0].tags)
        self.assertEqual(outcome["action"], "skip_srv")

    def test_latest_agent_comment_is_not_answered(self) -> None:
        ctx = _ctx(
            comments=[
                _comment("1", "10", "When is it?", at="2026-02-01T00:00:00Z"),
                _comment("2", "77", "I will take this.", at="2026-02-02T00:00:00Z"),
            ],
            users={"77": {"email": "meda.c@srglobal.com"}},
        )

        def drafter(**_kwargs):
            raise AssertionError("agent comment must not be answered")

        outcome, posted, _seen = self._run(ctx, drafter)
        self.assertEqual(posted, [])
        self.assertEqual(outcome["action"], "skip")
        self.assertIn("agent", outcome["reason"])

    def test_internal_draft_still_gets_a_public_reply(self) -> None:
        ctx = _ctx(
            comments=[
                _comment("1", "10", "When is the next MMI?", at="2026-02-01T00:00:00Z"),
                _comment("2", "99", "Staff only — Maya wrote this.", public=False, at="2026-02-01T01:00:00Z"),
            ]
        )
        _outcome, posted, seen = self._run(ctx, _draft())
        self.assertEqual(posted[0].action, "solve")
        self.assertNotIn("Staff only", seen["description"])
        self.assertIn("When is the next MMI?", seen["description"])

    def test_follow_up_includes_the_whole_conversation(self) -> None:
        ctx = _ctx(
            comments=[
                _comment("1", "10", "When is the next MMI?", at="2026-02-01T00:00:00Z"),
                _comment("2", "99", "All sessions are in English.", at="2026-02-01T01:00:00Z"),
                _comment("3", "10", "What about food?", at="2026-02-02T00:00:00Z"),
            ],
            users={"99": {"email": "bot@srglobal.com"}},
        )
        _outcome, posted, seen = self._run(ctx, _draft(public_body="Hello Ana,\n\nLight snacks are provided."))
        self.assertEqual(posted[0].action, "solve")
        self.assertIn("When is the next MMI?", seen["description"])
        self.assertIn("What about food?", seen["description"])
        self.assertIn("Staff:", seen["description"])

    def test_human_agent_already_on_the_thread_is_left_alone(self) -> None:
        ctx = _ctx(
            comments=[
                _comment("1", "10", "When is it?", at="2026-02-01T00:00:00Z"),
                _comment("2", "77", "Happy to help.", at="2026-02-01T02:00:00Z"),
                _comment("3", "10", "Thanks, one more thing.", at="2026-02-02T00:00:00Z"),
            ],
            users={"77": {"email": "meda.c@srglobal.com"}},
        )

        outcome, posted, seen = self._run(ctx, _draft())
        self.assertEqual(outcome["action"], "solve")
        self.assertEqual(posted[0].action, "solve")
        self.assertIn("one more thing", seen["description"])

    def test_asking_for_a_person_assigns_without_a_draft(self) -> None:
        ctx = _ctx(comments=[_comment("1", "10", "I want to speak to a human being.")])

        def drafter(**_kwargs):
            raise AssertionError("human request must not call the model")

        _outcome, posted, _seen = self._run(ctx, drafter)
        self.assertEqual(posted[0].action, "handoff")
        self.assertEqual(posted[0].assignee_email, "meda.c@srglobal.com")
        self.assertTrue(posted[0].claims_handoff)
        self.assertIn("asked the team", posted[0].public_body)

    def test_backfill_skips_solved_and_existing_public_reply(self) -> None:
        solved, posted, _seen = self._run(_ctx(status="solved"), _draft(), backfill=True, live=False)
        self.assertEqual(posted, [])
        self.assertIn("status is solved", solved["reason"])

        pending, _posted, _seen = self._run(_ctx(status="pending"), _draft(), backfill=True, live=False)
        self.assertIn("pending", pending["reason"])

        replied = _ctx(
            comments=[
                _comment("1", "10", "Hello", at="2026-02-01T00:00:00Z"),
                _comment("2", "99", "Already answered.", at="2026-02-01T01:00:00Z"),
            ]
        )
        skipped, posted, _seen = self._run(replied, _draft(), backfill=True, live=False)
        self.assertEqual(posted, [])
        self.assertIn("agent already replied", skipped["reason"])

    def test_failed_assign_does_not_publish_the_handoff_claim(self) -> None:
        calls = []
        original = (app._put_ticket, app.assign_open_for_human, app.post_ticket_update, app.post_internal_note)

        def put(ticket_id, ticket):
            calls.append(ticket)
            return False, "422 assignee"

        def assign(*_args, **_kwargs):
            return False

        def post(ticket_id, body, **kwargs):
            calls.append({"body": body, **kwargs})
            return True, "ok"

        def note(*_args, **_kwargs):
            return True, "ok"

        app._put_ticket = put
        app.assign_open_for_human = assign
        app.post_ticket_update = post
        app.post_internal_note = note
        try:
            disposition = flow.decide(
                agent="maya",
                lane="mmi",
                needs_human=True,
                matched="generated_needs_human",
                public_body="",
                note_body="internal draft",
                assignee_email="meda.c@srglobal.com",
                reason="needs a person",
            )
            outcome = app._apply_handoff("5", disposition)
        finally:
            app._put_ticket, app.assign_open_for_human, app.post_ticket_update, app.post_internal_note = original
        self.assertFalse(outcome["assigned"])
        self.assertNotIn("teammate", outcome["reply"].lower())
        self.assertNotIn("passed this", outcome["reply"].lower())
        posted = [item for item in calls if isinstance(item, dict) and "body" in item]
        self.assertTrue(posted)
        self.assertNotIn("teammate", posted[0]["body"].lower())
        self.assertNotIn(flow.TAG_ASSIGNED, posted[0]["extra_tags"])

    def test_backfill_recheck_blocks_the_post(self) -> None:
        calls = {"n": 0}

        def loader(_ticket_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return _ctx()
            return _ctx(status="pending")

        outcome, posted, _seen = self._run(_ctx(), _draft(), backfill=True, live=True, loader=loader)
        self.assertEqual(posted, [])
        self.assertIn("recheck", outcome["reason"])
        self.assertIn("pending", outcome["reason"])


class _Tasks:
    def __init__(self) -> None:
        self.jobs = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.jobs.append((func, args, kwargs))


def _post_webhook(raw: bytes) -> tuple[dict, _Tasks]:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/zendesk/webhook",
        "raw_path": b"/zendesk/webhook",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 123),
        "server": ("test", 80),
    }

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    tasks = _Tasks()
    response = asyncio.run(app.zendesk_webhook(Request(scope, receive), tasks))
    for func, args, kwargs in tasks.jobs:
        func(*args, **kwargs)
    return json.loads(response.body), tasks


class WebhookTests(unittest.TestCase):
    def test_malformed_body_is_accepted(self) -> None:
        seen = {}
        original = app._process_ticket

        def fake(ticket_id, hints=None, **kwargs):
            seen["id"] = ticket_id
            return {"action": "skip", "posted": False, "assigned": False, "detail": "test"}

        app._process_ticket = fake
        try:
            raw = (
                '{"id":"48111","ticket_id":"48111","subject":"Help",'
                '"requester_email":"ana@example.com"\n'
                '"latest_comment":"please"}'
            )
            body, tasks = _post_webhook(raw.encode())
            self.assertEqual(body["ticket_id"], "48111")
            self.assertTrue(body["accepted"])
            self.assertEqual(len(tasks.jobs), 1)
            self.assertEqual(seen["id"], "48111")
        finally:
            app._process_ticket = original
            app._release_ticket("48111")

    def test_in_flight_duplicate_is_already_processing(self) -> None:
        self.assertTrue(app._claim_ticket("77"))
        try:
            body, tasks = _post_webhook(b'{"ticket_id":"77","subject":"Hi"}')
            self.assertEqual(body["skipped"], "already processing")
            self.assertEqual(tasks.jobs, [])
        finally:
            app._release_ticket("77")

    def test_garbage_body_has_no_ticket_id(self) -> None:
        body, tasks = _post_webhook(b"not json at all")
        self.assertEqual(body["skipped"], "no ticket id in payload")
        self.assertEqual(tasks.jobs, [])


class BackfillScriptTests(unittest.TestCase):
    def test_csv_id_column(self) -> None:
        path = ROOT / "tests" / "_ids.csv"
        path.write_text("id,subject\n12,Hello\n\n13,Next\n", encoding="utf-8")
        try:
            self.assertEqual(backfill.ids_from_csv(str(path)), ["12", "13"])
        finally:
            path.unlink(missing_ok=True)

    def test_search_pages_are_unioned(self) -> None:
        pages = {
            "search.json?query=one&per_page=100": {
                "results": [{"id": 1, "result_type": "ticket"}],
                "next_page": "https://srglobalhelp.zendesk.com/api/v2/search.json?page=2",
            },
            "search.json?page=2": {
                "results": [{"id": 2, "result_type": "ticket"}, {"id": 1, "result_type": "ticket"}],
            },
        }

        def get_json_real(path):
            if path.startswith("search.json?query="):
                return pages["search.json?query=one&per_page=100"]
            if "page=2" in path:
                return pages["search.json?page=2"]
            return None

        ids = backfill.search_ticket_ids(["one"], get_json_real)
        self.assertEqual(ids, ["1", "2"])

    def test_demo_dry_run_shapes(self) -> None:
        text = []
        for ticket_id, outcome in flow.demo_cases():
            text.append(flow.format_outcome(ticket_id, outcome))
        joined = "\n\n".join(text)
        self.assertIn("ticket 550001", joined)
        self.assertIn("action: solve", joined)
        self.assertIn("Rome has Italian interpretation", joined)
        self.assertIn("posted: no", joined)
        self.assertIn("ticket 550002", joined)
        self.assertIn("action: handoff to alina.last@srglobal.com", joined)
        self.assertIn("ai_draft_only", joined)
        self.assertIn("ai_rafa", joined)
        self.assertNotIn("refund you today", joined.split("internal note:")[0])
        self.assertIn("ticket 550003", joined)
        self.assertIn("action: handoff to meda.c@srglobal.com", joined)
        self.assertIn("asked the team", joined)
        self.assertIn("ai_answered", joined)
        self.assertIn("ai_assigned_human", joined)


if __name__ == "__main__":
    unittest.main()
