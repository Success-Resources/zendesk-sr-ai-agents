"""KB sync 0011: facts from Meda/Alina replies and Evelin's audit load from both hub copies."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT))

import knowledge  # noqa: E402


class KbSyncTests(unittest.TestCase):
    def test_hub_copies_identical(self):
        for name in ("maya.md", "quinn.md"):
            a = (ROOT / "knowledge-hub/00-current-facts" / name).read_text(encoding="utf-8")
            b = (ROOT / "service/knowledge-hub/00-current-facts" / name).read_text(encoding="utf-8")
            self.assertEqual(a, b, name)

    def test_new_maya_facts_load(self):
        qs = {e.question for e in knowledge.load_entries("maya", refresh=False)}
        for q in ("When is MMI Warsaw", "Can I attend MMI online", "Can I join the crew"):
            self.assertIn(q, qs)

    def test_quinn_current_facts_load(self):
        es = [e for e in knowledge.load_entries("quinn", refresh=False) if "00-current-facts" in e.path]
        self.assertEqual(len(es), 5)
        self.assertTrue(any("7-10 January 2027" in e.email for e in es))

    def test_no_brussels_interpretation_claim(self):
        text = (ROOT / "knowledge-hub/00-current-facts/maya.md").read_text(encoding="utf-8")
        self.assertIn("Brussels does not have interpretation", text)


if __name__ == "__main__":
    unittest.main()
