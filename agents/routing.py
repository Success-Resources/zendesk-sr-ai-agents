"""Who handles a ticket. Shared by the router, Maya's corrections and flow.decide.

- Refund wording (even mixed with access or translation complaints) goes to Rafa.
- So do invoice and receipt requests (any language), internal only.
- Quantum Leap family products (QL, TTT, EWC, NWA, GBI) go to Quinn.
- A ticket-type correction, swap, upgrade/downgrade or booking change goes to a person.
Quinn and Rafa write internal notes only. These tickets are never solved by Maya.
"""

from __future__ import annotations

import re
import unicodedata

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
    r"upgrade|upgrading|downgrade|downgrading|"
    # Date or event changes (106422: "postpone my attending MMI from June to July").
    r"postpon\w*|defer(?:s|red|ring|ral)?|reschedul\w*|re-schedul\w*|"
    r"move (?:my|our|his|her|the|me|us|him) (?:\w+ ){0,2}?(?:place|seat|spot|ticket|tickets|booking|registration|"
    r"attendance|participation|reservation)?\s*(?:to|from) (?:the )?(?:next|later|another|other|following|future|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)|"
    r"move (?:my|our|his|her|the) (?:place|seat|spot|ticket|tickets|booking|registration|reservation)s?|"
    r"chang(?:e|ing) (?:the |my |our )?(?:event )?(?:dates?|event|session|city|month)|"
    r"(?:a |an )?(?:different|another|other|later) (?:date|event|session|month|edition)|"
    r"transfer(?:red|ring)? (?:\w+ ){0,3}?to (?:the |a |an )?(?:next|later|another|future|following) "
    r"(?:one|event|date|session|edition|month)|"
    r"(?:attend|join|come to|go to|switch to|move to) (?:the )?next one instead|next one instead|"
    # nl
    r"verplaats\w*|uitstel\w*|omboek\w*|andere datum|volgende editie|"
    # de
    r"verschieb\w*|verschoben|umbuch\w*|anderen termin|sp\u00e4teren termin|termin \u00e4ndern|datum \u00e4ndern|"
    # fr
    r"report(?:er|ez|é) (?:ma|mon|mes|la|le|ma place|\u00e0)|d[e\u00e9]cal\w*|reprogramm\w*|changer (?:la |de )?date|"
    r"une autre date|"
    # es
    r"aplaz\w*|pospon\w*|pospuest\w*|reprogram\w*|cambiar (?:la )?fecha|otra fecha|"
    r"cambiar (?:el |de )?evento"
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


