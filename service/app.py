"""Zendesk webhook → Maya/Quinn/Rafa reply.

Only Maya posts to the customer. A finished answer is a public reply and
Solved. Her handoff is one holding reply, status Open, and an assignee.
Quinn and Rafa stay on the internal note, and that path still assigns.
Noise is Solved with no reply and no assignee. srv@ is skipped.
MMI goes to Meda, MMO (mmo@) goes to Alina.

The trigger body is not trusted. The ticket id is recovered from broken JSON,
then the ticket and comments are read from the API. A claim expires and is
released when the run finishes, so a later replay is not stuck on
"already processing".
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

import flow
import noise
from knowledge import draft_note, ensure_hub, hub_root, knowledge_status, route_agent

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from agents import forward, notewords, publictext, routing  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zendesk_ai")

app = FastAPI(title="SR Zendesk AI")

# One Claude run per ticket. Zendesk retries the webhook when Claude is slow.
# The claim expires so a crashed run cannot block the ticket for the life of
# the process, and it is released when the run finishes so it does not survive
# into the next webhook.
_claims = flow.ClaimBook(ttl_seconds=flow.DEFAULT_CLAIM_TTL_SECONDS)
_DEFAULT_TEST_EMAIL = "akram.r@srglobal.com"
_SRV_MAILBOX = "srv@srglobal.com"
_MMO_MAILBOX = "mmo@srglobal.com"
_MMI_ASSIGNEE = "meda.c@srglobal.com"
_MMO_ASSIGNEE = "alina.last@srglobal.com"
_MAILBOX = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
_HUMAN_REQUEST = re.compile(
    r"\b("
    r"(?:talk|speak|chat) (?:to|with) (?:a |an )?(?:real )?(?:human(?: being)?|person)"
    r"|answer from (?:a |an )?(?:real )?(?:human|person)"
    r"|(?:need|want) (?:a |an )?(?:real )?human"
    r"|human being"
    r")\b",
    re.I,
)
_QUOTE = re.compile(r"\n-{2,}\s*original message|\nOn .+wrote:|\nFrom:|\n>", re.I)


@app.on_event("startup")
def _load_knowledge() -> None:
    # Bundled copy first so Vercel cold starts stay under the time limit.
    ensure_hub(download=False)


def _backend() -> str:
    value = (os.getenv("AGENT_BACKEND") or "matcher").strip().lower()
    return value if value in {"matcher", "ollama", "claude"} else "matcher"


def _brain_label() -> str:
    if _backend() == "claude":
        return os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"
    if _backend() == "ollama":
        return os.getenv("OLLAMA_MODEL") or "llama3.1"
    return "matcher"


def _compose_generated_note(result) -> tuple[str, list[str], str]:
    """Staff note, extra tags, and a match label. The staff footer never goes to the customer."""
    if result.reason == "no_reply":
        return (
            "No customer reply. This is an automated notification or a webinar chat note. Leave the status unchanged.",
            ["ai_no_reply"],
            "no_reply",
        )
    extra: list[str] = []
    footer = (
        f"\n\n---\nStaff only — {result.agent.title()} wrote this with {_brain_label()}. "
        f"tools={','.join(result.tools_used) or 'none'}; "
        f"needs_human={str(result.needs_human).lower()}; {result.reason}"
    )
    if result.needs_human:
        extra.append("needs_human")
    if result.reason == "masterclass_handoff":
        extra.append("ai_broken_link")
    if result.reason == "internal_alert":
        extra.append("ai_internal_alert")
    if result.email.strip() and not result.needs_human:
        return result.email.strip() + footer, extra, "generated"
    if result.email.strip():
        return result.email.strip() + footer, extra, "generated_needs_human"
    body = (
        f"No sendable draft ({result.agent.title()}). {result.reason}. "
        "A person should reply. Do not invent a price or approve a repayment."
    )
    return body, extra, "none"


def _zendesk_subdomain() -> str:
    sub = (os.getenv("ZENDESK_SUBDOMAIN") or "").strip()
    sub = sub.replace("https://", "").replace("http://", "").rstrip("/")
    if sub.endswith(".zendesk.com"):
        sub = sub[: -len(".zendesk.com")]
    return sub


def _email_set(env_name: str, default: str) -> set[str]:
    raw = os.getenv(env_name)
    if raw is None:
        raw = default
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _public_solve_emails() -> set[str]:
    """Kept for /health. It no longer gates who receives a public reply."""
    return _email_set("ZENDESK_PUBLIC_SOLVE_EMAILS", _DEFAULT_TEST_EMAIL)


def _claim_ttl() -> float:
    raw = (os.getenv("MAYA_CLAIM_TTL_SECONDS") or "").strip()
    if not raw:
        return flow.DEFAULT_CLAIM_TTL_SECONDS
    try:
        return max(30.0, float(raw))
    except ValueError:
        return flow.DEFAULT_CLAIM_TTL_SECONDS


def _bot_email() -> str:
    return (os.getenv("ZENDESK_EMAIL") or "").strip().lower()


def _human_assignee_email() -> str:
    raw = os.getenv("ZENDESK_HUMAN_ASSIGNEE_EMAIL")
    if raw is None or not raw.strip():
        return _MMI_ASSIGNEE
    return raw.strip().lower()


def _one_email(env_name: str, default: str) -> str:
    raw = os.getenv(env_name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower()


def _mailbox_address(value: str) -> str:
    match = _MAILBOX.search(value or "")
    return match.group(0).lower() if match else ""


def maya_lane(recipient: str) -> str:
    """srv is ignored. mmo@ goes to the MMO lane. Everything else Maya handles is MMI."""
    box = _mailbox_address(recipient)
    if box == _SRV_MAILBOX:
        return "srv"
    if box == _MMO_MAILBOX:
        return "mmo"
    return "mmi"


def maya_human_assignee(lane: str) -> str:
    if lane == "mmo":
        return _one_email("ZENDESK_MMO_ASSIGNEE_EMAIL", _MMO_ASSIGNEE)
    return _one_email("ZENDESK_MMI_ASSIGNEE_EMAIL", _MMI_ASSIGNEE)


def asks_for_human(subject: str, description: str, *, full: bool = False) -> bool:
    """True when this message asks for a person."""
    if _HUMAN_REQUEST.search(subject or ""):
        return True
    raw = description or ""
    if not full:
        raw = _QUOTE.split(raw, maxsplit=1)[0]
        raw = re.sub(r"(?is)\n\s*sent to:.*$", "", raw)
    return bool(_HUMAN_REQUEST.search(raw[:8000]))


def _zendesk_configured() -> bool:
    return bool(
        _zendesk_subdomain()
        and (os.getenv("ZENDESK_EMAIL") or "").strip()
        and (os.getenv("ZENDESK_API_TOKEN") or "").strip()
    )


def _zendesk_auth_header() -> tuple[str, str] | None:
    subdomain = _zendesk_subdomain()
    email = (os.getenv("ZENDESK_EMAIL") or "").strip()
    token = (os.getenv("ZENDESK_API_TOKEN") or "").strip()
    if not (subdomain and email and token):
        return None
    pair = f"{email}/token:{token}".encode("ascii")
    return subdomain, "Basic " + base64.b64encode(pair).decode("ascii")


def _claim_ticket(ticket_id: str) -> bool:
    _claims.ttl = _claim_ttl()
    return _claims.claim(ticket_id)


def _release_ticket(ticket_id: str) -> None:
    _claims.release(ticket_id)


def _zendesk_get(path: str) -> dict | None:
    creds = _zendesk_auth_header()
    if not creds:
        return None
    subdomain, auth = creds
    req = UrlRequest(
        f"https://{subdomain}.zendesk.com/api/v2/{path}",
        method="GET",
        headers={"Authorization": auth, "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        log.exception("zendesk get failed path=%s", path)
        return None


def _flag_repeated_broken_link(ticket_id: str, assignee_email: str) -> None:
    """One internal ticket when several people report the same broken link within a few hours."""
    creds = _zendesk_auth_header()
    if not creds:
        return
    subdomain, auth = creds
    recent = _zendesk_get("search.json?query=" + quote("type:ticket tags:ai_broken_link"))
    alerts = _zendesk_get("search.json?query=" + quote("type:ticket tags:ai_broken_link_alert"))
    now = time.time()
    window = 6 * 3600

    def _recent(payload: dict | None) -> int:
        count = 0
        for row in (payload or {}).get("results") or []:
            stamp = str(row.get("updated_at") or "")
            try:
                when = time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue
            if now - when < window:
                count += 1
        return count

    if _recent(alerts):
        return
    if _recent(recent) < 3:
        return
    body = json.dumps(
        {
            "ticket": {
                "subject": "Broken Masterclass link reported by several customers",
                "comment": {
                    "public": False,
                    "body": (
                        "Several customers reported a broken Masterclass or webinar link "
                        f"in the last few hours. Latest ticket: {ticket_id}. "
                        "Send the working link or the replay, and do not point them at an MMI city page."
                    ),
                },
                "status": "open",
                "assignee_email": assignee_email,
                "tags": ["ai_broken_link_alert"],
            }
        }
    ).encode()
    req = UrlRequest(
        f"https://{subdomain}.zendesk.com/api/v2/tickets.json",
        data=body,
        method="POST",
        headers={
            "Authorization": auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            log.info("broken-link alert created http=%s from=%s", getattr(resp, "status", 201), ticket_id)
    except Exception:
        log.exception("broken-link alert failed from=%s", ticket_id)


def _comment_text(comment: dict) -> str:
    body = str(comment.get("body") or "").strip()
    if body:
        return body
    html = str(comment.get("html_body") or "")
    return re.sub(r"<[^>]+>", " ", html)


def _comments_ask_for_human(ticket_id: str) -> bool:
    """Any comment on the ticket, including a reply under the solved answer."""
    data = _zendesk_get(f"tickets/{ticket_id}/comments.json")
    if not data:
        return False
    for comment in data.get("comments") or []:
        if asks_for_human("", _comment_text(comment), full=True):
            return True
    return False


_open_custom_status_id: int | None = None
_open_custom_status_checked = False


def _default_open_custom_status_id() -> int | None:
    """Used when the account has custom ticket statuses and plain status=open does not stick."""
    global _open_custom_status_id, _open_custom_status_checked
    if _open_custom_status_checked:
        return _open_custom_status_id
    _open_custom_status_checked = True
    data = _zendesk_get("custom_statuses.json") or {}
    chosen = None
    for row in data.get("custom_statuses") or []:
        if str(row.get("status_category") or "") != "open" or row.get("active") is False:
            continue
        if row.get("default"):
            chosen = row.get("id")
            break
        chosen = chosen or row.get("id")
    if chosen:
        _open_custom_status_id = int(chosen)
    return _open_custom_status_id


def _already_open_for(ticket_id: str, assignee_email: str) -> bool:
    data = _zendesk_get(f"tickets/{ticket_id}.json")
    ticket = (data or {}).get("ticket") or {}
    if str(ticket.get("status") or "") != "open":
        return False
    assignee_id = ticket.get("assignee_id")
    if not assignee_id or not assignee_email:
        return False
    user = _zendesk_get(f"users/{assignee_id}.json")
    email = str(((user or {}).get("user") or {}).get("email") or "").strip().lower()
    return email == assignee_email.strip().lower()


def _ticket_status(ticket_id: str) -> str:
    data = _zendesk_get(f"tickets/{ticket_id}.json")
    return str(((data or {}).get("ticket") or {}).get("status") or "")


def fetch_ticket_recipient(ticket_id: str) -> str:
    data = _zendesk_get(f"tickets/{ticket_id}.json")
    return str(((data or {}).get("ticket") or {}).get("recipient") or "")


def skip_srv_ticket(ticket_id: str) -> None:
    """Leave SRV mail for the team. Maya does not reply or get assigned."""
    if "ai_skipped_srv" in set(fetch_ticket_tags(ticket_id)):
        log.info("srv already skipped ticket_id=%s", ticket_id)
        return
    ok, detail = _put_ticket(ticket_id, {"additional_tags": ["ai_skipped_srv"]})
    log.info("srv skipped ticket_id=%s ok=%s detail=%s", ticket_id, ok, detail)


def assign_open_for_human(
    ticket_id: str,
    hinted_comment: str = "",
    assignee_email: str | None = None,
    force: bool = False,
) -> bool:
    """Reopen and assign. No comment is added."""
    if not force and not asks_for_human("", hinted_comment, full=True) and not _comments_ask_for_human(ticket_id):
        log.info("human handoff no match ticket_id=%s hint_len=%s", ticket_id, len(hinted_comment or ""))
        return False
    assignee = (assignee_email or _human_assignee_email()).strip().lower()
    if assignee and _already_open_for(ticket_id, assignee):
        log.info("human handoff already open ticket_id=%s", ticket_id)
        return True
    fields: dict = {"status": "open", "additional_tags": ["ai_assigned_human"]}
    if assignee:
        fields["assignee_email"] = assignee
    ok, detail = _put_ticket(ticket_id, fields)
    status = _ticket_status(ticket_id) if ok else ""
    if status != "open":
        custom_id = _default_open_custom_status_id()
        if custom_id:
            fields["custom_status_id"] = custom_id
            fields["status"] = "open"
        if not ok and assignee:
            fields.pop("assignee_email", None)
            detail = f"{detail}; assignee {assignee} was not applied"
        time.sleep(2)
        ok, detail = _put_ticket(ticket_id, fields)
        status = _ticket_status(ticket_id)
    log.info(
        "human handoff ticket_id=%s ok=%s status=%s detail=%s",
        ticket_id,
        ok,
        status,
        detail,
    )
    return status == "open"


def fetch_requester_email(ticket_id: str) -> str:
    """Used when the webhook body has no requester email."""
    creds = _zendesk_auth_header()
    if not creds:
        return ""
    subdomain, auth = creds
    headers = {"Authorization": auth, "Accept": "application/json"}
    try:
        req = UrlRequest(
            f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json",
            method="GET",
            headers=headers,
        )
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        requester_id = (data.get("ticket") or {}).get("requester_id")
        if not requester_id:
            return ""
        user_req = UrlRequest(
            f"https://{subdomain}.zendesk.com/api/v2/users/{requester_id}.json",
            method="GET",
            headers=headers,
        )
        with urlopen(user_req, timeout=15) as resp:
            user = json.loads(resp.read().decode("utf-8"))
        return str((user.get("user") or {}).get("email") or "").strip()
    except Exception:
        log.exception("zendesk requester lookup failed ticket_id=%s", ticket_id)
        return ""


def fetch_ticket_tags(ticket_id: str) -> list[str]:
    creds = _zendesk_auth_header()
    if not creds:
        return []
    subdomain, auth = creds
    req = UrlRequest(
        f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json",
        method="GET",
        headers={"Authorization": auth, "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [str(t) for t in (data.get("ticket") or {}).get("tags") or []]
    except Exception:
        log.exception("zendesk tags fetch failed ticket_id=%s", ticket_id)
        return []


def _add_tags(ticket_id: str, tags: list[str]) -> tuple[bool, str]:
    """Add tags without replacing the existing ones (PUT /tickets/{id}/tags).

    The single-ticket update endpoint ignores additional_tags, which is why no
    ai_* tag was ever written before this.
    """
    tags = [str(tag) for tag in tags or [] if str(tag).strip()]
    if not tags:
        return True, "no tags"
    creds = _zendesk_auth_header()
    if not creds:
        return False, "missing Zendesk credentials"
    subdomain, auth = creds
    req = UrlRequest(
        f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}/tags.json",
        data=json.dumps({"tags": tags}).encode("utf-8"),
        method="PUT",
        headers={"Authorization": auth, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return True, f"tags {getattr(resp, 'status', 200)}"
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        log.error("zendesk add tags failed ticket_id=%s status=%s body=%s", ticket_id, exc.code, detail)
        return False, f"tags {exc.code}"
    except URLError as exc:
        log.error("zendesk add tags failed ticket_id=%s error=%s", ticket_id, exc)
        return False, "tags connection error"


def _put_ticket(ticket_id: str, ticket: dict) -> tuple[bool, str]:
    ticket = dict(ticket)
    extra_tags = list(ticket.pop("additional_tags", None) or [])
    if not ticket:
        return _add_tags(ticket_id, extra_tags)
    ok, detail = _put_ticket_raw(ticket_id, ticket)
    if ok and extra_tags:
        _add_tags(ticket_id, extra_tags)
    return ok, detail


def _put_ticket_raw(ticket_id: str, ticket: dict) -> tuple[bool, str]:
    creds = _zendesk_auth_header()
    if not creds:
        return False, "missing ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, or ZENDESK_API_TOKEN"

    subdomain, auth = creds
    url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    payload = json.dumps({"ticket": ticket}).encode("utf-8")
    req = UrlRequest(
        url,
        data=payload,
        method="PUT",
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            status = getattr(resp, "status", 200)
            log.info(
                "zendesk ticket updated ticket_id=%s http=%s public=%s status=%s assignee=%s",
                ticket_id,
                status,
                (ticket.get("comment") or {}).get("public"),
                ticket.get("status") or "",
                ticket.get("assignee_email") or "",
            )
            return True, f"zendesk {status}"
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        log.error("zendesk update failed ticket_id=%s status=%s body=%s", ticket_id, exc.code, detail)
        return False, f"zendesk {exc.code}: {detail}"
    except URLError as exc:
        log.error("zendesk update failed ticket_id=%s error=%s", ticket_id, exc)
        return False, "zendesk connection error"


def post_ticket_update(
    ticket_id: str,
    body: str,
    *,
    public: bool,
    extra_tags: list[str] | None = None,
    status: str | None = None,
    assignee_email: str | None = None,
    allow_solve: bool = False,
) -> tuple[bool, str]:
    # A customer-visible reply or Solved has to pass allow_solve.
    # Callers that omit it stay on a private note.
    if not allow_solve:
        public = False
        if status == "solved":
            status = None
    ticket: dict = {"comment": {"body": body, "public": public}}
    if extra_tags:
        ticket["additional_tags"] = extra_tags
    if status:
        ticket["status"] = status
    if assignee_email:
        ticket["assignee_email"] = assignee_email
    ok, detail = _put_ticket(ticket_id, ticket)
    if ok or not assignee_email:
        return ok, detail
    # A bad assignee must not block the note. Retry the same comment without it.
    log.error("zendesk assignee skipped ticket_id=%s assignee=%s", ticket_id, assignee_email)
    ticket.pop("assignee_email", None)
    ok, retry = _put_ticket(ticket_id, ticket)
    if ok:
        return True, f"{retry}; assignee {assignee_email} was not applied"
    return False, retry


def post_internal_note(ticket_id: str, body: str, extra_tags: list[str] | None = None) -> tuple[bool, str]:
    return post_ticket_update(ticket_id, body, public=False, extra_tags=extra_tags)


def solve_without_reply(ticket_id: str, extra_tags: list[str] | None = None) -> tuple[bool, str]:
    """Close as solved and do not add a comment."""
    ticket: dict = {"status": "solved"}
    if extra_tags:
        ticket["additional_tags"] = extra_tags
    return _put_ticket(ticket_id, ticket)


def _matcher_draft(tags: str, subject: str, description: str, extra: list[str]) -> flow.Draft:
    agent, matched, note_body = draft_note(str(tags), str(subject), flow.routing_text(str(description)))
    public = "" if matched == "none" else note_body
    needs = agent in {"rafa", "quinn"} or matched == "none" or flow.promises_handoff(public)
    reason = "Rafa drafts only. A person sends." if agent == "rafa" else "matcher"
    if matched == "none":
        reason = "no hub match"
    if matched and matched != "none":
        extra.append("ai_hub_match")
    return flow.Draft(
        agent=agent,
        matched=matched,
        extra_tags=extra,
        note_body=note_body,
        public_body=public,
        needs_human=needs,
        reason=reason,
    )


def _build_draft(
    tags: str,
    subject: str,
    description: str,
    requester_name: str,
    requester_email: str = "",
) -> flow.Draft:
    """Staff note plus the customer reply. The staff footer is not the public body."""
    if _backend() in {"ollama", "claude"}:
        try:
            from agents.loop import run_agent

            agent = route_agent(str(tags), str(subject), flow.routing_text(str(description)))
            result = run_agent(
                agent,
                str(subject),
                str(description),
                str(tags),
                str(requester_name),
                str(requester_email),
            )
            note_body, extra, matched = _compose_generated_note(result)
            return flow.Draft(
                agent=result.agent,
                matched=matched,
                extra_tags=extra,
                note_body=note_body,
                public_body=result.email.strip(),
                needs_human=bool(result.needs_human) or result.agent in {"rafa", "quinn"},
                reason=result.reason,
            )
        except Exception:
            log.exception("agent generate failed; falling back to GitHub matcher")
            return _matcher_draft(tags, subject, description, ["ai_matcher_fallback"])
    return _matcher_draft(tags, subject, description, [])


def _load_context(ticket_id: str) -> dict | None:
    """Ticket plus comments. None when the ticket itself cannot be read."""
    ticket_data = _zendesk_get(f"tickets/{ticket_id}.json")
    ticket = (ticket_data or {}).get("ticket")
    if not ticket:
        return None
    packed = _zendesk_get(f"tickets/{ticket_id}/comments.json?include=users")
    comments_ok = packed is not None
    users = {
        str(user.get("id")): user
        for user in (packed or {}).get("users") or []
        if user.get("id") is not None
    }
    requester_id = str(ticket.get("requester_id") or "")
    requester = users.get(requester_id) or {}
    if requester_id and not requester.get("email"):
        user_payload = _zendesk_get(f"users/{requester_id}.json") or {}
        requester = user_payload.get("user") or requester
        if requester.get("id") is not None:
            users[str(requester.get("id"))] = requester
    bot = _bot_email()
    if bot and not any(flow.author_is_bot(author_id, users, bot) for author_id in users):
        found = _zendesk_get("users/search.json?query=" + quote(f"email:{bot}"))
        for user in (found or {}).get("users") or []:
            if str(user.get("email") or "").strip().lower() == bot and user.get("id") is not None:
                users[str(user.get("id"))] = user
                break
    comments = [flow.comment_from_api(row) for row in (packed or {}).get("comments") or []]
    return {
        "subject": str(ticket.get("subject") or ""),
        "description": str(ticket.get("description") or ""),
        "tags": ticket.get("tags") or [],
        "recipient": str(ticket.get("recipient") or ""),
        "status": str(ticket.get("status") or ""),
        "created_at": str(ticket.get("created_at") or ""),
        "requester_id": requester_id,
        "requester_email": str(requester.get("email") or ""),
        "requester_name": str(requester.get("name") or ""),
        "comments_ok": comments_ok,
        "comments": comments,
        "users": users,
    }


OLD_TICKET_BRIEF = (
    "OLD TICKET: the customer wrote this on {created}, before 2026, and we are only answering now. "
    "Any event, date, offer or link it mentions may be over. Never quote a past event date, a 2025 date "
    "or a link from the customer's message or from memory. If the question is about a past event or is "
    "no longer relevant, say so briefly and mention only the upcoming events listed in the current facts; "
    "that is a finished answer. If a person still has to act (refund, payment, access, a booking), hand off.\n\n"
)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _long_wait_apology(hints: dict | None) -> bool:
    """Off unless asked for.

    The webhook body decides when it carries long_wait_apology (true or false): a
    catch-up run sends false for 2026 tickets and true for 2025 ones. Only when the
    body has no such field does LONG_WAIT_APOLOGY (env, default off) apply.
    """
    value = (hints or {}).get("long_wait_apology")
    if value is not None and str(value).strip() != "":
        return _truthy(value)
    return _truthy(os.getenv("LONG_WAIT_APOLOGY"))


def _created_before_2026(ctx: dict) -> bool:
    created = str((ctx or {}).get("created_at") or "")
    return bool(created) and created[:4].isdigit() and int(created[:4]) < 2026


def _current_facts() -> str:
    """Maya's current-facts page, the only source of dates and links for an old ticket."""
    try:
        root = hub_root()
        return (root / "00-current-facts" / "maya.md").read_text(encoding="utf-8")
    except Exception:
        log.exception("current facts unavailable")
        return ""


