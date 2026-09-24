import re
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceSpan,
    SourceVersion,
    new_id,
)
from .schemas import ChatResponse, Citation, SourceCreate


def content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def extract_spans(content: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", content):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        text = raw.strip()
        if not text:
            continue
        start = match.start() + leading
        spans.append((start, start + len(text), text))
    return spans


def audit(db: Session, action: str, resource_type: str, resource_id: str, detail: str = ""):
    db.add(
        AuditEvent(
            id=new_id("evt"),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )


def classify_statement(statement: str) -> str:
    lowered = statement.lower()
    if any(word in lowered for word in ("believe", "should", "prefer", "matters")):
        return "belief"
    if any(word in lowered for word in ("learned", "lesson", "realized")):
        return "lesson"
    if any(word in lowered for word in ("because", "therefore", "means that")):
        return "thesis"
    if any(word in lowered for word in ("decided", "decision", "chose")):
        return "decision"
    return "fact"


def extract_candidates(content: str) -> list[tuple[str, str]]:
    candidates = [
        re.sub(r"\s+", " ", text) for _, _, text in extract_spans(content) if 35 <= len(text) <= 600
    ]
    unique = list(dict.fromkeys(candidates))
    return [(classify_statement(text), text) for text in unique[:8]]


def add_source_version(
    db: Session,
    source: Source,
    content: str,
    change_note: str,
    *,
    create_proposals: bool = True,
) -> SourceVersion:
    digest = content_hash(content)
    existing = db.scalar(
        select(SourceVersion).where(
            SourceVersion.source_id == source.id,
            SourceVersion.content_hash == digest,
        )
    )
    if existing is not None:
        raise ValueError("This exact source content already exists")
    latest_number = (
        db.scalar(
            select(func.max(SourceVersion.version)).where(SourceVersion.source_id == source.id)
        )
        or 0
    )
    version = SourceVersion(
        id=new_id("srcv"),
        source_id=source.id,
        version=latest_number + 1,
        content_hash=digest,
        content=content,
        change_note=change_note,
    )
    db.add(version)
    db.flush()
    for start, end, text in extract_spans(content):
        span = SourceSpan(
            id=new_id("span"),
            source_version_id=version.id,
            start_offset=start,
            end_offset=end,
            text=text,
            span_hash=content_hash(text),
        )
        db.add(span)
        db.flush()
        if create_proposals and 35 <= len(text) <= 600:
            statement = re.sub(r"\s+", " ", text)
            proposal = Proposal(
                id=new_id("prop"),
                source_id=source.id,
                type=classify_statement(statement),
                statement=statement,
                rationale=(
                    "Candidate extracted from an immutable source span. "
                    "Review wording and evidence before approval."
                ),
                source_excerpt=text,
            )
            db.add(proposal)
            db.flush()
            db.add(
                ProposalEvidence(
                    proposal_id=proposal.id,
                    source_version_id=version.id,
                    source_span_id=span.id,
                )
            )
    audit(
        db,
        "source.versioned",
        "source",
        source.id,
        f"Created source version {version.version}: {change_note}",
    )
    return version


def create_source_with_proposals(db: Session, payload: SourceCreate) -> Source:
    source = Source(id=new_id("src"), **payload.model_dump())
    db.add(source)
    db.flush()
    add_source_version(db, source, payload.content, "Initial capture")
    audit(db, "source.ingested", "source", source.id, f"Imported {source.title}")
    db.commit()
    db.refresh(source)
    return source


def approve_proposal(
    db: Session, proposal: Proposal, statement: str | None, rationale: str | None
) -> Knowledge:
    if proposal.status != "proposed":
        raise ValueError("Only proposed knowledge can be approved")
    canonical = Knowledge(
        id=new_id("know"),
        proposal_id=proposal.id,
        source_id=proposal.source_id,
        type=proposal.type,
        statement=statement or proposal.statement,
        rationale=rationale if rationale is not None else proposal.rationale,
        source_excerpt=proposal.source_excerpt,
    )
    proposal.status = "approved"
    db.add(canonical)
    db.flush()
    evidence = db.get(ProposalEvidence, proposal.id)
    if evidence is None:
        raise ValueError("Proposal has no immutable source evidence")
    db.add(
        KnowledgeRevision(
            id=new_id("rev"),
            knowledge_id=canonical.id,
            revision=1,
            statement=canonical.statement,
            rationale=canonical.rationale,
            source_id=canonical.source_id,
            source_version_id=evidence.source_version_id,
            source_span_id=evidence.source_span_id,
            source_excerpt=canonical.source_excerpt,
            change_note="Initial approval",
        )
    )
    audit(db, "knowledge.approved", "knowledge", canonical.id, f"Approved {proposal.id}")
    db.commit()
    db.refresh(canonical)
    return canonical


def supersede_knowledge(
    db: Session,
    item: Knowledge,
    statement: str,
    rationale: str,
    change_note: str,
) -> Knowledge:
    current = db.scalar(
        select(KnowledgeRevision)
        .where(KnowledgeRevision.knowledge_id == item.id)
        .order_by(KnowledgeRevision.revision.desc())
    )
    if current is None:
        raise ValueError("Knowledge item has no revision provenance")
    revision = current.revision + 1
    db.add(
        KnowledgeRevision(
            id=new_id("rev"),
            knowledge_id=item.id,
            revision=revision,
            statement=statement,
            rationale=rationale,
            source_id=item.source_id,
            source_version_id=current.source_version_id,
            source_span_id=current.source_span_id,
            source_excerpt=current.source_excerpt,
            change_note=change_note,
        )
    )
    item.statement = statement
    item.rationale = rationale
    item.version = revision
    audit(db, "knowledge.superseded", "knowledge", item.id, f"Created revision {revision}")
    db.commit()
    db.refresh(item)
    return item


def backfill_provenance(db: Session) -> None:
    changed = False
    for source in db.scalars(select(Source)).all():
        version = db.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source.id)
            .order_by(SourceVersion.version.desc())
        )
        if version is None:
            version = add_source_version(
                db,
                source,
                source.content,
                "Backfilled from pre-M2 source",
                create_proposals=False,
            )
            changed = True
        spans = list(
            db.scalars(select(SourceSpan).where(SourceSpan.source_version_id == version.id)).all()
        )
        for proposal in source.proposals:
            if db.get(ProposalEvidence, proposal.id) is not None:
                continue
            span = next(
                (candidate for candidate in spans if candidate.text == proposal.source_excerpt),
                None,
            )
            if span is None:
                span = SourceSpan(
                    id=new_id("span"),
                    source_version_id=version.id,
                    start_offset=max(source.content.find(proposal.source_excerpt), 0),
                    end_offset=max(source.content.find(proposal.source_excerpt), 0)
                    + len(proposal.source_excerpt),
                    text=proposal.source_excerpt,
                    span_hash=content_hash(proposal.source_excerpt),
                )
                db.add(span)
                db.flush()
            db.add(
                ProposalEvidence(
                    proposal_id=proposal.id,
                    source_version_id=version.id,
                    source_span_id=span.id,
                )
            )
            changed = True
    for item in db.scalars(select(Knowledge)).all():
        exists = db.scalar(
            select(KnowledgeRevision.id).where(KnowledgeRevision.knowledge_id == item.id)
        )
        if exists is not None:
            continue
        evidence = db.get(ProposalEvidence, item.proposal_id)
        if evidence is None:
            continue
        db.add(
            KnowledgeRevision(
                id=new_id("rev"),
                knowledge_id=item.id,
                revision=item.version,
                statement=item.statement,
                rationale=item.rationale,
                source_id=item.source_id,
                source_version_id=evidence.source_version_id,
                source_span_id=evidence.source_span_id,
                source_excerpt=item.source_excerpt,
                change_note="Backfilled from pre-M2 knowledge",
                approved_at=item.approved_at,
            )
        )
        changed = True
    if changed:
        db.commit()


