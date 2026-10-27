import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import turns as harness_turns
from .access import (
    ReadScope,
    WorkspaceAccess,
    audit_access,
    ensure_default_workspace,
    grant_workspace,
    require_in_workspace,
    require_scope,
    resolve_request_access,
    token_preview,
)
from .auth_api import router as auth_router
from .config import get_settings
from .connections_api import router as connections_router
from .connectors import ConnectorError, capture_content, get_connector, ingest_fetched
from .database import Base, SessionLocal, engine, get_db
from .entities import (
    clean_refs,
    co_mentioned,
    create_entity,
    entities_for_items,
    entity_items,
    item_counts,
    list_entities,
    merge_entities,
    parse_aliases,
    readable_entity,
    update_entity,
)
from .harness import Turn as TurnRow
from .mcp_hosted import install_hosted_mcp_routes
from .mcp_http import router as mcp_http_router
from .mcp_oauth import (  # noqa: F401 — register OAuth tables on Base.metadata
    McpConnection,
    McpOAuthClient,
    McpOAuthCode,
    McpOAuthPending,
    McpOAuthTokenRow,
)
from .migrate import (
    add_audit_actor_columns,
    add_engine_link_columns,
    add_grant_scope_and_expiry,
    add_knowledge_embedding,
    add_knowledge_summary_tags,
    add_knowledge_timeframe,
    add_nullable_evidence_span,
    add_proposal_relation,
    add_proposal_summary_tags,
    add_workspace_columns,
)
from .models import (
    AuditEvent,
    ConnectorWatch,
    Entity,
    EvalQuestion,
    EvalRun,
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceSpan,
    SourceVersion,
    WatchedDocument,
    Workspace,
    WorkspaceGrant,
    new_id,
)
from .retrieval import SEARCH_INDEX_VERSION, dialect_name, ensure_fts, rebuild_fts
from .schemas import (
    AgentNoteRead,
    ApprovalRequest,
    BatchReviewRequest,
    BatchReviewResult,
    BatchReviewSkip,
    CaptureRequest,
    ChatRequest,
    ChatResponse,
    ConnectorIngestRequest,
    DeletionPreview,
    DismissSourceResult,
    EntityChip,
    EntityCreate,
    EntityDetail,
    EntityMerge,
    EntityRead,
    EntityUpdate,
    EvalQuestionCreate,
    EvalQuestionRead,
    EvalReport,
    EvalRunRead,
    EvalRunRequest,
    EventCreate,
    EventIntake,
    EventRead,
    IntegrityRead,
    KnowledgeRead,
    KnowledgeRevisionRead,
    McpConnectionRead,
    OverviewRead,
    ProactivityRead,
    ProactivityUpdate,
    PromoteNoteRequest,
    ProposalRead,
    RejectRequest,
    RestorePreview,
    RestoreRequest,
    ResumeRequest,
    ReviewedRequest,
    SourceCreate,
    SourceHitRead,
    SourceRead,
    SourceVersionCreate,
    SourceVersionRead,
    SteerRequest,
    StepRequest,
    StepResponse,
    StopRequest,
    SupersedeRequest,
    SuspendRequest,
    TimeframeUpdate,
    TokenCreate,
    TokenListRead,
    TokenRead,
    TriageRead,
    TurnDetail,
    TurnRead,
    TurnStepRead,
    WatchCreate,
    WatchRead,
    WatchSyncRequest,
    WatchSyncResult,
    WorkspaceCreate,
    WorkspaceRead,
)
from .scratchpad import (
    ScratchpadError,
    list_notes,
    promote_note,
    readable_note,
    search_sources,
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
    is_due_for_review,
    is_expired,
    knowledge_is_stale,
    knowledge_revision_count,
    latest_source_version,
    mark_reviewed,
    overview,
    record_review_with_engine,
    reject_proposal,
    restore_preview,
    restore_workspace,
    search_knowledge,
    seed_demo,
    set_timeframe,
    supersede_knowledge,
    sync_derived_proposals,
)
from .studio_api import router as studio_router