# Money-back intent without the word "refund" (live misses 104296 and 103567, 27 Oct 2026).
# Kept tight: a plain "cancel" or "14 days" alone is not enough; it needs a money word nearby.
_CANCEL = r"(?:cancel\w*|annul\w*|stornier\w*|storno|k\u00fcndig\w*|kundig\w*|opzeg\w*|annuler|annulation|cancelar|anular)"
_MONEY = (
    r"(?:charg\w*|payments?|paid|pay|subscriptions?|membership|direct debit|instal?l?ments?|billing|billed|debit\w*|"
    r"\$\s?\d+|\d+\s?(?:\$|\u20ac|eur|usd|gbp|\u00a3)|\u20ac\s?\d+|\u00a3\s?\d+|"
    r"zahlung\w*|abbuch\w*|abo\w*|belast\w*|betaling\w*|afschrijving\w*|abonnement\w*|incasso|"
    r"paiement\w*|pr\u00e9l\u00e8vement\w*|pago\w*|cargo\w*|cobro\w*|suscripci\u00f3n\w*)"
)
REFUND_INTENT = re.compile(
    r"\b(?:"
    r"(?:get|want|need|have|receive|return|give|send|sending|sent|pay)(?:ing)?\s+(?:me\s+)?(?:back\s+)?(?:my|the|our)\s+"
    r"(?:money|payment|funds)\s+back|"
    r"(?:send|sending|give|giving|pay|paying|return|returning)\s+(?:me\s+)?back\s+(?:the|my|our)\s+(?:money|payment|funds)|"
    r"(?:return|returning|give back)\s+(?:of\s+)?(?:the|my|our)\s+(?:money|payment|funds)|"
    r"pay\s+me\s+back|my\s+money\s+returned|"
    r"cooling[\s-]*off|"
    r"14[\s-]*(?:days?|day|-day)\b[^.\n]{0,40}\b(?:rule|right|law|period|cancel\w*|withdraw\w*|return|back|cooling|term|policy)|"
    r"(?:rule|right|law|period|cancel\w*|withdraw\w*|back|cooling|term)\b[^.\n]{0,40}\b14[\s-]*days?|"
    r"right\s+(?:of|to)\s+withdraw\w*|withdraw\w*\s+from\s+(?:the|my|this|our)\s+(?:contract|purchase|order|booking|agreement)|"
    r"withdraw\s+(?:my|the|our)\s+(?:order|purchase|booking|registration)|withdrawal\s+(?:form|notice|request|period)|"
    r"herroep\w*|terugbetal\w*|geld\s+terug|"
    r"r\u00fcckerstatt\w*|ruckerstatt\w*|erstattung\w*|erstatten|geld\s+zur\u00fcck|widerruf\w*|r\u00fcckbuchung\w*|"
    r"rembours\w*|r\u00e9tractation|retractation|"
    r"reembols\w*|devoluci\u00f3n\s+del\s+dinero|devolver\s+el\s+dinero|devolu\u00e7\u00e3o|desistimiento|"
    r"rimbors\w*|zwrot\s+pieni\w*|"
    r"(?:do\s+not|don'?t|dont|please\s+don'?t|stop|never)\s+(?:to\s+)?charg\w*|"
    r"(?:not|n'?t)\s+be\s+(?:charged|billed)|charged\s+(?:twice|double|again|wrongly|by mistake|in error)|"
    r"double[\s-]+charged|wrongly\s+charged|unauthori[sz]ed\s+(?:charge|payment|transaction|debit)s?|"
    r"dispute\s+(?:the|this|a|my)\s+(?:charge|payment|transaction)"
    r")",
    re.I,
)
# v10 (live misses 27 Oct 2026): "paid twice" (106491), "$114 back ... processed twice" (107666),
# Swedish "pengar tillbaka" (107120). A double charge or an amount asked back is a refund ask,
# and so is refund wording in the Nordic and Central/Eastern European languages we see.
MONEY_BACK_EXTRA = re.compile(
    r"(?<!\w)(?:"
    r"(?:paid|pay(?:ment|ments)?|charg\w*|process\w*|debit\w*|deduct\w*|billed|taken|took|transactions?)"
    r"[^.\n]{0,60}\btwice\b|"
    r"\btwice\b[^.\n]{0,40}\b(?:paid|payments?|charg\w*|debit\w*|billed)|"
    r"double[\s-]*(?:charg\w*|paid|payments?|debit\w*|billed|billing)|"
    r"duplicate\s+(?:charges?|payments?|transactions?|debits?)|"
    r"(?:[$\u20ac\u00a3]\s?\d[\d.,]*|\d[\d.,]*\s?(?:[$\u20ac\u00a3]|eur|usd|gbp|aud|sgd|nok|sek|dkk|chf|pln)\b)\s*back\b|"
    # SV / NO / DA / FI
    r"pengar\w*\s+tillbaka|\u00e5terbetal\w*|aterbetal\w*|\u00e5terbetalning\w*|tilbakebetal\w*|refusjon\w*|"
    r"penge\w*\s+tilbag\w*|tilbagebetal\w*|hyvity\w*|rahat?\s+takaisin|"
    # PL / HU / RO / CS / RU / TR
    r"zwrot\w*|visszat\u00e9r\u00edt\w*|visszafizet\w*|rambursa\w*|vr\u00e1cen\u00ed\s+pen\w*|"
    r"\u0432\u043e\u0437\u0432\u0440\u0430\u0442\w*|\u0432\u0435\u0440\u043d\u0443\u0442\u044c\s+\u0434\u0435\u043d\u044c\u0433\w*|"
    # 100206: "Request for Cancellation of Purchase", "I need to cancel my <course> too"
    r"cancell?ation\s+of\s+(?:my\s+|the\s+|this\s+)?(?:purchase|order|payment|enrol\w*|contract|registration)|"
    r"(?:need|want|would like|wish|have)\s+to\s+cancel\s+(?:my|the|this)\s+(?:[\w-]+\s+){0,2}?"
    r"(?:course|program(?:me)?|purchase|order|contract|enrol\w*|\w*teg(?:y|ies)|coaching|mentoring)\b|"
    r"para\s+iade\w*|iade\s+(?:edin|etmek|talep\w*|istiyorum)|\u00fccret\s+iade\w*"
    r")",
    re.I,
)
# Return or refund wording in other languages (live miss 105726, 27 Oct 2026: "deseo devolver la
# entrada adquirida") and "return my ticket" in English. A return of what was bought is a money ask.
RETURN_INTENT = re.compile(
    r"\b(?:"
    # ES
    r"devolver\w*|devoluci[o\u00f3]n\w*|reembols\w*|reintegr\w*|"
    # PT
    r"devolu[c\u00e7][a\u00e3]o|devolu[c\u00e7][o\u00f5]es|estorn\w*|"
    # IT
    r"rimbors\w*|restituire|restituzione|restituit\w*|"
    # EN: return or give back what was bought; reverse the charge
    r"return(?:ing)?\s+(?:my|the|our|this|these|those)\s+(?:\w+\s+){0,2}?(?:tickets?|purchase|order|booking|seats?|pass(?:es)?)|"
    r"give\s+back\s+(?:my|the|our|this)\s+(?:\w+\s+){0,2}?(?:tickets?|purchase|order|seats?)|"
    r"give\s+(?:my|the|our|this)\s+(?:\w+\s+){0,2}?(?:tickets?|purchase|order|seats?)\s+back|"
    r"revers(?:e|ing|al of)\s+(?:the|my|this|that)\s+(?:charges?|payments?|transactions?)"
    r")",
    re.I,
)