def _tag_text(tags) -> str:
    if isinstance(tags, list):
        return " ".join(str(tag) for tag in tags)
    return str(tags or "")


def _message_from_context(ctx: dict, hints: dict) -> tuple[str, str, str, str, str]:
    """subject, description, tags, requester name, requester email."""
    subject = str(ctx.get("subject") or hints.get("subject") or "")
    tags = _tag_text(ctx.get("tags") or hints.get("tags") or "")
    name = str(ctx.get("requester_name") or hints.get("requester_name") or "")
    email = str(ctx.get("requester_email") or hints.get("requester_email") or "")
    comments = ctx.get("comments") or []
    requester_id = str(ctx.get("requester_id") or "")
    conversation = flow.render_conversation(comments, requester_id) if ctx.get("comments_ok") else ""
    if conversation:
        description = (
            "Full public conversation. Answer the latest customer message. "
            "Do not answer a Staff message. "
            "Do not say you have passed this to the team unless a person has to do something you cannot do.\n\n"
            + conversation
        )
    else:
        description = str(ctx.get("description") or hints.get("description") or "")
    return subject, description, tags, name, email


def _customer_text(ctx: dict, hints: dict, subject: str) -> str:
    comments = ctx.get("comments") or []
    latest = flow.latest_customer_text(comments, str(ctx.get("requester_id") or ""))
    if latest:
        return latest
    return str(ctx.get("description") or hints.get("description") or subject or "")