def _query_terms(query: str) -> list[str]:
    stop = {
        "what",
        "when",
        "where",
        "which",
        "that",
        "this",
        "with",
        "from",
        "your",
        "about",
        "does",
        "have",
        "into",
        "how",
        "the",
        "and",
        "are",
        "our",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in stop
    ]


def search_knowledge(db: Session, query: str, limit: int = 20) -> list[Knowledge]:
    terms = _query_terms(query)
    stmt = select(Knowledge).where(Knowledge.status == "canonical")
    if terms:
        filters = []
        for term in terms:
            pattern = f"%{term}%"
            filters.extend([Knowledge.statement.ilike(pattern), Knowledge.rationale.ilike(pattern)])
        stmt = stmt.where(or_(*filters))
    candidates = list(db.scalars(stmt.limit(max(limit * 3, 20))).all())
    if not terms:
        return candidates[:limit]
    scored = []
    for item in candidates:
        words = Counter(re.findall(r"[a-z0-9]+", f"{item.statement} {item.rationale}".lower()))
        scored.append((sum(words[term] for term in terms), item.approved_at, item))
    return [
        item
        for _, _, item in sorted(scored, key=lambda row: (row[0], row[1]), reverse=True)[:limit]
    ]


def latest_source_version(db: Session, source_id: str) -> SourceVersion | None:
    return db.scalar(
        select(SourceVersion)
        .where(SourceVersion.source_id == source_id)
        .order_by(SourceVersion.version.desc())
    )


