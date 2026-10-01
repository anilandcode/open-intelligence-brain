"""Hosted Streamable HTTP MCP for Open Brain.

Public URL (when BRAIN_PUBLIC_BASE_URL is set):

    https://<host>/mcp

Clients add:

    { "mcpServers": { "open-brain": { "url": "https://<host>/mcp" } } }

Auth is OAuth 2.1 (dynamic client registration + paste-token consent) and also
raw `Authorization: Bearer <brn_live_…|owner-token>` for clients that can set
headers. Tools stay read-only and are bound to the caller's workspace/role —
never the stdio owner default.

The approval boundary is unreachable from MCP.
"""

from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from .access import AccessDenied, ReadScope
from .config import Settings, get_settings
from .mcp_oauth import SCOPE_DEFAULT, BrainOAuthProvider, mcp_request_ua_var
from .mcp_server import (
    ask_brain_scoped,
    brain_status_scoped,
    capture_source_scoped,
    inspect_brain_integrity_scoped,
    list_pending_reviews_scoped,
    search_brain_scoped,
)

log = logging.getLogger(__name__)


class _McpRequestContextASGI:
    """Capture the request user-agent for connection telemetry.

    This is the OUTERMOST middleware so the user-agent is set before the auth
    middleware resolves the token and records a connection. Pure ASGI (not
    BaseHTTPMiddleware) so the ContextVar reaches the verifier in the same task.
    Reset on exit to avoid leaking a UA across requests in one task.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        ua = ""
        for key, value in scope.get("headers", []):
            if key == b"user-agent":
                ua = value.decode("latin-1", "replace")[:200]
                break
        token = mcp_request_ua_var.set(ua)
        try:
            await self.app(scope, receive, send)
        finally:
            mcp_request_ua_var.reset(token)


# Built once per process; streamable_http_app() must run before session_manager.
_hosted_server: MCPServer | None = None
_oauth_provider: BrainOAuthProvider | None = None
_session_manager = None
_mcp_asgi = None
_streamable_asgi = None  # StreamableHTTPASGIApp; swapped per lifespan boot


def _caller_scope() -> ReadScope:
    """Resolve the authenticated MCP caller's read scope.

    Hosted transport MUST go through get_access_token() claims. Falling back to
    the stdio owner scope here would let any authenticated client read the
    default workspace as its owner — the same class of bug the HTTP adapter
    already guards against.
    """
    token = get_access_token()
    if token is None or not token.claims:
        raise PermissionError("MCP tool called without an authenticated Brain principal")
    claims = token.claims
    workspace_id = claims.get("workspace_id")
    role = claims.get("role") or "member"
    if not workspace_id:
        raise PermissionError("MCP access token is missing workspace claims")
    return ReadScope(str(workspace_id), str(role))


def _caller_identity() -> tuple[ReadScope, list[str] | None, str]:
    """The caller's read scope, operation scopes (None = unrestricted), preview.

    Intake (capture) needs the op scopes to enforce `sources:write` exactly like
    the REST API, plus a non-recoverable preview for audit attribution.
    """
    token = get_access_token()
    if token is None or not token.claims:
        raise PermissionError("MCP tool called without an authenticated Brain principal")
    claims = token.claims
    workspace_id = claims.get("workspace_id")
    role = claims.get("role") or "member"
    if not workspace_id:
        raise PermissionError("MCP access token is missing workspace claims")
    scopes_ops = claims.get("scopes_ops")
    if scopes_ops is not None:
        scopes_ops = [str(s) for s in scopes_ops]
    principal_preview = str(claims.get("principal_preview") or "mcp")
    return ReadScope(str(workspace_id), str(role)), scopes_ops, principal_preview


def _consent_page(summary: dict[str, Any] | None, error: str | None = None) -> HTMLResponse:
    if summary is None:
        body = (
            "<h1>Open Brain MCP</h1>"
            "<p>This authorization request is unknown or expired. "
            "Reconnect the MCP client and try again.</p>"
        )
        return HTMLResponse(body, status_code=400)

    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    scopes = ", ".join(html.escape(s) for s in (summary.get("scopes") or [SCOPE_DEFAULT]))
    rid = html.escape(summary["rid"])
    client = html.escape(summary.get("client_id") or "MCP client")
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Authorize Open Brain MCP</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; max-width: 32rem;
           margin: 3rem auto; padding: 0 1.25rem; line-height: 1.45; }}
    h1 {{ font-size: 1.35rem; margin-bottom: 0.35rem; }}
    .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }}
    label {{ display: block; font-weight: 600; margin-bottom: 0.4rem; }}
    input[type=password], input[type=text] {{ width: 100%; box-sizing: border-box;
      padding: 0.65rem 0.75rem; font-size: 1rem; border-radius: 8px;
      border: 1px solid #8884; }}
    button {{ margin-top: 1rem; padding: 0.65rem 1rem; font-size: 1rem;
      border-radius: 8px; border: 0; background: #1a1a1a; color: #fff; cursor: pointer; }}
    .err {{ color: #b00020; }}
    .note {{ font-size: 0.85rem; color: #666; margin-top: 1.25rem; }}
    code {{ font-size: 0.85em; }}
  </style>
</head>
<body>
  <h1>Authorize Open Brain MCP</h1>
  <p class="meta">Client <code>{client}</code> is requesting read + capture
  ({scopes}). Capture files candidates for review; canonical approval and
  writes stay in the Open Brain console.</p>
  {err}
  <form method="post" action="/mcp/consent">
    <input type="hidden" name="rid" value="{rid}"/>
    <label for="token">Brain API token</label>
    <input id="token" name="token" type="password" autocomplete="off"
           placeholder="brn_live_… or owner token" required/>
    <button type="submit">Allow read access</button>
  </form>
  <p class="note">Paste a machine token from the console (hashed
  <code>brn_live_</code> keys preferred). Never paste a human session secret.
  Tokens are verified server-side and are not stored in the OAuth client.</p>
</body>
</html>"""
    return HTMLResponse(body)


