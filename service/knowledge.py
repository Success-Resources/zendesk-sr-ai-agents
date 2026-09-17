"""Load approved email answers from the knowledge hub and pick the closest match."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

STOP = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "my", "i",
    "is", "it", "this", "that", "please", "hello", "hi", "dear", "we", "you",
    "your", "our", "with", "from", "have", "has", "was", "be", "can", "not",
}


def hub_root() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "knowledge-hub", here.parent / "knowledge-hub"):
        if candidate.is_dir():
            return candidate
    return here / "knowledge-hub"


@dataclass
class Entry:
    agent: str
    question: str
    email: str
    tag: str
    path: str


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in STOP}


def _parse_file(path: Path, default_agent: str) -> list[Entry]:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"\n(?=## )", text)
    out: list[Entry] = []
    for chunk in chunks:
        heading = re.match(r"##\s+(.+)", chunk)
        if not heading:
            continue
        title = heading.group(1).strip()
        if title.startswith("Coverage") or "Entries:" in title:
            continue
        agent_m = re.search(r"\*\*Agent:\*\*\s*(.+)", chunk)
        tag_m = re.search(r"\*\*Tag:\*\*\s*(.+)", chunk)
        lines = chunk.splitlines()
        body_lines: list[str] = []
        started = False
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if not started:
                if not line.strip() or line.startswith("**") or line.startswith("### "):
                    continue
                started = True
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if len(body) < 40:
            continue
        question = re.sub(r"^[0-9.]+ — ", "", title).strip()
        out.append(
            Entry(
                agent=(agent_m.group(1).strip() if agent_m else default_agent),
                question=question,
                email=body,
                tag=(tag_m.group(1).strip() if tag_m else ""),
                path=str(path.as_posix()),
            )
        )
    return out


def load_entries(agent: str) -> list[Entry]:
    root = hub_root()
    filename = f"{agent}.md"
    entries: list[Entry] = []
    if not root.is_dir():
        return entries
    for path in root.rglob(filename):
        if path.name.startswith("all-"):
            continue
        entries.extend(_parse_file(path, agent.title()))
    return entries


def route_agent(tags: str, subject: str, description: str) -> str:
    blob = f"{tags} {subject} {description}".lower()
    tagset = set((tags or "").lower().split())
    if tagset & {"refund_request", "finance_related", "invoice_request", "vat_invoice"}:
        return "rafa"
    if tagset & {"ql", "nwa", "gbi", "ttt", "ewc"}:
        return "quinn"
    if tagset & {"mmi", "mmo_event"}:
        return "maya"
    if any(w in blob for w in ("refund", "invoice", "vat", "payment failed", "money back")):
        return "rafa"
    if any(w in blob for w in ("quantum leap", " qleap", "never work again", "enlightened warrior", "train the trainer", "guerrilla")):
        return "quinn"
    if any(w in blob for w in ("millionaire mind", " mmi", "vip ticket", "harv eker")):
        return "maya"
    return "maya"


def best_match(agent: str, subject: str, description: str) -> tuple[Entry | None, float]:
    query = _tokens(f"{subject} {description}")
    if not query:
        return None, 0.0
    ranked: list[tuple[float, Entry]] = []
    for entry in load_entries(agent):
        hay = _tokens(f"{entry.question} {entry.email[:400]}")
        if not hay:
            continue
        overlap = query & hay
        score = len(overlap) / max(1, len(query))
        if entry.question.lower() in (description or "").lower() or entry.question.lower() in (subject or "").lower():
            score += 0.3
        ranked.append((score, entry))
    if not ranked:
        return None, 0.0
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1], ranked[0][0]


def draft_note(tags: str, subject: str, description: str) -> tuple[str, str, str]:
    agent = route_agent(tags, subject, description)
    entry, score = best_match(agent, subject, description)
    if entry is None or score < 0.18:
        body = (
            f"Knowledge hub draft ({agent.title()})\n"
            f"No close email match in the hub (score {score:.2f}). "
            "A person should classify and reply. Do not invent a price or approve a refund."
        )
        return agent, "none", body
    email = entry.email.replace("All the best,\nEvelin", "Warm regards,\nSuccess Resources Support")
    email = email.replace("Kind regards,", "Warm regards,\nSuccess Resources Support")
    if "Success Resources Support" not in email and "Warm regards" not in email:
        email = email.rstrip() + "\n\nWarm regards,\nSuccess Resources Support"
    body = (
        f"Knowledge hub draft — {agent.title()}\n"
        f"Matched: {entry.question}\n"
        f"Score: {score:.2f} · Tag: {entry.tag or '—'} · File: {entry.path}\n"
        f"Staff: edit if needed, then send. Customer cannot see this note.\n\n"
        f"{email}"
    )
    return agent, entry.question, body
