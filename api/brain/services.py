import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .access import ReadScope, WorkspaceAccess, actor_ref, workspace_counts
from .config import get_settings
from .critic import assess_proposal
from .database import SessionLocal
from .embeddings import get_embedder
from .engine import (
    ContainerTagRejected,
    container_tag_for,
    engine_status,
    get_engine,
)
from .extraction import (
    candidate_score,
    extract_tags,
    is_low_value_fragment,
    is_near_duplicate,
    normalize_tags,
    parse_tags,
    statement_key,
    statement_terms,
    summarize,
)
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
from .retrieval import (
    hybrid_search,
    sync_fts_insert,
    sync_fts_update,
)
from .schemas import ChatResponse, Citation, SourceCreate

log = logging.getLogger(__name__)

# The rationale every locally extracted proposal starts with, and the prefix of
# an engine-derived one. Templates, not reasoning: answers ignore them.
_EXTRACTED_RATIONALE = (
    "Candidate extracted from an immutable source span. "
    "Review wording and evidence before approval."
)
_TEMPLATED_RATIONALES = (_EXTRACTED_RATIONALE, "Derived by the ")


class _HasWorkspace(Protocol):
    """A root record that carries a workspace_id column of its own."""

    workspace_id: str


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


def audit(
    db: Session,
    workspace_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: str = "",
    actor: "WorkspaceAccess | None" = None,
):
    """Append one domain event, attributed to whoever caused it.

    `actor` is the resolved caller. Passing None is correct and honest for work
    nobody asked for — engine derivation, startup backfill, a scheduled routine
    — and records `system` rather than inventing a human or crediting a token.
    """
    actor_kind, actor_id = actor_ref(actor)
    db.add(
        AuditEvent(
            id=new_id("evt"),
            workspace_id=workspace_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            actor_kind=actor_kind,
            actor_id=actor_id,
        )
    )


def classify_statement(statement: str) -> str:
    lowered = statement.lower()
    # Check thesis before decision/belief because "because" + "should" is common
    if any(word in lowered for word in ("because", "therefore", "means that")):
        return "thesis"
    if any(word in lowered for word in ("believe", "should", "prefer", "matters")):
        return "belief"
    if any(word in lowered for word in ("learned", "lesson", "realized")):
        return "lesson"
    # "decided" and "decision" — use word boundary to avoid matching "decisions" in evidence sentences
    if re.search(r"\b(?:decided|decision|chose)\b", lowered):
        return "decision"
    if any(
        word in lowered for word in ("framework", "model", "principle", "approach", "methodology")
    ):
        return "framework"
    if any(
        word in lowered
        for word in ("evidence", "data shows", "research shows", "study found", "measured")
    ):
        return "evidence"
    if any(word in lowered for word in ("story", "example", "case", "instance", "scenario")):
        return "story"
    if "?" in lowered or any(
        word in lowered for word in ("how to", "what is", "why do", "when should")
    ):
        return "question"
    return "fact"


def extract_candidates(content: str) -> list[tuple[str, str]]:
    candidates = [
        re.sub(r"\s+", " ", text)
        for _, _, text in extract_spans(content)
        if 35 <= len(text) <= 600 and not is_low_value_fragment(text)
    ]
    unique = list(dict.fromkeys(candidates))
    return [(classify_statement(text), text) for text in unique[:8]]


class KnownStatements:
    """Statements a workspace has already seen, for intake de-duplication.

    Every proposal ever made (pending, approved or rejected) plus the current
    canonical wording. A statement you already approved, already rejected or
    already have waiting is not new information, so offering it again only
    lengthens the queue. Matching is exact after normalisation, or a
    near-duplicate by significant-term overlap.
    """

    def __init__(self, statements: list[str]) -> None:
        self.keys: set[str] = set()
        self.terms: list[frozenset[str]] = []
        for statement in statements:
            self.add(statement)

    @classmethod
    def load(cls, db: Session, workspace_id: str) -> "KnownStatements":
        proposals = db.scalars(
            select(Proposal.statement).where(Proposal.workspace_id == workspace_id)
        ).all()
        canonical = db.scalars(
            select(Knowledge.statement).where(Knowledge.workspace_id == workspace_id)
        ).all()
        return cls([*proposals, *canonical])

    def add(self, statement: str) -> None:
        key = statement_key(statement)
        if key in self.keys:
            return
        self.keys.add(key)
        terms = statement_terms(statement)
        if terms:
            self.terms.append(terms)

    def contains(self, statement: str) -> bool:
        if statement_key(statement) in self.keys:
            return True
        terms = statement_terms(statement)
        return any(is_near_duplicate(terms, other) for other in self.terms)


