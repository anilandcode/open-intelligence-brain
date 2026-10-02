"""Pluggable text embeddings for hybrid (vector + keyword) retrieval.

Two providers behind one interface:

- ``HashingEmbedder`` — a deterministic **local lexical** embedding (word +
  character-trigram feature hashing, signed, L2-normalised). Always available,
  zero cost, fully testable. It captures surface-form similarity (shared words,
  morphology, misspellings), **not** deep semantics — it is the honest always-on
  fallback, not a neural model.
- ``OpenAICompatibleEmbedder`` — real neural embeddings via any OpenAI-compatible
  ``/v1/embeddings`` endpoint. Configure ``embedding_base_url`` (+ key + model)
  to get true semantic search (synonymy, paraphrase).

``get_embedder()`` prefers the neural provider when configured and otherwise
falls back to the lexical one, so the vector path is always live and upgrades to
real semantics with a single env var. ``set_embedder`` lets tests inject or
disable the provider.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# Hashing embedder dimension. Neural providers use their own native dimension.
DIM = 384


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, text: str) -> list[float] | None: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


class HashingEmbedder:
    """Deterministic lexical embedding via signed feature hashing.

    Word and character-trigram features hash into ``DIM`` buckets and are
    L2-normalised. Texts sharing words or morphology land close together, so the
    vector channel is robust to misspellings and partial overlap that exact-match
    keyword search misses. This is real (if shallow) similarity — deliberately
    NOT sold as neural semantics.
    """

    model = "hash-lexical-v1"

    def embed(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        vec = [0.0] * DIM
        lowered = text.lower()
        for word in re.findall(r"[a-z0-9]+", lowered):
            self._add(vec, "w:" + word, 1.0)
            for i in range(len(word) - 2):
                self._add(vec, "t:" + word[i : i + 3], 0.5)
        return _l2_normalize(vec)

    @staticmethod
    def _add(vec: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        sign = 1.0 if (h >> 63) == 0 else -1.0  # signed hashing cancels collisions
        vec[h % DIM] += sign * weight


class OpenAICompatibleEmbedder:
    """Neural embeddings via an OpenAI-compatible ``/v1/embeddings`` endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def embed(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            resp = httpx.post(
                f"{self.base_url}/v1/embeddings",
                headers=headers,
                json={"input": text, "model": self.model},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()["data"][0]["embedding"]
            return [float(x) for x in data]
        except Exception as exc:  # noqa: BLE001 — degrade to lexical, never fail a read
            log.warning("neural embedding failed, using lexical fallback: %s", exc)
            return HashingEmbedder().embed(text)


_UNSET = object()
_override: EmbeddingProvider | None | object = _UNSET
_cached: EmbeddingProvider | None = None


def set_embedder(provider: EmbeddingProvider | None) -> None:
    """Override the embedder (tests). ``None`` disables the vector channel."""
    global _override, _cached
    _override = provider
    _cached = provider


def reset_embedder() -> None:
    """Clear any override (tests) so the settings-based provider is rebuilt."""
    global _override, _cached
    _override = _UNSET
    _cached = None


def get_embedder() -> EmbeddingProvider | None:
    global _override, _cached
    if _override is not _UNSET:
        return _override  # type: ignore[return-value]
    if _cached is not None:
        return _cached
    settings = get_settings()
    if settings.embedding_base_url:
        _cached = OpenAICompatibleEmbedder(
            settings.embedding_base_url,
            settings.embedding_api_key,
            settings.embedding_model,
        )
        return _cached
    # No neural provider → return None so retrieval stays keyword-only. The
    # lexical HashingEmbedder is a TEST utility only: its hash collisions create
    # false matches between unrelated text, and a false match here would break
    # the abstention guarantee (a member could get a grounded answer to a
    # question whose only real evidence is private). Never the retrieval default.
    return None
