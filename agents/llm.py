"""LLM brain: Claude API in the cloud, or Ollama on a machine for tests."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ModelNotAvailable(RuntimeError):
    pass


def provider() -> str:
    if (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        return "claude"
    return "ollama"


def model_name() -> str:
    if provider() == "claude":
        return (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5").strip()
    return (os.getenv("OLLAMA_MODEL") or "llama3.1").strip()


def complete(messages: list[dict]) -> str:
    if provider() == "claude":
        return _complete_claude(messages)
    return _complete_ollama(messages)


def _complete_claude(messages: list[dict]) -> str:
    """Anthropic Messages API — no laptop, no Ollama."""
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ModelNotAvailable("ANTHROPIC_API_KEY is not set")

    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    chat = [m for m in messages if m.get("role") in {"user", "assistant"}]
    if not chat:
        chat = [{"role": "user", "content": "JSON only."}]

    payload: dict = {
        "model": model_name(),
        "max_tokens": 4096,
        "system": "\n\n".join(system_parts) if system_parts else "",
        "messages": [{"role": m["role"], "content": m["content"]} for m in chat],
    }
    if not payload["system"]:
        payload.pop("system")

    req = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise ModelNotAvailable(f"Claude API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ModelNotAvailable(f"Claude API connection error: {exc.reason}") from exc

    bits: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            bits.append(block.get("text") or "")
    text = "\n".join(bits).strip()
    if not text:
        raise ModelNotAvailable("Claude returned an empty reply")
    return text


def _complete_ollama(messages: list[dict]) -> str:
    host = (os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    url = f"{host}/api/chat"
    payload = json.dumps(
        {
            "model": model_name(),
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    req = Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        try:
            err = json.loads(detail).get("error") or detail
        except json.JSONDecodeError:
            err = detail or exc.reason
        raise ModelNotAvailable(f"Ollama refused model {model_name()} (HTTP {exc.code}): {err}") from exc
    except URLError as exc:
        raise ModelNotAvailable(
            "Ollama is not running. For production use ANTHROPIC_API_KEY instead of a local model. "
            f"Details: {exc.reason}"
        ) from exc
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise ModelNotAvailable(f"Ollama returned an empty reply from model {model_name()}")
    return text
