"""HTTP transport for the MCP server.

The existing mcp_server.py runs as a stdio process — fine for local agents but
unreachable from a remote host. This module mounts an SSE (Server-Sent Events)
endpoint on the FastAPI app so a remote Hermes, Codex, or Claude Code client
can discover and call the same read-only tools over HTTP.

Only read-only tools are exposed: search_brain, ask_brain, brain_status,
list_pending_reviews, and inspect_brain_integrity. The approval boundary
stays on the API side and is unreachable from MCP.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .access import AccessDenied, WorkspaceAccess, resolve_workspace
from .database import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP"])


def _resolve_access(
    x_brain_token: str = Header(default=""),
    x_brain_workspace: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> WorkspaceAccess:
    """Authenticate the caller for MCP endpoints."""
    try:
        return resolve_workspace(db, x_brain_token, x_brain_workspace)
    except AccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


# The MCP tool implementations take an explicit ReadScope, so the HTTP
# transport passes the CALLER's resolved scope — never the stdio server's
# default owner scope. That is the whole point of this transport: a member
# token gets member reach, a token granted only to another workspace gets
# its own workspace, exactly like the REST API.
from .access import ReadScope  # noqa: E402
from .mcp_server import (  # noqa: E402
    ask_brain_scoped,
    brain_status_scoped,
    inspect_brain_integrity_scoped,
    list_pending_reviews_scoped,
    search_brain_scoped,
)

TOOL_DEFS = [
    {
        "name": "brain_status",
        "description": "Get the current status of the Brain: source count, proposal count, canonical knowledge count, and engine health.",
        "parameters": {},
    },
    {
        "name": "search_brain",
        "description": "Search canonical knowledge by keyword. Returns matching items with source citations.",
        "parameters": {
            "query": {"type": "string", "description": "Search query", "required": True},
            "limit": {"type": "integer", "description": "Max results (default 10)", "required": False},
        },
    },
    {
        "name": "ask_brain",
        "description": "Ask a question across approved knowledge. Returns a grounded answer with citations, or abstains if the canon does not contain enough evidence.",
        "parameters": {
            "question": {"type": "string", "description": "Question to ask", "required": True},
        },
    },
    {
        "name": "list_pending_reviews",
        "description": "List proposals awaiting human review. Returns the queue with source excerpts.",
        "parameters": {
            "limit": {"type": "integer", "description": "Max results (default 10)", "required": False},
        },
    },
    {
        "name": "inspect_brain_integrity",
        "description": "Check for stale sources and possible conflicts in canonical knowledge.",
        "parameters": {},
    },
]

TOOL_NAMES = {t["name"] for t in TOOL_DEFS}


def _call_tool(name: str, params: dict, scope: ReadScope) -> Any:
    """Dispatch an MCP tool call to the matching implementation.

    `scope` is the resolved caller's read scope — every implementation is
    bound to it, so an HTTP caller can never read wider than the REST API
    would allow the same token.
    """
    if name == "brain_status":
        return brain_status_scoped(scope).model_dump()
    elif name == "search_brain":
        return search_brain_scoped(
            query=params.get("query", ""),
            limit=params.get("limit", 10),
            scope=scope,
        ).model_dump()
    elif name == "ask_brain":
        return ask_brain_scoped(
            question=params.get("question", ""), scope=scope
        ).model_dump()
    elif name == "list_pending_reviews":
        return list_pending_reviews_scoped(
            limit=params.get("limit", 10), scope=scope
        ).model_dump()
    elif name == "inspect_brain_integrity":
        return inspect_brain_integrity_scoped(scope).model_dump()
    else:
        return {"error": f"Unknown tool: {name}"}


@router.get("/tools")
def list_tools(
    access: WorkspaceAccess = Depends(_resolve_access),
):
    """List available MCP tools and their schemas."""
    return {"tools": TOOL_DEFS}


@router.post("/call")
async def call_tool(
    request: Request,
    access: WorkspaceAccess = Depends(_resolve_access),
):
    """Call an MCP tool by name with parameters.

    Expects JSON body: {"tool": "tool_name", "params": {...}}
    Returns the tool result as JSON.

    The caller's resolved access is turned into a ReadScope here, and every
    tool implementation is bound to it — the same narrowing the REST API
    applies to the same token.
    """
    body = await request.json()
    tool_name = body.get("tool", "")
    params = body.get("params", {})

    if tool_name not in TOOL_NAMES:
        return {"error": f"Unknown tool: {tool_name}. Available: {sorted(TOOL_NAMES)}"}

    scope = ReadScope.of(access)
    try:
        result = _call_tool(tool_name, params, scope)
        return {"tool": tool_name, "result": result}
    except Exception as exc:
        log.warning("MCP tool %s failed: %s", tool_name, exc)
        return {"tool": tool_name, "error": str(exc)}


@router.get("/sse")
async def sse_endpoint(
    request: Request,
    access: WorkspaceAccess = Depends(_resolve_access),
):
    """SSE transport for MCP clients.

    Clients connect here and receive tool listings. To call a tool, they
    POST to /api/v1/mcp/call. This endpoint exists for discovery and
    keep-alive — the MCP SSE spec requires a persistent connection for
    server-initiated messages, but our tools are request/response, so the
    SSE stream is primarily for compatibility with MCP clients that expect it.
    """
    async def event_stream():
        yield f"event: tools\ndata: {json.dumps({'tools': TOOL_DEFS})}\n\n"
        import asyncio
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(30)
            yield "event: ping\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )