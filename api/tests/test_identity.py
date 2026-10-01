"""Human identity: users, workspace_members, and the provider boundary.

Three rules this file exists to pin:

1. Identity is a verified provider assertion. Nothing in a request body, a
   query parameter, or model output may name a user — only `verify()` output
   reaches `users`.
2. A human credential and a machine credential are not interchangeable. A
   `User` is not a token and a token is not a person.
3. Identity is optional. With no provider configured, the machine-token
   surface behaves exactly as before (invariant 10).

Runs on both dialects: `postgres-parity` runs the whole suite on PostgreSQL
with `BRAIN_REQUIRE_POSTGRES_TESTS=1`, so a skip here would fail that job.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from brain.access import AccessDenied, ensure_default_workspace, resolve_workspace
from brain.config import Settings
from brain.database import SessionLocal
from brain.identity import (
    IdentityError,
    IdentityProvider,
    LocalIdentityProvider,
    VerifiedIdentity,
    add_member,
    find_user,
    get_identity_provider,
    membership_access,
    membership_role,
    upsert_user,
)
from brain.main import app
from brain.models import User, WorkspaceMember


def _identity(subject: str = "alice", **kw) -> VerifiedIdentity:
    return VerifiedIdentity(provider="local", subject=subject, **kw)


def _settings(**kw) -> Settings:
    """A Settings instance with identity fields pinned, whatever .env says."""
    base = {"identity_provider": "", "identity_dev_claims": ""}
    base.update(kw)
    return Settings(**base)


class TestProviderBoundary:
    """Who a human is, and how we come to believe it."""

    def test_provider_absent_means_no_identity(self):
        assert get_identity_provider(_settings()) is None

    def test_unknown_provider_name_fails_loudly(self):
        """A typo must be visible, not a silent fallback to no identity."""
        with pytest.raises(ValueError, match="Unknown identity provider"):
            get_identity_provider(_settings(identity_provider="not-a-real-provider"))

    def test_firebase_provider_requires_project_id(self):
        with pytest.raises(ValueError, match="identity_firebase_project_id"):
            get_identity_provider(_settings(identity_provider="firebase"))

    def test_firebase_provider_is_selected_when_configured(self):
        provider = get_identity_provider(
            _settings(identity_provider="firebase", identity_firebase_project_id="demo-brain")
        )
        assert provider is not None
        assert provider.name == "firebase"

    def test_local_provider_without_claims_fails_loudly(self):
        with pytest.raises(ValueError, match="requires identity_dev_claims"):
            get_identity_provider(_settings(identity_provider="local"))

    def test_malformed_claims_fail_loudly(self):
        with pytest.raises(ValueError, match="JSON object"):
            get_identity_provider(
                _settings(identity_provider="local", identity_dev_claims="{not json")
            )

    def test_claims_must_be_an_object(self):
        with pytest.raises(ValueError, match="JSON object"):
            get_identity_provider(_settings(identity_provider="local", identity_dev_claims='["a"]'))

    def test_local_provider_verifies_a_provisioned_credential(self):
        provider = get_identity_provider(
            _settings(
                identity_provider="local",
                identity_dev_claims=json.dumps(
                    {"dev-alice": {"subject": "alice", "email": "a@x.test"}}
                ),
            )
        )
        assert provider is not None
        verified = provider.verify("dev-alice")
        assert verified == VerifiedIdentity(provider="local", subject="alice", email="a@x.test")

    @pytest.mark.parametrize("credential", ["", "unknown", "dev-"])
    def test_unknown_credential_is_refused(self, credential):
        provider = LocalIdentityProvider({"dev-alice": {"subject": "alice"}})
        with pytest.raises(IdentityError):
            provider.verify(credential)

    def test_error_is_uninformative(self):
        """No user-enumeration oracle: one message for every failure mode."""
        provider = LocalIdentityProvider({"dev-alice": {"subject": "alice"}})
        messages = set()
        for bad in ("nobody", "dev-alice-wrong", ""):
            with pytest.raises(IdentityError) as exc:
                provider.verify(bad)
            messages.add(str(exc.value))
        assert messages == {"Sign-in failed"}

    def test_claims_without_a_subject_are_refused(self):
        provider = LocalIdentityProvider({"dev-alice": {"email": "a@x.test"}})
        with pytest.raises(IdentityError):
            provider.verify("dev-alice")

    def test_protocol_accepts_any_verifier(self):
        """A hosted provider is a drop-in: same one-method contract."""

        class FakeProvider:
            name = "fake"

            def verify(self, credential: str) -> VerifiedIdentity:
                return VerifiedIdentity(provider="fake", subject=credential)

        assert isinstance(FakeProvider(), IdentityProvider)


class TestUnverifiedIdentityNeverReachesTheDatabase:
    def test_failed_verify_writes_nothing(self):
        provider = LocalIdentityProvider({"dev-alice": {"subject": "alice"}})
        with SessionLocal() as db, pytest.raises(IdentityError):
            upsert_user(db, provider.verify("wrong"))
            db.commit()
        with SessionLocal() as db:
            assert db.query(User).count() == 0

    def test_no_request_body_can_name_a_user(self):
        """The capture surface must not accept a user id from the caller."""
        with TestClient(app) as client:
            headers = {"X-Brain-Token": "test-token"}
            client.post(
                "/api/v1/sources",
                headers=headers,
                json={"title": "t", "content": "c", "user_id": "usr_injected"},
            )
            with SessionLocal() as db:
                assert db.query(User).count() == 0


class TestUpsertUser:
    def test_creates_on_first_verified_login(self):
        with SessionLocal() as db, db.begin():
            user = upsert_user(db, _identity("alice", email="a@x.test", display_name="Alice"))
            assert user.id.startswith("usr_")
            assert user.provider == "local"
            assert user.provider_subject == "alice"
            assert user.is_active is True
            assert user.last_login_at is not None

    def test_is_idempotent_on_external_identity(self):
        with SessionLocal() as db, db.begin():
            first = upsert_user(db, _identity("alice"))
            second = upsert_user(db, _identity("alice"))
            assert first.id == second.id
            assert db.query(User).count() == 1

    def test_email_is_metadata_not_a_key(self):
        """A reassigned email must NOT move an identity to another person."""
        with SessionLocal() as db, db.begin():
            original = upsert_user(db, _identity("alice", email="a@x.test"))
            upsert_user(db, _identity("bob", email="a@x.test"))
            assert db.query(User).count() == 2
            assert find_user(db, "local", "alice").id == original.id

    def test_updates_profile_without_erasing_what_we_knew(self):
        with SessionLocal() as db, db.begin():
            upsert_user(db, _identity("alice", email="a@x.test", display_name="Alice"))
            upsert_user(db, _identity("alice"))  # provider says nothing
            user = find_user(db, "local", "alice")
            assert user.email == "a@x.test"
            assert user.display_name == "Alice"

    def test_same_subject_in_two_providers_is_two_people(self):
        with SessionLocal() as db, db.begin():
            upsert_user(db, VerifiedIdentity(provider="local", subject="alice"))
            upsert_user(db, VerifiedIdentity(provider="google", subject="alice"))
            assert db.query(User).count() == 2

    def test_provider_subject_unique_constraint(self):
        with SessionLocal() as db, pytest.raises(IntegrityError):
            db.add(
                User(
                    id="usr_dup1",
                    provider="local",
                    provider_subject="alice",
                    email="a@x.test",
                )
            )
            db.add(
                User(
                    id="usr_dup2",
                    provider="local",
                    provider_subject="alice",
                    email="b@x.test",
                )
            )
            db.commit()


class TestWorkspaceMembership:
    def test_member_gets_a_role(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="member")
            assert membership_role(db, workspace.id, user.id) == "member"

    def test_membership_is_unique_per_person_per_workspace(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="member")
            add_member(db, workspace, user, role="admin")  # replaces
            assert db.query(WorkspaceMember).count() == 1
            assert membership_role(db, workspace.id, user.id) == "admin"

    def test_no_membership_means_no_role(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            assert membership_role(db, workspace.id, user.id) is None

    def test_membership_does_not_cross_workspaces(self):
        with SessionLocal() as db, db.begin():
            here = ensure_default_workspace(db)
            from brain.models import Workspace  # noqa: PLC0415

            other = Workspace(id="ws_other", slug="other", name="Other")
            db.add(other)
            db.flush()
            user = upsert_user(db, _identity("alice"))
            add_member(db, here, user, role="owner")
            assert membership_role(db, other.id, user.id) is None

    def test_deactivated_user_loses_every_workspace_immediately(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="owner")
            user.is_active = False
            db.flush()
            assert membership_role(db, workspace.id, user.id) is None

    def test_unknown_user_has_no_role(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            assert membership_role(db, workspace.id, "usr_nobody") is None

    def test_add_member_to_no_workspace_is_an_error(self):
        with SessionLocal() as db, db.begin():
            user = upsert_user(db, _identity("alice"))
            with pytest.raises(ValueError, match="does not exist"):
                add_member(db, None, user)


class TestCredentialBoundary:
    """A human credential and a machine credential are not interchangeable."""

    def test_machine_token_path_is_unchanged(self, client):
        """The token surface must not start emitting user identity.

        Takes `client` because the owner grant is created in the app lifespan —
        a bare `SessionLocal()` never boots one, so the token would have no
        grant and the assertion would prove nothing.
        """
        with SessionLocal() as db:
            access = resolve_workspace(db, "test-token")
            assert access.actor_kind == "token"
            assert access.actor_id is None
            assert access.role == "owner"

    def test_machine_token_does_not_create_a_user(self):
        with TestClient(app) as client:
            client.get("/api/v1/overview", headers={"X-Brain-Token": "test-token"})
        with SessionLocal() as db:
            assert db.query(User).count() == 0

    def test_a_user_id_is_not_a_credential(self):
        """A `User` row must never be sendable in X-Brain-Token."""
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="owner")
            for candidate in (user.id, user.provider_subject, user.email):
                with pytest.raises(AccessDenied):
                    resolve_workspace(db, candidate)

    def test_a_token_is_not_a_user(self):
        with TestClient(app) as client:
            response = client.get("/api/v1/overview", headers={"X-Brain-Token": "test-token"})
            assert response.status_code == 200
        with SessionLocal() as db:
            assert find_user(db, "local", "test-token") is None

    def test_membership_access_marks_the_actor_as_a_user(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="member")
            access = membership_access(db, user, workspace)
            assert access.actor_kind == "user"
            assert access.actor_id == user.id
            assert access.role == "member"
            assert access.workspace_id == workspace.id

    def test_membership_access_refuses_without_live_membership(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            assert membership_access(db, user, workspace) is None

    def test_membership_access_refuses_a_deactivated_user(self):
        with SessionLocal() as db, db.begin():
            workspace = ensure_default_workspace(db)
            user = upsert_user(db, _identity("alice"))
            add_member(db, workspace, user, role="owner")
            user.is_active = False
            db.flush()
            assert membership_access(db, user, workspace) is None


class TestIdentityIsOptional:
    def test_app_boots_with_no_provider_configured(self):
        """Invariant 10: identity must never become required for reading."""
        with TestClient(app) as client:
            response = client.get("/api/v1/overview", headers={"X-Brain-Token": "test-token"})
            assert response.status_code == 200

    def test_reading_never_requires_a_human(self):
        with TestClient(app) as client:
            headers = {"X-Brain-Token": "test-token"}
            client.post(
                "/api/v1/sources",
                headers=headers,
                json={"title": "Pricing", "content": "We charge an annual fee."},
            )
            asked = client.post("/api/v1/chat", headers=headers, json={"question": "pricing"})
            assert asked.status_code == 200
