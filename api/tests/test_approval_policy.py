from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.database import SessionLocal
from brain.main import app
from brain.models import (
    AuditEvent,
    Knowledge,
    Proposal,
    Workspace,
)
from brain.schemas import SourceCreate, WorkspacePolicyUpdate
from brain.services import (
    create_source_with_proposals,
    get_or_create_workspace_policy,
    update_workspace_policy,
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
    slug = f"test-pol-{datetime.now(UTC).timestamp()}"
    ws = Workspace(id=f"ws_{slug[:16]}", slug=slug, name="Policy Test Workspace")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def test_default_policy_keeps_proposals_proposed(db: Session, test_workspace: Workspace):
    policy = get_or_create_workspace_policy(db, test_workspace.id)
    assert not policy.auto_approve_enabled

    source = create_source_with_proposals(
        db,
        SourceCreate(
            title="Clean Architecture",
            kind="note",
            sensitivity="internal",
            content="Microservices should always have bounded contexts to maintain loose coupling across team boundaries.",
        ),
        test_workspace.id,
    )

    proposals = db.scalars(select(Proposal).where(Proposal.source_id == source.id)).all()
    assert len(proposals) >= 1
    for p in proposals:
        assert p.status == "proposed"

    canonical = db.scalars(
        select(Knowledge).where(Knowledge.workspace_id == test_workspace.id)
    ).all()
    assert len(canonical) == 0


def test_auto_approval_enabled_approves_clean_proposal(db: Session, test_workspace: Workspace):
    update_workspace_policy(
        db,
        test_workspace.id,
        WorkspacePolicyUpdate(
            auto_approve_enabled=True,
            auto_approve_types="belief,lesson,fact,decision",
            auto_approve_max_sensitivity="internal",
            require_clean_critic=False,
            require_zero_conflicts=True,
        ),
    )

    source = create_source_with_proposals(
        db,
        SourceCreate(
            title="Clean Coding Standard",
            kind="note",
            sensitivity="internal",
            content="We believe test automation is essential for reliable distributed production deployments.",
        ),
        test_workspace.id,
    )

    proposals = db.scalars(select(Proposal).where(Proposal.source_id == source.id)).all()
    assert len(proposals) >= 1
    # At least one proposal should have been auto-approved
    approved = [p for p in proposals if p.status == "approved"]
    assert len(approved) >= 1

    canonical = db.scalars(
        select(Knowledge).where(Knowledge.workspace_id == test_workspace.id)
    ).all()
    assert len(canonical) >= 1

    events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.workspace_id == test_workspace.id,
            AuditEvent.action == "proposal.auto_approved",
        )
    ).all()
    assert len(events) >= 1


def test_conflict_gate_prevents_auto_approval(db: Session, test_workspace: Workspace):
    update_workspace_policy(
        db,
        test_workspace.id,
        WorkspacePolicyUpdate(
            auto_approve_enabled=True,
            auto_approve_types="belief,lesson,fact,decision",
            auto_approve_max_sensitivity="internal",
            require_clean_critic=False,
            require_zero_conflicts=True,
        ),
    )

    # 1. First capture approved belief
    _ = create_source_with_proposals(
        db,
        SourceCreate(
            title="Monorepo Standard",
            kind="note",
            sensitivity="internal",
            content="We should always use a monorepo for our core backend services and shared libraries.",
        ),
        test_workspace.id,
    )
    approved_count = db.scalar(select(Knowledge).where(Knowledge.workspace_id == test_workspace.id))
    assert approved_count is not None

    # 2. Capture direct contradiction
    s2 = create_source_with_proposals(
        db,
        SourceCreate(
            title="Polyrepo Discussion",
            kind="note",
            sensitivity="internal",
            content="We should not use a monorepo for our core backend services and shared libraries.",
        ),
        test_workspace.id,
    )

    proposals2 = db.scalars(select(Proposal).where(Proposal.source_id == s2.id)).all()
    assert len(proposals2) >= 1
    for p in proposals2:
        if p.conflict_with_id:
            # Conflicted proposal must NOT be auto-approved
            assert p.status == "proposed"


def test_sensitivity_gate_prevents_auto_approval(db: Session, test_workspace: Workspace):
    update_workspace_policy(
        db,
        test_workspace.id,
        WorkspacePolicyUpdate(
            auto_approve_enabled=True,
            auto_approve_types="belief,lesson,fact,decision",
            auto_approve_max_sensitivity="internal",  # Only public and internal
            require_clean_critic=False,
            require_zero_conflicts=True,
        ),
    )

    source = create_source_with_proposals(
        db,
        SourceCreate(
            title="Private Financials",
            kind="note",
            sensitivity="private",  # Exceeds internal ceiling
            content="The confidential annual operating budget for infrastructure is five million dollars.",
        ),
        test_workspace.id,
    )

    proposals = db.scalars(select(Proposal).where(Proposal.source_id == source.id)).all()
    assert len(proposals) >= 1
    for p in proposals:
        assert p.status == "proposed"


def test_type_gate_prevents_auto_approval(db: Session, test_workspace: Workspace):
    update_workspace_policy(
        db,
        test_workspace.id,
        WorkspacePolicyUpdate(
            auto_approve_enabled=True,
            auto_approve_types="decision",  # Only decisions
            auto_approve_max_sensitivity="internal",
            require_clean_critic=False,
            require_zero_conflicts=True,
        ),
    )

    source = create_source_with_proposals(
        db,
        SourceCreate(
            title="Team Belief",
            kind="note",
            sensitivity="internal",
            content="We believe code reviews should always be completed within twenty four business hours.",
        ),
        test_workspace.id,
    )

    proposals = db.scalars(select(Proposal).where(Proposal.source_id == source.id)).all()
    assert len(proposals) >= 1
    for p in proposals:
        if p.type != "decision":
            assert p.status == "proposed"


def test_workspace_policy_api_endpoints(client: TestClient, db: Session, test_workspace: Workspace):
    admin_token = f"tok_admin_{test_workspace.id[:8]}"
    grant_workspace(db, test_workspace, admin_token, role="admin")
    member_token = f"tok_member_{test_workspace.id[:8]}"
    grant_workspace(db, test_workspace, member_token, role="member")
    db.commit()

    # GET policy as admin
    resp = client.get(
        f"/api/v1/workspaces/{test_workspace.slug}/policy",
        headers={"X-Brain-Token": admin_token, "X-Brain-Workspace": test_workspace.slug},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["auto_approve_enabled"] is False
    assert data["workspace_id"] == test_workspace.id

    # PUT policy as member (should be 403 Forbidden)
    resp_mem = client.put(
        f"/api/v1/workspaces/{test_workspace.slug}/policy",
        headers={"X-Brain-Token": member_token, "X-Brain-Workspace": test_workspace.slug},
        json={"auto_approve_enabled": True},
    )
    assert resp_mem.status_code == 403

    # PUT policy as admin
    resp_put = client.put(
        f"/api/v1/workspaces/{test_workspace.slug}/policy",
        headers={"X-Brain-Token": admin_token, "X-Brain-Workspace": test_workspace.slug},
        json={
            "auto_approve_enabled": True,
            "auto_approve_types": "belief,lesson",
            "auto_approve_max_sensitivity": "internal",
            "require_clean_critic": True,
            "require_zero_conflicts": True,
        },
    )
    assert resp_put.status_code == 200, resp_put.text
    updated = resp_put.json()
    assert updated["auto_approve_enabled"] is True
    assert updated["auto_approve_types"] == "belief,lesson"