def add_source_version(
    db: Session,
    source: Source,
    content: str,
    change_note: str,
    *,
    create_proposals: bool = True,
    actor: WorkspaceAccess | None = None,
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
    # Spans the previous version already had. Their text is unchanged, so they
    # were already offered for review once and must not be offered again.
    previous_hashes: set[str] = set()
    if latest_number:
        previous = db.scalar(
            select(SourceVersion).where(
                SourceVersion.source_id == source.id,
                SourceVersion.version == latest_number,
            )
        )
        if previous is not None:
            previous_hashes = set(
                db.scalars(
                    select(SourceSpan.span_hash).where(SourceSpan.source_version_id == previous.id)
                ).all()
            )
    candidates: list[tuple[float, int, SourceSpan, str, str]] = []
    skipped_unchanged = 0
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
        if not create_proposals or not 35 <= len(text) <= 600 or is_low_value_fragment(text):
            continue
        if span.span_hash in previous_hashes:
            skipped_unchanged += 1
            continue
        statement = re.sub(r"\s+", " ", text)
        kind = classify_statement(statement)
        candidates.append(
            (candidate_score(statement, kind), len(candidates), span, statement, kind)
        )
    db.flush()

    known = KnownStatements.load(db, source.workspace_id) if candidates else None
    selected: list[tuple[int, SourceSpan, str, str]] = []
    skipped_duplicate = 0
    for _score, order, span, statement, kind in sorted(
        candidates, key=lambda row: (-row[0], row[1])
    ):
        if known is not None and known.contains(statement):
            skipped_duplicate += 1
            continue
        if known is not None:
            known.add(statement)
        selected.append((order, span, statement, kind))
    cap = get_settings().max_proposals_per_version
    skipped_over_cap = max(len(selected) - cap, 0) if cap > 0 else 0
    if skipped_over_cap:
        selected = selected[:cap]
    # Back into reading order, so the queue follows the source.
    for _, span, statement, kind in sorted(selected, key=lambda row: row[0]):
        proposal = Proposal(
            id=new_id("prop"),
            workspace_id=source.workspace_id,
            source_id=source.id,
            type=kind,
            statement=statement,
            rationale=_EXTRACTED_RATIONALE,
            source_excerpt=span.text,
            summary=summarize(statement),
            tags=json.dumps(extract_tags(statement), ensure_ascii=False),
        )
        db.add(proposal)
        db.flush()
        # Run critic pass
        assessment = assess_proposal(
            proposal_id=proposal.id,
            statement=statement,
            declared_type=proposal.type,
            source_excerpt=span.text,
        )
        if assessment.has_notes:
            proposal.critic_notes = json.dumps(
                [
                    {"severity": n.severity, "category": n.category, "message": n.message}
                    for n in assessment.notes
                ],
                ensure_ascii=False,
            )
        db.add(
            ProposalEvidence(
                proposal_id=proposal.id,
                source_version_id=version.id,
                source_span_id=span.id,
            )
        )
    intake = f"{len(selected)} proposed"
    for count, label in (
        (skipped_unchanged, "unchanged"),
        (skipped_duplicate, "already known"),
        (skipped_over_cap, "over the per-version cap"),
    ):
        if count:
            intake += f", {count} {label}"
    audit(
        db,
        source.workspace_id,
        "source.versioned",
        "source",
        source.id,
        f"Created source version {version.version}: {change_note} ({intake})",
        actor=actor,
    )
    return version


def create_source_with_proposals(
    db: Session, payload: SourceCreate, workspace_id: str, actor: WorkspaceAccess | None = None
) -> Source:
    source = Source(id=new_id("src"), workspace_id=workspace_id, **payload.model_dump())
    db.add(source)
    db.flush()
    add_source_version(db, source, payload.content, "Initial capture", actor=actor)
    audit(
        db,
        workspace_id,
        "source.ingested",
        "source",
        source.id,
        f"Imported {source.title}",
        actor=actor,
    )
    db.commit()
    db.refresh(source)
    offer_to_engine(source)
    return source


def offer_to_engine(source: Source) -> str:
    """Hand captured content to the extraction engine, off the request path.

    Called after the commit, so a slow or unreachable engine delays nothing
    and can never roll back a capture that already succeeded. Returns the
    engine's document id, stored on the source, because that id is the only
    reliable link between the content we captured and the facts the engine
    later derives from it — the container-level `/inferred` list has been
    observed returning empty for documents that did produce inferences.

    A workspace id that cannot be expressed as a container tag is logged and
    skipped rather than raised: the content is already stored, and refusing the
    capture over an engine naming problem would lose the customer's data to
    make our indexing tidier. The capture is the system of record; the engine
    copy is a convenience.
    """
    engine = get_engine()
    if engine.name == "deterministic":
        return ""
    try:
        tag = container_tag_for(source.workspace_id)
    except ContainerTagRejected as exc:
        log.warning("engine ingest skipped: %s", exc)
        return ""
    document_id = engine.ingest(
        content=source.content,
        container_tag=tag,
        metadata={
            "source_id": source.id,
            "title": source.title,
            "sensitivity": source.sensitivity,
            "kind": source.kind,
        },
    )
    if document_id:
        source.engine_document_id = document_id
        db = Session.object_session(source)
        if db is not None:
            db.commit()
    return document_id


def sync_derived_proposals(db: Session, scope: ReadScope, source_id: str, limit: int = 50) -> int:
    """Pull the engine's inferred facts for one source into the review queue.

    The engine derives facts from patterns across memories rather than being
    told them, so every row this writes is a proposal awaiting a human: it
    cannot reach canonical knowledge without the approval endpoint, which is
    the same status a locally extracted candidate gets.

    Facts are read from the source's own engine document, by the id stored at
    ingest. An unmatched source — captured before engine wiring, or one the
    engine never accepted — returns 0 rather than borrowing another source's
    facts; attaching a derived claim to the wrong source would corrupt the
    provenance chain the product exists to protect.

    Returns how many new proposals were created. An unreachable engine returns
    0 and changes nothing.
    """
    engine = get_engine()
    if engine.name == "deterministic":
        return 0
    source = db.get(Source, source_id)
    if source is None or source.workspace_id != scope.workspace_id:
        return 0
    if not source.engine_document_id:
        return 0
    facts = engine.derived(source.engine_document_id, limit=limit)
    if not facts:
        return 0
    facts = [f for f in facts if f.memory_id and f.text]
    if not facts:
        return 0

    created = 0
    known = KnownStatements.load(db, source.workspace_id)
    for fact in facts:
        # One engine fact, one proposal: re-syncing must not duplicate the
        # queue, and a fact the workspace already holds (from this source or
        # any other) is not worth a second review.
        if known.contains(fact.text[:5_000]):
            continue
        known.add(fact.text[:5_000])
        proposal = Proposal(
            id=new_id("prop"),
            workspace_id=source.workspace_id,
            source_id=source.id,
            type=classify_statement(fact.text),
            statement=fact.text[:5_000],
            rationale=(
                f"Derived by the {engine.name} engine from "
                f"{fact.support_count} supporting memories. "
                "Review wording and evidence before approval."
            ),
            # A derived fact is an inference across memories, so it has no
            # single excerpt. Empty is honest — a fabricated quote would be the
            # exact failure this product exists to prevent — and the evidence
            # edge below pins the whole source version instead.
            source_excerpt="",
            # The engine's own id for this fact, so an approve/reject decision
            # can be sent back and the retrieval index agrees with our state.
            engine_memory_id=fact.memory_id,
        )
        db.add(proposal)
        db.flush()
        # Without this edge the approval gate refuses the proposal forever,
        # because it requires immutable source evidence before it will create
        # canonical knowledge. Evidence is mandatory; a span is not.
        version_id = db.scalar(
            select(func.max(SourceVersion.version)).where(SourceVersion.source_id == source.id)
        )
        latest = db.scalar(
            select(SourceVersion.id).where(
                SourceVersion.source_id == source.id,
                SourceVersion.version == version_id,
            )
        )
        if latest is not None:
            db.add(
                ProposalEvidence(
                    proposal_id=proposal.id,
                    source_version_id=latest,
                    # No span: the derivation drew on the source as a whole.
                    source_span_id=None,
                )
            )
        created += 1
    if created:
        audit(
            db,
            source.workspace_id,
            "proposals.derived",
            "source",
            source.id,
            f"{created} engine-derived proposals awaiting review",
        )
        db.commit()
    return created


def record_review_with_engine(proposal: Proposal, action: str, memory_id: str | None) -> bool:
    """Tell the engine how a review resolved, so its ranking matches ours.

    Our table decides; this only keeps the retrieval index in agreement. A
    failure here is logged, not raised: a disagreeing index must not undo a
    decision a human already made and we already stored.
    """
    if not memory_id:
        return False
    engine = get_engine()
    if engine.name == "deterministic":
        return False
    return engine.review(container_tag_for(proposal.workspace_id), memory_id, action)


def approve_proposal(
    db: Session,
    proposal: Proposal,
    statement: str | None,
    rationale: str | None,
    actor: WorkspaceAccess | None = None,
    tags: list[str] | None = None,
) -> Knowledge:
    if proposal.status != "proposed":
        raise ValueError("Only proposed knowledge can be approved")
    evidence = db.get(ProposalEvidence, proposal.id)
    if evidence is None:
        raise ValueError("Proposal has no immutable source evidence")
    # A proposal must be checkable against the exact bytes it came from, so
    # canonical wording is only ever created once a source version is pinned.
    # Resolved before the row is written: raising afterwards would leave an
    # approved proposal with no canonical item, which is worse than refusing.
    version = db.get(SourceVersion, evidence.source_version_id)
    if version is None:
        raise ValueError("Proposal evidence points at a source version that is gone")
    canonical = Knowledge(
        id=new_id("know"),
        workspace_id=proposal.workspace_id,
        proposal_id=proposal.id,
        source_id=proposal.source_id,
        type=proposal.type,
        statement=statement or proposal.statement,
        rationale=rationale if rationale is not None else proposal.rationale,
        source_excerpt=proposal.source_excerpt or version.content[:600],
        summary=proposal.summary or "",
        tags=json.dumps(
            normalize_tags(tags) if tags is not None else parse_tags(proposal.tags),
            ensure_ascii=False,
        ),
    )
    # Embed the approved wording for hybrid retrieval (statement + rationale).
    # Best effort: an embedding failure never blocks a human's stored decision.
    embedder = get_embedder()
    if embedder is not None:
        vec = embedder.embed(f"{canonical.statement} {canonical.rationale}")
        if vec:
            canonical.embedding = json.dumps(vec)
            canonical.embedding_model = embedder.model
    proposal.status = "approved"
    db.add(canonical)
    db.flush()
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
    audit(
        db,
        canonical.workspace_id,
        "knowledge.approved",
        "knowledge",
        canonical.id,
        f"Approved {proposal.id}",
        actor=actor,
    )
    db.commit()
    db.refresh(canonical)
    # Keep FTS index in sync
    try:
        with SessionLocal() as fts_db:
            sync_fts_insert(fts_db, canonical)
            fts_db.commit()
    except Exception:
        pass  # FTS sync is best-effort; the knowledge row is the source of truth
    return canonical


def reject_proposal(
    db: Session,
    proposal: Proposal,
    reason: str,
    actor: WorkspaceAccess | None = None,
    *,
    commit: bool = True,
) -> Proposal:
    """Decline a pending proposal. The source and its spans are untouched."""
    if proposal.status != "proposed":
        raise ValueError("Only proposed knowledge can be rejected")
    proposal.status = "rejected"
    record_review_with_engine(proposal, "decline", proposal.engine_memory_id)
    audit(
        db,
        proposal.workspace_id,
        "proposal.rejected",
        "proposal",
        proposal.id,
        reason,
        actor=actor,
    )
    if commit:
        db.commit()
        db.refresh(proposal)
    return proposal


def supersede_knowledge(
    db: Session,
    item: Knowledge,
    statement: str,
    rationale: str,
    change_note: str,
    actor: WorkspaceAccess | None = None,
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
    audit(
        db,
        item.workspace_id,
        "knowledge.superseded",
        "knowledge",
        item.id,
        f"Created revision {revision}",
        actor=actor,
    )
    db.commit()
    db.refresh(item)
    # Keep FTS index in sync
    try:
        with SessionLocal() as fts_db:
            sync_fts_update(fts_db, item)
            fts_db.commit()
    except Exception:
        pass  # FTS sync is best-effort; the knowledge row is the source of truth
    return item


def backfill_provenance(db: Session, workspace_id: str) -> None:
    changed = False
    for source in db.scalars(select(Source).where(Source.workspace_id == workspace_id)).all():
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
    for item in db.scalars(select(Knowledge).where(Knowledge.workspace_id == workspace_id)).all():
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


def _knowledge_filters(knowledge_type: str | None, tag: str | None) -> list:
    filters = []
    if knowledge_type:
        filters.append(Knowledge.type == knowledge_type)
    cleaned = normalize_tags([tag]) if tag else []
    if cleaned:
        # Tags are stored as a JSON list, so match the quoted element. LIKE
        # wildcards in the tag itself are escaped so they match literally.
        escaped = cleaned[0].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Knowledge.tags.like(f'%"{escaped}"%', escape="\\"))
    return filters


def search_knowledge(
    db: Session,
    scope: ReadScope,
    query: str,
    limit: int = 20,
    *,
    knowledge_type: str | None = None,
    tag: str | None = None,
) -> list[Knowledge]:
    """Search canonical knowledge, optionally narrowed to one type and/or tag.

    Uses FTS5 BM25 ranking when available, falls back to ILIKE. Both paths
    respect workspace and sensitivity scoping through the same ReadScope.
    """
    filters = _knowledge_filters(knowledge_type, tag)
    base = scope.apply(
        select(Knowledge).where(Knowledge.status == "canonical", *filters),
        Knowledge,
    )
    if not query.strip():
        return list(db.scalars(base.order_by(Knowledge.approved_at.desc()).limit(limit)).all())

    # Try hybrid retrieval first: reciprocal-rank fusion of the dialect's keyword
    # index (FTS5/BM25 or ts_rank_cd) with the vector channel. When neither
    # answers it returns [] and we fall through to ILIKE.
    # Filters apply after ranking, so rank a wider pool when they are set.
    pool = min(limit * 5, 200) if filters else limit
    ranked_ids = hybrid_search(db, scope, query, limit=pool)
    if ranked_ids:
        # Preserve fused ranking order; filter by scope
        items = list(
            db.scalars(
                scope.apply(
                    select(Knowledge).where(
                        Knowledge.id.in_(ranked_ids),
                        Knowledge.status == "canonical",
                        *filters,
                    ),
                    Knowledge,
                )
            ).all()
        )
        # Re-order to match the fused ranking
        id_order = {kid: i for i, kid in enumerate(ranked_ids)}
        items.sort(key=lambda item: id_order.get(item.id, 999))
        # Fall through to ILIKE when the ranked ids resolve to nothing. They
        # can: an id may point at a superseded or out-of-scope row, or — as
        # happened when the index was declared contentless — the ids came back
        # NULL and matched no row at all. Returning [] here would report
        # "no knowledge" for a query the ILIKE fallback answers, and because
        # abstention is this product's safety signal, a false abstention is
        # worse than an unranked result.
        if items:
            return items[:limit]

    # ILIKE fallback
    terms = _query_terms(query)
    stmt = base
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
    if not (current_revision and latest) or current_revision.source_version_id == latest.id:
        return False
    # The source moved on. The fact is only stale if the sentence it rests on
    # changed: fixing a typo elsewhere in a note must not flag every fact the
    # note ever produced. A derived fact has no single span, so any new
    # version still asks for a re-check.
    if current_revision.source_span_id:
        evidence = db.get(SourceSpan, current_revision.source_span_id)
        if evidence is not None:
            still_present = db.scalar(
                select(func.count(SourceSpan.id)).where(
                    SourceSpan.source_version_id == latest.id,
                    SourceSpan.span_hash == evidence.span_hash,
                )
            )
            return not still_present
    return True


def _conflict_key(statement: str) -> tuple[set[str], bool, str]:
    """Extract conflict-relevant features from a statement.

    Returns (content_terms, has_negation, subject_ngram). The subject ngram
    is the first few significant words, used to detect same-topic contradictions.
    """
    lowered = statement.lower().replace("cannot", "can not")
    negative = bool(
        re.search(r"\b(?:not|never|no|cannot|shouldn't|won't|doesn't|isn't)\b", lowered)
    )
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
        "it",
        "that",
        "this",
        "with",
        "from",
        "for",
        "but",
        "or",
        "so",
        "if",
        "when",
    }
    terms = {
        term for term in re.findall(r"[a-z0-9]+", lowered) if len(term) > 2 and term not in ignored
    }
    # Subject ngram: first 3 significant words for same-topic detection
    sig_words = [
        term for term in re.findall(r"[a-z0-9]+", lowered) if len(term) > 2 and term not in ignored
    ]
    subject = " ".join(sig_words[:3])
    return terms, negative, subject


