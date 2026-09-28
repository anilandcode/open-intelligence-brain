import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import turns as harness_turns
from .access import (
    AccessDenied,
    ReadScope,
    WorkspaceAccess,
    audit_access,
    ensure_default_workspace,
    grant_workspace,
    require_in_workspace,
    resolve_workspace,
)
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .harness import Turn as TurnRow
from .migrate import add_engine_link_columns, add_grant_scope_and_expiry, add_nullable_evidence_span, add_workspace_columns
from .mcp_http import router as mcp_http_router
from .studio_api import router as studio_router
from .models import (
    AuditEvent,
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceSpan,
    SourceVersion,
    Workspace,
    WorkspaceGrant,
    new_id,
)
from .schemas import (
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    DeletionPreview,
    EventCreate,
    EventIntake,
    EventRead,
    IntegrityRead,
    KnowledgeRead,
    KnowledgeRevisionRead,
    OverviewRead,
    ProactivityRead,
    ProactivityUpdate,
    ProposalRead,
    RejectRequest,
    RestorePreview,
    RestoreRequest,
    ResumeRequest,
    SourceCreate,
    SourceRead,
    SourceVersionCreate,
    SourceVersionRead,
    SteerRequest,
    StepRequest,
    StepResponse,
    StopRequest,
    SupersedeRequest,
    SuspendRequest,
    TriageRead,
    TurnDetail,
    TurnRead,
    TurnStepRead,
    WorkspaceCreate,
    WorkspaceRead,
    TokenCreate,
    TokenRead,
)
from .services import (
    add_source_version,
    answer_question,
    approve_proposal,
    audit,
    backfill_provenance,
    conflict_map,
    create_source_with_proposals,
    export_workspace_data,
    integrity_snapshot,
    knowledge_is_stale,
    knowledge_revision_count,
    latest_source_version,
    overview,
    record_review_with_engine,
    restore_preview,
    restore_workspace,
    search_knowledge,
    seed_demo,
    supersede_knowledge,
    sync_derived_proposals,
)
from .retrieval import ensure_fts, rebuild_fts

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    # create_all does not alter existing tables, so an existing deployment needs
    # the columns added before any query that selects them.
    migrated = add_workspace_columns()
    if migrated:
        logging.getLogger(__name__).info("Added workspace_id to: %s", ", ".join(migrated))
    # Runs after the workspace columns, and only relaxes a NOT NULL, so it is
    # safe against a database that already carries provenance.
    relaxed = add_nullable_evidence_span()
    if relaxed:
        logging.getLogger(__name__).info("Relaxed NOT NULL on: %s", ", ".join(relaxed))
    # Adds the engine document/memory ids. Additive with defaults, so an
    # existing deployment keeps every row and merely gains the link columns.
    linked = add_engine_link_columns()
    if linked:
        logging.getLogger(__name__).info("Added engine link columns to: %s", ", ".join(linked))
    # Adds scope and expires_at to workspace_grants for expiring/scoped tokens.
    granted = add_grant_scope_and_expiry()
    if granted:
        logging.getLogger(__name__).info("Added grant columns: %s", ", ".join(granted))
    # Build the FTS5 index for full-text search over canonical knowledge.
    with SessionLocal() as db:
        if ensure_fts(db):
            count = rebuild_fts(db)
            logging.getLogger(__name__).info("FTS5 index built: %d canonical items", count)
        else:
            logging.getLogger(__name__).info("FTS5 not available, using ILIKE fallback")
    # Every deployment starts with a real workspace and a grant for the configured
    # token, so a single-company Brain works with no extra setup.
    with SessionLocal() as db:
        workspace = ensure_default_workspace(db)
        # Unconditional: authentication has to work whether or not demo data is
        # seeded, otherwise a non-demo deployment could not authenticate at all.
        grant_workspace(db, workspace, settings.owner_token, role="owner")
        db.commit()
    for workspace_row in _workspaces():
        with SessionLocal() as db:
            backfill_provenance(db, workspace_row)
    if settings.seed_demo:
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            seed_demo(db, workspace.id)
    yield