def knowledge_revision_count(db: Session, knowledge_id: str) -> int:
    return (
        db.scalar(
            select(func.count(KnowledgeRevision.id)).where(
                KnowledgeRevision.knowledge_id == knowledge_id
            )
        )
        or 0
    )


def knowledge_is_stale(db: Session, item: Knowledge) -> bool:
    current_revision = db.scalar(
        select(KnowledgeRevision)
        .where(KnowledgeRevision.knowledge_id == item.id)
        .order_by(KnowledgeRevision.revision.desc())
    )
    latest = latest_source_version(db, item.source_id)
    return bool(current_revision and latest and current_revision.source_version_id != latest.id)


def _conflict_key(statement: str) -> tuple[set[str], bool]:
    lowered = statement.lower().replace("cannot", "can not")
    negative = bool(re.search(r"\b(?:not|never|no)\b", lowered))
    ignored = {
        "a",
        "an",
        "and",
        "are",
        "be",
        "is",
        "not",
        "no",
        "never",
        "our",
        "should",
        "the",
        "to",
        "we",
    }
    terms = {
        term for term in re.findall(r"[a-z0-9]+", lowered) if len(term) > 2 and term not in ignored
    }
    return terms, negative


def conflict_map(items: list[Knowledge]) -> dict[str, list[str]]:
    conflicts: dict[str, list[str]] = {item.id: [] for item in items}
    keyed = {item.id: _conflict_key(item.statement) for item in items}
    for index, left in enumerate(items):
        left_terms, left_negative = keyed[left.id]
        for right in items[index + 1 :]:
            right_terms, right_negative = keyed[right.id]
            if left_negative == right_negative or not left_terms or not right_terms:
                continue
            overlap = len(left_terms & right_terms) / max(len(left_terms | right_terms), 1)
            if overlap >= 0.55:
                conflicts[left.id].append(right.id)
                conflicts[right.id].append(left.id)
    return conflicts


def integrity_snapshot(db: Session) -> dict:
    items = list(
        db.scalars(
            select(Knowledge).where(Knowledge.status == "canonical").order_by(Knowledge.approved_at)
        ).all()
    )
    conflicts = conflict_map(items)
    issues = []
    for item in items:
        if knowledge_is_stale(db, item):
            issues.append(
                {
                    "kind": "stale_source",
                    "knowledge_id": item.id,
                    "related_id": item.source_id,
                    "detail": "The source has a newer immutable version; review this knowledge again.",
                }
            )
        for related_id in conflicts[item.id]:
            if item.id < related_id:
                issues.append(
                    {
                        "kind": "possible_conflict",
                        "knowledge_id": item.id,
                        "related_id": related_id,
                        "detail": "These approved statements use highly similar terms with opposite polarity.",
                    }
                )
    return {
        "stale_count": sum(issue["kind"] == "stale_source" for issue in issues),
        "conflict_count": sum(issue["kind"] == "possible_conflict" for issue in issues),
        "issues": issues,
    }


def answer_question(db: Session, question: str) -> ChatResponse:
    matches = search_knowledge(db, question, limit=3)
    if not matches:
        return ChatResponse(
            answer="I could not find enough approved knowledge to answer that. Import a source or review the pending proposals first.",
            citations=[],
            grounded=False,
        )
    source_ids = {item.source_id for item in matches}
    sources = {
        item.id: item for item in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }
    statements = " ".join(item.statement.rstrip(".") + "." for item in matches)
    citations = [
        Citation(
            knowledge_id=item.id,
            source_id=item.source_id,
            source_title=sources[item.source_id].title,
            excerpt=item.source_excerpt,
        )
        for item in matches
    ]
    return ChatResponse(answer=statements, citations=citations, grounded=True)


