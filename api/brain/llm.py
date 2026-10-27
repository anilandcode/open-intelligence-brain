"""Optional chat model for claim extraction — any OpenAI-compatible endpoint.

Off unless `BRAIN_LLM_BASE_URL` is set. On the Oracle VM that can be the LLM
proxy sidecar on loopback (`http://127.0.0.1:6799/v1`), which already holds
the provider key. With no model configured every caller keeps the
deterministic path, so a fresh clone and the test suite never dial out.

A model here only ever *proposes*. Its output lands in the review queue like
any other candidate and cannot reach canonical knowledge without a person.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


class ChatModel(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> Any | None:
        """Return the parsed JSON the model answered with, or None on any failure."""
        ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_reply(text: str) -> Any | None:
    """Parse a model reply that should be JSON, tolerating a markdown fence."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        # Some models wrap the object in prose; take the outermost {...} or [...].
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except ValueError:
            return None


class OpenAICompatibleChat:
    """`POST {base}/chat/completions` with a JSON-only instruction."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete_json(self, system: str, user: str) -> Any | None:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 — extraction falls back, never fails capture
            log.warning("chat model call failed, using deterministic extraction: %s", exc)
            return None
        parsed = parse_json_reply(content or "")
        if parsed is None:
            log.warning("chat model returned non-JSON content; using deterministic extraction")
        return parsed


_UNSET = object()
_override: ChatModel | None | object = _UNSET


def set_chat_model(model: ChatModel | None) -> None:
    """Override the model (tests). ``None`` forces the deterministic path."""
    global _override
    _override = model


def reset_chat_model() -> None:
    global _override
    _override = _UNSET


def get_chat_model() -> ChatModel | None:
    if _override is not _UNSET:
        return _override  # type: ignore[return-value]
    settings = get_settings()
    if not settings.llm_base_url:
        return None
    return OpenAICompatibleChat(
        settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_timeout
    )
