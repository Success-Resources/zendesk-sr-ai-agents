"""Decisions for Maya's webhook and the backfill script.

No Zendesk calls live here. service/app.py and scripts/backfill.py apply the result.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field

# Zendesk trigger templates often drop the comma before a later field, and
# ticket text is not JSON-escaped. Recover the ticket id from either shape.
_TICKET_ID = re.compile(
    r'["\'](?:id|ticket_id)["\']\s*:\s*["\']?(\d{2,})["\']?',
    re.I,
)
_HANDOFF_CLAIM = re.compile(
    r"\b("
    r"i(?:'ll| will) check|"
    r"will follow up|"
    r"get back to you|"
    r"i(?:'ve| have) asked the team|"
    r"i(?:'ve| have) passed|"
    r"passed\b.{0,40}\bto (?:the team|a teammate)|"
    r"left (?:this|it) with the team|"
    r"passed this to a teammate"
    r")\b",
    re.I,
)
_STAFF_NOTE = re.compile(
    r"(No sendable draft|No customer reply|No close match|A person must handle this|"
    r"Internal alert|Staff only —|Do not invent a price)",
    re.I,
)
_STAFF_FOOTER = re.compile(r"\n---\nStaff only\b", re.I)

HOLDING_REPLY = (
    "Thank you for your message. I have passed this to a teammate, who will follow up from here.\n\n"
    "Warm regards,\n"
    "Maya - your AI assistant\n"
    "Success Resources Support"
)

TAG_ANSWERED = "ai_answered"
TAG_ASSIGNED = "ai_assigned_human"
DEFAULT_CLAIM_TTL_SECONDS = 900.0

# status<pending is new and open. created>2025-12-31 includes 1 Jan 2026.
# Same-field repeats are OR in Zendesk search; different fields are AND.
# Four queries avoid a boolean expression the search API does not support.
BACKFILL_SEARCHES = [
    "type:ticket status<pending created>2025-12-31 recipient:info.eu@srglobal.com",
    "type:ticket status<pending created>2025-12-31 recipient:mmo@srglobal.com",
    "type:ticket status<pending created>2025-12-31 tags:mmi recipient:clientcare.eu@srglobal.com",
    "type:ticket status<pending created>2025-12-31 tags:mmi recipient:support.eu@srglobal.com",
]


class ClaimBook:
    """In-flight ticket ids. A claim expires, and a new book starts empty."""

    def __init__(self, ttl_seconds: float = DEFAULT_CLAIM_TTL_SECONDS):
        self.ttl = ttl_seconds
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, ticket_id: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            until = self._until.get(ticket_id)
            if until is not None and now < until:
                return False
            self._until[ticket_id] = now + self.ttl
            return True

    def release(self, ticket_id: str) -> None:
        with self._lock:
            self._until.pop(ticket_id, None)


@dataclass
class Comment:
    id: str
    author_id: str
    public: bool
    body: str
    created_at: str = ""


@dataclass
class Draft:
    agent: str
    matched: str
    extra_tags: list[str]
    note_body: str
    public_body: str
    needs_human: bool
    reason: str


@dataclass
class Disposition:
    action: str
    agent: str = ""
    reason: str = ""
    public_body: str = ""
    internal_note: str = ""
    status: str | None = None
    assignee_email: str = ""
    tags: list[str] = field(default_factory=list)
    lane: str = ""
    claims_handoff: bool = False


def parse_webhook_payload(raw: str | bytes) -> dict:
    """Parse a trigger body. A missing comma or a raw newline still yields a ticket id."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw or ""
    text = text.strip().lstrip("\ufeff")
    if not text:
        return {}
    parsed = _load_json_object(text)
    if parsed is None:
        parsed = _load_json_object(_repair_json(text))
        if parsed is not None:
            parsed["_json_repaired"] = True
    if parsed is None:
        ticket_id = _first_ticket_id(text)
        if not ticket_id:
            return {}
        return {"ticket_id": ticket_id, "_partial": True}
    if not webhook_ticket_id(parsed):
        found = _first_ticket_id(text)
        if found:
            parsed["ticket_id"] = found
    return parsed