def _customer_bodies(ctx: dict) -> list[str]:
    requester_id = str(ctx.get("requester_id") or "")
    bodies = [
        comment.body
        for comment in flow.sorted_comments(ctx.get("comments") or [])
        if comment.public and str(comment.author_id) == requester_id
    ]
    if not bodies and ctx.get("description"):
        bodies = [str(ctx.get("description"))]
    return bodies


def _greeting_for(ctx: dict, name: str) -> tuple[str, str]:
    """Greeting with the customer's real first name, and the name for the note."""
    bodies = _customer_bodies(ctx)
    greet = publictext.greeting(name, bodies)
    first = publictext.first_name(name, bodies)
    who = name.strip() if publictext.first_name(name) else (first or name.strip())
    return greet, who


def _person(ctx: dict, name: str, email: str, fallback: str) -> dict:
    """Greeting and note facts. The note keeps every customer turn, not only the latest."""
    greet, who = _greeting_for(ctx, name)
    turns = [flow.above_quote(body) for body in _customer_bodies(ctx)[-3:]]
    turns = [turn for turn in turns if turn]
    text = " / ".join(turns) if turns else fallback
    return dict(greeting=greet, customer_text=text, customer_name=who, customer_email=email)


def _forward_note(ctx: dict, hints: dict, subject: str, staff_email: str, assignee: str, lane: str, customer_text: str) -> str:
    """Keep the forwarded original in full: customer, email, every question, KB suggestions."""
    candidates = [*_customer_bodies(ctx), str(ctx.get("description") or hints.get("description") or "")]
    for raw in candidates:
        parsed = forward.parse(raw)
        if parsed and (parsed.body or parsed.sender_email):
            return forward.note(parsed, staff_email=staff_email, subject=subject, assignee=assignee, lane=lane)
    # No forward block: keep the whole staff message, never cut at "From:".
    raw = (customer_text or candidates[-1] or "").strip()
    qs = forward.questions(raw)
    lines = [
        f"Internal message from {staff_email}. No public reply was sent.",
        f"Subject: {subject}",
    ]
    if qs:
        lines.append("Questions, with a suggested answer from the KB (internal only):")
        for n, question in enumerate(qs, 1):
            lines.append(f"{n}. {question}\n   Suggested: {notewords.scrub(forward.suggest(question))}")
    lines.append("Needed: answer the original customer, not the staff sender.")
    lines.append("\nFull message:\n" + raw[:6000])
    return "\n".join(lines)


