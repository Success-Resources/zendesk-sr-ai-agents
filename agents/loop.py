"""The agent loop: think → tool → observe → write. This is the agent, not the model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import guardrails, llm
from agents.tools import TOOL_DOCS, run as run_tool
from agents.tools import events, hub, sheets

_PERSONAS = Path(__file__).resolve().parent / "personas"
_MAX_STEPS = 6
_REGISTERED = re.compile(
    r"\b(regist|confirmation email|am i booked|did i (get|register)|"
    r"on the list|my ticket|booked me|have i got)\b",
    re.I,
)
_PRICE = re.compile(r"\b(price|cost|how much|ticket type|vip|fee|€995|995)\b", re.I)
_FOOD = re.compile(r"\b(food|accommodation|hotel|flights?|f&a|board|meal)\b", re.I)


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
        "If LIVE EVENTS / the sheet lists dates, include them. "
        "Food and accommodation: QL tuition does not include them unless the hub or sheet says so "
        "for that event (EWC F&A is separate). "
        "Prices only from lookup_sheet. If a date or price is missing, say a person will check "
        "and set needs_human true. Do not invent. JSON only."
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
        email, blocked, reason = guardrails.check(email, tools_used, agent)
        if blocked:
            needs = True
        if agent == "rafa":
            needs = True
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