def webhook_ticket_id(body: dict) -> str | None:
    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    raw = body.get("id") or body.get("ticket_id") or ticket.get("id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _load_json_object(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _repair_json(text: str) -> str:
    """Insert commas dropped between JSON fields in a Zendesk trigger template."""
    return re.sub(
        r'("(?:\\.|[^"\\])*"|\d+|true|false|null)\s*\n(\s*")',
        r"\1,\n\2",
        text,
        flags=re.I,
    )


def _first_ticket_id(text: str) -> str | None:
    match = _TICKET_ID.search(text or "")
    return match.group(1) if match else None


def comment_from_api(raw: dict) -> Comment:
    body = str(raw.get("body") or "").strip()
    if not body:
        body = re.sub(r"<[^>]+>", " ", str(raw.get("html_body") or "")).strip()
    return Comment(
        id=str(raw.get("id") or ""),
        author_id=str(raw.get("author_id") or ""),
        public=bool(raw.get("public", True)),
        body=body,
        created_at=str(raw.get("created_at") or ""),
    )


def sorted_comments(comments: list[Comment]) -> list[Comment]:
    return sorted(comments, key=lambda comment: (comment.created_at, comment.id))


def latest_public_comment(comments: list[Comment]) -> Comment | None:
    public = [comment for comment in sorted_comments(comments) if comment.public]
    return public[-1] if public else None


def skip_reason_for_latest(comments: list[Comment], requester_id: str) -> str | None:
    """Skip when the newest public comment is not the customer's.

    A later internal note (including an old Maya draft) does not count. That
    keeps a replay from stopping on the private note, and keeps Maya from
    answering her own public reply or an agent's public reply.
    """
    if not comments or not requester_id:
        return None
    last = latest_public_comment(comments)
    if last is None:
        return None
    if str(last.author_id) != str(requester_id):
        return "latest public comment is from an agent"
    return None


def author_is_bot(author_id: str, users: dict, bot_email: str) -> bool:
    email = str((users.get(str(author_id)) or {}).get("email") or "").strip().lower()
    return bool(bot_email) and email == bot_email.strip().lower()


def other_agent_replied(
    comments: list[Comment],
    requester_id: str,
    users: dict | None = None,
    bot_email: str = "",
) -> bool:
    """True when a human agent, not Maya's Zendesk user, has a public reply."""
    users = users or {}
    for comment in comments:
        if not comment.public or not comment.author_id:
            continue
        if str(comment.author_id) == str(requester_id):
            continue
        if author_is_bot(comment.author_id, users, bot_email):
            continue
        return True
    return False


def has_agent_public_reply(comments: list[Comment], requester_id: str) -> bool:
    """Any public reply that is not the requester, including Maya's own."""
    for comment in comments:
        if comment.public and comment.author_id and str(comment.author_id) != str(requester_id):
            return True
    return False


def render_conversation(comments: list[Comment], requester_id: str) -> str:
    """Public thread only. Internal drafts are not part of what the customer saw."""
    lines: list[str] = []
    for comment in sorted_comments(comments):
        if not comment.public:
            continue
        text = comment.body.strip()
        if not text:
            continue
        who = "Customer" if str(comment.author_id) == str(requester_id) else "Staff"
        lines.append(f"{who}:\n{text}")
    return "\n\n".join(lines)


def latest_customer_text(comments: list[Comment], requester_id: str) -> str:
    for comment in reversed(sorted_comments(comments)):
        if comment.public and str(comment.author_id) == str(requester_id):
            return comment.body
    return ""


def latest_customer_comment(comments: list[Comment], requester_id: str) -> Comment | None:
    for comment in reversed(sorted_comments(comments)):
        if comment.public and str(comment.author_id) == str(requester_id):
            return comment
    return None


def promises_handoff(text: str) -> bool:
    return bool(_HANDOFF_CLAIM.search(text or ""))


def without_staff_footer(text: str) -> str:
    return _STAFF_FOOTER.split(text or "", maxsplit=1)[0].strip()


def is_staff_only_text(text: str) -> bool:
    return bool(_STAFF_NOTE.search((text or "").strip()))


def strip_handoff_claims(text: str) -> str:
    """Drop sentences that say a teammate was already asked to help."""
    kept: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text or ""):
        sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
        good = [sentence for sentence in sentences if sentence and not _HANDOFF_CLAIM.search(sentence)]
        if good:
            kept.append(" ".join(good))
    return "\n\n".join(kept).strip()


