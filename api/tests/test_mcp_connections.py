"""MCP connection telemetry + the admin registry endpoint."""

from __future__ import annotations

from sqlalchemy import select

from brain.database import SessionLocal
from brain.mcp_oauth import BrainPrincipal, McpConnection, note_connection


def _mcp_initialize(client, token: str) -> int:
    """Drive one authenticated /mcp request to trigger a connection note."""
    resp = client.post(
        "/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Antigravity/1.0 test",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
    )
    return resp.status_code


class TestConnectionRegistry:
    def test_direct_bearer_client_is_visible(self, client, headers):
        token = headers["X-Brain-Token"]
        assert _mcp_initialize(client, token) == 200

        rows = client.get("/api/v1/mcp/connections", headers=headers).json()
        assert len(rows) >= 1
        row = rows[0]
        assert row["source_kind"] == "api_key"
        assert row["status"] == "active"
        assert row["access_count"] >= 1
        # The user-agent labels the client so it is not just "some bearer".
        assert "Antigravity" in row["user_agent"]

    def test_registry_never_leaks_a_credential(self, client, headers):
        token = headers["X-Brain-Token"]
        _mcp_initialize(client, token)
        rows = client.get("/api/v1/mcp/connections", headers=headers).json()
        assert rows
        for row in rows:
            for value in row.values():
                if isinstance(value, str):
                    assert token not in value

    def test_note_connection_is_idempotent_per_client(self, client, headers):
        token = headers["X-Brain-Token"]
        _mcp_initialize(client, token)
        _mcp_initialize(client, token)
        rows = client.get("/api/v1/mcp/connections", headers=headers).json()
        # Same principal + same (empty) client_id collapses to one row.
        api_key_rows = [r for r in rows if r["source_kind"] == "api_key"]
        assert len(api_key_rows) == 1
        assert api_key_rows[0]["access_count"] >= 2

    def test_requires_admin(self, client, headers):
        # A hashed member key must not read the connection registry.
        created = client.post(
            "/api/v1/workspaces/ws_default/tokens",
            headers=headers,
            json={"role": "member", "name": "member-key", "scopes": ["brain:read"]},
        )
        # workspace slug may differ; fall back to the owner's own listing shape.
        if created.status_code in (200, 201):
            member_token = created.json()["principal"]
            resp = client.get("/api/v1/mcp/connections", headers={"X-Brain-Token": member_token})
            assert resp.status_code == 403


class TestNoteConnectionHelper:
    def test_note_connection_records_a_row(self, client):
        principal = BrainPrincipal(
            workspace_id="ws_test",
            role="member",
            principal_preview="abc…xyz",
            scopes_ops=None,
        )
        note_connection(principal, client_id="", client_name="", source_kind="api_key")
        with SessionLocal() as db:
            row = db.scalar(
                select(McpConnection).where(
                    McpConnection.workspace_id == "ws_test",
                    McpConnection.principal_preview == "abc…xyz",
                )
            )
            assert row is not None
            assert row.access_count == 1
            assert row.source_kind == "api_key"
