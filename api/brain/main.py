from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import AuditEvent, Knowledge, Proposal, Source
from .schemas import (
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    KnowledgeRead,
    OverviewRead,
    ProposalRead,
    RejectRequest,
    SourceCreate,
    SourceRead,
)
from .services import (
    answer_question,
    approve_proposal,
    audit,
    create_source_with_proposals,
    overview,
    search_knowledge,
    seed_demo,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    if settings.seed_demo:
        with SessionLocal() as db:
            seed_demo(db)
    yield


app = FastAPI(
    title="Open Intelligence Brain API",
    description="A local-first governed knowledge workspace.",
    version="0.1.0",
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


def knowledge_view(item: Knowledge, source_title: str) -> KnowledgeRead:
    return KnowledgeRead.model_validate(item).model_copy(update={"source_title": source_title})


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
    return [
        SourceRead.model_validate(source).model_copy(update={"proposal_count": count})
        for source, count in rows
    ]


@app.post(
    "/api/v1/sources",
    response_model=SourceRead,
    status_code=201,
    dependencies=[Depends(require_owner)],
)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    source = create_source_with_proposals(db, payload)
    count = db.scalar(select(func.count(Proposal.id)).where(Proposal.source_id == source.id)) or 0
    return SourceRead.model_validate(source).model_copy(update={"proposal_count": count})


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
    return knowledge_view(item, source.title)


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
    return [knowledge_view(item, sources[item.source_id]) for item in items]


@app.post("/api/v1/chat", response_model=ChatResponse, dependencies=[Depends(require_owner)])
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    return answer_question(db, payload.question)


@app.get("/api/v1/export", dependencies=[Depends(require_owner)])
def export_workspace(db: Session = Depends(get_db)):
    sources = list(db.scalars(select(Source).order_by(Source.created_at)).all())
    proposals = list(db.scalars(select(Proposal).order_by(Proposal.created_at)).all())
    knowledge = list(db.scalars(select(Knowledge).order_by(Knowledge.approved_at)).all())
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all())
    return {
        "schema_version": 1,
        "exported_from": "open-intelligence-brain",
        "sources": [SourceRead.model_validate(row).model_dump(mode="json") for row in sources],
        "proposals": [
            ProposalRead.model_validate(row)
            .model_copy(update={"source_title": db.get(Source, row.source_id).title})
            .model_dump(mode="json")
            for row in proposals
        ],
        "knowledge": [
            KnowledgeRead.model_validate(row)
            .model_copy(update={"source_title": db.get(Source, row.source_id).title})
            .model_dump(mode="json")
            for row in knowledge
        ],
        "audit_events": [
            {
                "id": row.id,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
            }
            for row in events
        ],
    }


frontend = Path(__file__).resolve().parents[2] / "web" / "dist"
if frontend.exists():

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str):
        requested = frontend / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(frontend / "index.html")