def public_text_for_handoff(email: str, *, assigned: bool) -> str:
    """Customer text for a handoff. A handoff claim stays only when we assign."""
    text = without_staff_footer(email)
    if not text or is_staff_only_text(text):
        return HOLDING_REPLY if assigned else ""
    if assigned or not promises_handoff(text):
        return text
    stripped = strip_handoff_claims(text)
    if not stripped or is_staff_only_text(stripped):
        return ""
    return stripped


def decide(
    *,
    agent: str,
    lane: str,
    needs_human: bool,
    matched: str,
    public_body: str,
    note_body: str,
    assignee_email: str,
    reason: str = "",
) -> Disposition:
    """Maya solves or hands off. Quinn and Rafa stay on an internal note.

    Only Maya posts to the customer. Quinn and Rafa keep the pre-existing
    draft: a private note, no public comment, no status change, no assignee.
    """
    agent = (agent or "maya").lower()
    if lane == "srv":
        return Disposition(
            action="skip_srv",
            agent=agent,
            reason="srv mailbox",
            lane=lane,
            tags=["ai_skipped_srv"],
        )
    if agent in {"quinn", "rafa"}:
        note = (note_body or "").strip() or without_staff_footer(public_body)
        return Disposition(
            action="internal_draft",
            agent=agent,
            reason=reason or "draft only",
            public_body="",
            internal_note=note,
            status=None,
            assignee_email="",
            lane=lane,
            tags=["ai_draft_only", f"ai_{agent}", "ai_generated"],
        )
    if matched == "no_reply" or reason == "no_reply":
        return Disposition(
            action="solve_silent",
            agent=agent,
            reason=reason or "no_reply",
            status="solved",
            assignee_email=assignee_email,
            lane=lane,
            tags=[TAG_ANSWERED, "ai_generated", f"ai_{agent}", "ai_no_reply", "ai_solved"],
        )
    if reason == "internal_alert":
        return Disposition(
            action="handoff",
            agent=agent,
            reason=reason,
            public_body="",
            internal_note=note_body or "Internal alert. No customer reply. Leave this open.",
            status="open",
            assignee_email=assignee_email,
            lane=lane,
            tags=[TAG_ASSIGNED, "ai_generated", f"ai_{agent}", "ai_internal_alert"],
        )

    email = without_staff_footer(public_body)
    if is_staff_only_text(email):
        email = ""
    rafa = agent == "rafa"
    handoff = needs_human or rafa or not email or promises_handoff(email)
    if not handoff:
        return Disposition(
            action="solve",
            agent=agent,
            reason=reason or "ok",
            public_body=email,
            status="solved",
            assignee_email=assignee_email,
            lane=lane,
            tags=[TAG_ANSWERED, "ai_generated", f"ai_{agent}", "ai_public_reply", "ai_solved"],
        )

    if rafa or not email:
        public = HOLDING_REPLY
        claims = True
    else:
        public = email
        claims = promises_handoff(email)
    note = note_body or f"Handoff ({reason or 'needs a person'})."
    return Disposition(
        action="handoff",
        agent=agent,
        reason=reason or "needs_human",
        public_body=public,
        internal_note=note,
        status="open",
        assignee_email=assignee_email,
        lane=lane,
        tags=[TAG_ASSIGNED, "ai_generated", f"ai_{agent}", "ai_public_reply"],
        claims_handoff=claims,
    )


def human_request_disposition(lane: str, assignee_email: str) -> Disposition:
    return Disposition(
        action="handoff",
        agent="maya",
        reason="asked for a person",
        public_body=HOLDING_REPLY,
        internal_note=(
            "Customer asked to speak to a person. "
            f"Assigned to {assignee_email}. No answer was drafted."
        ),
        status="open",
        assignee_email=assignee_email,
        lane=lane,
        tags=[TAG_ASSIGNED, "ai_generated", "ai_maya", "ai_public_reply"],
        claims_handoff=True,
    )


def backfill_skip_reason(
    status: str,
    lane: str,
    comments: list[Comment],
    requester_id: str,
    *,
    comments_ok: bool,
) -> str | None:
    if not comments_ok:
        return "comments unavailable"
    if lane == "srv":
        return "srv mailbox"
    if (status or "").lower() not in {"new", "open"}:
        return f"status is {status or 'unknown'}"
    if not requester_id:
        return "requester unknown"
    if has_agent_public_reply(comments, requester_id):
        return "agent already replied publicly"
    return None


