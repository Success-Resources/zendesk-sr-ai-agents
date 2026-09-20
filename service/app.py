"""Zendesk webhook → Maya/Quinn/Rafa draft → private note.

AGENT_BACKEND=matcher  copy closest GitHub email (Vercel Hobby)
AGENT_BACKEND=claude   generate with Claude API + hub/site/sheet tools (remote)
AGENT_BACKEND=ollama   local laptop test only
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
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
_AI_DRAFT_TAGS = frozenset({"ai_draft_only", "ai_generated", "ai_matcher_fallback"})


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


def post_internal_note(ticket_id: str, body: str, extra_tags: list[str] | None = None) -> tuple[bool, str]:
    creds = _zendesk_auth_header()
    if not creds:
        return False, "missing ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, or ZENDESK_API_TOKEN"

    subdomain, auth = creds
    url = f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json"
    ticket: dict = {"comment": {"body": body, "public": False}}
    if extra_tags:
        ticket["additional_tags"] = extra_tags
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
            log.info("zendesk note posted ticket_id=%s status=%s", ticket_id, status)
            return True, f"zendesk {status}"
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        log.error("zendesk note failed ticket_id=%s status=%s body=%s", ticket_id, exc.code, detail)
        return False, f"zendesk {exc.code}"
    except URLError as exc:
        log.error("zendesk note failed ticket_id=%s error=%s", ticket_id, exc)
        return False, "zendesk connection error"


def _build_draft(
    tags: str,
    subject: str,
    description: str,
    requester_name: str,
    requester_email: str = "",
) -> tuple[str, str, list[str], str]:
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
            return agent, matched, extra, note_body
        except Exception:
            log.exception("agent generate failed; falling back to GitHub matcher")
            agent, matched, note_body = draft_note(str(tags), str(subject), str(description))
            extra = ["ai_draft_only", f"ai_{agent}", "ai_matcher_fallback"]
            if matched and matched != "none":
                extra.append("ai_hub_match")
            return agent, matched, extra, note_body
    agent, matched, note_body = draft_note(str(tags), str(subject), str(description))
    extra = ["ai_draft_only", f"ai_{agent}"]
    if matched and matched != "none":
        extra.append("ai_hub_match")
    return agent, matched, extra, note_body


def _draft_and_post(
    ticket_id: str,
    subject: str,
    description: str,
    tags: str,
    requester_name: str,
    requester_email: str = "",
) -> None:
    try:
        live_tags = fetch_ticket_tags(ticket_id)
        if _already_drafted(tags) or _already_drafted(live_tags):
            log.info("skip already drafted ticket_id=%s", ticket_id)
            return
        agent, matched, extra, note_body = _build_draft(
            tags, subject, description, requester_name, requester_email
        )
        posted, error = post_internal_note(ticket_id, note_body, extra)
        log.info(
            "draft backend=%s agent=%s matched=%s ticket_id=%s posted=%s error=%s",
            _backend(),
            agent,
            matched,
            ticket_id,
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

    if _already_drafted(tags):
        log.info("skip webhook already drafted ticket_id=%s", ticket_id)
        return JSONResponse(
            {
                "received": True,
                "ticket_id": ticket_id,
                "skipped": "already drafted",
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

    # Ack Zendesk immediately so it does not retry while Claude is still running.
    background_tasks.add_task(
        _draft_and_post,
        ticket_id,
        str(subject),
        str(description),
        str(tags),
        str(requester_name),
        str(requester_email),
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
