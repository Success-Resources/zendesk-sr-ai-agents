"""The agent loop: think → tool → observe → write. This is the agent, not the model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import guardrails, llm
from agents.tools import TOOL_DOCS, run as run_tool
from agents.tools import activecampaign, events, hub, links, sheets

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
    r"(summary of failures for google apps script|"
    r"spreadsheet shared with you|"
    r"your post has been published|"
    r"\bpostiz\b|webinarkit|"
    r"someone just sent you a new question during the webinar|"
    r"to view this content, open the following url)",
    re.I,
)
_FOLLOWUP = re.compile(
    r"^.*\b(flagged this|team member to confirm|get back to you|"
    r"which city would you like|let me know which city|could you let me know which)\b.*\n?",
    re.I | re.M,
)
_FOOD = re.compile(r"\b(food|accommodation|hotel|flights?|f&a|board|meal)\b", re.I)
_CONFIRM = re.compile(
    r"\b(confirmation email|e-?ticket|didn'?t receive|have not received|"
    r"not received (my )?(ticket|email|confirmation))\b",
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
    name = _agent_name(agent)
    return f"{text}\n\nWarm regards,\n{name}\nSuccess Resources Support"


def asks_unsubscribe(subject: str, description: str) -> bool:
    """True when the customer asked to stop marketing mail, not a footer in a quote."""
    if _UNSUB.search(subject or ""):
        return True
    body = _QUOTE.split(description or "", maxsplit=1)[0]
    body = re.sub(r"(?is)\n\s*sent to:.*$", "", body)
    return bool(_UNSUB.search(body[:1500]))


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

    if agent == "maya" and _LINKS.search(ticket):
        blocks.append(links.lookup_links(ticket))
        used.append("lookup_links")

    if asks_unsubscribe(subject, description):
        blocks.append(activecampaign.ac_unsubscribe_lists(requester_email or ticket, agent))
        used.append("ac_unsubscribe_lists")
    elif agent == "maya" and _CONFIRM.search(ticket):
        ac_query = " ".join(part for part in (requester_email, ticket) if part).strip()
        blocks.append(activecampaign.ac_fix_confirmation(ac_query, agent))
        used.append("ac_fix_confirmation")

    if _REGISTERED.search(ticket):
        query = " ".join(part for part in (requester_email, requester_name, ticket) if part).strip()
        blocks.append(sheets.lookup_registration(query))
        used.append("lookup_registration")
    elif program == "mmi" and (_PRICE.search(ticket) or _FOOD.search(ticket) or events.mentioned_city(ticket)):
        blocks.append(sheets.lookup_sheet(ticket, prefer="mmi"))
        used.append("lookup_sheet")

    return "\n\n---\n\n".join(blocks), used


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
        "and hub policy — never Millionaire Mind Intensive dates. "
        "If LIVE EVENTS / the sheet lists dates, include those and no others. "
        "Do not state an event date, city, or venue from memory or from the persona. "
        "Food and accommodation: QL tuition does not include them unless the hub or sheet says so "
        "for that event (EWC F&A is separate). "
        "Answer every question in this one email. The customer should not need to reply. "
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
        "If they asked for a registration link and named no country, send https://millionairemind.live/ "
        "and the upcoming dates. Do not ask them to reply with a country. "
        "If they asked for a fact sheet and named a city, send only the matching sr-event.com factsheet. "
        "Facebook and WhatsApp groups: send the listed group when they named a city. "
        "If they did not receive a confirmation email: tell them to check spam/junk/"
        "promotions. Use the EVENT REGISTRATION / ActiveCampaign result. "
        "Only say we found their booking if sheet_found=true. "
        "Do not claim an email was resent unless MODE=execute OK or AC_TAG=added or AC_TAG=retriggered. "
        "If sheet_found=false, ask for the purchase email and which city and set needs_human true. "
        + (
            "If they asked to unsubscribe, warn them first that a registered participant may no longer "
            "receive important updates about their event, and tell them they can unsubscribe themselves "
            "with the Unsubscribe link at the bottom of each email. "
            if agent == "maya"
            else "If they asked to unsubscribe from marketing emails, the whole reply is only that confirmation. "
        )
        + "Say the ticket email has already been removed only when AC_UNSUB=ok or AC_UNSUB=already, and then set needs_human false. "
        "Do not mention GDPR, data deletion, Ireland, or a data protection team, even if they asked for that too. "
        "Use the email address on the Zendesk ticket. Do not unsubscribe a different address. "
        "Do not invent a date or price. needs_human is false when this email answers the question. "
        "Set needs_human true only for a refund, a booking that was not found, or a request to speak to a person. "
        "Sign off with the agent name only, never the customer's name, never Akram, and never "
        "'To your success' or 'Customer Service Team'. JSON only."
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
        ticket = f"{subject}\n{description}"
        unsub_done = "AC_UNSUB=ok" in live or "AC_UNSUB=already" in live
        if unsub_done and not blocked:
            if re.search(r"\b(gdpr|data protection|personal data|erasure|forgotten)\b", email, re.I):
                who = (requester_name or "").strip().split()
                hello = f"Hello {who[0]}," if who else "Hello,"
                email = (
                    f"{hello}\n\n"
                    "The email address on this ticket has been unsubscribed from our marketing lists "
                    "and will no longer receive promotional emails from us.\n\n"
                    "If another promotional email arrives, forward it to us and we will check that list."
                )
            needs = False
        elif agent == "rafa":
            needs = True
        elif (
            _OVERVIEW.search(ticket)
            and not blocked
            and not _CONFIRM.search(ticket)
            and not _REGISTERED.search(ticket)
        ):
            email = _FOLLOWUP.sub("", email).strip()
            needs = False
        if _NO_REPLY.search(ticket):
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
