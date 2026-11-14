"""Tests for Bit 3: Bi-Temporal Knowledge, Conflict Radar, and Fast Review.

Invariants:
1. Canonical knowledge is immutable and bi-temporal: valid intervals (valid_from, valid_to)
   and supersession chains (superseded_by) track truth through time.
2. Conflict Radar alerts reviewers to direct contradictions before review.
3. Batch approval and rejection accelerate the review inbox while enforcing access scoping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from brain.access import ReadScope, ensure_default_workspace
from brain.database import SessionLocal
from brain.migrate import add_temporal_knowledge_and_conflict_columns
from brain.models import Knowledge, KnowledgeRevision, Proposal
from brain.schemas import SourceCreate
from brain.services import (
    approve_proposal,
    check_proposal_conflict,
    create_source_with_proposals,
    search_knowledge,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class TestBiTemporalKnowledge:
    def test_approve_with_supersession_sets_valid_interval(self, client, headers):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

        content_1 = "We chose PostgreSQL as the primary production database."
        with SessionLocal() as db:
            src1 = create_source_with_proposals(
                db, SourceCreate(title="DB Decision 1", content=content_1, kind="decision"), ws_id
            )
            p1 = db.query(Proposal).filter(Proposal.source_id == src1.id).first()
            assert p1 is not None

            past_time = datetime.now(UTC) - timedelta(days=30)
            k1 = approve_proposal(db, p1, None, None, valid_from=past_time)
            k1_id = k1.id
            assert _as_utc(k1.valid_from) == past_time
            assert k1.valid_to is None
            assert k1.superseded_by is None

        content_2 = "We migrated to CockroachDB for distributed production operations."
        with SessionLocal() as db:
            src2 = create_source_with_proposals(
                db, SourceCreate(title="DB Decision 2", content=content_2, kind="decision"), ws_id
            )
            p2 = db.query(Proposal).filter(Proposal.source_id == src2.id).first()
            assert p2 is not None

            now = datetime.now(UTC)
            k2 = approve_proposal(db, p2, None, None, valid_from=now, supersedes_knowledge_id=k1_id)
            k2_id = k2.id

            assert _as_utc(k2.valid_from) == now
            assert k2.valid_to is None
            assert k2.superseded_by is None

            # Check superseded k1
            k1_refreshed = db.get(Knowledge, k1_id)
            assert k1_refreshed.superseded_by == k2_id
            assert _as_utc(k1_refreshed.valid_to) == now
            assert k1_refreshed.status == "superseded"

            # Check revision on k2 notes supersession
            rev = (
                db.query(KnowledgeRevision).filter(KnowledgeRevision.knowledge_id == k2_id).first()
            )
            assert rev is not None
            assert k1_id in rev.change_note

    def test_time_travel_search(self):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

            scope = ReadScope(workspace_id=ws_id, role="owner")
            t0 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            t1 = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)

            src = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Policy History",
                    content="Remote work is allowed on Fridays only. Later, remote work became flexible everyday.",
                    kind="note",
                ),
                ws_id,
            )
            props = db.query(Proposal).filter(Proposal.source_id == src.id).all()
            assert len(props) >= 2

            k1 = approve_proposal(db, props[0], None, None, valid_from=t0)
            k2 = approve_proposal(
                db, props[1], None, None, valid_from=t1, supersedes_knowledge_id=k1.id
            )

            # 1. Live search without as_of returns only active k2
            live_results = search_knowledge(db, scope, "remote work")
            assert any(item.id == k2.id for item in live_results)
            assert not any(item.id == k1.id for item in live_results)

            # 2. Time-travel query at March 2024 (between t0 and t1) returns k1!
            t_march = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
            past_results = search_knowledge(db, scope, "remote work", as_of=t_march)
            assert any(item.id == k1.id for item in past_results)
            assert not any(item.id == k2.id for item in past_results)

            # 3. Query with include_superseded=True returns both
            all_results = search_knowledge(db, scope, "remote work", include_superseded=True)
            ids = {item.id for item in all_results}
            assert k1.id in ids
            assert k2.id in ids


class TestConflictRadar:
    def test_detects_contradiction_with_active_knowledge(self):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

            # Seed approved knowledge
            src1 = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Storage Standard",
                    content="We chose PostgreSQL for production data storage.",
                    kind="decision",
                ),
                ws_id,
            )
            p1 = db.query(Proposal).filter(Proposal.source_id == src1.id).first()
            k1 = approve_proposal(db, p1, None, None)

            # Proposal with opposite polarity on the same topic
            opposing_text = "We do not use PostgreSQL for production data storage."
            conflict_id, note = check_proposal_conflict(db, ws_id, opposing_text, "decision")
            assert conflict_id == k1.id
            assert "opposite polarity" in note

            # Proposal with unrelated content has no conflict
            unrelated_text = "The annual company offsite will take place in Lisbon."
            no_conflict_id, no_note = check_proposal_conflict(db, ws_id, unrelated_text, "note")
            assert no_conflict_id is None
            assert no_note is None

    def test_inbox_proposals_carry_conflict_metadata(self):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

            src1 = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Encryption",
                    content="All customer data must be encrypted at rest with AES-256.",
                    kind="decision",
                ),
                ws_id,
            )
            p1 = db.query(Proposal).filter(Proposal.source_id == src1.id).first()
            k1 = approve_proposal(db, p1, None, None)

            # Ingest source that contradicts active knowledge
            src2 = create_source_with_proposals(
                db,
                SourceCreate(
                    title="New Note",
                    content="Customer data is not encrypted at rest in local environments.",
                    kind="note",
                ),
                ws_id,
            )
            p2 = db.query(Proposal).filter(Proposal.source_id == src2.id).first()
            assert p2 is not None
            assert p2.conflict_with_id == k1.id
            assert "Contradicts approved knowledge" in p2.conflict_note


class TestBatchReviewEndpoints:
    def test_batch_approve_and_batch_reject(self, client, headers):
        with SessionLocal() as db:
            workspace = ensure_default_workspace(db)
            db.commit()
            ws_id = workspace.id

            src = create_source_with_proposals(
                db,
                SourceCreate(
                    title="Multi Proposal Source",
                    content=(
                        "First actionable fact about our infrastructure.\n"
                        "Second actionable fact about our security protocols.\n"
                        "Third actionable fact to be declined in bulk review."
                    ),
                    kind="note",
                ),
                ws_id,
            )
            props = db.query(Proposal).filter(Proposal.source_id == src.id).all()
            assert len(props) >= 3
            p1_id, p2_id, p3_id = props[0].id, props[1].id, props[2].id

        # 1. Batch approve first two proposals
        resp_approve = client.post(
            "/api/v1/proposals/batch-approve",
            json={"proposal_ids": [p1_id, p2_id, "nonexistent_id"]},
            headers=headers,
        )
        assert resp_approve.status_code == 200
        data_approve = resp_approve.json()
        assert data_approve["approved_count"] == 2
        assert len(data_approve["knowledge_ids"]) == 2
        assert "nonexistent_id" in data_approve["failed_ids"]

        # 2. Batch reject third proposal
        resp_reject = client.post(
            "/api/v1/proposals/batch-reject",
            json={"proposal_ids": [p3_id], "reason": "Not actionable right now"},
            headers=headers,
        )
        assert resp_reject.status_code == 200
        data_reject = resp_reject.json()
        assert data_reject["declined_count"] == 1
        assert p3_id in data_reject["declined_ids"]

        # 3. Verify final DB states
        with SessionLocal() as db:
            assert db.get(Proposal, p1_id).status == "approved"
            assert db.get(Proposal, p2_id).status == "approved"
            assert db.get(Proposal, p3_id).status == "rejected"


class TestMigrationParity:
    def test_migration_is_idempotent(self):
        # Running the migration function multiple times should not fail
        added_1 = add_temporal_knowledge_and_conflict_columns()
        assert isinstance(added_1, list)
        added_2 = add_temporal_knowledge_and_conflict_columns()
        # Second run should find all columns already exist and add 0
        assert added_2 == []
