# Phase 1 Python service (Vercel)

Step 5: on startup (and every 10 minutes) the service **downloads** `Success-Resources/zendesk-sr-ai-agents` from GitHub and reads `knowledge-hub/`. If GitHub is unreachable, it uses the bundled copy in `service/knowledge-hub`.

Only **Maya** posts a public reply. A finished answer is status **solved** (`ai_answered`). When she needs a person, she posts a short holding reply, sets **open**, and assigns the lane (`ai_assigned_human`): MMI to `ZENDESK_MMI_ASSIGNEE_EMAIL` (default `meda.c@srglobal.com`), MMO (`mmo@`) to `ZENDESK_MMO_ASSIGNEE_EMAIL` (default `alina.last@srglobal.com`). Quinn and Rafa write an internal note only (`ai_draft_only`, `ai_quinn` / `ai_rafa`): no public comment and no status change. `srv@srglobal.com` is tagged `ai_skipped_srv` and left alone. `ZENDESK_PUBLIC_SOLVE_EMAILS` does not gate Maya's replies.

The service loads the ticket and comments from the API. The webhook only needs a ticket id, because trigger JSON often breaks on ticket text. A follow-up runs only when the latest public comment is the customer's, and only when no human agent has already replied. Maya's own public reply does not start another run.

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
