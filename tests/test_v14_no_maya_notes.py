"""v14 (Akram, 27 Oct): Maya leaves no internal notes.

Her handoffs to Meda or Alina only assign, set the lane tags and leave the ticket open.
Quinn and Rafa keep their internal-note drafts.
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


class _Calls:
    def __init__(self):
        self.notes, self.tags, self.assigns, self.puts = [], [], [], []

    def patches(self):
        return [
            mock.patch.object(app, "post_internal_note", side_effect=lambda t, b, tags=None: (self.notes.append((b, tags)) or (True, "200"))),
            mock.patch.object(app, "_add_tags", side_effect=lambda t, tags: (self.tags.append(list(tags)) or (True, "200"))),
            mock.patch.object(app, "assign_open_for_human", side_effect=lambda t, h, a=None, force=False: (self.assigns.append(a) or True)),
            mock.patch.object(app, "_put_ticket", side_effect=lambda t, b: (self.puts.append(b) or (True, "200"))),
            mock.patch.object(app, "_ensure_open", return_value=None),
        ]


def _apply(disposition):
    calls = _Calls()
    ps = calls.patches()
    for p in ps:
        p.start()
    try:
        out = app._apply_disposition("110900", disposition)
    finally:
        for p in ps:
            p.stop()
    return out, calls


class NoMayaNoteTests(unittest.TestCase):
    def test_maya_no_answer_handoff_assigns_tags_no_note(self):
        d = flow.Disposition(action="handoff", agent="maya", internal_note="Staff only: draft",
                             status="open", assignee_email=flow.ALINA_EMAIL, tags=["ai_assigned_human", "ai_maya"], lane="mmo")
        out, calls = _apply(d)
        self.assertEqual(calls.notes, [])
        self.assertEqual(calls.assigns, [flow.ALINA_EMAIL])
        self.assertIn(["ai_assigned_human", "ai_maya"], calls.tags)
        self.assertTrue(out["assigned"])

    def test_maya_handoff_with_holding_reply_posts_no_note(self):
        d = flow.Disposition(action="handoff", agent="maya", public_body="Hi Ana,\n\n" + flow.HOLDING_BODY,
                             internal_note="Staff only", status="open", assignee_email=flow.MEDA_EMAIL,
                             tags=["ai_assigned_human"], lane="mmi", claims_handoff=True)
        out, calls = _apply(d)
        self.assertEqual(calls.notes, [])
        self.assertEqual(calls.puts[0]["status"], "open")
        self.assertEqual(calls.puts[0]["assignee_email"], flow.MEDA_EMAIL)
        self.assertFalse(any(not p.get("comment", {}).get("public", True) for p in calls.puts))

    def test_maya_internal_draft_has_no_note(self):
        d = flow.Disposition(action="internal_draft", agent="maya", internal_note="draft", tags=["ai_draft_only"], lane="mmi")
        out, calls = _apply(d)
        self.assertEqual(calls.notes, [])
        self.assertEqual(calls.tags, [["ai_draft_only"]])

    def test_quinn_keeps_note(self):
        d = flow.Disposition(action="handoff", agent="quinn", internal_note="Quinn draft", status="open",
                             assignee_email=flow.MEDA_EMAIL, tags=["ai_quinn", "ai_draft_only"], lane="mmi")
        out, calls = _apply(d)
        self.assertEqual(len(calls.notes), 1)
        self.assertEqual(calls.notes[0][0], "Quinn draft")
        self.assertIn("ai_quinn", calls.notes[0][1])

    def test_rafa_keeps_note(self):
        d = flow.Disposition(action="handoff", agent="rafa", internal_note="Rafa draft", status="open",
                             assignee_email=flow.ALINA_EMAIL, tags=["ai_rafa"], lane="mmo")
        out, calls = _apply(d)
        self.assertEqual([n[0] for n in calls.notes], ["Rafa draft"])

    def test_decide_maya_handoff_dry_run_shows_no_note(self):
        d = flow.decide(agent="maya", lane="mmi", needs_human=True, matched="generated_needs_human",
                        public_body="", note_body="Staff only — draft", assignee_email=flow.MEDA_EMAIL, reason="not in hub")
        plan = app._plan(d)
        self.assertEqual(plan["action"], "handoff")
        self.assertEqual(plan["internal_note"], "")
        self.assertEqual(plan["assignee"], flow.MEDA_EMAIL)

    def test_booking_change_goes_to_meda_without_note(self):
        import test_v13_followup_solve as v13
        comments = v13._ctx()["comments"][:3] + [v13._c("4", "10", "Can I postpone my ticket to a different date?", "2026-10-27T09:00:00Z")]
        out, posted, _ = v13._run(v13._ctx(comments=comments), v13._draft(public_body="Hi Ana,\n\nSure."), live=False)
        self.assertEqual(out["action"], "handoff")
        self.assertEqual(out["assignee"], flow.MEDA_EMAIL)
        self.assertEqual(out["internal_note"], "")


if __name__ == "__main__":
    unittest.main()
