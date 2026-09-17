# Phase 1 Python service (Vercel)

Tiny FastAPI app for Vercel Hobby. Follow `automations/docs/zendesk-ai-phase1-architecture.html`.

- `GET /health` — browser check. `zendesk_configured` is true when env vars are set.
- `POST /zendesk/webhook` — Zendesk trigger calls this; the service posts a **private** internal note. No AI yet. The customer does not see the note.

In the Vercel project, set **Root Directory** to `service`. Put secrets in Vercel Environment Variables, not in GitHub. Never commit `.env`.

Required env vars (Production, Preview, Development), then **Redeploy**:

| Name | Value |
|---|---|
| `ZENDESK_SUBDOMAIN` | `srglobalhelp` (not `srglobalhelp.zendesk.com`) |
| `ZENDESK_EMAIL` | Your Zendesk login email |
| `ZENDESK_API_TOKEN` | API token from Admin Center |

Optional: `ZENDESK_WEBHOOK_SECRET` after you turn on webhook signing.
