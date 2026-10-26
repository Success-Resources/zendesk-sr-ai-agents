# Phase 1 Python service (Vercel)

Step 5: on startup (and every 10 minutes) the service **downloads** `Success-Resources/zendesk-sr-ai-agents` from GitHub and reads `knowledge-hub/`. If GitHub is unreachable, it uses the bundled copy in `service/knowledge-hub`.

Only **Maya** posts a public reply. A finished answer is status **solved** (`ai_answered`). When she needs a person, she posts one short holding reply, sets **open**, and assigns the lane (`ai_assigned_human`): MMI and every other lane to `ZENDESK_MMI_ASSIGNEE_EMAIL` (default `meda.c@srglobal.com`), MMO (`mmo@`) to `ZENDESK_MMO_ASSIGNEE_EMAIL` (default `alina.last@srglobal.com`). Quinn and Rafa do not post publicly. Their draft is an internal note on that same handoff, which still assigns Meda or Alina. Marketing, bounces, and system alerts are **solved with no reply and no assignee** (`auto_closed_noise`). `srv@srglobal.com` is tagged `ai_skipped_srv` and left alone.

The service loads the ticket and comments from the API. The webhook only needs a ticket id, because trigger JSON often breaks on ticket text. A follow-up runs when the latest public comment is the customer's, including after Meda or Alina has already replied. Maya's own public reply does not start another run.

Backfill (dry-run unless `--live`): `python scripts/backfill.py --help`.

- `GET /health` — includes `source` (`github:...` or `bundled`) and `entries`
- `POST /zendesk/webhook`

On this PC, set `AGENT_BACKEND=ollama` so Maya/Quinn/Rafa **write** the note with Llama 3.1 (hub + SR websites + Sheets). Vercel should stay `matcher`. Click-path: `automations/docs/zendesk-ai-ollama-in-the-pipeline.html`.

Env vars (Redeploy after changing):

| Name | Value |
|---|---|
| `ZENDESK_SUBDOMAIN` | `srglobalhelp` |
| `ZENDESK_EMAIL` | Zendesk login email |
| `ZENDESK_API_TOKEN` | API token |
| `GITHUB_TOKEN` | Only if the repo is private |
| `GITHUB_KNOWLEDGE_REPO` | default `Success-Resources/zendesk-sr-ai-agents` |
| `GITHUB_KNOWLEDGE_BRANCH` | default `main` |
| `MAYA_CLAIM_TTL_SECONDS` | optional, default `900`. In-flight ticket claim expires after this many seconds |
| `ZENDESK_MMI_ASSIGNEE_EMAIL` | optional, default `meda.c@srglobal.com` |
| `ZENDESK_MMO_ASSIGNEE_EMAIL` | optional, default `alina.last@srglobal.com` |
