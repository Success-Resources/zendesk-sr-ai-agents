"""Public-reply hygiene shared by the agents and the webhook flow.

Zendesk appends the brand signature ("To your success, Customer Service Team,
Success Resources UK Limited ...") to every agent comment. That is the only
signature a customer sees, so Maya's text never carries its own sign-off.
Every public reply starts with a greeting that uses the customer's real first
name, or "Hello," when no reliable name is known.
"""

from __future__ import annotations

import re

_QUOTE = re.compile(
    r"\n-{2,}\s*(?:original|forwarded) message|\nOn .+wrote:|\nFrom:|\n>|\nSent from my ",
    re.I,
)
# A line that opens a closing block, e.g. "Warm regards," or "To your success,".
_CLOSING = re.compile(
    r"(?im)^[ \t]*(?:warm(?:est)? regards|kind(?:est)? regards|best regards|regards|"
    r"best wishes|warm wishes|all the best|with gratitude|to your success|many thanks|"
    r"thanks again|yours sincerely|sincerely|cordially|cheers)[ \t]*[,.!]?[ \t]*$"
)
# Lines that are only a signature, even without a closing word above them.
_SIGNATURE_LINE = re.compile(
    r"(?i)^\s*(?:maya\b[^\n]{0,60}|rafa\b[^\n]{0,40}|quinn\b[^\n]{0,40}|"
    r"success resources(?: uk)?(?: limited| ltd\.?| support| team)?\.?|"
    r"customer service team\.?|the success resources team\.?|evelin\b[^\n]{0,40})\s*$"
)
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|dear|good (?:morning|afternoon|evening)|greetings)\b[^\n]{0,60}\n",
    re.I,
)
_FOREIGN_GREETING = re.compile(
    r"^\s*(?:ciao|salve|gentile|bonjour|bonsoir|hallo|guten tag|liebe[rs]?|hola|"
    r"buongiorno|buenos d[ií]as|olá|oi|cze[sś][cć]|dzie[nń] dobry|witam|hej)\b[^\n]{0,60}\n",
    re.I,
)
_NAME = r"[A-ZÀ-ÖØ-ÞİŁŚŻŹĆŃÓ][a-zà-öø-ÿıłśżźćńó'’-]{1,20}"
_SIGNED = re.compile(
    r"(?im)^[ \t]*(?:(?:best|kind|warm|many|with)\s+)?(?:regards|wishes|thanks|thank you|best|cheers|"
    r"sincerely|cordially|greetings|saludos|cordiali saluti|grazie|merci|danke|pozdrawiam)"
    r"[ \t]*[,.!]?[ \t]*\n(?:[ \t]*\n){0,3}[ \t]*(" + _NAME + r")(?:[ \t]+" + _NAME + r")*[ \t]*$"
)
_NOT_A_PERSON = re.compile(
    r"(?i)\b(?:ltd|limited|llc|gmbh|inc|team|support|info|customer|service|services|global|"
    r"resources|admin|office|sales|company|group|hr|accounts?|billing|noreply|no-reply)\b"
)


def _first_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name or "@" in name or _NOT_A_PERSON.search(name):
        return ""
    parts = [p for p in re.split(r"\s+", name) if p]
    if len(parts) < 2:
        return ""
    first, second = parts[0], parts[1]
    if first.islower() and second.islower():
        first, second = first.capitalize(), second.capitalize()
    if not (re.fullmatch(_NAME, first) and re.fullmatch(_NAME, second)):
        return ""
    return first


def signed_first_name(text: str) -> str:
    """First name from the customer's own sign-off above any quote."""
    body = _QUOTE.split(text or "", maxsplit=1)[0]
    body = re.sub(r"[*_]+", "", body)  # markdown such as **_Marina Mursic_**
    found = ""
    for match in _SIGNED.finditer(body):
        found = match.group(1)
    if found and _NOT_A_PERSON.search(found):
        return ""
    return found


def first_name(requester_name: str = "", customer_texts: list[str] | str | None = None) -> str:
    """The customer's real first name, or "" when it is not reliable."""
    if isinstance(customer_texts, str):
        customer_texts = [customer_texts]
    for text in reversed(customer_texts or []):
        signed = signed_first_name(text)
        if signed:
            return signed
    return _first_name(requester_name)


def greeting(requester_name: str = "", customer_texts: list[str] | str | None = None) -> str:
    name = first_name(requester_name, customer_texts)
    return f"Hi {name}," if name else "Hello,"


def strip_signoff(text: str) -> str:
    """Remove any sign-off block and agent signature lines from a public reply."""
    body = (text or "").replace("\r\n", "\n").strip()
    if not body:
        return ""
    match = None
    for found in _CLOSING.finditer(body):
        # A closing word counts only in the tail of the email.
        if len(body) - found.start() <= 400:
            match = found
            break
    if match:
        body = body[: match.start()].rstrip()
    lines = body.split("\n")
    while lines and (not lines[-1].strip() or _SIGNATURE_LINE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines).strip()


def with_greeting(text: str, greet: str) -> str:
    """Body with exactly one greeting line at the top."""
    body = (text or "").strip()
    if not body:
        return ""
    greet = (greet or "Hello,").strip()
    foreign = _FOREIGN_GREETING.match(body + "\n")
    if foreign:
        line = foreign.group(0).strip()
        name = greet[3:-1] if greet.startswith("Hi ") else ""
        # Keep a greeting in the customer's language when it names nobody else.
        words = re.findall(_NAME, line)
        if (name and name in line) or len(words) <= 1:
            return body
        rest = body[foreign.end():] if foreign.end() <= len(body) else ""
        return f"{greet}\n\n{rest.strip()}".strip()
    english = _GREETING.match(body + "\n")
    if english:
        rest = body[english.end():] if english.end() <= len(body) else ""
        body = rest.strip()
    elif re.match(r"(?i)^(?:hi|hello|hey|dear)\b[^\n]{0,60}$", body):
        body = ""
    return f"{greet}\n\n{body}".strip()


def clean_public(text: str, greet: str = "Hello,") -> str:
    """No sign-off (Zendesk adds the one signature) and one greeting."""
    body = strip_signoff(text)
    if not body:
        return ""
    return with_greeting(body, greet)


def existing_greeting(text: str) -> str:
    """The greeting line the text already opens with, or ""."""
    body = (text or "").strip() + "\n"
    match = _GREETING.match(body) or _FOREIGN_GREETING.match(body)
    return match.group(0).strip() if match else ""


_CUSTOMER_CLOSE = re.compile(
    r"\n\s*(?:best regards|kind regards|warm regards|regards|best|thanks|thank you|many thanks|cheers|sincerely)"
    r"[,.!]?\s*(?:\n.{0,60}){0,3}\s*$",
    re.I,
)


def strip_customer_signoff(text: str) -> str:
    """Drop the customer's closing and name lines, for the "Asked:" summary."""
    return _CUSTOMER_CLOSE.sub("", "\n" + (text or "").strip()).strip()
