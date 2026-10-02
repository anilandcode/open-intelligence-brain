"""Hybrid retrieval: vector + keyword fusion over approved knowledge.

The vector channel is exercised with the deterministic lexical (hashing) embedder
via the `lexical` fixture, which resets after each test. That embedder is a
TEST-ONLY utility — never the retrieval default — because its hash collisions can
false-match unrelated text and break the abstention guarantee. In production the
vector channel runs only on a real neural embedder, or is off (keyword-only).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from brain.access import ReadScope, ensure_default_workspace
from brain.database import SessionLocal
from brain.embeddings import HashingEmbedder, get_embedder, reset_embedder, set_embedder
from brain.models import Knowledge
from brain.retrieval import _rrf, hybrid_search, vector_search
from brain.services import search_knowledge

GOVERNANCE = (
    "The governed brain requires human approval before any candidate becomes "
    "canonical retrievable truth for every agent."
)
PHOTO = "Photosynthesis converts sunlight into chemical energy in green plants."
MONEY = "The federal reserve sets monetary policy to manage inflation."


@pytest.fixture()
def lexical():
    """Turn on the lexical embedder for one test, then restore the default."""
    set_embedder(HashingEmbedder())
    yield
    reset_embedder()


def _approve(client, headers, content: str, title: str) -> None:
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": "private", "content": content},
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})


def _scope() -> ReadScope:
    with SessionLocal() as db:
        return ReadScope(ensure_default_workspace(db).id, "owner")


class TestEmbeddingOnApproval:
    def test_approval_stores_an_embedding(self, client, headers, lexical):
        _approve(client, headers, GOVERNANCE, "Governance rule")
        with SessionLocal() as db:
            item = db.scalars(select(Knowledge).where(Knowledge.status == "canonical")).first()
            assert item is not None
            assert item.embedding is not None
            vec = json.loads(item.embedding)
            assert isinstance(vec, list) and len(vec) > 10
            assert item.embedding_model


class TestHybridSearch:
    def test_hybrid_fuses_vector_and_keyword(self, client, headers, lexical):
        _approve(client, headers, GOVERNANCE, "Governance rule")
        with SessionLocal() as db:
            ids = hybrid_search(db, _scope(), "human approval canonical truth")
        assert ids  # keyword + vector fuse to return the approved row

    def test_vector_search_ranks_word_overlap_first(self, client, headers, lexical):
        _approve(client, headers, PHOTO, "Photosynthesis")
        _approve(client, headers, MONEY, "Monetary policy")
        with SessionLocal() as db:
            emb = get_embedder()
            ids = vector_search(db, emb.embed("sunlight green plants"), _scope())
        assert ids
        with SessionLocal() as db:
            first = db.get(Knowledge, ids[0])
        assert "photosynthesis" in first.statement.lower()

    def test_search_knowledge_returns_approved_via_hybrid(self, client, headers, lexical):
        _approve(client, headers, GOVERNANCE, "Governance rule")
        with SessionLocal() as db:
            results = search_knowledge(db, _scope(), "canonical truth approval")
        assert results
        assert any("human approval" in r.statement.lower() for r in results)

    def test_keyword_path_works_without_any_embedder(self, client, headers):
        # Default embedder is None (no neural config) → keyword-only retrieval,
        # the safe production default. It must still answer.
        _approve(client, headers, GOVERNANCE, "Governance rule")
        with SessionLocal() as db:
            ids = hybrid_search(db, _scope(), "human approval truth")
        assert ids  # FTS keyword path answers with no vector channel


class TestRRFFusion:
    def test_rrf_prefers_items_ranked_high_in_both(self):
        fused = _rrf([["a", "b", "c"], ["b", "a", "d"]], limit=3)
        assert set(fused[:2]) == {"a", "b"}

    def test_rrf_survives_a_single_result_list(self):
        assert _rrf([["x"]], limit=2) == ["x"]
