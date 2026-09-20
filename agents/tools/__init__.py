"""Tools the agent is allowed to call. Each tool is ordinary Python we wrote."""

from __future__ import annotations

from agents.tools import docs, events, hub, sheets, web

TOOLS = {
    "search_hub": hub.search_hub,
    "lookup_sheet": sheets.lookup_sheet,
    "lookup_registration": sheets.lookup_registration,
    "lookup_doc": docs.lookup_doc,
    "list_events": events.list_events,
    "search_site": web.search_site,
    "fetch_url": web.fetch_url,
}

TOOL_DOCS = """
You have these tools. Use LIVE FACTS already in the user message first. Call extra tools only if a fact is still missing.

1. list_events
   action_input: city or "upcoming MMI"
   Upcoming dates parsed from millionairemind.live. Put those dates in the email.

2. search_site
   action_input: keywords (city, venue, programme)
   Bounded crawl of Success Resources websites.

3. fetch_url
   action_input: one https URL on the allowlist, e.g. https://www.millionairemind.live/madrid
   Read that city page for venue/times. Prices on the page are stripped.

4. lookup_sheet
   action_input: city and programme, e.g. "Warsaw MMI"
   Live Google Sheets. If no_row, do not quote a price.

5. lookup_registration
   action_input: customer email and name
   Only confirm a booking if their email is in a matching row. Otherwise ask for the purchase email and set needs_human true.

6. search_hub
   action_input: the customer question
   Approved emails and policies from GitHub.

7. lookup_doc
   action_input: a short phrase
   Google Docs listed in GOOGLE_DOC_IDS only.

When you need a tool:
{"thought":"why","action":"list_events","action_input":"...","email":"","needs_human":false,"confidence":0}

When you write the customer email (fresh wording, facts only from tools):
{"thought":"why","action":"final","action_input":"","email":"the full email including sign-off","needs_human":false,"confidence":0.8}

If a person must handle it (registration not found, refund, missing fact):
{"thought":"why","action":"final","action_input":"","email":"helpful email asking for what we still need","needs_human":true,"confidence":0.2}
"""


def run(name: str, action_input: str, agent: str) -> str:
    fn = TOOLS.get(name)
    if fn is None:
        return json_error(f"unknown tool {name}")
    if name in {"search_hub", "list_events"}:
        return fn(action_input, agent)
    return fn(action_input)


def json_error(msg: str) -> str:
    return f"ERROR: {msg}"
