from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AuditEvent,
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceSpan,
    SourceVersion,
)
from .schemas import (
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    DeletionPreview,
    IntegrityRead,
    KnowledgeRead,
    KnowledgeRevisionRead,
    OverviewRead,
    ProposalRead,
    RejectRequest,
    RestorePreview,
    RestoreRequest,
    SourceCreate,
    SourceRead,
    SourceVersionCreate,
    SourceVersionRead,
    SupersedeRequest,
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
    restore_preview,
    restore_workspace,
    search_knowledge,
    seed_demo,
    supersede_knowledge,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        backfill_provenance(db)
    if settings.seed_demo:
        with SessionLocal() as db:
            seed_demo(db)
    yield


app = FastAPI(
    title="Open Intelligence Brain API",
    description="A local-first governed knowledge workspace.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Brain-Token"],
)


def require_owner(x_brain_token: str = Header(default="")) -> None:
    if x_brain_token != settings.owner_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Brain token")


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


@app.get("/api/v1/overview", response_model=OverviewRead, dependencies=[Depends(require_owner)])
def get_overview(db: Session = Depends(get_db)):
    return overview(db)


@app.get("/api/v1/sources", response_model=list[SourceRead], dependencies=[Depends(require_owner)])
def list_sources(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Source, func.count(Proposal.id))
        .outerjoin(Proposal)
        .group_by(Source.id)
        .order_by(Source.created_at.desc())
    ).all()
    return [source_view(db, source, count) for source, count in rows]


@app.post(
    "/api/v1/sources",
    response_model=SourceRead,
    status_code=201,
    dependencies=[Depends(require_owner)],
)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    source = create_source_with_proposals(db, payload)
    count = db.scalar(select(func.count(Proposal.id)).where(Proposal.source_id == source.id)) or 0
    return source_view(db, source, count)


@app.get(
    "/api/v1/sources/{source_id}/versions",
    response_model=list[SourceVersionRead],
    dependencies=[Depends(require_owner)],
)
def list_source_versions(source_id: str, db: Session = Depends(get_db)):
    if db.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
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


@app.post(
    "/api/v1/sources/{source_id}/versions",
    response_model=SourceVersionRead,
    status_code=201,
    dependencies=[Depends(require_owner)],
)
def create_source_version(
    source_id: str, payload: SourceVersionCreate, db: Session = Depends(get_db)
):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
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


@app.get(
    "/api/v1/sources/{source_id}/deletion-preview",
    response_model=DeletionPreview,
    dependencies=[Depends(require_owner)],
)
def preview_source_deletion(source_id: str, db: Session = Depends(get_db)):
    if db.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="Source not found")
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


@app.get(
    "/api/v1/proposals", response_model=list[ProposalRead], dependencies=[Depends(require_owner)]
)
def list_proposals(
    proposal_status: str = Query(default="proposed", alias="status"), db: Session = Depends(get_db)
):
    rows = db.execute(
        select(Proposal, Source.title)
        .join(Source, Source.id == Proposal.source_id)
        .where(Proposal.status == proposal_status)
        .order_by(Proposal.created_at.desc())
    ).all()
    return [proposal_view(proposal, title) for proposal, title in rows]


@app.post(
    "/api/v1/proposals/{proposal_id}/approve",
    response_model=KnowledgeRead,
    dependencies=[Depends(require_owner)],
)
def approve(proposal_id: str, payload: ApprovalRequest, db: Session = Depends(get_db)):
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    try:
        item = approve_proposal(db, proposal, payload.statement, payload.rationale)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    source = db.get(Source, item.source_id)
    return knowledge_view(db, item, source.title)


@app.post(
    "/api/v1/proposals/{proposal_id}/reject",
    response_model=ProposalRead,
    dependencies=[Depends(require_owner)],
)
def reject(proposal_id: str, payload: RejectRequest, db: Session = Depends(get_db)):
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "proposed":
        raise HTTPException(status_code=409, detail="Only proposed knowledge can be rejected")
    proposal.status = "rejected"
    audit(db, "proposal.rejected", "proposal", proposal.id, payload.reason)
    db.commit()
    db.refresh(proposal)
    source = db.get(Source, proposal.source_id)
    return proposal_view(proposal, source.title)


@app.get(
    "/api/v1/knowledge", response_model=list[KnowledgeRead], dependencies=[Depends(require_owner)]
)
def list_knowledge(q: str = "", db: Session = Depends(get_db)):
    items = search_knowledge(db, q, limit=50)
    sources = {item.source_id: db.get(Source, item.source_id).title for item in items}
    conflicts = conflict_map(items)
    return [knowledge_view(db, item, sources[item.source_id], conflicts) for item in items]


@app.get(
    "/api/v1/knowledge/{knowledge_id}/revisions",
    response_model=list[KnowledgeRevisionRead],
    dependencies=[Depends(require_owner)],
)
def list_knowledge_revisions(knowledge_id: str, db: Session = Depends(get_db)):
    if db.get(Knowledge, knowledge_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return list(
        db.scalars(
            select(KnowledgeRevision)
            .where(KnowledgeRevision.knowledge_id == knowledge_id)
            .order_by(KnowledgeRevision.revision.desc())
        ).all()
    )


@app.post(
    "/api/v1/knowledge/{knowledge_id}/supersede",
    response_model=KnowledgeRead,
    dependencies=[Depends(require_owner)],
)
def supersede(knowledge_id: str, payload: SupersedeRequest, db: Session = Depends(get_db)):
    item = db.get(Knowledge, knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    try:
        item = supersede_knowledge(
            db, item, payload.statement, payload.rationale, payload.change_note
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    source = db.get(Source, item.source_id)
    return knowledge_view(db, item, source.title)


@app.get(
    "/api/v1/integrity",
    response_model=IntegrityRead,
    dependencies=[Depends(require_owner)],
)
def get_integrity(db: Session = Depends(get_db)):
    return integrity_snapshot(db)


@app.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_owner)])
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    return answer_question(db, payload.question)


@app.get("/api/v1/export", dependencies=[Depends(require_owner)])
def export_workspace(db: Session = Depends(get_db)):
    return export_workspace_data(db)


@app.post(
    "/api/v1/restore/preview",
    response_model=RestorePreview,
    dependencies=[Depends(require_owner)],
)
def preview_restore(payload: RestoreRequest, db: Session = Depends(get_db)):
    return restore_preview(db, payload.backup)


@app.post(
    "/api/v1/restore",
    response_model=RestorePreview,
    dependencies=[Depends(require_owner)],
)
def restore(payload: RestoreRequest, db: Session = Depends(get_db)):
    if not payload.confirm_empty_workspace:
        raise HTTPException(
            status_code=400,
            detail="Set confirm_empty_workspace=true after reviewing the restore preview",
        )
    try:
        return restore_workspace(db, payload.backup)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
if frontend.exists():

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str):
        requested = frontend / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend / "index.html")
