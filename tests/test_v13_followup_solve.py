"""v13 (Akram, 27 Oct): every customer reply is re-checked against the hub.

Maya answers and solves again when she can (reassigned to Akram with a prev_assignee tag),
and hands off to Meda or Alina only when the hub has no answer. Quinn, Rafa and booking
changes stay as they are.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

os.environ["ZENDESK_MMI_ASSIGNEE_EMAIL"] = "meda.c@srglobal.com"
os.environ["ZENDESK_MMO_ASSIGNEE_EMAIL"] = "alina.last@srglobal.com"

import flow  # noqa: E402
import app  # noqa: E402

BOT = "bot@srglobal.com"
BOT_ID = "900"
USERS = {BOT_ID: {"id": 900, "email": BOT}, flow.ALINA_ID: {"id": 1, "email": flow.ALINA_EMAIL}}


def _c(cid, author, body, at, public=True):
    return flow.Comment(id=cid, author_id=author, public=public, body=body, created_at=at)


HOLDING = "Hi Ana,\n\nThank you for your message. I have asked the team to look at this, and they will follow up from here."


def _ctx(**over):
    ctx = {
        "subject": "Re: MMI Online",
        "description": "When does the online event start?",
        "tags": ["mmi", "ai_assigned_human", "ai_public_reply"],
        "recipient": "mmo@srglobal.com",
        "status": "open",
        "assignee_id": flow.ALINA_ID,
        "requester_id": "10",
        "requester_email": "ana@example.com",
        "requester_name": "Ana",
        "comments_ok": True,
        "comments": [
            _c("1", "10", "When does the online event start?", "2026-10-27T08:00:00Z"),
            _c("2", BOT_ID, HOLDING, "2026-10-27T08:01:00Z"),
            _c("3", BOT_ID, "staff note", "2026-10-27T08:01:01Z", public=False),
            _c("4", "10", "Also, what time does it start in Berlin?", "2026-10-27T09:00:00Z"),
        ],
        "users": dict(USERS),
    }
    ctx.update(over)
    return ctx


def _draft(**over):
    data = dict(
        agent="maya",
        matched="generated",
        extra_tags=[],
        note_body="staff note",
        public_body="Hi Ana,\n\nThe online event starts at 09:00 CET, which is 09:00 in Berlin.",
        needs_human=False,
        reason="ok",
    )
    data.update(over)
    return flow.Draft(**data)


def _run(ctx, draft, live=True):
    posted, seen = [], {}

    def poster(ticket_id, disposition):
        posted.append(disposition)
        return {"action": disposition.action, "posted": True, "tags": list(disposition.tags)}

    def drafter(**kw):
        seen["description"] = kw.get("description")
        return draft

    out = app._process_ticket("110900", live=live, loader=lambda _t: ctx, drafter=drafter, poster=poster, bot_email=BOT)
    return out, posted, seen


class PrevTagTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(flow.prev_assignee_tag(flow.MEDA_ID), "prev_assignee_meda")
        self.assertEqual(flow.prev_assignee_tag("", flow.MEDA_EMAIL), "prev_assignee_meda")
        self.assertEqual(flow.prev_assignee_tag(flow.ALINA_ID), "prev_assignee_alina")
        self.assertEqual(flow.prev_assignee_tag(""), "prev_assignee_none")
        self.assertEqual(flow.prev_assignee_tag("400349897534"), "prev_assignee_400349897534")

    def test_already_maya_keeps_earlier_tag(self):
        self.assertEqual(flow.prev_assignee_tag(BOT_ID, BOT, BOT_ID, ["prev_assignee_alina"]), "")
        self.assertEqual(flow.prev_assignee_tag(BOT_ID, BOT, BOT_ID, []), "prev_assignee_" + BOT_ID)

    def test_is_followup(self):
        ctx = _ctx()
        self.assertTrue(flow.is_followup(ctx["comments"], "10"))
        self.assertFalse(flow.is_followup(ctx["comments"][:1], "10"))
        self.assertFalse(flow.is_followup(ctx["comments"][:3], "10"))


class FollowupTests(unittest.TestCase):
    def test_reply_after_handoff_is_answered_and_solved_under_akram(self):
        out, posted, seen = _run(_ctx(), _draft())
        d = posted[0]
        self.assertEqual(d.action, "solve")
        self.assertEqual(d.status, "solved")
        self.assertEqual(d.solve_owner_email, BOT)
        self.assertIn("prev_assignee_alina", d.tags)
        self.assertIn(flow.TAG_FOLLOWUP, d.tags)
        self.assertIn("hand off only when it does not", seen["description"])
        self.assertIn("what time does it start in Berlin", seen["description"])

    def test_every_later_reply_is_solved_again(self):
        comments = _ctx()["comments"] + [
            _c("5", BOT_ID, "Hi Ana,\n\nIt starts at 09:00 CET.", "2026-10-27T09:01:00Z"),
            _c("6", "10", "And how long does day one last?", "2026-10-27T10:00:00Z"),
        ]
        ctx = _ctx(assignee_id=BOT_ID, status="open", comments=comments, tags=["mmi", "prev_assignee_alina", "ai_solved"])
        out, posted, _ = _run(ctx, _draft(public_body="Hi Ana,\n\nDay one runs from 09:00 to 18:00 CET."))
        d = posted[0]
        self.assertEqual(d.action, "solve")
        self.assertEqual(d.solve_owner_email, BOT)
        self.assertEqual([t for t in d.tags if t.startswith("prev_assignee_")], [])

    def test_no_hub_answer_hands_off_open_to_alina(self):
        out, posted, _ = _run(_ctx(), _draft(public_body="", needs_human=True, reason="not in hub"))
        d = posted[0]
        self.assertEqual(d.action, "handoff")
        self.assertEqual(d.status, "open")
        self.assertEqual(d.assignee_email, flow.ALINA_EMAIL)
        self.assertEqual(d.solve_owner_email, "")
        self.assertFalse(any(t.startswith("prev_assignee_") for t in d.tags))

    def test_no_hub_answer_on_mmi_goes_to_meda(self):
        ctx = _ctx(recipient="info.eu@srglobal.com", assignee_id="")
        out, posted, _ = _run(ctx, _draft(public_body="I will check and get back to you.", needs_human=False))
        self.assertEqual(posted[0].action, "handoff")
        self.assertEqual(posted[0].assignee_email, flow.MEDA_EMAIL)

    def test_quinn_followup_stays_internal(self):
        comments = _ctx()["comments"][:3] + [_c("4", "10", "Can I move my Quantum Leap seat to 2027?", "2026-10-27T09:00:00Z")]
        out, posted, _ = _run(_ctx(comments=comments), _draft(agent="quinn", public_body="Hi Ana,\n\nYes."))
        d = posted[0]
        self.assertEqual(d.action, "handoff")
        self.assertEqual(d.solve_owner_email, "")

    def test_refund_followup_stays_with_rafa(self):
        comments = _ctx()["comments"][:3] + [_c("4", "10", "Actually I want a refund please.", "2026-10-27T09:00:00Z")]
        out, posted, _ = _run(_ctx(comments=comments), _draft(public_body="Hi Ana,\n\nSure."))
        self.assertEqual(posted[0].action, "handoff")
        self.assertEqual(posted[0].agent, "rafa")

    def test_booking_change_followup_goes_to_meda(self):
        comments = _ctx()["comments"][:3] + [_c("4", "10", "Can I postpone my ticket to a different date?", "2026-10-27T09:00:00Z")]
        out, posted, _ = _run(_ctx(comments=comments), _draft(public_body="Hi Ana,\n\nSure."))
        self.assertEqual(posted[0].action, "handoff")
        self.assertEqual(posted[0].assignee_email, flow.MEDA_EMAIL)

    def test_first_answer_is_also_owned(self):
        ctx = _ctx(assignee_id="", comments=_ctx()["comments"][:1], tags=["mmi"])
        out, posted, _ = _run(ctx, _draft())
        self.assertEqual(posted[0].solve_owner_email, BOT)
        self.assertIn("prev_assignee_none", posted[0].tags)
        self.assertNotIn(flow.TAG_FOLLOWUP, posted[0].tags)

    def test_noise_solve_is_owned(self):
        d = flow.decide(agent="maya", lane="mmi", needs_human=False, matched="no_reply", public_body="", note_body="", assignee_email="", noise_tag="noise_marketing")
        d = app._owned(d, _ctx(assignee_id=flow.MEDA_ID), BOT)
        self.assertEqual(d.solve_owner_email, BOT)
        self.assertIn("prev_assignee_meda", d.tags)


class ApplyTests(unittest.TestCase):
    def test_solve_puts_assignee_and_tags_in_second_call(self):
        calls = []
        with mock.patch.object(app, "_put_ticket_raw", side_effect=lambda t, b: (calls.append(("put", b)) or (True, "200"))), \
             mock.patch.object(app, "_add_tags", side_effect=lambda t, tags: (calls.append(("tags", tags)) or (True, "200"))):
            d = flow.Disposition(action="solve", public_body="Hi Ana,\n\nAnswer.", status="solved",
                                 tags=["ai_solved", "prev_assignee_alina"], solve_owner_email=BOT)
            app._apply_disposition("110900", d)
        self.assertEqual(calls[0][0], "put")
        self.assertEqual(calls[0][1]["status"], "solved")
        self.assertEqual(calls[0][1]["assignee_email"], BOT)
        self.assertTrue(calls[0][1]["comment"]["public"])
        self.assertEqual(calls[1], ("tags", ["ai_solved", "prev_assignee_alina"]))

    def test_silent_solve_puts_assignee(self):
        calls = []
        with mock.patch.object(app, "_put_ticket_raw", side_effect=lambda t, b: (calls.append(b) or (True, "200"))), \
             mock.patch.object(app, "_add_tags", return_value=(True, "200")):
            app._apply_disposition("110900", flow.Disposition(action="solve_silent", tags=["x"], solve_owner_email=BOT))
        self.assertEqual(calls[0], {"status": "solved", "assignee_email": BOT})

    def test_handoff_does_not_take_owner(self):
        d = flow.Disposition(action="handoff", status="open", assignee_email=flow.ALINA_EMAIL)
        d = flow.with_solve_owner(d, BOT, "prev_assignee_alina")
        self.assertEqual(d.solve_owner_email, "")
        self.assertNotIn("prev_assignee_alina", d.tags)


if __name__ == "__main__":
    unittest.main()
