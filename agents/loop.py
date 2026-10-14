"""The agent loop: think → tool → observe → write. This is the agent, not the model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import guardrails, llm
from agents.tools import TOOL_DOCS, run as run_tool
from agents.tools import events, factsheets, hub, links, sheets

_PERSONAS = Path(__file__).resolve().parent / "personas"
_MAX_STEPS = 6
_REGISTERED = re.compile(
    r"\b(confirmation email|am i booked|did i (get|register)|"
    r"on the list|already registered|registration not found|"
    r"have i got|booked me)\b",
    re.I,
)
_LINKS = re.compile(
    r"\b(fact\s*sheet|factsheet|facebook|fb group|whats?app|wa group|"
    r"registration link|sign[- ]?up|how (do i|can i) register|"
    r"where (do i|can i) register|link to register)\b",
    re.I,
)
_PRICE = re.compile(r"\b(price|cost|how much|ticket type|vip|fee|€995|995)\b", re.I)
_OVERVIEW = re.compile(
    r"\b(how much|price|cost|trainer|what (?:should|do) i bring|bring with|"
    r"what (?:will|do) (?:we|i) learn|what we will learn)\b",
    re.I,
)
_NO_REPLY = re.compile(
    r"(spreadsheet shared with you|"
    r"your post has been published|"
    r"\bpostiz\b|webinarkit|"
    r"someone just sent you a new question during the webinar|"
    r"to view this content, open the following url|"
    r"\bout of office\b|\bautomatic reply\b|\bauto-?reply\b)",
    re.I,
)
_INTERNAL_ALERT = re.compile(
    r"(summary of failures for google apps script|"
    r"stripe transactions import failed|"
    r"stripe dispute)",
    re.I,
)
_TYPEFORM = "https://sr-event.typeform.com/to/ccysEJGM"
_VENUES = {
    "oslo": "MMI Oslo takes place at Quality Hotel 33, Oslo, 9-11 October 2026.",
    "birmingham": "MMI Birmingham takes place at Novotel Birmingham Centre, 6-8 November 2026.",
}
_DATES = {
    "amsterdam": "Amsterdam is 29-31 January 2027.",
}
_MASTERCLASS = re.compile(r"\b(masterclass|webinar)\b", re.I)
_GDPR = re.compile(r"\b(gdpr|article\s*17|right to erasure|delete my data|erase my (personal )?data|erasure)\b", re.I)
_TRANSFER = re.compile(
    r"\b(transfer|move my|move the ticket|another (date|city|event)|can't attend|cannot attend|can not attend)\b",
    re.I,
)
_NAME = re.compile(r"\b(change (the |my |her |his )?name|wrong name|name correction|participant name)\b", re.I)
_CASH = re.compile(r"\b(€\s?100|100\s?euros?|£\s?100|2\s*[x×]\s*€?\s?50|two\s*(times\s*)?50|bring cash)\b", re.I)
_AFFORD = re.compile(r"\b(can't afford|cannot afford|can not afford|don't have the cash|do not have the cash)\b", re.I)
_TRANSLATION = re.compile(r"\b(translation|interpretation|interpreter|headset)\b", re.I)
_VENUE_ASK = re.compile(
    r"\b(venue|hotel|address|fact\s*sheet|factsheet|where is (the |my )?event|location|"
    r"schedule|timetable|more information|event details|what time|start time)\b",
    re.I,
)
_FOOD = re.compile(
    r"\b(food|meal|lunch|snack|served|catering|accommodation|flights?|f&a|board)\b",
    re.I,
)
_VISA = re.compile(r"\b(visa|embassy)\b", re.I)
_PRIZE = re.compile(r"\b(prize|won|winner)\b", re.I)
_GUEST = re.compile(r"\b(my guest|guest's details|guest details|guest is)\b", re.I)
_CLAIM = re.compile(
    r"(re-?sent|re-?triggered|just triggered|has just been|on its way|"
    r"removed from our|already been removed|noted\b.{0,40}\bon file|we have noted)",
    re.I,
)
_FOLLOW_PROMISE = re.compile(
    r"\b(i('ll| will) check|will follow up|get back to you|i've asked the team|i have asked the team|"
    r"passed .{0,30} to the team|left this with the team)\b",
    re.I,
)
_FOLLOWUP = re.compile(
    r"^.*\b(flagged this|team member to confirm|get back to you|"
    r"which city would you like|let me know which city|could you let me know which)\b.*\n?",
    re.I | re.M,
)
_CONFIRM = re.compile(
    r"\b(confirmation email|e-?ticket|didn'?t receive|have not received|"
    r"not received (my )?(ticket|email|confirmation)|"
    r"no confirmation|missing confirmation|haven'?t received)\b",
    re.I,
)
_UNSUB = re.compile(
    r"\b("
    r"unsubscribe|un-subscribe|opt[\s-]?out|"
    r"stop (these |the |your |all )?(emails|mailing|marketing|newsletters)|"
    r"remove me from|take me off|"
    r"do not (email|contact|send)|don'?t (email|send|contact)|"
    r"no more (emails|marketing|newsletters|messages)"
    r")\b",
    re.I,
)
_QUOTE = re.compile(r"\n-{2,}\s*original message|\nOn .+wrote:|\nFrom:|\n>", re.I)


@dataclass
class AgentResult:
    agent: str
    email: str
    needs_human: bool
    confidence: float
    reason: str
    tools_used: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


def _persona(agent: str) -> str:
    path = _PERSONAS / f"{agent}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "You are a Success Resources support assistant. JSON only."


def _parse(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return {"action": "final", "email": "", "needs_human": True, "thought": "unreadable model output"}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"action": "final", "email": "", "needs_human": True, "thought": "unreadable model output"}


def _agent_name(agent: str) -> str:
    return {"maya": "Maya", "quinn": "Quinn", "rafa": "Rafa"}.get((agent or "").lower(), "Maya")


def _signature_name(agent: str) -> str:
    if (agent or "").lower() == "maya":
        return "Maya - your AI assistant"
    return _agent_name(agent)


def _strip_em_dashes(text: str) -> str:
    """Em dashes read as generated text. Keep ordinary hyphens and time ranges."""
    cleaned = (text or "").replace("\u2014", " - ").replace("\u2015", " - ")
    cleaned = re.sub(r"[ \t]*--[ \t]*", " - ", cleaned)
    return re.sub(r" {2,}", " ", cleaned)


def _apply_signature(email: str, agent: str) -> str:
    """Close as the agent who wrote the reply, never as the customer or the Zendesk login."""
    text = (email or "").strip()
    if not text:
        return text
    text = re.sub(
        r"\n+(?:warm|kind|best) regards,?\s*\n[\s\S]*\Z",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\n+to your success,?\s*\n[\s\S]*\Z", "", text, flags=re.I).strip()
    text = _strip_em_dashes(text).strip()
    name = _signature_name(agent)
    return f"{text}\n\nWarm regards,\n{name}\nSuccess Resources Support"


_BOILERPLATE = re.compile(
    r"(view (?:this )?email in your browser|"
    r"having trouble viewing|"
    r"view in (?:your )?browser|"
    r"you(?:'re| are) receiving this (?:email|message)|"
    r"click here to unsubscribe|"
    r"unsubscribe from (?:this|our)|"
    r"manage (?:your )?preferences|"
    r"if you no longer wish to receive)",
    re.I,
)


def _customer_words(description: str) -> str:
    """The customer's own text, without a quoted thread or a marketing template."""
    body = _QUOTE.split(description or "", maxsplit=1)[0]
    body = re.sub(r"(?is)\n\s*sent to:.*$", "", body)
    cut = _BOILERPLATE.search(body)
    if cut:
        body = body[: cut.start()]
    return body.strip()


