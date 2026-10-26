"""Current MMI fact sheets from the 2026 customer-service sheet, column D."""

from __future__ import annotations

import csv
import io
import os
import re
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_SHEET = "1wcTMXtbqqdgTvMfSwhXwcP0uOOFqSR8PtZWSvMjL3cQ"
_GID = "216008692"
_MAX_PDF = 12_000_000
_CACHE: dict[str, tuple[float, str]] = {}
_TTL = 60 * 60

# City word -> event-code suffix. Longer names are checked first.
_CITIES = (
    ("rotterdam", "ROT"),
    ("birmingham", "BIR"),
    ("brussels", "BRU"),
    ("bucharest", "BUC"),
    ("stockholm", "STO"),
    ("amsterdam", "AMS"),
    ("manchester", "MAN"),
    ("barcelona", "BAR"),
    ("ljubljana", "LJU"),
    ("frankfurt", "FRA"),
    ("the hague", "UTR"),
    ("hague", "UTR"),
    ("cologne", "COL"),
    ("munich", "MUN"),
    ("zurich", "ZUR"),
    ("geneva", "GEN"),
    ("london", "LON"),
    ("berlin", "BER"),
    ("madrid", "MAD"),
    ("warsaw", "WAR"),
    ("hamburg", "HAM"),
    ("krakow", "KRA"),
    ("oslo", "OSL"),
    ("rome", "ROM"),
    ("cluj", "CLU"),
)
_CODE = re.compile(r"MMI(\d{2})(\d{2})([A-Z]{3})", re.I)


def _sheet_id() -> str:
    return (os.getenv("GOOGLE_SHEET_FACTSHEETS") or _SHEET).strip()


def _gid() -> str:
    return (os.getenv("GOOGLE_SHEET_FACTSHEETS_GID") or _GID).strip()


def _get(url: str, limit: int) -> tuple[str, bytes, str]:
    req = Request(url, headers={"User-Agent": "sr-zendesk-ai-agent"})
    with urlopen(req, timeout=40) as resp:
        final = resp.geturl()
        kind = (resp.headers.get("Content-Type") or "").lower()
        return final, resp.read(limit), kind


def _csv_rows() -> list[list[str]]:
    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{_sheet_id()}/export?format=csv&gid={_gid()}"
    )
    _final, raw, _kind = _get(url, 2_000_000)
    return list(csv.reader(io.StringIO(raw.decode("utf-8", errors="replace"))))


def _columns(header: list[str]) -> tuple[int, int]:
    fact = 3
    event = 1
    for index, cell in enumerate(header):
        name = cell.strip().lower()
        if name.startswith("factsheet"):
            fact = index
        elif name.startswith("event"):
            event = index
    return event, fact


def _city(query: str) -> tuple[str, str]:
    blob = f" {(query or '').lower()} "
    for name, suffix in _CITIES:
        if f" {name} " in blob:
            return name, suffix
    return "", ""


def _when(code: str) -> int:
    match = _CODE.search(code or "")
    if not match:
        return 0
    return int(match.group(1)) * 100 + int(match.group(2))


def _pick(query: str, rows: list[list[str]]) -> tuple[str, str, str] | None:
    """Return event code, fact sheet URL, and city for the row that matches the question."""
    if not rows:
        return None
    event_i, fact_i = _columns(rows[0])
    city, suffix = _city(query)
    code_in_query = _CODE.search(query or "")
    chosen: list[tuple[int, str, str]] = []
    for row in rows[1:]:
        if fact_i >= len(row) or event_i >= len(row):
            continue
        url = row[fact_i].strip()
        code = row[event_i].strip().upper()
        if not url.lower().startswith("http"):
            continue
        blob = " ".join(row).lower()
        hit = False
        if code_in_query and code_in_query.group(0).upper() == code:
            hit = True
        elif suffix and code.endswith(suffix):
            hit = True
        elif city and city in blob:
            hit = True
        if hit:
            chosen.append((_when(code), code, url))
    if not chosen:
        return None
    today = date.today()
    now = (today.year % 100) * 100 + today.month
    upcoming = [row for row in chosen if row[0] >= now]
    pool = upcoming or chosen
    pool.sort(key=lambda row: row[0])
    # Soonest upcoming row. If every row is already past, use the latest, not the oldest.
    _when_code, code, url = pool[0] if upcoming else pool[-1]
    return code, url, city


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages[:6]:
        parts.append(page.extract_text() or "")
    return re.sub(r"[ \t]+\n", "\n", "\n".join(parts)).strip()


def _read_link(url: str) -> str:
    cached = _CACHE.get(url)
    if cached and time.time() - cached[0] < _TTL:
        return cached[1]
    final, raw, kind = _get(url, _MAX_PDF)
    if raw[:4] == b"%PDF" or "pdf" in kind:
        text = _pdf_text(raw)
    else:
        html = raw.decode("utf-8", errors="replace")
        shared = re.search(r'"sharedName":"([A-Za-z0-9]+)"', html)
        item = re.search(r'"itemID":(\d+)', html)
        if not shared or not item:
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()[:4000]
        else:
            host = urlparse(final)
            download = (
                f"{host.scheme}://{host.netloc}/index.php?rm=box_download_shared_file"
                f"&shared_name={shared.group(1)}&file_id=f_{item.group(1)}"
            )
            _box_url, pdf, _pdf_kind = _get(download, _MAX_PDF)
            text = _pdf_text(pdf) if pdf[:4] == b"%PDF" else ""
    text = text[:5000]
    _CACHE[url] = (time.time(), text)
    return text


def lookup_factsheet(query: str) -> str:
    """Open the current fact sheet for the city named in the question."""
    try:
        picked = _pick(query, _csv_rows())
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        return f"FACTSHEET_PAGE missing. The 2026 sheet could not be read ({exc}). Do not invent a venue."
    if not picked:
        return (
            "FACTSHEET_PAGE missing. No city from the 2026 fact sheet list was named. "
            "Ask which event city they mean. Do not send another city's fact sheet."
        )
    code, url, city = picked
    try:
        text = _read_link(url)
    except Exception as exc:
        return (
            f"FACTSHEET_PAGE code={code} url={url} unreadable ({exc}). "
            "You may send the link. Do not invent the venue."
        )
    if len(text) < 40:
        return (
            f"FACTSHEET_PAGE code={code} url={url}\n"
            "The file opened but almost no text could be read. Send the link and leave the ticket open."
        )
    place = city or code
    return (
        f"FACTSHEET_PAGE city={place} code={code}\n"
        f"URL: {url}\n"
        "Answer the venue, address, dates, and schedule from this file. "
        "You may send this link. Do not use another event's fact sheet.\n"
        f"{text}"
    )