# Invoice or receipt requests (Rafa, internal only). Own words in the customer's latest turn, or a
# subject the customer wrote. The subject of our own invoice email ("Re: Invoice 08592",
# "Invoice invoice no. I-1066-de - (XML)") is not an ask by itself: 104334 asked for a book copy
# and went to the payments lane only because of that subject.
INVOICE_WORDS = re.compile(
    r"\b(?:invoic\w*|receipts?|vat\s+(?:number|no\.?|id)|tax\s+(?:invoice|id)|"
    r"rechnung\w*|quittung\w*|factu\w*|fattur\w*|fatura\w*|faktur\w*|recibos?|ricevut\w*|re\u00e7us?|ontvangstbewijs\w*)\b",
    re.I,
)
_RECEIPT_NOT_ASK = re.compile(
    r"\b(?:upon|on|after|confirm(?:ed|ing)?|acknowledg\w*)\s+(?:the\s+)?receipt\b|\breceipt\s+of\s+(?:your|my|the|this)\s+(?:e-?mail|message|letter)",
    re.I,
)
_REPLY_PREFIX = re.compile(r"^\s*(?:(?:re|aw|fw|fwd|wg|tr|rv|sv|vs)\s*:\s*|\[[^\]]*\]\s*)+", re.I)
_SYSTEM_INVOICE_SUBJECT = re.compile(
    r"^(?:[^:\n]{0,80}:\s*)?(?:your\s+[^\n]{0,60}?\s)?(?:invoice|rechnung|factuur|facture|factura|fattura|receipt|ontvangstbewijs)\b"
    r"(?=[^\n]*\d)[\w\s.#:/()\[\]-]*$",
    re.I,
)


def system_invoice_subject(subject: str) -> bool:
    """The subject of our own invoice or receipt email (a number, nothing the customer wrote)."""
    return bool(_SYSTEM_INVOICE_SUBJECT.match(_REPLY_PREFIX.sub("", subject or "").strip()))


def invoice_ask(text: str, subject: str = "") -> bool:
    text = _RECEIPT_NOT_ASK.sub(" ", text or "")
    if INVOICE_WORDS.search(text):
        return True
    subject = subject or ""
    return bool(subject and not system_invoice_subject(subject) and INVOICE_WORDS.search(_RECEIPT_NOT_ASK.sub(" ", subject)))


_CANCEL_MONEY = re.compile(
    rf"\b{_CANCEL}\b[^.!?\n]{{0,80}}\b{_MONEY}|\b{_MONEY}[^.!?\n]{{0,80}}\b{_CANCEL}\b",
    re.I,
)


def refund_ask(text: str) -> bool:
    """Refund wording, or money-back intent in other words (EN, NL/DE/FR/ES, Nordic, PL/HU/RO/CS/RU/TR)."""
    text = text or ""
    return bool(
        REFUND.search(text)
        or REFUND_INTENT.search(text)
        or RETURN_INTENT.search(text)
        or MONEY_BACK_EXTRA.search(text)
        or _CANCEL_MONEY.search(text)
    )


