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
