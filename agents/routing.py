"""Who handles a ticket. Shared by the router, Maya's corrections and flow.decide.

- Refund wording (even mixed with access or translation complaints) goes to Rafa.
- Quantum Leap family products (QL, TTT, EWC, NWA, GBI) go to Quinn.
- A ticket-type correction, swap, upgrade/downgrade or booking change goes to a person.
Quinn and Rafa write internal notes only. These tickets are never solved by Maya.
"""

from __future__ import annotations

import re

REFUND = re.compile(
    r"\b(refunds?|refunded|refunding|reimburs\w*|money back|chargebacks?|charge ?back)\b",
    re.I,
)
QL_FAMILY = re.compile(
    r"\b(quantum[\s-]*leap|QL|TTT|EWC|NWA|GBI|never[\s-]*work[\s-]*again|enlightened[\s-]*warrior|"
    r"train[\s-]*the[\s-]*trainer|guerr?ill?a[\s-]*business)\b",
    re.I,
)
_NAME_CHANGE = re.compile(
    r"\b(change (?:the |my |her |his )?name|wrong name|name correction|participant name|name on the ticket)\b",
    re.I,
)
BOOKING_CHANGE = re.compile(
    r"\b("
    r"wrong (?:ticket|tickets|ticket types?|type of ticket|package|booking)|"
    r"(?:bought|purchased|booked|ordered) (?:the |a |\d+ |two |2 )?wrong|mistakenly (?:bought|purchased|booked)|"
    r"by mistake (?:i )?(?:bought|purchased|booked)|"
    r"change (?:the |my |our )?ticket[\s-]*types?|"
    r"change (?:the |my |our )?(?:tickets?|booking|order|package)|"
    r"(?:correct|fix|amend|modify|update) (?:the |my |our )?(?:tickets?|booking|order)|"
    r"swap(?:ped|ping)? (?:the |my |our )?tickets?|exchange (?:the |my |our )?tickets?|"
    r"upgrade|upgrading|downgrade|downgrading"
    r")\b",
    re.I,
)


def refund_ask(text: str) -> bool:
    return bool(REFUND.search(text or ""))


def ql_family(text: str) -> bool:
    return bool(QL_FAMILY.search(text or ""))


def booking_change(text: str) -> bool:
    """A change to what was bought. A plain name change or transfer is not one (that gets the form)."""
    text = text or ""
    if not BOOKING_CHANGE.search(text):
        return False
    # "change the name on my ticket" is a name change, not a booking change.
    stripped = _NAME_CHANGE.sub(" ", text)
    return bool(BOOKING_CHANGE.search(stripped))


def owner(text: str) -> str:
    """rafa, quinn or maya, from the customer's own words."""
    if refund_ask(text):
        return "rafa"
    if ql_family(text):
        return "quinn"
    return "maya"
