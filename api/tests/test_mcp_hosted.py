"""Hosted Streamable HTTP MCP + OAuth tests."""

from __future__ import annotations

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from brain.database import SessionLocal
from brain.mcp_hosted import _caller_scope
from brain.mcp_oauth import (
    SCOPE_DEFAULT,
    BrainTokenVerifier,
    access_token_from_principal,
    resolve_brain_principal,
)
from brain.mcp_server import brain_status_scoped, search_brain_scoped


def _seed_approved(client, headers, title: str = "Hosted MCP note") -> None:
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": title,
            "kind": "decision",
            "sensitivity": "private",
            "content": (
                "We decided that hosted MCP clients may retrieve approved project "
                "context, but only a person can approve new canonical knowledge."
            ),
        },
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})


class TestHostedMcpDiscovery:
    def test_oauth_metadata_is_public(self, client):
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        body = resp.json()
        assert "authorization_endpoint" in body
        assert "token_endpoint" in body
        assert body["authorization_endpoint"].endswith("/authorize")

    def test_protected_resource_metadata(self, client):
        # RFC 9728 path includes the resource path suffix for /mcp
        resp = client.get("/.well-known/oauth-protected-resource/mcp")
        if resp.status_code == 404:
            resp = client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200
        body = resp.json()
        assert "resource" in body
        assert body["resource"].endswith("/mcp")

    def test_mcp_requires_auth(self, client):
        resp = client.post(
            "/mcp",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert resp.status_code in (401, 403)

    def test_consent_page_unknown_rid(self, client):
        resp = client.get("/mcp/consent?rid=does-not-exist")
        assert resp.status_code == 400
        assert b"unknown or expired" in resp.content.lower()


class TestBrainTokenVerifier:
    @pytest.mark.asyncio
    async def test_accepts_owner_token(self, client, headers):
        # client fixture boots lifespan (owner grant)
        token = headers["X-Brain-Token"]
        verifier = BrainTokenVerifier(resource_url="http://127.0.0.1:8000/mcp")
        access = await verifier.verify_token(token)
        assert access is not None
        assert access.claims is not None
        assert access.claims["workspace_id"]
        assert access.claims["role"] == "owner"
        assert SCOPE_DEFAULT in access.scopes

    @pytest.mark.asyncio
    async def test_rejects_garbage(self, client):
        verifier = BrainTokenVerifier()
        assert await verifier.verify_token("not-a-real-token") is None


class TestHostedMcpToolsWithBearer:
    def test_brain_status_via_bearer_scope(self, client, headers):
        """Tool implementations honour the Bearer principal's workspace."""
        token = headers["X-Brain-Token"]
        with SessionLocal() as db:
            principal = resolve_brain_principal(db, token)
        access = access_token_from_principal(
            token=token,
            client_id="brain-api-key",
            principal=principal,
            scopes=[SCOPE_DEFAULT],
            expires_at=None,
            resource="http://127.0.0.1:8000/mcp",
        )
        ctx_token = auth_context_var.set(AuthenticatedUser(access))
        try:
            status = brain_status_scoped(_caller_scope())
            assert status.sources >= 0
            assert status.canonical >= 0
        finally:
            auth_context_var.reset(ctx_token)

    def test_search_bound_to_caller(self, client, headers):
        _seed_approved(client, headers)
        token = headers["X-Brain-Token"]
        with SessionLocal() as db:
            principal = resolve_brain_principal(db, token)
        access = access_token_from_principal(
            token=token,
            client_id="brain-api-key",
            principal=principal,
            scopes=[SCOPE_DEFAULT],
            expires_at=None,
            resource="http://127.0.0.1:8000/mcp",
        )
        ctx_token = auth_context_var.set(AuthenticatedUser(access))
        try:
            result = search_brain_scoped("hosted MCP", 8, _caller_scope())
            assert result.count >= 1
            assert any("person can approve" in item.statement for item in result.items)
        finally:
            auth_context_var.reset(ctx_token)

    def test_caller_scope_requires_auth(self):
        # No auth context → tools must refuse, not fall back to owner.
        with pytest.raises(PermissionError):
            _caller_scope()


class TestOAuthConsentFlow:
    def test_register_authorize_consent_exchange(self, client, headers):
        # Dynamic client registration
        reg = client.post(
            "/register",
            json={
                "client_name": "test-client",
                "redirect_uris": ["http://127.0.0.1:9999/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert reg.status_code in (200, 201), reg.text
        client_id = reg.json()["client_id"]

        # Start authorize → redirect to consent
        auth = client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "state": "xyz",
                "scope": SCOPE_DEFAULT,
                "resource": "http://127.0.0.1:8000/mcp",
            },
            follow_redirects=False,
        )
        assert auth.status_code in (302, 307), auth.text
        location = auth.headers["location"]
        assert "/mcp/consent?rid=" in location
        rid = location.split("rid=")[1].split("&")[0]

        # Consent with Brain token
        consent = client.post(
            "/mcp/consent",
            data={"rid": rid, "token": headers["X-Brain-Token"]},
            follow_redirects=False,
        )
        assert consent.status_code in (302, 307), consent.text
        cb = consent.headers["location"]
        assert "code=" in cb
        assert "state=xyz" in cb
        code = cb.split("code=")[1].split("&")[0]

        # PKCE: verifier "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk" → challenge above
        token_resp = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "client_id": client_id,
                "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
                "resource": "http://127.0.0.1:8000/mcp",
            },
        )
        assert token_resp.status_code == 200, token_resp.text
        body = token_resp.json()
        assert body["token_type"].lower() == "bearer"
        assert body["access_token"]
        assert body.get("refresh_token")

        # Bearer access token verifies
        import anyio

        verifier = BrainTokenVerifier(resource_url="http://127.0.0.1:8000/mcp")
        access = anyio.run(verifier.verify_token, body["access_token"])
        assert access is not None
        assert access.claims is not None
        assert access.claims["role"] == "owner"
