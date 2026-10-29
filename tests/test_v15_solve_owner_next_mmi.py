"""v15 (Akram, 29 Oct): solves follow the API account in ZENDESK_EMAIL (now Evelin), and the
hub answers "when is the next MMI" with Birmingham, Brussels, and Rome."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

import flow  # noqa: E402
import app  # noqa: E402
import knowledge  # noqa: E402
from agents import facts  # noqa: E402

EVELIN = "evelin.voigt@srglobal.com"
EVELIN_ID = "15557864239769"
AKRAM_ID = "60727819819161"


def _solve():
    return flow.Disposition(action="solve", agent="maya", lane="mmi", public_body="Hello", tags=["ai_generated"])


class SolveOwnerTests(unittest.TestCase):
    def setUp(self):
        app._bot_ids.clear()

    def test_bot_email_comes_from_env(self):
        with mock.patch.dict(os.environ, {"ZENDESK_EMAIL": " Evelin.Voigt@srglobal.com "}):
            self.assertEqual(app._bot_email(), EVELIN)

    def test_solve_goes_to_env_account_with_prev_assignee(self):
        ctx = {"assignee_id": flow.MEDA_ID, "users": {}, "tags": [], "comments": [], "requester_id": AKRAM_ID}
        with mock.patch.object(app, "_zendesk_get", return_value={"user": {"id": int(EVELIN_ID), "email": EVELIN}}):
            d = app._owned(_solve(), ctx, EVELIN)
        self.assertEqual(d.solve_owner_email, EVELIN)
        self.assertIn("prev_assignee_meda", d.tags)

    def test_bot_id_falls_back_to_users_me_and_is_cached(self):
        with mock.patch.object(app, "_zendesk_get", return_value={"user": {"id": int(EVELIN_ID), "email": EVELIN}}) as get:
            self.assertEqual(app._bot_user_id({"users": {}}, EVELIN), EVELIN_ID)
            self.assertEqual(app._bot_user_id({"users": {}}, EVELIN), EVELIN_ID)
        get.assert_called_once_with("users/me.json")

    def test_users_me_for_another_account_is_ignored(self):
        with mock.patch.object(app, "_zendesk_get", return_value={"user": {"id": int(AKRAM_ID), "email": "someone@else.com"}}):
            self.assertEqual(app._bot_user_id({"users": {}}, EVELIN), "")

    def test_reply_under_own_solve_keeps_earlier_tag(self):
        ctx = {"assignee_id": EVELIN_ID, "users": {}, "tags": ["prev_assignee_meda"], "comments": [], "requester_id": AKRAM_ID}
        with mock.patch.object(app, "_zendesk_get", return_value={"user": {"id": int(EVELIN_ID), "email": EVELIN}}):
            d = app._owned(_solve(), ctx, EVELIN)
        self.assertEqual(d.solve_owner_email, EVELIN)
        self.assertFalse(any(t.startswith("prev_assignee_") for t in d.tags))

    def test_no_hard_coded_akram_owner(self):
        src = (ROOT / "service/app.py").read_text(encoding="utf-8") + (ROOT / "service/flow.py").read_text(encoding="utf-8")
        self.assertNotIn(AKRAM_ID, src)


class NextMmiTests(unittest.TestCase):
    """Reads the bundled hub in this checkout, not the live GitHub copy."""

    def setUp(self):
        self._saved = knowledge._hub_dir
        knowledge._hub_dir = knowledge.bundled_hub()
        patcher = mock.patch.object(knowledge, "ensure_hub", return_value=knowledge._hub_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        knowledge._hub_dir = self._saved

    def test_hub_copies_identical(self):
        a = (ROOT / "knowledge-hub/00-current-facts/maya.md").read_text(encoding="utf-8")
        b = (ROOT / "service/knowledge-hub/00-current-facts/maya.md").read_text(encoding="utf-8")
        self.assertEqual(a, b)

    def test_next_mmi_question_matches_new_entry(self):
        entry, score = knowledge.best_match("maya", "test", "when is the next MMI ?")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.question, "When is the next MMI")
        self.assertIn("6-8 November 2026", entry.email)
        self.assertIn("Birmingham, United Kingdom", entry.email)
        self.assertIn("20-22 November 2026", entry.email)
        self.assertIn("Brussels, Belgium", entry.email)
        self.assertIn("Crowne Plaza Brussels Airport by IHG", entry.email)
        self.assertIn("4-6 December 2026", entry.email)
        self.assertIn("Rome, Italy", entry.email)

    def test_oslo_question_still_matches_oslo(self):
        entry, _ = knowledge.best_match("maya", "", "When is the next MMI Oslo?")
        self.assertEqual(entry.question, "When is the next MMI Oslo")

    def test_prompt_block_has_next_events(self):
        block = facts.prompt_block()
        self.assertIn("next MMI events are Birmingham, United Kingdom, 6-8 November 2026", block)
        self.assertIn("Brussels, Belgium, 20-22 November 2026", block)
        self.assertIn("Crowne Plaza Brussels Airport by IHG", block)
        self.assertIn("Rome, Italy, 4-6 December 2026", block)


if __name__ == "__main__":
    unittest.main()