def _ensure_open(ticket_id: str, assignee: str) -> None:
    if _ticket_status(ticket_id) == "open":
        return
    custom_id = _default_open_custom_status_id()
    fields: dict = {"status": "open"}
    if assignee:
        fields["assignee_email"] = assignee
    if custom_id:
        fields["custom_status_id"] = custom_id
    _put_ticket(ticket_id, fields)


def _pack(
    disposition: flow.Disposition,
    *,
    posted: bool,
    assigned: bool,
    detail: str = "",
    reply: str | None = None,
) -> dict:
    # Dry-run uses _plan. Here, name the assignee only when the assign stuck.
    assignee = disposition.assignee_email if disposition.action == "handoff" and assigned else ""
    return {
        "action": disposition.action,
        "agent": disposition.agent,
        "reason": disposition.reason,
        "reply": disposition.public_body if reply is None else reply,
        "assignee": assignee,
        "lane": disposition.lane,
        "tags": list(disposition.tags),
        "posted": posted,
        "assigned": assigned,
        "detail": detail,
    }


def _apply_handoff(ticket_id: str, disposition: flow.Disposition) -> dict:
    """Public holding reply only claims a handoff when the assignee sticks."""
    assignee = disposition.assignee_email
    public = (disposition.public_body or "").strip()
    tags = list(disposition.tags)
    note = disposition.internal_note or ""

    def _note(extra: list[str] | None = None) -> None:
        if note:
            post_internal_note(ticket_id, note, [*(extra or []), "ai_handoff_note"])
        elif extra:
            _add_tags(ticket_id, extra)

    if not public:
        assigned = assign_open_for_human(ticket_id, "", assignee, force=True) if assignee else False
        # Internal-only lanes (Quinn, Rafa, business, forwards): the lane tags (ai_quinn, ai_rafa,
        # ai_no_public_reply, ai_draft_only, ai_generated, ...) ride on the note's tag write.
        _note(tags)
        return _pack(
            disposition,
            posted=bool(note),
            assigned=assigned,
            reply="",
            detail="assigned" if assigned else "assign failed",
        )

    ticket: dict = {
        "comment": {"body": public, "public": True},
        "status": "open",
        "additional_tags": tags,
    }
    if assignee:
        ticket["assignee_email"] = assignee
    ok, detail = _put_ticket(ticket_id, ticket)
    if ok:
        _ensure_open(ticket_id, assignee)
        _note()
        if "ai_broken_link" in tags and assignee:
            _flag_repeated_broken_link(ticket_id, assignee)
        return _pack(disposition, posted=True, assigned=bool(assignee), reply=public, detail=detail)

    assigned = assign_open_for_human(ticket_id, "", assignee, force=True) if assignee else False
    if assigned:
        ok2, detail2 = post_ticket_update(
            ticket_id,
            public,
            public=True,
            status="open",
            allow_solve=True,
            extra_tags=tags,
        )
        _note()
        return _pack(
            disposition,
            posted=ok2,
            assigned=True,
            reply=public if ok2 else "",
            detail=detail2,
        )

    safe = public if not disposition.claims_handoff else flow.public_text_for_handoff(public, assigned=False)
    reply = ""
    posted = False
    if safe:
        safe_tags = [tag for tag in tags if tag != flow.TAG_ASSIGNED]
        ok3, detail = post_ticket_update(
            ticket_id,
            safe,
            public=True,
            status="open",
            allow_solve=True,
            extra_tags=safe_tags,
        )
        posted = ok3
        reply = safe if ok3 else ""
    _note()
    return _pack(disposition, posted=posted or bool(note), assigned=False, reply=reply, detail=detail)


