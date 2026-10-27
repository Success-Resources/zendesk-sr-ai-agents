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


# Suppliers, partners and sponsors write to the customer inbox too. They are not
# customers: no public reply, an internal note for Meda.
BUSINESS = re.compile(
    r"\b("
    r"quotations?|(?:price |our |a |the )quote for|quote (?:attached|enclosed)|proposals? for|bulk proposal|"
    r"sponsor(?:s|ship|ing)?|partnership|partner with (?:you|us)|business (?:collaboration|opportunit\w+)|"
    r"collaborat(?:e|ion) with (?:you|your)|in collaboration with you|"
    r"vendor|supplier|rate card|media kit|advertising opportunit\w+|"
    r"(?:organi[sz](?:e|ing)|host(?:ing)?) (?:a |an )?(?:seminar|event|workshop|conference)s? (?:in|with|for)|"
    r"book (?:alan|t\.? ?harv|harv eker)\w* as (?:a |the )?speaker|request \w+ as the speaker|"
    r"av (?:quotation|quote|services)|audio[\s-]*visual services"
    r")\b",
    re.I,
)


def business_enquiry(text: str, subject: str = "") -> bool:
    """A supplier, sponsor or partnership message, not a customer question."""
    return bool(BUSINESS.search(f"{subject or ''}\n{text or ''}"))


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


QUINN_TAGS = {"ql", "ttt", "ewc", "nwa", "gbi"}
RAFA_TAGS = {"refund_request"}


def _tagset(tags) -> set[str]:
    if isinstance(tags, str):
        return {part.strip().lower() for part in tags.replace(",", " ").split() if part.strip()}
    return {str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()}


def owner(text: str, subject: str = "", tags=None) -> str:
    """rafa, quinn or maya, from the customer's own words, the subject and the Zendesk auto-tags.

    The subject counts ("[QL Inquiry] Change of payment mode" is a Quinn ticket even
    when the body never says QL). So do the trigger auto-tags ql/ttt/ewc/nwa/gbi and
    refund_request.
    """
    tagset = _tagset(tags)
    if refund_ask(text) or refund_ask(subject) or tagset & RAFA_TAGS:
        return "rafa"
    if ql_family(text) or ql_family(subject) or tagset & QUINN_TAGS:
        return "quinn"
    return "maya"
