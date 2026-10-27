"""Written answers: a model phrases the answer, a check keeps it honest.

`answer_question` decides *whether* the approved brain answers a question
(and abstains otherwise). When a chat model is configured, this module turns
the matching items into a short written answer in which every sentence cites
the items it relies on. The model's text is never trusted on its own:

- a sentence must cite at least one of the items it was given;
- most of its content words must appear in the items it cites;
- every number in it must appear in the items it cites.

A sentence that fails any check is dropped and counted. If nothing survives,
the caller falls back to quoting the approved statements, so a model outage or
a bad answer can only make the answer plainer, never less grounded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .config import get_settings
from .llm import get_chat_model
from .models import Knowledge

log = logging.getLogger(__name__)

WRITER_PROMPT = """You answer questions for a person using only their approved \
knowledge base. You are given a question and numbered approved items, each with an id.

Return JSON only: {"sentences": [{"text": str, "cites": [str]}]}

Rules:
- Use only what the items say. Do not add facts, numbers, names or advice they do not contain.
- Each sentence lists in "cites" the ids of the items it relies on.
- Answer in at most 4 short sentences, plain and direct.
- If the items do not answer the question, return {"sentences": []}."""

# Words that carry no claim: they may appear in an answer without support.
_FILLER = frozenset(
    "a an and are as at be been but by can could do does for from had has have he her his "
    "how i if in into is it its may might more most must no not of on or our over per she "
    "should so such than that the their them then there these they this those to under up "
    "us was we were what when where which while who why will with would you your also both "
    "each other only same yes about after before because between during including all any "
    "every many much some very according item items approved knowledge says say said".split()
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SUPPORT_FLOOR = 0.6


@dataclass(frozen=True)
class WrittenSentence:
    text: str
    knowledge_ids: tuple[str, ...]


@dataclass(frozen=True)
class WrittenAnswer:
    sentences: list[WrittenSentence]
    dropped: int


def _stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word.rstrip("s") or word


def _content_terms(text: str) -> set[str]:
    return {
        _stem(word)
        for word in re.findall(r"[a-z][a-z0-9'-]*", text.lower())
        if word not in _FILLER and len(word) > 2
    }


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def supported(text: str, cited: list[Knowledge]) -> bool:
    """Whether a sentence can be traced to the items it cites."""
    if not cited:
        return False
    evidence = " ".join(f"{item.statement} {item.rationale}" for item in cited)
    if not _numbers(text) <= _numbers(evidence):
        return False
    terms = _content_terms(text)
    if not terms:
        return False
    known = _content_terms(evidence)
    return len(terms & known) / len(terms) >= SUPPORT_FLOOR


def _clean_text(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # Ids belong in "cites"; strip any the model also wrote into the prose.
    return re.sub(r"\s*\[(?:know_[0-9a-f]+(?:,\s*)?)+\]", "", text).strip()


def write_answer(question: str, items: list[Knowledge]) -> WrittenAnswer | None:
    """A checked, cited answer from `items`, or None to fall back to quoting."""
    settings = get_settings()
    model = get_chat_model()
    if model is None or not items or not settings.llm_write_answers:
        return None
    by_id = {item.id: item for item in items}
    listing = "\n".join(
        f"{index}. [{item.id}] ({item.type}) {item.statement}"
        + (f" Rationale: {item.rationale}" if item.rationale else "")
        for index, item in enumerate(items, start=1)
    )
    reply = model.complete_json(
        WRITER_PROMPT, f"Question: {question}\n\nApproved items:\n{listing}"
    )
    if not isinstance(reply, dict) or not isinstance(reply.get("sentences"), list):
        return None
    kept: list[WrittenSentence] = []
    dropped = 0
    for raw in reply["sentences"][:8]:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        text = _clean_text(raw.get("text"))
        cites = raw.get("cites") if isinstance(raw.get("cites"), list) else []
        ids = tuple(dict.fromkeys(str(cite) for cite in cites if str(cite) in by_id))
        if not text or not supported(text, [by_id[i] for i in ids]):
            dropped += 1
            continue
        kept.append(WrittenSentence(text=text, knowledge_ids=ids))
    if dropped:
        log.info("dropped %d written answer sentence(s) that could not be traced", dropped)
    return WrittenAnswer(sentences=kept, dropped=dropped)