def _apply_disposition(ticket_id: str, disposition: flow.Disposition) -> dict:
    action = disposition.action
    if action == "skip_srv":
        skip_srv_ticket(ticket_id)
        return _pack(disposition, posted=True, assigned=False, reply="", detail="srv skipped")
    if action == "solve_silent":
        ok, detail = solve_without_reply(ticket_id, disposition.tags)
        return _pack(disposition, posted=ok, assigned=False, reply="", detail=detail)
    if action == "solve":
        ok, detail = post_ticket_update(
            ticket_id,
            disposition.public_body,
            public=True,
            status="solved",
            allow_solve=True,
            extra_tags=disposition.tags,
        )
        if ok:
            return _pack(disposition, posted=True, assigned=False, reply=disposition.public_body, detail=detail)
        log.error("public solve failed ticket_id=%s detail=%s", ticket_id, detail)
        fallback = flow.Disposition(
            action="handoff",
            agent=disposition.agent or "maya",
            reason="public solve failed",
            public_body=disposition.public_body,
            internal_note="Public solve failed. Left open for the team.\n\n" + disposition.public_body,
            status="open",
            assignee_email=disposition.assignee_email or maya_human_assignee(disposition.lane or "mmi"),
            tags=["ai_assigned_human", "ai_generated", f"ai_{disposition.agent or 'maya'}", "ai_public_reply"],
            lane=disposition.lane,
            claims_handoff=flow.promises_handoff(disposition.public_body),
        )
        failed = _apply_handoff(ticket_id, fallback)
        failed["reason"] = "public solve failed"
        return failed
    if action == "handoff":
        return _apply_handoff(ticket_id, disposition)
    if action == "internal_draft":
        # Legacy path. Still assign, and do not post the draft publicly.
        assignee = disposition.assignee_email or maya_human_assignee(disposition.lane or "mmi")
        assigned = assign_open_for_human(ticket_id, "", assignee, force=True) if assignee else False
        ok, detail = post_internal_note(
            ticket_id,
            disposition.internal_note or "No sendable draft. A person should reply.",
            disposition.tags,
        )
        packed = _pack(disposition, posted=ok, assigned=assigned, reply="", detail=detail)
        packed["assignee"] = assignee if assigned else ""
        return packed
    return _pack(disposition, posted=False, assigned=False, detail="nothing to do")


