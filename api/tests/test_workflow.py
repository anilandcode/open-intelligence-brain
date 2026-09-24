from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.database import Base, engine
from brain.models import (
    Knowledge,
    KnowledgeRevision,
    Proposal,
    ProposalEvidence,
    Source,
    SourceVersion,
)
from brain.services import backfill_provenance


def test_requires_owner_token(client):
    response = client.get("/api/v1/sources")
    assert response.status_code == 401


def test_source_to_canonical_to_grounded_answer(client, headers):
    source_response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Founder design interview",
            "kind": "interview",
            "sensitivity": "private",
            "content": "We believe evidence-backed design decisions are easier to defend and reuse. The system should preserve the source behind every approved claim.",
        },
    )
    assert source_response.status_code == 201
    assert source_response.json()["proposal_count"] == 2

    proposals = client.get("/api/v1/proposals", headers=headers).json()
    assert len(proposals) == 2

    approval = client.post(
        f"/api/v1/proposals/{proposals[0]['id']}/approve",
        headers=headers,
        json={},
    )
    assert approval.status_code == 200
    knowledge = approval.json()
    assert knowledge["status"] == "canonical"

    answer = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "Why are evidence-backed design decisions useful?"},
    )
    assert answer.status_code == 200
    assert answer.json()["grounded"] is True
    assert answer.json()["citations"][0]["source_id"] == source_response.json()["id"]


def test_chat_abstains_without_approved_knowledge(client, headers):
    answer = client.post(
        "/api/v1/chat", headers=headers, json={"question": "What is our launch price?"}
    )
    assert answer.status_code == 200
    assert answer.json()["grounded"] is False
    assert answer.json()["citations"] == []


def test_proposal_cannot_be_approved_twice(client, headers):
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Decision note",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that every important knowledge item needs an inspectable source before public use.",
        },
    )
    proposal_id = client.get("/api/v1/proposals", headers=headers).json()[0]["id"]
    first = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers, json={})
    second = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers, json={})
    assert first.status_code == 200
    assert second.status_code == 409


def test_export_is_portable_and_versioned(client, headers):
    response = client.get("/api/v1/export", headers=headers)
    assert response.status_code == 200
    assert response.json()["schema_version"] == 2
    assert response.json()["exported_from"] == "open-intelligence-brain"
    assert "source_versions" in response.json()
    assert "knowledge_revisions" in response.json()


def test_source_versions_are_hashed_and_make_old_knowledge_stale(client, headers):
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Versioned decision",
            "kind": "decision",
            "sensitivity": "private",
            "content": "We decided that every approved claim must retain exact evidence from its source.",
        },
    ).json()
    assert source["current_version"] == 1
    assert len(source["content_hash"]) == 64

    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    knowledge = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve",
        headers=headers,
        json={},
    ).json()
    assert knowledge["stale"] is False

    version = client.post(
        f"/api/v1/sources/{source['id']}/versions",
        headers=headers,
        json={
            "content": (
                "We decided that every approved claim must retain exact evidence and "
                "receive a new review when the source changes."
            ),
            "change_note": "Clarified the review requirement",
        },
    )
    assert version.status_code == 201
    assert version.json()["version"] == 2
    assert version.json()["span_count"] == 1
    backup = client.get("/api/v1/export", headers=headers).json()
    latest = next(item for item in backup["source_versions"] if item["id"] == version.json()["id"])
    span = next(
        item for item in backup["source_spans"] if item["source_version_id"] == latest["id"]
    )
    assert latest["content"][span["start_offset"] : span["end_offset"]] == span["text"]
    assert len(span["span_hash"]) == 64

    refreshed = client.get("/api/v1/knowledge", headers=headers).json()[0]
    assert refreshed["id"] == knowledge["id"]
    assert refreshed["stale"] is True
    integrity = client.get("/api/v1/integrity", headers=headers).json()
    assert integrity["stale_count"] == 1

    duplicate = client.post(
        f"/api/v1/sources/{source['id']}/versions",
        headers=headers,
        json={
            "content": version.json()["content"],
            "change_note": "Accidental duplicate",
        },
    )
    assert duplicate.status_code == 409


