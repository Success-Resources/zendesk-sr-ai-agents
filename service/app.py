"""Phase 1 starter: receive Zendesk webhooks. No AI and no ticket updates yet."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zendesk_ai")

app = FastAPI(title="SR Zendesk AI Phase 1")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "phase": 1}


@app.post("/zendesk/webhook")
async def zendesk_webhook(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}

    ticket = body.get("ticket") if isinstance(body.get("ticket"), dict) else {}
    ticket_id = body.get("id") or body.get("ticket_id") or ticket.get("id")
    subject = body.get("subject") or ticket.get("subject")

    log.info("webhook received ticket_id=%s subject=%s", ticket_id, subject)
    return JSONResponse({"received": True, "ticket_id": ticket_id})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
