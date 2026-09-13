# Customer Service Knowledge Hub — Maya (MMI)

Knowledge architecture for the Millionaire Mind Intensive assistant. Canonical approved Q&As remain in `responses.jsonl` / `responses.md` (82 entries). This hub organises the same knowledge for agents and reviewers.

```
maya/knowledge/
├── products-programs/
│   ├── millionaire-mind-intensive.md   ✅ populated (12 Q&As)
│   ├── train-the-trainer.md            ⏳ stub
│   ├── enlightened-warrior.md          ⏳ stub
│   └── other-programs.md               ✅ pointer only
├── faqs/
│   ├── registration.md                 ✅
│   ├── payment.md                      ✅
│   ├── event-attendance.md             ✅
│   ├── transfers.md                    ✅
│   └── technical-questions.md          ✅
├── policies/
│   ├── event-policies.md
│   ├── refund-policy.md
│   ├── transfer-policy.md
│   └── cancellation-policy.md
├── sops/
│   ├── handle-refund-request.md
│   ├── handle-transfer-request.md
│   ├── customer-cannot-find-ticket.md
│   └── customer-complaint.md
├── response-guidelines/
│   ├── tone-of-voice.md
│   ├── approved-wording.md
│   ├── email-examples.md
│   └── whatsapp-examples.md
├── escalation-rules/
│   ├── finance-escalation.md
│   ├── event-escalation.md
│   ├── management-escalation.md
│   └── urgent-customer-issue.md
├── troubleshooting/
│   ├── cannot-access-zoom.md           ⏳ limited
│   ├── registration-not-found.md
│   ├── payment-issue.md
│   └── confirmation-email-missing.md
├── responses.jsonl                     canonical bot answers
├── responses.md
├── corrections.jsonl
└── CHANGELOG.md
```

## Scope

- **In scope:** Millionaire Mind Intensive customer questions Maya is approved to answer.
- **Out of scope for now:** Train the Trainer and full Enlightened Warrior product libraries (stubs only).
- **Sister assistants:** Quinn (Quantum Leap), Rafa (refunds/invoices/payments drafts).

## How to grow knowledge

1. Agree corrected wording on the Wednesday review.
2. Update `responses.jsonl` (and `responses.md`).
3. Mirror the entry into the matching hub FAQ file if it belongs there.
4. Log the change in `CHANGELOG.md`.
5. Optionally append the sheet row to `corrections.jsonl`.
