"""Richer extraction: semantic chunking + summarize/tag (Supermemory port)."""

from __future__ import annotations

from brain.extraction import chunk_content, extract_tags, summarize


class TestChunkContent:
    def test_respects_paragraph_boundaries(self):
        content = "First paragraph one.\n\nSecond paragraph two.\n\nThird paragraph three."
        chunks = chunk_content(content, max_chunk=40, overlap=0)
        # each short paragraph is its own unit and does not merge mid-thought
        assert all("paragraph" in c for c in chunks)
        assert len(chunks) >= 2

    def test_caps_chunk_size_and_carries_overlap(self):
        sentences = " ".join(f"Sentence number {i} carries some words here." for i in range(20))
        chunks = chunk_content(sentences, max_chunk=120, overlap=20)
        assert len(chunks) > 1
        # every chunk respects the cap (first is exact-packed, later carry overlap)
        assert all(len(c) <= 120 + 20 for c in chunks)
        # overlap: a later chunk repeats the tail of the previous one
        assert any(chunks[i][-15:] in chunks[i + 1] for i in range(len(chunks) - 1))

    def test_empty_and_whitespace_yield_no_chunks(self):
        assert chunk_content("") == []
        assert chunk_content("   \n\n  ") == []


class TestSummarizeAndTags:
    def test_summary_is_the_lead_clause(self):
        assert summarize("We chose Postgres because it scales. Everything else follows.") == (
            "We chose Postgres because it scales."
        )

    def test_summary_trims_a_long_lead(self):
        long_lead = "word " * 60 + "."
        s = summarize(long_lead)
        assert len(s) <= 160 and s.endswith("…")

    def test_tags_are_salient_and_drop_stopwords(self):
        tags = extract_tags(
            "The retrieval pipeline uses reciprocal rank fusion because fusion ranks matter for recall.",
            limit=4,
        )
        assert "retrieval" in tags or "fusion" in tags
        assert "the" not in tags and "because" not in tags

    def test_tags_respect_limit(self):
        text = "alpha beta gamma delta epsilon zeta eta theta"
        assert len(extract_tags(text, limit=3)) == 3


class TestExtractionLandsOnProposals:
    def test_capture_produces_summary_and_tags(self, client, headers):
        import json as _json

        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": "Decision",
                "kind": "note",
                "sensitivity": "private",
                "content": (
                    "We chose Postgres because it scales under concurrent load and our "
                    "team already knows the operational model well."
                ),
            },
        )
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        assert proposals
        proposal = proposals[0]
        assert proposal.get("summary"), "summary must be extracted"
        tags = _json.loads(proposal.get("tags") or "[]")
        assert isinstance(tags, list) and tags, "tags must be a non-empty JSON list"