def merge_tags(disposition: Disposition, extra: list[str]) -> Disposition:
    tags: list[str] = []
    for tag in [*disposition.tags, *extra]:
        if tag and tag not in tags:
            tags.append(tag)
    disposition.tags = tags
    return disposition


def format_outcome(ticket_id: str, outcome: dict) -> str:
    action = outcome.get("action") or "skip"
    lines = [
        f"ticket {ticket_id} lane={outcome.get('lane') or '-'} agent={outcome.get('agent') or '-'}"
    ]
    if action == "solve":
        lines.append("action: solve")
    elif action == "solve_silent":
        lines.append("action: solve (no public reply)")
    elif action == "handoff":
        lines.append(f"action: handoff to {outcome.get('assignee') or 'unassigned'}")
    elif action == "internal_draft":
        lines.append(f"action: internal draft ({outcome.get('agent') or 'agent'})")
    elif action == "skip_srv":
        lines.append("action: skip (srv@srglobal.com)")
    elif action == "skip":
        lines.append(f"action: skip ({outcome.get('reason') or 'skipped'})")
    else:
        lines.append(f"action: {action}")
    note = (outcome.get("internal_note") or "").strip()
    if action == "internal_draft" and note:
        lines.append("internal note:")
        lines.append(note)
    reply = (outcome.get("reply") or "").strip()
    if action == "internal_draft":
        reply = ""
    if reply:
        lines.append("reply:")
        lines.append(reply)
    elif action in {"solve", "handoff"}:
        lines.append("reply: (none)")
    if outcome.get("reason") and action != "skip":
        lines.append(f"reason: {outcome['reason']}")
    if outcome.get("tags"):
        lines.append("tags: " + " ".join(outcome["tags"]))
    lines.append("posted: " + ("yes" if outcome.get("posted") else "no"))
    return "\n".join(lines)


def demo_cases() -> list[tuple[str, dict]]:
    """Three mocked dry-runs: a confident solve, a Rafa handoff, a resend handoff."""
    specs = [
        (
            "550001",
            dict(
                agent="maya",
                lane="mmi",
                needs_human=False,
                matched="generated",
                public_body=(
                    "Hello Ana,\n\n"
                    "There is no translation at MMI this year. All sessions are in English.\n\n"
                    "Warm regards,\nMaya - your AI assistant\nSuccess Resources Support"
                ),
                note_body="",
                assignee_email="meda.c@srglobal.com",
                reason="interpretation_fact",
            ),
        ),
        (
            "550002",
            dict(
                agent="rafa",
                lane="mmo",
                needs_human=True,
                matched="generated_needs_human",
                public_body=(
                    "Hello,\n\nI have passed this refund request to the team and they will refund you today."
                ),
                note_body="Staff only — Rafa wrote this with claude-sonnet-5. needs_human=true",
                assignee_email="alina.last@srglobal.com",
                reason="Rafa drafts only. A person sends.",
            ),
        ),
        (
            "550003",
            dict(
                agent="maya",
                lane="mmi",
                needs_human=True,
                matched="generated_needs_human",
                public_body=(
                    "Hello Ana,\n\n"
                    "I have asked the team to resend your confirmation. I cannot resend it myself.\n\n"
                    "Warm regards,\nMaya - your AI assistant\nSuccess Resources Support"
                ),
                note_body="Staff only — Maya wrote this with claude-sonnet-5.",
                assignee_email="meda.c@srglobal.com",
                reason="resend_handoff",
            ),
        ),
    ]
    cases: list[tuple[str, dict]] = []
    for ticket_id, kwargs in specs:
        disposition = decide(**kwargs)
        cases.append(
            (
                ticket_id,
                {
                    "action": disposition.action,
                    "agent": disposition.agent,
                    "reason": disposition.reason,
                    "reply": disposition.public_body,
                    "internal_note": disposition.internal_note,
                    "assignee": disposition.assignee_email if disposition.action == "handoff" else "",
                    "lane": disposition.lane,
                    "tags": list(disposition.tags),
                    "posted": False,
                },
            )
        )
    return cases