def conflict_map(items: list[Knowledge]) -> dict[str, list[str]]:
    """Detect possible conflicts between canonical knowledge items.

    Two items conflict when they share significant terms but express opposite
    polarity (one affirms, the other denies). Also flags same-topic items of
    the same type with very high overlap as potential contradictions.
    """
    conflicts: dict[str, list[str]] = {item.id: [] for item in items}
    keyed = {item.id: _conflict_key(item.statement) for item in items}
    for index, left in enumerate(items):
        left_terms, left_negative, left_subject = keyed[left.id]
        for right in items[index + 1 :]:
            right_terms, right_negative, right_subject = keyed[right.id]
            if not left_terms or not right_terms:
                continue
            overlap = len(left_terms & right_terms) / max(len(left_terms | right_terms), 1)
            # Case 1: opposite polarity with high term overlap
            if left_negative != right_negative and overlap >= 0.50:
                conflicts[left.id].append(right.id)
                conflicts[right.id].append(left.id)
                continue
            # Case 2: same topic, same type, very high overlap — possible duplicate/contradiction
            if (
                left.type == right.type
                and left_subject == right_subject
                and overlap >= 0.70
                and left.id not in conflicts[right.id]
            ):
                conflicts[left.id].append(right.id)
                conflicts[right.id].append(left.id)
    return conflicts


