"""Google Docs export as text. Only IDs listed in GOOGLE_DOC_IDS."""

from __future__ import annotations

import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def lookup_doc(query: str) -> str:
    ids = [p.strip() for p in (os.getenv("GOOGLE_DOC_IDS") or "").split(",") if p.strip()]
    if not ids:
        return (
            "no_doc: set GOOGLE_DOC_IDS to comma-separated Google Doc IDs, "
            "and share each Doc as Viewer to anyone with the link. "
            f"Query was: {(query or '').strip() or '(empty)'}."
        )
    q = (query or "").lower()
    chunks: list[str] = []
    for doc_id in ids[:8]:
        url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        req = Request(url, headers={"User-Agent": "sr-zendesk-ai-agent"})
        try:
            with urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError) as exc:
            chunks.append(f"Doc {doc_id}: not readable ({exc}). Share as Viewer anyone-with-link.")
            continue
        text = " ".join(text.split())
        if q:
            idx = text.lower().find(q[:40])
            snippet = text[max(0, idx - 200) : idx + 800] if idx >= 0 else text[:800]
        else:
            snippet = text[:800]
        chunks.append(f"Doc {doc_id}:\n{snippet}")
    return "\n\n".join(chunks) if chunks else "no_doc: nothing readable"
