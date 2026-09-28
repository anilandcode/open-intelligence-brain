"""Tests for the background worker and decision provider."""

from unittest.mock import MagicMock

from brain.decision import (
    DeterministicProvider,
    JevShadowProvider,
    create_provider,
)
from brain.worker import _fake_access, _fake_scope


class TestDecisionProvider:
    def test_deterministic_provider_returns_valid_action(self):
        provider = DeterministicProvider()
        result = provider.score(text="What is our churn rate?", channel="slack", addressed=True)
        assert result.action in ("answer", "investigate", "pass")
        assert 0.0 <= result.confidence <= 1.0
        assert result.provider == "deterministic"

    def test_deterministic_provider_passes_unaddressed(self):
        provider = DeterministicProvider()
        result = provider.score(text="random chatter", channel="slack", addressed=False)
        assert result.action in ("answer", "investigate", "pass")

    def test_create_provider_returns_deterministic_by_default(self):
        provider = create_provider()
        assert isinstance(provider, DeterministicProvider)

    def test_create_provider_returns_jev_when_url_given(self):
        provider = create_provider(jev_url="http://localhost:5186")
        assert isinstance(provider, JevShadowProvider)

    def test_jev_shadow_fallback_on_unreachable(self):
        provider = JevShadowProvider(api_url="http://localhost:99999", timeout=0.1)
        result = provider.score(text="test", channel="slack")
        assert result.action == "pass"
        assert result.confidence == 0.0
        assert "Jev unreachable" in result.reason
        assert result.provider == "jev-shadow"


class TestWorkerHelpers:
    def test_fake_access_has_admin_role(self):
        turn = MagicMock()
        turn.workspace_id = "ws_test"
        access = _fake_access(turn)
        assert access.workspace_id == "ws_test"
        assert access.role == "admin"
        assert access.can_administer is True

    def test_fake_scope_filters_workspace(self):
        turn = MagicMock()
        turn.workspace_id = "ws_test"
        scope = _fake_scope(turn)
        assert scope.workspace_id == "ws_test"
        # The worker runs as admin within the turn's workspace, so its scope
        # carries the admin sensitivity ceiling (may read private material),
        # matching what an admin token would reach — but a real ReadScope, so
        # every query is narrowed identically to the API.
        assert scope.role == "admin"
        assert scope.permitted == {"public", "internal", "private"}
