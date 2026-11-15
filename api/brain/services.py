import base64
import json
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .access import SENSITIVITY_RANK, ReadScope, WorkspaceAccess, actor_ref, workspace_counts
from .critic import assess_proposal
from .database import SessionLocal
from .embeddings import get_embedder
from .engine import (
    ContainerTagRejected,
    container_tag_for,
    engine_status,
    get_engine,
)
from .extraction import extract_tags, is_task_fragment, summarize
from .models import (
    AuditEvent,
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceSpan,
    SourceVersion,
    WorkspacePolicy,
    new_id,
)
from .retrieval import (
    hybrid_search,
    sync_fts_insert,
    sync_fts_update,
)
from .schemas import ChatResponse, Citation, SourceCreate, WorkspacePolicyUpdate

log = logging.getLogger(__name__)


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
        if 35 <= len(text) <= 600 and not is_task_fragment(text)
    ]
    unique = list(dict.fromkeys(candidates))
    return [(classify_statement(text), text) for text in unique[:8]]


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
    sig_words = [
        term for term in re.findall(r"[a-z0-9]+", lowered) if len(term) > 2 and term not in ignored
    ]
    subject = " ".join(sig_words[:3])
    return terms, negative, subject


def check_proposal_conflict(
    db: Session,
    workspace_id: str,
    statement: str,
    prop_type: str,
) -> tuple[str | None, str | None]:
    """Conflict Radar: detects potential contradictions with active canonical knowledge.

    Returns (conflicting_knowledge_id, conflict_note) or (None, None).
    """
    active_knowledge = list(
        db.scalars(
            select(Knowledge).where(
                Knowledge.workspace_id == workspace_id,
                Knowledge.status == "canonical",
                Knowledge.valid_to.is_(None),
            )
        ).all()
    )
    if not active_knowledge:
        return None, None

    prop_terms, prop_negative, prop_subject = _conflict_key(statement)
    if not prop_terms:
        return None, None

    for item in active_knowledge:
        item_terms, item_negative, item_subject = _conflict_key(item.statement)
        if not item_terms:
            continue
        overlap = len(prop_terms & item_terms) / max(len(prop_terms | item_terms), 1)

        # Opposite polarity with substantial topic overlap -> direct contradiction
        if prop_negative != item_negative and overlap >= 0.30:
            return (
                item.id,
                f"Contradicts approved knowledge ({item.id}): opposite polarity on overlapping topic ({overlap:.0%} overlap)",
            )

        # Same subject, same type, high overlap -> possible supersession or duplicate
        if prop_type == item.type and prop_subject == item_subject and overlap >= 0.70:
            return (
                item.id,
                f"Potentially supersedes approved knowledge ({item.id}): high topical overlap ({overlap:.0%})",
            )

    return None, None


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
        if create_proposals and 35 <= len(text) <= 600 and not is_task_fragment(text):
            statement = re.sub(r"\s+", " ", text)
            p_type = classify_statement(statement)
            conflict_id, conflict_note = check_proposal_conflict(
                db, source.workspace_id, statement, p_type
            )
            proposal = Proposal(
                id=new_id("prop"),
                workspace_id=source.workspace_id,
                source_id=source.id,
                type=p_type,
                statement=statement,
                rationale=(
                    "Candidate extracted from an immutable source span. "
                    "Review wording and evidence before approval."
                ),
                source_excerpt=text,
                summary=summarize(statement),
                tags=json.dumps(extract_tags(statement), ensure_ascii=False),
                conflict_with_id=conflict_id,
                conflict_note=conflict_note,
            )
            db.add(proposal)
            db.flush()
            # Run critic pass
            assessment = assess_proposal(
                proposal_id=proposal.id,
                statement=statement,
                declared_type=proposal.type,
                source_excerpt=text,
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
            db.flush()
            evaluate_auto_approval(db, source.workspace_id, source, proposal, actor=actor)
    audit(
        db,
        source.workspace_id,
        "source.versioned",
        "source",
        source.id,
        f"Created source version {version.version}: {change_note}",
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
    for fact in facts:
        # One engine fact, one proposal: re-syncing must not duplicate the queue.
        already = db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.source_id == source_id,
                Proposal.statement == fact.text[:5_000],
            )
        )
        if already:
            continue
        fact_type = (
            fact.fact_type
            if fact.fact_type
            in {
                "decision",
                "belief",
                "lesson",
                "thesis",
                "evidence",
                "framework",
                "story",
                "open_question",
            }
            else classify_statement(fact.text)
        )
        conflict_id, conflict_note = check_proposal_conflict(
            db, source.workspace_id, fact.text, fact_type
        )
        proposal = Proposal(
            id=new_id("prop"),
            workspace_id=source.workspace_id,
            source_id=source.id,
            type=fact_type,
            statement=fact.text[:5_000],
            rationale=(
                f"Derived by the {engine.name} engine from "
                f"{fact.support_count} supporting memories. "
                "Review wording and evidence before approval."
            ),
            source_excerpt=fact.exact_quote if fact.exact_quote else "",
            engine_memory_id=fact.memory_id,
            conflict_with_id=conflict_id,
            conflict_note=conflict_note,
        )
        db.add(proposal)
        db.flush()

        # Critic pass for quality and grounding
        assessment = assess_proposal(
            proposal_id=proposal.id,
            statement=proposal.statement,
            declared_type=proposal.type,
            source_excerpt=proposal.source_excerpt,
        )
        if assessment.has_notes:
            proposal.critic_notes = json.dumps(
                [
                    {"severity": n.severity, "category": n.category, "message": n.message}
                    for n in assessment.notes
                ],
                ensure_ascii=False,
            )

        # Pin immutable source evidence
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
            span_id = None
            if fact.exact_quote and fact.start_offset >= 0 and fact.end_offset > fact.start_offset:
                existing_span = db.scalar(
                    select(SourceSpan.id).where(
                        SourceSpan.source_version_id == latest,
                        SourceSpan.start_offset == fact.start_offset,
                        SourceSpan.end_offset == fact.end_offset,
                    )
                )
                if existing_span:
                    span_id = existing_span
                else:
                    new_span = SourceSpan(
                        id=new_id("span"),
                        source_version_id=latest,
                        start_offset=fact.start_offset,
                        end_offset=fact.end_offset,
                        text=fact.exact_quote,
                        span_hash=content_hash(fact.exact_quote),
                    )
                    db.add(new_span)
                    db.flush()
                    span_id = new_span.id

            db.add(
                ProposalEvidence(
                    proposal_id=proposal.id,
                    source_version_id=latest,
                    source_span_id=span_id,
                )
            )
            db.flush()
            evaluate_auto_approval(db, source.workspace_id, source, proposal)
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
    valid_from: datetime | None = None,
    supersedes_knowledge_id: str | None = None,
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

    v_from = valid_from or datetime.now(UTC)
    canonical = Knowledge(
        id=new_id("know"),
        workspace_id=proposal.workspace_id,
        proposal_id=proposal.id,
        source_id=proposal.source_id,
        type=proposal.type,
        statement=statement or proposal.statement,
        rationale=rationale if rationale is not None else proposal.rationale,
        source_excerpt=proposal.source_excerpt or version.content[:600],
        valid_from=v_from,
        valid_to=None,
        superseded_by=None,
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

    # If this proposal explicitly supersedes an existing canonical item
    if supersedes_knowledge_id:
        old_item = db.get(Knowledge, supersedes_knowledge_id)
        if old_item is not None and old_item.workspace_id == proposal.workspace_id:
            old_item.superseded_by = canonical.id
            old_item.valid_to = v_from
            old_item.status = "superseded"
            audit(
                db,
                canonical.workspace_id,
                "knowledge.superseded",
                "knowledge",
                old_item.id,
                f"Superseded by {canonical.id} during approval of {proposal.id}",
                actor=actor,
            )

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
            change_note=(
                f"Initial approval (supersedes {supersedes_knowledge_id})"
                if supersedes_knowledge_id
                else "Initial approval"
            ),
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


def get_or_create_workspace_policy(db: Session, workspace_id: str) -> WorkspacePolicy:
    policy = db.scalar(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == workspace_id))
    if policy is None:
        policy = WorkspacePolicy(
            id=new_id("wspol"),
            workspace_id=workspace_id,
            auto_approve_enabled=False,
            auto_approve_types="note,lesson,evidence,fact",
            auto_approve_max_sensitivity="internal",
            require_clean_critic=True,
            require_zero_conflicts=True,
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


def update_workspace_policy(
    db: Session, workspace_id: str, payload: WorkspacePolicyUpdate
) -> WorkspacePolicy:
    policy = get_or_create_workspace_policy(db, workspace_id)
    if payload.auto_approve_enabled is not None:
        policy.auto_approve_enabled = payload.auto_approve_enabled
    if payload.auto_approve_types is not None:
        policy.auto_approve_types = payload.auto_approve_types
    if payload.auto_approve_max_sensitivity is not None:
        policy.auto_approve_max_sensitivity = payload.auto_approve_max_sensitivity
    if payload.require_clean_critic is not None:
        policy.require_clean_critic = payload.require_clean_critic
    if payload.require_zero_conflicts is not None:
        policy.require_zero_conflicts = payload.require_zero_conflicts
    db.commit()
    db.refresh(policy)
    return policy


def evaluate_auto_approval(
    db: Session,
    workspace_id: str,
    source: Source,
    proposal: Proposal,
    actor: WorkspaceAccess | None = None,
) -> bool:
    """Deterministically evaluate if a proposal qualifies for auto-approval.

    Governed strictly by deterministic WorkspacePolicy code. Never decided
    by prompt or model output.
    """
    if proposal.status != "proposed":
        return False

    policy = db.scalar(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == workspace_id))
    if policy is None or not policy.auto_approve_enabled:
        return False

    # Check allowed types
    allowed_types = {t.strip().lower() for t in policy.auto_approve_types.split(",") if t.strip()}
    if proposal.type.lower() not in allowed_types:
        return False

    # Check sensitivity ladder
    src_rank = SENSITIVITY_RANK.get(source.sensitivity, 2)
    max_rank = SENSITIVITY_RANK.get(policy.auto_approve_max_sensitivity, 1)
    if src_rank > max_rank:
        return False

    # Check conflicts
    if policy.require_zero_conflicts and proposal.conflict_with_id:
        return False

    # Check critic notes
    if policy.require_clean_critic and proposal.critic_notes:
        return False

    # All deterministic gates passed: mint canonical knowledge through standard approval gate
    try:
        approve_proposal(
            db,
            proposal,
            statement=None,
            rationale=None,
            actor=actor,
        )
        audit(
            db,
            workspace_id,
            "proposal.auto_approved",
            "proposal",
            proposal.id,
            f"Auto-approved via deterministic policy {policy.id} (type={proposal.type}, sensitivity={source.sensitivity})",
            actor=actor,
        )
        db.commit()
        return True
    except Exception as exc:
        log.warning("Auto-approval failed for proposal %s: %s", proposal.id, exc)
        return False


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


