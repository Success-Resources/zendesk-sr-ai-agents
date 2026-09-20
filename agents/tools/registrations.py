"""MMI registration lists. Full List tab: column E = email, column B = Standard/VIP.

Tag formula: MMI + YY + MM + first three letters of the city, then -Standard or -VIP.
Example: Rotterdam October 2026 Standard → MMI2610ROT-Standard.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_FILE = Path(__file__).resolve().parent.parent / "event-sheets.json"
_TTL = 300
_cache: dict[str, tuple[float, list[list[str]]]] = {}


def configured_events() -> list[dict]:
    items: list[dict] = []
    if _FILE.is_file():
        items.extend(json.loads(_FILE.read_text(encoding="utf-8")))
    extra = (os.getenv("GOOGLE_SHEET_MMI_EVENTS") or "").strip()
    if extra:
        loaded = json.loads(extra)
        if isinstance(loaded, list):
            items.extend(loaded)
    out: list[dict] = []
    seen: set[str] = set()
    for raw in items:
        code = str(raw.get("code") or "").strip().upper()
        sheet_id = str(raw.get("sheet_id") or "").strip()
        if not code or not sheet_id or code in seen:
            continue
        seen.add(code)
        aliases = [str(a).strip().lower() for a in (raw.get("aliases") or []) if str(a).strip()]
        aliases.append(code.lower())
        city = str(raw.get("city") or code).strip()
        aliases.append(city.lower())
        out.append(
            {
                "city": city,
                "code": code,
                "aliases": list(dict.fromkeys(aliases)),
                "sheet_id": sheet_id,
                "tab": str(raw.get("tab") or "Full List").strip() or "Full List",
                "gid": str(raw.get("gid") or "").strip(),
            }
        )
    return out


def first_email(*parts: str) -> str:
    for part in parts:
        match = _EMAIL.search(part or "")
        if match:
            return match.group(0)
    return ""


def detect_events(text: str) -> list[dict]:
    blob = (text or "").lower()
    compact = re.sub(r"\s+", "", blob)
    found: list[dict] = []
    for event in configured_events():
        if event["code"].lower() in compact:
            found.append(event)
            continue
        if any(re.search(rf"\b{re.escape(alias)}\b", blob) for alias in event["aliases"]):
            found.append(event)
    return found


def _download(event: dict) -> list[list[str]]:
    key = f"{event['sheet_id']}|{event['tab']}|{event['gid']}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    urls = [
        (
            f"https://docs.google.com/spreadsheets/d/{event['sheet_id']}"
            f"/gviz/tq?tqx=out:csv&sheet={quote(event['tab'])}"
        )
    ]
    if event["gid"]:
        urls.append(
            f"https://docs.google.com/spreadsheets/d/{event['sheet_id']}"
            f"/export?format=csv&gid={event['gid']}"
        )
    last = "download failed"
    raw = ""
    for url in urls:
        req = Request(url, headers={"User-Agent": "sr-zendesk-ai-agent"})
        try:
            with urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except HTTPError as exc:
            last = f"HTTP {exc.code}"
        except URLError as exc:
            last = str(exc.reason)
    if not raw:
        raise RuntimeError(last)
    rows = list(csv.reader(io.StringIO(raw)))
    _cache[key] = (time.time(), rows)
    return rows


def _header_index(header: list[str], names: set[str], fallback: int) -> int:
    for index, cell in enumerate(header):
        if cell.strip().lower() in names:
            return index
    return fallback if fallback < len(header) else 0


def _category(lead_source: str, ticket_type: str) -> str:
    blob = f"{lead_source} {ticket_type}"
    if re.search(r"\bvip\b", blob, re.I):
        return "VIP"
    if re.search(r"\bstandard\b", blob, re.I):
        return "Standard"
    return ""


def _cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def _find_row(event: dict, email: str) -> dict | None:
    rows = _download(event)
    if not rows:
        return None
    header = rows[0]
    email_i = _header_index(header, {"email", "e-mail"}, 4)
    source_i = _header_index(header, {"lead source"}, 1)
    type_i = _header_index(header, {"type"}, 11)
    first_i = _header_index(header, {"first name", "firstname"}, 2)
    last_i = _header_index(header, {"last name", "lastname"}, 3)
    wanted = email.strip().lower()
    for row in rows[1:]:
        if _cell(row, email_i).lower() != wanted:
            continue
        category = _category(_cell(row, source_i), _cell(row, type_i))
        return {
            "city": event["city"],
            "code": event["code"],
            "category": category,
            "tag": f"{event['code']}-{category}" if category else "",
            "first": _cell(row, first_i),
            "last": _cell(row, last_i),
        }
    return None


def lookup_event_registration(query: str) -> str:
    """Find the requester on a city Full List. Never dumps other attendees."""
    email = first_email(query)
    if not email:
        return (
            "sheet_no_email: no email in the ticket. Ask for the purchase / registration email "
            "and which MMI city. Set needs_human true. Do not add an ActiveCampaign tag."
        )
    events = configured_events()
    if not events:
        return "sheet_not_configured: no MMI event sheets listed in agents/event-sheets.json."
    named = detect_events(query)
    search = named or events
    matches: list[dict] = []
    errors: list[str] = []
    for event in search:
        try:
            found = _find_row(event, email)
        except Exception as exc:
            errors.append(f"{event['code']}: {exc}")
            continue
        if found:
            matches.append(found)
    if matches:
        lines = [
            f"sheet_found=true email={email} searched={','.join(e['code'] for e in search)}"
        ]
        for match in matches:
            lines.append(
                f"event={match['city']} code={match['code']} category={match['category'] or 'UNKNOWN'} "
                f"tag={match['tag'] or 'NONE'} name={match['first']} {match['last']}".rstrip()
            )
        lines.append(
            "Maya may tell them we found their registration. Always ask them to check spam/junk/"
            "promotions. Add only the tag shown above in ActiveCampaign."
        )
        return "\n".join(lines)
    hint = "; ".join(errors) if errors else "email not on Full List"
    cities = ", ".join(e["city"] for e in search)
    codes = ", ".join(e["code"] for e in search)
    if named:
        return (
            f"sheet_found=false email={email} lists={codes} detail={hint}. "
            f"Do not confirm they are registered for {cities}. "
            "Ask if they used a different purchase email. Set needs_human true. "
            "Do not add an ActiveCampaign tag."
        )
    return (
        f"sheet_found=false email={email} lists={codes} detail={hint}. "
        "Ask which MMI city they registered for, and the purchase email if it may differ. "
        "Set needs_human true. Do not add an ActiveCampaign tag."
    )