def seed_demo(db: Session) -> None:
    if db.scalar(select(func.count(Source.id))) > 0:
        return
    samples = [
        SourceCreate(
            title="Founder interview — proprietary context",
            kind="interview",
            sensitivity="internal",
            content=(
                "We believe AI output becomes valuable when it is grounded in ideas the company has actually earned through experience. "
                "The Brain should preserve evidence and disagreement rather than flatten every comment into a single truth.\n\n"
                "I learned that asking for more content is usually the wrong starting point. The stronger question is what the company knows that its competitors cannot copy from the public internet."
            ),
        ),
        SourceCreate(
            title="Architecture decision — approval boundary",
            kind="decision",
            sensitivity="public",
            content=(
                "We decided that extracted statements remain proposals until a person approves the exact wording. "
                "Model confidence cannot grant authority because a valid data shape can still contain a wrong judgment.\n\n"
                "Every canonical item must link back to its original source excerpt so a reviewer can inspect why the system believes it."
            ),
        ),
        SourceCreate(
            title="Personal workflow notes",
            kind="note",
            sensitivity="private",
            content=(
                "A useful weekly workflow captures one project lesson, reviews unresolved proposals, and reuses one approved idea in two different outputs. "
                "The system should reduce the time spent reconstructing past reasoning without publishing anything automatically."
            ),
        ),
    ]
    for payload in samples:
        create_source_with_proposals(db, payload)

    proposals = list(db.scalars(select(Proposal).order_by(Proposal.created_at).limit(5)).all())
    for proposal in proposals:
        approve_proposal(db, proposal, None, None)


def overview(db: Session) -> dict:
    events = list(
        db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(6)).all()
    )
    return {
        "sources": db.scalar(select(func.count(Source.id))) or 0,
        "proposals": db.scalar(select(func.count(Proposal.id))) or 0,
        "canonical": db.scalar(select(func.count(Knowledge.id))) or 0,
        "pending_reviews": db.scalar(
            select(func.count(Proposal.id)).where(Proposal.status == "proposed")
        )
        or 0,
        "recent_activity": [
            {
                "id": event.id,
                "action": event.action,
                "detail": event.detail,
                "created_at": event.created_at.astimezone(UTC).isoformat(),
            }
            for event in events
        ],
    }


def export_workspace_data(db: Session) -> dict:
    sources = list(db.scalars(select(Source).order_by(Source.created_at)).all())
    versions = list(
        db.scalars(
            select(SourceVersion).order_by(SourceVersion.source_id, SourceVersion.version)
        ).all()
    )
    spans = list(
        db.scalars(
            select(SourceSpan).order_by(SourceSpan.source_version_id, SourceSpan.start_offset)
        ).all()
    )
    proposals = list(db.scalars(select(Proposal).order_by(Proposal.created_at)).all())
    evidence = list(
        db.scalars(select(ProposalEvidence).order_by(ProposalEvidence.proposal_id)).all()
    )
    knowledge = list(db.scalars(select(Knowledge).order_by(Knowledge.approved_at)).all())
    revisions = list(
        db.scalars(
            select(KnowledgeRevision).order_by(
                KnowledgeRevision.knowledge_id, KnowledgeRevision.revision
            )
        ).all()
    )
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all())

    def timestamp(value: datetime) -> str:
        return value.isoformat()

    return {
        "schema_version": 2,
        "exported_from": "open-intelligence-brain",
        "sources": [
            {
                "id": row.id,
                "title": row.title,
                "kind": row.kind,
                "sensitivity": row.sensitivity,
                "content": row.content,
                "created_at": timestamp(row.created_at),
            }
            for row in sources
        ],
        "source_versions": [
            {
                "id": row.id,
                "source_id": row.source_id,
                "version": row.version,
                "content_hash": row.content_hash,
                "content": row.content,
                "parser_version": row.parser_version,
                "change_note": row.change_note,
                "created_at": timestamp(row.created_at),
            }
            for row in versions
        ],
        "source_spans": [
            {
                "id": row.id,
                "source_version_id": row.source_version_id,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "text": row.text,
                "span_hash": row.span_hash,
                "speaker": row.speaker,
            }
            for row in spans
        ],
        "proposals": [
            {
                "id": row.id,
                "source_id": row.source_id,
                "type": row.type,
                "statement": row.statement,
                "rationale": row.rationale,
                "source_excerpt": row.source_excerpt,
                "status": row.status,
                "created_at": timestamp(row.created_at),
            }
            for row in proposals
        ],
        "proposal_evidence": [
            {
                "proposal_id": row.proposal_id,
                "source_version_id": row.source_version_id,
                "source_span_id": row.source_span_id,
            }
            for row in evidence
        ],
        "knowledge": [
            {
                "id": row.id,
                "proposal_id": row.proposal_id,
                "source_id": row.source_id,
                "type": row.type,
                "statement": row.statement,
                "rationale": row.rationale,
                "source_excerpt": row.source_excerpt,
                "status": row.status,
                "version": row.version,
                "approved_at": timestamp(row.approved_at),
            }
            for row in knowledge
        ],
        "knowledge_revisions": [
            {
                "id": row.id,
                "knowledge_id": row.knowledge_id,
                "revision": row.revision,
                "statement": row.statement,
                "rationale": row.rationale,
                "source_id": row.source_id,
                "source_version_id": row.source_version_id,
                "source_span_id": row.source_span_id,
                "source_excerpt": row.source_excerpt,
                "change_note": row.change_note,
                "approved_at": timestamp(row.approved_at),
            }
            for row in revisions
        ],
        "audit_events": [
            {
                "id": row.id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "detail": row.detail,
                "created_at": timestamp(row.created_at),
            }
            for row in events
        ],
    }


