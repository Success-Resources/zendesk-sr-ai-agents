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
_PRICE = re.compile(r"\b(price|cost|how much|ticket type|vip|fee)\b", re.I)


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

    blocks.append(events.list_events(ticket, agent))
    used.append("list_events")

    city = events.mentioned_city(ticket)
    if city:
        blocks.append(events.fetch_city(city))
        used.append("fetch_url")

    if _REGISTERED.search(ticket):
        query = " ".join(part for part in (requester_email, requester_name, ticket) if part).strip()
        blocks.append(sheets.lookup_registration(query))
        used.append("lookup_registration")
    elif _PRICE.search(ticket) or city:
        blocks.append(sheets.lookup_sheet(city or ticket))
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
        "Write a new email for this person using those facts. If LIVE EVENTS lists dates, "
        "include the relevant upcoming dates in the email — do not say a person must confirm "
        "a date that is already listed. If they asked whether they are registered, only confirm "
        "when lookup_registration shows their email; otherwise ask for the purchase email and "
        "set needs_human true. Call another tool only if a needed fact is still missing. JSON only."
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
