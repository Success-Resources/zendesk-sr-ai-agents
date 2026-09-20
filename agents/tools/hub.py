"""Search the GitHub knowledge hub. This is retrieval, not live web search."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SERVICE = _ROOT / "service"
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

from knowledge import best_match, load_entries, route_agent  # noqa: E402


def search_hub(query: str, agent: str) -> str:
    agent = (agent or "maya").lower()
    if agent not in {"maya", "quinn", "rafa"}:
        agent = route_agent("", query, query)
    entry, score = best_match(agent, query, query)
    lines = [f"agent={agent} best_score={score:.2f}"]
    if entry is None:
        lines.append("No close match.")
        return "\n".join(lines)
    lines.append(f"QUESTION: {entry.question}")
    lines.append(f"APPROVED EMAIL:\n{entry.email}")
    extras = []
    for other in load_entries(agent, refresh=False)[:8]:
        if other.question != entry.question and query.lower()[:12] in other.question.lower():
            extras.append(other)
        if len(extras) >= 2:
            break
    for extra in extras:
        lines.append(f"\nALSO: {extra.question}\n{extra.email[:500]}")
    return "\n".join(lines)
