"""ActiveCampaign lookup and Maya-only confirmation actions.

A missing confirmation or e-ticket does not use the registration sheet.
Maya looks up the Zendesk ticket email in ActiveCampaign. The event tag is
MMI + year + month + the city's first three letters, then -Standard or -VIP.
Stockholm in September 2026 is MMI2609STO-VIP or MMI2609STO-Standard.
Madrid in October 2026 is MMI2610MAD-VIP or MMI2610MAD-Standard.
If that tag is already on the contact, she removes it and adds it again so
the automation sends the email. If it is not there, she does not add it.
Never runs for Rafa.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from agents.tools import events, registrations

_EMAIL = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)


def _mode() -> str:
    value = (os.getenv("AGENT_ACTIONS") or "propose").strip().lower()
    return value if value in {"off", "propose", "execute"} else "propose"


def configured() -> bool:
    return bool(_base() and _token())


def _base() -> str:
    raw = (os.getenv("ACTIVECAMPAIGN_URL") or os.getenv("AC_API_URL") or "").strip().rstrip("/")
    if raw.endswith("/api/3"):
        raw = raw[: -len("/api/3")]
    return raw


def _token() -> str:
    return (os.getenv("ACTIVECAMPAIGN_API_TOKEN") or os.getenv("AC_API_TOKEN") or "").strip()


def _mmi_tag_names() -> set[str]:
    raw = os.getenv("AC_MMI_TAG") or os.getenv("ACTIVECAMPAIGN_MMI_TAG") or "MMI"
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{_base()}/api/3/{path.lstrip('/')}"
    headers = {
        "Api-Token": _token(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"ActiveCampaign HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"ActiveCampaign connection error: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


def _first_email(*parts: str) -> str:
    for part in parts:
        match = _EMAIL.search(part or "")
        if match:
            return match.group(0)
    return ""


def _contact_by_email(email: str) -> dict | None:
    qs = urlencode({"email": email})
    data = _request("GET", f"contacts?{qs}")
    contacts = data.get("contacts") or []
    return contacts[0] if contacts else None


def _contact_tags(contact_id: str) -> list[dict]:
    data = _request("GET", f"contacts/{contact_id}/contactTags")
    out: list[dict] = []
    for row in data.get("contactTags") or []:
        contact_tag_id = str(row.get("id") or "")
        tag_id = str(row.get("tag") or "")
        if not contact_tag_id or not tag_id:
            continue
        try:
            tag = _request("GET", f"tags/{tag_id}").get("tag") or {}
        except RuntimeError:
            continue
        name = (tag.get("tag") or "").strip()
        if name:
            out.append({"id": contact_tag_id, "tag_id": tag_id, "name": name})
    return out


def _tag_names(contact_id: str) -> list[str]:
    return [row["name"] for row in _contact_tags(contact_id)]


def _has_mmi_tag(names: list[str]) -> bool:
    have = {n.lower() for n in names}
    return bool(have & _mmi_tag_names())


def _tag_id(name: str) -> str:
    data = _request("GET", f"tags?search={quote(name)}")
    for row in data.get("tags") or []:
        if (row.get("tag") or "").strip().lower() == name.lower():
            return str(row.get("id") or "")
    created = _request("POST", "tags", {"tag": {"tag": name, "tagType": "contact"}})
    tag = created.get("tag") or {}
    tag_id = str(tag.get("id") or "")
    if not tag_id:
        raise RuntimeError(f"could not create ActiveCampaign tag {name}")
    return tag_id


def _remove_tag(contact_tag_id: str) -> None:
    _request("DELETE", f"contactTags/{contact_tag_id}")


def _apply_tag(contact_id: str, tag_id: str) -> None:
    _request(
        "POST",
        "contactTags",
        {"contactTag": {"contact": contact_id, "tag": tag_id}},
    )


def _retrigger_tag(contact_id: str, tag_name: str, existing: list[dict]) -> str:
    """Add the tag. If it is already on the contact, remove then add so AC fires again."""
    tag_id = _tag_id(tag_name)
    present = [row for row in existing if row["name"].lower() == tag_name.lower()]
    if present:
        for row in present:
            _remove_tag(row["id"])
        time.sleep(0.4)
        _apply_tag(contact_id, tag_id)
        return f"AC_TAG=retriggered tag={tag_name}"
    _apply_tag(contact_id, tag_id)
    return f"AC_TAG=added tag={tag_name}"


def _create_contact(email: str, first: str, last: str) -> dict:
    data = _request(
        "POST",
        "contacts",
        {"contact": {"email": email, "firstName": first, "lastName": last}},
    )
    contact = data.get("contact") or {}
    if not contact.get("id"):
        raise RuntimeError(f"could not create ActiveCampaign contact for {email}")
    return contact


def lookup_ac(query: str) -> str:
    """Read-only: contact + tags for the email in the ticket."""
    if not configured():
        return (
            "ac_not_configured: set ACTIVECAMPAIGN_URL and ACTIVECAMPAIGN_API_TOKEN on Render. "
            "Do not invent a registration. Ask for the purchase email if needed."
        )
    email = _first_email(query)
    if not email:
        return (
            "ac_no_email: no email in the ticket. Ask for the purchase / registration email. "
            "Set needs_human true. Do not start an automation."
        )
    try:
        contact = _contact_by_email(email)
    except RuntimeError as exc:
        return f"ac_error: {exc}. A person should check ActiveCampaign."
    if not contact:
        return (
            f"ac_not_found: no ActiveCampaign contact for {email}. "
            "Do not tell them they are registered. Ask a person to check the purchase email."
        )
    contact_id = str(contact.get("id") or "")
    try:
        tags = _tag_names(contact_id)
    except RuntimeError as exc:
        return f"ac_error: contact {contact_id} found but tags failed ({exc})."
    mmi = _has_mmi_tag(tags)
    return (
        f"AC contact id={contact_id} email={contact.get('email') or email} "
        f"name={(contact.get('firstName') or '')} {(contact.get('lastName') or '')}\n"
        f"tags={', '.join(tags) or '(none)'}\n"
        f"mmi_tag_present={str(mmi).lower()} "
        f"(looking for: {', '.join(sorted(_mmi_tag_names())) or 'MMI'})"
    )


_EVENT_TAG = re.compile(r"^MMI(\d{2})(\d{2})([A-Z]{3})-(Standard|VIP)$", re.I)
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _months_in(text: str) -> set[int]:
    blob = (text or "").lower()
    found: set[int] = set()
    for index, name in enumerate(_MONTH_NAMES, 1):
        if name == "may":
            if re.search(r"\b(?:\d{1,2}\s+may|may\s+20\d{2}|in may)\b", blob):
                found.add(index)
            continue
        if re.search(rf"\b{name}\b", blob):
            found.add(index)
    return found


def _event_rows(existing: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in existing:
        match = _EVENT_TAG.match(str(row.get("name") or "").strip())
        if not match:
            continue
        yy, mm, city, _kind = match.groups()
        rows.append(
            {
                **row,
                "yy": yy,
                "mm": mm,
                "city": city.upper(),
                "prefix": f"MMI{yy}{mm}{city.upper()}",
            }
        )
    return rows


def _select_event_tags(query: str, existing: list[dict]) -> tuple[list[dict], str]:
    """Pick the Standard/VIP tag for the event in the ticket. Do not invent one."""
    parsed = _event_rows(existing)
    if not parsed:
        return [], "no_event_tag"

    explicit = {code.upper() for code in re.findall(r"\b(MMI\d{4}[A-Z]{3})\b", query or "", re.I)}
    configured = {event["code"].upper() for event in registrations.detect_events(query)}
    city = events.mentioned_city(query)
    city3 = re.sub(r"[^A-Za-z]", "", (city or "").split(",")[0])[:3].upper()
    narrowed = False
    chosen = parsed
    if explicit or configured or len(city3) == 3:
        def matches(row: dict) -> bool:
            if row["prefix"] in explicit or row["prefix"] in configured:
                return True
            return len(city3) == 3 and row["city"] == city3

        chosen = [row for row in parsed if matches(row)]
        narrowed = True
        if not chosen:
            return [], "event_tag_not_on_contact"
    elif len({row["prefix"] for row in parsed}) != 1:
        return [], "several_events"

    months = _months_in(query)
    if months:
        month_hit = [row for row in chosen if int(row["mm"]) in months]
        if not month_hit:
            return [], "event_tag_not_on_contact"
        chosen = month_hit
    years = {year[2:] for year in re.findall(r"\b(20\d{2})\b", query or "")}
    if years:
        year_hit = [row for row in chosen if row["yy"] in years]
        if not year_hit:
            return [], "event_tag_not_on_contact"
        chosen = year_hit

    prefixes = {row["prefix"] for row in chosen}
    if len(prefixes) > 1:
        live = set(events.mmi_codes_for_city(city)) if city else set()
        live_hit = [row for row in chosen if row["prefix"] in live]
        if len({row["prefix"] for row in live_hit}) == 1:
            chosen = live_hit
        else:
            return [], "several_events"
    if not chosen and not narrowed:
        return [], "no_event_tag"
    return chosen, "matched"


def ac_fix_confirmation(query: str, agent: str = "maya") -> str:
    """Maya does not resend confirmations. A person does that, and the ticket stays open."""
    if (agent or "").lower() != "maya":
        return "ActiveCampaign confirmation actions are Maya only."
    return (
        "AC_ACTION=not_performed. Do not say a confirmation or e-ticket was re-sent. "
        "Tell the customer the team will resend it and set needs_human true."
    )



def ac_unsubscribe_lists(query: str, agent: str = "maya") -> str:
    """Maya does not unsubscribe. A person removes the address, and the ticket stays open."""
    if (agent or "").lower() not in {"maya", "quinn", "rafa"}:
        return "ActiveCampaign unsubscribe is for Maya, Quinn, and Rafa only."
    return (
        "AC_ACTION=not_performed. Do not say the address was removed. "
        "Tell the customer the team will remove it and set needs_human true."
    )