def _plan(disposition: flow.Disposition) -> dict:
    return {
        "action": disposition.action,
        "agent": disposition.agent,
        "reason": disposition.reason,
        "reply": disposition.public_body,
        "internal_note": disposition.internal_note,
        "assignee": disposition.assignee_email if disposition.action == "handoff" else "",
        "lane": disposition.lane,
        "tags": list(disposition.tags),
        "posted": False,
        "assigned": False,
        "detail": "dry-run",
    }


def _skip(reason: str, *, lane: str = "", agent: str = "") -> dict:
    return {
        "action": "skip",
        "agent": agent,
        "reason": reason,
        "reply": "",
        "assignee": "",
        "lane": lane,
        "tags": [],
        "posted": False,
        "assigned": False,
        "detail": reason,
    }


def _webhook_skip(ctx: dict, bot_email: str) -> str | None:
    if not ctx.get("comments_ok"):
        return "comments unavailable"
    requester_id = str(ctx.get("requester_id") or "")
    comments = ctx.get("comments") or []
    if not requester_id:
        return "requester unknown"
    if not comments:
        return None
    reason = flow.skip_reason_for_latest(comments, requester_id)
    if reason:
        return reason
    return None


def _maybe_refresh(ticket_id: str, ctx: dict, loader, backfill: bool, live: bool, bot_email: str):
    """Return (ctx, skip_reason). Reloads before acting. None loader result keeps ctx."""
    if loader is None:
        return ctx, None
    fresh = loader(ticket_id)
    if not fresh:
        if backfill and live:
            return ctx, "recheck failed"
        return ctx, None
    if backfill:
        lane = maya_lane(str(fresh.get("recipient") or ctx.get("recipient") or ""))
        reason = flow.backfill_skip_reason(
            str(fresh.get("status") or ""),
            lane,
            fresh.get("comments") or [],
            str(fresh.get("requester_id") or ""),
            comments_ok=bool(fresh.get("comments_ok")),
        )
        if reason:
            return fresh, "recheck: " + reason
        return fresh, None
    if live:
        reason = _webhook_skip(fresh, bot_email)
        if reason:
            return fresh, reason
    return fresh, None


