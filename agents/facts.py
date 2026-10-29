"""Dates, venues, and interpretation Maya may state. Unknown venues escalate."""

from __future__ import annotations

ROME_CART = "https://millionairemind.live/rome-translation-cart"
TYPEFORM = "https://sr-event.typeform.com/to/ccysEJGM"
MIRA = "https://eu.jotform.com/agent/01a0f307603070008b0f3cc1cb07c16c3baf"
EVENTS_PAGE = "https://www.millionairemind.live/"

# code -> customer-facing fact. "none" means English only, no interpretation.
INTERPRETATION = {
    "ROM": {
        "city": "Rome",
        "language": "Italian",
        "price": "EUR 200",
        "url": ROME_CART,
    },
    "PAR": {
        "city": "Paris",
        "language": "French",
        "price": "EUR 99",
        "url": "",
    },
    "*": "none",
}

# Upcoming as of 26 Oct 2026. venue "" means do not guess.
EVENTS = {
    "birmingham": {
        "dates": "6-8 November 2026",
        "venue": "Novotel Birmingham Centre",
        "format": "in person only",
    },
    "brussels": {
        "dates": "20-22 November 2026",
        "venue": "",
        "format": "hybrid",
    },
    "rome": {
        "dates": "4-6 December 2026",
        "venue": "Pineta Palace Hotel, Via S. Lino Papa 35",
        "format": "in person",
    },
    "paris": {
        "dates": "4-6 December 2026",
        "venue": "",
        "format": "",
    },
    "amsterdam": {
        "dates": "29-31 January 2027",
        "venue": "",
        "format": "",
    },
    "krakow": {
        "dates": "12-14 February 2027",
        "venue": "",
        "format": "",
    },
    "manchester": {
        "dates": "",
        "venue": "",
        "format": "",
        "note": "February 2027. The exact days are not confirmed. Details go out about three weeks before.",
    },
    "warsaw": {
        "dates": "14-16 May 2027",
        "venue": "",
        "format": "",
    },
    "lisbon": {
        "dates": "",
        "venue": "",
        "format": "",
        "note": "Postponed. No new date is published.",
    },
    "oslo": {
        "dates": "",
        "venue": "",
        "format": "",
        "note": "The next Oslo date is not published.",
    },
}


def interpretation_for(text: str) -> str:
    """Customer sentence for an interpretation question. Empty if not that question."""
    blob = text or ""
    if not __import__("re").search(r"\b(translation|interpretation|interpreter|headset)\b", blob, flags=__import__("re").I):
        return ""
    import re

    if re.search(r"\b(rome|roma)\b", blob, re.I):
        return (
            "Rome on 4-6 December 2026 is delivered in English. "
            "Italian interpretation is a paid add-on for EUR 200. "
            f"You can add it here: {ROME_CART}"
        )
    if re.search(r"\bparis\b", blob, re.I):
        return (
            "Paris on 4-6 December 2026 is delivered in English. "
            "French interpretation is a paid add-on for EUR 99."
        )
    if re.search(r"\bbrussels\b", blob, re.I):
        return (
            "Brussels on 20-22 November 2026 is delivered in English. "
            "There is no interpretation at Brussels."
        )
    return (
        "Sessions are in English. There is no interpretation at this event. "
        "In 2026, interpretation is only at Rome (Italian) and Paris (French)."
    )


def event_sentence(city: str) -> str:
    row = EVENTS.get((city or "").strip().lower())
    if not row:
        return ""
    return _join(
        city.strip().title(),
        row.get("dates") or "",
        row.get("format") or "",
        row.get("venue") or "",
        row.get("note") or "",
    )


def _join(label: str, dates: str, form: str, venue: str, note: str) -> str:
    parts = [f"MMI {label}"]
    if dates:
        parts.append(dates)
    if form:
        parts.append(form)
    sentence = " is ".join(parts[:1]) 
    # "MMI Rome is 4-6 December 2026, in person, at Pineta..."
    detail = ", ".join(bit for bit in (dates, form, f"at {venue}" if venue else "") if bit)
    text = f"MMI {label}"
    if detail:
        text += f" is {detail}."
    else:
        text += "."
    if not venue:
        text += " The venue is not confirmed. The team will send it."
    if note:
        text += " " + note
    return text


def prompt_block() -> str:
    return (
        "Interpretation, 2026: Rome has paid Italian interpretation for EUR 200 at "
        f"{ROME_CART}. Paris has paid French interpretation for EUR 99. "
        "No other MMI event has interpretation, including Brussels. Do not say interpretation varies by city.\n"
        "Transfers and name changes: send "
        f"{TYPEFORM} and do not ask for an order number. "
        "Solved unless the ticket is VIP, a refund, or a legal matter.\n"
        "On-site registration opens at 8:00 and late registration closes Saturday at 12:00. "
        "Children must be 10 or older. Lunch is not provided. There are no hotel discounts.\n"
        "The EUR 100 or GBP 100 cash is a Day 1 exercise, separate from the ticket.\n"
        "MMI live and hybrid events are not recorded. Do not send an unverified replay link.\n"
        "A Masterclass, webinar, or SRLE Presenter email is not an MMI ticket. Do not send an MMI city page.\n"
        "Do not claim you resent, unsubscribed, deleted, or saved anything.\n"
        "If the venue is not in the facts below, say the team will send it and set needs_human true.\n"
        "When is the next MMI: the next MMI events are Birmingham, United Kingdom, 6-8 November 2026, "
        "and Rome, Italy, 4-6 December 2026. Answer with both and the events page "
        f"{EVENTS_PAGE}.\n"
        "Birmingham 6-8 November 2026, Novotel Birmingham Centre, in person only. "
        "Brussels 20-22 November 2026, hybrid, venue unknown. "
        "Rome 4-6 December 2026, Pineta Palace Hotel, Via S. Lino Papa 35. "
        "Paris 4-6 December 2026, venue unknown. "
        "Amsterdam 29-31 January 2027, venue unknown. "
        "Krakow 12-14 February 2027, venue unknown. "
        "Lisbon is postponed with no new date. The next Oslo date is not published."
    )