def asks_unsubscribe(subject: str, description: str) -> bool:
    """True when the customer asked to stop marketing mail, not a footer in a quote."""
    if _UNSUB.search(subject or ""):
        return True
    return bool(_UNSUB.search(_customer_words(description)[:1500]))


def is_marketing_or_automated(subject: str, description: str) -> bool:
    """Inbound campaign or system mail. Not a person asking to unsubscribe."""
    blob = f"{subject}\n{description}"
    if _NO_REPLY.search(blob):
        return True
    if asks_unsubscribe(subject, description):
        return False
    if _BOILERPLATE.search(description or "") and len(_customer_words(description)) < 80:
        return True
    return False


def _prefetch(
    agent: str,
    subject: str,
    description: str,
    requester_email: str,
    requester_name: str,
) -> tuple[str, list[str]]:
    """Python fetches live facts first so Claude does not hedge or skip the websites."""
    ticket = f"{subject}\n{description}"
    used: list[str] = []
    blocks: list[str] = []

    blocks.append(hub.search_hub(ticket, agent))
    used.append("search_hub")

    program = events.detect_program(ticket, agent)
    blocks.append(events.list_events(ticket, agent))
    used.append("list_events")
    if program != "mmi":
        used.append("lookup_sheet")

    if program == "mmi":
        city = events.mentioned_city(ticket)
        if city:
            blocks.append(events.fetch_city(city))
            used.append("fetch_url")
        elif _OVERVIEW.search(ticket):
            blocks.append(events.fetch_next_city(ticket, agent))
            used.append("fetch_url")

    if agent == "maya" and (
        _VENUE_ASK.search(ticket)
        or re.search(
            r"fact\s*sheet|factsheet|schedule|timetable|more information|event details|what time|start time",
            ticket,
            re.I,
        )
    ):
        blocks.append(factsheets.lookup_factsheet(ticket))
        used.append("lookup_factsheet")

    if agent == "maya" and _LINKS.search(ticket):
        blocks.append(links.lookup_links(ticket))
        used.append("lookup_links")

    if asks_unsubscribe(subject, description) or (agent == "maya" and _CONFIRM.search(ticket)):
        blocks.append(
            "AC_ACTION=not_performed. Do not unsubscribe and do not resend a confirmation or e-ticket. "
            "Say the team will do it and leave the ticket open."
        )
        used.append("ac_action_skipped")
    elif _REGISTERED.search(ticket):
        query = " ".join(part for part in (requester_email, requester_name, ticket) if part).strip()
        blocks.append(sheets.lookup_registration(query))
        used.append("lookup_registration")
    elif program == "mmi" and (_PRICE.search(ticket) or _FOOD.search(ticket) or events.mentioned_city(ticket)):
        blocks.append(sheets.lookup_sheet(ticket, prefer="mmi"))
        used.append("lookup_sheet")

    return "\n\n---\n\n".join(blocks), used


