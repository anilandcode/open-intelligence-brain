"""Agent working memory: a scratchpad, and a search over unreviewed sources.

Agents need somewhere to keep notes between steps of a task, and sometimes
need to look in material nobody has reviewed yet. Both are kept visibly apart
from approved knowledge:

- A scratchpad note belongs to the credential that wrote it, expires on its
  own (``BRAIN_SCRATCHPAD_DEFAULT_DAYS``, at most ``..._MAX_DAYS``) and is
  never searched, cited or answered from. ``promote_note`` files it as an
  ordinary source, so its claims reach the review queue like any capture.
- ``search_sources`` finds sentences in the latest version of readable
  sources and labels each hit "unreviewed", or "approved" with the item id
  when an approved item rests on that sentence. Hits are evidence to check,
  not answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .access import ReadScope, WorkspaceAccess
from .config import get_settings
from .extraction import statement_terms
from .models import (
    AgentNote,
    Knowledge,
    KnowledgeRevision,
    Source,
    SourceSpan,
    SourceVersion,
    new_id,
)
from .schemas import SourceCreate
from .services import audit, aware_utc, create_source_with_proposals

MAX_QUERY_TERMS = 8
MAX_CANDIDATES = 400


class ScratchpadError(ValueError):
    """A scratchpad request that cannot be done (full, too short, already promoted)."""


def purge_expired(db: Session, workspace_id: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    result = db.execute(
        delete(AgentNote).where(AgentNote.workspace_id == workspace_id, AgentNote.expires_at <= now)
    )
    db.commit()
    return result.rowcount or 0


def write_note(
    db: Session,
    workspace_id: str,
    author: str,
    content: str,
    *,
    topic: str = "",
    days: int | None = None,
    sensitivity: str = "private",
    now: datetime | None = None,
) -> AgentNote:
    now = now or datetime.now(UTC)
    settings = get_settings()
    purge_expired(db, workspace_id, now)
    live = db.scalar(
        select(func.count(AgentNote.id)).where(
            AgentNote.workspace_id == workspace_id, AgentNote.author == author
        )
    )
    if (live or 0) >= settings.scratchpad_max_notes:
        raise ScratchpadError(
            f"The scratchpad holds at most {settings.scratchpad_max_notes} notes per agent; "
            "delete or promote some first"
        )
    lifetime = min(max(days or settings.scratchpad_default_days, 1), settings.scratchpad_max_days)
    note = AgentNote(
        id=new_id("note"),
        workspace_id=workspace_id,
        author=author,
        topic=topic.strip()[:160],
        content=content.strip(),
        sensitivity=sensitivity,
        created_at=now,
        expires_at=now + timedelta(days=lifetime),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def list_notes(
    db: Session,
    scope: ReadScope,
    *,
    author: str | None,
    topic: str = "",
    limit: int = 50,
    now: datetime | None = None,
) -> list[AgentNote]:
    """Live notes, newest first. `author=None` lists every author's (the console)."""
    purge_expired(db, scope.workspace_id, now)
    stmt = select(AgentNote).where(
        AgentNote.workspace_id == scope.workspace_id,
        AgentNote.sensitivity.in_(scope.permitted),
    )
    if author is not None:
        stmt = stmt.where(AgentNote.author == author)
    if topic.strip():
        stmt = stmt.where(AgentNote.topic == topic.strip())
    return list(db.scalars(stmt.order_by(AgentNote.created_at.desc()).limit(limit)))


def readable_note(db: Session, scope: ReadScope, note_id: str, author: str | None) -> AgentNote:
    note = db.get(AgentNote, note_id)
    if (
        note is None
        or note.workspace_id != scope.workspace_id
        or not scope.may_read(note.sensitivity)
        or (author is not None and note.author != author)
        or aware_utc(note.expires_at) <= datetime.now(UTC)
    ):
        raise LookupError("Note not found")
    return note


def promote_note(
    db: Session, note: AgentNote, *, title: str = "", actor: WorkspaceAccess | None = None
) -> Source:
    """File the note as a source for review. The note stays until it expires."""
    if note.promoted_source_id:
        raise ScratchpadError("This note was already promoted")
    if len(note.content) < 20:
        raise ScratchpadError("Too short to promote: a source needs at least 20 characters")
    name = title.strip() or (
        f"Agent note: {note.topic}" if note.topic else f"Agent note: {note.content[:60]}"
    )
    if len(name) < 3:
        name = "Agent note"
    source = create_source_with_proposals(
        db,
        SourceCreate(
            title=name[:240], kind="note", sensitivity=note.sensitivity, content=note.content
        ),
        note.workspace_id,
        actor=actor,
    )
    note.promoted_source_id = source.id
    note.promoted_at = datetime.now(UTC)
    audit(
        db,
        note.workspace_id,
        "scratchpad.promoted",
        "agent_note",
        note.id,
        f"Promoted to source {source.id}",
        actor=actor,
    )
    db.commit()
    return source


@dataclass
class SourceHit:
    source_id: str
    source_title: str
    source_kind: str
    version: int
    excerpt: str
    speaker: str | None
    status: str  # "unreviewed" or "approved"
    knowledge_id: str | None
    score: float


def search_sources(db: Session, scope: ReadScope, query: str, limit: int = 10) -> list[SourceHit]:
    """Sentences from the latest version of each readable source that match the query."""
    terms = sorted(t for t in statement_terms(query) if not t.startswith("<"))
    terms = sorted(terms, key=len, reverse=True)[:MAX_QUERY_TERMS]
    if not terms:
        return []
    latest = (
        select(SourceVersion.source_id, func.max(SourceVersion.version).label("version"))
        .group_by(SourceVersion.source_id)
        .subquery()
    )
    stmt = (
        select(SourceSpan, SourceVersion.version, Source)
        .join(SourceVersion, SourceSpan.source_version_id == SourceVersion.id)
        .join(
            latest,
            (latest.c.source_id == SourceVersion.source_id)
            & (latest.c.version == SourceVersion.version),
        )
        .join(Source, Source.id == SourceVersion.source_id)
        .where(or_(*(func.lower(SourceSpan.text).like(f"%{term}%") for term in terms)))
        .limit(MAX_CANDIDATES)
    )
    rows = db.execute(scope.apply(stmt, Source)).all()
    scored: list[tuple[float, SourceSpan, int, Source]] = []
    for span, version, source in rows:
        span_terms = statement_terms(span.text)
        hits = sum(1 for term in terms if term in span_terms)
        if not hits:
            continue
        scored.append((hits / len(terms), span, version, source))
    scored.sort(key=lambda row: (-row[0], len(row[1].text)))
    scored = scored[:limit]
    approved = _approved_by_hash(db, scope, {row[1].span_hash for row in scored})
    return [
        SourceHit(
            source_id=source.id,
            source_title=source.title,
            source_kind=source.kind,
            version=version,
            excerpt=span.text,
            speaker=span.speaker,
            status="approved" if span.span_hash in approved else "unreviewed",
            knowledge_id=approved.get(span.span_hash),
            score=round(score, 3),
        )
        for score, span, version, source in scored
    ]


def _approved_by_hash(db: Session, scope: ReadScope, hashes: set[str]) -> dict[str, str]:
    """span hash -> id of a readable approved item whose current evidence has that text."""
    if not hashes:
        return {}
    rows = db.execute(
        scope.apply(
            select(SourceSpan.span_hash, Knowledge.id)
            .join(KnowledgeRevision, KnowledgeRevision.source_span_id == SourceSpan.id)
            .join(Knowledge, Knowledge.id == KnowledgeRevision.knowledge_id)
            .where(
                SourceSpan.span_hash.in_(hashes),
                Knowledge.status == "canonical",
                KnowledgeRevision.revision == Knowledge.version,
            ),
            Knowledge,
        )
    ).all()
    return {span_hash: knowledge_id for span_hash, knowledge_id in rows}
