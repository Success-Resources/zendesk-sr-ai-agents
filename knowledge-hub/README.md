# Customer Service Knowledge Hub

Organised knowledge for **Maya** (MMI), **Quinn** (Quantum Leap), and **Rafa** (refunds / finance).

This hub is the filing cabinet: the same Maya, Quinn, and Rafa answers, split by topic.

Canonical libraries (one Q&A per line) still live in:

- `maya/knowledge/responses.jsonl`
- `quinn/knowledge/responses.jsonl`
- `rafa/knowledge/responses.jsonl`

## Agents

| Agent | Owns | Do not |
|---|---|---|
| **Maya** | MMI tickets, venue, schedule, VIP, pre-training | Invent prices; say Harv is attending unless confirmed |
| **Quinn** | QL package, NWA, GBI, TTT, EWC inclusions, QL registration | Quote validity/fees/EWC amounts from memory |
| **Rafa** | Refund, cancel, invoice, VAT, failed payment, balance, payment plan | Approve refunds; auto-send; promise a pay date |

Mixed QL + refund: Rafa owns the money part. Quinn facts only after the booking is identified.

## Folder map

```
Customer Service Knowledge Hub
├── Products & Programs
│   ├── Millionaire Mind Intensive     Maya
│   ├── Train the Trainer              Quinn
│   ├── Enlightened Warrior            Quinn + Rafa (F&A)
│   ├── Guerrilla Business Intensive   Quinn
│   ├── Never Work Again               Quinn
│   ├── Quantum Leap                   Quinn
│   └── Other programs                 leftover programmes only
├── FAQs
│   ├── Registration
│   ├── Payment                        Rafa on money questions
│   ├── Event attendance
│   ├── Transfers
│   └── Technical questions
├── Policies
│   ├── Event policies
│   ├── Refund policy                  Rafa
│   ├── Transfer policy
│   └── Cancellation policy
├── Customer Service SOPs
│   ├── Handle refund request          Rafa
│   ├── Handle transfer request
│   ├── Customer cannot find ticket
│   └── Customer complaint
├── Response Guidelines
│   ├── Tone of voice
│   ├── Approved wording
│   ├── Email examples
│   └── WhatsApp examples
├── Escalation Rules
│   ├── Finance escalation             Rafa
│   ├── Event escalation
│   ├── Management escalation
│   └── Urgent customer issue
└── Troubleshooting
    ├── Cannot access Zoom
    ├── Registration not found
    ├── Payment issue                  Rafa
    └── Confirmation email missing
```

## Hard rules (every folder)

- Never invent prices. Verify on the Allocation Sheet / order.
- Never approve refunds, discounts, comps, or payment-plan exceptions.
- Phase 1: draft only. A human sends. Rafa never auto-sends.

## Sources

- Maya: `maya/knowledge/responses.jsonl` (82) and [MMI Sheet](https://docs.google.com/spreadsheets/d/1I0_drElvOqO4RLeAC-cBjXr6ekXQ_OAGbRigwOyjYCE/edit)
- Quinn: `quinn/knowledge/responses.jsonl` (41) and [QL Sheet](https://docs.google.com/spreadsheets/d/12z82ByWdS-_wJxPWlrN2F4TNZ2Cq92Dm1bbA_hIKimE/edit)
- Rafa: `rafa/knowledge/responses.jsonl` (24) and [Rafa Sheet](https://docs.google.com/spreadsheets/d/1_nudcBpyJZiUkKKeufXWpwfsbBVOT4XpxHNX-fmbC-E/edit)
- Corrections: [Sheet](https://docs.google.com/spreadsheets/d/1oF6b-08OOfsKmXC5FrEvbsTqDFoIC47XHEfms21ViaI/edit)
