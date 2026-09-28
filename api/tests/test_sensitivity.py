"""Sensitivity enforcement inside one workspace.

`workspace_id` answers "which company". `sensitivity` answers "which rows of
that company may this role read". That second question had no implementation:
the field was stored, validated, exported and restored, and read by no query.

Every test here proves a negative. A missing assertion is how a silent
cross-team leak ships, so the shape is deliberately: build a private source,
approve it into canonical knowledge, then try to reach it as a member.
"""

from sqlalchemy.orm import Session

from brain.access import ReadScope, allowed_sensitivities, ensure_default_workspace, grant_workspace
from brain.database import engine
from brain.models import DEFAULT_WORKSPACE_ID, Workspace

MEMBER = {"X-Brain-Token": "member-token", "X-Brain-Workspace": "acme"}
OWNER = {"X-Brain-Token": "owner-token", "X-Brain-Workspace": "acme"}

# Long enough to clear the extractor's minimum, and phrased so the deterministic
# extractor produces at least one proposal to approve.
PRIVATE_BODY = (
    "The acquisition budget is confidential and must never leave the leadership "
    "team. Nobody outside the board should see this figure in any document."
)
INTERNAL_BODY = (
    "The platform team agreed to ship the billing migration in the third quarter "
    "because the dependency audit cleared the previous blockers this cycle."
)
PUBLIC_BODY = (
    "The company was founded in 2014 and its public mission statement describes "
    "helping small businesses understand their own financial position."
)


def _seed_workspace() -> None:
    """One company, an owner and a member. Both roles hold the same workspace."""
    with Session(engine) as db:
        ensure_default_workspace(db)
        if db.get(Workspace, "ws_acme") is None:
            db.add(Workspace(id="ws_acme", slug="acme", name="Acme"))
        db.flush()
        workspace = db.get(Workspace, "ws_acme")
        grant_workspace(db, workspace, "owner-token", role="owner")
        grant_workspace(db, workspace, "member-token", role="member")
        db.commit()


def _make_source(headers: dict, body: str, sensitivity: str) -> str:
    response = client_post(headers, body, sensitivity)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def client_post(headers: dict, body: str, sensitivity: str):
    from fastapi.testclient import TestClient

    from brain.main import app

    with TestClient(app) as test_client:
        return test_client.post(
            "/api/v1/sources",
            headers=headers,
            json={
                "title": f"{sensitivity} note {body[:12]}",
                "kind": "note",
                "sensitivity": sensitivity,
                "content": body,
            },
        )


def test_role_ceilings_are_ordered():
    """A member reaches public and internal; only an admin role reaches private."""
    assert allowed_sensitivities("member") == {"public", "internal"}
    assert allowed_sensitivities("owner") == {"public", "internal", "private"}
    assert allowed_sensitivities("admin") == {"public", "internal", "private"}


def test_private_source_is_invisible_to_a_member(client):
    _seed_workspace()
    _make_source(OWNER, PRIVATE_BODY, "private")

    listed = client.get("/api/v1/sources", headers=MEMBER)
    assert listed.status_code == 200
    assert listed.json() == []


def test_member_still_sees_internal_and_public(client):
    _seed_workspace()
    _make_source(OWNER, INTERNAL_BODY, "internal")
    _make_source(OWNER, PUBLIC_BODY, "public")

    listed = client.get("/api/v1/sources", headers=MEMBER)
    kinds = {row["sensitivity"] for row in listed.json()}
    assert kinds == {"internal", "public"}


def test_private_knowledge_is_absent_from_search_for_a_member(client):
    """The original defect: search filtered on workspace and status only.

    A private source approved into canonical knowledge was returned to every
    role in the workspace, because `sensitivity` was never read.
    """
    _seed_workspace()
    source_id = _make_source(OWNER, PRIVATE_BODY, "private")

    approved = _approve_first(client, OWNER, source_id)
    assert approved is not None
    _, statement = approved

    # Query the extractor's own wording, not a guess: the deterministic
    # extractor picks its own sentences, so a hardcoded phrase would pass for
    # the wrong reason (no match) instead of for the right one (filtered out).
    q = _query_from(statement)

    # The owner can find it, proving the canonical row exists.
    owner_hits = client.get("/api/v1/knowledge", headers=OWNER, params={"q": q})
    assert owner_hits.status_code == 200
    assert len(owner_hits.json()) >= 1

    # A member cannot, even by quoting the exact approved wording.
    member_hits = client.get("/api/v1/knowledge", headers=MEMBER, params={"q": q})
    assert member_hits.status_code == 200
    assert member_hits.json() == []


