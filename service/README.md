# Phase 1 Python service (Vercel)

Zendesk webhook → match an approved **email** from `knowledge-hub/` → private internal note. No public reply. No AI model yet; the draft is the closest hub email.

- `GET /health` — `zendesk_configured` and `knowledge_hub_exists`
- `POST /zendesk/webhook`

Vercel **Root Directory:** `service`. Knowledge is copied to `service/knowledge-hub` so the function can read it.

Env vars (then Redeploy): `ZENDESK_SUBDOMAIN` (`srglobalhelp`), `ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`.
