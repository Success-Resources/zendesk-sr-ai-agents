"""v10 fixes (Akram, 27 Oct 2026), from the live catch-up run of v9 (Success-Resources main 9060a2a).

Fixtures are anonymised versions of the real tickets.

- 106491 "paid twice", 107666 "$114 back ... processed twice", 107120 Swedish "pengar tillbaka":
  money-back asks without the word refund got a public holding reply. They go to Rafa, internal only.
- 107559: a restaurant chain's points newsletter got a public "Hi Which," reply. Silent close.
- 109175: a seminar question under a "Masterclass" subject got the Masterclass replay text.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402,F401
from test_v6_catchup import _run  # noqa: E402
from agents import loop, routing  # noqa: E402
from service import noise  # noqa: E402

T106491 = "Hello,\n\nI paid twice for the MMI ticket, please check my card statement.\n\nAnna"
T107666 = ("Hi,\n\nThe payment was processed twice on my card. Can I have the $114 back please?\n\nThanks\nAnna\n\n"
           "> On 2 Oct 2026, at 10:00, Millionaire Mind <mmo@srglobal.com> wrote:\n> Hi Anna")
T107120 = "Hej,\n\nJag vill ha mina pengar tillbaka for biljetten.\n\nMvh\nAnna"
T107559_FROM = "rewards@news.examplefoods.co.uk"
T107559 = ("Hi Which Wich fan,\n\nYou have 120 points! Treat yourself this week with a free sandwich?\n"
           "Order now in the app.\n\nView this email in your browser | Manage your preferences | Unsubscribe here")


def _customer_ctx(body, *, subject="Question", email="customer@example.com", name="Anna Example"):
    return _ctx(subject=subject, description=body, tags=[], recipient="mmo@srglobal.com",
                requester_email=email, requester_name=name, comments=[_comment("1", "10", body)])


class MoneyBackTests(unittest.TestCase):
    def test_live_misses_go_to_rafa_without_public_reply(self) -> None:
        for tid, body in (("106491", T106491), ("107666", T107666), ("107120", T107120)):
            with self.subTest(ticket=tid):
                draft = _draft(public_body="Hi Anna,\n\nThank you, the team will look at this.", needs_human=True)
                _o, posted, _seen = _run(_customer_ctx(body), draft)
                d = posted[0]
                self.assertEqual((d.action, d.agent, d.public_body, d.status), ("handoff", "rafa", "", "open"))
                self.assertIn("ai_rafa", d.tags)

    def test_phrases(self) -> None:
        for text in (
            "I paid twice", "I was charged twice for one ticket", "The payment went through twice",
            "you took the money twice", "twice charged on my card", "double payment on my account",
            "I was double billed", "duplicate payment", "Can I get the €50 back?", "please send 114 USD back",
            "Jag vill ha pengarna tillbaka", "Jeg vil ha pengene tilbake (tilbakebetaling)", "refusjon takk",
            "Jeg vil have mine penge tilbage", "Haluan rahat takaisin", "hyvitys", "Proszę o zwrot pieniędzy",
            "visszatérítést kérek", "Solicit rambursarea", "Žádám o vrácení peněz", "Прошу возврат денег",
            "para iadesi istiyorum", "Request for Cancellation of Purchase",
            "Unfortunately I need to cancel my 100 Stategies too. I am still very sick.",
            "I want to cancel my coaching program", "I would like to cancel the course",
        ):
            with self.subTest(text=text):
                self.assertTrue(routing.refund_ask(text))
                self.assertEqual(routing.owner(text), "rafa")

    def test_not_money_back(self) -> None:
        for text in (
            "I tried to log in twice", "I emailed you twice about the venue", "When is the next MMI?",
            "Can I pay in two instalments?", "I will be back in Berlin in May", "I paid, where is my ticket?",
            "Jag har en fråga om biljetten", "Kommer jag tillbaka nästa år?", "Can I bring my friend back stage?",
            "Can I cancel my hotel booking through you?", "I had to cancel my flight, will the event be recorded?",
        ):
            with self.subTest(text=text):
                self.assertFalse(routing.refund_ask(text))


class NewsletterTests(unittest.TestCase):
    def test_107559_points_newsletter_is_silent(self) -> None:
        self.assertEqual(noise.classify(sender=T107559_FROM, subject="Your treat is waiting", text=T107559),
                         "noise_marketing")
        ctx = _customer_ctx(T107559, subject="Your treat is waiting", email=T107559_FROM, name="Which Wich")
        _o, posted, _seen = _run(ctx, _draft(public_body="Hi Which,\n\nThanks."))
        self.assertEqual(posted[0].action, "solve_silent")
        self.assertEqual(posted[0].public_body, "")

    def test_customers_are_not_newsletters(self) -> None:
        footer = "\n\nView this email in your browser | Manage your preferences"
        cases = (
            ("anna@gmail.com", "Question", "Where is the venue?" + footer),  # personal domain
            ("anna@company.example", "Re: Your MMI ticket", "Where is the venue?" + footer),  # a reply
            ("anna@company.example", "Ticket", "I bought a ticket, where is it?" + footer),  # own order
            ("anna@company.example", "Question", "Where is the venue?"),  # no footer
            ("events@srglobal.com", "Newsletter", "News" + footer),  # our own domain
        )
        for sender, subject, body in cases:
            with self.subTest(sender=sender, subject=subject):
                self.assertFalse(noise.third_party_newsletter(sender, subject, body))


class MasterclassTextTests(unittest.TestCase):
    S = "Re: Congrats for registering for the Millionaire Mind Masterclass"

    def _correct(self, subject, body):
        return loop._correct_maya("", True, "ok", subject, body, "Anna Example", "")

    def test_109175_seminar_question_under_masterclass_subject(self) -> None:
        body = "Hello, I bought a seminar earlier this year with you in Manchester but cannot find the information."
        text, _needs, reason = self._correct(self.S, body)
        self.assertNotEqual(reason, "masterclass_handoff")
        self.assertNotIn("Masterclass replay", text)

    def test_99742_masterclass_checkout_problem_is_not_replay(self) -> None:
        body = ("I've watched Stephen webinar. Then I decided to sign his masterclass at the cart. After providing my "
                "bank card details the payment does not proceed. It has been 10 minutes showing: Processing.")
        text, _needs, reason = self._correct("Signing program: 100 Points Strategy Masterclass", body)
        self.assertNotEqual(reason, "masterclass_handoff")
        self.assertNotIn("Masterclass replay", text)

    def test_94252_webinar_in_signature_is_not_replay(self) -> None:
        body = ("Hallo Success Ressources, Do you have an Early Bird Code for that event? I might be going with my team "
                "Greetings, Maria. SUPER AKTUELL - ZAHNGESUNDHEITS-WEBINAR am 12.07. Anmeldung hier")
        text, _needs, reason = self._correct("Do you have a Early Bird Code : Rotterdam, time to 10X your sales", body)
        self.assertNotEqual(reason, "masterclass_handoff")
        self.assertNotIn("Masterclass replay", text)

    def test_replay_text_still_used_for_access_problems(self) -> None:
        for subject, body in (
            (self.S, "The replay link does not work, I can't watch it."),
            ("Question", "Where can I find the masterclass recording?"),
            ("Question", "I missed the webinar yesterday"),
        ):
            with self.subTest(body=body):
                _text, _needs, reason = self._correct(subject, body)
                self.assertEqual(reason, "masterclass_handoff")


if __name__ == "__main__":
    unittest.main()
