"""v11 (Akram, 27 Oct 2026): holding texts in the customer's language.

The v10 catch-up sent the English holding text to Dutch, German, French, Spanish, Italian,
Portuguese and Chinese customers. Fixed holding sentences now follow the customer's language for
nl/de/fr/es/it/pt. Any other language, mixed text, or a reply that is not purely fixed sentences
stays English. The greeting ("Hi <first name>," / "Hi there,") never changes.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402,F401
from test_v6_catchup import _run  # noqa: E402
from agents import i18n, publictext  # noqa: E402

SAMPLES = {
    "nl": "Hallo, ik heb een vraag over mijn ticket voor het evenement. Kunt u mij laten weten wanneer het begint? Alvast bedankt, Jan",
    "de": "Hallo, ich habe eine Frage zu meinem Ticket. Können Sie mir bitte sagen, wann die Veranstaltung beginnt? Vielen Dank, Anna",
    "fr": "Bonjour, j'ai une question sur mon billet. Pouvez-vous me dire quand commence l'événement ? Merci beaucoup, Marie",
    "es": "Hola, tengo una pregunta sobre mi entrada. ¿Puede decirme cuándo empieza el evento? Muchas gracias, Ana",
    "it": "Buongiorno, ho una domanda sul mio biglietto. Può dirmi quando inizia l'evento? Grazie mille, Giulia",
    "pt": "Olá, tenho uma pergunta sobre o meu bilhete. Pode dizer-me quando começa o evento? Muito obrigado, João",
}
ENGLISH = "Hello, I have a question about my ticket. Can you please tell me when the event starts? Thanks, Anna"


def _ctx_for(body, name="Anna Example"):
    return _ctx(subject="Question", description=body, tags=[], recipient="mmo@srglobal.com",
                requester_email="customer@example.com", requester_name=name, comments=[_comment("1", "10", body)])


def _holding():
    return _draft(public_body="Hi there,\n\nThanks, the team will look at this.", needs_human=True,
                  note_body="Hello,\n\nDraft for the team.")


class DetectTests(unittest.TestCase):
    def test_samples(self) -> None:
        for lang, text in SAMPLES.items():
            with self.subTest(lang=lang):
                self.assertEqual(i18n.detect_language(text), lang)

    def test_english_and_unsupported_fall_back(self) -> None:
        for text in (ENGLISH, "请不要再给我发了啊，要不然我要投诉你", "Hej, jag har en fråga om biljetten.", "", "Ok thanks",
                     "Hi, quick question about the Amsterdam event: is parking available? Thanks"):
            with self.subTest(text=text[:30]):
                self.assertEqual(i18n.detect_language(text), "en")

    def test_quoted_reply_does_not_count(self) -> None:
        text = ("Thanks, I will be there. Can you please send the address?\n\n"
                "> Op 2 okt 2026 schreef het team: Hallo, wij hebben een vraag voor u over het evenement en de tickets")
        self.assertEqual(i18n.detect_language(text), "en")


class LocalizeTests(unittest.TestCase):
    def test_every_fixed_text_has_every_language(self) -> None:
        for en, langs in i18n.TEXTS.items():
            for lang in i18n.SUPPORTED:
                with self.subTest(en=en[:30], lang=lang):
                    self.assertTrue(langs.get(lang))

    def test_fixed_texts_match_flow_and_publictext(self) -> None:
        self.assertEqual(i18n.HOLDING, flow.HOLDING_BODY)
        self.assertEqual(i18n.ACCESS, flow.ACCESS_HOLDING_BODY)
        self.assertEqual(i18n.BOOKING, flow.BOOKING_HOLDING_BODY)
        self.assertEqual(i18n.APOLOGY, publictext.LONG_WAIT_APOLOGY)

    def test_holding_is_translated_greeting_kept(self) -> None:
        for lang, text in SAMPLES.items():
            with self.subTest(lang=lang):
                body, used = i18n.localize_holding(f"Hi Jan,\n\n{flow.HOLDING_BODY}", text)
                self.assertEqual(used, lang)
                self.assertEqual(body, f"Hi Jan,\n\n{i18n.TEXTS[flow.HOLDING_BODY][lang]}")

    def test_apology_plus_holding(self) -> None:
        src = publictext.with_long_wait_apology(f"Hi there,\n\n{flow.ACCESS_HOLDING_BODY}")
        body, used = i18n.localize_holding(src, SAMPLES["de"])
        self.assertEqual(used, "de")
        self.assertEqual(body, "Hi there,\n\n" + i18n.TEXTS[i18n.APOLOGY]["de"] + "\n\n" + i18n.TEXTS[i18n.ACCESS]["de"])

    def test_drafted_answers_are_never_translated(self) -> None:
        src = "Hi Jan,\n\nThe event starts at 9:00 in the Jaarbeurs, Utrecht."
        self.assertEqual(i18n.localize_holding(src, SAMPLES["nl"]), (src, "en"))
        mixed = f"Hi Jan,\n\n{flow.HOLDING_BODY}\n\nThe venue is the Jaarbeurs."
        self.assertEqual(i18n.localize_holding(mixed, SAMPLES["nl"]), (mixed, "en"))

    def test_english_customer_keeps_english(self) -> None:
        src = f"Hi Anna,\n\n{flow.HOLDING_BODY}"
        self.assertEqual(i18n.localize_holding(src, ENGLISH), (src, "en"))


class EndToEndTests(unittest.TestCase):
    def test_dutch_customer_gets_dutch_holding(self) -> None:
        _o, posted, _s = _run(_ctx_for(SAMPLES["nl"], name="Jan de Vries"), _holding())
        body = posted[0].public_body
        self.assertTrue(body.startswith("Hi Jan,\n\n"), body)
        self.assertIn(i18n.TEXTS[flow.HOLDING_BODY]["nl"], body)
        self.assertIn("ai_lang_nl", posted[0].tags)

    def test_french_customer_with_long_wait_apology(self) -> None:
        with mock.patch.dict(os.environ, {"LONG_WAIT_APOLOGY": ""}):
            _o, posted, _s = _run(_ctx_for(SAMPLES["fr"], name="Marie Dupont"), _holding(), hints={"long_wait_apology": True})
        body = posted[0].public_body
        self.assertTrue(body.startswith("Hi Marie,\n\n"), body)
        self.assertIn(i18n.TEXTS[i18n.APOLOGY]["fr"], body)
        self.assertNotIn("Thank you", body)
        self.assertIn("ai_long_wait_apology", posted[0].tags)

    def test_english_customer_unchanged(self) -> None:
        _o, posted, _s = _run(_ctx_for(ENGLISH), _holding())
        self.assertEqual(posted[0].public_body, f"Hi Anna,\n\n{flow.HOLDING_BODY}")
        self.assertFalse([t for t in posted[0].tags if t.startswith("ai_lang_")])

    def test_chinese_customer_falls_back_to_english(self) -> None:
        _o, posted, _s = _run(_ctx_for("请问活动什么时候开始？谢谢"), _holding())
        self.assertIn(flow.HOLDING_BODY, posted[0].public_body)


if __name__ == "__main__":
    unittest.main()
