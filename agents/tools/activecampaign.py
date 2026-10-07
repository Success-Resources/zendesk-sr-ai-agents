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
    """Maya: retrigger the event tag already on this email. Do not check a sheet or add a new tag."""
    if (agent or "").lower() != "maya":
        return "ActiveCampaign confirmation actions are Maya only."
    if _mode() == "off":
        return (
            "tag_found=false AC_TAG=failed: set AGENT_ACTIONS=propose or execute. "
            "Set needs_human true. Do not say a confirmation was sent."
        )
    spam = (
        "Tell them to check inbox, spam, junk and promotions. "
        "Do not mention a Google Sheet or a registration list."
    )
    email = _first_email(query)
    if not email:
        return (
            "tag_found=false AC_TAG=missing reason=no_email. "
            "Set needs_human true. Do not say a confirmation was sent. " + spam
        )
    if not configured():
        return (
            f"tag_found=false AC_TAG=failed email={email}: ActiveCampaign is not configured. "
            "Set needs_human true. Do not say a confirmation was sent."
        )
    try:
        contact = _contact_by_email(email)
    except RuntimeError as exc:
        return (
            f"tag_found=false AC_TAG=failed email={email}: {exc}. "
            "Set needs_human true. Do not say a confirmation was sent."
        )
    if not contact:
        return (
            f"tag_found=false AC_TAG=missing email={email} reason=no_contact. "
            "This address has no ActiveCampaign contact. Do not create one. "
            "Set needs_human true. Do not say they are registered or that a confirmation was sent. "
            + spam
        )
    contact_id = str(contact.get("id") or "")
    try:
        existing = _contact_tags(contact_id)
    except RuntimeError as exc:
        return (
            f"tag_found=false AC_TAG=failed email={email}: {exc}. "
            "Set needs_human true. Do not say a confirmation was sent."
        )
    chosen, why = _select_event_tags(query, existing)
    if not chosen:
        have = ", ".join(row["name"] for row in existing) or "(none)"
        return (
            f"tag_found=false AC_TAG=missing email={email} reason={why} tags={have}. "
            "Do not add a tag. A person must take this ticket. Set needs_human true. "
            "Do not say they are registered or that a confirmation was sent. "
            + spam
        )
    try:
        results = [_retrigger_tag(contact_id, row["name"], existing) for row in chosen]
    except RuntimeError as exc:
        names = ", ".join(row["name"] for row in chosen)
        return (
            f"tag_found=true AC_TAG=failed email={email} tag={names}: {exc}. "
            "Set needs_human true. Do not say a confirmation was sent."
        )
    return (
        f"tag_found=true email={email} {'; '.join(results)}. "
        "The event tag was already on this address, so it was removed and added again. "
        "The confirmation automation will send the email. "
        "Tell the customer it is on its way. Set needs_human false. " + spam
    )


def _account_lists() -> dict[str, str]:
    names: dict[str, str] = {}
    offset = 0
    while offset <= 1000:
        data = _request("GET", f"lists?limit=100&offset={offset}")
        rows = data.get("lists") or []
        for row in rows:
            list_id = str(row.get("id") or "")
            if list_id:
                names[list_id] = (row.get("name") or f"list {list_id}").strip()
        if len(rows) < 100:
            break
        offset += 100
    return names


def _memberships(contact_id: str) -> list[dict]:
    data = _request("GET", f"contacts/{contact_id}/contactLists")
    return list(data.get("contactLists") or [])


def _unsubscribe_one(contact_id: str, list_id: str) -> None:
    _request(
        "POST",
        "contactLists",
        {"contactList": {"list": list_id, "contact": contact_id, "status": 2}},
    )


def ac_unsubscribe_lists(query: str, agent: str = "maya") -> str:
    """Remove the ticket sender from every ActiveCampaign list they are still on."""
    if (agent or "").lower() not in {"maya", "quinn", "rafa"}:
        return "ActiveCampaign unsubscribe is for Maya, Quinn, and Rafa only."
    mode = _mode()
    if mode == "off":
        return "ac_actions_off: set AGENT_ACTIONS=propose or execute. Do not say they were unsubscribed."
    if not configured():
        return (
            "AC_UNSUB=skipped: ActiveCampaign is not configured. "
            "A person must unsubscribe this address from all lists. Do not say it is done."
        )
    email = _first_email(query)
    if not email:
        return (
            "AC_UNSUB=no_email: the Zendesk ticket has no sender email. "
            "Ask which address to remove. Do not say they were unsubscribed."
        )
    try:
        contact = _contact_by_email(email)
    except RuntimeError as exc:
        return f"AC_UNSUB=failed: {exc}. A person must unsubscribe {email}. Do not say it is done."
    if not contact:
        return (
            f"AC_UNSUB=not_found email={email}. "
            "No ActiveCampaign contact for the address on this ticket. "
            "Do not create one. A person should confirm there is no other address. "
            "Do not say they were unsubscribed."
        )
    contact_id = str(contact.get("id") or "")
    try:
        names = _account_lists()
        rows = _memberships(contact_id)
    except RuntimeError as exc:
        return f"AC_UNSUB=failed email={email}: {exc}. A person must finish the lists."
    subscribed = [row for row in rows if str(row.get("status") or "") != "2"]
    if not subscribed:
        return (
            f"AC_UNSUB=already email={email} contact={contact_id}. "
            "They are not on any active ActiveCampaign list. "
            "Tell them marketing mail to this address is already stopped."
        )
    done: list[str] = []
    failed: list[str] = []
    for row in subscribed:
        list_id = str(row.get("list") or "")
        label = names.get(list_id) or f"list {list_id}"
        try:
            _unsubscribe_one(contact_id, list_id)
            done.append(label)
        except RuntimeError as exc:
            failed.append(f"{label} ({exc})")
    if failed and not done:
        return (
            f"AC_UNSUB=failed email={email}. " + "; ".join(failed) +
            ". A person must unsubscribe the remaining lists. Do not say it is done."
        )
    result = f"AC_UNSUB=ok email={email} removed={', '.join(done) or '(none)'}"
    if failed:
        result += " still_failed=" + "; ".join(failed)
        result += ". Tell them the lists that were removed. A person must finish the ones that failed."
    else:
        result += (
            ". Tell them this email has been unsubscribed from marketing lists. "
            "Another promotional email after this can be forwarded so the remaining list can be identified."
        )
    return result