# Imported at module level on purpose: UsageEvent must be registered on Base
# before lifespan's create_all runs, or usage_events never exists on a fresh
# database and every /api/v1/usage* route 500s. Do not make this lazy.
from .usage import top_used, track_batch, unused_knowledge, usage_summary
from .vectors import ensure_pgvector
from .watches import sync_watch

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    # Attributes audit events to a caller. Additive with a 'system' default, so
    # an existing audit trail keeps working and never claims a human it cannot
    # name. Defined here rather than only in create_all because create_all does
    # not add columns to a table that already exists.
    attributed = add_audit_actor_columns()
    if attributed:
        logging.getLogger(__name__).info("Added audit actor columns: %s", ", ".join(attributed))
    # Adds vector embedding columns to knowledge for hybrid retrieval. Nullable
    # and additive, so existing rows are untouched (re-embedded on next rebuild).
    embedded = add_knowledge_embedding()
    if embedded:
        logging.getLogger(__name__).info("Added embedding columns: %s", ", ".join(embedded))
    # Adds richer-extraction metadata (summary/tags) to proposals. Additive and
    # idempotent: existing proposals are untouched and gain the columns only.
    enriched = add_proposal_summary_tags()
    if enriched:
        logging.getLogger(__name__).info(
            "Added proposal summary/tags columns: %s", ", ".join(enriched)
        )
    # Records how each proposal relates to approved knowledge (new/update/contradiction).
    related = add_proposal_relation()
    if related:
        logging.getLogger(__name__).info("Added proposal relation columns: %s", ", ".join(related))
    timeframe = add_knowledge_timeframe()
    if timeframe:
        logging.getLogger(__name__).info(
            "Added knowledge time frame columns: %s", ", ".join(timeframe)
        )
    # Carries proposal summary/tags onto approved knowledge for topic filters.
    tagged = add_knowledge_summary_tags()
    if tagged:
        logging.getLogger(__name__).info(
            "Added knowledge summary/tags columns: %s", ", ".join(tagged)
        )
    # Build the ranked full-text index for canonical knowledge. The backend
    # depends on the dialect: FTS5 on SQLite, a tsvector GIN index on
    # PostgreSQL. `ensure_fts` picks; we only log which one answered.
    with SessionLocal() as db:
        if ensure_fts(db):
            count = rebuild_fts(db)
            logging.getLogger(__name__).info(
                "Full-text index v%d ready (%s): %d canonical items",
                SEARCH_INDEX_VERSION,
                dialect_name(db),
                count,
            )
        else:
            logging.getLogger(__name__).info(
                "No ranked full-text index on %s; using ILIKE fallback", dialect_name(db)
            )
        # PostgreSQL with the vector extension searches embeddings in SQL.
        if ensure_pgvector(db):
            logging.getLogger(__name__).info("pgvector ready for embedding search")
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
    mcp_manager = getattr(app.state, "mcp_session_manager", None)
    # Hosted Streamable HTTP MCP needs the session manager task group for the
    # life of the process. When hosting is disabled, skip it.
    if mcp_manager is not None:
        from .mcp_hosted import run_mcp_session_manager

        async with run_mcp_session_manager(mcp_manager):
            yield
    else:
        yield


def _workspaces() -> list[str]:
    with SessionLocal() as db:
        return [row.id for row in db.scalars(select(Workspace)).all()]


app = FastAPI(
    title="Open Intelligence Brain API",
    description="A local-first governed knowledge workspace.",
    version="1.1.0",
    lifespan=lifespan,
)
app.include_router(mcp_http_router)
app.include_router(studio_router)
app.include_router(auth_router)
app.include_router(connections_router)

# Hosted Streamable HTTP MCP at /mcp (+ OAuth authorize/token/register). Must
# install before the SPA catch-all so /.well-known and /mcp are not HTML.
if settings.mcp_hosted:
    app.state.mcp_session_manager = install_hosted_mcp_routes(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Brain-Token",
        "X-Brain-Workspace",
        "X-Brain-Session",
        "Mcp-Session-Id",
        "Last-Event-ID",
        "MCP-Protocol-Version",
    ],
)


def resolve_access(
    x_brain_token: str = Header(default=""),
    x_brain_session: str = Header(default=""),
    x_brain_workspace: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WorkspaceAccess:
    """Authenticate the caller and pin every request to one workspace.

    Two credential classes, deliberately in two different headers:

    - `X-Brain-Token`   a machine credential from `workspace_grants`
    - `X-Brain-Session` a human session from `user_sessions`

    Neither is accepted where the other is expected, so an audit row can always
    say which class acted. Sending both is refused rather than silently picking
    one — a request whose actor is ambiguous is exactly what the separation
    exists to prevent.

    This replaces the old single `require_owner` check. A credential that is
    not granted the named workspace gets 403 and reads nothing; a record that
    exists in another workspace is reported as 404 so its existence is not
    confirmed.
    """
    if x_brain_token and x_brain_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Send exactly one credential"
        )
    return resolve_request_access(db, x_brain_token, x_brain_session, x_brain_workspace)


def read_scope(access: WorkspaceAccess = Depends(resolve_access)) -> ReadScope:
    """The read authority for a request: one workspace, one role's sensitivities.

    Handed to services so every collection query is narrowed by the same rule
    `require_in_workspace` applies to a single record. Passing a bare
    `workspace_id` around is what allowed `sensitivity` to go unenforced.
    """
    return ReadScope.of(access)


def proposal_view(
    proposal: Proposal, source_title: str, targets: dict[str, str] | None = None
) -> ProposalRead:
    """`targets` maps knowledge ids the caller may read to their wording.

    A target outside the caller's scope is reported as a plain `new` proposal
    with no id, so an update proposal never reveals private knowledge.
    """
    view = ProposalRead.model_validate(proposal).model_copy(update={"source_title": source_title})
    target = proposal.target_knowledge_id
    if target and targets is not None and target in targets:
        return view.model_copy(update={"target_statement": targets[target]})
    if target:
        return view.model_copy(update={"relation": "new", "target_knowledge_id": None})
    return view


def readable_targets(db: Session, scope: ReadScope, proposals: list[Proposal]) -> dict[str, str]:
    ids = {p.target_knowledge_id for p in proposals if p.target_knowledge_id}
    if not ids:
        return {}
    rows = db.execute(
        scope.apply(
            select(Knowledge.id, Knowledge.statement).where(
                Knowledge.id.in_(ids), Knowledge.status == "canonical"
            ),
            Knowledge,
        )
    ).all()
    return dict(rows)


