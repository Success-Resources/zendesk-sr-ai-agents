"""Upcoming events from allowlisted Success Resources sites — not open web search."""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from threading import Lock
from urllib.parse import urlparse

from agents.tools import web

_MONTH = (
    r"January|February|March|April|May|June|July|August|"
    r"September|October|November|December"
)
_RANGE_SAME = re.compile(
    rf"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){{0,2}}(?:,\s*[A-Z][A-Za-z]+)?)\s+"
    rf"(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({_MONTH})\s+(\d{{4}})",
    re.I,
)
_RANGE_CROSS = re.compile(
    rf"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){{0,2}})\s+"
    rf"(\d{{1,2}})\s+({_MONTH})\s*[-–]\s*(\d{{1,2}})\s+({_MONTH})\s+(\d{{4}})",
    re.I,
)
_JUNK_PREFIX = {
    "buy", "tickets", "ticket", "your", "city", "coming", "come", "to",
    "we", "were", "we're", "check", "out", "now", "if", "find", "more",
    "about", "the", "this", "our", "and", "for", "with", "from", "live",
    "event", "events", "intensive", "see", "tap", "here",
}
_MULTI_FIRST = {"kuala", "new", "los", "san", "cape", "the"}
_EUROPE = {
    "madrid", "oslo", "ljubljana", "rotterdam", "birmingham", "brussels",
    "rome", "paris", "geneva", "cologne", "manchester", "dublin", "amsterdam",
    "hague", "warsaw", "prague", "vienna", "zurich", "stockholm", "copenhagen",
    "lisbon", "barcelona", "milan", "frankfurt", "munich", "hamburg", "berlin",
    "london", "edinburgh", "glasgow", "lyon", "marseille", "nice", "porto",
    "valencia", "seville", "krakow", "budapest", "bucharest", "sofia", "zagreb",
    "belgrade", "athens", "helsinki", "tallinn", "riga", "vilnius", "bratislava",
}
_VENUE = re.compile(
    r"(venue|address|location|trainer|schedule|friday|saturday|sunday|"
    r"registered attendees|exact venue)[^.|]{0,220}",
    re.I,
)
_HOMES = (
    "https://www.millionairemind.live/",
    "https://www.millionairemind.live/europe/ql-redemption",
)
_QL_HOMES = (
    "https://www.millionairemind.live/europe/ql-redemption",
    "https://www.srglobal.com/events",
)
_PROGRAMS = (
    ("nwa", r"\b(nwa|never work again)\b", "Never Work Again NWA date city venue"),
    ("ewc", r"\b(ewc|ewtc|enlightened warrior)\b", "Enlightened Warrior Camp EWC date city food accommodation"),
    ("gbi", r"\b(gbi|guerrilla)\b", "Guerrilla Business Intensive GBI date city venue"),
    ("ttt", r"\b(ttt|train the trainer)\b", "Train the Trainer TTT date city venue"),
    ("ql", r"\b(quantum leap|\bql\b)\b", "Quantum Leap QL programme date city"),
    ("mmi", r"\b(mmi|millionaire mind)\b", "Millionaire Mind Intensive MMI date city venue"),
)
_TTL = 1800.0
_lock = Lock()
_cache: dict = {"at": 0.0, "pages": []}


def _month_num(name: str) -> int:
    return datetime.strptime(name[:3].title(), "%b").month


