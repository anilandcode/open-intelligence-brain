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

import json
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


_TASK_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*\[[ xX]\]\s*")


def is_task_fragment(text: str) -> bool:
    """Checkbox / task-list lines are note scaffolding, never knowledge.

    A vault import turns every ``- [ ] …`` checklist line into a proposal
    otherwise (3,685 proposals from 35 notes, most of them QA checklists).
    The line stays in the immutable source and remains an evidence span — it
    just never becomes a proposal. Plain prose bullets are deliberately NOT
    filtered: some carry real decisions and stay eligible.
    """
    return bool(_TASK_LINE.match(text.strip()))


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


def normalize_tags(tags: list[str] | None, limit: int = 12) -> list[str]:
    """Lower-case, trimmed, de-duplicated tags of at most 40 characters each."""
    cleaned: list[str] = []
    for tag in tags or []:
        value = re.sub(r"\s+", " ", str(tag).replace('"', "")).strip().lower()[:40]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:limit]


def parse_tags(raw: str | None) -> list[str]:
    """Read a stored JSON tag list, tolerating NULL or a malformed value."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return normalize_tags(parsed) if isinstance(parsed, list) else []


# --- intake selection --------------------------------------------------------
#
# Every span stays in the immutable source as evidence. These helpers only
# decide which spans are worth a reviewer's attention, because a queue that
# proposes every sentence (3,685 proposals from 35 notes) cannot be reviewed,
# and an unreviewable queue defeats the approval gate it exists to feed.

_HEADING = re.compile(r"^\s*#{1,6}\s")
_URL = re.compile(r"https?://\S+")
_CLAIM_SIGNAL = re.compile(
    r"\b(?:because|decided|decision|chose|learned|lesson|realized|should|must|"
    r"always|never|prefer|believe|means|principle|rule|policy|costs?|price|"
    r"revenue|deadline|owner|responsible|works?|fails?|caused?)\b"
)


def is_low_value_fragment(text: str) -> bool:
    """Spans that are note structure rather than a statement of knowledge.

    Markdown headings, lead-in lines ending in a colon, table rows, bare links
    and lines that are mostly symbols or numbers. Like task lines they remain
    evidence spans; they just never become proposals.
    """
    stripped = text.strip()
    if not stripped or is_task_fragment(stripped):
        return True
    if _HEADING.match(stripped) or stripped.endswith(":"):
        return True
    if stripped.count("|") >= 2:
        return True
    without_urls = _URL.sub("", stripped).strip()
    if len(without_urls) < 20:
        return True
    letters = sum(char.isalpha() for char in without_urls)
    return letters / max(len(without_urls), 1) < 0.6


_TIME_SENSITIVE = re.compile(
    r"(?:[$€£¥]\s?\d|\d\s?%|\b\d[\d,.]*\s?(?:dollars|euros|pounds|usd|eur|gbp|per\s+(?:seat|month|year|user))\b"
    r"|\b(?:price|prices|pricing|costs?|fee|fees|salary|budget|headcount|currently|right now|"
    r"at the moment|this (?:quarter|month|year)|next (?:quarter|month|year)|deadline|roadmap|"
    r"plan(?:s|ned)? to|owns|owner|lead(?:s)?|head of|reports to|version|release)\b)",
    re.IGNORECASE,
)


def looks_time_sensitive(statement: str) -> bool:
    """Whether a statement is the kind that goes out of date.

    Prices, amounts, roles and owners, plans and "currently" statements change;
    lessons and principles mostly do not. Used only to suggest a review-by date.
    """
    return bool(_TIME_SENSITIVE.search(statement))


def candidate_score(text: str, declared_type: str) -> float:
    """How likely a span is to be knowledge worth approving. Higher is better.

    Deterministic and explainable on purpose: it only ranks spans for the
    per-version cap, and a reviewer can still find every span in the source.
    A typed statement (decision, lesson, belief…) beats a plain fact, explicit
    claim language and concrete detail (numbers, names) add weight, and very
    short or very long spans lose some.
    """
    lowered = text.lower()
    score = 0.0
    if declared_type not in ("fact", "question"):
        score += 2.0
    score += min(len(_CLAIM_SIGNAL.findall(lowered)), 3) * 0.75
    if re.search(r"\d", text):
        score += 0.5
    # Capitalised words after the first suggest names, products or places.
    if any(word[:1].isupper() for word in text.split()[1:]):
        score += 0.5
    length = len(text)
    if 60 <= length <= 320:
        score += 1.0
    elif length < 45:
        score -= 0.5
    return score


def statement_key(text: str) -> str:
    """Normalised form used to spot the same statement captured twice."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


_NEGATION = re.compile(r"\b(?:not|never|no|cannot|can't|won't|don't|doesn't|isn't|shouldn't)\b")


def statement_terms(text: str) -> frozenset[str]:
    """Significant terms for near-duplicate comparison.

    Negation is kept as a marker term. "X should not Y" is a contradiction of
    "X should Y", which a reviewer must see, so the two can never be treated as
    duplicates of each other.
    """
    lowered = text.lower()
    terms = {
        word
        for word in re.findall(r"[a-z0-9]+", lowered)
        if len(word) > 2 and word not in _STOPWORDS
    }
    if _NEGATION.search(lowered):
        terms.add("<negated>")
    return frozenset(terms)


def is_near_duplicate(left: frozenset[str], right: frozenset[str], threshold: float = 0.85) -> bool:
    """Jaccard overlap of significant terms at or above `threshold`."""
    if not left or not right:
        return False
    # Opposite polarity is a possible contradiction, never a duplicate.
    if ("<negated>" in left) != ("<negated>" in right):
        return False
    smaller, larger = sorted((len(left), len(right)))
    # Cheap bound: sets this different in size cannot reach the threshold.
    if smaller / larger < threshold:
        return False
    return len(left & right) / len(left | right) >= threshold