def _factsheet_body(live: str) -> tuple[str, str] | None:
    text = live or ""
    if "FACTSHEET_PAGE city=" not in text and "FACTSHEET_PAGE code=" not in text:
        return None
    url_match = re.search(r"URL: (https://\S+)", text)
    marker = text.find("Do not use another event's fact sheet.")
    if not url_match or marker < 0:
        return None
    body = text[marker + len("Do not use another event's fact sheet.") :].strip()
    if len(body) < 40:
        return None
    return url_match.group(1), body


def _quotes_page(email: str, page: str) -> bool:
    words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", page[:900])}
    skip = {"millionaire", "intensive", "friday", "saturday", "sunday", "event", "registration"}
    words -= skip
    hay = (email or "").lower()
    return sum(1 for word in words if word in hay) >= 2


def _hello(name: str) -> str:
    first = (name or "").strip().split()
    if not first or "@" in first[0]:
        return "Hello,"
    return f"Hello {first[0]},"


def _city_of(text: str) -> str:
    return events.mentioned_city(text)


def _correct_maya(
    email: str,
    needs: bool,
    reason: str,
    subject: str,
    description: str,
    requester_name: str,
    live: str,
) -> tuple[str, bool, str]:
    """Apply the 3-13 Oct correction set. A handoff stays open. A finished fact can be solved."""
    blob = f"{subject}\n{description}"
    words = _customer_words(description)
    customer = f"{subject}\n{words}"
    hello = _hello(requester_name)
    city = _city_of(blob)

    if re.search(r"no reply needed|this is an automated", email or "", re.I):
        return "", False, "no_reply"

    if _MASTERCLASS.search(blob):
        return (
            f"{hello}\n\n"
            "Thank you for writing about the Masterclass. I do not have a confirmed registration "
            "link or replay to send, so I have asked the team to send the working link, or the next "
            "session if there is no replay. I have also flagged the broken link for them. "
            "This is not an MMI ticket, so I have not sent an MMI city page.",
            True,
            "masterclass_handoff",
        )

    if _GDPR.search(customer):
        return (
            f"{hello}\n\n"
            "Thank you for your message. I have passed on both requests: to stop emails to this "
            "address, and to delete your personal data. The team will confirm the erasure within "
            "the legal deadline. I cannot remove the address or delete the data myself.",
            True,
            "gdpr_handoff",
        )

    if asks_unsubscribe(subject, description):
        repeated = bool(re.search(r"\b(many times|again and again|leave me alone|stop emailing)\b", customer, re.I))
        wrong_name = bool(re.search(r"\bi am not\b|\bthis is not\b", customer, re.I))
        extra = ""
        if wrong_name:
            extra = " I am sorry the message used the wrong name."
        if repeated:
            extra += " Because this has happened more than once, I have flagged it for the team."
        return (
            f"{hello}\n\n"
            f"Thank you.{extra} I have passed your request to the team to remove this email address. "
            "You can also use the Unsubscribe link at the bottom of each email. "
            "I have not removed the address myself.",
            True,
            "unsubscribe_handoff",
        )

    if _VISA.search(customer):
        return (
            f"{hello}\n\n"
            "Thank you for your message. The team will handle the confirmation if the embassy calls. "
            "I have left this ticket open for them. I cannot confirm the seat or resend a ticket myself.",
            True,
            "visa_handoff",
        )

    if _PRIZE.search(customer) and re.search(r"\b(online session|nobody contacted|no one contacted)\b", blob, re.I):
        return (
            f"{hello}\n\n"
            "Thank you for telling us about the prize. The team will contact you. "
            "If the email on this ticket is not the one you used, please reply with that address. "
            "An order number is not needed for a free session.",
            True,
            "prize_handoff",
        )

    if _NAME.search(customer) or (_TRANSFER.search(customer) and not _CASH.search(customer)):
        lines = [
            f"{hello}",
            "",
            "Thank you for your message.",
        ]
        if re.search(r"\b(cancer|bereav|sorry to hear|diagnos)\b", customer, re.I):
            lines.append("I am sorry you are dealing with this.")
        lines.append(
            f"Please use this form for the transfer or name change: {_TYPEFORM}"
        )
        lines.append("Send one form for each ticket. You do not need to send an order number.")
        if city == "amsterdam" or "amsterdam" in blob.lower():
            lines.append(_DATES["amsterdam"])
        if re.search(r"\bvip\b", customer, re.I):
            lines.append("VIP transfers are reviewed by the team.")
        lines.append("Nothing is changed until the team confirms it in writing.")
        handoff = bool(
            re.search(r"\b(refund|money back)\b", customer, re.I)
            or re.search(r"\bvip\b", customer, re.I)
            or _NAME.search(customer)
        )
        return "\n\n".join(lines), handoff or needs, "transfer_form" if not handoff else "transfer_handoff"

    if _GUEST.search(customer):
        return (
            f"{hello}\n\n"
            "Thank you. I have passed your guest's details to the team to register. "
            "I cannot save those details myself, so this ticket stays open until they do.",
            True,
            "guest_handoff",
        )

    if _CONFIRM.search(customer):
        order = "Thank you for the order number. " if re.search(r"\b(order|MMI\d{4})", customer, re.I) else ""
        return (
            f"{hello}\n\n"
            f"{order}I have asked the team to check the booking and resend the confirmation or e-ticket. "
            "I cannot resend it myself. If the purchase used a different email address, please send that address. "
            "That does not mean you are not registered.",
            True,
            "resend_handoff",
        )

    if _TRANSLATION.search(customer) and not _MASTERCLASS.search(blob):
        return (
            f"{hello}\n\n"
            "There is no translation or interpretation at any MMI event this year. "
            "All sessions are in English.",
            False,
            "interpretation_fact",
        )

    if _CASH.search(customer):
        body = (
            "The €100 cash is for a Day 1 exercise. It is separate from your ticket and is not a fee. "
            "You can bring one 100 note, two 50 notes, or five 20 notes. "
            "It is not needed if you join from Saturday."
        )
        if _AFFORD.search(customer):
            body += " If you cannot bring the cash, you can still attend. It is optional."
        if re.search(r"sheet_found\s*=\s*false|no_row|not found", live or "", re.I):
            body += (
                " If the purchase used a different email address, please send that address. "
                "That does not mean you are not registered."
            )
        return f"{hello}\n\n{body}", False, "cash_fact"

    if _VENUE_ASK.search(customer) or re.search(r"fact\s*sheet|factsheet", customer, re.I):
        page = _factsheet_body(live)
        if page:
            url, body = page
            if _quotes_page(email, body):
                return email, False, "factsheet_page"
            clip = body[:1600].strip()
            return (
                f"{hello}\n\n"
                f"Here are the details from the current fact sheet: {url}\n\n{clip}",
                False,
                "factsheet_page",
            )
        known = _VENUES.get(city)
        if known:
            return (
                f"{hello}\n\n{known} I have not attached an older fact sheet.",
                False,
                "venue_fact",
            )
        where = city.title() if city else "that city"
        return (
            f"{hello}\n\n"
            f"I do not have a confirmed venue for {where} on the current list, so I have asked the team "
            "to send it. I will not send a previous year's fact sheet, and I am not saying the venue is unpublished.",
            True,
            "venue_handoff",
        )

    if _FOOD.search(customer) and re.search(r"\b(food|meal|lunch|snack|served)\b", customer, re.I):
        place = f"MMI {city.title()}" if city else "MMI"
        return (
            f"{hello}\n\n"
            f"At {place}, light snacks are provided in the breaks. Meals are not included. "
            "The in-person hours are Friday 9:00-21:00, Saturday 9:00-20:00, and Sunday 8:00-19:00 local. "
            "VIP speed networking is Saturday at 8:00.",
            False,
            "food_fact",
        )

    if re.search(r"\b(90-day workbook|discount)\b", customer, re.I):
        return (
            f"{hello}\n\n"
            "I do not have a confirmed discount or a 90-day workbook rule for this event. "
            "I have left it with the team rather than guess.",
            True,
            "price_handoff",
        )

    text = email or ""
    text = re.sub(r"https://sr-event\.com/\S*factsheet\S*", "", text, flags=re.I)
    if _CLAIM.search(text):
        text = _CLAIM.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        needs = True
        reason = "false_claim_removed"
    if text.strip() and _FOLLOW_PROMISE.search(text):
        needs = True
        reason = reason if reason not in {"ok", ""} else "follow_up_left_open"
    if city and text.strip():
        other = [name for name in ("kuala lumpur", "singapore") if name != city and name in text.lower()]
        if other and city not in text.lower():
            text = (
                f"{hello}\n\n"
                f"This reply is about your {city.title()} event only. "
                "I have asked the team to confirm the detail, and I have not used another city's page."
            )
            needs = True
            reason = "wrong_city_blocked"
    return text, needs, reason


