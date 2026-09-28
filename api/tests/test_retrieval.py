"""Tests for FTS5 retrieval, expiring tokens, MCP HTTP, and richer proposal types."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from brain.access import AccessDenied, ensure_default_workspace, grant_workspace, resolve_workspace
from brain.database import Base
from brain.models import Knowledge, Source, new_id
from brain.retrieval import ensure_fts, rebuild_fts, search_fts, sync_fts_insert
from brain.services import classify_statement


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestClassifyStatement:
    def test_framework(self):
        assert (
            classify_statement("Our framework for evaluating AI tools is based on three principles")
            == "framework"
        )

    def test_evidence(self):
        assert (
            classify_statement("Research shows that evidence-based decisions outperform intuition")
            == "evidence"
        )

    def test_story(self):
        assert (
            classify_statement("An example of this pattern is the case of the failed launch")
            == "story"
        )

    def test_question(self):
        assert classify_statement("How to evaluate whether a tool is worth adopting?") == "question"

    def test_belief(self):
        assert classify_statement("We believe that quality matters more than speed") == "belief"

    def test_lesson(self):
        assert (
            classify_statement("I learned that shipping early beats shipping perfect") == "lesson"
        )

    def test_thesis(self):
        assert classify_statement("Because the market is shifting, we should pivot") == "thesis"

    def test_decision(self):
        assert classify_statement("We decided to use PostgreSQL for all new services") == "decision"

    def test_fact_default(self):
        assert classify_statement("The system processes 10,000 requests per second") == "fact"


class TestFTS5:
    def test_ensure_fts_creates_table(self, db):
        assert ensure_fts(db) is True
        assert ensure_fts(db) is True

    def test_rebuild_fts(self, db):
        ensure_fts(db)
        source = Source(
            id=new_id("src"), workspace_id="ws_default", title="Test", content="Test content"
        )
        db.add(source)
        db.flush()
        item = Knowledge(
            id=new_id("know"),
            workspace_id="ws_default",
            proposal_id=new_id("prop"),
            source_id=source.id,
            type="belief",
            statement="We believe AI should be grounded in evidence",
            rationale="Because ungrounded claims are dangerous",
            source_excerpt="evidence",
        )
        db.add(item)
        db.commit()
        count = rebuild_fts(db)
        assert count == 1

    def test_search_fts(self, db):
        ensure_fts(db)
        source = Source(
            id=new_id("src"), workspace_id="ws_default", title="Test", content="Test content"
        )
        db.add(source)
        db.flush()
        item = Knowledge(
            id=new_id("know"),
            workspace_id="ws_default",
            proposal_id=new_id("prop"),
            source_id=source.id,
            type="belief",
            statement="Grounded AI output is more trustworthy",
            rationale="Evidence-based claims are reliable",
            source_excerpt="trustworthy",
        )
        db.add(item)
        db.commit()
        db.expire_all()
        rebuild_fts(db)
        db.expire_all()
        results = search_fts(db, "grounded trustworthy")
        assert len(results) >= 1

    def test_sync_fts_insert(self, db):
        ensure_fts(db)
        source = Source(
            id=new_id("src"), workspace_id="ws_default", title="Test", content="Test content"
        )
        db.add(source)
        db.flush()
        item = Knowledge(
            id=new_id("know"),
            workspace_id="ws_default",
            proposal_id=new_id("prop"),
            source_id=source.id,
            type="fact",
            statement="The API handles 10k requests per second",
            rationale="Load tested",
            source_excerpt="10k",
        )
        db.add(item)
        db.commit()
        sync_fts_insert(db, item)
        results = search_fts(db, "requests per second")
        assert len(results) == 1


class TestExpiringTokens:
    def test_grant_with_expiry(self, db):
        workspace = ensure_default_workspace(db)
        expires = datetime.now(UTC) + timedelta(hours=24)
        grant = grant_workspace(db, workspace, "test_token", role="member", expires_at=expires)
        db.commit()
        assert grant.expires_at is not None
        assert grant.scope is None

    def test_grant_with_scope(self, db):
        workspace = ensure_default_workspace(db)
        grant = grant_workspace(db, workspace, "scoped_token", role="member", scope="read_only")
        db.commit()
        assert grant.scope == "read_only"

    def test_expired_token_rejected(self, db):
        workspace = ensure_default_workspace(db)
        expires = datetime.now(UTC) - timedelta(hours=1)
        grant_workspace(db, workspace, "expired_token", role="member", expires_at=expires)
        db.commit()
        with pytest.raises(AccessDenied):
            resolve_workspace(db, "expired_token")

    def test_valid_token_accepted(self, db):
        workspace = ensure_default_workspace(db)
        expires = datetime.now(UTC) + timedelta(hours=24)
        grant_workspace(db, workspace, "valid_token", role="member", expires_at=expires)
        db.commit()
        access = resolve_workspace(db, "valid_token")
        assert access.role == "member"


class TestMCPHttp:
    def test_list_tools(self, client, headers):
        response = client.get("/api/v1/mcp/tools", headers=headers)
        assert response.status_code == 200
        tools = response.json()["tools"]
        names = {t["name"] for t in tools}
        assert "brain_status" in names
        assert "search_brain" in names
        assert "ask_brain" in names

    def test_call_brain_status(self, client, headers):
        response = client.post(
            "/api/v1/mcp/call",
            json={"tool": "brain_status", "params": {}},
            headers=headers,
        )
        assert response.status_code == 200
        result = response.json()
        assert result["tool"] == "brain_status"
        assert "result" in result

    def test_call_unknown_tool(self, client, headers):
        response = client.post(
            "/api/v1/mcp/call",
            json={"tool": "nonexistent", "params": {}},
            headers=headers,
        )
        assert response.status_code == 200
        assert "error" in response.json()

    def test_call_search_brain(self, client, headers):
        response = client.post(
            "/api/v1/mcp/call",
            json={"tool": "search_brain", "params": {"query": "test", "limit": 5}},
            headers=headers,
        )
        assert response.status_code == 200
        result = response.json()
        assert result["tool"] == "search_brain"
