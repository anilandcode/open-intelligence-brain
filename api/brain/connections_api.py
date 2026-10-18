"""Connections hub + staged action queue (mcp-auth-bridge integration).

Routes:
    GET   /api/v1/connections                    connected accounts (masked)
    POST  /api/v1/connections/link               start an OAuth connect flow
    PATCH /api/v1/connections/{account_id}       rename an alias
    POST  /api/v1/oauth/verify                   redeem the bridge's session_uri
    GET   /api/v1/staged-actions                 the approval queue
    POST  /api/v1/staged-actions                 stage a mutating tool call
    POST  /api/v1/staged-actions/{id}/approve    execute exactly once
    POST  /api/v1/staged-actions/{id}/reject     discard

Identity follows the repo's single resolver (one credential class per
request). The bridge user key is derived from the resolved actor, so a human
and a machine credential never share connected accounts.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .access import WorkspaceAccess, actor_ref, require_scope, resolve_request_access
from .bridge_client import BridgeClient, BridgeError
from .config import get_settings
from .connections import StagedAction
from .connections_schemas import (
    AliasUpdate,
    ConnectionRead,
    LinkStartRead,
    LinkStartRequest,
    StagedActionCreate,
    StagedActionRead,
    VerifyRead,
    VerifyRequest,
)
from .database import get_db

logger = logging.getLogger("brain.connections")

router = APIRouter(prefix="/api/v1", tags=["Connections"])

WRITE_TOOLS = {"LINKEDIN_CREATE_POST", "X_CREATE_POST", "X_DELETE_POST", "OPENBRAIN_PROXY_EXECUTE"}


class BridgeNotConfigured(RuntimeError):
    pass


def get_bridge() -> BridgeClient:
    settings = get_settings()
    if not settings.mab_bridge_url or not settings.mab_service_token:
        raise BridgeNotConfigured("mab bridge is not configured")
    return BridgeClient(settings.mab_bridge_url, settings.mab_service_token)


def _resolve_access(
    db: Session = Depends(get_db),
    x_brain_token: str = Header(""),
    x_brain_session: str = Header(""),
    x_brain_workspace: str | None = Header(None),
) -> WorkspaceAccess:
    # Same shape as studio_api: the shared resolver is a plain function, so
    # each router wraps it in its own FastAPI dependency exactly once.
    return resolve_request_access(db, x_brain_token, x_brain_session, x_brain_workspace)


def _bridge_user(access: WorkspaceAccess) -> str:
    return f"{access.actor_kind}:{access.actor_id or access.principal}"


def _connection_read(raw: dict) -> ConnectionRead:
    return ConnectionRead(
        connected_account_id=str(raw.get("connected_account_id", "")),
        toolkit_slug=str(raw.get("toolkit_slug", "")),
        alias=str(raw.get("alias", "")),
        provider_account_id=str(raw.get("provider_account_id", "")),
        display_name=str(raw.get("display_name", "")),
        status=str(raw.get("status", "")),
        expires_at=raw.get("expires_at"),
        credential_state="present" if raw.get("access_token") else "none",
    )


def _staged_read(row: StagedAction) -> StagedActionRead:
    try:
        payload = json.loads(row.payload_json or "{}")
    except ValueError:
        payload = {}
    return StagedActionRead(
        id=row.id,
        tool_name=row.tool_name,
        account_alias=row.account_alias,
        payload=payload if isinstance(payload, dict) else {},
        status=row.status,
        result_urn=row.result_urn,
        error=row.error,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@router.get("/connections", response_model=list[ConnectionRead])
def list_connections(
    access: WorkspaceAccess = Depends(_resolve_access), db: Session = Depends(get_db)
) -> list[ConnectionRead]:
    try:
        bridge = get_bridge()
    except BridgeNotConfigured:
        raise HTTPException(503, "bridge_not_configured") from None
    try:
        raw = bridge.list_accounts(_bridge_user(access))
    except BridgeError as exc:
        raise HTTPException(502 if exc.status >= 500 else exc.status, exc.code) from exc
    return [_connection_read(item) for item in raw]


@router.post("/connections/link", response_model=LinkStartRead)
def start_link(
    body: LinkStartRequest,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> LinkStartRead:
    require_scope(access, "connections:write")
    settings = get_settings()
    # The provider must send the browser to the BROKER's callback: the broker
    # exchanges the code and then redirects to Open Brain's verifier with the
    # single-use session_uri.
    redirect_uri = f"{settings.mab_bridge_url.rstrip('/')}/oauth/callback"
    try:
        bridge = get_bridge()
        result = bridge.start_link(
            user_id=_bridge_user(access),
            toolkit_slug=body.toolkit_slug,
            alias=body.alias,
            redirect_uri=redirect_uri,
        )
    except BridgeNotConfigured:
        raise HTTPException(503, "bridge_not_configured") from None
    except BridgeError as exc:
        raise HTTPException(502, exc.code) from exc
    return LinkStartRead(
        authorization_url=str(result.get("authorization_url", "")),
        session_uri=str(result.get("session_uri", "")),
    )


@router.patch("/connections/{account_id}")
def rename_connection(
    account_id: str,
    body: AliasUpdate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> dict:
    require_scope(access, "connections:write")
    try:
        get_bridge().rename_alias(account_id, body.alias)
    except BridgeNotConfigured:
        raise HTTPException(503, "bridge_not_configured") from None
    except BridgeError as exc:
        if exc.status == 409:
            raise HTTPException(409, "alias_taken") from exc
        raise HTTPException(502, exc.code) from exc
    return {"connected_account_id": account_id, "alias": body.alias}


@router.post("/oauth/verify", response_model=VerifyRead)
def verify_link(
    body: VerifyRequest,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> VerifyRead:
    """Redeem the bridge's single-use session_uri as the signed-in caller."""
    try:
        bridge = get_bridge()
        result = bridge.complete_auth(session_uri=body.session_uri, user_id=_bridge_user(access))
    except BridgeNotConfigured:
        raise HTTPException(503, "bridge_not_configured") from None
    except BridgeError as exc:
        if exc.status == 404:
            raise HTTPException(404, "not_found") from exc
        if exc.status == 400:
            raise HTTPException(400, exc.code) from exc
        raise HTTPException(502, exc.code) from exc
    return VerifyRead(
        connected_account_id=str(result.get("connected_account_id", "")),
        status=str(result.get("status", "")),
    )


