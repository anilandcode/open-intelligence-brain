"""Tests for fail-closed production configuration validation."""

import pytest
from starlette.testclient import TestClient

from brain.config import Settings
from brain.main import app


def test_development_config_has_no_blocking_issues():
    settings = Settings(env="development", owner_token="local-dev-token")
    assert settings.validate_for_production() == []


def test_production_config_rejects_default_owner_token():
    settings = Settings(
        env="production",
        owner_token="local-dev-token",
        seed_demo=False,
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        public_base_url="https://brain.example.com",
    )
    issues = settings.validate_for_production()
    assert any("BRAIN_OWNER_TOKEN" in issue for issue in issues)


def test_production_config_rejects_short_owner_token():
    settings = Settings(
        env="production",
        owner_token="too-short-token",
        seed_demo=False,
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        public_base_url="https://brain.example.com",
    )
    issues = settings.validate_for_production()
    assert any("at least 20 characters" in issue for issue in issues)


def test_production_config_rejects_seed_demo():
    settings = Settings(
        env="production",
        owner_token="a-very-long-production-owner-token-12345",
        seed_demo=True,
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        public_base_url="https://brain.example.com",
    )
    issues = settings.validate_for_production()
    assert any("BRAIN_SEED_DEMO" in issue for issue in issues)


def test_production_config_rejects_sqlite():
    settings = Settings(
        env="production",
        owner_token="a-very-long-production-owner-token-12345",
        seed_demo=False,
        database_url="sqlite:///./data/brain.db",
        public_base_url="https://brain.example.com",
    )
    issues = settings.validate_for_production()
    assert any("PostgreSQL connection" in issue for issue in issues)


def test_production_config_rejects_non_https_url():
    settings = Settings(
        env="production",
        owner_token="a-very-long-production-owner-token-12345",
        seed_demo=False,
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        public_base_url="http://brain.example.com",
    )
    issues = settings.validate_for_production()
    assert any("https://" in issue for issue in issues)


def test_valid_production_config_passes():
    settings = Settings(
        env="production",
        owner_token="a-very-long-production-owner-token-12345",
        seed_demo=False,
        database_url="postgresql+psycopg://user:pass@host:5432/db",
        public_base_url="https://brain.example.com",
    )
    assert settings.validate_for_production() == []


def test_lifespan_aborts_on_invalid_production_settings(monkeypatch):
    monkeypatch.setenv("BRAIN_ENV", "production")
    monkeypatch.setenv("BRAIN_OWNER_TOKEN", "local-dev-token")
    from brain.config import get_settings

    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="Production configuration failed"):
        with TestClient(app):
            pass
    get_settings.cache_clear()
