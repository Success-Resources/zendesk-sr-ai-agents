"""Silent-close classifier. Solved, no public reply, no Meda or Alina assignment.

A protecting signal always wins over a strong noise signal. Quoted history is
not part of the input: callers pass the text above the quote.
"""

from __future__ import annotations

import re

_PROTECT = re.compile(
    r"(\?|"
    r"\b("
    r"unsubscribe|remove me|stop emailing|gdpr|delete my data|art\.?\s*17|"
    r"refund|money back|cancel|invoice|ticket|transfer|booking|payment|"
    r"my registration|link doesn'?t work|link does not work|can'?t access|"
    r"cannot access|not available|i am not|i'm not"
    r")\b)",
    re.I,
)
_HUMAN_TAGS = {"ql", "vip", "refund"}
_SPAM_INVITE = re.compile(
    r"has invited you to test|testflight|openai ads|openal ads|adsgpt|ads gpt",
    re.I,
)
_AUTOREPLY_SUBJECT = re.compile(
    r"^(re:\s*)?(automatic reply|auto(?:matic)?[- ]?reply|out of (?:the )?office|"
    r"abwesenheit|r[eé]ponse automatique)\b|"
    r"\[rethink academy\]\s*-\s*thanks for getting in touch|"
    r"case c-\d+|"
    r"i'?m on vacation|"
    r"ticket \d+ is waiting for your response",
    re.I,
)
_AUTOREPLY_BODY = re.compile(
    r"\b(offices are closed|will respond within|this is an automatic|"
    r"out of (?:the )?office|auto-?reply|automatic reply)\b",
    re.I,
)
_BOUNCE_FROM = re.compile(r"^(mailer-daemon|postmaster)@", re.I)
_BOUNCE_SUBJECT = re.compile(
    r"undeliverable|delivery status notification|mail delivery failed",
    re.I,
)
_VENDOR = re.compile(
    r"\b(partnership|we help companies|lead generation|\bseo\b|vendor maintenance)\b",
    re.I,
)
_TOOL_FROM = re.compile(
    r"@(?:.*\.)?(webinarkit|postiz|zapier|calendly|notion\.so|pinterest)\.",
    re.I,
)
_SYSTEM = re.compile(
    r"summary of failures for google apps script|"
    r"stripe transactions import failed|"
    r"stripe dispute",
    re.I,
)
_INTERNAL_FYI = re.compile(
    r"\b(office(?:s)? (?:are |is )?closed|holiday|public holiday|\bfyi\b)\b",
    re.I,
)


def _domain(sender: str) -> str:
    sender = (sender or "").strip().lower()
    if "@" not in sender:
        return sender
    return sender.split("@", 1)[1]


def classify(
    *,
    sender: str = "",
    name: str = "",
    subject: str = "",
    text: str = "",
    headers: str = "",
    tags: str | list | set = "",
) -> str | None:
    """Return a noise subtag, or None when Maya should answer or hand off."""
    if isinstance(tags, str):
        tagset = {part.strip().lower() for part in tags.replace(",", " ").split() if part.strip()}
    else:
        tagset = {str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()}
    if tagset & _HUMAN_TAGS:
        return None
    body = text or ""
    if _PROTECT.search(f"{subject}\n{body}"):
        return None

    blob = f"{subject}\n{body}"
    header_blob = headers or ""
    sender_l = (sender or "").strip().lower()
    domain = _domain(sender_l)

    if _SPAM_INVITE.search(subject or "") or _SPAM_INVITE.search(body[:400]):
        return "noise_spam_invite"
    if _BOUNCE_FROM.search(sender_l) or _BOUNCE_SUBJECT.search(subject or ""):
        return "noise_bounce"
    if _SYSTEM.search(blob):
        return "noise_system_alert"
    if re.search(r"auto-submitted:\s*auto-", header_blob, re.I) or _AUTOREPLY_SUBJECT.search(subject or ""):
        return "noise_autoreply"
    # Staff "offices are closed" notes are internal FYI, not a customer auto-reply.
    if sender_l.endswith("@srglobal.com") and _INTERNAL_FYI.search(blob) and "?" not in body:
        return "noise_internal_fyi"
    if _AUTOREPLY_BODY.search(body[:600]):
        return "noise_autoreply"
    if domain.endswith("standardbank.co.za") and re.search(r"case c-\d+", blob, re.I):
        return "noise_autoreply"
    if "rethinkacademy.com" in domain and re.search(r"thanks for getting in touch", blob, re.I):
        return "noise_autoreply"
    if _TOOL_FROM.search(sender_l) and len(body.strip()) < 40:
        return "noise_tool"
    if re.search(r"list-unsubscribe", header_blob, re.I) and len(body.strip()) < 40:
        return "noise_marketing"
    if _VENDOR.search(body) and "?" not in body and not re.search(
        r"\b(mmi|ticket|register|my order|i bought|i purchased)\b", body, re.I
    ):
        return "noise_vendor"
    if name or sender:
        return None
    return None
