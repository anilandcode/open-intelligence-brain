"""Knowledge graph: nodes + edges over approved knowledge (ported edge logic)."""

from __future__ import annotations

from brain.graph import calculate_semantic_similarity, cosine_similarity


def _approve(client, headers, content: str, title: str) -> None:
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": "private", "content": content},
    )
    proposals = client.get("/api/v1/proposals", headers=headers).json()
    for proposal in proposals:
        client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})


TWO_FACTS = (
    "The governed brain requires human approval before any candidate becomes "
    "canonical retrievable truth for every agent and service. "
    "Every approved fact keeps a citation back to its exact source excerpt and span."
)


class TestGraphShape:
    def test_document_edges_link_source_to_knowledge(self, client, headers):
        _approve(client, headers, TWO_FACTS, "Governance")
        graph = client.get("/api/v1/graph", headers=headers).json()
        assert graph["documents"] and graph["edges"]
        doc_ids = {d["id"] for d in graph["documents"]}
        mem_ids = {m["id"] for d in graph["documents"] for m in d["memories"]}
        document_edges = [e for e in graph["edges"] if e["edgeType"] == "document"]
        assert document_edges
        for edge in document_edges:
            assert edge["source"] in doc_ids
            assert edge["target"] in mem_ids

    def test_extends_edges_for_shared_source_siblings(self, client, headers):
        _approve(client, headers, TWO_FACTS, "Governance")
        graph = client.get("/api/v1/graph", headers=headers).json()
        mem_ids = {m["id"] for d in graph["documents"] for m in d["memories"]}
        assert len(mem_ids) >= 2  # two facts extracted from one source
        extends = [e for e in graph["edges"] if e["edgeType"] == "extends"]
        # sibling facts from the same source are linked
        assert extends
        assert all(e["source"] in mem_ids and e["target"] in mem_ids for e in extends)

    def test_graph_never_leaks_a_proposal_or_raw_token(self, client, headers):
        _approve(client, headers, TWO_FACTS, "Governance")
        graph = client.get("/api/v1/graph", headers=headers).json()
        payload = str(graph)
        assert "proposed" not in payload  # only approved/canonical appears
        assert headers["X-Brain-Token"] not in payload


class TestPortedSimilarity:
    def test_cosine_similarity_matches_dot_product(self):
        assert abs(cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_semantic_similarity_clamps_to_unit(self):
        assert calculate_semantic_similarity([1.0], [-1.0]) == 0.0  # negative clamps
        assert abs(calculate_semantic_similarity([1.0], [1.0]) - 1.0) < 1e-9
        # no embeddings → relevance fallback → 0
        assert calculate_semantic_similarity(None, None) == 0.0
        assert calculate_semantic_similarity(None, None, relevance_score=50) == 0.5


class TestGraphSupersessionAndReindex:
    def test_updates_edges_for_superseded_knowledge(self, client, headers):
        # 1. Capture and approve initial fact
        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": "Initial Rule",
                "kind": "note",
                "sensitivity": "internal",
                "content": "Our API tokens will expire after 90 days of issue without exception.",
            },
        )
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        item1 = client.post(
            f"/api/v1/proposals/{proposals[0]['id']}/approve", headers=headers, json={}
        ).json()
        assert item1["id"]

        # 2. Capture second fact that supersedes item1
        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": "Updated Rule",
                "kind": "note",
                "sensitivity": "internal",
                "content": "Our API tokens will expire after 30 days of issue to improve security posture.",
            },
        )
        proposals2 = [
            p
            for p in client.get("/api/v1/proposals", headers=headers).json()
            if p["status"] == "proposed"
        ]
        item2 = client.post(
            f"/api/v1/proposals/{proposals2[0]['id']}/approve",
            headers=headers,
            json={"supersedes_knowledge_id": item1["id"]},
        ).json()
        assert item2["id"]

        # Active graph (without superseded) should only contain active items
        active_graph = client.get("/api/v1/graph", headers=headers).json()
        active_mem_ids = {m["id"] for d in active_graph["documents"] for m in d["memories"]}
        assert item2["id"] in active_mem_ids
        assert item1["id"] not in active_mem_ids

        # Full evolutionary graph (include_superseded=true)
        full_graph = client.get("/api/v1/graph?include_superseded=true", headers=headers).json()
        full_mem_ids = {m["id"] for d in full_graph["documents"] for m in d["memories"]}
        assert item1["id"] in full_mem_ids
        assert item2["id"] in full_mem_ids

        updates_edges = [e for e in full_graph["edges"] if e["edgeType"] == "updates"]
        assert any(e["source"] == item1["id"] and e["target"] == item2["id"] for e in updates_edges)

    def test_reindex_knowledge_endpoint(self, client, headers):
        resp = client.post("/api/v1/knowledge/reindex", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total" in data
        assert "embedded" in data
        assert "fts_rebuilt" in data
