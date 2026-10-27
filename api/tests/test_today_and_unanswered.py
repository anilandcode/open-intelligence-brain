"""The "couldn't answer" log and the Today summary."""

from __future__ import annotations

import pytest
from mcp import Client
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.database import engine
from brain.mcp_server import mcp
from brain.models import DEFAULT_WORKSPACE_ID, ConnectorWatch, UnansweredQuestion, Workspace
from brain.unanswered import question_key

MEMBER = {"X-Brain-Token": "member-token"}
FEE = "Enterprise customers pay an annual platform fee of 1200 dollars per seat."


def _member():
    with Session(engine) as db:
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "member-token", role="member")
        db.commit()


def _ask(client, headers, question):
    response = client.post("/api/v1/chat", headers=headers, json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def _approve(client, headers, content):
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": "Pricing", "kind": "note", "sensitivity": "internal", "content": content},
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    response = client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_question_key_ignores_case_and_filler():
    assert question_key("Who owns billing?") == question_key("who owns the billing")
    assert question_key("Who owns billing?") != question_key("Who owns pricing?")


def test_declined_questions_are_logged_and_folded(client, headers):
    assert _ask(client, headers, "What is the enterprise platform fee?")["grounded"] is False
    _ask(client, headers, "what is the enterprise platform fee")
    _ask(client, headers, "Who is our accountant?")
    rows = client.get("/api/v1/unanswered", headers=headers).json()
    assert [(r["question"], r["times_asked"]) for r in rows] == [
        ("what is the enterprise platform fee", 2),
        ("Who is our accountant?", 1),
    ]
    assert rows[0]["via"] == "console" and rows[0]["status"] == "open"


def test_answering_later_closes_the_row_and_failing_again_reopens_it(client, headers):
    _ask(client, headers, "What is the enterprise platform fee per seat?")
    _approve(client, headers, FEE)
    assert _ask(client, headers, "What is the enterprise platform fee per seat?")["grounded"]
    assert client.get("/api/v1/unanswered", headers=headers).json() == []
    answered = client.get("/api/v1/unanswered", headers=headers, params={"status": "answered"})
    assert [r["times_asked"] for r in answered.json()] == [1]


def test_dismiss_and_admin_only(client, headers):
    _member()
    _ask(client, headers, "Who is our accountant?")
    # Members can ask (and their questions are logged) but cannot read the log.
    _ask(client, MEMBER, "Where is the office?")
    assert client.get("/api/v1/unanswered", headers=MEMBER).status_code == 403
    rows = client.get("/api/v1/unanswered", headers=headers).json()
    assert len(rows) == 2
    accountant = next(r for r in rows if r["question"] == "Who is our accountant?")
    assert (
        client.post(f"/api/v1/unanswered/{accountant['id']}/dismiss", headers=MEMBER).status_code
        == 403
    )
    dismissed = client.post(f"/api/v1/unanswered/{accountant['id']}/dismiss", headers=headers)
    assert dismissed.json()["status"] == "dismissed"
    assert len(client.get("/api/v1/unanswered", headers=headers).json()) == 1
    # Asked again, still unanswered: back on the list.
    _ask(client, headers, "who is our accountant")
    reopened = client.get("/api/v1/unanswered", headers=headers).json()
    assert {r["question"] for r in reopened} == {"who is our accountant", "Where is the office?"}
    assert client.post("/api/v1/unanswered/unq_missing/dismiss", headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_agent_questions_are_logged_too(client):
    async with Client(mcp, raise_exceptions=True) as agent:
        result = await agent.call_tool("ask_brain", {"question": "Who is our accountant?"})
    assert result.structured_content["grounded"] is False
    with Session(engine) as db:
        row = db.scalar(select(UnansweredQuestion))
    assert row.via == "agent" and row.question == "Who is our accountant?"


def test_today_lists_what_needs_a_person(client, headers):
    assert client.get("/api/v1/today", headers=headers).json()["items"] == []
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": "Pricing", "kind": "note", "content": FEE},
    )
    _ask(client, headers, "Who is our accountant?")
    with Session(engine) as db:
        db.add(
            ConnectorWatch(
                id="watch_x",
                workspace_id=DEFAULT_WORKSPACE_ID,
                provider="google-drive",
                folder_id="f",
                label="Plans",
                last_result="Listing failed: Provider returned 401",
            )
        )
        db.commit()
    today = client.get("/api/v1/today", headers=headers).json()
    by_key = {item["key"]: item for item in today["items"]}
    assert by_key["reviews"]["label"] == "1 suggestion to review"
    assert by_key["reviews"]["view"] == "inbox"
    assert by_key["unanswered"]["label"] == "1 question the Brain couldn't answer"
    assert today["top_unanswered"][0]["question"] == "Who is our accountant?"
    assert by_key["sync"]["detail"] == "Plans"
    assert by_key["captured"]["count"] == 1

    _member()
    member_today = client.get("/api/v1/today", headers=MEMBER).json()
    keys = {item["key"] for item in member_today["items"]}
    # A member sees no log, and nothing from private sources.
    assert "unanswered" not in keys and "reviews" not in keys
    assert member_today["top_unanswered"] == []