# Vendors, platforms and partners who write to the customer inbox. Decided by who
# SENT the message (domain, display name, platform subject tag), never by a
# customer merely naming the platform ("I paid through Digistore24").
VENDOR_BRANDS = (
    "hyros", "digistore24", "digistore", "clickbank", "thrivecart", "samcart", "copecart", "elopage", "ablefy",
    "kajabi", "teachable", "thinkific", "clickfunnels", "stripe", "paypal", "klarna", "mollie", "adyen",
    "gocardless", "paddle", "eventbrite", "hubspot", "activecampaign", "mailchimp", "systeme", "podia",
)
# Support-desk relays. Only a company's support team sends from these.
_SUPPORT_RELAYS = ("intercom-mail.com", "intercom.io", "helpscout.net", "freshdesk.com", "zendesk.com")
_OWN = ("srglobal", "srglobalhelp", "successresources")
_BRAND_RX = "|".join(sorted(VENDOR_BRANDS, key=len, reverse=True))
_NAME_FROM = re.compile(rf"\b(?:from|at|@|by|team|support)\s+({_BRAND_RX})\b|^\s*({_BRAND_RX})(?:\s+(?:gmbh|inc|ltd|support|team))?\s*$", re.I)
_SUBJECT_TAG = re.compile(rf"^\s*\[\s*({_BRAND_RX})\b[^\]]*\]", re.I)
# Strong B2B wording. A customer does not write like this about their own order.
VENDOR_CONTENT = re.compile(
    r"\b(?:"
    r"(?:reaching out to|contact(?:ing)?|cc'?d?\s+the)\s+the\s+product\s+(?:provider|owner|vendor)|"
    r"product\s+provider|"
    r"(?:review and )?respond to the customer(?:'s)? (?:inquiry|enquiry|request|complaint)|"
    r"customer (?:inquiry|enquiry|request|complaint) (?:associated with|regarding|for|about) (?:the |this )?order|"
    r"please assist (?:the|our|your) customer|refer to the (?:customer'?s|buyer'?s) (?:request|message|inquiry|enquiry)|"
    r"reply to all with|dear (?:vendor|merchant|seller|product (?:owner|provider))|"
    r"(?:your|our) (?:merchant|vendor|seller|affiliate) account"
    r")\b",
    re.I,
)


def _domain(email: str) -> str:
    email = (email or "").strip().lower()
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def vendor_sender(email: str = "", name: str = "", subject: str = "", text: str = "") -> str:
    """The vendor/platform name when the SENDER is a vendor, partner or system, else ""."""
    domain = _domain(email)
    if domain and not any(own in domain for own in _OWN):
        labels = domain.split(".")
        for label in labels[:-1]:
            if label in VENDOR_BRANDS:
                return label
        relay = next((r for r in _SUPPORT_RELAYS if domain == r or domain.endswith("." + r)), "")
        if relay:
            first = labels[0].split("-")[0] if len(labels) > len(relay.split(".")) else ""
            return first if first in VENDOR_BRANDS else (first or relay.split(".")[0])
    m = _NAME_FROM.search(name or "")
    if m:
        return (m.group(1) or m.group(2)).lower()
    m = _SUBJECT_TAG.search(subject or "")
    if m:
        return m.group(1).lower()
    if VENDOR_CONTENT.search(text or ""):
        return "b2b"
    return ""


def fold(text: str) -> str:
    """Strip accents so "Train the Tra\u00eener" (107110) matches like "Train the Trainer"."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def ql_family(text: str) -> bool:
    text = text or ""
    return bool(QL_FAMILY.search(text) or QL_FAMILY.search(fold(text)))


_ANOTHER_SESSION = re.compile(r"\b(?:a |an )?(?:different|another|other|later) session\b", re.I)
_HOLDS_TICKET = re.compile(
    r"\b(tickets?|booking|booked|bought|purchased|paid|seat|registration|registered|reservation|mmi|"
    r"millionaire mind intensive)\b",
    re.I,
)


def booking_change(text: str) -> bool:
    """A change to what was bought. A plain name change or transfer is not one (that gets the form)."""
    text = text or ""
    if not BOOKING_CHANGE.search(text):
        return False
    # "change the name on my ticket" is a name change, not a booking change.
    stripped = _NAME_CHANGE.sub(" ", text)
    # "another session" after a missed webinar or masterclass is a replay request, not a booking
    # change, unless the customer also talks about a ticket they hold (110534, 61934).
    if not _HOLDS_TICKET.search(stripped):
        stripped = _ANOTHER_SESSION.sub(" ", stripped)
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
    if invoice_ask(text, subject):
        return "rafa"  # invoice and receipt requests: Rafa, internal only (104954, 105610)
    if ql_family(text) or ql_family(subject) or tagset & QUINN_TAGS:
        return "quinn"
    return "maya"
