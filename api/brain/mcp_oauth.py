"""OAuth 2.1 provider for the hosted MCP endpoint.

Clients (Cursor, Claude Connectors, ChatGPT) open the authorization URL, the
human pastes a Brain machine token (`brn_live_…` or owner token), and the
provider issues short-lived access tokens. Those tokens are what the Streamable
HTTP transport presents as `Authorization: Bearer …`.

Direct Brain API keys are also accepted as Bearer tokens (no OAuth round-trip)
so agents that can set headers do not need the browser flow.

Storage is Postgres/SQLite via SQLAlchemy so Cloud Run cold starts do not wipe
issued tokens the way an in-memory map would.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .access import AccessDenied, resolve_workspace, token_preview
from .database import Base, SessionLocal
from .models import now_utc

log = logging.getLogger(__name__)

ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 8  # 8 hours
REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
AUTH_CODE_TTL_SECONDS = 60 * 10
PENDING_TTL_SECONDS = 60 * 15
SCOPE_DEFAULT = "brain:read"


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now_ts() -> int:
    return int(time.time())


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    redirect_uris_json: Mapped[str] = mapped_column(Text, default="[]")
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(40), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class McpOAuthPending(Base):
    """Authorize request waiting for the human to paste a Brain token."""

    __tablename__ = "mcp_oauth_pending"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    params_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class McpOAuthCode(Base):
    __tablename__ = "mcp_oauth_codes"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    code_challenge: Mapped[str] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(String(500))
    redirect_uri_provided_explicitly: Mapped[int] = mapped_column(Integer, default=1)
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    resource: Mapped[str | None] = mapped_column(String(500), nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    principal_preview: Mapped[str] = mapped_column(String(80))
    scopes_ops_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class McpOAuthTokenRow(Base):
    __tablename__ = "mcp_oauth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    resource: Mapped[str | None] = mapped_column(String(500), nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    principal_preview: Mapped[str] = mapped_column(String(80))
    scopes_ops_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


@dataclass(frozen=True)
class BrainPrincipal:
    workspace_id: str
    role: str
    principal_preview: str
    scopes_ops: list[str] | None  # hashed credential ops; None = unrestricted legacy


def resolve_brain_principal(db: Session, brain_token: str) -> BrainPrincipal:
    access = resolve_workspace(db, brain_token, None)
    preview = token_preview(access.principal) if len(access.principal) > 12 else access.principal
    return BrainPrincipal(
        workspace_id=access.workspace.id,
        role=access.role,
        principal_preview=preview,
        scopes_ops=list(access.scopes) if access.scopes is not None else None,
    )


def access_token_from_principal(
    *,
    token: str,
    client_id: str,
    principal: BrainPrincipal,
    scopes: list[str],
    expires_at: int | None,
    resource: str | None,
) -> AccessToken:
    return AccessToken(
        token=token,
        client_id=client_id,
        scopes=scopes or [SCOPE_DEFAULT],
        expires_at=expires_at,
        resource=resource,
        subject=principal.principal_preview,
        claims={
            "workspace_id": principal.workspace_id,
            "role": principal.role,
            "principal_preview": principal.principal_preview,
            "scopes_ops": principal.scopes_ops,
            "iss": "open-brain",
        },
    )


class BrainTokenVerifier:
    """Accept OAuth-issued tokens OR raw Brain API keys as Bearer credentials."""

    def __init__(self, resource_url: str | None = None) -> None:
        self.resource_url = resource_url

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not token.strip():
            return None
        token = token.strip()

        # 1) Opaque OAuth access token
        th = _hash_secret(token)
        with SessionLocal() as db:
            row = db.get(McpOAuthTokenRow, th)
            if row is not None:
                if (
                    row.expires_at.replace(tzinfo=UTC)
                    if row.expires_at.tzinfo is None
                    else row.expires_at
                ):
                    exp = row.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=UTC)
                    if exp < datetime.now(UTC):
                        return None
                scopes = json.loads(row.scopes_json or "[]")
                scopes_ops = json.loads(row.scopes_ops_json) if row.scopes_ops_json else None
                principal = BrainPrincipal(
                    workspace_id=row.workspace_id,
                    role=row.role,
                    principal_preview=row.principal_preview,
                    scopes_ops=scopes_ops,
                )
                exp_ts = int(
                    (
                        row.expires_at.replace(tzinfo=UTC)
                        if row.expires_at.tzinfo is None
                        else row.expires_at
                    ).timestamp()
                )
                return access_token_from_principal(
                    token=token,
                    client_id=row.client_id,
                    principal=principal,
                    scopes=scopes,
                    expires_at=exp_ts,
                    resource=row.resource or self.resource_url,
                )

        # 2) Raw Brain machine credential (owner token or brn_live_…)
        try:
            with SessionLocal() as db:
                principal = resolve_brain_principal(db, token)
        except AccessDenied:
            return None
        except Exception:
            log.exception("Brain token verification failed")
            return None

        return access_token_from_principal(
            token=token,
            client_id="brain-api-key",
            principal=principal,
            scopes=[SCOPE_DEFAULT],
            expires_at=None,
            resource=self.resource_url,
        )


class BrainOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, *, public_base_url: str, resource_url: str) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self.resource_url = resource_url.rstrip("/")
        self.consent_path = "/mcp/consent"

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with SessionLocal() as db:
            row = db.get(McpOAuthClient, client_id)
            if row is None:
                return None
            redirect_uris = [AnyUrl(u) for u in json.loads(row.redirect_uris_json or "[]")]
            return OAuthClientInformationFull(
                client_id=row.client_id,
                client_secret=None,  # never re-emit secret
                redirect_uris=redirect_uris,
                token_endpoint_auth_method=row.token_endpoint_auth_method or "none",  # type: ignore[arg-type]
                client_name=row.client_name,
                # Hosted MCP is read-only: every dynamic client is allowed brain:read.
                scope=SCOPE_DEFAULT,
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
            )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise RegistrationError(
                error="invalid_client_metadata", error_description="client_id required"
            )
        redirect_uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not redirect_uris:
            raise RegistrationError(
                error="invalid_redirect_uri", error_description="redirect_uris required"
            )
        secret_hash = _hash_secret(client_info.client_secret) if client_info.client_secret else None
        with SessionLocal() as db:
            existing = db.get(McpOAuthClient, client_info.client_id)
            if existing is not None:
                existing.redirect_uris_json = json.dumps(redirect_uris)
                existing.client_name = client_info.client_name
                if secret_hash:
                    existing.client_secret_hash = secret_hash
                if client_info.token_endpoint_auth_method:
                    existing.token_endpoint_auth_method = client_info.token_endpoint_auth_method
            else:
                db.add(
                    McpOAuthClient(
                        client_id=client_info.client_id,
                        client_secret_hash=secret_hash,
                        redirect_uris_json=json.dumps(redirect_uris),
                        client_name=client_info.client_name,
                        token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                    )
                )
            db.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        pending_id = secrets.token_urlsafe(24)
        payload = {
            "client_id": client.client_id,
            "state": params.state,
            "scopes": params.scopes or [SCOPE_DEFAULT],
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "resource": params.resource or self.resource_url,
        }
        expires = datetime.now(UTC) + timedelta(seconds=PENDING_TTL_SECONDS)
        with SessionLocal() as db:
            db.add(
                McpOAuthPending(
                    id=pending_id,
                    client_id=client.client_id,
                    params_json=json.dumps(payload),
                    expires_at=expires,
                )
            )
            db.commit()
        return f"{self.public_base_url}{self.consent_path}?{urlencode({'rid': pending_id})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with SessionLocal() as db:
            row = db.get(McpOAuthCode, authorization_code)
            if row is None or row.client_id != client.client_id:
                return None
            exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                db.delete(row)
                db.commit()
                return None
            return AuthorizationCode(
                code=row.code,
                scopes=json.loads(row.scopes_json or "[]"),
                expires_at=exp.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=bool(row.redirect_uri_provided_explicitly),
                resource=row.resource,
                subject=row.principal_preview,
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with SessionLocal() as db:
            row = db.get(McpOAuthCode, authorization_code.code)
            if row is None or row.client_id != client.client_id:
                raise TokenError(
                    error="invalid_grant", error_description="Unknown authorization code"
                )
            principal = BrainPrincipal(
                workspace_id=row.workspace_id,
                role=row.role,
                principal_preview=row.principal_preview,
                scopes_ops=json.loads(row.scopes_ops_json) if row.scopes_ops_json else None,
            )
            scopes = json.loads(row.scopes_json or "[]")
            resource = row.resource
            db.delete(row)
            access, refresh, exp = self._mint_tokens(
                db, client.client_id, principal, scopes, resource
            )
            db.commit()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else SCOPE_DEFAULT,
            refresh_token=refresh,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        rh = _hash_secret(refresh_token)
        with SessionLocal() as db:
            row = db.scalar(select(McpOAuthTokenRow).where(McpOAuthTokenRow.refresh_hash == rh))
            if row is None or row.client_id != client.client_id:
                return None
            if row.refresh_expires_at is not None:
                exp = (
                    row.refresh_expires_at
                    if row.refresh_expires_at.tzinfo
                    else row.refresh_expires_at.replace(tzinfo=UTC)
                )
                if exp < datetime.now(UTC):
                    return None
                exp_ts = int(exp.timestamp())
            else:
                exp_ts = None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=json.loads(row.scopes_json or "[]"),
                expires_at=exp_ts,
                resource=row.resource,
                subject=row.principal_preview,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        rh = _hash_secret(refresh_token.token)
        with SessionLocal() as db:
            row = db.scalar(select(McpOAuthTokenRow).where(McpOAuthTokenRow.refresh_hash == rh))
            if row is None or row.client_id != client.client_id:
                raise TokenError(error="invalid_grant", error_description="Unknown refresh token")
            principal = BrainPrincipal(
                workspace_id=row.workspace_id,
                role=row.role,
                principal_preview=row.principal_preview,
                scopes_ops=json.loads(row.scopes_ops_json) if row.scopes_ops_json else None,
            )
            use_scopes = scopes or json.loads(row.scopes_json or "[]")
            resource = row.resource
            db.delete(row)
            access, refresh, _ = self._mint_tokens(
                db, client.client_id, principal, use_scopes, resource
            )
            db.commit()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(use_scopes) if use_scopes else SCOPE_DEFAULT,
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        verifier = BrainTokenVerifier(resource_url=self.resource_url)
        return await verifier.verify_token(token)

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        with SessionLocal() as db:
            if isinstance(token, RefreshToken):
                row = db.scalar(
                    select(McpOAuthTokenRow).where(
                        McpOAuthTokenRow.refresh_hash == _hash_secret(token.token)
                    )
                )
            else:
                row = db.get(McpOAuthTokenRow, _hash_secret(token.token))
            if row is not None:
                db.delete(row)
                db.commit()

    def _mint_tokens(
        self,
        db: Session,
        client_id: str,
        principal: BrainPrincipal,
        scopes: list[str],
        resource: str | None,
    ) -> tuple[str, str, datetime]:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)
        refresh_exp = datetime.now(UTC) + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS)
        db.add(
            McpOAuthTokenRow(
                token_hash=_hash_secret(access),
                refresh_hash=_hash_secret(refresh),
                client_id=client_id,
                scopes_json=json.dumps(scopes or [SCOPE_DEFAULT]),
                resource=resource or self.resource_url,
                workspace_id=principal.workspace_id,
                role=principal.role,
                principal_preview=principal.principal_preview,
                scopes_ops_json=json.dumps(principal.scopes_ops)
                if principal.scopes_ops is not None
                else None,
                expires_at=expires,
                refresh_expires_at=refresh_exp,
            )
        )
        return access, refresh, expires

    def complete_consent(self, rid: str, brain_token: str) -> str:
        """Validate Brain token for a pending authorize and return client redirect URL."""
        with SessionLocal() as db:
            pending = db.get(McpOAuthPending, rid)
            if pending is None:
                raise AccessDenied("Unknown or expired authorization request")
            exp = (
                pending.expires_at
                if pending.expires_at.tzinfo
                else pending.expires_at.replace(tzinfo=UTC)
            )
            if exp < datetime.now(UTC):
                db.delete(pending)
                db.commit()
                raise AccessDenied("Authorization request expired")
            params = json.loads(pending.params_json)
            principal = resolve_brain_principal(db, brain_token)
            code = secrets.token_urlsafe(32)
            db.add(
                McpOAuthCode(
                    code=code,
                    client_id=params["client_id"],
                    code_challenge=params["code_challenge"],
                    redirect_uri=params["redirect_uri"],
                    redirect_uri_provided_explicitly=1
                    if params.get("redirect_uri_provided_explicitly")
                    else 0,
                    scopes_json=json.dumps(params.get("scopes") or [SCOPE_DEFAULT]),
                    resource=params.get("resource") or self.resource_url,
                    workspace_id=principal.workspace_id,
                    role=principal.role,
                    principal_preview=principal.principal_preview,
                    scopes_ops_json=json.dumps(principal.scopes_ops)
                    if principal.scopes_ops is not None
                    else None,
                    expires_at=datetime.now(UTC) + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
                )
            )
            db.delete(pending)
            db.commit()
            return construct_redirect_uri(
                params["redirect_uri"],
                code=code,
                state=params.get("state"),
            )

    def pending_summary(self, rid: str) -> dict | None:
        with SessionLocal() as db:
            pending = db.get(McpOAuthPending, rid)
            if pending is None:
                return None
            exp = (
                pending.expires_at
                if pending.expires_at.tzinfo
                else pending.expires_at.replace(tzinfo=UTC)
            )
            if exp < datetime.now(UTC):
                return None
            params = json.loads(pending.params_json)
            return {
                "rid": rid,
                "client_id": params.get("client_id"),
                "client_name": None,
                "scopes": params.get("scopes") or [SCOPE_DEFAULT],
            }
