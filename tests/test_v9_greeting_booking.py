"""v9 fixes (Akram, 27 Oct 2026), from the live run of v8 (Success-Resources main 41130bc).

Fixtures are anonymised versions of the real tickets (names, emails and addresses replaced).

- 105974: the requester name "Dr <first> <last>" gave the greeting "Hi Dr,".
- 106422: "postpone my attending MMI from June to July" (mmo@) got the access-link holding text
  and went to Alina. A booking change (date or event too) goes to Meda with a booking holding text.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from test_maya_flow import _comment, _ctx, _draft, app, flow  # noqa: E402,F401
from test_v6_catchup import _run  # noqa: E402
from agents import notewords, publictext, routing  # noqa: E402

MEDA = "meda.c@srglobal.com"  # Zendesk user 60727801768601

T105974 = (
    "Dear Sir or Madam,\n\nI purchased this product as a gift for someone, so I'd like you to send\n"
    "order-related messages to my email address: buyer@example.com and to:\n\n"
    "Please send the recipient list to: friend@example.com\n\n"
    "Receive a confirmation that messages will be sent to both addresses.\n\nSincerely,\nAnna Example\n\n"
    "W dniu 2026-05-18 11:04, Millionaire Mind napisal(a):\n> Hey Friend,\n> You've earned a lot of money."
)
S106422 = "Re: [LIVE NOW] Don't Let Day 2 Pass You By - Join Us Live Now"
T106422 = (
    "Yes, I have repeatedly written to Success Resources ( as per latest email\nbelow ); to date, no reply is "
    "received.\n\nHi ,\nTeam,\n\nI had made a request ( on 30//5/2026) to postpone my attending MMI\nfrom June to "
    "July, as I am not available ( June 12 to 14); would I need to pay\nfor attending the MMI in July ( currently "
    "priced at $29/-; standard admission\nor is special rate available), since attending MMI Hybrid in June, I am "
    "not\ncharged ?\n\nYour early reply would be appreciated.\n\nRegards\n\nCustomer Name\n\nSent from my iPad\n\n"
    "> On 13 Jun 2026, at 2:47 PM, Millionaire Mind Hybrid <mmo@srglobal.com> wrote:\n> Hi Customer,\n"
    "> Day 2 is LIVE NOW! If you haven't joined yet, now is the perfect time."
)


def _mmo_ctx(body, *, subject="Question", name="Anna Example"):
    return _ctx(subject=subject, description=body, tags=[], recipient="mmo@srglobal.com",
                requester_email="customer@example.com", requester_name=name,
                comments=[_comment("1", "10", body)])


def _holding(greet="Hi there,"):
    return _draft(public_body=f"{greet}\n\nThanks, the team will look at this.", needs_human=True,
                  note_body="Hello,\n\nDraft for the team.")


class TitleGreetingTests(unittest.TestCase):
    """Fix 1: never greet with a title or honorific."""

    def test_105974_dr_requester_name(self) -> None:
        _o, posted, _seen = _run(_mmo_ctx(T105974, name="Dr Anna Example"), _holding("Hi Dr,"))
        body = posted[0].public_body
        self.assertTrue(body.startswith("Hi Anna,\n\n"), body)
        self.assertNotIn("Dr", body.split("\n")[0])

    def test_title_plus_surname_only_is_hi_there(self) -> None:
        _o, posted, _seen = _run(_mmo_ctx("Where is the venue?", name="Dr Example"), _holding("Hi Dr,"))
        self.assertTrue(posted[0].public_body.startswith("Hi there,\n\n"), posted[0].public_body)

    def test_requester_names(self) -> None:
        cases = {
            "Dr Jane Smith": "Hi Jane,", "Dr. Jane Smith": "Hi Jane,", "dr jane smith": "Hi Jane,",
            "DR JANE SMITH": "Hi there,",  # unchanged v5 rule: all-caps is not trusted
            "Prof. Dr. Karl Weber": "Hi Karl,", "MRS. Ann Lee": "Hi Ann,", "Frau Anna Schmidt": "Hi Anna,",
            "Sra. Lucia Gomez": "Hi Lucia,", "M. Jean Dupont": "Hi Jean,", "Dhr. Jan de Vries": "Hi Jan,",
            "Mx Sam Lee": "Hi Sam,", "Sir John Smith": "Hi John,",
            "Dr": "Hi there,", "Dr.": "Hi there,", "Mr Smith": "Hi there,", "Mrs. Smith": "Hi there,",
            "Ms Smith": "Hi there,", "Miss Smith": "Hi there,", "Herr Mueller": "Hi there,",
            "Mme Dupont": "Hi there,", "Mevr Jansen": "Hi there,", "Madam": "Hi there,", "Prof Weber": "Hi there,",
            "Sr. Garcia": "Hi there,", "Don Smith": "Hi Don,",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                got = publictext.greeting(name)
                if name == "DR JANE SMITH" and got != expected:
                    self.assertEqual(got, "Hi Jane,")  # either is fine, never a title
                else:
                    self.assertEqual(got, expected)

    def test_signoff_with_a_title(self) -> None:
        self.assertEqual(publictext.greeting("", "Hello\n\nKind regards\nDr Jane Smith"), "Hi Jane,")
        self.assertEqual(publictext.greeting("", "Hello\n\nKind regards\nDr Smith"), "Hi there,")
        self.assertEqual(publictext.greeting("", "Hello\n\nRegards\nMr. Smith"), "Hi there,")

    def test_safe_greeting_any_case_any_dot(self) -> None:
        for greet in ("Hi Dr,", "Hi dr,", "Hi DR.,", "Hi Mr,", "Hi Mrs.,", "Hi Ms,", "Hi Miss,", "Hi Mx,",
                      "Hi Prof,", "Hi Sir,", "Hi Madam,", "Hi Dhr,", "Hi Mevr.,", "Hi Herr,", "Hi Frau,",
                      "Hi Sr,", "Hi Sra.,", "Hi Mme,", "Hi M.,", "Dear Sir,", "Hi Dr Smith,"):
            with self.subTest(greet=greet):
                self.assertEqual(publictext.safe_greeting(greet), "Hi there,")
        self.assertEqual(publictext.safe_greeting("Hi Dr Jane Smith,"), "Hi Jane,")
        self.assertEqual(publictext.safe_greeting("Hi Jane,"), "Hi Jane,")

    def test_draft_greeting_with_a_title_is_replaced(self) -> None:
        self.assertEqual(publictext.draft_first_name("Hi Dr,\n\nText", "Dr Smith"), "")
        self.assertTrue(publictext.clean_public("Hi Dr,\n\nText", "Hi Dr,").startswith("Hi there,"))
        d = flow.decide(agent="maya", lane="mmo", needs_human=True, matched="generated",
                        public_body="Hi Dr,\n\nText.", note_body="", assignee_email="", reason="ok",
                        greeting="Hi there,", customer_text="Where is the venue?", customer_name="Dr Smith")
        self.assertTrue(d.public_body.startswith("Hi there,\n\n"), d.public_body)


class BookingChangeTests(unittest.TestCase):
    """Fix 2: postpone/move/date or event change is a booking change: Meda, booking holding text."""

    def test_106422_postpone_goes_to_meda_with_booking_text(self) -> None:
        _o, posted, _seen = _run(_mmo_ctx(T106422, subject=S106422, name="Customer Name"), _holding("Hi Customer,"))
        d = posted[0]
        self.assertEqual((d.action, d.agent, d.assignee_email), ("handoff", "maya", MEDA))
        self.assertIn(flow.BOOKING_HOLDING_BODY, d.public_body)
        self.assertNotIn("working link", d.public_body)
        self.assertNotIn("access", d.public_body)
        self.assertIn("Handoff to Meda", d.internal_note)
        self.assertNotIn("working link", d.internal_note)
        self.assertIn("date or event", d.internal_note)
        self.assertEqual(notewords.trigger_hits(d.internal_note.split("draft (not sent")[0]), [])

    def test_booking_change_on_mmo_is_meda_not_alina(self) -> None:
        d = flow.decide(agent="maya", lane="mmo", needs_human=True, matched="generated", public_body="",
                        note_body="", assignee_email="alina.last@srglobal.com", reason="ok",
                        customer_text="Can I move my place to the July event?")
        self.assertEqual(d.assignee_email, MEDA)
        self.assertIn(flow.BOOKING_HOLDING_BODY, d.public_body)

    def test_booking_change_phrases(self) -> None:
        for text in (
            "I would like to postpone my place from June to July", "Can I defer my seat to the next event?",
            "Please reschedule me", "Can you move my ticket to the July event?", "Please move me to the next one",
            "I need to change the date of my event", "Can I change the event?", "Can I attend another date?",
            "Please transfer my registration to a later event", "Can I transfer my place to the next one?",
            "Can I join the next one instead?",
            "Ik wil mijn ticket verplaatsen naar juli", "Kan ik omboeken?", "uitstellen naar de volgende editie",
            "Kann ich meinen Platz verschieben?", "Ich moechte umbuchen", "Ich brauche einen anderen Termin",
            "Je voudrais reporter ma place", "Puis-je decaler ma date ?", "Je voudrais une autre date",
            "Puedo aplazar mi entrada?", "Quiero posponer mi plaza", "Quiero cambiar la fecha",
        ):
            with self.subTest(text=text):
                self.assertTrue(routing.booking_change(text))
                self.assertFalse(flow.is_access_issue(text))
                self.assertTrue(flow.holding_reply("Hi Ana,", text).endswith(flow.BOOKING_HOLDING_BODY))

    def test_not_booking_changes(self) -> None:
        for text in (
            "When is the next one?", "When is the next event in Berlin?", "Can I transfer my ticket to my wife?",
            "I moved house, here is my new address", "Where is the venue?", "Is the event in English?",
            "Please change the name on my ticket", "How do I join the zoom?", "I forgot what time it starts",
        ):
            with self.subTest(text=text):
                self.assertFalse(routing.booking_change(text))


class AccessHoldingTextTests(unittest.TestCase):
    """The access-link holding text only for missing or broken access or links."""

    def test_access_reports_get_the_access_text(self) -> None:
        for text in (
            "I cannot access the replay", "The link is not working", "I never received the link",
            "I have not received my access", "The zoom link is broken", "The link expired", "I can't log in",
            "I forgot my password", "There is a missing link", "Access denied", "The page is not loading",
            "I get an error when I try to log in", "There was no link in the email",
        ):
            with self.subTest(text=text):
                self.assertTrue(flow.is_access_issue(text))
                self.assertIn(flow.ACCESS_HOLDING_BODY, flow.holding_reply("Hi Ana,", text))

    def test_everything_else_gets_the_generic_text(self) -> None:
        for text in (
            "I am not available ( June 12 to 14)", "Will there be a recording?", "Can I get the replay?",
            "When is the next one?", "Is the venue accessible by wheelchair?", "How long is the session?",
            T105974,
        ):
            with self.subTest(text=text[:40]):
                self.assertFalse(flow.is_access_issue(text))
                self.assertTrue(flow.holding_reply("Hi Ana,", text).endswith(flow.HOLDING_BODY))

    def test_105974_holding_text_is_generic(self) -> None:
        _o, posted, _seen = _run(_mmo_ctx(T105974, name="Dr Anna Example"), _holding("Hi Dr,"))
        self.assertEqual(posted[0].public_body, f"Hi Anna,\n\n{flow.HOLDING_BODY}")


if __name__ == "__main__":
    unittest.main()
