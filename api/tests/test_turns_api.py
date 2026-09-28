"""The harness over HTTP.

The API is where the harness stops being a set of rules and becomes something a
client can drive, so these tests check the three things a client must be able to
trust: the decision is explained, the budget is honest, and the approval gate
cannot be crossed by a turn.
"""

from sqlalchemy.orm import Session

from brain.access import ensure_default_workspace, grant_workspace
from brain.database import engine
from brain.models import Workspace

HEADERS = {"X-Brain-Token": "test-token"}
OTHER = {"X-Brain-Token": "token-b", "X-Brain-Workspace": "other"}
QUESTION = "@brain what did we decide about enterprise pricing?"


def _intake(client, **payload):
    body = {"channel": "#eng", "text": QUESTION, "addressed": True}
    body.update(payload)
    return client.post("/api/v1/events", headers=HEADERS, json=body)


def _seed_other_workspace() -> None:
    with Session(engine) as db:
        ensure_default_workspace(db)
        if db.get(Workspace, "ws_other") is None:
            db.add(Workspace(id="ws_other", slug="other", name="Other"))
            db.flush()
        grant_workspace(db, db.get(Workspace, "ws_other"), "token-b", role="owner")
        db.commit()


def test_intake_reports_the_decision_and_opens_a_turn(client):
    response = _intake(client)
    assert response.status_code == 201
    body = response.json()
    assert body["triage"]["action"] == "investigate"
    assert body["triage"]["version"] == "deterministic-triage-v1"
    assert body["triage"]["kind"] == "mention"
    assert body["turn"]["status"] == "pending"
    assert body["turn"]["step_budget"] == 6
    assert body["superseded"] == []
    # The private reading is not part of the answer a user reads.
    assert "private_raw" not in body["triage"]


def test_turn_detail_carries_the_transcript_and_the_plan(client):
    turn_id = _intake(client).json()["turn"]["id"]
    detail = client.get(f"/api/v1/turns/{turn_id}", headers=HEADERS).json()
    assert detail["plan"] == ["search_knowledge", "list_sources", "get_proposal"]
    assert detail["active_tools"] == detail["plan"]
    assert [step["kind"] for step in detail["steps"]] == ["triage", "policy"]

    listed = client.get("/api/v1/turns", headers=HEADERS).json()
    assert [row["id"] for row in listed] == [turn_id]


def test_an_answer_turn_spends_two_steps_and_then_stops(client):
    turn_id = _intake(
        client, model_output="ANSWER conf=0.95", evidence_strength=0.95
    ).json()["turn"]["id"]
    detail = client.get(f"/api/v1/turns/{turn_id}", headers=HEADERS).json()
    assert detail["action"] == "answer"
    assert detail["step_budget"] == 2

    first = client.post(
        f"/api/v1/turns/{turn_id}/step",
        headers=HEADERS,
        json={"tool": "search_knowledge", "summary": "looked up the pricing decision"},
    )
    assert first.status_code == 200
    assert first.json()["turn"]["steps_used"] == 1

    # The action decides the tools: a question that can be answered is never
    # handed the workspace browser.
    refused = client.post(
        f"/api/v1/turns/{turn_id}/step",
        headers=HEADERS,
        json={"tool": "list_sources", "summary": "browse everything instead"},
    )
    assert refused.status_code == 409

    last = client.post(
        f"/api/v1/turns/{turn_id}/step",
        headers=HEADERS,
        json={"tool": "search_knowledge", "summary": "cited the pricing decision"},
    )
    assert last.status_code == 200
    assert last.json()["exhausted"] is True
    assert last.json()["turn"]["stop_reason"] == "budget_exhausted"


def test_writing_knowledge_is_refused_over_http(client):
    turn_id = _intake(client).json()["turn"]["id"]
    refused = client.post(
        f"/api/v1/turns/{turn_id}/step",
        headers=HEADERS,
        json={"tool": "approve_proposal", "summary": "approve my own draft"},
    )
    assert refused.status_code == 409
    assert "human decision" in refused.json()["detail"]