def _workspaces() -> list[str]:
    with SessionLocal() as db:
        return [row.id for row in db.scalars(select(Workspace)).all()]


app = FastAPI(
    title="Open Intelligence Brain API",
    description="A local-first governed knowledge workspace.",
    version="0.4.0",
    lifespan=lifespan,
)
app.include_router(mcp_http_router)
app.include_router(studio_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Content-Type", "X-Brain-Token", "X-Brain-Workspace"],
)


def resolve_access(
    x_brain_token: str = Header(default=""),
    x_brain_workspace: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WorkspaceAccess:
    """Authenticate the caller and pin every request to one workspace.

    This replaces the old single `require_owner` check. A token that is not
    granted the named workspace gets 403 and reads nothing; a record that exists
    in another workspace is reported as 404 so its existence is not confirmed.
    """
    try:
        return resolve_workspace(db, x_brain_token, x_brain_workspace)
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def read_scope(access: WorkspaceAccess = Depends(resolve_access)) -> ReadScope:
    """The read authority for a request: one workspace, one role's sensitivities.

    Handed to services so every collection query is narrowed by the same rule
    `require_in_workspace` applies to a single record. Passing a bare
    `workspace_id` around is what allowed `sensitivity` to go unenforced.
    """
    return ReadScope.of(access)


def proposal_view(proposal: Proposal, source_title: str) -> ProposalRead:
    return ProposalRead.model_validate(proposal).model_copy(update={"source_title": source_title})


def source_view(db: Session, source: Source, proposal_count: int = 0) -> SourceRead:
    version = latest_source_version(db, source.id)
    return SourceRead.model_validate(source).model_copy(
        update={
            "content": version.content if version else source.content,
            "proposal_count": proposal_count,
            "current_version": version.version if version else 1,
            "content_hash": version.content_hash if version else "",
        }
    )


def knowledge_view(
    db: Session,
    item: Knowledge,
    source_title: str,
    conflicts: dict[str, list[str]] | None = None,
) -> KnowledgeRead:
    return KnowledgeRead.model_validate(item).model_copy(
        update={
            "source_title": source_title,
            "revision_count": knowledge_revision_count(db, item.id),
            "stale": knowledge_is_stale(db, item),
            "conflict_ids": (conflicts or {}).get(item.id, []),
        }
    )


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    db.scalar(select(func.count(Source.id)))
    return {"status": "ready"}


@app.get("/api/v1/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(
    access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)
):
    """Every workspace the caller's token is granted. Never a global list."""
    rows = db.execute(
        select(Workspace)
        .join(
            WorkspaceGrant,
            WorkspaceGrant.workspace_id == Workspace.id,
        )
        .where(WorkspaceGrant.principal == access.principal)
        .order_by(Workspace.created_at)
    ).scalars().all()
    return list(rows)


@app.post("/api/v1/workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Give the caller's token a second company's Brain.

    Creating a workspace is an owner action and always grants the creator the
    owner role, so the new workspace is reachable without a second setup step.
    """
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can create a workspace",
        )
    if db.scalar(select(Workspace.id).where(Workspace.slug == payload.slug)) is not None:
        raise HTTPException(status_code=409, detail="That workspace slug is already in use")
    workspace = Workspace(id=new_id("ws"), slug=payload.slug, name=payload.name)
    db.add(workspace)
    db.flush()
    grant_workspace(db, workspace, access.principal, role="owner")
    audit_access(
        db, access, "workspace.created", f"Created {workspace.name} ({workspace.slug})"
    )
    db.commit()
    db.refresh(workspace)
    return workspace


@app.post("/api/v1/workspaces/{workspace_slug}/tokens", response_model=TokenRead, status_code=201)
def create_workspace_token(
    workspace_slug: str,
    payload: TokenCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Create a scoped or expiring access token for a workspace.

    Only owners and admins can create tokens. The generated token string is
    returned in the `principal` field — give it to the person or agent that
    needs access. Scoped tokens can only perform actions within their scope;
    expiring tokens stop working after `expires_in_hours`.
    """
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can create access tokens",
        )
    workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    token_string = f"brn_{uuid4().hex}"
    expires_at = None
    if payload.expires_in_hours is not None:
        expires_at = datetime.now(UTC) + timedelta(hours=payload.expires_in_hours)
    grant = grant_workspace(
        db, workspace, token_string,
        role=payload.role, scope=payload.scope, expires_at=expires_at,
    )
    audit_access(
        db, access, "token.created",
        f"Created {payload.role} token" + (f" scoped to {payload.scope}" if payload.scope else ""),
    )
    db.commit()
    db.refresh(grant)
    return grant


