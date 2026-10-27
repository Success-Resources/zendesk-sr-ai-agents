"""Internal staff forwards (e.g. Zina at info.uk@ forwarding a customer).

The forwarded original is kept in full. The internal note names the original
customer and their email, lists every question, and adds a suggested answer
from the KB where one exists. Nothing here is ever posted publicly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agents import facts, notewords

_MARKER = re.compile(
    r"(?im)^[ \t>]*(?:-{2,}\s*(?:forwarded message|original message)\s*-{2,}|begin forwarded message:)[ \t]*$"
)
_HEADER = re.compile(r"(?im)^[ \t>]*\**(from|date|sent|subject|to|cc|reply-to)\**\s*:\**\s*(.*)$")
_ADDRESS = re.compile(r"<?([A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})>?")
_INNER_QUOTE = re.compile(r"\nOn .{5,200}wrote:|\n-{2,}\s*(?:original|forwarded) message|\n>", re.I)


@dataclass
class Forward:
    staff_text: str = ""
    sender_name: str = ""
    sender_email: str = ""
    date: str = ""
    subject: str = ""
    body: str = ""
    questions: list[str] = field(default_factory=list)


def _clean_name(raw: str) -> str:
    name = re.sub(r"[*_\"]", "", raw or "")
    name = _ADDRESS.sub("", name)
    return re.sub(r"\s+", " ", name).strip(" <>,")


def parse(text: str) -> Forward | None:
    """The forwarded original, or None when the text has no forward block."""
    raw = (text or "").replace("\r\n", "\n")
    marker = _MARKER.search(raw)
    if not marker:
        return None
    out = Forward(staff_text=raw[: marker.start()].strip())
    rest = raw[marker.end():]
    lines = rest.split("\n")
    idx = 0
    seen_header = False
    while idx < len(lines):
        line = lines[idx]
        match = _HEADER.match(line)
        if match:
            seen_header = True
            key, value = match.group(1).lower(), match.group(2).strip()
            if key == "from":
                addr = _ADDRESS.search(value)
                out.sender_email = addr.group(1) if addr else ""
                out.sender_name = _clean_name(value)
            elif key in {"date", "sent"}:
                out.date = value
            elif key == "subject":
                out.subject = value.strip("* ")
            idx += 1
            continue
        if not line.strip() and not seen_header:
            idx += 1
            continue
        if seen_header and not line.strip():
            idx += 1
            break
        if not seen_header:
            break
        idx += 1
    body = "\n".join(lines[idx:]).strip()
    body = _INNER_QUOTE.split("\n" + body, maxsplit=1)[0].strip()
    out.body = body
    out.questions = questions(body)
    return out


def questions(body: str) -> list[str]:
    """Numbered items first, else every sentence that ends with a question mark."""
    text = (body or "").replace("\r\n", "\n")
    items: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        numbered = re.match(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+(.*)$", line)
        if numbered:
            if current:
                items.append(" ".join(current))
            current = [numbered.group(1).strip()]
        elif current and line.strip():
            current.append(line.strip())
        elif current:
            items.append(" ".join(current))
            current = []
    if current:
        items.append(" ".join(current))
    items = [re.sub(r"\s+", " ", item).strip() for item in items if item.strip()]
    if items:
        return items
    flat = re.sub(r"\s+", " ", text)
    return [q.strip() for q in re.findall(r"[^.!?\n]*\?", flat) if len(q.strip()) > 8]


def suggest(question: str, context: str = "") -> str:
    """A KB-grounded suggestion for staff, or an honest "not in the KB"."""
    q = question.lower()
    if re.search(r"\bvisa\b.*\b(refus|reject|denied)|\b(refus|reject|denied)\w*\b.*\bvisa\b|\brefund\b|\btransfer", q):
        return (
            "Transfers to another person or another MMI event (any future city, or online) go through "
            f"{facts.TYPEFORM}; there is no transfer deadline and no order number is needed. "
            "Refunds are a staff decision only (14-day cooling-off from purchase; refunds go to the original "
            "payment method within up to 45 working days). Do not promise a refund in advance."
        )
    if re.search(r"\bupgrad|\bvip\b.*\b(later|difference)", q):
        return "Not in the KB: no upgrade price or deadline on file. A person must confirm the upgrade price and cut-off; do not quote a price that is not on the fact sheet."
    if re.search(r"\b(invitation letter|visa letter|letter)\b|\bvisa\b", q):
        return "Not in the KB: visa or invitation letters need a person to decide and prepare."
    if re.search(r"\bvenue\b|\baddress\b|\blocation\b|\bwhere\b", q):
        return "Venue not in the KB for this event yet; event-detail emails go out about 3 weeks before the event. A person confirms the venue."
    if re.search(r"\binterpret|\btranslat", q):
        return facts.interpretation_for(f"{question} {context}") or facts.interpretation_for(question)
    if re.search(r"\be-?ticket\b|\bconfirmation\b", q):
        return "E-tickets are emailed 3 days before the event; the attendance-confirmation email about 14 days before. Check spam and the purchase email."
    if re.search(r"\binvoice\b", q):
        return "MMI invoices are issued 3 days before or after the event."
    if re.search(r"\bchild|\bkids?\b|\bage\b", q):
        return "Children aged 10 or older only."
    if re.search(r"\b(100|cash)\b", q):
        return "The 100 in cash is used in a Day 1 exercise; it is separate from the ticket and not a fee."
    if re.search(r"\brecord|\breplay\b", q):
        return "MMI live and hybrid events are not recorded and have no replays."
    if re.search(r"\blunch|\bfood|\bhotel", q):
        return "Lunch is not provided and there are no hotel discounts for participants."
    return "No KB answer on file; a person should answer."


def note(fwd: Forward, *, staff_email: str, subject: str, assignee: str, lane: str) -> str:
    who = {"meda.c@srglobal.com": "Meda", "alina.last@srglobal.com": "Alina"}.get(assignee.lower(), assignee)
    customer = fwd.sender_name or "(name not shown)"
    if fwd.sender_email:
        customer += f" <{fwd.sender_email}>"
    lines = [
        f"Internal forward from {staff_email}. Handoff to {who} ({who} lane). "
        "No public reply was sent (it would go to the staff sender, not the customer).",
        f"Original customer: {customer}",
    ]
    if fwd.date:
        lines.append(f"Sent: {fwd.date}")
    lines.append(f"Subject: {fwd.subject or subject}")
    if fwd.questions:
        lines.append("")
        lines.append("Customer's questions, with a suggested answer from the KB (internal only):")
        for n, question in enumerate(fwd.questions, 1):
            lines.append(f"{n}. {question}")
            lines.append(f"   Suggested: {notewords.scrub(suggest(question, f"{fwd.subject} {subject}"))}")
    lines.append("")
    target = fwd.sender_email or "the original customer"
    lines.append(f"Needed: reply directly to {target}, not to {staff_email}.")
    lines.append("")
    lines.append("Forwarded original (full):")
    lines.append(fwd.body[:6000])
    return "\n".join(lines)
