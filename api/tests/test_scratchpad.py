"""Agent working memory: expiring notes, promotion to review, unreviewed source search, pgvector."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from mcp import Client
from sqlalchemy import text
from sqlalchemy.orm import Session

from brain.access import ReadScope, ensure_default_workspace, grant_workspace
from brain.config import get_settings
from brain.database import SessionLocal, engine
from brain.embeddings import HashingEmbedder, get_embedder, reset_embedder, set_embedder
from brain.mcp_server import (
    mcp,
    scratch_promote_scoped,
    scratch_read_scoped,
    scratch_write_scoped,
    search_sources_scoped,
)
from brain.models import DEFAULT_WORKSPACE_ID, AgentNote, Knowledge, Workspace
from brain.retrieval import vector_search
from brain.vectors import ensure_pgvector, forget, pgvector_ready

MEMBER = {"X-Brain-Token": "member-token"}
NOTE = "The customer asked whether the analytics export can include archived projects too."
RENEWAL = "Renewal discounts for annual contracts are capped at fifteen percent this year."
ONBOARDING = "Onboarding calls with enterprise customers are scheduled within two working days."


def _scope(role: str = "owner") -> ReadScope:
    with SessionLocal() as db:
        return ReadScope(ensure_default_workspace(db).id, role)


def _capture(client, headers, content, title="Note", sensitivity="internal"):
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": sensitivity, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _member():
    with Session(engine) as db:
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "member-token", role="member")
        db.commit()


class TestScratchpad:
    @pytest.mark.asyncio
    async def test_agent_writes_reads_and_promotes_a_note(self, client, headers):
        async with Client(mcp, raise_exceptions=True) as agent:
            written = await agent.call_tool(
                "scratch_write", {"content": NOTE, "topic": "export question"}
            )
            note = written.structured_content
            expires = datetime.fromisoformat(note["expires_at"])
            assert 6.9 < (expires - datetime.now(UTC)).total_seconds() / 86_400 <= 7

            read = (await agent.call_tool("scratch_read", {})).structured_content
            assert [n["note_id"] for n in read["notes"]] == [note["note_id"]]
            assert "not approved knowledge" in read["note"]
            other_topic = await agent.call_tool("scratch_read", {"topic": "pricing"})
            assert other_topic.structured_content["notes"] == []

            # A note is not knowledge: search and ask never see it.
            found = await agent.call_tool("search_brain", {"query": "archived projects export"})
            assert found.structured_content["count"] == 0

            promoted = await agent.call_tool("scratch_promote", {"note_id": note["note_id"]})
            assert promoted.structured_content["status"] == "awaiting_review"
            assert promoted.structured_content["title"] == "Agent note: export question"
            again = await agent.call_tool("scratch_promote", {"note_id": note["note_id"]})
            assert again.is_error

        proposals = client.get("/api/v1/proposals", headers=headers).json()
        assert [p["statement"] for p in proposals] == [NOTE]
        assert client.get("/api/v1/knowledge", headers=headers).json() == []
        listed = client.get("/api/v1/scratchpad", headers=headers).json()
        assert listed[0]["promoted_source_id"] == promoted.structured_content["source_id"]

    def test_notes_belong_to_their_author(self, client):
        scope = _scope()
        mine = scratch_write_scoped(scope, content=NOTE, principal_preview="obk_agent_a")
        scratch_write_scoped(scope, content=RENEWAL, principal_preview="obk_agent_b")
        notes = scratch_read_scoped(scope, principal_preview="obk_agent_a").notes
        assert [n.content for n in notes] == [NOTE]
        with pytest.raises(ValueError, match="Note not found"):
            scratch_promote_scoped(scope, note_id=mine.note_id, principal_preview="obk_agent_b")

    def test_memory_and_source_scopes_are_enforced(self, client):
        scope = _scope()
        with pytest.raises(PermissionError, match="memory:write"):
            scratch_write_scoped(scope, content=NOTE, scopes_ops=["brain:read"])
        with pytest.raises(PermissionError, match="memory:read"):
            scratch_read_scoped(scope, scopes_ops=["brain:read"])
        note = scratch_write_scoped(scope, content=NOTE, scopes_ops=["memory:write"])
        with pytest.raises(PermissionError, match="sources:write"):
            scratch_promote_scoped(scope, note_id=note.note_id, scopes_ops=["memory:write"])

    def test_notes_expire_and_are_purged(self, client):
        scope = _scope()
        note = scratch_write_scoped(scope, content=NOTE, days=90)
        assert (datetime.fromisoformat(note.expires_at) - datetime.now(UTC)).days <= 30
        with Session(engine) as db:
            row = db.get(AgentNote, note.note_id)
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
        assert scratch_read_scoped(scope).notes == []
        with Session(engine) as db:
            assert db.get(AgentNote, note.note_id) is None

    def test_each_agent_has_a_note_limit(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "scratchpad_max_notes", 1)
        scope = _scope()
        scratch_write_scoped(scope, content=NOTE)
        with pytest.raises(ValueError, match="at most 1 notes"):
            scratch_write_scoped(scope, content=RENEWAL)
        scratch_write_scoped(scope, content=RENEWAL, principal_preview="obk_other")

    def test_console_lists_deletes_and_promotes(self, client, headers):
        _member()
        owner_note = scratch_write_scoped(_scope(), content=NOTE, topic="export")
        member_note = scratch_write_scoped(
            _scope("member"), content=RENEWAL, principal_preview="obk_m"
        )
        assert {n["id"] for n in client.get("/api/v1/scratchpad", headers=headers).json()} == {
            owner_note.note_id,
            member_note.note_id,
        }
        # A member never sees a private note, even one an owner's agent wrote.
        visible = client.get("/api/v1/scratchpad", headers=MEMBER).json()
        assert [n["id"] for n in visible] == [member_note.note_id]
        assert (
            client.delete(f"/api/v1/scratchpad/{owner_note.note_id}", headers=MEMBER).status_code
            == 404
        )
        promoted = client.post(
            f"/api/v1/scratchpad/{member_note.note_id}/promote",
            headers=headers,
            json={"title": "Renewal discount cap"},
        )
        assert promoted.status_code == 201, promoted.text
        assert promoted.json()["title"] == "Renewal discount cap"
        assert promoted.json()["sensitivity"] == "internal"
        conflict = client.post(
            f"/api/v1/scratchpad/{member_note.note_id}/promote", headers=headers, json={}
        )
        assert conflict.status_code == 409
        assert (
            client.delete(f"/api/v1/scratchpad/{owner_note.note_id}", headers=headers).status_code
            == 204
        )
        assert len(client.get("/api/v1/scratchpad", headers=headers).json()) == 1


class TestUnreviewedSourceSearch:
    def test_hits_are_labelled_unreviewed_or_approved(self, client, headers):
        _capture(client, headers, RENEWAL, title="Pricing notes")
        _capture(client, headers, ONBOARDING, title="Onboarding notes")
        proposal = next(
            p
            for p in client.get("/api/v1/proposals", headers=headers).json()
            if p["statement"] == ONBOARDING
        )
        approved = client.post(
            f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={}
        ).json()

        hits = client.get(
            "/api/v1/search/sources", headers=headers, params={"q": "renewal discounts annual"}
        ).json()
        assert hits[0]["excerpt"] == RENEWAL and hits[0]["status"] == "unreviewed"
        assert hits[0]["knowledge_id"] is None and hits[0]["source_title"] == "Pricing notes"

        result = search_sources_scoped("enterprise onboarding calls", 5, _scope())
        assert result.hits[0].status == "approved"
        assert result.hits[0].knowledge_id == approved["id"]
        assert "unverified" in result.note

    def test_only_readable_sources_and_latest_versions(self, client, headers):
        _member()
        _capture(client, headers, RENEWAL, title="Private pricing", sensitivity="private")
        source = _capture(client, headers, ONBOARDING, title="Onboarding")
        assert search_sources_scoped("renewal discounts", 5, _scope("member")).hits == []
        assert search_sources_scoped("renewal discounts", 5, _scope()).hits

        changed = "Onboarding calls with enterprise customers now happen on the first day."
        response = client.post(
            f"/api/v1/sources/{source['id']}/versions",
            headers=headers,
            json={"content": changed, "change_note": "Faster onboarding"},
        )
        assert response.status_code == 201, response.text
        hits = search_sources_scoped("onboarding calls enterprise", 5, _scope()).hits
        assert [h.excerpt for h in hits] == [changed]
        assert hits[0].version == 2

    def test_empty_queries_find_nothing(self, client, headers):
        _capture(client, headers, RENEWAL)
        assert (
            client.get("/api/v1/search/sources", headers=headers, params={"q": "the and"}).json()
            == []
        )


def _is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


@pytest.mark.skipif(not _is_postgres(), reason="pgvector runs on PostgreSQL only")
class TestPgvector:
    @pytest.fixture(autouse=True)
    def _embedder(self):
        set_embedder(HashingEmbedder())
        yield
        reset_embedder()

    def test_sql_ranking_matches_the_python_path(self, client, headers):
        with SessionLocal() as db:
            forget(db)
            if not ensure_pgvector(db):
                pytest.skip("the vector extension is not installed on this server")
        for content in (RENEWAL, ONBOARDING, NOTE):
            _capture(client, headers, content)
        for proposal in client.get("/api/v1/proposals", headers=headers).json():
            client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})

        query = get_embedder().embed("enterprise onboarding calls")
        scope = _scope()
        with SessionLocal() as db:
            # The trigger mirrored every embedding written through the ORM.
            mirrored = db.execute(
                text("SELECT count(*) FROM knowledge WHERE embedding_vec IS NOT NULL")
            ).scalar()
            assert mirrored == 3
            assert pgvector_ready(db)
            in_sql = vector_search(db, query, scope, limit=3)
            forget(db)
            from brain import vectors

            vectors._ready[str(db.get_bind().url)] = False
            in_python = vector_search(db, query, scope, limit=3)
            forget(db)
        assert in_sql == in_python
        assert in_sql

    def test_member_scope_applies_in_sql(self, client, headers):
        with SessionLocal() as db:
            forget(db)
            if not ensure_pgvector(db):
                pytest.skip("the vector extension is not installed on this server")
        _member()
        _capture(client, headers, RENEWAL, sensitivity="private")
        proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
        client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})
        query = get_embedder().embed("renewal discounts")
        with SessionLocal() as db:
            assert vector_search(db, query, _scope("member"), limit=5) == []
            assert len(vector_search(db, query, _scope(), limit=5)) == 1
            item = db.query(Knowledge).first()
            item.embedding = json.dumps([0.0] * 384)
            db.commit()
            vec = db.execute(
                text("SELECT embedding_vec IS NOT NULL FROM knowledge WHERE id = :id"),
                {"id": item.id},
            ).scalar()
            assert vec is True
