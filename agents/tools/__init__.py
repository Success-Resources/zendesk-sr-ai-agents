"""Tools the agent is allowed to call. Each tool is ordinary Python we wrote."""

from __future__ import annotations

from agents.tools import docs, hub, sheets, web

TOOLS = {
    "search_hub": hub.search_hub,
    "lookup_sheet": sheets.lookup_sheet,
    "lookup_doc": docs.lookup_doc,
    "search_site": web.search_site,
    "fetch_url": web.fetch_url,
}

TOOL_DOCS = """
You have these tools. Use them. Then write a tailored email. Do not invent facts.

1. search_hub
   action_input: the customer question
   Approved emails and policies from GitHub. Call this first.

2. search_site
   action_input: keywords (city, venue, programme)
   Bounded crawl of Success Resources websites on the allowlist only.

3. fetch_url
   action_input: one https URL that is on the allowlist
   Read that page.

4. lookup_sheet
   action_input: city and programme, e.g. "Warsaw MMI"
   Live Google Sheets (MMI / QL / Rafa / Allocation if configured).
   If it returns no_row, do not quote a price.

5. lookup_doc
   action_input: a short phrase
   Google Docs listed in GOOGLE_DOC_IDS only.

When you need a tool:
{"thought":"why","action":"search_hub","action_input":"...","email":"","needs_human":false,"confidence":0}

When you write the customer email (fresh wording, facts only from tools):
{"thought":"why","action":"final","action_input":"","email":"the full email including sign-off","needs_human":false,"confidence":0.8}

If a person must handle it:
{"thought":"why","action":"final","action_input":"","email":"","needs_human":true,"confidence":0.2}
"""


def run(name: str, action_input: str, agent: str) -> str:
    fn = TOOLS.get(name)
    if fn is None:
        return json_error(f"unknown tool {name}")
    if name == "search_hub":
        return fn(action_input, agent)
    return fn(action_input)


def json_error(msg: str) -> str:
    return f"ERROR: {msg}"
