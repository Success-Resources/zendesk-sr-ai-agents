#!/usr/bin/env python3
"""Post Maya's answer on tickets she has not replied to yet.

Dry-run is the default: it prints the reply and whether she would solve or
hand off, and it posts nothing. Pass --live to post.

Each ticket is read again immediately before the action. A ticket is skipped
when it is no longer new or open, when anyone other than the requester has a
public reply (an internal Maya draft does not count), or when the recipient
is srv@. Requests are paced so the Zendesk and model limits are not hit.

Default scope (four Zendesk searches, unioned):

  created after 2025-12-31 (so from 2026-01-01), status new or open, and
  - recipient info.eu@srglobal.com, or
  - recipient mmo@srglobal.com, or
  - tag mmi and recipient clientcare.eu@srglobal.com, or
  - tag mmi and recipient support.eu@srglobal.com

Usage:
  python scripts/backfill.py --demo
  python scripts/backfill.py --csv tickets.csv
  python scripts/backfill.py --search 'type:ticket status<pending created>2025-12-31 recipient:info.eu@srglobal.com'
  python scripts/backfill.py --csv tickets.csv --live
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "service"))

import flow  # noqa: E402


def ids_from_csv(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"{path} has no header row")
        fields = {name.strip().lower(): name for name in reader.fieldnames}
        key = fields.get("id") or fields.get("ticket_id")
        if not key:
            raise SystemExit(f"{path} needs an id or ticket_id column")
        ids: list[str] = []
        for row in reader:
            value = str(row.get(key) or "").strip()
            if value:
                ids.append(value)
        return ids


def search_ticket_ids(queries: list[str], get_json) -> list[str]:
    """Page a Zendesk search. get_json takes an /api/v2 path and returns a dict or None."""
    found: list[str] = []
    seen: set[str] = set()
    for query in queries:
        path = "search.json?query=" + quote(query) + "&per_page=100"
        while path:
            data = get_json(path)
            if not data:
                break
            for row in data.get("results") or []:
                if row.get("result_type") not in (None, "ticket"):
                    continue
                ticket_id = str(row.get("id") or "").strip()
                if ticket_id and ticket_id not in seen:
                    seen.add(ticket_id)
                    found.append(ticket_id)
            nxt = str(data.get("next_page") or "")
            path = nxt.split("/api/v2/", 1)[1] if "/api/v2/" in nxt else ""
    return found


def _dedupe(ids: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for ticket_id in ids:
        text = str(ticket_id).strip()
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return ordered


def run_one(ticket_id: str, *, live: bool) -> dict:
    import app

    if not app._claim_ticket(ticket_id):
        return {
            "action": "skip",
            "reason": "already processing",
            "reply": "",
            "assignee": "",
            "lane": "",
            "agent": "",
            "tags": [],
            "posted": False,
        }
    try:
        return app._process_ticket(ticket_id, live=live, backfill=True)
    finally:
        app._release_ticket(ticket_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill public Maya replies. Dry-run unless --live.")
    parser.add_argument("--csv", help="CSV with an id or ticket_id column")
    parser.add_argument(
        "--search",
        action="append",
        default=[],
        help="Zendesk search query. Repeat to union several. Default is the Jan 2026 scope.",
    )
    parser.add_argument("--live", action="store_true", help="Post replies. Omit to dry-run.")
    parser.add_argument("--demo", action="store_true", help="Print three mocked dry-runs and exit.")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many tickets. 0 means all.")
    parser.add_argument(
        "--pause",
        type=float,
        default=None,
        help="Seconds between tickets. Default BACKFILL_PAUSE_SECONDS or 3.",
    )
    args = parser.parse_args(argv)

    if args.demo:
        for ticket_id, outcome in flow.demo_cases():
            print(flow.format_outcome(ticket_id, outcome))
            print()
        return 0

    import app

    ids: list[str] = []
    if args.csv:
        ids.extend(ids_from_csv(args.csv))
    queries = args.search or ([] if args.csv else list(flow.BACKFILL_SEARCHES))
    if queries:
        if not app._zendesk_configured():
            print(
                "Zendesk is not configured. Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN.",
                file=sys.stderr,
            )
            return 1
        ids.extend(search_ticket_ids(queries, app._zendesk_get))
    ids = _dedupe(ids)
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        print("No ticket ids.")
        return 0

    pause = args.pause
    if pause is None:
        raw = (os.getenv("BACKFILL_PAUSE_SECONDS") or "").strip()
        pause = float(raw) if raw else 3.0

    mode = "LIVE" if args.live else "dry-run"
    print(f"{mode}: {len(ids)} ticket(s), pause {pause:.1f}s")
    counts: dict[str, int] = {}
    for index, ticket_id in enumerate(ids):
        outcome = run_one(ticket_id, live=args.live)
        print(flow.format_outcome(ticket_id, outcome))
        print()
        action = str(outcome.get("action") or "skip")
        counts[action] = counts.get(action, 0) + 1
        if pause > 0 and index < len(ids) - 1:
            time.sleep(pause)
    summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    print(f"done {mode}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
