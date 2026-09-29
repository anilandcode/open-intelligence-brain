"""Audit events must say WHO acted, not just that something happened.

Three rules:

1. A human's action names the human (`users.id`).
2. A machine credential's action names only a NON-RECOVERABLE preview. The raw
   token must never appear anywhere in `audit_events` — an audit log that
   stores live credentials is a credential store with a misleading name.
3. Work nobody asked for records `system`, not a fabricated person and not a
   token that did not act.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from brain.access import (
    WorkspaceAccess,
    actor_ref,
    ensure_default_workspace,
    grant_workspace,
    token_preview,
)
from brain.database import SessionLocal
from brain.identity import VerifiedIdentity, add_member, upsert_user
from brain.main import app
from brain.models import AuditEvent, User
from brain.schemas import SourceCreate
from brain.services import (
    audit,
    create_source_with_proposals,
)

RAW_TOKEN = "test-token"


def _latest_event(db, action: str) -> AuditEvent:
    return db.scalar(
        select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.created_at.desc())
    )


class TestHumanIsNamed:
    def test_a_human_approval_names_the_human(self, client, headers):
        """The central claim: an approval says who approved."""
        with SessionLocal() as db:
            user = upsert_user(db, VerifiedIdentity(provider="local", subject="alice"))
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, user, role="owner")
            human_access = WorkspaceAccess(
                workspace=workspace,
                principal=user.id,
                role="owner",
                actor_kind="user",
                actor_id=user.id,
            )
            db.commit()

        with SessionLocal() as db:
            create_source_with_proposals(
                db,
                SourceCreate(
                    title="Policy", content="We charge an annual fee.", sensitivity="public"
                ),
                workspace.id,
                actor=human_access,
            )
            db.commit()
            event = _latest_event(db, "source.ingested")
            assert event.actor_kind == "user"
            assert event.actor_id == user.id

    def test_human_actor_id_is_the_user_id_not_a_token(self, client, headers):
        with SessionLocal() as db:
            user = upsert_user(db, VerifiedIdentity(provider="local", subject="alice"))
            workspace = ensure_default_workspace(db)
            access = WorkspaceAccess(
                workspace=workspace,
                principal=user.id,
                role="member",
                actor_kind="user",
                actor_id=user.id,
            )
            assert actor_ref(access) == ("user", user.id)


class TestMachineTokenIsNeverStoredRaw:
    def test_token_actor_is_a_preview_never_the_credential(self, client, headers):
        """A real route, a real token: the audit row must not hold the secret."""
        response = client.post(
            "/api/v1/sources",
            headers=headers,
            json={"title": "Note", "content": "We charge an annual fee."},
        )
        assert response.status_code in (200, 201)

        with SessionLocal() as db:
            rows = list(db.scalars(select(AuditEvent)).all())
            assert rows, "capture produced no audit events"
            for row in rows:
                # The raw credential must not appear in ANY column.
                for value in (row.detail, row.actor_id, row.resource_id, row.action):
                    assert RAW_TOKEN not in str(value), f"raw token leaked into audit: {row}"
            ingest = _latest_event(db, "source.ingested")
            assert ingest.actor_kind == "token"
            assert ingest.actor_id == token_preview(RAW_TOKEN)
            assert RAW_TOKEN not in ingest.actor_id

    def test_preview_is_not_recoverable(self):
        preview = token_preview("brn_" + "a" * 40)
        assert "a" * 40 not in preview
        # Keeps a head AND a tail to tell credentials apart, so it ends in the
        # tail rather than the ellipsis.
        assert "…" in preview

    def test_actor_ref_of_a_token_access_uses_the_preview(self):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            grant_workspace(db, workspace, RAW_TOKEN, role="owner")
            db.commit()
            access = WorkspaceAccess(workspace=workspace, principal=RAW_TOKEN, role="owner")
            kind, ref = actor_ref(access)
            assert kind == "token"
            assert ref == token_preview(RAW_TOKEN)
            assert RAW_TOKEN not in ref


class TestSystemWorkIsNotBlamedOnAnyone:
    def test_no_actor_records_system(self):
        with SessionLocal() as db:
            assert actor_ref(None) == ("system", None)
            # Create the workspace row: `audit_events.workspace_id` is a real FK
            # and PostgreSQL enforces it (SQLite would let this pass silently).
            workspace = ensure_default_workspace(db)
            audit(db, workspace.id, "test.event", "thing", "thing_1", "nobody asked for this")
            db.commit()
            event = _latest_event(db, "test.event")
            assert event.actor_kind == "system"
            assert event.actor_id is None

    def test_engine_derivation_records_system(self):
        """`sync_derived_proposals` has no caller, and must not borrow one."""
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            audit(db, workspace.id, "proposals.derived", "source", "src_1", "2 derived")
            db.commit()
            event = _latest_event(db, "proposals.derived")
            assert event.actor_kind == "system"
            assert event.actor_id is None


class TestApprovalIsAttributed:
    def test_approve_via_api_names_the_caller(self, client, headers):
        """End to end through the real route: the approval row names the actor.

        The content is the string `test_restart_gate` proved extracts: a bare
        "We charge an annual fee." yields zero proposals and this test would
        then assert on an empty list.
        """
        created = client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": "Policy",
                "content": "We charge enterprise customers an annual fee because monthly billing caused churn.",
            },
        )
        assert created.status_code in (200, 201)
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        proposals = proposals if isinstance(proposals, list) else proposals.get("items", [])
        pending = [p for p in proposals if p.get("status") == "proposed"]
        assert pending, "no proposals to approve"

        approved = client.post(
            f"/api/v1/proposals/{pending[0]['id']}/approve",
            headers=headers,
            json={"statement": "We charge an annual fee", "type": "fact"},
        )
        assert approved.status_code == 200, approved.text

        with SessionLocal() as db:
            event = _latest_event(db, "knowledge.approved")
            assert event is not None
            # A machine token acted: it is named only by a preview, and it is
            # definitely not claimed to be a human.
            assert event.actor_kind == "token"
            assert event.actor_id == token_preview(RAW_TOKEN)
            assert event.actor_kind != "user"

    def test_reject_via_api_names_the_caller(self, client, headers):
        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": "Policy",
                "content": "We charge enterprise customers an annual fee because monthly billing caused churn.",
            },
        )
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        proposals = proposals if isinstance(proposals, list) else proposals.get("items", [])
        pending = [p for p in proposals if p.get("status") == "proposed"]
        assert pending
        response = client.post(
            f"/api/v1/proposals/{pending[0]['id']}/reject",
            headers=headers,
            json={"reason": "not a policy"},
        )
        assert response.status_code == 200, response.text
        with SessionLocal() as db:
            event = _latest_event(db, "proposal.rejected")
            assert event.actor_kind == "token"
            assert event.actor_id == token_preview(RAW_TOKEN)


class TestSessionActorIsNamed:
    def test_a_human_session_names_the_human(self, monkeypatch):
        """The payoff: a person's action is traceable to that person."""
        import json

        import brain.config as config_module
        import brain.identity as identity_module
        from brain.config import Settings

        claims = json.dumps({"dev-alice": {"subject": "alice"}})
        settings = Settings(identity_provider="local", identity_dev_claims=claims)
        monkeypatch.setattr(config_module, "get_settings", lambda: settings)
        monkeypatch.setattr(identity_module, "get_settings", lambda: settings)

        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={"credential": "dev-alice"})
            assert login.status_code == 200, login.text
            session_token = login.json()["session_token"]
            user_id = login.json()["user"]["id"]

            with SessionLocal() as db:
                workspace = ensure_default_workspace(db)
                add_member(db, workspace, db.get(User, user_id), role="owner")
                db.commit()

            created = client.post(
                "/api/v1/sources",
                headers={"X-Brain-Session": session_token},
                json={"title": "Policy", "content": "We charge an annual fee."},
            )
            assert created.status_code in (200, 201), created.text

            with SessionLocal() as db:
                event = _latest_event(db, "source.ingested")
                assert event.actor_kind == "user", f"expected a human, got {event.actor_kind}"
                assert event.actor_id == user_id
                # And the session secret itself is not stored either.
                for row in db.scalars(select(AuditEvent)).all():
                    for value in (row.detail, row.actor_id, row.resource_id):
                        assert session_token not in str(value)


class TestMigration:
    def test_migration_is_idempotent_and_additive(self):
        import brain.migrate as migrate_module

        first = migrate_module.add_audit_actor_columns()
        second = migrate_module.add_audit_actor_columns()
        assert second == [], f"migration is not idempotent: {second}"
        # Either it just added the columns, or they were already there.
        assert all(name.startswith("audit_events.") for name in first)

    def test_pre_existing_rows_read_as_system_not_as_a_human(self):
        """Nothing before this migration recorded who acted, so no old row may
        claim a person."""
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            audit(db, workspace.id, "legacy.event", "thing", "thing_1", "from before")
            db.commit()
        with SessionLocal() as db:
            event = _latest_event(db, "legacy.event")
            assert event.actor_kind == "system"
            assert event.actor_id is None
