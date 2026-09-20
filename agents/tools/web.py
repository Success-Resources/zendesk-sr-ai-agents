"""Allowlisted Success Resources pages only — not open web search."""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[1]
_ALLOW = _ROOT / "allowlist.txt"
_SEEDS = _ROOT / "site-seeds.txt"
_MAX_PAGES = 20
_TTL = 1800.0
_lock = Lock()
_index: list[tuple[str, str]] = []
_loaded_at = 0.0


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


def _allowed_hosts() -> set[str]:
    hosts = set()
    if _ALLOW.is_file():
        for line in _ALLOW.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                hosts.add(line.split("/")[0])
    return hosts


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in _allowed_hosts()


def _download(url: str, limit: int = 120_000) -> str:
    req = Request(url, headers={"User-Agent": "sr-zendesk-ai-agent"})
    with urlopen(req, timeout=12) as resp:
        return resp.read(limit).decode("utf-8", errors="replace")


def _parse_html(url: str, html: str) -> tuple[str, list[str]]:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    links = []
    for href in parser.links:
        abs_url = urljoin(url, href).split("#")[0]
        if _allowed(abs_url) and abs_url not in links:
            links.append(abs_url)
    return text, links


def fetch_url(url: str) -> str:
    raw = (url or "").strip()
    if not _allowed(raw):
        host = (urlparse(raw).hostname or raw or "that URL")
        return f"ERROR: {host} is not on the Success Resources allowlist. Do not crawl the open web."
    try:
        html = _download(raw)
    except URLError as exc:
        return f"ERROR: could not fetch page ({exc})"
    text, _ = _parse_html(raw, html)
    if len(text) < 40:
        return f"Fetched {raw} but almost no text was visible."
    return f"URL: {raw}\n{text[:4000]}"


def _seeds() -> list[str]:
    if not _SEEDS.is_file():
        return []
    out = []
    for line in _SEEDS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and _allowed(line):
            out.append(line)
    return out


def _rebuild_index() -> None:
    global _index, _loaded_at
    pages: list[tuple[str, str]] = []
    seen: set[str] = set()
    queue = list(_seeds())
    while queue and len(pages) < _MAX_PAGES:
        url = queue.pop(0)
        if url in seen or not _allowed(url):
            continue
        seen.add(url)
        try:
            html = _download(url)
        except Exception:
            continue
        text, links = _parse_html(url, html)
        if len(text) >= 80:
            pages.append((url, text[:6000]))
        for link in links:
            if link not in seen and len(seen) + len(queue) < _MAX_PAGES:
                queue.append(link)
    _index = pages
    _loaded_at = time.time()


def search_site(query: str) -> str:
    """Keyword search over a bounded crawl of allowlisted SR pages."""
    q = (query or "").strip()
    words = {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", q)}
    with _lock:
        if not _index or (time.time() - _loaded_at) > _TTL:
            _rebuild_index()
        pages = list(_index)
    if not pages:
        return (
            "no_pages: could not read Success Resources sites. "
            "Do not invent venue or price. Set needs_human true if you needed a live page."
        )
    ranked: list[tuple[int, str, str]] = []
    for url, text in pages:
        blob = text.lower()
        score = sum(1 for w in words if w in blob) if words else 0
        ranked.append((score, url, text))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if words and ranked[0][0] == 0:
        return (
            "no_match on crawled Success Resources pages for: "
            f"{q}. Do not invent. You may fetch_url a specific allowlisted link from the hub."
        )
    chunks = []
    for score, url, text in ranked[:3]:
        chunks.append(f"URL: {url}\n{text[:1500]}")
    return "\n\n---\n\n".join(chunks)