@app.get("/api/v1/workspaces/{workspace_slug}/tokens", response_model=list[TokenRead])
def list_workspace_tokens(
    workspace_slug: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """List all tokens for a workspace. Only owners and admins."""
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can list tokens",
        )
    workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None or workspace.id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return list(
        db.scalars(
            select(WorkspaceGrant).where(WorkspaceGrant.workspace_id == workspace.id)
        ).all()
    )


@app.delete("/api/v1/workspaces/{workspace_slug}/tokens/{token_id}", status_code=204)
def revoke_workspace_token(
    workspace_slug: str,
    token_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Revoke an access token. Only owners and admins."""
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can revoke tokens",
        )
    workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None or workspace.id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    grant = db.get(WorkspaceGrant, token_id)
    if grant is None or grant.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Token not found")
    db.delete(grant)
    audit_access(db, access, "token.revoked", f"Revoked token {token_id}")
    db.commit()


@app.get("/api/v1/overview", response_model=OverviewRead)
def get_overview(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    return overview(db, scope)


@app.get("/api/v1/sources", response_model=list[SourceRead])
def list_sources(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    rows = db.execute(
        scope.apply(
            select(Source, func.count(Proposal.id))
            .outerjoin(Proposal, Proposal.source_id == Source.id),
            Source,
        )
        .group_by(Source.id)
        .order_by(Source.created_at.desc())
    ).all()
    return [source_view(db, source, count) for source, count in rows]


@app.post("/api/v1/sources", response_model=SourceRead, status_code=201)
def create_source(
    payload: SourceCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    source = create_source_with_proposals(db, payload, access.workspace_id)
    count = (
        db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.source_id == source.id,
                Proposal.workspace_id == access.workspace_id,
            )
        )
        or 0
    )
    return source_view(db, source, count)


@app.post("/api/v1/sources/{source_id}/sync-derived")
def sync_derived(
    source_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    """Pull this source's engine-derived facts into the review queue.

    Explicit and human-triggered, never automatic: derivation is asynchronous
    on the engine side, so pulling at capture time would find an empty queue
    and teach users that the feature does nothing. Sync creates proposals
    only — approval stays the sole path to canonical knowledge.

    Refuses a source outside the caller's workspace with 404 like every other
    record route, rather than returning a quiet zero that a caller cannot tell
    apart from "nothing to derive".
    """
    require_in_workspace(db, access, Source, source_id)
    created = sync_derived_proposals(db, scope, source_id)
    return {"created": created}


@app.get("/api/v1/sources/{source_id}/versions", response_model=list[SourceVersionRead])
def list_source_versions(
    source_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_in_workspace(db, access, Source, source_id)
    versions = list(
        db.scalars(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.version.desc())
        ).all()
    )
    result = []
    for version in versions:
        span_count = (
            db.scalar(
                select(func.count(SourceSpan.id)).where(SourceSpan.source_version_id == version.id)
            )
            or 0
        )
        proposal_count = (
            db.scalar(
                select(func.count(ProposalEvidence.proposal_id)).where(
                    ProposalEvidence.source_version_id == version.id
                )
            )
            or 0
        )
        result.append(
            SourceVersionRead.model_validate(version).model_copy(
                update={"span_count": span_count, "proposal_count": proposal_count}
            )
        )
    return result


@app.post("/api/v1/sources/{source_id}/versions", response_model=SourceVersionRead, status_code=201)
def create_source_version(
    source_id: str,
    payload: SourceVersionCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    source = require_in_workspace(db, access, Source, source_id)
    try:
        version = add_source_version(db, source, payload.content, payload.change_note)
        db.commit()
        db.refresh(version)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    span_count = (
        db.scalar(
            select(func.count(SourceSpan.id)).where(SourceSpan.source_version_id == version.id)
        )
        or 0
    )
    proposal_count = (
        db.scalar(
            select(func.count(ProposalEvidence.proposal_id)).where(
                ProposalEvidence.source_version_id == version.id
            )
        )
        or 0
    )
    return SourceVersionRead.model_validate(version).model_copy(
        update={"span_count": span_count, "proposal_count": proposal_count}
    )


@app.get("/api/v1/sources/{source_id}/deletion-preview", response_model=DeletionPreview)
def preview_source_deletion(
    source_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_in_workspace(db, access, Source, source_id)
    versions = (
        db.scalar(select(func.count(SourceVersion.id)).where(SourceVersion.source_id == source_id))
        or 0
    )
    spans = (
        db.scalar(
            select(func.count(SourceSpan.id))
            .join(SourceVersion, SourceSpan.source_version_id == SourceVersion.id)
            .where(SourceVersion.source_id == source_id)
        )
        or 0
    )
    proposals = (
        db.scalar(select(func.count(Proposal.id)).where(Proposal.source_id == source_id)) or 0
    )
    canonical = (
        db.scalar(select(func.count(Knowledge.id)).where(Knowledge.source_id == source_id)) or 0
    )
    events = (
        db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.resource_type == "source",
                AuditEvent.resource_id == source_id,
            )
        )
        or 0
    )
    return DeletionPreview(
        source_id=source_id,
        versions=versions,
        spans=spans,
        proposals=proposals,
        canonical_items=canonical,
        audit_events=events,
        blocked=canonical > 0,
        reason=(
            "Deletion is blocked while approved knowledge depends on this source."
            if canonical
            else "Preview only. No data has been deleted."
        ),
    )


@app.get("/api/v1/proposals", response_model=list[ProposalRead])
def list_proposals(
    proposal_status: str = Query(default="proposed", alias="status"),
    access: WorkspaceAccess = Depends(resolve_access),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        scope.apply(
            select(Proposal, Source.title)
            .join(Source, Source.id == Proposal.source_id)
            .where(Proposal.status == proposal_status),
            Proposal,
        )
        .order_by(Proposal.created_at.desc())
    ).all()
    return [proposal_view(proposal, title) for proposal, title in rows]


@app.post("/api/v1/proposals/{proposal_id}/approve", response_model=KnowledgeRead)
def approve(
    proposal_id: str,
    payload: ApprovalRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    proposal = require_in_workspace(db, access, Proposal, proposal_id)
    try:
        item = approve_proposal(db, proposal, payload.statement, payload.rationale)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Engine-derived facts: tell the engine so its index agrees with our
    # canonical state. Best effort — our table is the system of record and a
    # failing notification must not undo a human's stored decision.
    record_review_with_engine(proposal, "approve", proposal.engine_memory_id)
    source = db.get(Source, item.source_id)
    return knowledge_view(db, item, source.title)


@app.post("/api/v1/proposals/{proposal_id}/reject", response_model=ProposalRead)
def reject(
    proposal_id: str,
    payload: RejectRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    proposal = require_in_workspace(db, access, Proposal, proposal_id)
    if proposal.status != "proposed":
        raise HTTPException(status_code=409, detail="Only proposed knowledge can be rejected")
    proposal.status = "rejected"
    record_review_with_engine(proposal, "decline", proposal.engine_memory_id)
    audit(
        db,
        access.workspace_id,
        "proposal.rejected",
        "proposal",
        proposal.id,
        payload.reason,
    )
    db.commit()
    db.refresh(proposal)
    source = db.get(Source, proposal.source_id)
    return proposal_view(proposal, source.title)


@app.get("/api/v1/knowledge", response_model=list[KnowledgeRead])
def list_knowledge(
    q: str = "",
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    items = search_knowledge(db, scope, q, limit=50)
    titles = {
        source_id: title
        for source_id, title in db.execute(
            scope.apply(
                select(Source.id, Source.title).where(Source.id.in_(
                    {item.source_id for item in items}
                )),
                Source,
            )
        ).all()
    }
    conflicts = conflict_map(items)
    return [
        knowledge_view(db, item, titles[item.source_id], conflicts)
        for item in items
        if item.source_id in titles
    ]


@app.get("/api/v1/knowledge/{knowledge_id}/revisions", response_model=list[KnowledgeRevisionRead])
def list_knowledge_revisions(
    knowledge_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_in_workspace(db, access, Knowledge, knowledge_id)
    return list(
        db.scalars(
            select(KnowledgeRevision)
            .where(KnowledgeRevision.knowledge_id == knowledge_id)
            .order_by(KnowledgeRevision.revision.desc())
        ).all()
    )


@app.post("/api/v1/knowledge/{knowledge_id}/supersede", response_model=KnowledgeRead)
def supersede(
    knowledge_id: str,
    payload: SupersedeRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    item = require_in_workspace(db, access, Knowledge, knowledge_id)
    try:
        item = supersede_knowledge(
            db, item, payload.statement, payload.rationale, payload.change_note
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    source = db.get(Source, item.source_id)
    return knowledge_view(db, item, source.title)


@app.get("/api/v1/integrity", response_model=IntegrityRead)
def get_integrity(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    return integrity_snapshot(db, scope)


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return answer_question(db, scope, payload.question)


@app.get("/api/v1/export")
def export_workspace(access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)):
    return export_workspace_data(db, access.workspace_id)


@app.post("/api/v1/restore/preview", response_model=RestorePreview)
def preview_restore(
    payload: RestoreRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    return restore_preview(db, payload.backup, access.workspace_id)


@app.post("/api/v1/restore", response_model=RestorePreview)
def restore(
    payload: RestoreRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    if not payload.confirm_empty_workspace:
        raise HTTPException(
            status_code=400,
            detail="Set confirm_empty_workspace=true after reviewing the restore preview",
        )
    try:
        return restore_workspace(db, payload.backup, access.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/events", response_model=EventIntake, status_code=201)
def intake_event(
    payload: EventCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Record an inbound message and open the turn triage decides it deserves.

    The response carries the decision and the rule behind it, not just the turn.
    A user who asks why the Brain stayed quiet gets the answer from the same
    call that recorded the message.
    """
    try:
        outcome = harness_turns.handle_event(
            db,
            access,
            channel=payload.channel,
            text=payload.text,
            author=payload.author,
            addressed=payload.addressed,
            is_bot=payload.is_bot,
            external_id=payload.external_id,
            raw_output=payload.model_output,
            evidence_strength=payload.evidence_strength,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EventIntake(
        event=EventRead.model_validate(outcome.event),
        turn=TurnRead.model_validate(outcome.turn),
        triage=TriageRead(
            action=outcome.decision.action,
            confidence=outcome.decision.confidence,
            reason=outcome.decision.reason,
            source=outcome.decision.source,
            kind=outcome.decision.kind,
            react=outcome.decision.react,
        ),
        superseded=list(outcome.superseded),
    )


def turn_detail(db: Session, turn: TurnRow) -> TurnDetail:
    detail = TurnDetail.model_validate(turn)
    return detail.model_copy(
        update={
            "steps": [
                TurnStepRead.model_validate(step)
                for step in harness_turns.turn_steps(db, turn)
            ],
            "plan": harness_turns.turn_plan(turn),
            "active_tools": list(harness_turns.active_tools(turn.action)),
        }
    )


def load_turn_or_404(db: Session, access: WorkspaceAccess, turn_id: str) -> TurnRow:
    """A turn outside the caller's workspace is 404, like every other record."""
    try:
        return harness_turns.load_turn(db, access, turn_id)
    except harness_turns.TurnNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


def turn_conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@app.get("/api/v1/turns", response_model=list[TurnRead])
def list_turns(
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return harness_turns.list_turns(
        db, scope, status_filter=status_filter, channel=channel, limit=limit
    )


@app.get("/api/v1/turns/{turn_id}", response_model=TurnDetail)
def get_turn(
    turn_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    return turn_detail(db, load_turn_or_404(db, access, turn_id))


@app.post("/api/v1/turns/{turn_id}/step", response_model=StepResponse)
def step_turn(
    turn_id: str,
    payload: StepRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Record one executed step. The caller observes, the server decides.

    An exhausted turn answers with itself and `exhausted: true` rather than an
    error, because running out of budget is a legitimate ending that the client
    has to render, not a failure it should retry.
    """
    turn = load_turn_or_404(db, access, turn_id)
    try:
        outcome = harness_turns.advance_turn(
            db, access, turn, tool=payload.tool, summary=payload.summary
        )
    except harness_turns.TurnConflict as exc:
        raise turn_conflict(exc) from exc
    return StepResponse(
        turn=TurnRead.model_validate(outcome.turn),
        step=TurnStepRead.model_validate(outcome.step),
        exhausted=outcome.exhausted,
    )


@app.post("/api/v1/turns/{turn_id}/steer", response_model=TurnDetail)
def steer_turn(
    turn_id: str,
    payload: SteerRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    turn = load_turn_or_404(db, access, turn_id)
    try:
        harness_turns.steer_turn(db, access, turn, note=payload.note)
    except harness_turns.TurnConflict as exc:
        raise turn_conflict(exc) from exc
    return turn_detail(db, turn)


@app.post("/api/v1/turns/{turn_id}/suspend", response_model=TurnDetail)
def suspend_turn(
    turn_id: str,
    payload: SuspendRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    turn = load_turn_or_404(db, access, turn_id)
    try:
        harness_turns.suspend_turn(
            db, access, turn, proposal_id=payload.proposal_id, question=payload.question
        )
    except harness_turns.TurnConflict as exc:
        raise turn_conflict(exc) from exc
    return turn_detail(db, turn)


@app.post("/api/v1/turns/{turn_id}/resume", response_model=TurnDetail)
def resume_turn(
    turn_id: str,
    payload: ResumeRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    turn = load_turn_or_404(db, access, turn_id)
    try:
        harness_turns.resume_turn(
            db, access, turn, approved=payload.approved, note=payload.note
        )
    except harness_turns.TurnConflict as exc:
        raise turn_conflict(exc) from exc
    return turn_detail(db, turn)


@app.post("/api/v1/turns/{turn_id}/stop", response_model=TurnDetail)
def stop_turn(
    turn_id: str,
    payload: StopRequest | None = None,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    turn = load_turn_or_404(db, access, turn_id)
    stopped = harness_turns.stop_turn(db, access, turn, reason=(payload.reason if payload else ""))
    return turn_detail(db, stopped)


@app.get("/api/v1/proactivity", response_model=list[ProactivityRead])
def list_proactivity(
    access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)
):
    """Only channels with an explicit policy. Unset channels follow the default."""
    return harness_turns.list_policies(db, access)


@app.put("/api/v1/proactivity", response_model=ProactivityRead)
def put_proactivity(
    payload: ProactivityUpdate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can change how a channel interrupts",
        )
    try:
        return harness_turns.set_policy(
            db,
            access,
            channel=payload.channel,
            mode=payload.mode,
            min_confidence=payload.min_confidence,
            answer_threshold=payload.answer_threshold,
            allow_investigate=payload.allow_investigate,
            react=payload.react,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
if frontend.exists():

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str):
        # The API has its own router; a path that reached here and still starts
        # with /api/v1 is an unknown endpoint, not a client route. Returning
        # index.html for it would answer a typo with 200 HTML and hide the
        # mistake from every API client that trusts status codes.
        if path.startswith("api/v1"):
            raise HTTPException(status_code=404, detail="Unknown endpoint")
        requested = frontend / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend / "index.html")
