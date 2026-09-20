# Phase 1 Python service (Vercel)

Step 5: on startup (and every 10 minutes) the service **downloads** `Success-Resources/zendesk-sr-ai-agents` from GitHub and reads `knowledge-hub/`. If GitHub is unreachable, it uses the bundled copy in `service/knowledge-hub`.

The internal note is the **approved email** from the hub — the text staff should send to the customer. It is still `public: false`.

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
