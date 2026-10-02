"""Richer extraction — semantic chunking + summarize/tag (Supermemory port).

The hosted Supermemory engine is the full extractor (reuse-by-integration via
``offer_to_engine``). This module is the always-on local fallback so a captured
source still yields coherent chunks, a summary, and tags with no provider
configured — every output lands in the review queue as a proposal and is never
canonical.

Ported pieces:

- **Chunking** follows Supermemory ``code-chunk``'s ``ChunkOptions`` strategy
  (``maxChunkSize``, ``overlapLines``, boundary-respecting splits) adapted from
  tree-sitter code chunks to prose: split at paragraph boundaries first, then
  sentence boundaries, never mid-word, capped at ``max_chunk`` chars carrying
  ``overlap`` chars of the previous tail for context.
- **summarize / tags** mirror what the hosted engine's summarize/tag derive
  (lead-clause summary, salient key terms), so the review queue shows the shape
  of the engine's extraction even when it is not wired.
"""

from __future__ import annotations

import re
from collections import Counter

# code-chunk defaults ~1500 bytes per chunk; prose reads better a little smaller.
MAX_CHUNK = 600
OVERLAP = 80

_STOPWORDS = frozenset(
    """
    a about after again all also an and any are as at be because been before being
    between both but by can could did do does doing down during each few for from
    further get got had has have having he her here hers herself him himself his how
    i if in into is it its itself just like made make many may me might more most much
    must my myself no nor not now of off on once only or other our ours ourselves out
    over own said same see shall she should since so some still such take than that
    the their theirs them themselves then there these they this those through to too
    under until up upon use used using very was way we were what when where which while
    who whom why will with would you your yours yourself
    """.split()
)


def chunk_content(content: str, max_chunk: int = MAX_CHUNK, overlap: int = OVERLAP) -> list[str]:
    """Split prose into coherent chunks (code-chunk ``ChunkOptions`` strategy).

    Paragraph boundaries first, then sentence boundaries for over-long paragraphs.
    A packed chunk never exceeds ``max_chunk`` chars and carries ``overlap`` chars
    of the previous chunk's tail so a fact split across a boundary keeps its
    context. Returns non-empty stripped chunk texts.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chunk:
            units.append(para)
        else:
            for sentence in re.split(r"(?<=[.!?])\s+", para):
                if sentence.strip():
                    units.append(sentence.strip())

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > max_chunk:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail} {unit}".strip() if tail else unit
        else:
            current = f"{current} {unit}".strip() if current else unit
    if current:
        chunks.append(current)
    return chunks


def summarize(text: str, max_len: int = 160) -> str:
    """One-line summary — the lead clause, trimmed (engine summarize fallback)."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return ""
    first = re.split(r"(?<=[.!?])\s+", flat)[0]
    if len(first) <= max_len:
        return first
    return first[: max_len - 1].rsplit(" ", 1)[0] + "…"


def extract_tags(text: str, limit: int = 5) -> list[str]:
    """Salient key terms (engine tag fallback) — top non-stopword words, stable order."""
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text.lower())
    counts = Counter(w for w in words if w not in _STOPWORDS)
    return [word for word, _ in counts.most_common(limit)]
