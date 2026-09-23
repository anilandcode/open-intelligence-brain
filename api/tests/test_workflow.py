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
    assert response.json()["schema_version"] == 1
    assert response.json()["exported_from"] == "open-intelligence-brain"