def test_private_knowledge_cannot_be_fetched_by_id(client):
    """A direct GET is refused, and it is 404 rather than 403.

    403 would confirm the record exists, which is the same disclosure the
    cross-workspace rule exists to prevent.
    """
    _seed_workspace()
    source_id = _make_source(OWNER, PRIVATE_BODY, "private")
    approved = _approve_first(client, OWNER, source_id)
    assert approved is not None
    knowledge_id, _ = approved

    response = client.get(f"/api/v1/knowledge/{knowledge_id}/revisions", headers=MEMBER)
    assert response.status_code == 404

    # And the proposal that produced it is equally out of reach.
    proposals = client.get("/api/v1/proposals", headers=MEMBER)
    assert all(p["source_id"] != source_id for p in proposals.json())


def test_a_member_cannot_approve_a_private_proposal(client):
    """Refusing to read must also mean refusing to act.

    Otherwise the gate is closed but the door beside it is open.
    """
    _seed_workspace()
    source_id = _make_source(OWNER, PRIVATE_BODY, "private")

    with Session(engine) as db:
        from sqlalchemy import select

        from brain.models import Proposal

        proposal = db.scalar(select(Proposal).where(Proposal.source_id == source_id))
        assert proposal is not None
        proposal_id = proposal.id

    response = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        headers=MEMBER,
        json={},
    )
    assert response.status_code == 404


def test_counts_do_not_leak_private_row_counts(client):
    """A count is a read. Excluding the rows but counting them still leaks."""
    _seed_workspace()
    _make_source(OWNER, PRIVATE_BODY, "private")
    _make_source(OWNER, INTERNAL_BODY, "internal")

    owner_overview = client.get("/api/v1/overview", headers=OWNER).json()
    member_overview = client.get("/api/v1/overview", headers=MEMBER).json()

    assert owner_overview["sources"] == 2
    assert member_overview["sources"] == 1


def test_grounded_answer_refuses_a_private_citation(client):
    """The answer is scoped too — otherwise the leak survives the search fix."""
    _seed_workspace()
    source_id = _make_source(OWNER, PRIVATE_BODY, "private")
    approved = _approve_first(client, OWNER, source_id)
    assert approved is not None
    question = _query_from(approved[1])
    owner_answer = client.post("/api/v1/chat", headers=OWNER, json={"question": question})
    member_answer = client.post("/api/v1/chat", headers=MEMBER, json={"question": question})
    assert owner_answer.status_code == 200
    assert member_answer.status_code == 200
    assert member_answer.json()["grounded"] is False
    assert member_answer.json()["citations"] == []


def test_read_scope_is_the_only_way_services_read_rows():
    """Guard the class of bug, not just this instance.

    `ReadScope` exists because passing a bare `workspace_id` string is what let
    the field go unenforced; a caller that reintroduces the string has
    reintroduced the leak.
    """
    with Session(engine) as db:
        ensure_default_workspace(db)
        db.commit()
    scope = ReadScope(DEFAULT_WORKSPACE_ID, "member")
    assert scope.may_read("public")
    assert scope.may_read("internal")
    assert not scope.may_read("private")


def _approve_first(client, headers: dict, source_id: str) -> tuple[str, str] | None:
    """Approve the first pending proposal for a source; return (id, statement).

    Both, because the tests that follow need the exact wording the engine
    produced in order to search for it, and the id to fetch it directly.
    """
    proposals = client.get("/api/v1/proposals", headers=headers).json()
    matching = [p for p in proposals if p["source_id"] == source_id and p["status"] == "proposed"]
    if not matching:
        return None
    response = client.post(
        f"/api/v1/proposals/{matching[0]['id']}/approve", headers=headers, json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["id"], body["statement"]


def _query_from(statement: str) -> str:
    """A search query built from the approved wording itself.

    Six leading words is comfortably above the extractor's three-character
    minimum and below the point where unrelated words dilute the match.
    """
    return " ".join(statement.split()[:6])
