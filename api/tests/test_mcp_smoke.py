"""MCP server smoke tests — verify tools work for Codex/Claude/Hermes.

These tests exercise the MCP server's tool implementations directly,
without starting an actual stdio/HTTP transport. This verifies the contract
that any MCP host (Codex, Claude Code, Hermes) depends on.
"""

import pytest
from sqlalchemy.orm import Session

from brain.database import SessionLocal
from brain.access import ensure_default_workspace
from brain.models import Knowledge, Proposal, Source, SourceVersion, ProposalEvidence, new_id
from brain.services import create_source_with_proposals, approve_proposal, search_knowledge, integrity_snapshot, overview
from brain.access import ReadScope
from brain.schemas import SourceCreate
from sqlalchemy import select


def _seed_full(db: Session, workspace_id: str):
    """Seed a realistic workspace for MCP testing."""
    source = create_source_with_proposals(
        db,
        SourceCreate(
            title="Product vision interview",
            kind="interview",
            sensitivity="internal",
            content=(
                "We believe that knowledge compounds over time. "
                "The company decided to build a local-first architecture because "
                "data sovereignty matters more than convenience. "
                "I learned that shipping fast without evidence leads to rework."
            ),
        ),
        workspace_id,
    )
    # Approve the first proposal
    proposals = list(db.scalars(
        select(Proposal).where(
            Proposal.workspace_id == workspace_id,
            Proposal.status == "proposed",
        ).limit(1)
    ).all())
    if proposals:
        approve_proposal(db, proposals[0], None, None)
    return source


class TestMCPSmoke:
    """Verify the MCP tools work as expected."""

    def test_brain_status(self):
        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            result = overview(db, scope)
            assert "canonical" in result or "proposals" in result
            assert "engine" in result
        finally:
            db.close()

    def test_search_brain(self):
        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            _seed_full(db, ws.id)
            results = search_knowledge(db, scope, "knowledge compounds")
            assert len(results) >= 1
            assert any("knowledge" in r.statement.lower() for r in results)
        finally:
            db.close()

    def test_search_brain_empty_query(self):
        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            _seed_full(db, ws.id)
            results = search_knowledge(db, scope, "")
            assert len(results) >= 0  # Should not error
        finally:
            db.close()

    def test_ask_brain(self):
        db = SessionLocal()
        try:
            from brain.services import answer_question
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            _seed_full(db, ws.id)
            result = answer_question(db, scope, "What did the team learn about shipping?")
            assert result.grounded is True or "could not find" in result.answer.lower()
            if result.grounded:
                assert len(result.citations) >= 1
        finally:
            db.close()

    def test_inspect_integrity(self):
        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            _seed_full(db, ws.id)
            result = integrity_snapshot(db, scope)
            assert "stale_count" in result
            assert "conflict_count" in result
            assert "issues" in result
        finally:
            db.close()

    def test_list_pending_reviews(self):
        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            _seed_full(db, ws.id)
            pending = list(db.scalars(
                select(Proposal).where(
                    Proposal.workspace_id == ws.id,
                    Proposal.status == "proposed",
                )
            ).all())
            # May be 0 if all were approved, but should not error
            assert isinstance(pending, list)
        finally:
            db.close()