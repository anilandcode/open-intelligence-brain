"""Hashed machine credentials: mint once, store only a digest, enforce scopes.

Pins the v1.1 contract from the governed-context research:

1. A raw `brn_live_…` secret is returned exactly once and never lands in Postgres.
2. Revoking the credential blocks the next request.
3. Scopes are enforced centrally (`require_scope`), not by role alone.
4. Legacy owner/bootstrap tokens in `workspace_grants` keep working (rollback path).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from brain.access import ensure_default_workspace, require_scope
from brain.credentials import (
    KNOWN_SCOPES,
    create_api_credential,
    hash_api_key,
    resolve_api_credential,
)
from brain.database import SessionLocal
from brain.models import ApiCredential

OWNER = {"X-Brain-Token": "test-token"}


class TestCredentialSecretIsNeverStored:
    def test_mint_returns_brn_live_secret_once(self, client):
        created = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read", "brain:ask"], "name": "reader"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        raw = body["principal"]
        assert raw.startswith("brn_live_")
        assert body["name"] == "reader"
        assert sorted(body["scopes"]) == ["brain:ask", "brain:read"]

        with SessionLocal() as db:
            rows = list(db.scalars(select(ApiCredential)).all())
            assert len(rows) == 1
            assert rows[0].key_hash == hash_api_key(raw)
            assert rows[0].key_hash != raw
            assert raw not in rows[0].key_prefix
            # The digest is the only secret-shaped value stored.
            assert raw not in (rows[0].key_hash + rows[0].key_prefix + (rows[0].name or ""))

    def test_listing_never_returns_raw_secret(self, client):
        created = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read"], "name": "list-me"},
        ).json()
        raw = created["principal"]
        listed = client.get("/api/v1/workspaces/default/tokens", headers=OWNER)
        assert listed.status_code == 200
        assert raw not in listed.text
        assert "test-token" not in listed.text
        rows = listed.json()
        assert any(row.get("name") == "list-me" for row in rows)
        assert all("principal" not in row for row in rows)
        assert all(row.get("principal_preview") for row in rows)

    def test_hashed_credential_authenticates(self, client):
        raw = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read", "sources:read"]},
        ).json()["principal"]
        overview = client.get("/api/v1/overview", headers={"X-Brain-Token": raw})
        assert overview.status_code == 200, overview.text

    def test_revoked_credential_is_refused(self, client):
        created = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read"]},
        ).json()
        raw = created["principal"]
        token_id = created["id"]
        assert (
            client.delete(
                f"/api/v1/workspaces/default/tokens/{token_id}", headers=OWNER
            ).status_code
            == 204
        )
        assert client.get("/api/v1/overview", headers={"X-Brain-Token": raw}).status_code == 401

    def test_expired_credential_is_refused(self, client):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            raw, cred = create_api_credential(
                db,
                workspace,
                name="expired",
                role="member",
                scopes=["brain:read"],
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
            db.commit()
            token_id = cred.id
        assert client.get("/api/v1/overview", headers={"X-Brain-Token": raw}).status_code == 401
        # Still listed so an admin can see it is dead, but marked revoked/expired.
        listed = client.get("/api/v1/workspaces/default/tokens", headers=OWNER).json()
        assert any(row["id"] == token_id for row in listed)


class TestScopeEnforcement:
    def test_missing_scope_is_forbidden(self, client):
        raw = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read"]},
        ).json()["principal"]
        # Creating a source needs sources:write.
        refused = client.post(
            "/api/v1/sources",
            headers={"X-Brain-Token": raw},
            json={
                "title": "Scoped out note",
                "kind": "note",
                "sensitivity": "internal",
                "content": "We learned that a read-only credential must not capture sources.",
            },
        )
        assert refused.status_code == 403, refused.text
        assert "sources:write" in refused.json()["detail"]

    def test_granted_scope_is_allowed(self, client):
        raw = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["brain:read", "sources:read", "sources:write"]},
        ).json()["principal"]
        created = client.post(
            "/api/v1/sources",
            headers={"X-Brain-Token": raw},
            json={
                "title": "Scoped in note",
                "kind": "note",
                "sensitivity": "internal",
                "content": "We learned that a write-scoped credential may capture a source.",
            },
        )
        assert created.status_code == 201, created.text

    def test_admin_scope_bypasses_individual_checks(self, client):
        raw = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "admin", "scopes": ["admin"]},
        ).json()["principal"]
        created = client.post(
            "/api/v1/sources",
            headers={"X-Brain-Token": raw},
            json={
                "title": "Admin scoped note",
                "kind": "note",
                "sensitivity": "internal",
                "content": "We learned that the admin scope covers source capture.",
            },
        )
        assert created.status_code == 201, created.text

    def test_unknown_scope_is_rejected_at_mint(self, client):
        bad = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "scopes": ["not:a-real-scope"]},
        )
        assert bad.status_code == 422

    def test_require_scope_helper_none_means_unrestricted(self):
        from brain.access import WorkspaceAccess
        from brain.models import Workspace

        access = WorkspaceAccess(
            workspace=Workspace(id="ws_default", slug="default", name="My workspace"),
            principal="legacy",
            role="owner",
            scopes=None,
        )
        require_scope(access, "sources:write")  # must not raise

    def test_legacy_owner_token_still_works_without_scopes(self, client):
        """Bootstrap / emergency path: raw workspace_grants principal, unrestricted."""
        assert client.get("/api/v1/overview", headers=OWNER).status_code == 200
        created = client.post(
            "/api/v1/sources",
            headers=OWNER,
            json={
                "title": "Owner bootstrap note",
                "kind": "note",
                "sensitivity": "private",
                "content": "We learned that the owner token remains the emergency unlock path.",
            },
        )
        assert created.status_code == 201, created.text


class TestCredentialUnitHelpers:
    def test_resolve_unknown_hash_is_none(self):
        with SessionLocal() as db:
            ensure_default_workspace(db)
            db.commit()
            assert resolve_api_credential(db, "brn_live_nope_secret") is None

    def test_hash_is_stable(self):
        assert hash_api_key("brn_live_abc_def") == hash_api_key("brn_live_abc_def")
        assert hash_api_key("a") != hash_api_key("b")

    def test_known_scopes_cover_v1_surface(self):
        for needed in (
            "brain:read",
            "brain:ask",
            "sources:read",
            "sources:write",
            "reviews:read",
            "reviews:write",
            "admin",
        ):
            assert needed in KNOWN_SCOPES