def update_target_for(
    db: Session, access: WorkspaceAccess, proposal: Proposal, as_new: bool
) -> Knowledge | None:
    """The approved item this proposal should revise, or None to add it as new."""
    if as_new or proposal.relation not in ("update", "contradiction"):
        return None
    if not proposal.target_knowledge_id:
        return None
    try:
        return require_in_workspace(db, access, Knowledge, proposal.target_knowledge_id)
    except HTTPException:
        # Not readable by this reviewer (or gone): they cannot judge the
        # change, so the proposal is approved as a separate item.
        return None


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
    entities: list[Entity] | None = None,
) -> KnowledgeRead:
    return KnowledgeRead.model_validate(item).model_copy(
        update={
            "source_title": source_title,
            "revision_count": knowledge_revision_count(db, item.id),
            "stale": knowledge_is_stale(db, item),
            "conflict_ids": (conflicts or {}).get(item.id, []),
            "entities": [
                EntityChip(id=entity.id, name=entity.name, kind=entity.kind)
                for entity in entities or []
            ],
            "due_for_review": is_due_for_review(item),
            "expired": is_expired(item),
        }
    )


def entity_view(entity: Entity, count: int) -> EntityRead:
    return EntityRead(
        id=entity.id,
        name=entity.name,
        kind=entity.kind,
        aliases=parse_aliases(entity.aliases),
        item_count=count,
    )