def search_knowledge(
    db: Session,
    scope: ReadScope,
    query: str,
    limit: int = 20,
    as_of: datetime | None = None,
    include_superseded: bool = False,
) -> list[Knowledge]:
    """Search canonical knowledge.

    Uses FTS5 BM25 ranking when available, falls back to ILIKE. Both paths
    respect workspace and sensitivity scoping through the same ReadScope,
    with bi-temporal filtering via as_of.
    """
    valid_statuses = (
        ["canonical", "superseded"] if (as_of is not None or include_superseded) else ["canonical"]
    )
    base = scope.apply(
        select(Knowledge).where(Knowledge.status.in_(valid_statuses)),
        Knowledge,
    )

    if as_of is not None:
        base = base.where(or_(Knowledge.valid_from.is_(None), Knowledge.valid_from <= as_of)).where(
            or_(Knowledge.valid_to.is_(None), Knowledge.valid_to > as_of)
        )
    elif not include_superseded:
        base = base.where(Knowledge.valid_to.is_(None))

    if not query.strip():
        return list(db.scalars(base.order_by(Knowledge.approved_at.desc()).limit(limit)).all())

    # Try hybrid retrieval first: reciprocal-rank fusion of the dialect's keyword
    # index (FTS5/BM25 or ts_rank_cd) with the vector channel. When neither
    # answers it returns [] and we fall through to ILIKE.
    ranked_ids = hybrid_search(db, scope, query, limit=limit)
    if ranked_ids:
        # Preserve fused ranking order; filter by scope and temporal conditions
        items_stmt = scope.apply(
            select(Knowledge).where(
                Knowledge.id.in_(ranked_ids),
                Knowledge.status.in_(valid_statuses),
            ),
            Knowledge,
        )
        if as_of is not None:
            items_stmt = items_stmt.where(
                or_(Knowledge.valid_from.is_(None), Knowledge.valid_from <= as_of)
            ).where(or_(Knowledge.valid_to.is_(None), Knowledge.valid_to > as_of))
        elif not include_superseded:
            items_stmt = items_stmt.where(Knowledge.valid_to.is_(None))

        items = list(db.scalars(items_stmt).all())
        # Re-order to match the fused ranking
        id_order = {kid: i for i, kid in enumerate(ranked_ids)}
        items.sort(key=lambda item: id_order.get(item.id, 999))
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
    return bool(current_revision and latest and current_revision.source_version_id != latest.id)


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


