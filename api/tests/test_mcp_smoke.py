"""MCP server smoke tests — verify tools work for Codex/Claude/Hermes.

These tests exercise the MCP server's tool implementations directly,
without starting an actual stdio/HTTP transport. This verifies the contract
that any MCP host (Codex, Claude Code, Hermes) depends on.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.access import ReadScope, ensure_default_workspace
from brain.database import SessionLocal
from brain.models import Proposal
from brain.schemas import SourceCreate
from brain.services import (
    approve_proposal,
    create_source_with_proposals,
    integrity_snapshot,
    overview,
    search_knowledge,
)


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
    proposals = list(
        db.scalars(
            select(Proposal)
            .where(
                Proposal.workspace_id == workspace_id,
                Proposal.status == "proposed",
            )
            .limit(1)
        ).all()
    )
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
            pending = list(
                db.scalars(
                    select(Proposal).where(
                        Proposal.workspace_id == ws.id,
                        Proposal.status == "proposed",
                    )
                ).all()
            )
            # May be 0 if all were approved, but should not error
            assert isinstance(pending, list)
        finally:
            db.close()

    def test_search_brain_scoped_temporal_time_travel(self):
        from datetime import UTC, datetime, timedelta

        from brain.mcp_server import search_brain_scoped

        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            # Ingest and approve two facts
            src = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Database Standard Policy",
                    kind="decision",
                    sensitivity="internal",
                    content="We designate PostgreSQL 16 as our production standard database.",
                ),
                ws.id,
            )
            prop = db.scalars(
                select(Proposal).where(Proposal.source_id == src.id, Proposal.status == "proposed")
            ).first()
            assert prop is not None
            past_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)
            k1 = approve_proposal(db, prop, None, None, valid_from=past_time)

            # Search with current time -> finds it
            res_now = search_brain_scoped("PostgreSQL 16", 10, scope)
            assert any(item.knowledge_id == k1.id for item in res_now.items)
            hit = next(item for item in res_now.items if item.knowledge_id == k1.id)
            assert hit.valid_from is not None
            assert hit.superseded_by is None

            # Search with historical time prior to valid_from -> does not find it
            ancient_time = (past_time - timedelta(days=365)).isoformat()
            res_past = search_brain_scoped("PostgreSQL 16", 10, scope, as_of=ancient_time)
            assert not any(item.knowledge_id == k1.id for item in res_past.items)
        finally:
            db.close()

    def test_list_pending_reviews_scoped_includes_conflict(self):
        from brain.mcp_server import list_pending_reviews_scoped

        db = SessionLocal()
        try:
            ws = ensure_default_workspace(db)
            scope = ReadScope(ws.id, "owner")
            # First create and approve a real knowledge item so FK constraint on conflict_with_id is satisfied in PostgreSQL
            base_src = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Base Conflict Source",
                    kind="decision",
                    sensitivity="internal",
                    content="We mandate strict mutual TLS across all internal microservices.",
                ),
                ws.id,
            )
            base_prop = db.scalars(
                select(Proposal).where(
                    Proposal.source_id == base_src.id, Proposal.status == "proposed"
                )
            ).first()
            assert base_prop is not None
            k_conflict = approve_proposal(db, base_prop, None, None)

            # Create a second source that produces a proposal and link conflict_with_id to k_conflict.id
            src = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Conflict Test Source",
                    kind="decision",
                    sensitivity="internal",
                    content="Contradictory claim for conflict radar test in reviews.",
                ),
                ws.id,
            )
            prop = db.scalars(
                select(Proposal).where(Proposal.source_id == src.id, Proposal.status == "proposed")
            ).first()
            assert prop is not None
            prop.conflict_with_id = k_conflict.id
            prop.conflict_note = f"Direct contradiction detected with {k_conflict.id}"
            db.commit()

            queue = list_pending_reviews_scoped(10, scope)
            matching = [item for item in queue.items if item.proposal_id == prop.id]
            assert len(matching) == 1
            assert matching[0].conflict_with_id == k_conflict.id
            assert "contradiction" in matching[0].conflict_note.lower()
        finally:
            db.close()