def _process_ticket(
    ticket_id: str,
    hints: dict | None = None,
    *,
    live: bool = True,
    backfill: bool = False,
    loader=None,
    drafter=None,
    poster=None,
    bot_email: str | None = None,
) -> dict:
    """Run Maya's answer flow for one ticket. Dry-run posts nothing."""
    hints = hints or {}
    loader = loader or _load_context
    drafter = drafter or _build_draft
    poster = poster or _apply_disposition
    bot = _bot_email() if bot_email is None else bot_email
    ctx = loader(ticket_id)
    if not ctx:
        return _skip("ticket unavailable")
    recipient = str(ctx.get("recipient") or hints.get("recipient") or "")
    lane = maya_lane(recipient)
    if lane == "srv":
        disposition = flow.decide(
            agent="maya",
            lane="srv",
            needs_human=False,
            matched="",
            public_body="",
            note_body="",
            assignee_email="",
        )
        if live:
            return poster(ticket_id, disposition)
        return _plan(disposition)

    if backfill:
        reason = flow.backfill_skip_reason(
            str(ctx.get("status") or ""),
            lane,
            ctx.get("comments") or [],
            str(ctx.get("requester_id") or ""),
            comments_ok=bool(ctx.get("comments_ok")),
        )
        if reason:
            return _skip(reason, lane=lane)
    else:
        reason = _webhook_skip(ctx, bot)
        if reason:
            return _skip(reason, lane=lane)

    subject, description, tags, name, email = _message_from_context(ctx, hints)
    customer_text = _customer_text(ctx, hints, subject)
    plain = flow.routing_text(customer_text or description)
    assignee = maya_human_assignee(lane)
    noise_tag = noise.classify(
        sender=email,
        name=name,
        subject=subject,
        text=plain,
        tags=tags,
    )
    if noise_tag == "noise_vendor" and routing.business_enquiry(plain, subject):
        # Quotes, sponsorship, partnership and supplier offers go to Meda as a note, not a silent close.
        noise_tag = None
    if noise_tag:
        disposition = flow.decide(
            agent="maya",
            lane=lane,
            needs_human=False,
            matched="no_reply",
            public_body="",
            note_body="",
            assignee_email="",
            reason=noise_tag,
            noise_tag=noise_tag,
        )
        if live:
            return poster(ticket_id, disposition)
        return _plan(disposition)
    if email.lower().endswith("@srglobal.com"):
        disposition = flow.decide(
            agent="maya",
            lane=lane,
            needs_human=True,
            matched="forward",
            public_body="",
            note_body=_forward_note(ctx, hints, subject, email, assignee, lane, customer_text),
            assignee_email=assignee,
            reason="internal_forward",
            forward=True,
        )
        if live:
            return poster(ticket_id, disposition)
        return _plan(disposition)
    person = _person(ctx, name, email, plain or customer_text)
    vendor = routing.vendor_sender(email, name, subject, plain)
    if vendor:
        # Hyros, Digistore24 and other platforms are not customers. No draft (it would be a
        # customer reply), no public text: an internal note for Meda, status open.
        disposition = flow.decide(
            agent="maya",
            lane=lane,
            needs_human=True,
            matched="vendor",
            public_body="",
            note_body="",
            assignee_email=assignee,
            reason=f"vendor or platform sender ({vendor})",
            subject=subject,
            tags=tags,
            vendor=vendor,
            **person,
        )
        log.info("answer ticket_id=%s lane=%s action=%s vendor=%s live=%s", ticket_id, lane, disposition.action, vendor, live)
        if not live:
            return _plan(disposition)
        return poster(ticket_id, disposition)
    old_ticket = _created_before_2026(ctx)
    if old_ticket:
        base_drafter = drafter

        def drafter(**kw):  # noqa: F811 - same drafter, with the old-ticket brief first
            kw["description"] = OLD_TICKET_BRIEF.format(created=str(ctx.get("created_at") or "")[:10]) + str(
                kw.get("description") or ""
            )
            return base_drafter(**kw)

    if asks_for_human(subject, customer_text):
        disposition = flow.human_request_disposition(lane, assignee, **person)
    else:
        first_customer = flow.latest_customer_comment(ctx.get("comments") or [], str(ctx.get("requester_id") or ""))
        draft = drafter(
            tags=tags,
            subject=subject,
            description=description,
            requester_name=name,
            requester_email=email,
        )
        ctx, refresh_reason = _maybe_refresh(ticket_id, ctx, loader, backfill, live, bot)
        if refresh_reason:
            return _skip(refresh_reason, lane=lane)
        latest = flow.latest_customer_comment(ctx.get("comments") or [], str(ctx.get("requester_id") or ""))
        if (
            latest
            and first_customer
            and latest.id
            and latest.id != first_customer.id
            and not asks_for_human(subject, latest.body)
        ):
            subject, description, tags, name, email = _message_from_context(ctx, hints)
            person = _person(ctx, name, email, flow.routing_text(latest.body))
            draft = drafter(
                tags=tags,
                subject=subject,
                description=description,
                requester_name=name,
                requester_email=email,
            )
        elif latest and asks_for_human(subject, latest.body):
            disposition = flow.human_request_disposition(lane, assignee, **person)
            log.info(
                "answer ticket_id=%s lane=%s action=%s agent=%s live=%s",
                ticket_id,
                lane,
                disposition.action,
                disposition.agent,
                live,
            )
            if not live:
                return _plan(disposition)
            return poster(ticket_id, disposition)
        disposition = flow.decide(
            agent=draft.agent,
            lane=lane,
            needs_human=draft.needs_human,
            matched=draft.matched,
            public_body=draft.public_body,
            note_body=draft.note_body,
            assignee_email=assignee,
            reason=draft.reason,
            subject=subject,
            tags=tags,
            stale_facts=_current_facts() if old_ticket else None,
            **person,
        )
        disposition = flow.merge_tags(disposition, draft.extra_tags)
    if disposition.public_body and _long_wait_apology(hints):
        disposition.public_body = publictext.with_long_wait_apology(disposition.public_body)
        disposition.tags = [*disposition.tags, "ai_long_wait_apology"]
    log.info(
        "answer ticket_id=%s lane=%s action=%s agent=%s live=%s reason=%s",
        ticket_id,
        lane,
        disposition.action,
        disposition.agent,
        live,
        disposition.reason,
    )
    if not live:
        return _plan(disposition)
    return poster(ticket_id, disposition)


