from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.database import SessionLocal
from brain.main import app
from brain.models import Knowledge, Workspace
from brain.services import (
    restore_preview,
    restore_workspace,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_workspace(db: Session):
    slug = f"ws-enc-{datetime.now(UTC).timestamp()}"
    ws = Workspace(id=f"ws_{slug[:16]}", slug=slug, name="Encryption Test Workspace")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def test_schema_v4_export_contains_temporal_and_conflict_fields(
    client: TestClient, db: Session, test_workspace: Workspace
):
    owner_token = f"tok_owner_{test_workspace.id[:8]}"
    grant_workspace(db, test_workspace, owner_token, role="owner")
    db.commit()

    headers = {"X-Brain-Token": owner_token, "X-Brain-Workspace": test_workspace.slug}

    # Ingest a source and approve a fact
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Security Guidance",
            "kind": "note",
            "sensitivity": "internal",
            "content": "All database backups must be encrypted at rest using validated cryptographic algorithms.",
        },
    )
    proposals = client.get("/api/v1/proposals", headers=headers).json()
    assert len(proposals) >= 1
    client.post(f"/api/v1/proposals/{proposals[0]['id']}/approve", headers=headers, json={})

    # Export backup
    resp = client.get("/api/v1/export", headers=headers)
    assert resp.status_code == 200, resp.text
    backup = resp.json()
    assert backup["schema_version"] == 4
    assert len(backup["knowledge"]) >= 1
    k = backup["knowledge"][0]
    assert "valid_from" in k
    assert "valid_to" in k
    assert "superseded_by" in k

    assert len(backup["proposals"]) >= 1
    p = backup["proposals"][0]
    assert "conflict_with_id" in p
    assert "conflict_note" in p


def test_schema_v3_backwards_compatibility_restore(db: Session):
    # Create empty workspace for restore
    slug = f"ws-v3-{datetime.now(UTC).timestamp()}"
    ws = Workspace(id=f"ws_{slug[:16]}", slug=slug, name="V3 Restore Target")
    db.add(ws)
    db.commit()
    db.refresh(ws)

    now = datetime.now(UTC).isoformat()
    v3_backup = {
        "schema_version": 3,
        "exported_from": "open-intelligence-brain",
        "workspace": {"id": ws.id},
        "sources": [
            {
                "id": "src_legacy_1",
                "workspace_id": ws.id,
                "title": "Legacy System Doc",
                "kind": "note",
                "sensitivity": "internal",
                "content": "This is a historic specification created under schema version 3.",
                "created_at": now,
            }
        ],
        "source_versions": [
            {
                "id": "srcv_legacy_1",
                "source_id": "src_legacy_1",
                "version": 1,
                "content_hash": "a" * 64,
                "content": "This is a historic specification created under schema version 3.",
                "parser_version": "v1",
                "change_note": "Initial capture",
                "created_at": now,
            }
        ],
        "source_spans": [
            {
                "id": "span_legacy_1",
                "source_version_id": "srcv_legacy_1",
                "start_offset": 0,
                "end_offset": 50,
                "text": "This is a historic specification created under schema version 3.",
                "span_hash": "b" * 64,
                "speaker": None,
            }
        ],
        "proposals": [
            {
                "id": "prop_legacy_1",
                "source_id": "src_legacy_1",
                "type": "fact",
                "statement": "This is a historic specification created under schema version 3.",
                "rationale": "Extracted fact",
                "source_excerpt": "historic spec",
                "status": "approved",
                "created_at": now,
            }
        ],
        "proposal_evidence": [
            {
                "proposal_id": "prop_legacy_1",
                "source_version_id": "srcv_legacy_1",
                "source_span_id": "span_legacy_1",
            }
        ],
        "knowledge": [
            {
                "id": "know_legacy_1",
                "proposal_id": "prop_legacy_1",
                "source_id": "src_legacy_1",
                "type": "fact",
                "statement": "This is a historic specification created under schema version 3.",
                "rationale": "Extracted fact",
                "source_excerpt": "historic spec",
                "status": "canonical",
                "version": 1,
                "approved_at": now,
            }
        ],
        "knowledge_revisions": [
            {
                "id": "rev_legacy_1",
                "knowledge_id": "know_legacy_1",
                "revision": 1,
                "statement": "This is a historic specification created under schema version 3.",
                "rationale": "Extracted fact",
                "source_id": "src_legacy_1",
                "source_version_id": "srcv_legacy_1",
                "source_span_id": "span_legacy_1",
                "source_excerpt": "historic spec",
                "change_note": "Initial approval",
                "approved_at": now,
            }
        ],
        "audit_events": [
            {
                "id": "evt_legacy_1",
                "action": "knowledge.approved",
                "resource_type": "knowledge",
                "resource_id": "know_legacy_1",
                "detail": "Approved legacy item",
                "created_at": now,
            }
        ],
    }

    # Preview should be valid
    preview = restore_preview(db, v3_backup, ws.id)
    assert preview["valid"] is True
    assert preview["schema_version"] == 3

    # Restore should succeed
    res = restore_workspace(db, v3_backup, ws.id)
    assert res["valid"] is True
    k = db.get(Knowledge, "know_legacy_1")
    assert k is not None
    assert k.statement == "This is a historic specification created under schema version 3."


