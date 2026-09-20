"""ActiveCampaign lookup and Maya-only confirmation actions.

Confirmation resend is tag-based: if the email is on that MMI Full List,
Maya adds MMIYYMMCCC-Standard or MMIYYMMCCC-VIP. If that tag is already on
the contact, she removes it and adds it again so the AC automation fires.
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

from agents.tools import registrations

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


def ac_fix_confirmation(query: str, agent: str = "maya") -> str:
    """Maya: Full List match → add MMIYYMMCCC-Standard or -VIP in ActiveCampaign."""
    if (agent or "").lower() != "maya":
        return "ActiveCampaign confirmation actions are Maya only."
    mode = _mode()
    if mode == "off":
        return "ac_actions_off: set AGENT_ACTIONS=propose or execute."

    sheet = registrations.lookup_event_registration(query)
    email = registrations.first_email(query)
    looked = lookup_ac(query) if email else "ac_no_email"
    spam = (
        "Always tell the customer to check inbox, spam, junk and promotions. "
        "Do not invent a ticket number. E-tickets still go out 3–5 days before the event."
    )

    if not sheet.startswith("sheet_found=true"):
        return (
            f"{sheet}\n{looked}\n"
            "PLAN: do not add an ActiveCampaign tag until the email is on that city's Full List. "
            f"{spam}"
        )

    tags = re.findall(r"\btag=(MMI\d{4}[A-Z]{3}-(?:Standard|VIP))\b", sheet)
    if not tags:
        return (
            f"{sheet}\n{looked}\n"
            "PLAN: they are on the list but Standard/VIP is missing. A person must pick the tag. "
            f"{spam}"
        )
    plan = (
        "PLAN: in ActiveCampaign, add tag(s) "
        + ", ".join(tags)
        + ". If the tag is already on the contact, remove it and add it again "
        "so the confirmation automation is triggered."
    )

    if not configured():
        return (
            f"{sheet}\n{looked}\n{plan}\n"
            "AC_TAG=skipped: ActiveCampaign is not configured. A person must add or re-add the tag. "
            f"{spam}"
        )

    first = last = ""
    name_match = re.search(r"\bname=(\S+)\s+(\S+)", sheet)
    if name_match:
        first, last = name_match.group(1), name_match.group(2)
    try:
        contact = _contact_by_email(email)
        created = False
        if not contact:
            contact = _create_contact(email, first, last)
            created = True
        contact_id = str(contact.get("id") or "")
        existing = _contact_tags(contact_id) if contact_id else []
        results = [_retrigger_tag(contact_id, tag, existing) for tag in tags]
    except RuntimeError as exc:
        return f"{sheet}\n{looked}\n{plan}\nAC_TAG=failed: {exc}. A person must finish this."
    created_bit = " created contact;" if created else ""
    retriggered = any("AC_TAG=retriggered" in row for row in results)
    added = any("AC_TAG=added" in row for row in results)
    return (
        f"{sheet}\n{looked}\n{plan}\n"
        f"MODE=execute OK:{created_bit} {'; '.join(results)}. "
        "Tell the customer the confirmation is on its way and to check spam. "
        + ("The city tag was already there, so it was removed and added again. " if retriggered else "")
        + ("The city tag was added. " if added and not retriggered else "")
        + spam
    )
