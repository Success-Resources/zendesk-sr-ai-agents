"""Load approved emails from GitHub knowledge-hub (Step 5). Fall back to the bundled copy."""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

log = logging.getLogger("zendesk_ai")

STOP = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "my", "i",
    "is", "it", "this", "that", "please", "hello", "hi", "dear", "we", "you",
    "your", "our", "with", "from", "have", "has", "was", "be", "can", "not",
    "but", "got", "get", "never", "still", "also", "just", "will", "would",
}

_lock = Lock()
_hub_dir: Path | None = None
_loaded_at = 0.0
_source = "none"
_entry_count = 0


def _repo() -> str:
    return (os.getenv("GITHUB_KNOWLEDGE_REPO") or "Success-Resources/zendesk-sr-ai-agents").strip()


def _branch() -> str:
    return (os.getenv("GITHUB_KNOWLEDGE_BRANCH") or "main").strip()


def _ttl() -> float:
    return float(os.getenv("KNOWLEDGE_TTL_SECONDS") or "600")


def _stamp_path() -> Path:
    return Path(tempfile.gettempdir()) / "sr-zendesk-knowledge" / ".stamp"


def _cached_hub() -> Path | None:
    hub = Path(tempfile.gettempdir()) / "sr-zendesk-knowledge"
    if not hub.exists():
        return None
    stamp = _stamp_path()
    try:
        age = time.time() - stamp.stat().st_mtime
    except OSError:
        age = time.time() * 2
    if age >= _ttl():
        return None
    matches = list(hub.glob("*/knowledge-hub"))
    if matches and matches[0].is_dir():
        return matches[0]
    return None


def _count_entries(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*.md") if p.name in {"maya.md", "quinn.md", "rafa.md"})


def bundled_hub() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "knowledge-hub", here.parent / "knowledge-hub"):
        if candidate.is_dir():
            return candidate
    return here / "knowledge-hub"


def hub_root() -> Path:
    ensure_hub()
    return _hub_dir or bundled_hub()


def knowledge_status() -> dict:
    ensure_hub()
    return {
        "source": _source,
        "repo": _repo(),
        "branch": _branch(),
        "path": str(_hub_dir) if _hub_dir else None,
        "exists": bool(_hub_dir and _hub_dir.is_dir()),
        "entries": _entry_count,
        "loaded_at": _loaded_at,
    }


def _download_github_hub() -> Path:
    repo = _repo()
    branch = _branch()
    url = f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
    headers = {"User-Agent": "sr-zendesk-ai"}
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = UrlRequest(url, headers=headers)
    with urlopen(req, timeout=8) as resp:
        data = resp.read()
    extract_root = Path(tempfile.gettempdir()) / "sr-zendesk-knowledge"
    if extract_root.exists():
        shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(extract_root)
    tops = [p for p in extract_root.iterdir() if p.is_dir()]
    repo_dir = tops[0] if tops else extract_root
    hub = repo_dir / "knowledge-hub"
    if not hub.is_dir():
        raise FileNotFoundError(f"knowledge-hub missing in {repo}@{branch}")
    _stamp_path().write_text(str(time.time()), encoding="utf-8")
    log.info("knowledge hub downloaded from GitHub repo=%s branch=%s path=%s", repo, branch, hub)
    return hub


def ensure_hub(force: bool = False, download: bool = True) -> Path:
    global _hub_dir, _loaded_at, _source, _entry_count
    with _lock:
        age = time.time() - _loaded_at
        if (
            not force
            and _hub_dir
            and _hub_dir.is_dir()
            and age < _ttl()
            and _source.startswith("github")
        ):
            return _hub_dir
        cached = None if force else _cached_hub()
        if cached is not None:
            _hub_dir = cached
            _source = f"github-cache:{_repo()}@{_branch()}"
            _loaded_at = time.time()
            _entry_count = _count_entries(_hub_dir)
            return _hub_dir
        if download:
            try:
                _hub_dir = _download_github_hub()
                _source = f"github:{_repo()}@{_branch()}"
                _loaded_at = time.time()
                _entry_count = _count_entries(_hub_dir)
                return _hub_dir
            except Exception:
                log.exception("GitHub knowledge download failed; using bundled hub")
        _hub_dir = bundled_hub()
        _source = "bundled"
        _loaded_at = time.time()
        _entry_count = _count_entries(_hub_dir)
        return _hub_dir


@dataclass
class Entry:
    agent: str
    question: str
    email: str
    tag: str
    path: str


