"""ActiveCampaign lookup and Maya-only confirmation actions.

propose (default): look up the contact and say what Maya would do.
execute: start the resend automation if the MMI tag is present, otherwise start
the main MMI automation. Never creates a contact. Never runs for Rafa.
"""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def _id(name: str) -> str:
    return (os.getenv(name) or "").strip()


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


def _tag_names(contact_id: str) -> list[str]:
    data = _request("GET", f"contacts/{contact_id}/contactTags")
    names: list[str] = []
    for row in data.get("contactTags") or []:
        tag_id = str(row.get("tag") or "")
        if not tag_id:
            continue
        try:
            tag = _request("GET", f"tags/{tag_id}").get("tag") or {}
        except RuntimeError:
            continue
        name = (tag.get("tag") or "").strip()
        if name:
            names.append(name)
    return names


def _has_mmi_tag(names: list[str]) -> bool:
    have = {n.lower() for n in names}
    return bool(have & _mmi_tag_names())


def _start_automation(contact_id: str, automation_id: str) -> str:
    if not automation_id:
        return "skipped: automation id is not set on Render"
    _request(
        "POST",
        "contactAutomations",
        {"contactAutomation": {"contact": contact_id, "automation": automation_id}},
    )
    return f"started automation {automation_id}"


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
    """Maya: if MMI tag exists, resend confirmation; otherwise start the MMI automation."""
    if (agent or "").lower() != "maya":
        return "ActiveCampaign confirmation actions are Maya only."
    mode = _mode()
    if mode == "off":
        return "ac_actions_off: lookup only is disabled too. Set AGENT_ACTIONS=propose or execute."

    looked = lookup_ac(query)
    if looked.startswith("ac_"):
        return looked

    mmi_present = "mmi_tag_present=true" in looked
    resend_id = _id("AC_MMI_RESEND_AUTOMATION_ID")
    start_id = _id("AC_MMI_AUTOMATION_ID")
    if mmi_present:
        plan = (
            f"PLAN: MMI tag is present. Resend the confirmation email "
            f"(automation {resend_id or 'NOT SET — add AC_MMI_RESEND_AUTOMATION_ID'})."
        )
        action = "resend"
        automation_id = resend_id
    else:
        plan = (
            f"PLAN: MMI tag is not present. Start the MMI confirmation automation "
            f"(automation {start_id or 'NOT SET — add AC_MMI_AUTOMATION_ID'})."
        )
        action = "start"
        automation_id = start_id

    if mode == "propose":
        return (
            f"{looked}\n{plan}\n"
            "MODE=propose: nothing was changed in ActiveCampaign. "
            "A person can do it, or set AGENT_ACTIONS=execute on Render after the automations are tested. "
            "Tell the customer we are checking / have asked the team to resend. Do not invent a ticket number."
        )

    contact_id = ""
    match = re.search(r"contact id=(\d+)", looked)
    if match:
        contact_id = match.group(1)
    if not contact_id or not automation_id:
        return (
            f"{looked}\n{plan}\n"
            "MODE=execute but the automation id is missing or the contact id was not parsed. "
            "A person must complete this in ActiveCampaign."
        )
    try:
        result = _start_automation(contact_id, automation_id)
    except RuntimeError as exc:
        return f"{looked}\n{plan}\nMODE=execute FAILED: {exc}. A person must finish this."
    return (
        f"{looked}\n{plan}\nMODE=execute OK: {action} — {result}. "
        "Tell the customer to check inbox, spam, junk and promotions. "
        "E-tickets still go out 3–5 days before the event unless this was a confirmation email."
    )
