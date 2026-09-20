"""Run one agent on a ticket from the command line (no Zendesk)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.loop import run_agent  # noqa: E402
from agents.llm import ModelNotAvailable  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Maya, Quinn or Rafa locally")
    parser.add_argument("--agent", default="", help="maya, quinn or rafa (optional; inferred from text)")
    parser.add_argument("--tags", default="")
    parser.add_argument("--subject", default="Customer question")
    parser.add_argument("--body", default="", help="Customer message")
    parser.add_argument("text", nargs="*", help="Customer message if --body is omitted")
    args = parser.parse_args()
    body = args.body or " ".join(args.text)
    if not body:
        parser.error("Pass a customer message, e.g. python -m agents.run --agent maya \"I did not get my confirmation email\"")

    agent = args.agent
    if not agent:
        sys.path.insert(0, str(_ROOT / "service"))
        from knowledge import route_agent

        agent = route_agent(args.tags, args.subject, body)

    try:
        result = run_agent(agent, args.subject, body, args.tags)
    except ModelNotAvailable as exc:
        print(exc, file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "agent": result.agent,
                "needs_human": result.needs_human,
                "confidence": result.confidence,
                "reason": result.reason,
                "tools_used": result.tools_used,
                "trace": result.trace,
                "email": result.email,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
