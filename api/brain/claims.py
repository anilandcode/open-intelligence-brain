"""Model-based claim extraction and relation labelling for intake.

Two jobs, both proposal-side only:

- `extract_claims` asks the optional chat model (`llm.py`) for short,
  self-contained claims, each with a quote copied from the source. A claim
  whose quote cannot be found verbatim in the immutable source version is
  dropped: evidence must point at exact bytes, so a paraphrased or invented
  quote is treated as no evidence at all.
- `relate_to_canon` labels a candidate against approved knowledge as `new`,
  `update` (same subject, changed content) or `contradiction` (same subject,
  opposite polarity), and names the item it would change. Approving an update
  revises that item with the new evidence instead of adding a near-copy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .entities import EntityRef, clean_refs
from .extraction import is_near_duplicate, statement_terms
from .llm import get_chat_model
from .models import Knowledge

log = logging.getLogger(__name__)

CLAIM_TYPES = (
    "fact",
    "decision",
    "belief",
    "lesson",
    "thesis",
    "framework",
    "evidence",
    "story",
    "question",
)

SYSTEM_PROMPT = """You extract durable knowledge from a person's notes for their \
personal knowledge base. A human reviews every claim before it is kept.

Return JSON only: {"claims": [{"statement": str, "type": str, "quote": str, \
"confidence": number, "entities": [{"name": str, "kind": str}]}]}

Rules:
- One idea per claim. Write the statement so it stands alone: name the subject, \
resolve "we", "it", "this" and relative dates where the passage makes them clear.
- Keep the author's meaning. Do not add facts that are not in the passage.
- "quote" must be copied character for character from the passage: the shortest \
contiguous text that supports the claim, at most 300 characters.
- "type" is one of: fact, decision, belief, lesson, thesis, framework, evidence, story, question.
- "confidence" is 0 to 1: how clearly the passage states the claim.
- "entities" lists the specific people, companies, projects and named topics the \
claim is about, each with "kind" one of: person, company, project, topic. Use the \
fullest name the passage gives. Leave it empty when the claim names none.
- Skip headings, to-do items, greetings, boilerplate and anything trivial or temporary.
- Return {"claims": []} when nothing is worth keeping."""


@dataclass(frozen=True)
class Claim:
    statement: str
    type: str
    start: int
    end: int
    confidence: float | None
    entities: tuple[EntityRef, ...] = ()


def windows(content: str, size: int) -> list[tuple[int, str]]:
    """Split content into windows of about `size` chars at paragraph breaks.

    Returns (absolute_start, text) pairs so quotes can be mapped back to exact
    offsets in the source version.
    """
    out: list[tuple[int, str]] = []
    start = 0
    length = len(content)
    while start < length:
        end = min(start + size, length)
        if end < length:
            cut = content.rfind("\n\n", start + size // 2, end)
            if cut == -1:
                cut = content.rfind("\n", start + size // 2, end)
            if cut != -1:
                end = cut
        text = content[start:end]
        if text.strip():
            out.append((start, text))
        start = end
        while start < length and content[start] in "\n\r":
            start += 1
    return out


def locate_quote(window: str, quote: str) -> tuple[int, int] | None:
    """Offsets of `quote` in `window`, exact first, then ignoring case.

    Whitespace is not normalised: the stored span has to equal the source
    bytes it claims to be, and a match that needed rewriting would not.
    """
    quote = quote.strip()
    if len(quote) < 8:
        return None
    index = window.find(quote)
    if index == -1:
        index = window.lower().find(quote.lower())
    if index == -1:
        return None
    return index, index + len(quote)


def _clean_type(value: object, statement: str) -> str:
    from .services import classify_statement  # avoid an import cycle

    kind = str(value or "").strip().lower()
    return kind if kind in CLAIM_TYPES else classify_statement(statement)


def _confidence(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def extract_claims(content: str) -> list[Claim] | None:
    """Claims from the chat model, or None when no model answered.

    None (not an empty list) tells the caller to use the deterministic path,
    so a model outage never empties the review queue. An empty list means the
    model read the source and found nothing worth keeping.
    """
    model = get_chat_model()
    if model is None:
        return None
    settings = get_settings()
    claims: list[Claim] = []
    answered = False
    for offset, text in windows(content, settings.llm_window_chars)[: settings.llm_max_windows]:
        reply = model.complete_json(SYSTEM_PROMPT, f"Passage:\n\n{text}")
        if not isinstance(reply, dict) or not isinstance(reply.get("claims"), list):
            continue
        answered = True
        for raw in reply["claims"]:
            if not isinstance(raw, dict):
                continue
            statement = re.sub(r"\s+", " ", str(raw.get("statement", ""))).strip()
            if not 12 <= len(statement) <= 1_000:
                continue
            located = locate_quote(text, str(raw.get("quote", "")))
            if located is None:
                log.info("dropped a model claim whose quote is not in the source")
                continue
            claims.append(
                Claim(
                    statement=statement,
                    type=_clean_type(raw.get("type"), statement),
                    start=offset + located[0],
                    end=offset + located[1],
                    confidence=_confidence(raw.get("confidence")),
                    entities=tuple(clean_refs(raw.get("entities"))),
                )
            )
    return claims if answered else None


# --- relation to approved knowledge -------------------------------------------

RELATED_THRESHOLD = 0.5


def term_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    left_terms = left - {"<negated>"}
    right_terms = right - {"<negated>"}
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


class CanonIndex:
    """Approved knowledge of one workspace, for labelling new candidates."""

    def __init__(self, items: list[Knowledge]) -> None:
        self.items = [(item, statement_terms(item.statement)) for item in items]

    @classmethod
    def load(cls, db: Session, workspace_id: str) -> CanonIndex:
        rows = db.scalars(
            select(Knowledge).where(
                Knowledge.workspace_id == workspace_id, Knowledge.status == "canonical"
            )
        ).all()
        return cls(list(rows))

    def relate(self, statement: str) -> tuple[str, str | None]:
        """("new", None), ("update", id) or ("contradiction", id)."""
        terms = statement_terms(statement)
        best: tuple[float, Knowledge, frozenset[str]] | None = None
        for item, item_terms in self.items:
            if is_near_duplicate(terms, item_terms):
                # Same statement: intake de-duplication already drops these.
                continue
            score = term_overlap(terms, item_terms)
            if score >= RELATED_THRESHOLD and (best is None or score > best[0]):
                best = (score, item, item_terms)
        if best is None:
            return "new", None
        _, item, item_terms = best
        opposite = ("<negated>" in terms) != ("<negated>" in item_terms)
        return ("contradiction" if opposite else "update"), item.id
