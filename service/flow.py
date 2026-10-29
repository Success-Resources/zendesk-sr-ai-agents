"""Decisions for Maya's webhook and the backfill script.

No Zendesk calls live here. service/app.py and scripts/backfill.py apply the result.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents import notewords, publictext, routing  # noqa: E402

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

# Zendesk appends the brand signature to every agent comment. Maya adds none.
MAYA_SIGNOFF = ""
HOLDING_BODY = "Thank you for your message. I have asked the team to look at this, and they will follow up from here."
ACCESS_HOLDING_BODY = (
    "Thank you for letting us know, and sorry for the trouble. "
    "I have asked the team to check your access and send you a working link."
)
BOOKING_HOLDING_BODY = (
    "Thank you for your message. I have passed your request to change your booking to the team, "
    "and they will follow up with you from here."
)
HOLDING_REPLY = "Hello,\n\n" + HOLDING_BODY
# The access text is only for a customer who reports missing or broken access or links
# (106422 got it because "I am not available (June 12 to 14)").
_ACCESS_THING = (
    r"(?:links?|access|log ?ins?|log-ins?|sign[ -]?ins?|password|account|portal|zoom|stream|livestream|"
    r"replay|recording|video|webinar|masterclass|session|page|platform|app)"
)
_ACCESS_ISSUE = re.compile(
    r"\b(?:can'?t|cannot|can not|unable to|not able to|couldn'?t|could not|won'?t let me|doesn'?t let me)\s+"
    r"(?:\w+\s+)?(?:open|access|join|log ?in|sign ?in|get in|get into|enter|watch|view|play|find (?:the|my|a) link)\b|"
    r"\b" + _ACCESS_THING + r"\s+(?:\w+\s+){0,2}?(?:is |was |are |were |seems |keeps )?"
    r"(?:not working|isn'?t working|doesn'?t work|does not work|don'?t work|won'?t (?:open|load|work)|"
    r"broken|expired|invalid|missing|not (?:available|valid|loading|opening)|unavailable|denied|failed|failing)\b|"
    r"\b(?:broken|expired|invalid|dead|missing|wrong) (?:\w+ )?" + _ACCESS_THING + r"\b|"
    r"\b(?:access denied|no access|lost access|without access|wrong password|forgot (?:my )?password|"
    r"reset (?:my |the )?password)\b|"
    r"\b(?:have\s?n[o']t|has\s?n[o']t|did\s?n[o']t|did not|have not|never|not yet)\s+(?:\w+\s+)?"
    r"(?:received|got|gotten|get|receive)\s+(?:the |my |a |any |an )?(?:\w+ )?(?:links?|access|log ?in|login details|password)\b|"
    r"\b(?:no|without) (?:\w+ )?(?:links?|login details|log-in details)\b|"
    r"\b(?:error|problem|issue|trouble)s?\s+(?:\w+\s+){0,4}?(?:log ?in|logging in|sign(?:ing)? in|access(?:ing)?|"
    r"the link|joining|opening the)\b",
    re.I,
)
_MONEY_ASK = re.compile(r"\b(refund|reimburs|money back|chargeback|cancel(?:l?ation|l?ed|l?ing)?)\b", re.I)
_QUOTE_MARK = re.compile(r"\n-{2,}\s*original message|\n[ \t]*On .+wrote:|\nFrom:|\n>", re.I)
_SIG_CUT = re.compile(r"(?m)^--\s*$|^VAT No\b|^Registered office\b", re.I)
_SIGNOFF_BLOCK = re.compile(
    r"(?:\n+|^)(?:warm regards|kind regards|best regards|all the best|to your success),?\s*\n[\s\S]*\Z",
    re.I,
)
_ACTION_CLAIM = re.compile(
    r"\b(?:has been|have been|we have|i have) "
    r"(?:unsubscribed|removed|deleted|resent|re-sent|cancelled|canceled|registered|updated|refunded)\b",
    re.I,
)
_META = re.compile(
    r"^\s*(?:hello,?\s*)?customer\s*\(|\bper (?:hub|kb) policy\b|\bhub policy\b|\bNeeded:|\bMaya (?:to|should|must) reply\b|"
    r"\bthe customer (?:wants|asks|asked|is asking|purchased|says|would like)\b|\bcustomer (?:wants|asks|purchased)\b|"
    r"\bThis is a standard\b.*\brequest\b|\bcan be resolved directly\b|\bwithout further verification\b|"
    r"\bstaff only\b|\binternal note\b|\bdraft(?:ed)? (?:reply|email)\b",
    re.I | re.M | re.S,
)
_REASONING = re.compile(
    r"\b(not an MMI ticket|I will not send|I am not saying|\bpersona\b|knowledge hub)\b",
    re.I,
)
_KEEP_ACK = {"gdpr_handoff", "unsubscribe_handoff", "masterclass_handoff"}

MEDA_EMAIL = "meda.c@srglobal.com"  # Zendesk user 60727801768601
MEDA_ID = "60727801768601"
ALINA_EMAIL = "alina.last@srglobal.com"  # Zendesk user 14193395548057
ALINA_ID = "14193395548057"
PREV_ASSIGNEE_PREFIX = "prev_assignee_"
TAG_FOLLOWUP = "ai_followup_reply"


def _env_flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def skip_holding_for_internal_lanes() -> bool:
    """SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES (default on): Quinn and Rafa tickets get no public reply."""
    return _env_flag("SKIP_HOLDING_REPLY_FOR_INTERNAL_LANES", True)


_STALE_YEAR = re.compile(r"\b(20\d\d)\b")
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_DATE_MENTION = re.compile(
    r"\b(\d{1,2}(?:\s*[-–]\s*\d{1,2})?)(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MONTHS + r")\b",
    re.I,
)
_URL = re.compile(r"https?://[^\s)>\]]+", re.I)


def _norm_date(day: str, month: str) -> str:
    day = re.sub(r"\s*[-–]\s*", "-", day.strip())
    return f"{day} {month.lower()[:3]}"


def stale_content(text: str, facts: str, current_year: int = 2026) -> str:
    """Why a reply to an old ticket is stale, or "".

    A year before current_year, a date that is not in the current facts, or a
    link that is not in the current facts (a bare site homepage is fine).
    """
    body = text or ""
    hay = facts or ""
    for year in _STALE_YEAR.findall(body):
        if int(year) < current_year:
            return f"past year {year}"
    known = {_norm_date(d, m) for d, m in _DATE_MENTION.findall(hay)}
    for day, month in _DATE_MENTION.findall(body):
        if _norm_date(day, month) not in known:
            return f"date not in current facts: {day} {month}"
    for url in _URL.findall(body):
        url = url.rstrip(".,;:!?'\"")
        bare = re.sub(r"^https?://", "", url).rstrip("/")
        if "/" not in bare:
            continue
        if url.rstrip("/") not in hay and bare not in hay:
            return f"link not in current facts: {url}"
    return ""


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
    # v13: who owns a Maya solve (the ZENDESK_EMAIL API user, Evelin since 29 Oct). Empty for handoffs.
    solve_owner_email: str = ""


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


def above_quote(text: str) -> str:
    """Customer words only. Quoted history and signature blocks are dropped."""
    body = _QUOTE_MARK.split(text or "", maxsplit=1)[0]
    body = _SIG_CUT.split(body, maxsplit=1)[0]
    return body.strip()


def _only_quote(text: str) -> bool:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and all(line.lstrip().startswith(">") for line in lines)


def _dequote_lead(text: str) -> str:
    """A reply that starts with a quote and writes below it (104954): the leading quote block
    plus the text after it, without the "> " marks, up to the next quote or history marker."""
    raw = (text or "").lstrip()
    lines = raw.splitlines()
    out, seen_plain = [], False
    for line in lines:
        quoted = line.lstrip().startswith(">")
        if quoted and seen_plain:
            break
        if not quoted and line.strip():
            seen_plain = True
        out.append(re.sub(r"^\s*>+\s?", "", line) if quoted else line)
    return above_quote("\n".join(out).strip() + "\n")


def routing_text(description: str) -> str:
    """Latest customer turn, for routing and the noise classifier."""
    if _only_quote(above_quote(description or "")):
        return _dequote_lead(description)
    text = above_quote(description or "")
    chunks = re.split(r"\n(?=(?:Customer|Staff):)", text)
    customers = []
    for chunk in chunks:
        if chunk.startswith("Customer:"):
            customers.append(chunk.split(":", 1)[-1].strip())
    if customers:
        last = above_quote(customers[-1])
        if not last or _only_quote(last):
            # The latest turn opens with a quote (104954). Read it from the uncut text.
            raw = re.split(r"\n(?=(?:Customer|Staff):)", description or "")
            raw_customers = [c.split(":", 1)[-1] for c in raw if c.startswith("Customer:")]
            if raw_customers and _only_quote(above_quote(raw_customers[-1].strip())):
                return _dequote_lead(raw_customers[-1])
        return last
    return text


def single_signoff(text: str) -> str:
    """No sign-off from Maya. The Zendesk brand signature is the only one."""
    return publictext.strip_signoff(text)


def is_access_issue(text: str) -> bool:
    text = text or ""
    # A refund or cancellation request is not an access problem, even if it says "unable to access".
    if _MONEY_ASK.search(text) or routing.refund_ask(text) or routing.booking_change(text):
        return False
    return bool(_ACCESS_ISSUE.search(text))


def holding_reply(greet: str = "Hi there,", customer_text: str = "") -> str:
    if routing.booking_change(customer_text):
        body = BOOKING_HOLDING_BODY
    elif is_access_issue(customer_text):
        body = ACCESS_HOLDING_BODY
    else:
        body = HOLDING_BODY
    return f"{publictext.safe_greeting(greet)}\n\n{body}"


_ASSIGNEE_NAMES = {"meda.c@srglobal.com": "Meda", "alina.last@srglobal.com": "Alina"}
_GENERIC_REASONS = {"", "ok", "needs_human", "generated", "generated_needs_human", "none", "a person"}


_VENDOR_NEEDED = (
    "read the message from the vendor or platform and reply to the sender if needed. "
    "This is not a customer, so no public reply was sent.",
    "what the sender refers to (order, account or tracking set-up) and whether an end customer also needs an answer.",
)


def _lane_label(agent: str, who: str, business: bool = False) -> str:
    """Lane names that no Zendesk keyword trigger matches (no "mmi", "refund" or programme names)."""
    if agent == "rafa":
        return "payments lane (Rafa)"
    if agent == "quinn":
        return "programme lane (Quinn)"
    if business:
        return "business lane (Meda)"
    return f"{who} lane"


_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _needed_for(reason: str, agent: str, text: str) -> tuple[str, str]:
    """(what is needed, what to check). Never a bare model reason such as "ok".

    The wording avoids every Zendesk trigger word (see agents/notewords.py).
    """
    needed, check = _needed_raw(reason, agent, text)
    return notewords.scrub(needed), notewords.scrub(check)


def _needed_raw(reason: str, agent: str, text: str) -> tuple[str, str]:
    r = (reason or "").lower()
    if r.startswith("vendor or platform sender"):
        return _VENDOR_NEEDED
    if "masterclass" in r:
        return (
            "send the customer working access to the Masterclass/webinar replay.",
            "replay link status (is the link live?) and the customer's access for that product.",
        )
    if "booking_change" in r or routing.booking_change(text):
        return (
            "correct the ticket type or booking, or move it to the date or event the customer asked for "
            "(staff change; no transfer form was sent).",
            "the order, what was bought, and what the customer wants instead (type, date or event).",
        )
    if is_access_issue(text):
        return (
            "check the customer's access and send a working link.",
            "account access for this event under the customer's email, and the access or replay link status.",
        )
    if "gdpr" in r:
        return ("process the GDPR request and confirm by email.", "the legal deadline and the address on file.")
    if "unsub" in r:
        return ("remove this address from the mailing lists.", "every list the address is on.")
    if "resend" in r or "confirm" in r:
        return ("check the booking and resend the confirmation or e-ticket.", "the purchase email and the booking.")
    if agent == "rafa" or "refund" in r or "rafa" in r or routing.refund_ask(text):
        return (
            "review the payment request and reply to the customer (the payments-lane draft from Rafa is below; "
            "Maya made no promise).",
            "the payment record, the purchase date, and the T&C (14-day cooling-off from purchase).",
        )
    if agent == "quinn" or routing.ql_family(text):
        return (
            "review Quinn's draft below and reply to the customer (programme lane).",
            "the customer's programme package and the tickets or sessions in question.",
        )
    if "transfer" in r:
        return ("review the transfer (VIP, payment or legal case).", "the booking and the transfer form submission.")
    if agent == "rafa" or "refund" in r or "rafa" in r or _MONEY_ASK.search(text or ""):
        return (
            "review the payment or billing request (staff decision; Maya made no promise).",
            "the payment record and the T&C (14-day cooling-off from purchase).",
        )
    if "person" in r or "human" in r:
        return ("reply to the customer personally; they asked for a person.", "the conversation history.")
    if r not in _GENERIC_REASONS and len(r) < 120:
        return (f"reply to the customer ({reason.strip().rstrip('.')}).", "the customer's question below.")
    return ("reply to the customer; Maya had no grounded KB answer.", "the customer's question below.")


def handoff_note(
    *,
    lane: str,
    assignee_email: str,
    reason: str,
    agent: str = "maya",
    customer_text: str = "",
    customer_name: str = "",
    customer_email: str = "",
    public_sent: bool = True,
    draft: str = "",
    business: bool = False,
    vendor: str = "",
) -> str:
    """Spec handoff note: who, what they asked, what is needed, what to check.

    Zendesk keyword triggers read private notes too. Maya's own wording never
    uses a trigger word; the customer's words are summarised with neutral words;
    a draft keeps a trigger word only when the customer used it (notewords.scrub).
    """
    who = _ASSIGNEE_NAMES.get((assignee_email or "").lower(), assignee_email or "a person")
    customer_text = _MD_IMAGE.sub(" ", customer_text or "")
    asked = " / ".join(
        re.sub(r"\s+", " ", publictext.strip_customer_signoff(part)).strip()
        for part in (customer_text or "").split(" / ")
    )
    asked = re.sub(r"\s+", " ", above_quote(asked))[:600].strip()
    asked = notewords.scrub(asked)
    draft = notewords.scrub(
        (draft or "").strip(),
        keep_from=customer_text,
        keep_groups=notewords.LANE_GROUPS.get((agent or "maya").lower()),
    )
    if len(draft) < 25 or draft.lower().rstrip(".") in {"ok", (reason or "").lower().rstrip(".")}:
        draft = ""
    needed, check = _needed_for(reason, (agent or "maya").lower(), f"{reason}\n{customer_text}")
    head = f"Handoff to {who}, {_lane_label((agent or 'maya').lower(), who, business or bool(vendor))}. "
    head += "Maya sent a short holding reply." if public_sent else "No public reply was sent."
    lines = [head]
    parts = [customer_name.strip()]
    if customer_email.strip():
        parts.append(f"<{customer_email.strip()}>")
    customer = " ".join(part for part in parts if part)
    if customer:
        label = f"Sender (vendor or platform: {vendor})" if vendor and vendor != "b2b" else (
            "Sender (vendor or platform)" if vendor else "Customer"
        )
        lines.append(f"{label}: {notewords.scrub(customer)}")
    if asked:
        lines.append(f"Asked: {asked}")
    lines.append(f"Needed: {needed}")
    lines.append(f"What to check: {check}")
    if draft:
        label = f"{(agent or 'maya').title()} draft (not sent to the customer)"
        lines.append(f"\n{label}:\n{publictext.strip_signoff(draft)}")
    return "\n".join(lines)


def public_is_unsafe(text: str) -> bool:
    raw = text or ""
    if is_staff_only_text(raw):
        return True
    if _ACTION_CLAIM.search(raw) or _REASONING.search(raw) or _META.search(raw):
        return True
    if re.search(r"refund you today|we will refund|refund will (?:now )?be processed", raw, re.I):
        return True
    return False


def _default_assignee(lane: str, assignee_email: str) -> str:
    if (assignee_email or "").strip():
        return assignee_email.strip()
    if (lane or "") == "mmo":
        return "alina.last@srglobal.com"
    return "meda.c@srglobal.com"


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


def public_text_for_handoff(email: str, *, assigned: bool, greet: str | None = None) -> str:
    """Customer text for a handoff. A handoff claim stays only when we assign."""
    text = without_staff_footer(email)
    if greet is None:
        greet = publictext.safe_greeting(publictext.existing_greeting(text) or "Hi there,")
    if not text or is_staff_only_text(text):
        return holding_reply(greet) if assigned else ""
    if assigned or not promises_handoff(text):
        return publictext.clean_public(text, greet)
    stripped = strip_handoff_claims(publictext.strip_signoff(text))
    if not stripped or is_staff_only_text(stripped):
        return ""
    return publictext.clean_public(stripped, greet)


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
    noise_tag: str = "",
    forward: bool = False,
    greeting: str = "Hi there,",
    customer_text: str = "",
    customer_name: str = "",
    customer_email: str = "",
    subject: str = "",
    tags=None,
    stale_facts: str | None = None,
    vendor: str = "",
) -> Disposition:
    """Maya posts the public text. Noise is solved with no reply and no assignee.

    Quinn and Rafa never write the public reply. Their draft stays on the
    internal note, and that path still assigns Meda or Alina. srv@ is skipped.
    Public text never carries a sign-off (Zendesk adds the one signature) and
    always opens with a greeting.
    """
    agent = (agent or "maya").lower()
    greet = publictext.safe_greeting(greeting or "Hi there,")
    if publictext.is_fallback_greeting(greet):
        drafted = publictext.draft_first_name(
            public_body or note_body or "", f"{customer_name}\n{customer_email}\n{customer_text}"
        )
        if drafted:
            greet = publictext.safe_greeting(f"Hi {drafted},")
    if lane == "srv":
        return Disposition(
            action="skip_srv",
            agent=agent,
            reason="srv mailbox",
            lane=lane,
            tags=["ai_skipped_srv"],
        )
    if noise_tag or matched == "no_reply" or reason in {"no_reply", "internal_alert"}:
        sub = noise_tag or ("noise_system_alert" if reason == "internal_alert" else "noise_marketing")
        return Disposition(
            action="solve_silent",
            agent=agent,
            reason=reason or sub,
            public_body="",
            status="solved",
            assignee_email="",
            lane=lane,
            tags=["auto_closed_noise", sub, "ai_no_reply"],
        )
    if forward:
        assignee = _default_assignee(lane, assignee_email)
        note = (note_body or "").strip() or (
            "Internal forward. No public reply was sent.\n"
            "Needed: read the original customer's message and answer them directly."
        )
        return Disposition(
            action="handoff",
            agent=agent,
            reason=reason or "internal_forward",
            public_body="",
            internal_note=note,
            status="open",
            assignee_email=assignee,
            lane=lane,
            tags=[TAG_ASSIGNED, "ai_generated", "ai_internal_forward"],
        )

    email = without_staff_footer(public_body)
    if is_staff_only_text(email) or public_is_unsafe(email):
        email = ""
    elif email:
        email = publictext.clean_public(email, greet)
    # Routing rules (Akram, 26 Oct): refund -> Rafa, QL family -> Quinn, booking change -> a person.
    # These are never solved by Maya, even when a draft looks grounded.
    owner = routing.owner(customer_text, subject, tags) if (customer_text or subject or tags) else "maya"
    adviser = agent in {"quinn", "rafa"} or owner in {"quinn", "rafa"}
    if adviser and agent not in {"quinn", "rafa"}:
        agent = owner
    booking = routing.booking_change(customer_text)
    business = routing.business_enquiry(customer_text, subject)
    # A vendor, platform or partner SENDER (Hyros, Digistore24, ...) is business, never a
    # customer: Meda, internal note, no public reply. Decided by the sender, not by mentions.
    vendor = vendor or routing.vendor_sender(customer_email, "", subject, customer_text)
    if vendor:
        adviser = False
        booking = False
        business = True
        agent = "maya"
        reason = f"vendor or platform sender ({vendor})"
    if adviser or booking or business:
        email = ""
    stale = ""
    if email and stale_facts is not None:
        stale = stale_content(email, stale_facts)
        if stale:
            email = ""
            reason = f"stale content blocked ({stale})"
    specific = reason in _KEEP_ACK and email and not public_is_unsafe(public_body or "")
    handoff = (
        needs_human
        or adviser
        or booking
        or business
        or not email
        or (promises_handoff(email) and not specific)
    )
    if not handoff:
        return Disposition(
            action="solve",
            agent="maya",
            reason=reason or "ok",
            public_body=email,
            status="solved",
            assignee_email="",
            lane=lane,
            tags=[TAG_ANSWERED, "ai_generated", "ai_maya", "ai_public_reply", "ai_solved"],
        )

    # Business and booking changes (date, event, type) are Meda's, also for mmo@ (106422).
    assignee = MEDA_EMAIL if (business or booking) else _default_assignee(lane, assignee_email)
    public = email if specific else holding_reply(greet, customer_text)
    if (adviser and skip_holding_for_internal_lanes()) or business:
        public = ""
    if business and not adviser and not vendor:
        reason = "business enquiry (supplier, sponsor or partner)"
    draft = without_staff_footer(note_body)
    if is_staff_only_text(draft):
        draft = ""
    if not draft:
        draft = without_staff_footer(public_body)
    if is_staff_only_text(draft):
        draft = ""
    draft = publictext.strip_signoff(draft)
    if booking and not adviser and "typeform.com" in draft:
        draft = ""  # Maya's form reply is wrong for a booking change; do not hand it to staff as a draft.
    if draft and draft.strip() == publictext.strip_signoff(public or "").strip():
        draft = ""
    if vendor:
        draft = ""  # Maya's customer-style draft is wrong for a vendor (102967 got a venue in Nice).
    note = handoff_note(
        lane=lane,
        assignee_email=assignee,
        reason=reason,
        agent=agent,
        customer_text=customer_text,
        customer_name=customer_name,
        customer_email=customer_email,
        public_sent=bool(public),
        draft=draft,
        business=business,
        vendor=vendor,
    )
    tags = [TAG_ASSIGNED, "ai_generated", f"ai_{agent}"]
    if public:
        tags.append("ai_public_reply")
    else:
        tags.append("ai_no_public_reply")
    if adviser:
        tags.append("ai_draft_only")
    if business:
        tags.append("ai_business_enquiry")
    if vendor:
        tags.append("ai_vendor_sender")
    if stale:
        tags.append("ai_stale_blocked")
    return Disposition(
        action="handoff",
        agent=agent,
        reason=reason or "needs_human",
        public_body=public,
        internal_note=note,
        status="open",
        assignee_email=assignee,
        lane=lane,
        tags=tags,
        claims_handoff=True,
    )


def human_request_disposition(
    lane: str,
    assignee_email: str,
    *,
    greeting: str = "Hi there,",
    customer_text: str = "",
    customer_name: str = "",
    customer_email: str = "",
) -> Disposition:
    return Disposition(
        action="handoff",
        agent="maya",
        reason="asked for a person",
        public_body=f"{publictext.safe_greeting(greeting or 'Hi there,')}\n\n{HOLDING_BODY}",
        internal_note=handoff_note(
            lane=lane,
            assignee_email=assignee_email,
            reason="asked for a person",
            customer_text=customer_text,
            customer_name=customer_name,
            customer_email=customer_email,
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


def prev_assignee_tag(assignee_id, assignee_email: str = "", bot_id: str = "", existing_tags=()) -> str:
    """v13 (Akram, 27 Oct): the tag that records who held the ticket before Maya solved it.

    Meda and Alina get names, anyone else their Zendesk id, nobody prev_assignee_none.
    When the ticket is already Maya's (a reply under her own solve), the earlier tag stays
    and no new one is added.
    """
    aid = str(assignee_id or "").strip()
    email = (assignee_email or "").strip().lower()
    if aid and bot_id and aid == str(bot_id):
        if any(str(tag).startswith(PREV_ASSIGNEE_PREFIX) for tag in existing_tags or ()):
            return ""
    if aid == MEDA_ID or email == MEDA_EMAIL:
        return PREV_ASSIGNEE_PREFIX + "meda"
    if aid == ALINA_ID or email == ALINA_EMAIL:
        return PREV_ASSIGNEE_PREFIX + "alina"
    if not aid:
        return PREV_ASSIGNEE_PREFIX + "none"
    return PREV_ASSIGNEE_PREFIX + aid


def is_followup(comments: list[Comment], requester_id: str) -> bool:
    """The latest customer message comes after a public staff or Maya reply."""
    seen_reply = False
    latest_after_reply = False
    for comment in sorted_comments(comments):
        if not comment.public:
            continue
        if str(comment.author_id) == str(requester_id):
            latest_after_reply = seen_reply
        else:
            seen_reply = True
            latest_after_reply = False
    return latest_after_reply


NOTE_AGENTS = frozenset({"quinn", "rafa"})


def without_maya_note(disposition: Disposition) -> Disposition:
    """v14 (Akram, 27 Oct): Maya leaves no internal notes.

    A Maya handoff to Meda or Alina (no hub answer, booking change, forward, vendor) only
    assigns the ticket, sets the lane tags and leaves it open. Quinn and Rafa keep their
    internal-note drafts for now.
    """
    if disposition.action in {"handoff", "internal_draft"} and (disposition.agent or "maya") not in NOTE_AGENTS:
        disposition.internal_note = ""
    return disposition


def with_solve_owner(
    disposition: Disposition,
    owner_email: str,
    prev_tag: str,
    followup: bool = False,
) -> Disposition:
    """v13: every Maya solve, first answer or a reply under an earlier answer, goes to owner_email.

    owner_email is the API account in ZENDESK_EMAIL (Evelin since 29 Oct 2026, Akram before).

    Handoffs are untouched: they keep the open status, the note and Meda or Alina.
    """
    extra: list[str] = []
    if followup:
        extra.append(TAG_FOLLOWUP)
    if disposition.action in {"solve", "solve_silent"}:
        disposition.solve_owner_email = (owner_email or "").strip().lower()
        if prev_tag:
            extra.append(prev_tag)
    return merge_tags(disposition, extra) if extra else disposition


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
    if note and action in {"handoff", "internal_draft"}:
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
                    "Sessions are in English. Rome has Italian interpretation for EUR 200, "
                    "and Paris has French interpretation for EUR 99. "
                    "No other MMI event in 2026 has interpretation, including Brussels."
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
                    "I have asked the team to resend your confirmation. I cannot resend it myself."
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
