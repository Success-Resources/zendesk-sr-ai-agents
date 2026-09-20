"""The agent loop: think → tool → observe → write. This is the agent, not the model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import guardrails, llm
from agents.tools import TOOL_DOCS, run as run_tool

_PERSONAS = Path(__file__).resolve().parent / "personas"
_MAX_STEPS = 6


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


def run_agent(
    agent: str,
    subject: str,
    description: str,
    tags: str = "",
    requester_name: str = "",
) -> AgentResult:
    agent = (agent or "maya").lower()
    if agent not in {"maya", "quinn", "rafa"}:
        agent = "maya"
    system = _persona(agent) + "\n" + TOOL_DOCS
    user = (
        f"Ticket tags: {tags or '(none)'}\n"
        f"Customer name: {requester_name or '(unknown)'}\n"
        f"Subject: {subject}\n"
        f"Message:\n{description}\n\n"
        "Call search_hub first. If they ask for a city, date, venue, or price, also call "
        "lookup_sheet and search_site. Then write a new email for this person. JSON only."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tools_used: list[str] = []
    trace: list[str] = []

    for step in range(_MAX_STEPS):
        if step == _MAX_STEPS - 1:
            messages.append(
                {
                    "role": "user",
                    "content": "No more tools. action must be final. Write the customer email now. JSON only.",
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