def _clean_city(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    country = ""
    if "," in text:
        text, country = text.split(",", 1)
        country = country.strip()
    parts = [p for p in text.split() if p]
    while parts and parts[0].lower().strip(".,") in _JUNK_PREFIX:
        parts.pop(0)
    while parts and parts[-1].lower().strip(".,") in _JUNK_PREFIX:
        parts.pop()
    if len(parts) > 2:
        if parts[-2].lower() in _MULTI_FIRST:
            parts = parts[-2:]
        else:
            parts = parts[-1:]
    city = " ".join(parts).title()
    if country and country.lower() not in _JUNK_PREFIX:
        city = f"{city}, {country.title()}"
    return city


def _ok_city(city: str) -> bool:
    first = city.split(",")[0].strip().lower()
    if not first or first in _JUNK_PREFIX or len(first) < 3:
        return False
    return not first.isdigit()


def _parse_events(text: str) -> list[dict]:
    found: list[dict] = []
    for match in _RANGE_SAME.finditer(text or ""):
        city, d1, d2, month, year = match.groups()
        city = _clean_city(city)
        if not _ok_city(city):
            continue
        try:
            end = date(int(year), _month_num(month), int(d2))
        except ValueError:
            continue
        label = f"{int(d1)}-{int(d2)} {month.title()} {year}"
        found.append({"city": city, "dates": label, "end": end})
    for match in _RANGE_CROSS.finditer(text or ""):
        city, d1, m1, d2, m2, year = match.groups()
        city = _clean_city(city)
        if not _ok_city(city):
            continue
        try:
            end = date(int(year), _month_num(m2), int(d2))
        except ValueError:
            continue
        label = f"{int(d1)} {m1.title()} – {int(d2)} {m2.title()} {year}"
        found.append({"city": city, "dates": label, "end": end})
    return found


def _city_urls(pages: list[tuple[str, str, list[str]]]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for url, _text, links in pages:
        for href in [url, *links]:
            path = urlparse(href).path.strip("/").split("/")[0].lower()
            if not path or path in {"europe", "ql-redemption"}:
                continue
            clean = href.split("?")[0]
            if path in {"kl", "kualalumpur"}:
                mapped["kuala lumpur"] = clean
            else:
                mapped[path.replace("-", " ")] = clean
    return mapped


def _match_url(city: str, urls: dict[str, str]) -> str:
    key = city.split(",")[0].strip().lower()
    if key in urls:
        return urls[key]
    for name, url in urls.items():
        if name in key or key in name:
            return url
    slug = key.replace(" ", "-")
    return f"https://www.millionairemind.live/{slug}"


def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    today = date.today()
    for row in sorted(rows, key=lambda item: item["end"]):
        if row["end"] < today:
            continue
        key = (row["city"].split(",")[0].strip().lower(), row["dates"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _load_homes() -> list[tuple[str, str, list[str]]]:
    with _lock:
        if _cache["pages"] and (time.time() - _cache["at"]) < _TTL:
            return list(_cache["pages"])
        pages: list[tuple[str, str, list[str]]] = []
        for url in _HOMES:
            try:
                text, links = web.fetch_page(url)
            except Exception:
                continue
            if len(text) >= 40:
                pages.append((url, text, links))
        _cache["pages"] = pages
        _cache["at"] = time.time()
        return list(pages)


def mentioned_city(text: str) -> str:
    blob = (text or "").lower()
    urls = _city_urls(_load_homes())
    for name in sorted(set(urls) | _EUROPE, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", blob):
            return name
    return ""


def fetch_city(city: str) -> str:
    city = (city or "").strip()
    if not city:
        return "no_city"
    url = _match_url(city, _city_urls(_load_homes()))
    raw = web.fetch_url(url)
    venue_bits = _VENUE.findall(raw)[:6]
    extra = "\n".join(venue_bits).strip()
    return (
        f"CITY PAGE for {city} ({url})\n"
        f"{raw[:1800]}\n"
        + (f"VENUE/SCHEDULE SNIPPETS:\n{extra}" if extra else "No venue line on this page. Do not invent a venue.")
    )


def detect_program(text: str, agent: str = "maya") -> str:
    blob = (text or "").lower()
    for name, pattern, _query in _PROGRAMS:
        if re.search(pattern, blob):
            return name
    if (agent or "").lower() in {"quinn", "rafa"}:
        return "ql"
    return "mmi"


def _program_query(program: str, text: str) -> str:
    for name, _pattern, query in _PROGRAMS:
        if name == program:
            return f"{query} {text}".strip()
    return text


def list_events(query: str = "", agent: str = "maya") -> str:
    """Upcoming dates: MMI from millionairemind.live, QL programmes from the QL Sheet + SR pages."""
    program = detect_program(query, agent)
    if program == "mmi":
        return _list_mmi(query, agent)
    return _list_ql(query, agent, program)


def _list_ql(query: str, agent: str, program: str) -> str:
    from agents.tools import sheets

    label = {
        "nwa": "Never Work Again",
        "ewc": "Enlightened Warrior Camp",
        "gbi": "Guerrilla Business Intensive",
        "ttt": "Train the Trainer",
        "ql": "Quantum Leap programmes",
    }.get(program, program)
    sheet = sheets.lookup_sheet(_program_query(program, query), prefer="ql")
    site_bits: list[str] = []
    for url in _QL_HOMES:
        try:
            text, _links = web.fetch_page(url)
        except Exception:
            continue
        if len(text) >= 40:
            site_bits.append(f"URL: {url}\n{text[:1500]}")
    lines = [
        f"LIVE {label} FACTS. Do not use Millionaire Mind Intensive dates for this answer.",
        "Dates and cities only from the QL Sheet or these pages. If missing, set needs_human true.",
        "Prices only from the sheet. Food, accommodation and flights: use hub policy unless the sheet has an event-specific F&A amount.",
        "",
        "QL SHEET:",
        sheet,
    ]
    if site_bits:
        lines.append("\nQL / SR PAGES:\n" + "\n\n".join(site_bits))
    else:
        lines.append("No extra QL page text. Rely on the sheet and the hub.")
    return "\n".join(lines)


def _list_mmi(query: str, agent: str) -> str:
    pages = _load_homes()
    if not pages:
        return (
            "no_events: could not read Success Resources sites. "
            "Do not invent a date or city. Set needs_human true."
        )
    rows: list[dict] = []
    urls = _city_urls(pages)
    for url, text, _links in pages:
        for row in _parse_events(text):
            row["url"] = _match_url(row["city"], urls)
            rows.append(row)
    rows = _dedupe(rows)
    if not rows:
        return (
            "no_events: no upcoming dates parsed from allowlisted pages. "
            "Do not invent. Set needs_human true."
        )

    q = (query or "").lower()
    agent = (agent or "maya").lower()
    europe_only = agent == "maya" and not any(name in q for name in ("asia", "world", "all cities"))
    if europe_only:
        europe = [r for r in rows if r["city"].split(",")[0].strip().lower() in _EUROPE]
        ordered = europe or rows
    else:
        ordered = rows

    city = mentioned_city(query)
    if city:
        focus = [r for r in ordered if city in r["city"].lower()] or ordered[:8]
    else:
        focus = ordered[:10]

    lines = [
        "LIVE UPCOMING EVENTS from millionairemind.live. "
        "Put these dates in the customer email when they ask what is next. "
        "Do not say a person must confirm a date that is listed here.",
    ]
    for row in focus:
        line = f"- {row['city']}: {row['dates']}"
        if row.get("url"):
            line += f" ({row['url']})"
        lines.append(line)
    if city:
        lines.append(
            f"Customer named a city ({city}). Prefer that row. "
            "Venue/times only if the city page stated them."
        )
    elif europe_only and agent == "maya":
        lines.append(
            "Maya/Europe: listed Europe dates first. "
            "Point them to https://www.millionairemind.live/ for the full calendar."
        )
    lines.append("Do not copy ticket prices from these pages. Prices only from lookup_sheet.")
    return "\n".join(lines)