def test_the_approval_gate_round_trip(client):
    turn_id = _intake(client).json()["turn"]["id"]
    suspended = client.post(
        f"/api/v1/turns/{turn_id}/suspend",
        headers=HEADERS,
        json={"proposal_id": "prop_9", "question": "Store the renewal terms as fact?"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "awaiting_approval"

    blocked = client.post(
        f"/api/v1/turns/{turn_id}/step",
        headers=HEADERS,
        json={"tool": "search_knowledge", "summary": "carry on without asking"},
    )
    assert blocked.status_code == 409

    resumed = client.post(
        f"/api/v1/turns/{turn_id}/resume",
        headers=HEADERS,
        json={"approved": True, "note": "verified against the March note"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["stop_reason"] == "approved"

    # Resolving the same gate twice is a conflict, not a second approval.
    assert (
        client.post(
            f"/api/v1/turns/{turn_id}/resume", headers=HEADERS, json={"approved": True}
        ).status_code
        == 409
    )


def test_stopping_a_turn_is_idempotent_over_http(client):
    turn_id = _intake(client).json()["turn"]["id"]
    for _ in range(2):
        stopped = client.post(
            f"/api/v1/turns/{turn_id}/stop", headers=HEADERS, json={"reason": "changed my mind"}
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "cancelled"
    detail = client.get(f"/api/v1/turns/{turn_id}", headers=HEADERS).json()
    assert [step["kind"] for step in detail["steps"]].count("stop") == 1


def test_steering_is_recorded_without_replacing_earlier_instructions(client):
    turn_id = _intake(client).json()["turn"]["id"]
    client.post(f"/api/v1/turns/{turn_id}/steer", headers=HEADERS, json={"note": "check March"})
    steered = client.post(
        f"/api/v1/turns/{turn_id}/steer", headers=HEADERS, json={"note": "and renewals"}
    )
    assert steered.json()["instructions"].splitlines() == ["check March", "and renewals"]


def test_a_channel_policy_changes_what_arrives(client):
    updated = client.put(
        "/api/v1/proactivity",
        headers=HEADERS,
        json={"channel": "#quiet", "mode": "off"},
    )
    assert updated.status_code == 200
    assert updated.json()["mode"] == "off"

    quiet = _intake(client, channel="#quiet")
    assert quiet.json()["triage"]["action"] == "pass"
    assert quiet.json()["triage"]["source"] == "policy"
    assert quiet.json()["turn"]["status"] == "completed"

    assert [row["channel"] for row in client.get("/api/v1/proactivity", headers=HEADERS).json()] == [
        "#quiet"
    ]
    # The mode is a closed set; a typo is refused rather than stored.
    assert (
        client.put(
            "/api/v1/proactivity", headers=HEADERS, json={"channel": "#quiet", "mode": "loud"}
        ).status_code
        == 422
    )


def test_events_and_turns_need_a_token(client):
    assert (
        client.post(
            "/api/v1/events", json={"channel": "#eng", "text": QUESTION, "addressed": True}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/turns").status_code == 401


def test_another_workspace_turns_are_reported_as_not_found(client):
    _seed_other_workspace()
    mine = _intake(client).json()["turn"]["id"]
    assert client.get(f"/api/v1/turns/{mine}", headers=OTHER).status_code == 404
    assert (
        client.post(
            f"/api/v1/turns/{mine}/stop", headers=OTHER, json={"reason": "not mine"}
        ).status_code
        == 404
    )
    assert client.get("/api/v1/turns", headers=OTHER).json() == []
    # The foreign attempt changed nothing in the owning workspace.
    assert client.get(f"/api/v1/turns/{mine}", headers=HEADERS).json()["status"] == "pending"

    theirs = client.post(
        "/api/v1/events",
        headers=OTHER,
        json={"channel": "#eng", "text": QUESTION, "addressed": True},
    ).json()["turn"]["id"]
    assert theirs != mine
    assert client.get(f"/api/v1/turns/{theirs}", headers=HEADERS).status_code == 404
