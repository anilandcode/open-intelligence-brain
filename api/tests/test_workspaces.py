"""Workspace isolation.

Every test here proves a negative: that one company's Brain cannot see, read,
approve or restore another company's data. A missing assertion here is how a
silent cross-tenant leak would ship.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brain.access import ensure_default_workspace, grant_workspace
from brain.database import engine
from brain.models import DEFAULT_WORKSPACE_ID, Knowledge, Proposal, Source, Workspace

FIRM_A = {"X-Brain-Token": "token-a", "X-Brain-Workspace": "acme"}
FIRM_B = {"X-Brain-Token": "token-b", "X-Brain-Workspace": "globex"}


def _seed_workspaces() -> None:
    """Create two companies and grant each its own token.

    Idempotent: application startup already creates the default workspace, so
    this only adds the two named companies on top of whatever exists.
    """
    with Session(engine) as db:
        ensure_default_workspace(db)
        for workspace_id, slug, name in (
            ("ws_acme", "acme", "Acme"),
            ("ws_globex", "globex", "Globex"),
        ):
            if db.get(Workspace, workspace_id) is None:
                db.add(Workspace(id=workspace_id, slug=slug, name=name))
        db.flush()
        default = db.get(Workspace, DEFAULT_WORKSPACE_ID)
        # token-a deliberately holds two workspaces, so the "must name one" rule
        # is exercised; every other test always sends the header.
        grant_workspace(db, default, "token-a", role="owner")
        grant_workspace(db, db.get(Workspace, "ws_acme"), "token-a", role="owner")
        grant_workspace(db, db.get(Workspace, "ws_globex"), "token-b", role="owner")
        db.commit()


def test_invalid_token_is_rejected(client):
    assert client.get("/api/v1/sources", headers={"X-Brain-Token": "nope"}).status_code == 401


def test_token_cannot_name_a_workspace_it_does_not_hold(client):
    headers = {"X-Brain-Token": "token-a", "X-Brain-Workspace": "globex"}
    assert client.get("/api/v1/sources", headers=headers).status_code == 401


def test_sources_are_invisible_across_workspaces(client):
    _seed_workspaces()
    acme_source = client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme pricing decision",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that Acme will never discount below thirty percent of list price.",
        },
    )
    assert acme_source.status_code == 201
    assert len(client.get("/api/v1/sources", headers=FIRM_A).json()) == 1

    globex_sources = client.get("/api/v1/sources", headers=FIRM_B).json()
    assert globex_sources == []
    assert acme_source.json()["id"] not in [row["id"] for row in globex_sources]


def test_other_workspace_records_are_reported_as_not_found(client):
    """A 404 rather than a 403: confirming existence would leak it."""
    _seed_workspaces()
    acme_source = client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme roadmap note",
            "kind": "note",
            "sensitivity": "internal",
            "content": "We learned that Acme ships the billing rewrite before the mobile client work begins.",
        },
    ).json()

    leaked = client.get(f"/api/v1/sources/{acme_source['id']}/deletion-preview", headers=FIRM_B)
    assert leaked.status_code == 404

    versions = client.get(f"/api/v1/sources/{acme_source['id']}/versions", headers=FIRM_B)
    assert versions.status_code == 404

    assert (
        client.post(
            f"/api/v1/sources/{acme_source['id']}/versions",
            headers=FIRM_B,
            json={
                "content": "We learned that Globex should never read this source.",
                "change_note": "probe",
            },
        ).status_code
        == 404
    )


def test_proposals_cannot_be_approved_from_another_workspace(client):
    _seed_workspaces()
    client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme hiring principle",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that Acme hires for slope rather than for years of experience in the same stack.",
        },
    )
    # The proposal exists in Acme's queue. Globex must not even see it.
    acme_proposals = client.get("/api/v1/proposals", headers=FIRM_A).json()
    assert len(acme_proposals) == 1
    assert client.get("/api/v1/proposals", headers=FIRM_B).json() == []

    stolen = acme_proposals[0]["id"]
    assert (
        client.post(f"/api/v1/proposals/{stolen}/approve", headers=FIRM_B, json={}).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/proposals/{stolen}/reject",
            headers=FIRM_B,
            json={"reason": "not ours"},
        ).status_code
        == 404
    )
    # Still pending in its own workspace: the cross-workspace attempt changed nothing.
    assert client.get("/api/v1/proposals", headers=FIRM_A).json()[0]["status"] == "proposed"


def test_answers_and_search_never_cite_another_workspace(client):
    _seed_workspaces()
    client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme support policy",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that Acme guarantees a four hour response on every enterprise support request.",
        },
    )
    proposal = client.get("/api/v1/proposals", headers=FIRM_A).json()[0]
    client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=FIRM_A, json={})

    grounded = client.post(
        "/api/v1/chat",
        headers=FIRM_A,
        json={"question": "What is the Acme support response guarantee?"},
    )
    assert grounded.json()["grounded"] is True
    assert len(grounded.json()["citations"]) == 1

    # The identical question in the other workspace must abstain, not borrow.
    foreign = client.post(
        "/api/v1/chat",
        headers=FIRM_B,
        json={"question": "What is the Acme support response guarantee?"},
    )
    assert foreign.json()["grounded"] is False
    assert foreign.json()["citations"] == []
    assert client.get("/api/v1/knowledge", headers=FIRM_B).json() == []


def test_overview_counts_are_per_workspace(client):
    _seed_workspaces()
    client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme expansion note",
            "kind": "note",
            "sensitivity": "private",
            "content": "We learned that Acme should open the Berlin office only after the pipeline is proven locally.",
        },
    )
    client.post(
        "/api/v1/sources",
        headers=FIRM_B,
        json={
            "title": "Globex expansion note",
            "kind": "note",
            "sensitivity": "private",
            "content": "We learned that Globex should open the Lagos office only after the pipeline is proven locally.",
        },
    )

    acme = client.get("/api/v1/overview", headers=FIRM_A).json()
    globex = client.get("/api/v1/overview", headers=FIRM_B).json()
    assert acme["sources"] == 1
    assert globex["sources"] == 1
    # Each workspace only sees its own audit trail.
    for event in globex["recent_activity"]:
        assert "Acme" not in event["detail"]


def test_integrity_scan_is_scoped_to_one_workspace(client):
    _seed_workspaces()
    for headers, company in ((FIRM_A, "Acme"), (FIRM_B, "Globex")):
        client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": f"{company} policy",
                "kind": "decision",
                "sensitivity": "internal",
                "content": f"We decided that {company} must retain approval evidence for every published claim.",
            },
        )
        proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
        client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})

    # Both companies hold a near-identical statement; conflict detection must not
    # treat the other company's knowledge as a contradiction.
    for headers in (FIRM_A, FIRM_B):
        integrity = client.get("/api/v1/integrity", headers=headers).json()
        assert integrity["conflict_count"] == 0
        assert integrity["stale_count"] == 0


def test_export_is_per_workspace_and_restore_refuses_another_company(client):
    _seed_workspaces()
    client.post(
        "/api/v1/sources",
        headers=FIRM_A,
        json={
            "title": "Acme confidential plan",
            "kind": "note",
            "sensitivity": "private",
            "content": "We decided that Acme will not announce the Atlas acquisition before the regulatory filing clears.",
        },
    )
    backup = client.get("/api/v1/export", headers=FIRM_A).json()
    assert backup["workspace"]["id"] == "ws_acme"
    assert all(row["workspace_id"] == "ws_acme" for row in backup["sources"])

    # Globex's own empty export cannot carry Acme's rows.
    globex_export = client.get("/api/v1/export", headers=FIRM_B).json()
    assert globex_export["sources"] == []
    assert globex_export["workspace"]["id"] == "ws_globex"

    # Restoring Acme's backup into Globex is refused, not silently re-homed.
    preview = client.post("/api/v1/restore/preview", headers=FIRM_B, json={"backup": backup}).json()
    assert preview["valid"] is False
    assert any("different workspace" in blocker for blocker in preview["blockers"])

    refused = client.post(
        "/api/v1/restore",
        headers=FIRM_B,
        json={"backup": backup, "confirm_empty_workspace": True},
    )
    assert refused.status_code == 409
    assert client.get("/api/v1/sources", headers=FIRM_B).json() == []


def test_a_token_reaching_two_workspaces_must_name_one(client):
    _seed_workspaces()
    both = {"X-Brain-Token": "token-a"}
    # token-a holds both the default and Acme, so an unnamed request is ambiguous.
    assert client.get("/api/v1/sources", headers=both).status_code == 401
    named = client.get("/api/v1/sources", headers={**both, "X-Brain-Workspace": "acme"})
    assert named.status_code == 200


def test_records_default_to_the_single_workspace_without_configuration(client):
    """The no-setup path: one grant means the header is optional."""
    with Session(engine) as db:
        ensure_default_workspace(db)
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "solo-token", role="owner")
        db.commit()

    solo = {"X-Brain-Token": "solo-token"}
    created = client.post(
        "/api/v1/sources",
        headers=solo,
        json={
            "title": "Solo note",
            "kind": "note",
            "sensitivity": "private",
            "content": "We learned that a single-company Brain needs no workspace header to record a source.",
        },
    )
    assert created.status_code == 201
    with Session(engine) as db:
        stored = db.get(Source, created.json()["id"])
        assert stored is not None and stored.workspace_id == DEFAULT_WORKSPACE_ID


def test_workspace_rows_cannot_disagree_with_their_own_children(client):
    """Every proposal and approved item lands in the same workspace as its source."""
    _seed_workspaces()
    source = client.post(
        "/api/v1/sources",
        headers=FIRM_B,
        json={
            "title": "Globex governance",
            "kind": "decision",
            "sensitivity": "internal",
            "content": "We decided that Globex records every brand voice change as an approved revision.",
        },
    ).json()
    proposal = client.get("/api/v1/proposals", headers=FIRM_B).json()[0]
    knowledge = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=FIRM_B, json={}
    ).json()

    with Session(engine) as db:
        stored_source = db.get(Source, source["id"])
        stored_proposal = db.get(Proposal, proposal["id"])
        stored_knowledge = db.get(Knowledge, knowledge["id"])
        assert stored_source is not None and stored_source.workspace_id == "ws_globex"
        assert stored_proposal is not None and stored_proposal.workspace_id == "ws_globex"
        assert stored_knowledge is not None and stored_knowledge.workspace_id == "ws_globex"
        assert (
            db.scalar(select(func.count(Knowledge.id)).where(Knowledge.workspace_id == "ws_acme"))
            == 0
        )
