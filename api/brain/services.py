import re
from collections import Counter
from datetime import UTC

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import AuditEvent, Knowledge, Proposal, Source, new_id
from .schemas import ChatResponse, Citation, SourceCreate


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
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    candidates: list[str] = []
    for paragraph in paragraphs:
        cleaned = re.sub(r"\s+", " ", paragraph)
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        candidates.extend(sentence for sentence in sentences if 35 <= len(sentence) <= 600)
    unique = list(dict.fromkeys(candidates))
    return [(classify_statement(text), text) for text in unique[:8]]


def create_source_with_proposals(db: Session, payload: SourceCreate) -> Source:
    source = Source(id=new_id("src"), **payload.model_dump())
    db.add(source)
    db.flush()
    for knowledge_type, statement in extract_candidates(payload.content):
        db.add(
            Proposal(
                id=new_id("prop"),
                source_id=source.id,
                type=knowledge_type,
                statement=statement,
                rationale="Candidate extracted from the source. Review wording and evidence before approval.",
                source_excerpt=statement,
            )
        )
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
    audit(db, "knowledge.approved", "knowledge", canonical.id, f"Approved {proposal.id}")
    db.commit()
    db.refresh(canonical)
    return canonical


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