def restore_preview(db: Session, backup: dict) -> dict:
    required = {
        "sources",
        "source_versions",
        "source_spans",
        "proposals",
        "proposal_evidence",
        "knowledge",
        "knowledge_revisions",
        "audit_events",
    }
    schema_version = backup.get("schema_version", 0)
    blockers = []
    if schema_version != 2:
        blockers.append("Only schema version 2 backups can be restored")
    missing = sorted(required - backup.keys())
    if missing:
        blockers.append(f"Missing collections: {', '.join(missing)}")
    empty_workspace = all(
        (db.scalar(select(func.count(model.id))) or 0) == 0
        for model in (Source, Proposal, Knowledge, AuditEvent)
    )
    if not empty_workspace:
        blockers.append("Restore requires an empty workspace; existing data is never overwritten")
    counts = {
        key: len(backup.get(key, []))
        for key in sorted(required)
        if isinstance(backup.get(key, []), list)
    }
    return {
        "schema_version": schema_version,
        "valid": not blockers,
        "empty_workspace": empty_workspace,
        "counts": counts,
        "blockers": blockers,
    }


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def restore_workspace(db: Session, backup: dict) -> dict:
    preview = restore_preview(db, backup)
    if not preview["valid"]:
        raise ValueError("; ".join(preview["blockers"]))
    for row in backup["sources"]:
        db.add(
            Source(
                id=row["id"],
                title=row["title"],
                kind=row["kind"],
                sensitivity=row["sensitivity"],
                content=row["content"],
                created_at=_parse_timestamp(row["created_at"]),
            )
        )
    db.flush()
    for row in backup["source_versions"]:
        db.add(
            SourceVersion(
                id=row["id"],
                source_id=row["source_id"],
                version=row["version"],
                content_hash=row["content_hash"],
                content=row["content"],
                parser_version=row["parser_version"],
                change_note=row["change_note"],
                created_at=_parse_timestamp(row["created_at"]),
            )
        )
    db.flush()
    for row in backup["source_spans"]:
        db.add(SourceSpan(**row))
    db.flush()
    for row in backup["proposals"]:
        db.add(
            Proposal(
                **{key: value for key, value in row.items() if key != "created_at"},
                created_at=_parse_timestamp(row["created_at"]),
            )
        )
    db.flush()
    for row in backup["proposal_evidence"]:
        db.add(ProposalEvidence(**row))
    db.flush()
    for row in backup["knowledge"]:
        db.add(
            Knowledge(
                **{key: value for key, value in row.items() if key != "approved_at"},
                approved_at=_parse_timestamp(row["approved_at"]),
            )
        )
    db.flush()
    for row in backup["knowledge_revisions"]:
        db.add(
            KnowledgeRevision(
                **{key: value for key, value in row.items() if key != "approved_at"},
                approved_at=_parse_timestamp(row["approved_at"]),
            )
        )
    db.flush()
    for row in backup["audit_events"]:
        db.add(
            AuditEvent(
                **{key: value for key, value in row.items() if key != "created_at"},
                created_at=_parse_timestamp(row["created_at"]),
            )
        )
    db.commit()
    return preview