def _normalize(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    t = t.replace("n't", " not")
    return t


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return {w for w in words if len(w) > 2 and w not in STOP}


def _parse_file(path: Path, default_agent: str) -> list[Entry]:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"\n(?=## )", text)
    out: list[Entry] = []
    for chunk in chunks:
        heading = re.match(r"##\s+(.+)", chunk)
        if not heading:
            continue
        title = heading.group(1).strip()
        if title.startswith("Coverage") or "Entries:" in title:
            continue
        agent_m = re.search(r"\*\*Agent:\*\*\s*(.+)", chunk)
        tag_m = re.search(r"\*\*Tag:\*\*\s*(.+)", chunk)
        lines = chunk.splitlines()
        body_lines: list[str] = []
        started = False
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if not started:
                if not line.strip() or line.startswith("**") or line.startswith("### "):
                    continue
                started = True
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if len(body) < 40:
            continue
        question = re.sub(r"^[0-9.]+ — ", "", title).strip()
        out.append(
            Entry(
                agent=(agent_m.group(1).strip() if agent_m else default_agent),
                question=question,
                email=body,
                tag=(tag_m.group(1).strip() if tag_m else ""),
                path=str(path.as_posix()),
            )
        )
    return out


def load_entries(agent: str, refresh: bool = True) -> list[Entry]:
    if refresh:
        ensure_hub()
    root = _hub_dir or bundled_hub()
    filename = f"{agent}.md"
    entries: list[Entry] = []
    if not root.is_dir():
        return entries
    for path in root.rglob(filename):
        if path.name.startswith("all-"):
            continue
        entries.extend(_parse_file(path, agent.title()))
    return entries


def route_agent(tags: str, subject: str, description: str) -> str:
    blob = f"{tags} {subject} {description}".lower()
    tagset = set((tags or "").lower().split())
    if tagset & {"refund_request", "finance_related", "invoice_request", "vat_invoice"}:
        return "rafa"
    if any(w in blob for w in ("refund", "invoice", "vat", "payment failed", "money back")):
        return "rafa"
    if tagset & {"ql", "nwa", "gbi", "ttt", "ewc"}:
        return "quinn"
    if tagset & {"mmi", "mmo_event"}:
        return "maya"
    if any(w in blob for w in ("quantum leap", " qleap", "never work again", "enlightened warrior", "train the trainer", "guerrilla")):
        return "quinn"
    if any(w in blob for w in ("millionaire mind", " mmi", "vip ticket", "harv eker")):
        return "maya"
    return "maya"


def best_match(agent: str, subject: str, description: str) -> tuple[Entry | None, float]:
    blob = _normalize(f"{subject} {description}")
    query = _tokens(blob)
    if not query:
        return None, 0.0
    ranked: list[tuple[float, Entry]] = []
    for entry in load_entries(agent):
        title_tokens = _tokens(entry.question)
        if not title_tokens:
            continue
        title_hit = len(query & title_tokens) / len(title_tokens)
        body_hit = len(query & _tokens(entry.email[:400])) / max(1, len(query))
        score = title_hit + 0.15 * body_hit
        if _normalize(entry.question) in blob:
            score += 0.45
        ranked.append((score, entry))
    if not ranked:
        return None, 0.0
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1], ranked[0][0]


def sendable_email(text: str) -> str:
    """Same words as the hub email, with the send-ready sign-off."""
    email = re.sub(
        r"(All the best|Kind regards|Warm regards|Best regards),?\s*\nEvelin\s*$",
        "Warm regards,\nSuccess Resources Support",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if "Success Resources Support" not in email:
        email = re.sub(
            r"(Kind regards|All the best|Best regards|Warm regards),?\s*$",
            "Warm regards,\nSuccess Resources Support",
            email,
            flags=re.IGNORECASE,
        )
    if "Success Resources Support" not in email:
        email = email.rstrip() + "\n\nWarm regards,\nSuccess Resources Support"
    return email.strip()


def draft_note(tags: str, subject: str, description: str) -> tuple[str, str, str]:
    """Return agent, matched question, and the exact email staff should send."""
    agent = route_agent(tags, subject, description)
    entry, score = best_match(agent, subject, description)
    if entry is None or score < 0.18:
        body = (
            f"No close match in the GitHub knowledge hub ({agent.title()}, score {score:.2f}). "
            "A person should classify and reply. Do not invent a price or approve a refund."
        )
        return agent, "none", body
    log.info("hub match agent=%s question=%s score=%.2f", agent, entry.question, score)
    return agent, entry.question, sendable_email(entry.email)
