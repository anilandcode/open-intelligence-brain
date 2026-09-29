"""Human sessions and the login routes.

Pins three separations:

1. A session secret is never stored — only its hash. A database read must not
   yield a usable credential.
2. A session and a machine token are different classes in different headers.
   Neither is accepted where the other belongs.
3. Login creates identity, not reach. Workspace access still comes from
   `workspace_members`, so inviting someone and accepting their sign-in are
   different acts.

Plus the failure-mode rules: one indistinguishable 401 for every login failure,
and logout that answers 204 whether or not the session existed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from brain.access import AccessDenied, ensure_default_workspace
from brain.config import Settings
from brain.database import SessionLocal
from brain.identity import add_member
from brain.main import app
from brain.models import User, UserSession, WorkspaceMember
from brain.sessions import (
    hash_session_token,
    resolve_session,
    resolve_session_access,
    revoke_all_sessions,
)

DEV_CRED = "dev-alice"


def _claims() -> str:
    import json

    return json.dumps(
        {"dev-alice": {"subject": "alice", "email": "a@x.test", "display_name": "Alice"}}
    )


@pytest.fixture
def auth_client(monkeypatch):
    """A client whose deployment has a local identity provider configured."""
    import brain.config as config_module
    import brain.identity as identity_module

    settings = Settings(identity_provider="local", identity_dev_claims=_claims())
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr(identity_module, "get_settings", lambda: settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def signed_in(auth_client):
    """Login through the real route and return (client, raw_token, user_id)."""
    response = auth_client.post("/api/v1/auth/login", json={"credential": DEV_CRED})
    assert response.status_code == 200, response.text
    body = response.json()
    return auth_client, body["session_token"], body["user"]["id"]


class TestSessionSecretIsNeverStored:
    def test_login_returns_a_raw_secret_once(self, signed_in):
        _client, raw, _user_id = signed_in
        assert raw.startswith("bss_")
        assert len(raw) > 40

    def test_only_the_hash_is_persisted(self, signed_in):
        _client, raw, user_id = signed_in
        with SessionLocal() as db:
            rows = list(db.scalars(select(UserSession)).all())
            assert len(rows) == 1
            assert rows[0].token_hash != raw
            assert rows[0].token_hash == hash_session_token(raw)
            stored = [rows[0].token_hash]
            assert raw not in stored
            # The raw secret must not appear anywhere in the row's own values.
            for value in (rows[0].id, rows[0].user_id, rows[0].user_agent):
                assert raw not in str(value)

    def test_me_never_returns_the_secret(self, signed_in):
        client, raw, _user_id = signed_in
        response = client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw})
        assert response.status_code == 200
        assert raw not in response.text

    def test_the_raw_secret_matches_no_stored_column(self, signed_in):
        """Lookup is by hash, so a replayed raw value finds the row only after
        we digest it — the column itself never holds the secret."""
        _client, raw, _user_id = signed_in
        with SessionLocal() as db:
            row = db.scalar(
                select(UserSession).where(UserSession.token_hash == hash_session_token(raw))
            )
            assert row is not None
            direct = db.scalar(select(UserSession).where(UserSession.token_hash == raw))
            assert direct is None


class TestLoginFailureIsIndistinguishable:
    def test_unknown_credential_401s(self, auth_client):
        response = auth_client.post("/api/v1/auth/login", json={"credential": "wrong"})
        assert response.status_code == 401

    def test_every_failure_has_one_message(self, auth_client):
        """Unknown credential and no-provider-must-not differ, so the route
        cannot be used to enumerate people or fingerprint providers."""
        wrong = auth_client.post("/api/v1/auth/login", json={"credential": "wrong"})
        empty = auth_client.post("/api/v1/auth/login", json={"credential": "x" * 2048})
        assert wrong.json()["detail"] == empty.json()["detail"] == "Sign-in failed"

    def test_no_provider_configured_refuses_login(self):
        """Invariant 10 in the other direction: identity is opt-in, and when it
        is off the login route says so rather than minting a session."""
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/login", json={"credential": DEV_CRED})
            assert response.status_code == 401
            assert response.json()["detail"] == "Sign-in failed"

    def test_failed_login_creates_nothing(self, auth_client):
        auth_client.post("/api/v1/auth/login", json={"credential": "wrong"})
        with SessionLocal() as db:
            assert db.query(User).count() == 0
            assert db.query(UserSession).count() == 0


class TestLoginGrantsIdentityNotReach:
    def test_login_alone_reaches_no_workspace(self, auth_client):
        response = auth_client.post("/api/v1/auth/login", json={"credential": DEV_CRED})
        assert response.status_code == 200
        raw = response.json()["session_token"]
        with SessionLocal() as db:
            assert db.query(WorkspaceMember).count() == 0
            with pytest.raises(AccessDenied):
                resolve_session_access(db, raw)

    def test_membership_is_what_grants_reach(self, signed_in):
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            user = db.get(User, user_id)
            add_member(db, workspace, user, role="member")
            db.commit()
        response = client.get("/api/v1/overview", headers={"X-Brain-Session": raw})
        assert response.status_code == 200

    def test_reach_stops_the_moment_membership_is_dropped(self, signed_in):
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, db.get(User, user_id), role="owner")
            db.commit()
        assert client.get("/api/v1/overview", headers={"X-Brain-Session": raw}).status_code == 200
        with SessionLocal() as db:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete()
            db.commit()
        assert client.get("/api/v1/overview", headers={"X-Brain-Session": raw}).status_code == 401

    def test_deactivated_person_cannot_even_ask_who_they_are(self, signed_in):
        """Pins the `is_active` check in `resolve_session` itself.

        `/me` never touches membership, so `membership_role`'s own deactivation
        check cannot cover it — this is the one route that proves `resolve_session`
        is load-bearing rather than redundant.
        """
        client, raw, user_id = signed_in
        assert client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).status_code == 200
        with SessionLocal() as db:
            db.get(User, user_id).is_active = False
            db.commit()
        assert client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).status_code == 401

    def test_deactivated_person_loses_every_session_immediately(self, signed_in):
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, db.get(User, user_id), role="owner")
            db.get(User, user_id).is_active = False
            db.commit()
        assert client.get("/api/v1/overview", headers={"X-Brain-Session": raw}).status_code == 401
        # The session row still exists — it is simply no longer resolvable,
        # which is what makes revocation immediate without a session walk.
        with SessionLocal() as db:
            assert db.query(UserSession).count() == 1


class TestCredentialClassesStaySeparate:
    def test_a_session_is_not_a_machine_token(self, signed_in):
        """Must hold even when the session WOULD grant reach if it were a token.

        Earlier this asserted 401 against a signed-in user with no membership —
        which every resolution path answers with 401, so it passed whether or
        not the classes were conflated. Granting membership first is what makes
        the assertion mean something: a conflation now returns 200.
        """
        _client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, db.get(User, user_id), role="owner")
            db.commit()
        with TestClient(app) as client:
            # Sanity: the same secret works as a session (positive control).
            as_session = client.get("/api/v1/overview", headers={"X-Brain-Session": raw})
            assert as_session.status_code == 200, as_session.text
            # And is refused where a machine token belongs.
            as_token = client.get("/api/v1/overview", headers={"X-Brain-Token": raw})
            assert as_token.status_code == 401, as_token.text

    def test_a_machine_token_is_not_a_session(self):
        """Positive control included: the same owner token DOES work as a
        machine token, so the 401 below is about the class, not about the
        credential being bad."""
        with TestClient(app) as client:
            as_token = client.get("/api/v1/overview", headers={"X-Brain-Token": "test-token"})
            assert as_token.status_code == 200, as_token.text
            as_session = client.get("/api/v1/overview", headers={"X-Brain-Session": "test-token"})
            assert as_session.status_code == 401, as_session.text

    def test_sending_both_credentials_is_refused(self, signed_in):
        client, raw, _user_id = signed_in
        response = client.get(
            "/api/v1/overview",
            headers={"X-Brain-Session": raw, "X-Brain-Token": "test-token"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Send exactly one credential"

    def test_machine_token_path_is_unchanged_by_sessions(self, auth_client):
        assert (
            auth_client.get("/api/v1/overview", headers={"X-Brain-Token": "test-token"}).status_code
            == 200
        )

    def test_actor_kind_records_the_class(self, signed_in):
        _client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, db.get(User, user_id), role="member")
            db.commit()
            access = resolve_session_access(db, raw)
            assert access.actor_kind == "user"
            assert access.actor_id == user_id


class TestLogout:
    def test_logout_revokes_the_session(self, signed_in):
        client, raw, _user_id = signed_in
        assert (
            client.post("/api/v1/auth/logout", headers={"X-Brain-Session": raw}).status_code == 204
        )
        assert client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).status_code == 401

    def test_logout_is_idempotent_and_uninformative(self, auth_client):
        """204 for an unknown secret too, so the route is not a validity probe."""
        assert (
            auth_client.post(
                "/api/v1/auth/logout", headers={"X-Brain-Session": "bss_bogus"}
            ).status_code
            == 204
        )
        assert auth_client.post("/api/v1/auth/logout").status_code == 204

    def test_revoking_all_sessions(self, signed_in):
        client, raw, user_id = signed_in
        assert revoke_all_sessions_count(client, user_id) == 1
        assert client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).status_code == 401


def revoke_all_sessions_count(client, user_id: str) -> int:
    with SessionLocal() as db:
        count = revoke_all_sessions(db, user_id)
        db.commit()
        return count


class TestExpiry:
    def test_expired_session_does_not_resolve(self, signed_in):
        _client, raw, _user_id = signed_in
        with SessionLocal() as db:
            row = db.scalar(
                select(UserSession).where(UserSession.token_hash == hash_session_token(raw))
            )
            from datetime import UTC, datetime

            row.expires_at = datetime.now(UTC).replace(year=2020)
            db.commit()
        with SessionLocal() as db:
            assert resolve_session(db, raw) is None

    def test_unknown_secret_resolves_to_none(self):
        with SessionLocal() as db:
            assert resolve_session(db, "bss_nope") is None
            assert resolve_session(db, "") is None


class TestMe:
    def test_me_reports_identity_and_membership(self, signed_in):
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            add_member(db, workspace, db.get(User, user_id), role="admin")
            db.commit()
        body = client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).json()
        assert body["user"]["id"] == user_id
        assert body["user"]["provider"] == "local"
        assert body["memberships"][0]["role"] == "admin"

    def test_me_works_before_any_membership(self, signed_in):
        """Identity and reach are separate: a person in no workspace yet can
        still see who they are signed in as."""
        client, raw, _user_id = signed_in
        body = client.get("/api/v1/auth/me", headers={"X-Brain-Session": raw}).json()
        assert body["memberships"] == []
        assert body["user"]["display_name"] == "Alice"

    def test_me_requires_a_session(self, auth_client):
        assert auth_client.get("/api/v1/auth/me").status_code == 401


class TestWorkspaceSelection:
    def test_several_memberships_require_naming_one(self, signed_in):
        _client, raw, user_id = signed_in
        with SessionLocal() as db:
            first = ensure_default_workspace(db)
            from brain.models import Workspace

            second = Workspace(id="ws_two", slug="second", name="Second")
            db.add(second)
            db.flush()
            user = db.get(User, user_id)
            add_member(db, first, user, role="member")
            add_member(db, second, user, role="member")
            db.commit()
        with SessionLocal() as db:
            with pytest.raises(AccessDenied, match="several workspaces"):
                resolve_session_access(db, raw)

    def test_naming_a_workspace_selects_it(self, signed_in):
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            first = ensure_default_workspace(db)
            from brain.models import Workspace

            second = Workspace(id="ws_two", slug="second", name="Second")
            db.add(second)
            db.flush()
            user = db.get(User, user_id)
            add_member(db, first, user, role="member")
            add_member(db, second, user, role="owner")
            db.commit()
        response = client.get(
            "/api/v1/overview",
            headers={"X-Brain-Session": raw, "X-Brain-Workspace": "second"},
        )
        assert response.status_code == 200

    def test_membership_in_another_workspace_cannot_be_probed(self, signed_in):
        """No live membership there must read exactly like an unknown slug."""
        client, raw, user_id = signed_in
        with SessionLocal() as db:
            from brain.models import Workspace

            other = Workspace(id="ws_other", slug="other", name="Other")
            db.add(other)
            db.commit()
        response = client.get(
            "/api/v1/overview",
            headers={"X-Brain-Session": raw, "X-Brain-Workspace": "other"},
        )
        unknown = client.get(
            "/api/v1/overview",
            headers={"X-Brain-Session": raw, "X-Brain-Workspace": "no-such-slug"},
        )
        assert response.status_code == unknown.status_code == 401
        assert response.json()["detail"] == unknown.json()["detail"]
