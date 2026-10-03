"""Google sign-in, explicit first-owner bootstrap, and login audit logging."""

import pytest

from brain.config import Settings
from brain.identity import (
    GoogleIdentityProvider,
    IdentityError,
    LocalIdentityProvider,
    get_identity_provider,
)


class TestGoogleProvider:
    def test_factory_returns_google_provider(self):
        provider = get_identity_provider(
            Settings(
                identity_provider="google",
                identity_google_client_id="cid.apps.googleusercontent.com",
            )
        )
        assert isinstance(provider, GoogleIdentityProvider)
        assert provider.name == "google"

    def test_factory_fails_closed_without_client_id(self):
        with pytest.raises(ValueError):
            get_identity_provider(
                Settings(identity_provider="google", identity_google_client_id="")
            )

    def test_rejects_empty_credential(self):
        provider = GoogleIdentityProvider("cid.apps.googleusercontent.com")
        with pytest.raises(IdentityError):
            provider.verify("")

    def test_rejects_unverifiable_token_with_one_message(self):
        provider = GoogleIdentityProvider("cid.apps.googleusercontent.com")
        with pytest.raises(IdentityError, match="Sign-in failed"):
            provider.verify("not-a-real-google-token")

    def test_maps_real_google_claims(self, monkeypatch):
        # Happy path with Google's real claims shape. Guard against the failure
        # this suite once masked: `google-auth` is an optional extra, and without
        # it the lazy import fails with the SAME message as a bad token, so the
        # rejection tests above passed while every real sign-in 401'd. Importing
        # the real module here turns a missing extra into a loud test failure.
        from google.oauth2 import id_token as google_id_token

        monkeypatch.setattr(
            google_id_token,
            "verify_oauth2_token",
            lambda credential, request, audience: {
                "iss": "https://accounts.google.com",
                "aud": audience,
                "sub": "google-sub-122883344",
                "email": "anil.pervaiz01@gmail.com",
                "email_verified": True,
                "name": "Anil Pervaiz",
            },
        )
        provider = GoogleIdentityProvider("cid.apps.googleusercontent.com")
        identity = provider.verify("header.payload.signature")
        assert identity.provider == "google"
        assert identity.subject == "google-sub-122883344"
        assert identity.email == "anil.pervaiz01@gmail.com"
        assert identity.display_name == "Anil Pervaiz"

    def test_rejects_unverified_email(self, monkeypatch):
        from google.oauth2 import id_token as google_id_token

        monkeypatch.setattr(
            google_id_token,
            "verify_oauth2_token",
            lambda credential, request, audience: {"sub": "s1", "email_verified": False},
        )
        provider = GoogleIdentityProvider("cid.apps.googleusercontent.com")
        with pytest.raises(IdentityError, match="Sign-in failed"):
            provider.verify("header.payload.signature")

    def test_rejects_claims_without_sub(self, monkeypatch):
        # The Google sub is the identity key; a token without one must never
        # fall back to the email (or anything else) as the key.
        from google.oauth2 import id_token as google_id_token

        monkeypatch.setattr(
            google_id_token,
            "verify_oauth2_token",
            lambda credential, request, audience: {"email": "a@example.com"},
        )
        provider = GoogleIdentityProvider("cid.apps.googleusercontent.com")
        with pytest.raises(IdentityError, match="Sign-in failed"):
            provider.verify("header.payload.signature")


def _sign_in(client, monkeypatch, credential, subject, name):
    monkeypatch.setattr(
        "brain.sessions.get_identity_provider",
        lambda settings=None, _c=credential, _s=subject, _n=name: LocalIdentityProvider(
            {_c: {"subject": _s, "email": f"{_s}@example.com", "display_name": _n}}
        ),
    )
    response = client.post("/api/v1/auth/login", json={"credential": credential})
    assert response.status_code == 200
    return response.json()["session_token"]


class TestBootstrapAndLogging:
    def test_login_grants_identity_and_is_logged_but_no_reach(self, client, monkeypatch):
        session = _sign_in(client, monkeypatch, "dev-ann", "ann-1", "Ann")
        assert session, "a session must be issued"

        from sqlalchemy import select

        from brain.database import SessionLocal
        from brain.models import AuditEvent, User, UserSession, WorkspaceMember

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.provider_subject == "ann-1"))
            assert user is not None
            # login is logged: the session row (who / when / client) …
            assert db.scalar(select(UserSession).where(UserSession.user_id == user.id)) is not None
            # … and an entry in the audit trail alongside every operation
            assert (
                db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login")) is not None
            )
            # … but NO reach: a login alone grants no membership (the invariant)
            assert (
                db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)) is None
            )

    def test_bootstrap_claims_first_owner(self, client, monkeypatch):
        session = _sign_in(client, monkeypatch, "dev-ann", "ann-1", "Ann")
        response = client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": session})
        assert response.status_code == 200
        assert response.json()["memberships"][0]["role"] == "owner"

        from sqlalchemy import select

        from brain.database import SessionLocal
        from brain.models import AuditEvent, User, WorkspaceMember

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.provider_subject == "ann-1"))
            member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
            assert member is not None and member.role == "owner"
            assert (
                db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.bootstrap"))
                is not None
            )

    def test_bootstrap_fails_once_a_member_exists(self, client, monkeypatch):
        first = _sign_in(client, monkeypatch, "dev-ann", "ann-1", "Ann")
        assert (
            client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": first}).status_code
            == 200
        )

        second = _sign_in(client, monkeypatch, "dev-bob", "bob-2", "Bob")
        # Bob cannot seize a Brain that already has a home — bootstrap fails closed
        assert (
            client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": second}).status_code
            == 409
        )
