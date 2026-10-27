"""v12: accent-folded Quinn check (107110) and short French/other messages detected by greetings."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

from agents import i18n, routing  # noqa: E402
import knowledge  # noqa: E402

MSG_107110 = "Bonjour,\nJe souhaite faire Train the Tra\u00eener en 2027\n\nMerci\n\nLouisa"


class V12Tests(unittest.TestCase):
    def test_accented_ttt_is_quinn(self):
        self.assertTrue(routing.ql_family(MSG_107110))
        self.assertEqual(routing.owner(MSG_107110, ""), "quinn")
        self.assertEqual(knowledge.route_agent("", "", MSG_107110), "quinn")

    def test_fold(self):
        self.assertEqual(routing.fold("Tra\u00eener \u00e9t\u00e9"), "Trainer ete")

    def test_short_french(self):
        self.assertEqual(i18n.detect_language(MSG_107110), "fr")
        self.assertEqual(i18n.detect_language("Bonjour, je n'ai pas re\u00e7u mon billet. Merci"), "fr")

    def test_short_others(self):
        self.assertEqual(i18n.detect_language("Hola, no tengo mi entrada. Saludos"), "es")
        self.assertEqual(i18n.detect_language("Guten Tag, ich habe kein Ticket. Viele Gr\u00fc\u00dfe"), "de")

    def test_english_stays_english(self):
        self.assertEqual(i18n.detect_language("Hi, I have not received my ticket for the event. Thanks"), "en")
        self.assertEqual(i18n.detect_language("Merci"), "en")
        self.assertEqual(i18n.detect_language(""), "en")
        self.assertEqual(i18n.detect_language("Hello team, merci beaucoup for the help with my booking, I will see you there and thank you"), "en")

    def test_another_session_replay_is_not_booking_change(self):
        self.assertFalse(routing.booking_change("Pls give me another session bcoz I m working today"))
        self.assertFalse(routing.booking_change("Hello\n\nDo we have another session for this?\n\nMissed it."))

    def test_another_session_with_ticket_is_booking_change(self):
        self.assertTrue(routing.booking_change("I bought a ticket but can I move to another session?"))
        self.assertTrue(routing.booking_change("Can I attend a different date instead?"))

    def test_plain_trainer_word_not_quinn(self):
        self.assertFalse(routing.ql_family("My personal trainer said hello"))


if __name__ == "__main__":
    unittest.main()
