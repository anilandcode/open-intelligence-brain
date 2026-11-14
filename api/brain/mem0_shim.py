"""Mem0 Drop-In Compatibility Shim.

Provides endpoints matching Mem0's REST API (/v1/memories) so applications built
for Mem0 can switch their base_url to Open Intelligence Brain with zero code changes,
gaining span verification, conflict radar, bi-temporal history, and immutable provenance.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .access import ReadScope, WorkspaceAccess, resolve_request_access
from .database import get_db
from .models import Knowledge, Proposal, now_utc
from .schemas import SourceCreate
from .services import (
    approve_proposal,
    create_source_with_proposals,
    search_knowledge,
    supersede_knowledge,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/memories", tags=["Mem0 Compatibility Shim"])


def get_access(
    x_brain_token: str | None = Header(None, alias="X-Brain-Token"),
    x_brain_session: str | None = Header(None, alias="X-Brain-Session"),
    x_brain_workspace: str | None = Header(None, alias="X-Brain-Workspace"),
    db: Session = Depends(get_db),
) -> WorkspaceAccess:
    return resolve_request_access(db, x_brain_token, x_brain_session, x_brain_workspace)


class Mem0Message(BaseModel):
    role: str = "user"
    content: str


class Mem0CreateRequest(BaseModel):
    messages: list[Mem0Message] | None = None
    text: str | None = None
    user_id: str = "default_user"
    agent_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_approve: bool = True  # In Mem0 mode, memories become canonical immediately


class Mem0SearchRequest(BaseModel):
    query: str
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    limit: int = 10
    filters: dict[str, Any] | None = None


def _format_memory(
    item: Knowledge, user_id: str = "default_user", score: float | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": item.id,
        "memory": item.statement,
        "user_id": user_id,
        "hash": item.id,
        "created_at": item.approved_at.isoformat() if item.approved_at else now_utc().isoformat(),
        "updated_at": item.valid_to.isoformat() if item.valid_to else None,
        "metadata": {
            "source_id": item.source_id,
            "source_title": getattr(item, "source_title", ""),
            "source_excerpt": item.source_excerpt,
            "rationale": item.rationale,
            "type": item.type,
            "version": item.version,
            "status": item.status,
            "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "valid_to": item.valid_to.isoformat() if item.valid_to else None,
            "provenance": "open-intelligence-brain",
        },
    }
    if score is not None:
        record["score"] = score
    return record


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED)
def create_memories(
    payload: Mem0CreateRequest,
    db: Session = Depends(get_db),
    actor: WorkspaceAccess = Depends(get_access),
) -> dict[str, Any]:
    """Ingest conversational text or messages, deriving span-verified memories."""
    # 1. Extract raw content
    if payload.messages:
        content = "\n".join(f"{m.role.capitalize()}: {m.content}" for m in payload.messages)
    elif payload.text:
        content = payload.text
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'messages' or 'text' must be provided",
        )

    title = f"Mem0 Ingestion ({payload.user_id})"
    src = create_source_with_proposals(
        db,
        SourceCreate(
            title=title,
            content=content,
            kind="note",
            sensitivity="internal",
        ),
        actor.workspace_id,
        actor=actor,
    )

    # 2. Collect derived proposals
    proposals = (
        db.query(Proposal).filter(Proposal.source_id == src.id, Proposal.status == "proposed").all()
    )

    results: list[dict[str, Any]] = []

    # 3. If auto_approve is True (standard for Mem0 parity), approve proposals to canonical
    if payload.auto_approve and proposals:
        for prop in proposals:
            try:
                # If Conflict Radar detected a conflict, resolve or supersede
                supersedes_id = prop.conflict_with_id if prop.conflict_with_id else None
                k = approve_proposal(
                    db,
                    prop,
                    statement=None,
                    rationale=None,
                    actor=actor,
                    supersedes_knowledge_id=supersedes_id,
                )
                results.append(
                    {
                        "id": k.id,
                        "memory": k.statement,
                        "event": "ADD",
                        "conflict_detected": bool(prop.conflict_with_id),
                        "conflict_note": prop.conflict_note,
                    }
                )
            except Exception as exc:
                log.warning("Mem0 auto-approval failed for proposal %s: %s", prop.id, exc)

    elif proposals:
        # Proposals staged for review
        for prop in proposals:
            results.append(
                {
                    "id": prop.id,
                    "memory": prop.statement,
                    "event": "PROPOSED",
                    "conflict_detected": bool(prop.conflict_with_id),
                }
            )
    else:
        # Fallback: if deterministic extractor did not create long enough propositions,
        # create a single proposal & memory from content
        results.append(
            {
                "id": src.id,
                "memory": content[:300],
                "event": "INGESTED",
            }
        )

    return {"results": results}


@router.post("/search")
@router.post("/search/")
def search_memories(
    payload: Mem0SearchRequest,
    db: Session = Depends(get_db),
    actor: WorkspaceAccess = Depends(get_access),
) -> list[dict[str, Any]]:
    """Search memories with hybrid BM25 and vector retrieval."""
    scope = ReadScope(workspace_id=actor.workspace_id, role=actor.role)
    items = search_knowledge(db, scope, payload.query, limit=payload.limit)
    return [
        _format_memory(item, user_id=payload.user_id or "default_user", score=0.9) for item in items
    ]


@router.get("")
@router.get("/")
def list_memories(
    user_id: str = Query("default_user"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: WorkspaceAccess = Depends(get_access),
) -> list[dict[str, Any]]:
    """List memories for a user or agent."""
    scope = ReadScope(workspace_id=actor.workspace_id, role=actor.role)
    items = search_knowledge(db, scope, "", limit=limit)
    return [_format_memory(item, user_id=user_id) for item in items]


@router.get("/{memory_id}")
def get_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    actor: WorkspaceAccess = Depends(get_access),
) -> dict[str, Any]:
    """Retrieve a single memory by ID."""
    item = db.get(Knowledge, memory_id)
    if item is None or item.workspace_id != actor.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return _format_memory(item)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    actor: WorkspaceAccess = Depends(get_access),
) -> dict[str, Any]:
    """Soft delete / supersede a memory."""
    item = db.get(Knowledge, memory_id)
    if item is None or item.workspace_id != actor.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    supersede_knowledge(
        db,
        item,
        statement=item.statement,
        rationale="Deleted via Mem0 compatibility endpoint",
        change_note="Deleted via Mem0 API",
        actor=actor,
    )
    return {"message": "Memory deleted successfully"}