def answer_question(db: Session, scope: ReadScope, question: str) -> ChatResponse:
    matches = search_knowledge(db, scope, question, limit=3)
    if not matches:
        return ChatResponse(
            answer="I could not find enough approved knowledge to answer that. Import a source or review the pending proposals first.",
            citations=[],
            grounded=False,
        )
    source_ids = {item.source_id for item in matches}
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
    statements = " ".join(item.statement.rstrip(".") + "." for item in matches)
    citations = [
        Citation(
            knowledge_id=item.id,
            source_id=item.source_id,
            source_title=sources[item.source_id].title,
            excerpt=item.source_excerpt,
        )
        for item in matches
        if item.source_id in sources
    ]
    return ChatResponse(answer=statements, citations=citations, grounded=True)


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
        "schema_version": 4,
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
                "critic_notes": row.critic_notes or "",
                "summary": row.summary or "",
                "tags": row.tags or "[]",
                "conflict_with_id": row.conflict_with_id,
                "conflict_note": row.conflict_note,
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
                "valid_from": timestamp(row.valid_from) if row.valid_from else None,
                "valid_to": timestamp(row.valid_to) if row.valid_to else None,
                "superseded_by": row.superseded_by,
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
    if schema_version not in (3, 4):
        blockers.append("Only schema version 3 or 4 backups can be restored")
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
        k_data = {
            key: value
            for key, value in row.items()
            if key not in ("approved_at", "workspace_id", "valid_from", "valid_to")
        }
        if "valid_from" in row and row["valid_from"]:
            k_data["valid_from"] = _parse_timestamp(row["valid_from"])
        if "valid_to" in row and row["valid_to"]:
            k_data["valid_to"] = _parse_timestamp(row["valid_to"])
        db.add(
            Knowledge(
                **k_data,
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


def reindex_knowledge_embeddings(
    db: Session, workspace_id: str, force: bool = False
) -> dict[str, int]:
    """Recompute embeddings for canonical knowledge in a workspace.

    Can fill in missing embeddings or re-embed everything if force=True.
    Also rebuilds full-text search index to keep hybrid search in parity.
    """
    embedder = get_embedder()
    items = db.scalars(
        select(Knowledge).where(
            Knowledge.workspace_id == workspace_id,
            Knowledge.status.in_(("canonical", "superseded")),
        )
    ).all()

    embedded_count = 0
    skipped_count = 0
    if embedder is not None:
        for item in items:
            if not force and item.embedding:
                skipped_count += 1
                continue
            text = f"{item.statement} {item.rationale}"
            vec = embedder.embed(text)
            if vec:
                item.embedding = json.dumps(vec)
                item.embedding_model = embedder.model
                embedded_count += 1
        db.commit()

    fts_rebuilt = 0
    try:
        from .retrieval import rebuild_fts

        fts_rebuilt = rebuild_fts(db)
    except Exception as exc:
        log.warning("FTS rebuild during reindex failed: %s", exc)

    return {
        "total": len(items),
        "embedded": embedded_count,
        "skipped": skipped_count,
        "fts_rebuilt": fts_rebuilt,
    }


MAGIC_ENCRYPTED_HEADER = b"OIB_ENC_V1:"


def _derive_fernet_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_backup_data(backup_data: dict, passphrase: str) -> bytes:
    """Encrypt backup JSON dict with AES-256 (Fernet) derived from passphrase."""
    from cryptography.fernet import Fernet

    raw_json = json.dumps(backup_data, ensure_ascii=False).encode("utf-8")
    salt = os.urandom(16)
    key = _derive_fernet_key(passphrase, salt)
    f = Fernet(key)
    ciphertext = f.encrypt(raw_json)
    return MAGIC_ENCRYPTED_HEADER + salt + ciphertext


def decrypt_backup_data(encrypted_bytes: bytes, passphrase: str) -> dict:
    """Decrypt backup data using passphrase."""
    from cryptography.fernet import Fernet

    if not encrypted_bytes.startswith(MAGIC_ENCRYPTED_HEADER):
        raise ValueError("Invalid encrypted backup format: missing magic header")
    offset = len(MAGIC_ENCRYPTED_HEADER)
    salt = encrypted_bytes[offset : offset + 16]
    ciphertext = encrypted_bytes[offset + 16 :]
    key = _derive_fernet_key(passphrase, salt)
    f = Fernet(key)
    try:
        decrypted = f.decrypt(ciphertext)
    except Exception as exc:
        raise ValueError("Decryption failed: incorrect passphrase or corrupted data") from exc
    return json.loads(decrypted.decode("utf-8"))


def execute_source_deletion(
    db: Session,
    source: Source,
    actor: WorkspaceAccess | None = None,
) -> dict[str, object]:
    """Execute reviewed deletion of a source and its unapproved children.

    Fails closed (raises ValueError) if any canonical knowledge item or
    knowledge revision depends on this source or its versions/spans.
    """
    from .studio import InterviewSession

    canonical_count = (
        db.scalar(select(func.count(Knowledge.id)).where(Knowledge.source_id == source.id)) or 0
    )
    revision_count = (
        db.scalar(
            select(func.count(KnowledgeRevision.id)).where(KnowledgeRevision.source_id == source.id)
        )
        or 0
    )
    if canonical_count > 0 or revision_count > 0:
        raise ValueError("Deletion is blocked while approved knowledge depends on this source.")

    version_ids = list(
        db.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source.id)).all()
    )
    span_ids = (
        list(
            db.scalars(
                select(SourceSpan.id).where(SourceSpan.source_version_id.in_(version_ids))
            ).all()
        )
        if version_ids
        else []
    )
    proposal_ids = list(
        db.scalars(select(Proposal.id).where(Proposal.source_id == source.id)).all()
    )

    # Clear InterviewSession references if any point to this source
    for session_row in db.scalars(
        select(InterviewSession).where(InterviewSession.source_id == source.id)
    ).all():
        session_row.source_id = None

    if proposal_ids:
        db.execute(
            ProposalEvidence.__table__.delete().where(
                ProposalEvidence.proposal_id.in_(proposal_ids)
            )
        )
        db.execute(Proposal.__table__.delete().where(Proposal.id.in_(proposal_ids)))

    if span_ids:
        db.execute(SourceSpan.__table__.delete().where(SourceSpan.id.in_(span_ids)))

    if version_ids:
        db.execute(SourceVersion.__table__.delete().where(SourceVersion.id.in_(version_ids)))

    source_id = source.id
    source_title = source.title
    workspace_id = source.workspace_id

    db.delete(source)
    audit(
        db,
        workspace_id,
        "source.deleted",
        "source",
        source_id,
        f"Deleted source '{source_title}' ({len(version_ids)} versions, {len(span_ids)} spans, {len(proposal_ids)} proposals)",
        actor=actor,
    )
    db.commit()

    return {
        "source_id": source_id,
        "deleted": True,
        "versions_deleted": len(version_ids),
        "spans_deleted": len(span_ids),
        "proposals_deleted": len(proposal_ids),
        "detail": f"Deleted source {source_id} and {len(proposal_ids)} unapproved proposals.",
    }