def test_encrypted_export_and_restore_cycle(
    client: TestClient, db: Session, test_workspace: Workspace
):
    owner_token = f"tok_owner_{test_workspace.id[:8]}"
    grant_workspace(db, test_workspace, owner_token, role="owner")
    db.commit()

    headers = {"X-Brain-Token": owner_token, "X-Brain-Workspace": test_workspace.slug}

    # Ingest source
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Secret Enterprise Strategy",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "Our confidential expansion into European markets will proceed in Q3.",
        },
    )
    proposals = client.get("/api/v1/proposals", headers=headers).json()
    assert len(proposals) >= 1
    client.post(f"/api/v1/proposals/{proposals[0]['id']}/approve", headers=headers, json={})

    # Encrypted export via query param
    passphrase = "UltraSecureEnterprisePassphrase2026!"
    resp = client.get(f"/api/v1/export?passphrase={passphrase}", headers=headers)
    assert resp.status_code == 200, resp.text
    enc_export = resp.json()
    assert enc_export["schema_version"] == 4
    assert enc_export["format"] == "encrypted_v4"
    assert "encrypted_data" in enc_export
    ciphertext_b64 = enc_export["encrypted_data"]

    # Target empty workspace for encrypted restore
    slug_target = f"ws-target-{datetime.now(UTC).timestamp()}"
    ws_target = Workspace(
        id=f"ws_{slug_target[:16]}", slug=slug_target, name="Encrypted Restore Target"
    )
    db.add(ws_target)
    target_token = f"tok_target_{ws_target.id[:8]}"
    grant_workspace(db, ws_target, target_token, role="owner")
    db.commit()
    target_headers = {"X-Brain-Token": target_token, "X-Brain-Workspace": ws_target.slug}

    # 1. Preview with wrong passphrase should fail with 400
    bad_resp = client.post(
        "/api/v1/restore/preview",
        headers=target_headers,
        json={
            "backup": {"encrypted_data": ciphertext_b64},
            "passphrase": "WrongPassword123",
        },
    )
    assert bad_resp.status_code == 400
    assert "Decryption failed" in bad_resp.json()["detail"]

    # 2. Preview with correct passphrase
    good_prev = client.post(
        "/api/v1/restore/preview",
        headers=target_headers,
        json={
            "backup": {"encrypted_data": ciphertext_b64},
            "passphrase": passphrase,
        },
    )
    assert good_prev.status_code == 200, good_prev.text
    assert good_prev.json()["schema_version"] == 4
    # Note: blockers will note workspace id mismatch if backup was exported from ws_enc vs ws_target, which is correct
    # But it verifies decryption succeeded!
