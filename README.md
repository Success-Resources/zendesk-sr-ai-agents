# Success Resources AI assistants (GitHub knowledge)

This folder is the GitHub home for Maya, Quinn and Rafa. Each assistant has its own knowledge base. You update the files here as tickets are corrected. The knowledge grows over time.

The Quantum Leap assistant is named **Quinn** (not Queen).

```
github/sr-ai-agents/
  maya/knowledge/     MMI
  quinn/knowledge/    Quantum Leap
  rafa/knowledge/     Refunds, invoices, payments (drafts only)
```

## What lives in each knowledge folder

| File | Purpose |
|------|---------|
| `responses.jsonl` | One approved question and answer per line. This is what the assistant will use. |
| `responses.md` | Same content, easy to read. |
| `corrections.jsonl` | Empty for now. Add a line here when a live ticket was wrong and you have better wording. |
| `CHANGELOG.md` | Short log of what changed and when. |

## How knowledge grows

1. The reviewer finds a wrong reply in Zendesk.
2. They write the better wording in the shared Google Sheet.
3. On the Wednesday call you agree it.
4. You add the answer to that assistant's `responses.jsonl` (and a line in `CHANGELOG.md`).
5. Optionally copy the sheet row into `corrections.jsonl` so you have a history of what was fixed.

## Starting counts

- Maya: 82 MMI answers
- Quinn: 41 Quantum Leap answers
- Rafa: 24 refund, payment, transfer and invoice drafts. Rafa never sends without a person.

## Not in this step

Connecting Zendesk, running the service, or publishing online. This step is only the folder and the knowledge.