def run_agent(
    agent: str,
    subject: str,
    description: str,
    tags: str = "",
    requester_name: str = "",
    requester_email: str = "",
) -> AgentResult:
    agent = (agent or "maya").lower()
    if agent not in {"maya", "quinn", "rafa"}:
        agent = "maya"
    if agent == "maya" and _INTERNAL_ALERT.search(f"{subject}\n{description}"):
        return AgentResult(
            agent=agent,
            email="",
            needs_human=True,
            confidence=1.0,
            reason="internal_alert",
            trace=["internal alert: leave open, no customer reply"],
        )
    if agent == "maya" and is_marketing_or_automated(subject, description):
        return AgentResult(
            agent=agent,
            email="",
            needs_human=False,
            confidence=1.0,
            reason="no_reply",
            trace=["marketing or automated mail: close solved, no customer reply"],
        )
    live, tools_used = _prefetch(agent, subject, description, requester_email, requester_name)
    system = _persona(agent) + "\n" + TOOL_DOCS
    user = (
        f"Ticket tags: {tags or '(none)'}\n"
        f"Customer name: {requester_name or '(unknown)'}\n"
        f"Customer email: {requester_email or '(not in payload)'}\n"
        f"Subject: {subject}\n"
        f"Message:\n{description}\n\n"
        "LIVE FACTS already retrieved from GitHub, Success Resources websites, and Sheets:\n"
        f"{live}\n\n"
        "Write a new email for this person using those facts. "
        "If they asked about Never Work Again, EWC, GBI, TTT or Quantum Leap, use the QL Sheet "
        "and hub policy, never Millionaire Mind Intensive dates. "
        "If LIVE EVENTS / the sheet lists dates, include those and no others. "
        "Do not state an event date, city, or venue from memory or from the persona. "
        "Food and accommodation: QL tuition does not include them unless the hub or sheet says so "
        "for that event (EWC F&A is separate). "
        "Answer every question in this one email. Before you finish, check that the email "
        "answers the question they asked, not a different question from the hub. "
        "If they ask why they must bring 100 euros, two 50 euro notes, or cash to MMI, "
        "explain that it is for an exercise during the event and is separate from the ticket "
        "they already paid. They may bring one 100 note, two 50 notes, or five 20 notes. "
        "Do not answer that question with pens, snacks, a water bottle, or a jacket. "
        "The customer should not need to reply when the fact is already known. "
        "If you have asked the team to do something, set needs_human true. "
        "Do not ask which city or country on a general question about the next event, the price, "
        "the trainer, what to bring, or what they will learn. "
        "Ask a question only when a specific link or a booking check is impossible without it: "
        "a fact sheet or Facebook/WhatsApp group when they named no city, or the purchase email "
        "when their booking was not found. "
        "Do not say a teammate will confirm a date or price that is already in LIVE FACTS. "
        "Do not say you have flagged the ticket or that someone will get back to them, "
        "unless they asked for a person or the booking was not found. "
        "Quote a Standard or VIP price only when that exact figure is in LIVE FACTS, and name the city it belongs to. "
        "If the next city page names the lead trainer, use that name. Otherwise say the event is delivered "
        "by an Official Certified Millionaire Mind Intensive Trainer. "
        "What they will learn comes from the hub. What to bring: only what the hub or city page states. "
        "If it is not stated, describe what the ticket includes and link that city page. Do not ask them to choose a city. "
        "If they asked for a registration link for MMI and named no country, send https://millionairemind.live/ "
        "and the upcoming dates. Do not ask them to reply with a country. "
        "If they asked for a fact sheet or a venue, use FACTSHEET_PAGE from the 2026 sheet. "
        "You may send that link. Do not send a different city's file. "
        "Facebook and WhatsApp groups: send the listed group when they named a city. "
        "If they did not receive a confirmation email or an e-ticket, do not say it was re-sent. "
        "Say you have asked the team to resend it and set needs_human true. "
        "Transfers and name changes always include https://sr-event.typeform.com/to/ccysEJGM. "
        "Do not ask for an order number. One form per ticket. "
        "There is no translation or interpretation at any MMI event this year. All sessions are in English. "
        "A reply to a Masterclass or webinar is about that webinar. Do not send an MMI city page. "
        "If FACTSHEET_PAGE is present, quote the venue, address, and dates from it and you may send its URL. "
        "If it is missing, say you do not have the fact sheet and set needs_human true. Do not say the venue is unpublished. "
        "The €100 cash is a Day 1 exercise, separate from the ticket, and not a fee. Answer that first. "
        "If they cannot afford it, it is optional and they can still attend. "
        "Never claim you unsubscribed someone, saved a guest, or changed a name. "
        "Say you have asked the team and set needs_human true. "
        "A GDPR erasure request gets a short acknowledgement and needs_human true. "
        "Do not use em dashes. Use a comma, a period, or a hyphen. "
        "Sign off with the agent name only, never the customer's name, never Akram, and never "
        "'To your success' or 'Customer Service Team'. "
        "Maya's sign-off name is 'Maya - your AI assistant'. JSON only."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    trace: list[str] = ["prefetch: " + ",".join(tools_used)]

    for step in range(_MAX_STEPS):
        if step == _MAX_STEPS - 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "No more tools. action must be final. Write the customer email now. "
                        "Use the live dates already provided. JSON only."
                    ),
                }
            )
        raw = llm.complete(messages)
        data = _parse(raw)
        action = str(data.get("action") or "final").strip()
        thought = str(data.get("thought") or "")
        trace.append(f"step {step + 1}: {action} {thought[:120]}")
        if action != "final" and step < _MAX_STEPS - 1:
            observation = run_tool(action, str(data.get("action_input") or ""), agent)
            tools_used.append(action)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"Tool result:\n{observation}\nJSON next."})
            continue

        email = str(data.get("email") or "").strip()
        needs = bool(data.get("needs_human"))
        confidence = float(data.get("confidence") or 0)
        email, blocked, reason = guardrails.check(email, tools_used, agent, live)
        if blocked:
            needs = True
        if agent == "maya" and reason != "refund language blocked":
            email, needs, reason = _correct_maya(
                email, needs, reason, subject, description, requester_name, live
            )
        elif agent == "rafa":
            needs = True
        if reason == "no_reply" or (_NO_REPLY.search(f"{subject}\n{description}") and not email.strip()):
            email = ""
            needs = False
            reason = "no_reply"
        elif email.strip():
            email = _apply_signature(email, agent)
        return AgentResult(
            agent=agent,
            email=email,
            needs_human=needs,
            confidence=confidence,
            reason=reason,
            tools_used=tools_used,
            trace=trace,
        )

    return AgentResult(
        agent=agent,
        email="",
        needs_human=True,
        confidence=0.0,
        reason="too many tool steps",
        tools_used=tools_used,
        trace=trace,
    )
