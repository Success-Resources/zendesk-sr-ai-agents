# Phase 1 Python service (Vercel)

Tiny FastAPI app for Vercel Hobby. Step 2 of `docs/zendesk-ai-phase1-architecture.html`.

- `GET /health` — browser check
- `POST /zendesk/webhook` — Zendesk will call this later

Does not post to Zendesk yet. Does not call an AI model yet.

In the Vercel project, set **Root Directory** to `service`. Put secrets in Vercel Environment Variables, not in GitHub. Never commit `.env`.
