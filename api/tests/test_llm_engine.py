"""Tests for Bit 2: Native LLM Extraction Engine & Verbatim Span Verifier.

Guards:
1. Anti-hallucination guard: Any quote not matching verbatim in source text is rejected.
2. Degrades gracefully on timeout or HTTP error (never crashes reads).
3. Models never dictate workspace, owner, status, or role.
4. Preserves citation links from proposal down to exact SourceSpan.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx

from brain.access import ReadScope, ensure_default_workspace
from brain.config import Settings
from brain.database import SessionLocal
from brain.engine import (
    DerivedFact,
    DeterministicEngine,
    LLMExtractionEngine,
    get_engine,
    verify_span,
)
from brain.models import Proposal, ProposalEvidence, SourceSpan
from brain.schemas import SourceCreate
from brain.services import create_source_with_proposals, sync_derived_proposals


class TestSpanVerifier:
    """Verifies that quotes match character-for-character within source text."""

    source = (
        "Project Atlas was initiated in Q1 2024 to modernize the cargo routing pipeline.\n"
        "We chose PostgreSQL as the primary database for all production deployments.\n"
        "Deployment to staging failed twice due to missing schema migrations."
    )

    def test_exact_offset_match(self):
        quote = "We chose PostgreSQL as the primary database for all production deployments."
        start = self.source.find(quote)
        end = start + len(quote)
        res = verify_span(self.source, quote, start, end)
        assert res is not None
        v_start, v_end, v_quote = res
        assert v_start == start
        assert v_end == end
        assert v_quote == quote
        assert self.source[v_start:v_end] == quote

    def test_offset_with_whitespace_stripping(self):
        quote = "We chose PostgreSQL as the primary database for all production deployments."
        start = self.source.find(quote)
        end = start + len(quote)
        # LLM gave offsets with 2 spaces padding
        padded_start = max(0, start - 2)
        padded_end = end + 2
        res = verify_span(self.source, quote, padded_start, padded_end)
        assert res is not None
        v_start, v_end, v_quote = res
        assert v_quote == quote
        assert self.source[v_start:v_end] == quote

    def test_substring_search_when_offsets_missing(self):
        quote = "Project Atlas was initiated in Q1 2024 to modernize the cargo routing pipeline."
        res = verify_span(self.source, quote, -1, -1)
        assert res is not None
        v_start, v_end, v_quote = res
        assert v_start == 0
        assert v_end == len(quote)
        assert v_quote == quote

    def test_normalized_whitespace_across_newlines(self):
        multi_line = "First sentence.\nSecond line with some   spaced words.\nThird sentence."
        quote = "Second line with some spaced words."
        res = verify_span(multi_line, quote)
        assert res is not None
        v_start, v_end, v_quote = res
        assert multi_line[v_start:v_end] == "Second line with some   spaced words."

    def test_rejects_hallucinated_fact(self):
        """The model fabricated a claim that does not exist in the source."""
        hallucinated = "We chose MySQL as the primary database for all production deployments."
        assert verify_span(self.source, hallucinated) is None

    def test_rejects_altered_or_paraphrased_quote(self):
        """Even a 1-word alteration is rejected by the verbatim verifier."""
        altered = "Project Atlas was launched in Q1 2024 to modernize the cargo routing pipeline."
        assert verify_span(self.source, altered) is None

    def test_rejects_empty_inputs(self):
        assert verify_span(self.source, "") is None
        assert verify_span(self.source, "   ") is None
        assert verify_span("", "something") is None


class TestLLMExtractionEngine:
    def test_remote_requires_api_key(self):
        engine = LLMExtractionEngine(base_url="https://api.openai.com/v1", api_key="")
        status = engine.available()
        assert not status.available
        assert "No API key" in status.detail

    def test_local_endpoint_allows_no_api_key(self, monkeypatch):
        engine = LLMExtractionEngine(base_url="http://localhost:11434/v1", api_key="")

        def fake_get(url, **kwargs):
            return httpx.Response(200, json={"data": [{"id": "llama3"}]})

        monkeypatch.setattr(httpx, "get", fake_get)
        status = engine.available()
        assert status.available
        assert "LLM ready" in status.detail

    def test_ingest_filters_hallucinated_candidates(self, monkeypatch):
        source_text = (
            "We decided to deprecate SQLite in production and mandate PostgreSQL 16. "
            "The team also learned that connection pooling is mandatory."
        )

        mock_llm_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "candidates": [
                                    {
                                        "statement": "PostgreSQL 16 is mandatory for production.",
                                        "type": "decision",
                                        "exact_quote": "We decided to deprecate SQLite in production and mandate PostgreSQL 16.",
                                        "start_offset": 0,
                                        "end_offset": 70,
                                    },
                                    {
                                        "statement": "The team adopted Redis for caching.",
                                        "type": "decision",
                                        "exact_quote": "We chose Redis for in-memory session caching across all pods.",
                                        "start_offset": 100,
                                        "end_offset": 150,
                                    },
                                ]
                            }
                        )
                    }
                }
            ]
        }

        def fake_post(url, **kwargs):
            return httpx.Response(200, json=mock_llm_response)

        monkeypatch.setattr(httpx, "post", fake_post)

        engine = LLMExtractionEngine(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o-mini",
        )

        doc_id = engine.ingest(source_text, "org_ws_test")
        assert doc_id.startswith("doc_")

        derived = engine.derived(doc_id)
        # Redis hallucination MUST be filtered out
        assert len(derived) == 1
        fact = derived[0]
        assert fact.text == "PostgreSQL 16 is mandatory for production."
        assert (
            fact.exact_quote
            == "We decided to deprecate SQLite in production and mandate PostgreSQL 16."
        )
        assert fact.start_offset == 0
        assert fact.end_offset == len(fact.exact_quote)
        assert fact.fact_type == "decision"

    def test_ingest_handles_markdown_json(self, monkeypatch):
        source_text = "The migration was scheduled for midnight."
        fenced_content = (
            "Here is the extraction:\n```json\n"
            "{\n"
            '  "candidates": [\n'
            "    {\n"
            '      "statement": "Migration occurs at midnight.",\n'
            '      "type": "decision",\n'
            '      "exact_quote": "The migration was scheduled for midnight."\n'
            "    }\n"
            "  ]\n"
            "}\n```"
        )

        def fake_post(url, **kwargs):
            return httpx.Response(200, json={"choices": [{"message": {"content": fenced_content}}]})

        monkeypatch.setattr(httpx, "post", fake_post)
        engine = LLMExtractionEngine(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        doc_id = engine.ingest(source_text, "org_ws_test")
        facts = engine.derived(doc_id)
        assert len(facts) == 1
        assert facts[0].text == "Migration occurs at midnight."

    def test_ingest_degrades_gracefully_on_network_failure(self, monkeypatch):
        def fake_post(url, **kwargs):
            raise httpx.ConnectTimeout("timeout")

        monkeypatch.setattr(httpx, "post", fake_post)
        engine = LLMExtractionEngine(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
        )
        assert engine.ingest("Some text", "org_ws_test") == ""
        assert engine.derived("doc_nonexistent") == []


class TestDerivedProposalsSpanLinking:
    """Verifies that derived facts with exact quotes create linked SourceSpans."""

    def test_sync_derived_proposals_creates_spans_and_evidence(self, monkeypatch):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

        content = "We decided to use PostgreSQL 16 for all production databases."
        quote = "We decided to use PostgreSQL 16 for all production databases."
        start = 0
        end = len(quote)

        mock_fact = DerivedFact(
            memory_id="mem_test_123",
            text="PostgreSQL 16 is standard in production.",
            support_count=2,
            created_at="2026-11-10T00:00:00Z",
            exact_quote=quote,
            start_offset=start,
            end_offset=end,
            fact_type="decision",
        )

        mock_engine = MagicMock()
        mock_engine.name = "llm"
        mock_engine.ingest.return_value = "doc_test_1"
        mock_engine.derived.return_value = [mock_fact]

        monkeypatch.setattr("brain.services.get_engine", lambda: mock_engine)

        with SessionLocal() as db:
            source = create_source_with_proposals(
                db,
                SourceCreate(title="Database Choice", content=content, kind="note"),
                workspace_id=ws_id,
            )
            # Pretend engine accepted it
            source.engine_document_id = "doc_test_1"
            db.commit()

            scope = ReadScope(workspace_id=ws_id, role="owner")
            created_count = sync_derived_proposals(db, scope, source.id)
            assert created_count == 1

            from sqlalchemy import select

            # Verify Proposal
            prop = db.scalar(
                select(Proposal).where(
                    Proposal.source_id == source.id,
                    Proposal.engine_memory_id == "mem_test_123",
                )
            )
            assert prop is not None
            assert prop.type == "decision"
            assert prop.source_excerpt == quote

            # Verify Evidence links to a concrete SourceSpan
            evidence = db.scalar(
                select(ProposalEvidence).where(ProposalEvidence.proposal_id == prop.id)
            )
            assert evidence is not None
            assert evidence.source_span_id is not None

            # Verify the SourceSpan
            span = db.get(SourceSpan, evidence.source_span_id)
            assert span is not None
            assert span.text == quote
            assert span.start_offset == start
            assert span.end_offset == end


class TestStrictLocalPrecedence:
    def test_strict_local_overrides_llm_config(self, monkeypatch):
        import brain.config as config_module
        import brain.engine as engine_module

        settings = Settings(
            strict_local=True,
            llm_extraction_enabled=True,
            llm_api_key="sk-test-live",
        )
        monkeypatch.setattr(config_module, "get_settings", lambda: settings)
        monkeypatch.setattr(engine_module, "get_settings", lambda: settings)

        engine = get_engine()
        assert isinstance(engine, DeterministicEngine)
        assert "strict local" in engine_module._registry.reason
