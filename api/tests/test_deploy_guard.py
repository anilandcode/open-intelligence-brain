"""Public-deployment guards: no published owner token, no demo data, no open claim."""

import logging

import pytest
from sqlalchemy import select

from brain.access import ensure_default_workspace, grant_workspace
from brain.config import Settings
from brain.database import SessionLocal
from brain.deploy_guard import (
    UnsafeDeployment,
    check_owner_token,
    report_or_retire_stale_owner_grants,
    should_seed_demo,
)
from brain.models import WorkspaceGrant

PUBLIC = "https://brain.example.com"
STRONG = "x" * 40


class TestPublicDetection:
    @pytest.mark.parametrize(
        "url,public",
        [
            ("http://127.0.0.1:8000", False),
            ("https://localhost:8443", False),
            ("http://brain.example.com", False),
            (PUBLIC, True),
        ],
    )
    def test_https_on_a_real_host_is_public(self, url, public):
        assert Settings(public_base_url=url).is_public_deployment is public


class TestOwnerToken:
    def test_default_token_refused_on_public(self):
        with pytest.raises(UnsafeDeployment):
            check_owner_token(Settings(public_base_url=PUBLIC, owner_token="local-dev-token"))

    def test_empty_token_refused_on_public(self):
        with pytest.raises(UnsafeDeployment):
            check_owner_token(Settings(public_base_url=PUBLIC, owner_token=""))

    def test_default_token_allowed_locally(self):
        check_owner_token(Settings(owner_token="local-dev-token"))

    def test_short_token_warns_but_boots(self, caplog):
        with caplog.at_level(logging.WARNING):
            check_owner_token(Settings(public_base_url=PUBLIC, owner_token="short-but-custom"))
        assert "shorter than" in caplog.text


class TestDemoSeed:
    def test_never_seeds_on_public(self):
        assert should_seed_demo(Settings(public_base_url=PUBLIC, seed_demo=True)) is False

    def test_seeds_locally_when_asked(self):
        assert should_seed_demo(Settings(seed_demo=True)) is True


class TestStaleOwnerGrants:
    def _grants(self):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            grant_workspace(db, workspace, "current-owner-token", role="owner")
            grant_workspace(db, workspace, "rotated-old-token", role="owner")
            grant_workspace(db, workspace, "member-token", role="member")
            db.commit()

    def _principals(self):
        with SessionLocal() as db:
            return {row.principal for row in db.scalars(select(WorkspaceGrant)).all()}

    def test_reports_without_deleting_by_default(self, caplog):
        self._grants()
        with SessionLocal() as db, caplog.at_level(logging.WARNING):
            removed = report_or_retire_stale_owner_grants(
                db, Settings(owner_token="current-owner-token")
            )
            db.commit()
        assert removed == 0
        assert "rotated-old-token" in self._principals()
        assert "1 legacy owner grant" in caplog.text
        assert "rotated-old-token" not in caplog.text  # previews only, never the credential

    def test_retires_only_stale_owner_rows_when_enabled(self):
        self._grants()
        with SessionLocal() as db:
            removed = report_or_retire_stale_owner_grants(
                db,
                Settings(owner_token="current-owner-token", retire_legacy_owner_grants=True),
            )
            db.commit()
        assert removed == 1
        assert self._principals() == {"current-owner-token", "member-token"}


def _sign_in(client, monkeypatch, subject, email):
    from brain.identity import LocalIdentityProvider

    monkeypatch.setattr(
        "brain.sessions.get_identity_provider",
        lambda settings=None: LocalIdentityProvider(
            {f"dev-{subject}": {"subject": subject, "email": email, "display_name": subject}}
        ),
    )
    response = client.post("/api/v1/auth/login", json={"credential": f"dev-{subject}"})
    assert response.status_code == 200
    return response.json()["session_token"]


class TestBootstrapAllowlist:
    def _settings(self, monkeypatch, **overrides):
        monkeypatch.setattr("brain.auth_api.get_settings", lambda: Settings(**overrides))

    def test_public_brain_with_no_allowlist_refuses_every_claim(self, client, monkeypatch):
        self._settings(monkeypatch, public_base_url=PUBLIC, owner_token=STRONG)
        session = _sign_in(client, monkeypatch, "eve", "eve@example.com")
        response = client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": session})
        assert response.status_code == 403

    def test_stranger_cannot_claim_an_allowlisted_brain(self, client, monkeypatch):
        self._settings(
            monkeypatch, public_base_url=PUBLIC, bootstrap_allowed_emails="owner@example.com"
        )
        session = _sign_in(client, monkeypatch, "eve", "eve@example.com")
        response = client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": session})
        assert response.status_code == 403

    def test_allowlisted_owner_claims_case_insensitively(self, client, monkeypatch):
        self._settings(
            monkeypatch, public_base_url=PUBLIC, bootstrap_allowed_emails=" Owner@Example.com "
        )
        session = _sign_in(client, monkeypatch, "anil", "owner@example.com")
        response = client.post("/api/v1/auth/bootstrap", headers={"X-Brain-Session": session})
        assert response.status_code == 200
        assert response.json()["memberships"][0]["role"] == "owner"