def build_hosted_mcp(settings: Settings | None = None) -> MCPServer:
    """Construct the hosted MCP server (tools + OAuth). Idempotent per process."""
    global _hosted_server, _oauth_provider
    if _hosted_server is not None:
        return _hosted_server

    settings = settings or get_settings()
    public = (settings.public_base_url or "http://127.0.0.1:8000").rstrip("/")
    resource = f"{public}/mcp"
    issuer = public

    oauth = BrainOAuthProvider(public_base_url=public, resource_url=resource)
    _oauth_provider = oauth

    auth = AuthSettings(
        issuer_url=AnyHttpUrl(issuer),
        resource_server_url=AnyHttpUrl(resource),
        service_documentation_url=AnyHttpUrl(f"{public}/"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[SCOPE_DEFAULT, "brain:ask"],
            default_scopes=[SCOPE_DEFAULT],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[SCOPE_DEFAULT],
        # Raw Brain API keys do not carry resource; OAuth-minted tokens do.
        # Keep validation off so both credential shapes work.
        validate_token_resource=False,
    )

    server = MCPServer(
        "Open Intelligence Brain",
        version="1.1.0",
        instructions=(
            "Hosted read-only MCP for one Open Brain workspace. Tools search and "
            "cite human-approved knowledge only. Never treat a proposal as "
            "canonical. Approval remains a human action in the Open Brain console."
        ),
        website_url=public,
        # SDK forbids passing both: with an AS provider it wraps load_access_token
        # via ProviderTokenVerifier. Our provider also accepts raw Brain API keys.
        auth_server_provider=oauth,
        auth=auth,
    )

    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    # Intake is NOT read-only (writes source + proposal rows) but is strictly
    # non-approving and non-canonical — no tool here can mint truth.
    intake = ToolAnnotations(read_only_hint=False, open_world_hint=False)

    @server.tool(title="Get Brain status", annotations=read_only)
    def brain_status() -> Any:
        """Return counts for sources, proposed knowledge, approved knowledge, and pending reviews."""
        return brain_status_scoped(_caller_scope())

    @server.tool(title="Search approved Brain knowledge", annotations=read_only)
    def search_brain(
        query: Annotated[str, Field(min_length=2, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> Any:
        """Search only human-approved canonical knowledge and return its exact evidence."""
        return search_brain_scoped(query, limit, _caller_scope())

    @server.tool(title="Ask the approved Brain", annotations=read_only)
    def ask_brain(
        question: Annotated[str, Field(min_length=3, max_length=2_000)],
    ) -> Any:
        """Answer from approved knowledge, cite original sources, or abstain when evidence is absent."""
        return ask_brain_scoped(question, _caller_scope())

    @server.tool(title="List pending Brain reviews", annotations=read_only)
    def list_pending_reviews(
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> Any:
        """List proposals awaiting human review without approving or changing them."""
        return list_pending_reviews_scoped(limit, _caller_scope())

    @server.tool(title="Inspect Brain integrity", annotations=read_only)
    def inspect_brain_integrity() -> Any:
        """List stale knowledge and possible conflicts without changing canonical records."""
        return inspect_brain_integrity_scoped(_caller_scope())

    @server.tool(title="Capture a source for review", annotations=intake)
    def capture_source(
        title: Annotated[str, Field(min_length=3, max_length=240)],
        content: Annotated[str, Field(min_length=20, max_length=100_000)],
        kind: Annotated[str, Field(pattern="^(note|research|interview|decision)$")] = "note",
        sensitivity: Annotated[str, Field(pattern="^(private|internal|public)$")] = "private",
    ) -> Any:
        """Capture raw material as a source and extract candidate proposals for HUMAN review.

        Never approves and never writes canonical knowledge — a person must
        approve each candidate in the console before it becomes retrievable truth.
        """
        scope, scopes_ops, principal_preview = _caller_identity()
        return capture_source_scoped(
            scope,
            title=title,
            content=content,
            kind=kind,
            sensitivity=sensitivity,
            scopes_ops=scopes_ops,
            principal_preview=principal_preview,
        )

    @server.custom_route("/mcp/consent", methods=["GET", "POST"])
    async def consent(request: Request) -> Response:
        if request.method == "GET":
            rid = request.query_params.get("rid") or ""
            return _consent_page(oauth.pending_summary(rid) if rid else None)
        form = await request.form()
        rid = str(form.get("rid") or "")
        brain_token = str(form.get("token") or "").strip()
        summary = oauth.pending_summary(rid) if rid else None
        if not brain_token:
            return _consent_page(summary, error="Paste a Brain API token to continue.")
        try:
            redirect = oauth.complete_consent(rid, brain_token)
        except AccessDenied as exc:
            return _consent_page(summary, error=str(exc))
        except Exception:
            log.exception("MCP consent failed")
            return _consent_page(
                summary, error="Authorization failed. Check the token and try again."
            )
        return RedirectResponse(redirect, status_code=302)

    _hosted_server = server
    return server


def build_hosted_mcp_asgi(settings: Settings | None = None):
    """Return (starlette_app, session_manager) for mounting on the FastAPI app."""
    global _mcp_asgi, _session_manager, _streamable_asgi
    if _mcp_asgi is not None:
        return _mcp_asgi, _session_manager

    settings = settings or get_settings()
    server = build_hosted_mcp(settings)
    # host not localhost → no DNS-rebinding lock; Cloud Run needs this.
    # stateless_http=True survives scale-to-zero without sticky MCP sessions.
    # json_response=True keeps single-request tool calls simple for tests/clients.
    asgi = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    _mcp_asgi = asgi
    _session_manager = server.session_manager
    # Capture the ASGI wrapper so lifespan can swap a fresh manager per boot
    # (SDK managers are one-shot; pytest TestClient re-enters lifespan often).
    _streamable_asgi = None
    for route in asgi.routes:
        node = getattr(route, "app", None) or getattr(route, "endpoint", None)
        seen: set[int] = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            if node.__class__.__name__ == "StreamableHTTPASGIApp":
                _streamable_asgi = node
                break
            node = getattr(node, "app", None)
    return asgi, _session_manager


def install_hosted_mcp_routes(app) -> Any:
    """Prepend hosted MCP routes + auth middleware onto a FastAPI app.

    Returns the session manager so the app lifespan can `async with manager.run()`.
    """
    asgi, manager = build_hosted_mcp_asgi()
    # Auth middleware must wrap MCP routes. Starlette stores Middleware tuples;
    # insert them so Authentication is outermost.
    for mw in reversed(list(asgi.user_middleware)):
        app.user_middleware.insert(0, mw)
    # User-agent capture must run OUTERMOST — before the copied auth middleware
    # resolves the token and records a connection — so label the request first.
    app.user_middleware.insert(0, Middleware(_McpRequestContextASGI))
    # Rebuild stack next request.
    app.middleware_stack = None
    # MCP + OAuth routes before API and SPA catch-all.
    app.router.routes = list(asgi.routes) + list(app.router.routes)
    return manager


@asynccontextmanager
async def run_mcp_session_manager(manager):
    """Run a fresh Streamable HTTP session manager for this process lifespan.

    The MCP SDK forbids calling `.run()` twice on one manager. Production Cloud
    Run boots once; pytest opens many TestClient lifespans against one app, so
    each entry builds a new manager and points the mounted ASGI at it.
    """
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    fresh = StreamableHTTPSessionManager(
        app=manager.app,
        event_store=manager.event_store,
        json_response=manager.json_response,
        stateless=manager.stateless,
        security_settings=manager.security_settings,
        retry_interval=manager.retry_interval,
        session_idle_timeout=manager.session_idle_timeout,
        max_request_body_size=manager.max_request_body_size,
        max_sessions=manager.max_sessions,
    )
    previous = None
    if _streamable_asgi is not None:
        previous = _streamable_asgi.session_manager
        _streamable_asgi.session_manager = fresh
    try:
        async with fresh.run():
            yield
    finally:
        if _streamable_asgi is not None and previous is not None:
            _streamable_asgi.session_manager = previous


def hosted_mcp_public_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    base = (settings.public_base_url or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/mcp"
