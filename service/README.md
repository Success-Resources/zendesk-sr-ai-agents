# Phase 1 Python service (Vercel)

Step 5: on startup (and every 10 minutes) the service **downloads** `Success-Resources/zendesk-sr-ai-agents` from GitHub and reads `knowledge-hub/`. If GitHub is unreachable, it uses the bundled copy in `service/knowledge-hub`.

The internal note is the **approved email** from the hub — the text staff should send to the customer. It is still `public: false`, except for requester addresses in `ZENDESK_PUBLIC_SOLVE_EMAILS`. Those tickets get a public reply and status **solved**. If the customer asks to speak to a person, on a new ticket or in a reply on the same ticket, the status is set to **open** and the ticket is assigned to `ZENDESK_HUMAN_ASSIGNEE_EMAIL`. No note is added.

That reply only reaches the service if a second Zendesk trigger fires on the comment. Conditions, all of them: Ticket is Updated, Comment is present, Comment is public. Do not add “Requester is (current user)” and do not exclude the `ai_generated` tag — both stop the reply from being seen. The reply must be a public comment. Same webhook URL and JSON body as the create trigger, including `"latest_comment": "{{ticket.latest_comment}}"`.

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
