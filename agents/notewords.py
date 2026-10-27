"""Keep Maya's internal notes from firing Zendesk keyword triggers.

The live triggers (backup 26 Oct 2026) match words in ANY comment, private notes
included, and they add tags and change the priority:
  refund / money back                         -> refund_request finance_related, priority high
  Quantum, Leap, QL                           -> ql
  TTT, train the trainer                      -> ttt
  EWC, warrior, enlightened warrior camp      -> ewc
  NWA, never work again                       -> nwa
  GBI, guerilla (and misspellings)            -> gbi
  millionaire, MMI                            -> mmi
  invoice, invoices, invoicing                -> invoice_request finance_related
So the note's own wording (lane names, "Needed:", "What to check:") must not use
those words. Customer quotes in a note are rewritten to neutral words as well.
Drafts keep a word only when the customer used it themselves, so the tag it adds
matches what the customer asked.
"""

from __future__ import annotations

import re

# (group, pattern, replacement). Order matters: phrases before single words.
_RULES: list[tuple[str, str, str]] = [
    ("money", r"refunds", "repayments"),
    ("money", r"refunded", "repaid"),
    ("money", r"refunding", "repaying"),
    ("money", r"refund", "repayment"),
    ("money", r"reimbursements?", "repayment"),
    ("money", r"reimbursed", "repaid"),
    ("money", r"reimburs(?:e|ing)", "repay"),
    ("money", r"charge[\s-]?backs?", "card dispute"),
    ("money", r"money\s+back", "repayment"),
    ("ql", r"quantum[\s-]*leap", "QLeap"),
    ("ql", r"quantum", "QLeap"),
    ("ql", r"QL", "QLeap"),
    ("ttt", r"train[\s-]+the[\s-]+trainer", "T3"),
    ("ttt", r"TTT", "T3"),
    ("ewc", r"enlightened[\s-]+warriors?(?:[\s-]+camp)?", "EWCamp"),
    ("ewc", r"enligh?t?n?ed[\s-]+warriors?", "EWCamp"),
    ("ewc", r"warriors?", "EWCamp"),
    ("ewc", r"enlighted|enlightned", "enlightened"),
    ("ewc", r"EWC", "EWCamp"),
    ("nwa", r"never[\s-]+work[\s-]+again", "NWAgain"),
    ("nwa", r"NWA", "NWAgain"),
    ("gbi", r"gu?err?ill?a[\s-]+business(?:[\s-]+intensive)?", "GBIntensive"),
    ("gbi", r"gu?err?ill?a|gurr?ill?a", "GBIntensive"),
    ("gbi", r"GBI", "GBIntensive"),
    ("mmi", r"millionaire[\s-]+mind(?:[\s-]+intensive)?", "MM-Intensive"),
    ("mmi", r"millionaires?", "MM-Intensive"),
    ("mmi", r"MMI", "MM-Intensive"),
]
_COMPILED = [(group, re.compile(rf"(?<!\w)(?:{pat})(?!\w)", re.I), rep) for group, pat, rep in _RULES]

# Every trigger word, for tests and for checking Maya's own template text.
TRIGGER_WORDS = re.compile(
    r"(?<!\w)(?:refund\w*|reimburs\w*|charge[\s-]?backs?|money\s+back|quantum|leap|QL|TTT|EWC|NWA|GBI|MMI|"
    r"millionaire\w*|warriors?|enlighted|enlightned|enlightened\s+warrior\s+camp|never\s+work\s+again|"
    r"train\s+the\s+trainer|gu?err?ill?a|gurr?ill?a|invoic\w*|confirmation\s+link|missing\s+confirmation|"
    r"confirmation\s+missing|registration\s+link|access\s+link)(?!\w)",
    re.I,
)


def _groups_in(text: str) -> set[str]:
    return {group for group, rx, _rep in _COMPILED if rx.search(text or "")}


LANE_GROUPS = {"quinn": {"ql", "ttt", "ewc", "nwa", "gbi"}, "rafa": {"money"}}


def scrub(text: str, keep_from: str | None = None, keep_groups=None) -> str:
    """Swap trigger words for neutral ones.

    keep_from: a word group the customer used in keep_from is kept as is.
    keep_groups: groups to keep regardless (a Quinn draft keeps programme names,
    a Rafa draft keeps payment words: that lane's tag is the right tag).
    """
    out = text or ""
    keep = (_groups_in(keep_from) if keep_from else set()) | set(keep_groups or ())
    for group, rx, rep in _COMPILED:
        if group in keep:
            continue
        out = rx.sub(lambda m, rep=rep: _match_case(m.group(0), rep), out)
    return out


def _match_case(found: str, rep: str) -> str:
    if found[:1].isupper() and rep[:1].islower():
        return rep[:1].upper() + rep[1:]
    return rep


def trigger_hits(text: str) -> list[str]:
    return [m.group(0) for m in TRIGGER_WORDS.finditer(text or "")]