@router.get("/staged-actions", response_model=list[StagedActionRead])
def list_staged(
    access: WorkspaceAccess = Depends(_resolve_access), db: Session = Depends(get_db)
) -> list[StagedActionRead]:
    rows = db.scalars(
        select(StagedAction)
        .where(StagedAction.workspace_id == access.workspace_id)
        .order_by(StagedAction.created_at.desc())
    ).all()
    return [_staged_read(row) for row in rows]


@router.post("/staged-actions", response_model=StagedActionRead, status_code=201)
def stage_action(
    body: StagedActionCreate,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> StagedActionRead:
    require_scope(access, "reviews:write")
    if body.tool_name not in WRITE_TOOLS:
        raise HTTPException(400, "tool_not_staged")
    kind, actor = actor_ref(access)
    row = StagedAction(
        id=f"sta_{uuid4().hex}",
        workspace_id=access.workspace_id,
        tool_name=body.tool_name,
        account_alias=body.account_alias,
        payload_json=json.dumps(body.payload, sort_keys=True),
        status="PENDING",
        created_by_kind=kind,
        created_by_id=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _staged_read(row)


@router.post("/staged-actions/{action_id}/approve", response_model=StagedActionRead)
def approve_action(
    action_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> StagedActionRead:
    require_scope(access, "reviews:write")
    row = db.get(StagedAction, action_id)
    if row is None or row.workspace_id != access.workspace_id:
        raise HTTPException(404, "not_found")
    # Exactly-once: only one caller can move PENDING -> EXECUTING.
    claimed = db.execute(
        update(StagedAction)
        .where(StagedAction.id == action_id, StagedAction.status == "PENDING")
        .values(status="EXECUTING")
    )
    db.commit()
    if claimed.rowcount != 1:
        raise HTTPException(409, "already_decided")
    try:
        bridge = get_bridge()
        result = bridge.call_tool(
            user_id=_bridge_user(access),
            pinned_aliases=[row.account_alias],
            tool_name=row.tool_name,
            arguments={**json.loads(row.payload_json or "{}"), "account": row.account_alias},
        )
        urn = _extract_urn(result)
        row.status = "EXECUTED"
        row.result_urn = urn
    except BridgeNotConfigured:
        row.status = "PENDING"
        db.commit()
        raise HTTPException(503, "bridge_not_configured") from None
    except BridgeError as exc:
        row.status = "FAILED"
        row.error = exc.code
    kind, actor = actor_ref(access)
    row.decided_by_kind = kind
    row.decided_by_id = actor
    row.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _staged_read(row)


@router.post("/staged-actions/{action_id}/reject", response_model=StagedActionRead)
def reject_action(
    action_id: str,
    access: WorkspaceAccess = Depends(_resolve_access),
    db: Session = Depends(get_db),
) -> StagedActionRead:
    require_scope(access, "reviews:write")
    row = db.get(StagedAction, action_id)
    if row is None or row.workspace_id != access.workspace_id:
        raise HTTPException(404, "not_found")
    claimed = db.execute(
        update(StagedAction)
        .where(StagedAction.id == action_id, StagedAction.status == "PENDING")
        .values(status="REJECTED")
    )
    db.commit()
    if claimed.rowcount != 1:
        raise HTTPException(409, "already_decided")
    kind, actor = actor_ref(access)
    row.decided_by_kind = kind
    row.decided_by_id = actor
    row.decided_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _staged_read(row)


def _extract_urn(result: dict) -> str:
    content = (
        result.get("result", {}).get("content") if isinstance(result.get("result"), dict) else None
    )
    if isinstance(content, list) and content and isinstance(content[0], dict):
        try:
            payload = json.loads(str(content[0].get("text", "{}")))
        except ValueError:
            return ""
        if isinstance(payload, dict):
            for key in ("result_urn", "id", "urn"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
            data = payload.get("data")
            if isinstance(data, dict):
                value = data.get("id")
                if isinstance(value, str):
                    return value
    return ""