def test_knowledge_supersession_preserves_revision_history(client, headers):
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Revision decision",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that canonical language must be revised through an explicit human action.",
        },
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    knowledge = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={}
    ).json()
    superseded = client.post(
        f"/api/v1/knowledge/{knowledge['id']}/supersede",
        headers=headers,
        json={
            "statement": (
                "Canonical language must be revised through an explicit, recorded human action."
            ),
            "rationale": "The revision makes the audit requirement explicit.",
            "change_note": "Clarified that revisions are recorded",
        },
    )
    assert superseded.status_code == 200
    assert superseded.json()["version"] == 2
    assert superseded.json()["revision_count"] == 2

    revisions = client.get(f"/api/v1/knowledge/{knowledge['id']}/revisions", headers=headers).json()
    assert [revision["revision"] for revision in revisions] == [2, 1]
    assert revisions[1]["statement"] == knowledge["statement"]


def test_integrity_reports_possible_opposite_polarity_conflicts(client, headers):
    for title, content in [
        (
            "Positive policy",
            "We decided that coding agents should retain approved evidence in every context package.",
        ),
        (
            "Negative policy",
            "We decided that coding agents should not retain approved evidence in every context package.",
        ),
    ]:
        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": title,
                "kind": "decision",
                "sensitivity": "internal",
                "content": content,
            },
        )
    for proposal in client.get("/api/v1/proposals", headers=headers).json():
        client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})

    integrity = client.get("/api/v1/integrity", headers=headers).json()
    assert integrity["conflict_count"] == 1
    assert integrity["issues"][0]["kind"] == "possible_conflict"


def test_deletion_preview_never_deletes_and_blocks_dependencies(client, headers):
    source = client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Protected source",
            "kind": "note",
            "sensitivity": "private",
            "content": "We learned that deletion should be previewed before dependent knowledge is affected.",
        },
    ).json()
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})

    preview = client.get(f"/api/v1/sources/{source['id']}/deletion-preview", headers=headers).json()
    assert preview["blocked"] is True
    assert preview["canonical_items"] == 1
    assert len(client.get("/api/v1/sources", headers=headers).json()) == 1


def test_backup_restores_same_canonical_result_into_empty_workspace(client, headers):
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Backup decision",
            "kind": "decision",
            "sensitivity": "private",
            "content": "We decided that a verified backup must reproduce the same canonical knowledge.",
        },
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    approved = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={}
    ).json()
    backup = client.get("/api/v1/export", headers=headers).json()

    blocked_preview = client.post(
        "/api/v1/restore/preview",
        headers=headers,
        json={"backup": backup},
    ).json()
    assert blocked_preview["valid"] is False
    assert blocked_preview["empty_workspace"] is False

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    preview = client.post(
        "/api/v1/restore/preview",
        headers=headers,
        json={"backup": backup},
    ).json()
    assert preview["valid"] is True
    restored = client.post(
        "/api/v1/restore",
        headers=headers,
        json={"backup": backup, "confirm_empty_workspace": True},
    )
    assert restored.status_code == 200
    restored_knowledge = client.get("/api/v1/knowledge", headers=headers).json()
    assert restored_knowledge[0]["id"] == approved["id"]
    assert restored_knowledge[0]["statement"] == approved["statement"]


def test_pre_m2_records_receive_provenance_without_wording_changes():
    with Session(engine) as db:
        source = Source(
            id="src_legacy",
            title="Legacy note",
            kind="note",
            sensitivity="private",
            content="We learned that compatibility migrations must preserve approved wording exactly.",
        )
        proposal = Proposal(
            id="prop_legacy",
            source_id=source.id,
            type="lesson",
            statement=source.content,
            rationale="Legacy proposal",
            source_excerpt=source.content,
            status="approved",
        )
        knowledge = Knowledge(
            id="know_legacy",
            proposal_id=proposal.id,
            source_id=source.id,
            type="lesson",
            statement=source.content,
            rationale="Legacy rationale",
            source_excerpt=source.content,
        )
        db.add_all([source, proposal, knowledge])
        db.commit()
        original = knowledge.statement

        backfill_provenance(db)

        assert db.scalar(select(func.count(SourceVersion.id))) == 1
        assert db.scalar(select(func.count(ProposalEvidence.proposal_id))) == 1
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 1
        assert db.get(Knowledge, knowledge.id).statement == original
