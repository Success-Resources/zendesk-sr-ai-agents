"""Zendesk webhook → Maya/Quinn/Rafa draft → private note, or a public solved reply in test.

AGENT_BACKEND=matcher  copy closest GitHub email (Vercel Hobby)
AGENT_BACKEND=claude   generate with Claude API + hub/site/sheet tools (remote)
AGENT_BACKEND=ollama   local laptop test only

Test stage: requesters in ZENDESK_PUBLIC_SOLVE_EMAILS get a public reply and status solved.
Anyone who asks to speak to a person is assigned to ZENDESK_HUMAN_ASSIGNEE_EMAIL instead.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from knowledge import draft_note, ensure_hub, knowledge_status, route_agent

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zendesk_ai")

app = FastAPI(title="SR Zendesk AI")

# One Claude run per ticket. Zendesk retries the webhook when Claude is slow;
# without this lock each retry bills again and posts another note.
_draft_lock = threading.Lock()
_claimed_tickets: set[str] = set()
_AI_DRAFT_TAGS = frozenset(
    {"ai_draft_only", "ai_generated", "ai_matcher_fallback", "ai_assigned_human"}
)
_DEFAULT_TEST_EMAIL = "akram.r@srglobal.com"
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
    extra = ["ai_draft_only", f"ai_{result.agent}", "ai_generated"]
    footer = (
        f"\n\n---\nStaff only — {result.agent.title()} wrote this with {_brain_label()}. "
        f"tools={','.join(result.tools_used) or 'none'}; "
        f"needs_human={str(result.needs_human).lower()}; {result.reason}"
    )
    if result.needs_human:
        extra.append("needs_human")
    if result.email.strip() and not result.needs_human:
        extra.append("ai_sendable")
        return result.email.strip() + footer, extra, "generated"
    if result.email.strip():
        return result.email.strip() + footer, extra, "generated_needs_human"
    body = (
        f"No sendable draft ({result.agent.title()}). {result.reason}. "
        "A person should reply. Do not invent a price or approve a refund."
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
    """Requesters who receive a public reply and Solved. Empty env disables it."""
    return _email_set("ZENDESK_PUBLIC_SOLVE_EMAILS", _DEFAULT_TEST_EMAIL)


def _human_assignee_email() -> str:
    raw = os.getenv("ZENDESK_HUMAN_ASSIGNEE_EMAIL")
    if raw is None:
        return _DEFAULT_TEST_EMAIL
    return raw.strip().lower()


def asks_for_human(subject: str, description: str) -> bool:
    """True when this message asks for a person, not a quoted earlier email."""
    if _HUMAN_REQUEST.search(subject or ""):
        return True
    body = _QUOTE.split(description or "", maxsplit=1)[0]
    body = re.sub(r"(?is)\n\s*sent to:.*$", "", body)
    return bool(_HUMAN_REQUEST.search(body[:2000]))


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


def _ticket_id(body: dict) -> str | None:
    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    raw = body.get("id") or body.get("ticket_id") or ticket.get("id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _tag_set(tags) -> set[str]:
    if isinstance(tags, list):
        parts = tags
    else:
        parts = str(tags or "").replace(",", " ").split()
    return {str(p).strip().lower() for p in parts if str(p).strip()}


def _already_drafted(tags) -> bool:
    return bool(_tag_set(tags) & _AI_DRAFT_TAGS)


def _claim_ticket(ticket_id: str) -> bool:
    with _draft_lock:
        if ticket_id in _claimed_tickets:
            return False
        _claimed_tickets.add(ticket_id)
        return True


def _release_ticket(ticket_id: str) -> None:
    with _draft_lock:
        _claimed_tickets.discard(ticket_id)


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


def _comment_text(comment: dict) -> str:
    body = str(comment.get("body") or "").strip()
    if body:
        return body
    html = str(comment.get("html_body") or "")
    return re.sub(r"<[^>]+>", " ", html)


def fetch_latest_public_comment(ticket_id: str) -> str:
    """The newest public comment. Zendesk returns comments oldest-first."""
    data = _zendesk_get(f"tickets/{ticket_id}/comments.json")
    if not data:
        return ""
    public = [
        comment
        for comment in data.get("comments") or []
        if comment.get("public", True)
    ]
    if not public:
        return ""
    public.sort(key=lambda comment: str(comment.get("created_at") or ""))
    return _comment_text(public[-1])


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


def assign_open_for_human(ticket_id: str, hinted_comment: str = "") -> bool:
    """Reopen and assign when the requester asks for a person. No comment is added."""
    latest = fetch_latest_public_comment(ticket_id)
    if not asks_for_human("", latest) and not asks_for_human("", hinted_comment):
        log.info(
            "human handoff no match ticket_id=%s latest_len=%s hint_len=%s",
            ticket_id,
            len(latest),
            len(hinted_comment or ""),
        )
        return False
    assignee = _human_assignee_email()
    if assignee and _already_open_for(ticket_id, assignee):
        log.info("human handoff already open ticket_id=%s", ticket_id)
        return True
    fields: dict = {"status": "open", "additional_tags": ["ai_assigned_human"]}
    if assignee:
        fields["assignee_email"] = assignee
    ok, detail = _put_ticket(ticket_id, fields)
    if not ok and assignee:
        fields.pop("assignee_email", None)
        ok, detail = _put_ticket(ticket_id, fields)
        detail = f"{detail}; assignee {assignee} was not applied"
    # The inbound reply can land after this update and leave the ticket solved.
    if ok and _ticket_status(ticket_id) != "open":
        time.sleep(2)
        ok, detail = _put_ticket(ticket_id, fields)
    log.info(
        "human handoff ticket_id=%s ok=%s status=%s detail=%s",
        ticket_id,
        ok,
        _ticket_status(ticket_id),
        detail,
    )
    return True


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


def _put_ticket(ticket_id: str, ticket: dict) -> tuple[bool, str]:
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
) -> tuple[bool, str]:
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


def _build_draft(
    tags: str,
    subject: str,
    description: str,
    requester_name: str,
    requester_email: str = "",
) -> tuple[str, str, list[str], str, str]:
    """Returns agent, matched, tags, private note, and the customer reply with no staff footer."""
    extra: list[str] = []
    if _backend() in {"ollama", "claude"}:
        try:
            from agents.loop import run_agent

            agent = route_agent(str(tags), str(subject), str(description))
            result = run_agent(
                agent,
                str(subject),
                str(description),
                str(tags),
                str(requester_name),
                str(requester_email),
            )
            note_body, extra, matched = _compose_generated_note(result)
            return agent, matched, extra, note_body, result.email.strip()
        except Exception:
            log.exception("agent generate failed; falling back to GitHub matcher")
            agent, matched, note_body = draft_note(str(tags), str(subject), str(description))
            extra = ["ai_draft_only", f"ai_{agent}", "ai_matcher_fallback"]
            if matched and matched != "none":
                extra.append("ai_hub_match")
            return agent, matched, extra, note_body, ""
    agent, matched, note_body = draft_note(str(tags), str(subject), str(description))
    extra = ["ai_draft_only", f"ai_{agent}"]
    if matched and matched != "none":
        extra.append("ai_hub_match")
    return agent, matched, extra, note_body, ""


def _draft_and_post(
    ticket_id: str,
    subject: str,
    description: str,
    tags: str,
    requester_name: str,
    requester_email: str = "",
    latest_comment: str = "",
) -> None:
    try:
        if assign_open_for_human(ticket_id, latest_comment):
            log.info("human handoff only ticket_id=%s", ticket_id)
            _release_ticket(ticket_id)
            return
        live_tags = fetch_ticket_tags(ticket_id)
        if _already_drafted(tags) or _already_drafted(live_tags):
            log.info("skip already drafted ticket_id=%s", ticket_id)
            return
        if not requester_email.strip():
            requester_email = fetch_requester_email(ticket_id)
        agent, matched, extra, note_body, public_body = _build_draft(
            tags, subject, description, requester_name, requester_email
        )
        requester = requester_email.strip().lower()
        disposition = "private_note"
        if (
            requester in _public_solve_emails()
            and public_body
            and matched.startswith("generated")
        ):
            posted, error = post_ticket_update(
                ticket_id,
                public_body,
                public=True,
                status="solved",
                extra_tags=["ai_generated", f"ai_{agent}", "ai_public_reply", "ai_solved"],
            )
            disposition = "public_solved"
            if not posted:
                posted, error = post_internal_note(ticket_id, note_body, extra)
                disposition = "public_solve_failed_private_note"
        else:
            posted, error = post_internal_note(ticket_id, note_body, extra)
        log.info(
            "draft backend=%s agent=%s matched=%s ticket_id=%s disposition=%s posted=%s error=%s",
            _backend(),
            agent,
            matched,
            ticket_id,
            disposition,
            posted,
            error,
        )
        if not posted:
            _release_ticket(ticket_id)
    except Exception:
        log.exception("zendesk note crashed ticket_id=%s", ticket_id)
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
        "public_solve_emails": sorted(_public_solve_emails()),
        "human_assignee_email": _human_assignee_email(),
        "mmi_event_sheets": _event_sheet_codes(),
        **knowledge_status(),
    }


@app.post("/zendesk/webhook")
async def zendesk_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}

    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    ticket_id = _ticket_id(body)
    subject = body.get("subject") or ticket.get("subject") or ""
    description = body.get("description") or ticket.get("description") or ""
    requester_name = (
        body.get("requester_name")
        or (ticket.get("requester") or {}).get("name")
        or ""
    )
    requester_email = (
        body.get("requester_email")
        or (ticket.get("requester") or {}).get("email")
        or body.get("email")
        or ""
    )
    tags = body.get("tags") or ticket.get("tags") or ""
    if isinstance(tags, list):
        tags = " ".join(str(t) for t in tags)
    latest_comment = str(
        body.get("latest_comment") or body.get("comment") or ticket.get("latest_comment") or ""
    )

    log.info("webhook received ticket_id=%s subject=%s", ticket_id, subject)

    if not ticket_id:
        return JSONResponse(
            {
                "received": True,
                "ticket_id": None,
                "skipped": "no ticket id in payload",
                "note_posted": False,
            }
        )

    # A reply on a ticket we already answered must still be able to reopen it.
    # Also catch the human request from the webhook body before another solve.
    if _already_drafted(tags) or asks_for_human("", latest_comment):
        log.info("webhook follow-up ticket_id=%s", ticket_id)
        background_tasks.add_task(assign_open_for_human, ticket_id, latest_comment)
        return JSONResponse(
            {
                "received": True,
                "accepted": True,
                "ticket_id": ticket_id,
                "handoff_check": True,
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

    # Ack Zendesk immediately so it does not retry while Claude is still running.
    background_tasks.add_task(
        _draft_and_post,
        ticket_id,
        str(subject),
        str(description),
        str(tags),
        str(requester_name),
        str(requester_email),
        latest_comment,
    )
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