def knowledge_views(db: Session, scope: ReadScope, items: list[Knowledge]) -> list[KnowledgeRead]:
    """Readable items with source titles, conflicts and entities, in order."""
    titles = {
        source_id: title
        for source_id, title in db.execute(
            scope.apply(
                select(Source.id, Source.title).where(
                    Source.id.in_({item.source_id for item in items})
                ),
                Source,
            )
        ).all()
    }
    conflicts = conflict_map(items)
    linked = entities_for_items(db, scope, [item.id for item in items])
    return [
        knowledge_view(db, item, titles[item.source_id], conflicts, linked.get(item.id))
        for item in items
        if item.source_id in titles
    ]


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
    """Every workspace the caller's credential reaches. Never a global list."""
    if access.actor_kind == "user":
        from .models import WorkspaceMember

        rows = (
            db.execute(
                select(Workspace)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(WorkspaceMember.user_id == access.actor_id)
                .order_by(Workspace.created_at)
            )
            .scalars()
            .all()
        )
        return list(rows)

    # Hashed API credentials bind to exactly one workspace (access.workspace).
    # Legacy grants may span several; look those up by raw principal only when
    # the principal still matches a grant row (bootstrap / test tokens).
    grant_rows = (
        db.execute(
            select(Workspace)
            .join(
                WorkspaceGrant,
                WorkspaceGrant.workspace_id == Workspace.id,
            )
            .where(WorkspaceGrant.principal == access.principal)
            .order_by(Workspace.created_at)
        )
        .scalars()
        .all()
    )
    if grant_rows:
        return list(grant_rows)
    return [access.workspace]


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
    audit_access(db, access, "workspace.created", f"Created {workspace.name} ({workspace.slug})")
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
    """Mint a hashed API credential for a workspace.

    Only owners and admins can create tokens. The raw secret is returned exactly
    once in `principal`. Scopes, when provided, are enforced on every later
    request; omit them for an unrestricted machine key (still bound to role).
    """
    require_scope(access, "admin")
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

    from .credentials import create_api_credential, validate_scopes

    scopes = payload.scopes
    if scopes is None and payload.scope:
        scopes = [s.strip() for s in payload.scope.split(",") if s.strip()]
    try:
        normalised = validate_scopes(scopes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    expires_at = None
    if payload.expires_in_hours is not None:
        expires_at = datetime.now(UTC) + timedelta(hours=payload.expires_in_hours)
    owner_user_id = access.actor_id if access.actor_kind == "user" else None
    raw, cred = create_api_credential(
        db,
        workspace,
        name=payload.name,
        role=payload.role,
        scopes=normalised,
        expires_at=expires_at,
        owner_user_id=owner_user_id,
    )
    scope_label = ",".join(normalised) if normalised else None
    audit_access(
        db,
        access,
        "token.created",
        f"Created {payload.role} credential"
        + (f" scoped to {scope_label}" if scope_label else "")
        + (f" ({payload.name})" if payload.name else ""),
    )
    db.commit()
    db.refresh(cred)
    return TokenRead(
        id=cred.id,
        workspace_id=cred.workspace_id,
        principal=raw,
        role=cred.role,
        name=cred.name,
        scope=scope_label,
        scopes=list(normalised or []),
        expires_at=cred.expires_at,
        created_at=cred.created_at,
    )


@app.get("/api/v1/workspaces/{workspace_slug}/tokens", response_model=list[TokenListRead])
def list_workspace_tokens(
    workspace_slug: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """List credentials for a workspace. Only owners and admins.

    Returns previews only — never raw secrets. Includes hashed API keys and
    legacy workspace_grants (bootstrap owner token shown as a preview).
    """
    require_scope(access, "admin")
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can list tokens",
        )
    workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None or workspace.id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from .credentials import list_api_credentials, scopes_for_credential

    rows: list[TokenListRead] = []
    for cred in list_api_credentials(db, workspace.id):
        scopes = scopes_for_credential(db, cred)
        rows.append(
            TokenListRead(
                id=cred.id,
                workspace_id=cred.workspace_id,
                principal_preview=token_preview(cred.key_prefix + "xxxx"),
                role=cred.role,
                name=cred.name,
                scope=",".join(scopes) if scopes else None,
                scopes=scopes,
                expires_at=cred.expires_at,
                created_at=cred.created_at,
                last_used_at=cred.last_used_at,
                revoked_at=cred.revoked_at,
                kind="api_key",
            )
        )
    grants = db.scalars(
        select(WorkspaceGrant).where(WorkspaceGrant.workspace_id == workspace.id)
    ).all()
    for grant in grants:
        rows.append(
            TokenListRead(
                id=grant.id,
                workspace_id=grant.workspace_id,
                principal_preview=token_preview(grant.principal),
                role=grant.role,
                name="",
                scope=grant.scope,
                scopes=[grant.scope] if grant.scope else [],
                expires_at=grant.expires_at,
                created_at=grant.created_at,
                kind="legacy_grant",
            )
        )
    return rows


@app.delete("/api/v1/workspaces/{workspace_slug}/tokens/{token_id}", status_code=204)
def revoke_workspace_token(
    workspace_slug: str,
    token_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Revoke an access token. Only owners and admins."""
    require_scope(access, "admin")
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can revoke tokens",
        )
    workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None or workspace.id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from .credentials import revoke_api_credential
    from .models import ApiCredential

    if revoke_api_credential(db, token_id, workspace.id):
        audit_access(db, access, "token.revoked", f"Revoked API credential {token_id}")
        db.commit()
        return None

    grant = db.get(WorkspaceGrant, token_id)
    if grant is None or grant.workspace_id != workspace.id:
        # Also accept api credential id that was already revoked — 404 either way.
        cred = db.get(ApiCredential, token_id)
        if cred is None or cred.workspace_id != workspace.id:
            raise HTTPException(status_code=404, detail="Token not found")
        raise HTTPException(status_code=404, detail="Token not found")
    db.delete(grant)
    audit_access(db, access, "token.revoked", f"Revoked token {token_id}")
    db.commit()
    return None


@app.get("/api/v1/mcp/connections", response_model=list[McpConnectionRead])
def list_mcp_connections(
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Which MCP clients have reached this workspace. Owner/admin only.

    Telemetry only — never a credential. Covers BOTH auth shapes: OAuth-issued
    clients (named) and direct-bearer agents such as Antigravity. `status`
    reflects last-seen recency: active (<5m), idle (<24h), else stale.
    """
    require_scope(access, "admin")
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can view MCP connections",
        )
    rows = db.scalars(
        select(McpConnection)
        .where(McpConnection.workspace_id == access.workspace_id)
        .order_by(McpConnection.last_seen.desc())
    ).all()
    now = datetime.now(UTC)
    out: list[McpConnectionRead] = []
    for r in rows:
        last = r.last_seen.replace(tzinfo=UTC) if r.last_seen.tzinfo is None else r.last_seen
        age = (now - last).total_seconds()
        conn_status = "active" if age < 300 else ("idle" if age < 86400 else "expired")
        out.append(
            McpConnectionRead(
                id=r.id,
                client_id=r.client_id,
                client_name=r.client_name,
                source_kind=r.source_kind,
                principal_preview=r.principal_preview,
                role=r.role,
                user_agent=r.user_agent,
                access_count=r.access_count,
                first_seen=r.first_seen,
                last_seen=r.last_seen,
                status=conn_status,
            )
        )
    return out


@app.get("/api/v1/overview", response_model=OverviewRead)
def get_overview(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    return overview(db, scope)


@app.get("/api/v1/graph")
def get_graph(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    """Knowledge graph: sources + approved knowledge + edges. Read-only.

    Node/edge shape follows the Supermemory memory-graph contract so a client can
    render it (and later drop in their force engine). Scope-narrowed like every
    other read; never returns proposals or anything above the caller's ceiling.
    """
    from .graph import build_graph

    return build_graph(db, scope)


@app.get("/api/v1/sources", response_model=list[SourceRead])
def list_sources(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    rows = db.execute(
        scope.apply(
            select(Source, func.count(Proposal.id)).outerjoin(
                Proposal, Proposal.source_id == Source.id
            ),
            Source,
        )
        .group_by(Source.id)
        .order_by(Source.created_at.desc())
    ).all()
    return [source_view(db, source, count) for source, count in rows]


@app.post("/api/v1/connectors/{provider}/ingest", response_model=SourceRead, status_code=201)
def connector_ingest(
    provider: str,
    payload: ConnectorIngestRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Fetch one document from a provider and ingest it for human review.

    External content becomes a source + candidate proposals — never canonical.
    The provider token is used for the read only and never stored; a provider
    failure is a clean 502 and never blocks reads, review, or export.
    """
    require_scope(access, "sources:write")
    try:
        connector = get_connector(provider)
        fetched = connector.fetch_document(payload.document_id, payload.access_token)
        source = ingest_fetched(
            db, access.workspace_id, fetched, sensitivity=payload.sensitivity, actor=access
        )
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return source


@app.post("/api/v1/capture", response_model=SourceRead, status_code=201)
def quick_capture(
    payload: CaptureRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Capture a note, clipped page, shared link or voice note for review.

    The text is kept as given (a link is appended as "Source: <url>"), so the
    capture is an ordinary source: its sentences become proposals and nothing
    is approved automatically.
    """
    require_scope(access, "sources:write")
    content, title = capture_content(payload)
    if len(content) < 20:
        raise HTTPException(status_code=422, detail="Too short to capture: add a few words.")
    source = create_source_with_proposals(
        db,
        SourceCreate(
            title=title, kind=payload.kind, sensitivity=payload.sensitivity, content=content
        ),
        access.workspace_id,
        actor=access,
    )
    audit(
        db,
        access.workspace_id,
        "source.captured",
        "source",
        source.id,
        f"via {payload.via}",
        actor=access,
    )
    db.commit()
    count = (
        db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.source_id == source.id, Proposal.workspace_id == access.workspace_id
            )
        )
        or 0
    )
    return source_view(db, source, count)


def _watch_view(db: Session, watch: ConnectorWatch) -> WatchRead:
    count = (
        db.scalar(
            select(func.count(WatchedDocument.id)).where(WatchedDocument.watch_id == watch.id)
        )
        or 0
    )
    return WatchRead.model_validate(watch).model_copy(update={"document_count": count})


def _require_watch(db: Session, access: WorkspaceAccess, watch_id: str) -> ConnectorWatch:
    watch = db.get(ConnectorWatch, watch_id)
    if watch is None or watch.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Watched folder not found")
    return watch


@app.get("/api/v1/watches", response_model=list[WatchRead])
def list_watches(access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)):
    require_scope(access, "sources:write")
    watches = db.scalars(
        select(ConnectorWatch)
        .where(ConnectorWatch.workspace_id == access.workspace_id)
        .order_by(ConnectorWatch.created_at)
    ).all()
    return [_watch_view(db, watch) for watch in watches]


@app.post("/api/v1/watches", response_model=WatchRead, status_code=201)
def create_watch(
    payload: WatchCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Watch a provider folder. Nothing is fetched until the first sync."""
    require_scope(access, "sources:write")
    folder_id = payload.folder_id.strip()
    exists = db.scalar(
        select(ConnectorWatch.id).where(
            ConnectorWatch.workspace_id == access.workspace_id,
            ConnectorWatch.provider == payload.provider,
            ConnectorWatch.folder_id == folder_id,
        )
    )
    if exists:
        raise HTTPException(status_code=409, detail="This folder is already watched")
    watch = ConnectorWatch(
        id=new_id("watch"),
        workspace_id=access.workspace_id,
        provider=payload.provider,
        folder_id=folder_id,
        label=payload.label.strip(),
        kind=payload.kind,
        sensitivity=payload.sensitivity,
    )
    db.add(watch)
    audit(
        db,
        access.workspace_id,
        "watch.created",
        "connector_watch",
        watch.id,
        f"{watch.provider} {watch.label or folder_id}",
        actor=access,
    )
    db.commit()
    db.refresh(watch)
    return _watch_view(db, watch)


@app.delete("/api/v1/watches/{watch_id}", status_code=204)
def delete_watch(
    watch_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Stop watching. Sources already brought in, and their proposals, stay."""
    require_scope(access, "sources:write")
    watch = _require_watch(db, access, watch_id)
    db.execute(delete(WatchedDocument).where(WatchedDocument.watch_id == watch.id))
    audit(
        db,
        access.workspace_id,
        "watch.deleted",
        "connector_watch",
        watch.id,
        f"{watch.provider} {watch.label or watch.folder_id}",
        actor=access,
    )
    db.delete(watch)
    db.commit()


@app.post("/api/v1/watches/{watch_id}/sync", response_model=WatchSyncResult)
def sync_watch_route(
    watch_id: str,
    payload: WatchSyncRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Pull new and changed documents into review. The token is used once, not stored."""
    require_scope(access, "sources:write")
    watch = _require_watch(db, access, watch_id)
    try:
        result = sync_watch(db, watch, payload.access_token, actor=access)
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result.to_dict()


@app.get("/api/v1/scratchpad", response_model=list[AgentNoteRead])
def list_scratchpad(
    topic: str = Query(default="", max_length=160),
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Agents' live working notes in this workspace, at sensitivities the caller may read."""
    return list_notes(db, ReadScope.of(access), author=None, topic=topic, limit=200)


@app.delete("/api/v1/scratchpad/{note_id}", status_code=204)
def delete_scratch_note(
    note_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_scope(access, "sources:write")
    try:
        note = readable_note(db, ReadScope.of(access), note_id, author=None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.delete(note)
    db.commit()


@app.post("/api/v1/scratchpad/{note_id}/promote", response_model=SourceRead, status_code=201)
def promote_scratch_note(
    note_id: str,
    payload: PromoteNoteRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """File a note as a source; its sentences go to the review queue."""
    require_scope(access, "sources:write")
    try:
        note = readable_note(db, ReadScope.of(access), note_id, author=None)
        source = promote_note(db, note, title=payload.title, actor=access)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScratchpadError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    count = (
        db.scalar(
            select(func.count(Proposal.id)).where(
                Proposal.source_id == source.id, Proposal.workspace_id == access.workspace_id
            )
        )
        or 0
    )
    return source_view(db, source, count)


@app.get("/api/v1/search/sources", response_model=list[SourceHitRead])
def search_source_text(
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(default=10, ge=1, le=30),
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Sentences in readable sources, each labelled unreviewed or approved."""
    return [hit.__dict__ for hit in search_sources(db, ReadScope.of(access), q, limit=limit)]


@app.post("/api/v1/sources", response_model=SourceRead, status_code=201)
def create_source(
    payload: SourceCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_scope(access, "sources:write")
    source = create_source_with_proposals(db, payload, access.workspace_id, actor=access)
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
        version = add_source_version(db, source, payload.content, payload.change_note, actor=access)
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
        ).order_by(Proposal.created_at.desc())
    ).all()
    targets = readable_targets(db, scope, [proposal for proposal, _ in rows])
    return [proposal_view(proposal, title, targets) for proposal, title in rows]


@app.post("/api/v1/proposals/{proposal_id}/approve", response_model=KnowledgeRead)
def approve(
    proposal_id: str,
    payload: ApprovalRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_scope(access, "reviews:write")
    proposal = require_in_workspace(db, access, Proposal, proposal_id)
    try:
        item = approve_proposal(
            db,
            proposal,
            payload.statement,
            payload.rationale,
            actor=access,
            tags=payload.tags,
            update_target=update_target_for(db, access, proposal, payload.as_new),
            entities=(
                clean_refs([ref.model_dump() for ref in payload.entities])
                if payload.entities is not None
                else None
            ),
            timeframe=payload.timeframe(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Engine-derived facts: tell the engine so its index agrees with our
    # canonical state. Best effort — our table is the system of record and a
    # failing notification must not undo a human's stored decision.
    record_review_with_engine(proposal, "approve", proposal.engine_memory_id)
    return knowledge_views(db, ReadScope.of(access), [item])[0]


@app.post("/api/v1/proposals/{proposal_id}/reject", response_model=ProposalRead)
def reject(
    proposal_id: str,
    payload: RejectRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_scope(access, "reviews:write")
    proposal = require_in_workspace(db, access, Proposal, proposal_id)
    try:
        reject_proposal(db, proposal, payload.reason, actor=access)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    source = db.get(Source, proposal.source_id)
    return proposal_view(proposal, source.title)


@app.post("/api/v1/proposals/review", response_model=BatchReviewResult)
def review_batch(
    payload: BatchReviewRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Approve or reject a reviewer's selection in one request.

    Each id is loaded through the same scope check as the single-item routes, so
    an id the caller cannot see is skipped as "Not found" rather than revealed.
    Approval uses the proposed wording unchanged. Items are decided one at a
    time, so one bad id never undoes the others.
    """
    require_scope(access, "reviews:write")
    result = BatchReviewResult()
    for proposal_id in dict.fromkeys(payload.proposal_ids):
        try:
            proposal = require_in_workspace(db, access, Proposal, proposal_id)
        except HTTPException:
            result.skipped.append(BatchReviewSkip(proposal_id=proposal_id, reason="Not found"))
            continue
        try:
            if payload.action == "approve":
                item = approve_proposal(
                    db,
                    proposal,
                    None,
                    None,
                    actor=access,
                    update_target=update_target_for(db, access, proposal, as_new=False),
                )
                record_review_with_engine(proposal, "approve", proposal.engine_memory_id)
                result.approved.append(item.id)
            else:
                reject_proposal(db, proposal, payload.reason, actor=access)
                result.rejected.append(proposal.id)
        except ValueError as exc:
            db.rollback()
            result.skipped.append(BatchReviewSkip(proposal_id=proposal_id, reason=str(exc)))
    return result


@app.post("/api/v1/sources/{source_id}/proposals/dismiss", response_model=DismissSourceResult)
def dismiss_source_proposals(
    source_id: str,
    payload: RejectRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Reject every proposal still pending for one source.

    For the moment a reviewer has taken what matters from a note and wants the
    rest out of the queue. Approved and already-rejected items are untouched,
    and the source keeps every span as evidence.
    """
    require_scope(access, "reviews:write")
    source = require_in_workspace(db, access, Source, source_id)
    pending = list(
        db.scalars(
            select(Proposal).where(
                Proposal.source_id == source.id,
                Proposal.workspace_id == access.workspace_id,
                Proposal.status == "proposed",
            )
        ).all()
    )
    for proposal in pending:
        reject_proposal(db, proposal, payload.reason, actor=access, commit=False)
    db.commit()
    return DismissSourceResult(source_id=source.id, rejected=len(pending))


@app.get("/api/v1/knowledge", response_model=list[KnowledgeRead])
def list_knowledge(
    q: str = "",
    knowledge_type: str | None = Query(default=None, alias="type", max_length=40),
    tag: str | None = Query(default=None, max_length=40),
    entity: str | None = Query(default=None, max_length=32),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    if entity and readable_entity(db, scope, entity) is None:
        return []
    items = search_knowledge(
        db, scope, q, limit=50, knowledge_type=knowledge_type, tag=tag, entity_id=entity
    )
    return knowledge_views(db, scope, items)


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
            db, item, payload.statement, payload.rationale, payload.change_note, actor=access
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return knowledge_views(db, ReadScope.of(access), [item])[0]


@app.patch("/api/v1/knowledge/{knowledge_id}/timeframe", response_model=KnowledgeRead)
def patch_timeframe(
    knowledge_id: str,
    payload: TimeframeUpdate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Set or clear an item's as-of, review-by and expiry dates (audited)."""
    require_scope(access, "reviews:write")
    item = require_in_workspace(db, access, Knowledge, knowledge_id)
    try:
        item = set_timeframe(db, item, payload.changes(), actor=access)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return knowledge_views(db, ReadScope.of(access), [item])[0]


@app.post("/api/v1/knowledge/{knowledge_id}/reviewed", response_model=KnowledgeRead)
def post_reviewed(
    knowledge_id: str,
    payload: ReviewedRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """A person confirms the item still holds; schedules the next check."""
    require_scope(access, "reviews:write")
    item = require_in_workspace(db, access, Knowledge, knowledge_id)
    try:
        item = mark_reviewed(db, item, payload.next_review_days, actor=access)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return knowledge_views(db, ReadScope.of(access), [item])[0]


# --- entities: people, companies, projects, topics ----------------------------


def _entity_or_404(db: Session, scope: ReadScope, entity_id: str) -> Entity:
    entity = readable_entity(db, scope, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Not found")
    return entity


@app.get("/api/v1/entities", response_model=list[EntityRead])
def get_entities(
    kind: str | None = Query(default=None, pattern="^(person|company|project|topic)$"),
    q: str = Query(default="", max_length=80),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return [
        entity_view(entity, count) for entity, count in list_entities(db, scope, kind=kind, q=q)
    ]


@app.get("/api/v1/entities/{entity_id}", response_model=EntityDetail)
def get_entity(
    entity_id: str, scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)
):
    entity = _entity_or_404(db, scope, entity_id)
    items = entity_items(db, scope, entity.id)
    related = co_mentioned(db, scope, entity.id, [item.id for item in items])
    views = knowledge_views(db, scope, items)
    return EntityDetail(
        **entity_view(entity, len(views)).model_dump(),
        items=views,
        related=[entity_view(other, count) for other, count in related],
    )


@app.post("/api/v1/entities", response_model=EntityRead, status_code=201)
def post_entity(
    payload: EntityCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """A reviewer adds a person, company, project or topic by hand.

    With `link_existing`, approved items whose wording names it (or one of its
    aliases) are linked now; later intake suggests it automatically.
    """
    require_scope(access, "reviews:write")
    try:
        entity, _ = create_entity(
            db,
            access.workspace_id,
            payload.name,
            payload.kind,
            payload.aliases,
            link_existing=payload.link_existing,
            actor=access,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scope = ReadScope.of(access)
    return entity_view(entity, item_counts(db, scope, [entity.id])[entity.id])


@app.patch("/api/v1/entities/{entity_id}", response_model=EntityRead)
def patch_entity(
    entity_id: str,
    payload: EntityUpdate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    require_scope(access, "reviews:write")
    scope = ReadScope.of(access)
    entity = _entity_or_404(db, scope, entity_id)
    try:
        entity = update_entity(
            db,
            entity,
            name=payload.name,
            kind=payload.kind,
            aliases=payload.aliases,
            actor=access,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return entity_view(entity, item_counts(db, scope, [entity.id])[entity.id])


@app.post("/api/v1/entities/{entity_id}/merge", response_model=EntityRead)
def merge_entity(
    entity_id: str,
    payload: EntityMerge,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Fold a duplicate into another entity. Both must be visible to the caller."""
    require_scope(access, "reviews:write")
    scope = ReadScope.of(access)
    duplicate = _entity_or_404(db, scope, entity_id)
    keep = _entity_or_404(db, scope, payload.into_id)
    try:
        keep = merge_entities(db, duplicate, keep, actor=access)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return entity_view(keep, item_counts(db, scope, [keep.id])[keep.id])


@app.get("/api/v1/integrity", response_model=IntegrityRead)
def get_integrity(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    return integrity_snapshot(db, scope)


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    require_scope(access, "brain:ask")
    result = answer_question(db, scope, payload.question)
    # Track which knowledge atoms were cited
    if result.citations:
        track_batch(
            db,
            scope.workspace_id,
            [c.knowledge_id for c in result.citations],
            context="answer",
            query=payload.question,
        )
    return result


@app.get("/api/v1/export")
def export_workspace(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    # Scoped read: a member's export excludes private material exactly like
    # every list endpoint does. Passing a bare workspace_id here is what let
    # a member export sources above their ceiling.
    return export_workspace_data(db, scope)


@app.post("/api/v1/restore/preview", response_model=RestorePreview)
def preview_restore(
    payload: RestoreRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    # Restore is a destructive admin-class operation; preview is gated the
    # same way so a member cannot probe backup validity either.
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can preview a restore",
        )
    return restore_preview(db, payload.backup, access.workspace_id)


@app.post("/api/v1/restore", response_model=RestorePreview)
def restore(
    payload: RestoreRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can restore a workspace",
        )
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
                TurnStepRead.model_validate(step) for step in harness_turns.turn_steps(db, turn)
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
        harness_turns.resume_turn(db, access, turn, approved=payload.approved, note=payload.note)
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


# --- Routines and Usage ---


@app.get("/api/v1/routines/digest")
def get_routine_digest(
    hours: int = 24,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    from .access import ReadScope
    from .routines import build_digest, format_digest

    scope = ReadScope(access.workspace_id, access.role)
    digest = build_digest(db, scope, since_hours=hours)
    return {
        "pending_proposals": digest.pending_proposals,
        "stale_knowledge": digest.stale_knowledge,
        "conflict_count": digest.conflict_count,
        "recent_approvals": digest.recent_approvals,
        "recent_sources": digest.recent_sources,
        "top_proposals": digest.top_proposals,
        "warnings": digest.warnings,
        "summary": digest.summary,
        "formatted": format_digest(digest),
    }


@app.get("/api/v1/gardening")
def get_gardening(scope: ReadScope = Depends(read_scope), db: Session = Depends(get_db)):
    """Approved knowledge that needs a person: due, expired, changed, conflicting,
    duplicated or unused. Scoped like every read."""
    from .gardening import build_gardening

    return build_gardening(db, scope).to_dict()


@app.post("/api/v1/routines/gardening/send")
def send_gardening_digest(
    force: bool = False,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Send the gardening report through Hermes (owners and admins).

    Not re-sent within `BRAIN_GARDENING_MIN_DAYS` unless `force`, so a weekly
    cron that fires twice does not message twice.
    """
    from .gardening import send_gardening

    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can send the gardening digest",
        )
    return send_gardening(
        db,
        ReadScope.of(access),
        workspace_name=access.workspace.name,
        force=force,
        actor=access,
    )


@app.get("/api/v1/usage")
def get_usage_summary(
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return usage_summary(db, scope)


@app.get("/api/v1/usage/top")
def get_usage_top(
    limit: int = 10,
    days: int = 30,
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return top_used(db, scope, limit=limit, since_days=days)


@app.get("/api/v1/usage/unused")
def get_usage_unused(
    limit: int = 10,
    scope: ReadScope = Depends(read_scope),
    db: Session = Depends(get_db),
):
    return unused_knowledge(db, scope, limit=limit)


@app.get("/api/v1/evaluation")
def run_jev_evaluation(
    access: WorkspaceAccess = Depends(resolve_access),
):
    """Run the held-out evaluation against the CONFIGURED Jev shadow URL.

    The URL comes from settings (BRAIN_JEV_URL), never from a query param:
    a caller-named URL would let any token make the server POST to arbitrary
    internal hosts or cloud metadata (SSRF). Admin-only, like proactivity.
    """
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can run the evaluation",
        )
    from .evaluation import run_evaluation

    report = run_evaluation(jev_url=settings.jev_url or None)
    return report.to_dict()


# --- answer evaluation: the person's own questions with known answers ----------


def _require_admin(access: WorkspaceAccess) -> None:
    # Questions name approved items and the runner reads with its own scope,
    # so the set is managed by those who can read everything it may cite.
    if not access.can_administer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or admin can manage the question set",
        )


def _eval_question_view(row: EvalQuestion) -> EvalQuestionRead:
    from .answer_eval import parse_ids

    return EvalQuestionRead(
        id=row.id,
        question=row.question,
        expected_ids=parse_ids(row.expected_ids),
        expect_abstain=row.expect_abstain,
        note=row.note or "",
        created_at=row.created_at,
    )


@app.get("/api/v1/eval/questions", response_model=list[EvalQuestionRead])
def list_eval_questions(
    access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)
):
    _require_admin(access)
    rows = db.scalars(
        select(EvalQuestion)
        .where(EvalQuestion.workspace_id == access.workspace_id)
        .order_by(EvalQuestion.created_at)
    )
    return [_eval_question_view(row) for row in rows]


@app.post("/api/v1/eval/questions", response_model=EvalQuestionRead, status_code=201)
def add_eval_question(
    payload: EvalQuestionCreate,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    from .answer_eval import readable_ids

    _require_admin(access)
    expected = list(dict.fromkeys(payload.expected_ids))
    if payload.expect_abstain and expected:
        raise HTTPException(status_code=422, detail="An abstain question has no expected items")
    if not payload.expect_abstain and not expected:
        raise HTTPException(
            status_code=422, detail="Name at least one expected item, or mark it as abstain"
        )
    unknown = set(expected) - readable_ids(db, ReadScope.of(access), expected)
    if unknown:
        raise HTTPException(status_code=409, detail="Expected items must be approved knowledge")
    row = EvalQuestion(
        id=new_id("evq"),
        workspace_id=access.workspace_id,
        question=payload.question.strip(),
        expected_ids=json.dumps(expected),
        expect_abstain=payload.expect_abstain,
        note=payload.note.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _eval_question_view(row)


@app.delete("/api/v1/eval/questions/{question_id}", status_code=204)
def delete_eval_question(
    question_id: str,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    _require_admin(access)
    row = db.get(EvalQuestion, question_id)
    if row is None or row.workspace_id != access.workspace_id:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()


@app.post("/api/v1/eval/run", response_model=EvalReport)
def run_answer_eval(
    payload: EvalRunRequest,
    access: WorkspaceAccess = Depends(resolve_access),
    db: Session = Depends(get_db),
):
    """Ask every question in the set and score the answers. The run is kept."""
    from dataclasses import asdict

    from .answer_eval import run_eval

    _require_admin(access)
    summary, results = run_eval(db, ReadScope.of(access), write=payload.write_answers)
    summary["write_answers"] = payload.write_answers
    run = EvalRun(
        id=new_id("evr"),
        workspace_id=access.workspace_id,
        label=payload.label.strip(),
        summary=json.dumps(summary),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return EvalReport(
        id=run.id,
        label=run.label,
        summary=summary,
        created_at=run.created_at,
        results=[asdict(result) for result in results],
    )


@app.get("/api/v1/eval/runs", response_model=list[EvalRunRead])
def list_eval_runs(
    access: WorkspaceAccess = Depends(resolve_access), db: Session = Depends(get_db)
):
    _require_admin(access)
    rows = db.scalars(
        select(EvalRun)
        .where(EvalRun.workspace_id == access.workspace_id)
        .order_by(EvalRun.created_at.desc())
        .limit(20)
    )
    return [
        EvalRunRead(
            id=row.id,
            label=row.label,
            summary=json.loads(row.summary or "{}"),
            created_at=row.created_at,
        )
        for row in rows
    ]


@app.get("/api/v1/messaging/status")
def messaging_status(
    access: WorkspaceAccess = Depends(resolve_access),
):
    from .messaging import HermesMessenger

    messenger = HermesMessenger()
    return {
        "configured": messenger.config.configured,
        "api_url": messenger.config.api_url or None,
        "channel": messenger.config.channel,
        "reachable": messenger.test_connection(),
    }


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
        # Hosted MCP + OAuth must never fall through to index.html.
        if path.startswith(
            (
                "mcp",
                "authorize",
                "token",
                "register",
                "revoke",
                ".well-known",
            )
        ):
            raise HTTPException(status_code=404, detail="Unknown endpoint")
        requested = frontend / path
        # Starlette unquotes %2f AFTER routing, so `path` can contain ../
        # segments that were invisible to the router. Without this containment
        # check the fallback serves arbitrary files — the project's .env
        # (owner token), the live SQLite database, anything the process can
        # read. Resolve first, then require the result to stay inside dist.
        try:
            resolved = requested.resolve()
            resolved.relative_to(frontend.resolve())
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail="Not found") from None
        if path and resolved.is_file():
            return FileResponse(resolved)
        return FileResponse(frontend / "index.html")
