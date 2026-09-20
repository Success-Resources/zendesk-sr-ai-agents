"""Tools the agent is allowed to call. Each tool is ordinary Python we wrote."""

from __future__ import annotations

from agents.tools import activecampaign, docs, events, hub, links, registrations, sheets, web

TOOLS = {
    "search_hub": hub.search_hub,
    "lookup_sheet": sheets.lookup_sheet,
    "lookup_registration": sheets.lookup_registration,
    "lookup_event_registration": registrations.lookup_event_registration,
    "lookup_links": links.lookup_links,
    "lookup_ac": activecampaign.lookup_ac,
    "ac_fix_confirmation": activecampaign.ac_fix_confirmation,
    "lookup_doc": docs.lookup_doc,
    "list_events": events.list_events,
    "search_site": web.search_site,
    "fetch_url": web.fetch_url,
}

TOOL_DOCS = """
You have these tools. Use LIVE FACTS already in the user message first. Call extra tools only if a fact is still missing.

1. list_events
   action_input: "next Never Work Again" or "upcoming MMI" or "EWC city"
   MMI: dates from millionairemind.live. QL programmes: dates from the QL Google Sheet, not MMI.

2. search_site
   action_input: keywords (city, venue, programme)
   Bounded crawl of Success Resources websites only — not Google.

3. fetch_url
   action_input: one https URL on the allowlist
   Read that page. Prices on the page are stripped.

4. lookup_sheet
   action_input: programme and city, e.g. "Never Work Again" or "EWC food accommodation"
   Live Google Sheets (Quinn = QL sheet, Maya = MMI sheet). If no_row, do not quote a price or date.

5. lookup_registration / lookup_event_registration
   action_input: customer email plus the MMI city if they named one
   Full List tab: column E = email, column B = Standard/VIP.
   Only confirm a booking if sheet_found=true. Otherwise ask for the purchase email and city.

6. lookup_links
   action_input: the ticket text (city/country if they named one)
   MMI registration (millionairemind.live), city factsheets (sr-event.com), Facebook groups, WhatsApp groups.
   If the city/country is missing, ask for it. Do not invent a group or factsheet URL.

7. search_hub
   action_input: the customer question
   Approved emails and policies from GitHub.

8. lookup_ac
   action_input: the customer email
   Read-only ActiveCampaign contact and tags. Maya uses this when they did not get a confirmation email or e-ticket.

9. ac_fix_confirmation
   action_input: customer email plus the ticket text (city / MMI code)
   Maya only. Checks that city's Full List. If the email is there, adds
   MMIYYMMCCC-Standard or MMIYYMMCCC-VIP in ActiveCampaign. If that tag is
   already on the contact, it is removed and added again so the automation fires.

10. lookup_doc
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
    if name == "lookup_sheet":
        prefer = {"maya": "mmi", "quinn": "ql", "rafa": "rafa"}.get(agent, "")
        return fn(action_input, prefer)
    if name == "ac_fix_confirmation":
        return fn(action_input, agent)
    return fn(action_input)


def json_error(msg: str) -> str:
    return f"ERROR: {msg}"
