"""Tests for routines (daily digest) and usage tracking."""

import pytest
from sqlalchemy.orm import Session

from brain.database import SessionLocal
from brain.models import Knowledge, Proposal, Source, SourceVersion, ProposalEvidence, new_id
from brain.access import ReadScope
from brain.routines import build_digest, format_digest, RoutineDigest, LogDelivery
from brain.usage import track_usage, track_batch, top_used, unused_knowledge, usage_summary


def _seed(db: Session, workspace_id: str):
    """Seed minimal data for routine/usage tests."""
    source = Source(
        id=new_id("src"), workspace_id=workspace_id,
        title="Test", kind="note", sensitivity="private",
        content="Test content for routines.",
    )
    db.add(source)
    db.flush()
    version = SourceVersion(
        id=new_id("srcv"), source_id=source.id, version=1,
        content_hash="a" * 64, content="Test content for routines.",
    )
    db.add(version)
    db.flush()
    proposal = Proposal(
        id=new_id("prop"), workspace_id=workspace_id,
        source_id=source.id, type="fact",
        statement="Test proposal for routines.",
        source_excerpt="Test content for routines.",
    )
    db.add(proposal)
    db.flush()
    db.add(ProposalEvidence(
        proposal_id=proposal.id,
        source_version_id=version.id,
    ))
    knowledge = Knowledge(
        id=new_id("know"), workspace_id=workspace_id,
        proposal_id=proposal.id, source_id=source.id,
        type="fact", statement="Test knowledge for routines.",
        source_excerpt="Test content for routines.",
    )
    db.add(knowledge)
    db.commit()
    return source, proposal, knowledge


class TestRoutines:
    def test_digest_counts(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            source, proposal, knowledge = _seed(db, ws.id)
            scope = ReadScope(ws.id, "owner")
            digest = build_digest(db, scope)
            assert isinstance(digest, RoutineDigest)
            assert digest.pending_proposals >= 1
            assert digest.recent_sources >= 1
            assert len(digest.summary) > 0
        finally:
            db.close()

    def test_format_digest(self):
        digest = RoutineDigest(
            pending_proposals=3,
            stale_knowledge=1,
            conflict_count=0,
            summary="Test summary",
        )
        formatted = format_digest(digest, "Test Workspace")
        assert "Brain Update" in formatted
        assert "Test Workspace" in formatted
        assert "Test summary" in formatted

    def test_empty_digest(self):
        digest = RoutineDigest()
        assert digest.is_empty()
        formatted = format_digest(digest)
        assert "Nothing needs attention" in formatted or "Brain Update" in formatted

    def test_log_delivery(self):
        delivery = LogDelivery()
        assert delivery.send("test message", "test") is True


class TestUsage:
    def test_track_usage(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            _, _, knowledge = _seed(db, ws.id)
            event = track_usage(db, ws.id, knowledge.id, context="search", query="test query")
            assert event.knowledge_id == knowledge.id
            assert event.context == "search"
            db.commit()
        finally:
            db.close()

    def test_track_batch(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            _, _, knowledge = _seed(db, ws.id)
            count = track_batch(db, ws.id, [knowledge.id, knowledge.id], context="answer")
            assert count == 2
        finally:
            db.close()

    def test_usage_summary(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            _, _, knowledge = _seed(db, ws.id)
            track_usage(db, ws.id, knowledge.id, context="search")
            db.commit()
            summary = usage_summary(db, ws.id)
            assert summary["total_knowledge"] >= 1
            assert summary["total_usage_events"] >= 1
            assert summary["unique_atoms_used"] >= 1
        finally:
            db.close()

    def test_top_used(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            _, _, knowledge = _seed(db, ws.id)
            track_usage(db, ws.id, knowledge.id, context="search")
            track_usage(db, ws.id, knowledge.id, context="answer")
            db.commit()
            top = top_used(db, ws.id)
            assert len(top) >= 1
            assert top[0]["count"] >= 2
        finally:
            db.close()

    def test_unused_knowledge(self):
        db = SessionLocal()
        try:
            from brain.access import ensure_default_workspace
            ws = ensure_default_workspace(db)
            _, _, knowledge = _seed(db, ws.id)
            unused = unused_knowledge(db, ws.id)
            # The seeded knowledge should be unused
            ids = [u["id"] for u in unused]
            assert knowledge.id in ids
        finally:
            db.close()