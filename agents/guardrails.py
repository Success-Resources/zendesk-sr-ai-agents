"""Block invented prices and refund approvals after the model writes."""

from __future__ import annotations

import re

_REFUND = re.compile(
    r"refund (is |has been |was )?(approved|processed|paid|on (its|the) way)|we will refund|money will be (sent|returned)",
    re.I,
)
_PRICE = re.compile(
    r"€|\$|£|\b\d+([.,]\d+)?\s*(eur|euro|euros|usd|gbp|pln|huf|czk)\b",
    re.I,
)
_DATE_CLAIM = re.compile(
    r"\b\d{1,2}\s*[-–]\s*\d{1,2}\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)",
    re.I,
)
_REG_CONFIRM = re.compile(
    r"you are registered|you('re| are) booked|we have (you )?booked|"
    r"your registration is confirmed|we can confirm you are (registered|booked)",
    re.I,
)
_LIVE_DATES = {"list_events", "search_site", "fetch_url", "lookup_sheet"}


def _drop_ungrounded_prices(email: str, live: str) -> str:
    """Remove a price the model wrote that was not in the live page or sheet."""
    amounts = re.findall(r"(?:€|£|\$)\s?\d[\d.,]*", email or "")
    if not amounts:
        return email
    hay = re.sub(r"\s+", "", live or "")
    # €100 / £100 is the standing MMI exercise cash, not a city ticket price.
    bad = [
        amount
        for amount in amounts
        if re.sub(r"\s+", "", amount) not in hay
        and not re.fullmatch(r"(?:€|£)\s?100", amount.strip())
    ]
    if not bad:
        return email
    kept = []
    for line in (email or "").splitlines():
        compact = re.sub(r"\s+", "", line)
        if any(re.sub(r"\s+", "", amount) in compact for amount in bad):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def check(email: str, tools_used: list[str], agent: str, live: str = "") -> tuple[str, bool, str]:
    """Return email, needs_human, reason."""
    text = _drop_ungrounded_prices(email or "", live)
    if agent == "rafa":
        return text, True, "Rafa drafts only. A person sends."
    if _REFUND.search(text):
        return (
            "A person must handle this. The draft tried to approve or process a refund.",
            True,
            "refund language blocked",
        )
    without_exercise_cash = re.sub(r"(?:€|£)\s?100\b", "", text, flags=re.I)
    without_exercise_cash = re.sub(
        r"\b100\s*(?:eur|euros|gbp|pounds)\b", "", without_exercise_cash, flags=re.I
    )
    if _PRICE.search(without_exercise_cash) and not (
        {"lookup_sheet", "fetch_url", "search_site"} & set(tools_used)
    ):
        return text, True, "ungrounded price blocked"
    if _DATE_CLAIM.search(text) and not (_LIVE_DATES & set(tools_used)):
        return text, True, "ungrounded date blocked"
    if _REG_CONFIRM.search(text) and not (
        {"lookup_registration", "lookup_event_registration", "ac_fix_confirmation"} & set(tools_used)
    ):
        return text, True, "registration confirmation blocked"
    if not text.strip():
        return text, True, "empty email"
    return text, False, "ok"