def _run_webhook(ticket_id: str, hints: dict | None = None) -> None:
    try:
        outcome = _process_ticket(ticket_id, hints, live=True, backfill=False)
        log.info(
            "webhook done ticket_id=%s action=%s posted=%s assigned=%s detail=%s",
            ticket_id,
            outcome.get("action"),
            outcome.get("posted"),
            outcome.get("assigned"),
            outcome.get("detail"),
        )
    except Exception:
        log.exception("webhook crashed ticket_id=%s", ticket_id)
    finally:
        _release_ticket(ticket_id)


@app.get("/")
def root() -> dict:
    return {
        "ok": True,
        "phase": 1 if _backend() == "matcher" else 2,
        "agent_backend": _backend(),
        "health": "/health",
        "webhook": "/zendesk/webhook",
        "zendesk_configured": _zendesk_configured(),
    }


def _event_sheet_codes() -> list[str]:
    try:
        from agents.tools import registrations

        return [event["code"] for event in registrations.configured_events()]
    except Exception:
        return []


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "phase": 1 if _backend() == "matcher" else 2,
        "agent_backend": _backend(),
        "ollama_model": os.getenv("OLLAMA_MODEL") or "llama3.1",
        "anthropic_model": os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5",
        "claude_key_set": bool((os.getenv("ANTHROPIC_API_KEY") or "").strip()),
        "claude_workspace_set": bool((os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip()),
        "zendesk_configured": _zendesk_configured(),
        "ac_configured": bool(
            (os.getenv("ACTIVECAMPAIGN_URL") or os.getenv("AC_API_URL") or "").strip()
            and (os.getenv("ACTIVECAMPAIGN_API_TOKEN") or os.getenv("AC_API_TOKEN") or "").strip()
        ),
        "agent_actions": (os.getenv("AGENT_ACTIONS") or "propose").strip().lower(),
        "maya_live": True,
        "public_reply_scope": "confident answers are public for every requester",
        "public_solve_emails": sorted(_public_solve_emails()),
        "claim_ttl_seconds": _claim_ttl(),
        "mmi_assignee_email": maya_human_assignee("mmi"),
        "mmo_assignee_email": maya_human_assignee("mmo"),
        "mmi_event_sheets": _event_sheet_codes(),
        **knowledge_status(),
    }


def _hints_from_body(body: dict) -> dict:
    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    tags = body.get("tags") or ticket.get("tags") or ""
    if isinstance(tags, list):
        tags = " ".join(str(tag) for tag in tags)
    return {
        "subject": body.get("subject") or ticket.get("subject") or "",
        "description": body.get("description") or ticket.get("description") or "",
        "requester_name": body.get("requester_name") or (ticket.get("requester") or {}).get("name") or "",
        "requester_email": (
            body.get("requester_email")
            or (ticket.get("requester") or {}).get("email")
            or body.get("email")
            or ""
        ),
        "tags": tags,
        "recipient": body.get("recipient") or ticket.get("recipient") or "",
        # None when the body has no field, so the env default (off) applies; an explicit false wins.
        "long_wait_apology": _truthy(body["long_wait_apology"]) if body.get("long_wait_apology") not in (None, "") else None,
    }


@app.post("/zendesk/webhook")
async def zendesk_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    raw = await request.body()
    body = flow.parse_webhook_payload(raw)
    ticket_id = flow.webhook_ticket_id(body)
    hints = _hints_from_body(body)
    log.info(
        "webhook received ticket_id=%s subject=%s partial=%s",
        ticket_id,
        hints.get("subject"),
        bool(body.get("_partial")),
    )

    if not ticket_id:
        return JSONResponse(
            {
                "received": True,
                "ticket_id": None,
                "skipped": "no ticket id in payload",
                "note_posted": False,
            }
        )

    if not _claim_ticket(ticket_id):
        log.info("skip webhook duplicate in-flight ticket_id=%s", ticket_id)
        return JSONResponse(
            {
                "received": True,
                "ticket_id": ticket_id,
                "skipped": "already processing",
                "note_posted": False,
            }
        )

    # Ack Zendesk immediately. The run reads the ticket and comments itself,
    # so a broken trigger body is enough as long as it contains the ticket id.
    background_tasks.add_task(_run_webhook, ticket_id, hints)
    return JSONResponse(
        {
            "received": True,
            "accepted": True,
            "ticket_id": ticket_id,
            "backend": _backend(),
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
