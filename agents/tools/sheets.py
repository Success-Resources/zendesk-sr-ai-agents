"""Live Google Sheets via public CSV export. No invented prices if export fails."""

from __future__ import annotations

import csv
import io
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_DEFAULT = {
    "mmi": "1I0_drElvOqO4RLeAC-cBjXr6ekXQ_OAGbRigwOyjYCE",
    "ql": "12z82ByWdS-_wJxPWlrN2F4TNZ2Cq92Dm1bbA_hIKimE",
    "rafa": "1_nudcBpyJZiUkKKeufXWpwfsbBVOT4XpxHNX-fmbC-E",
}


def _sheets() -> dict[str, str]:
    out = dict(_DEFAULT)
    out["mmi"] = (os.getenv("GOOGLE_SHEET_MMI") or out["mmi"]).strip()
    out["ql"] = (os.getenv("GOOGLE_SHEET_QL") or out["ql"]).strip()
    out["rafa"] = (os.getenv("GOOGLE_SHEET_RAFA") or out["rafa"]).strip()
    extra = (os.getenv("GOOGLE_SHEET_ALLOCATION") or "").strip()
    if extra:
        out["allocation"] = extra
    registrations = (os.getenv("GOOGLE_SHEET_REGISTRATIONS") or "").strip()
    if registrations:
        out["registrations"] = registrations
    return {k: v for k, v in out.items() if v}


def _download_csv(sheet_id: str) -> str:
    urls = [
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv",
    ]
    last = ""
    for url in urls:
        req = Request(url, headers={"User-Agent": "sr-zendesk-ai-agent"})
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last = f"HTTP {exc.code}"
        except URLError as exc:
            last = str(exc.reason)
    raise RuntimeError(last or "download failed")


def lookup_sheet(query: str) -> str:
    q = (query or "").strip()
    words = {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", q)}
    blocks: list[str] = []
    failures: list[str] = []
    for name, sheet_id in _sheets().items():
        try:
            raw = _download_csv(sheet_id)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        rows = list(csv.reader(io.StringIO(raw)))
        if not rows:
            continue
        header = rows[0]
        scored: list[tuple[int, str]] = []
        for row in rows[1:]:
            line = " | ".join(cell.strip() for cell in row if cell.strip())
            if not line:
                continue
            blob = line.lower()
            score = sum(1 for w in words if w in blob) if words else 0
            scored.append((score, line))
        scored.sort(key=lambda item: item[0], reverse=True)
        picked = [line for score, line in scored[:5] if (not words or score > 0)]
        if not picked and not words:
            picked = [line for _, line in scored[:5]]
        if picked:
            cols = " | ".join(header[:12])
            blocks.append(
                f"Sheet {name} ({sheet_id})\nColumns: {cols}\n" + "\n".join(picked)
            )
    if blocks:
        return "\n\n".join(blocks)
    hint = "; ".join(failures) if failures else "no matching rows"
    return (
        f"no_row: {hint}. Query was: {q or '(empty)'}. "
        "Share the Sheet as Viewer to anyone with the link, or Publish to web, "
        "then retry. Do not invent a price, date, or venue."
    )


def lookup_registration(query: str) -> str:
    """Look up a customer email/name. Never confirm registration on a miss."""
    q = (query or "").strip()
    emails = re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", q, flags=re.I)
    result = lookup_sheet(q)
    blob = result.lower()
    if result.startswith("no_row") or not q:
        return (
            "registration_not_found: no sheet row matched. "
            "Do not tell the customer they are registered. "
            "Ask for the purchase email and event city/date. Set needs_human true. "
            f"Query was: {q or '(empty)'}."
        )
    if emails and not any(e.lower() in blob for e in emails):
        return (
            "registration_not_found: sheet rows came back but none contain this email. "
            "Do not confirm registration. Ask a person to check. "
            f"Email tried: {emails[0]}."
        )
    return (
        "registration_possible_match (a person must still confirm before you tell the "
        "customer they are booked):\n" + result
    )