def integrity_snapshot(db: Session, scope: ReadScope) -> dict:
    items = list(
        db.scalars(
            scope.apply(
                select(Knowledge).where(Knowledge.status == "canonical"),
                Knowledge,
            ).order_by(Knowledge.approved_at)
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


# Question words that carry no topic. Kept separate from `_query_terms`'s list
# so search recall is unchanged; this only decides what an answer must cover.
_QUESTION_WORDS = frozenset(
    "who why whom whose did was were can could should would will tell know "
    "explain describe give list show any some there their they them its".split()
)


def _stem(word: str) -> str:
    """Crude shared prefix so 'pricing' meets 'price' and 'customers' meets 'customer'."""
    return word[:5] if len(word) > 5 else word.rstrip("s") or word


def _answer_terms(question: str) -> list[str]:
    return list(
        dict.fromkeys(term for term in _query_terms(question) if term not in _QUESTION_WORDS)
    )


def coverage(question_terms: list[str], item: Knowledge) -> float:
    """Share of the question's topic terms that appear in an approved item."""
    if not question_terms:
        return 0.0
    # A templated rationale ("Candidate extracted from an immutable source
    # span…") is on almost every item. Counting it let any question containing
    # "evidence", "source" or "review" match every fact in the brain.
    rationale = "" if item.rationale.startswith(_TEMPLATED_RATIONALES) else item.rationale
    words = {
        _stem(word) for word in re.findall(r"[a-z0-9]+", f"{item.statement} {rationale}".lower())
    }
    hits = sum(1 for term in question_terms if _stem(term) in words)
    return hits / len(question_terms)


def _required_hits(term_count: int) -> int:
    """Topic terms an item must contain to count as answering.

    Short questions need one (a three-word question often has one decisive
    term); longer ones need 40 percent: 4→2, 5→2, 6→3, 8→4.
    """
    if term_count <= 3:
        return 1
    return -(-term_count * 2 // 5)


def _semantic_support(question: str, items: list[Knowledge]) -> set[str]:
    """Ids whose stored embedding is close to the question, when embeddings exist.

    Lets a paraphrase count as an answer when the words differ. Without an
    embedding provider this is empty and the term check alone decides.
    """
    embedder = get_embedder()
    if embedder is None:
        return set()
    query_vec = embedder.embed(question)
    if not query_vec:
        return set()
    floor = get_settings().answer_min_similarity
    supported: set[str] = set()
    for item in items:
        if not item.embedding:
            continue
        try:
            vec = json.loads(item.embedding)
        except Exception:  # noqa: BLE001 — a corrupt embedding must not 500 a read
            continue
        if (
            len(vec) == len(query_vec)
            and sum(a * b for a, b in zip(vec, query_vec, strict=True)) >= floor
        ):
            supported.add(item.id)
    return supported


def answer_question(db: Session, scope: ReadScope, question: str) -> ChatResponse:
    """Answer only from approved knowledge that actually addresses the question.

    Search ORs its terms for recall, so a single shared word is enough to come
    back as a match. That is right for browsing and wrong for answering:
    abstention is this product's safety signal, and a confident, cited
    non-answer is the failure it exists to prevent. An item therefore has to
    cover most of the question's topic terms (or, with embeddings configured,
    be semantically close) before it is cited as an answer. Matches that fall
    short are returned as `near_matches`, never as citations.
    """
    candidates = search_knowledge(db, scope, question, limit=8)
    terms = _answer_terms(question)
    needed = _required_hits(len(terms))
    semantic = _semantic_support(question, candidates)
    matches = [
        item
        for item in candidates
        if item.id in semantic or (terms and coverage(terms, item) * len(terms) >= needed - 1e-9)
    ][:3]
    near = [item for item in candidates if item not in matches][:3]
    source_ids = {item.source_id for item in [*matches, *near]}
    # Scoped by the same permission as the matches, so a citation can never
    # name a source the caller was not allowed to read.
    sources = {
        item.id: item
        for item in db.scalars(
            scope.apply(
                select(Source).where(Source.id.in_(source_ids)),
                Source,
            )
        ).all()
    }

    def cite(items: list[Knowledge]) -> list[Citation]:
        return [
            Citation(
                knowledge_id=item.id,
                source_id=item.source_id,
                source_title=sources[item.source_id].title,
                excerpt=item.source_excerpt,
            )
            for item in items
            if item.source_id in sources
        ]

    if not matches:
        if near:
            answer = (
                "I could not find approved knowledge that answers this. The closest approved "
                "items are listed as near matches, but they do not answer the question as asked."
            )
        else:
            answer = (
                "I could not find enough approved knowledge to answer that. Import a source "
                "or review the pending proposals first."
            )
        return ChatResponse(answer=answer, citations=[], grounded=False, near_matches=cite(near))
    statements = " ".join(item.statement.rstrip(".") + "." for item in matches)
    return ChatResponse(answer=statements, citations=cite(matches), grounded=True)


def seed_demo(db: Session, workspace_id: str) -> None:
    existing = db.scalar(select(func.count(Source.id)).where(Source.workspace_id == workspace_id))
    if (existing or 0) > 0:
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
        create_source_with_proposals(db, payload, workspace_id)

    proposals = list(
        db.scalars(
            select(Proposal)
            .where(Proposal.workspace_id == workspace_id)
            .order_by(Proposal.created_at)
            .limit(5)
        ).all()
    )
    for proposal in proposals:
        approve_proposal(db, proposal, None, None)


def overview(db: Session, scope: ReadScope) -> dict:
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == scope.workspace_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(6)
        ).all()
    )
    status = engine_status(scope.workspace_id)
    return {
        **workspace_counts(db, scope),
        "recent_activity": [
            {
                "id": event.id,
                "action": event.action,
                "detail": event.detail,
                "created_at": event.created_at.astimezone(UTC).isoformat(),
            }
            for event in events
        ],
        "engine": {
            "name": status.name,
            "available": status.available,
            "detail": status.detail,
            "container_tag": status.container_tag,
            "degraded": status.degraded,
        },
    }


def export_workspace_data(db: Session, scope: ReadScope) -> dict:
    # An export is a read, so it carries the caller's ReadScope like every
    # other collection read: a member's export omits private material the
    # list endpoints already hide from them. Root tables are filtered by
    # workspace AND sensitivity ceiling; child tables do not carry either —
    # they are reached through the ids of roots that are already in scope, so
    # a child can never be exported without its readable parent.
    workspace_id = scope.workspace_id
    sources = sorted(
        db.scalars(scope.apply(select(Source).order_by(Source.created_at), Source)).all(),
        key=lambda row: row.created_at,
    )
    source_ids = {row.id for row in sources}
    versions = sorted(
        db.scalars(
            select(SourceVersion)
            .where(SourceVersion.source_id.in_(source_ids))
            .order_by(SourceVersion.source_id, SourceVersion.version)
        ).all(),
        key=lambda row: (row.source_id, row.version),
    )
    version_ids = {row.id for row in versions}
    spans = sorted(
        db.scalars(select(SourceSpan).where(SourceSpan.source_version_id.in_(version_ids))).all(),
        key=lambda row: (row.source_version_id, row.start_offset),
    )
    proposals = sorted(
        db.scalars(scope.apply(select(Proposal).order_by(Proposal.created_at), Proposal)).all(),
        key=lambda row: row.created_at,
    )
    proposal_ids = {row.id for row in proposals}
    evidence = sorted(
        db.scalars(
            select(ProposalEvidence).where(ProposalEvidence.proposal_id.in_(proposal_ids))
        ).all(),
        key=lambda row: row.proposal_id,
    )
    knowledge = sorted(
        db.scalars(scope.apply(select(Knowledge).order_by(Knowledge.approved_at), Knowledge)).all(),
        key=lambda row: row.approved_at,
    )
    knowledge_ids = {row.id for row in knowledge}
    revisions = sorted(
        db.scalars(
            select(KnowledgeRevision).where(KnowledgeRevision.knowledge_id.in_(knowledge_ids))
        ).all(),
        key=lambda row: (row.knowledge_id, row.revision),
    )
    events = sorted(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at)
        ).all(),
        key=lambda row: row.created_at,
    )

    def timestamp(value: datetime) -> str:
        return value.isoformat()

    return {
        "schema_version": 3,
        "exported_from": "open-intelligence-brain",
        "workspace": {"id": workspace_id},
        "sources": [
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
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
                "summary": row.summary or "",
                "tags": row.tags or "[]",
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


def restore_preview(db: Session, backup: dict, workspace_id: str) -> dict:
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
    if schema_version != 3:
        blockers.append("Only schema version 3 backups can be restored")
    missing = sorted(required - backup.keys())
    if missing:
        blockers.append(f"Missing collections: {', '.join(missing)}")
    # A restore writes into the caller's workspace. A backup belonging to another
    # workspace is refused rather than silently re-homed into this one.
    backup_workspace = (backup.get("workspace") or {}).get("id")
    if backup_workspace and backup_workspace != workspace_id:
        blockers.append("This backup belongs to a different workspace")
    foreign = {
        "sources": sum(
            1
            for row in backup.get("sources", [])
            if row.get("workspace_id", workspace_id) != workspace_id
        ),
        "knowledge": sum(
            1
            for row in backup.get("knowledge", [])
            if row.get("workspace_id", workspace_id) != workspace_id
        ),
    }
    leaked = {name: count for name, count in foreign.items() if count}
    if leaked:
        blockers.append(
            "Backup rows belong to another workspace: "
            + ", ".join(f"{name}={count}" for name, count in sorted(leaked.items()))
        )
    empty_workspace = all(
        (db.scalar(select(func.count(model.id)).where(model.workspace_id == workspace_id)) or 0)
        == 0
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


def restore_workspace(db: Session, backup: dict, workspace_id: str) -> dict:
    preview = restore_preview(db, backup, workspace_id)
    if not preview["valid"]:
        raise ValueError("; ".join(preview["blockers"]))
    for row in backup["sources"]:
        db.add(
            Source(
                id=row["id"],
                workspace_id=workspace_id,
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
                **{
                    key: value
                    for key, value in row.items()
                    if key not in ("created_at", "workspace_id")
                },
                workspace_id=workspace_id,
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
                **{
                    key: value
                    for key, value in row.items()
                    if key not in ("approved_at", "workspace_id")
                },
                workspace_id=workspace_id,
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
                **{
                    key: value
                    for key, value in row.items()
                    if key not in ("created_at", "workspace_id")
                },
                workspace_id=workspace_id,
                created_at=_parse_timestamp(row["created_at"]),
            )
        )
    db.commit()
    return preview
