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


def check(email: str, tools_used: list[str], agent: str) -> tuple[str, bool, str]:
    """Return email, needs_human, reason."""
    text = email or ""
    if agent == "rafa":
        return text, True, "Rafa drafts only. A person sends."
    if _REFUND.search(text):
        return (
            "A person must handle this. The draft tried to approve or process a refund.",
            True,
            "refund language blocked",
        )
    if _PRICE.search(text) and "lookup_sheet" not in tools_used:
        return text, True, "ungrounded price blocked"
    if not text.strip():
        return text, True, "empty email"
    return text, False, "ok"
