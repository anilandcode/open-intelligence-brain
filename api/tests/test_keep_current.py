"""Keeping knowledge current: dates, review, expiry, the gardening report and digest."""

from datetime import UTC, datetime, timedelta

import pytest
from mcp import Client
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.access import ensure_default_workspace, grant_workspace
from brain.database import Base, engine
from brain.extraction import looks_time_sensitive
from brain.gardening import main as gardening_main
from brain.mcp_server import mcp
from brain.messaging import HermesConfig, HermesMessenger
from brain.models import DEFAULT_WORKSPACE_ID, AuditEvent, Knowledge, Workspace
from brain.usage import track_usage

MEMBER = {"X-Brain-Token": "member-token"}
PRICE = "Enterprise customers pay an annual platform fee of 1200 dollars per seat."
LESSON = "Customers trust onboarding more when one named person stays with them throughout."


def _member():
    with Session(engine) as db:
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "member-token", role="member")
        db.commit()


def _capture(client, headers, content, title="Note", sensitivity="internal"):
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": sensitivity, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve_text(client, headers, content, title="Note", sensitivity="internal", **body):
    _capture(client, headers, content, title, sensitivity)
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    response = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


def _days_from_now(value: str) -> float:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment - datetime.now(UTC)).total_seconds() / 86_400


def _backdate(knowledge_id: str, **fields):
    with Session(engine) as db:
        item = db.get(Knowledge, knowledge_id)
        for key, value in fields.items():
            setattr(item, key, value)
        db.commit()


# --- dates at approval ----------------------------------------------------------


def test_time_sensitive_statements_are_recognised():
    assert looks_time_sensitive(PRICE)
    assert looks_time_sensitive("Dana currently owns the billing migration.")
    assert looks_time_sensitive("Churn fell to 4% this quarter.")
    assert not looks_time_sensitive(LESSON)


def test_time_sensitive_claims_get_a_review_date_unless_the_reviewer_chooses(client, headers):
    _capture(client, headers, PRICE, title="Pricing")
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    assert proposal["time_sensitive"] is True
    price = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve",
        headers=headers,
        json={"as_of": "2026-09-01T00:00:00Z"},
    ).json()
    assert 89 < _days_from_now(price["review_by"]) < 91
    assert price["as_of"].startswith("2026-09-01")
    assert price["due_for_review"] is False

    lesson = _approve_text(client, headers, LESSON, title="Lessons")
    assert lesson["review_by"] is None

    chosen = _approve_text(
        client,
        headers,
        "Startups pay a monthly platform fee of 49 dollars per seat.",
        title="Startup pricing",
        review_by=None,
        expires_at="2027-01-01T00:00:00Z",
    )
    assert chosen["review_by"] is None
    assert chosen["expires_at"].startswith("2027-01-01")


def test_dates_can_be_edited_and_an_item_marked_reviewed(client, headers):
    item = _approve_text(client, headers, LESSON)
    response = client.patch(
        f"/api/v1/knowledge/{item['id']}/timeframe",
        headers=headers,
        json={"review_by": "2020-01-01T00:00:00Z", "as_of": "2019-06-01T00:00:00Z"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["due_for_review"] is True
    cleared = client.patch(
        f"/api/v1/knowledge/{item['id']}/timeframe", headers=headers, json={"as_of": None}
    ).json()
    assert cleared["as_of"] is None
    assert cleared["review_by"].startswith("2020-01-01")

    reviewed = client.post(
        f"/api/v1/knowledge/{item['id']}/reviewed", headers=headers, json={"next_review_days": 30}
    ).json()
    assert reviewed["due_for_review"] is False
    assert 29 < _days_from_now(reviewed["review_by"]) < 31
    assert reviewed["last_reviewed_at"]
    assert reviewed["version"] == 1  # metadata only: no new revision
    with Session(engine) as db:
        actions = set(db.scalars(select(AuditEvent.action)))
    assert {"knowledge.timeframe", "knowledge.reviewed"} <= actions


def test_members_cannot_touch_private_dates(client, headers):
    _member()
    item = _approve_text(client, headers, PRICE, sensitivity="private")
    path = f"/api/v1/knowledge/{item['id']}/timeframe"
    assert client.patch(path, headers=MEMBER, json={"review_by": None}).status_code == 404
    reviewed = f"/api/v1/knowledge/{item['id']}/reviewed"
    assert client.post(reviewed, headers=MEMBER, json={}).status_code == 404


def test_an_update_restarts_the_clock(client, headers):
    original = _approve_text(client, headers, PRICE, as_of="2025-01-01T00:00:00Z")
    _capture(
        client,
        headers,
        "Enterprise customers now pay an annual platform fee of 1500 dollars per seat.",
        title="Pricing 2026",
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    assert proposal["relation"] == "update"
    updated = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={}
    ).json()
    assert updated["id"] == original["id"]
    assert updated["as_of"] is None
    assert updated["last_reviewed_at"]
    assert 89 < _days_from_now(updated["review_by"]) < 91


# --- answers ---------------------------------------------------------------------------


def test_expired_items_are_not_cited_as_answers(client, headers):
    item = _approve_text(client, headers, PRICE, expires_at="2020-01-01T00:00:00Z")
    assert item["expired"] is True
    answer = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "What annual platform fee do enterprise customers pay per seat?"},
    ).json()
    assert answer["grounded"] is False
    assert answer["near_matches"][0]["knowledge_id"] == item["id"]
    assert answer["near_matches"][0]["expired"] is True


def test_due_items_are_cited_with_a_flag(client, headers):
    item = _approve_text(client, headers, PRICE, review_by="2020-01-01T00:00:00Z")
    answer = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "What annual platform fee do enterprise customers pay per seat?"},
    ).json()
    assert answer["grounded"] is True
    assert answer["citations"][0]["knowledge_id"] == item["id"]
    assert answer["citations"][0]["due_for_review"] is True


@pytest.mark.asyncio
async def test_agents_see_dates_and_warnings(client, headers):
    item = _approve_text(
        client,
        headers,
        PRICE,
        as_of="2026-03-01T00:00:00Z",
        review_by="2020-01-01T00:00:00Z",
    )
    async with Client(mcp, raise_exceptions=True) as agent:
        pack = (
            await agent.call_tool("context_pack", {"task": "enterprise annual platform fee"})
        ).structured_content
    assert pack["items"][0]["knowledge_id"] == item["id"]
    assert pack["items"][0]["due_for_review"] is True
    assert "as of 2026-03-01" in pack["brief"]
    assert "due for review; may be out of date" in pack["brief"]


# --- gardening -------------------------------------------------------------------------


def test_gardening_lists_what_needs_a_person(client, headers):
    due = _approve_text(client, headers, PRICE, title="Pricing", review_by="2020-01-01T00:00:00Z")
    expired = _approve_text(
        client,
        headers,
        "The beta waitlist closes once two hundred teams have signed up.",
        title="Beta",
        expires_at="2020-01-01T00:00:00Z",
    )
    source = _capture(
        client,
        headers,
        "Support answers every ticket within one business day.",
        title="Support",
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    changed = client.post(
        f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={}
    ).json()
    client.post(
        f"/api/v1/sources/{source['id']}/versions",
        headers=headers,
        json={
            "content": "Support answers every ticket within four business hours.",
            "change_note": "Faster SLA",
        },
    )
    client.post(
        "/api/v1/proposals/review",
        headers=headers,
        json={
            "proposal_ids": [
                p["id"] for p in client.get("/api/v1/proposals", headers=headers).json()
            ],
            "action": "reject",
        },
    )
    positive = _approve_text(
        client,
        headers,
        "Coding agents should retain approved evidence in every context package they build.",
        title="Agents",
    )
    negative = _approve_text(
        client,
        headers,
        "Coding agents should not retain approved evidence in context packages they build.",
        title="Agents later",
        as_new=True,
    )
    old = _approve_text(client, headers, LESSON, title="Lessons")
    used = _approve_text(
        client, headers, "Weekly demos keep the whole team aligned on priorities.", title="Demos"
    )
    long_ago = datetime.now(UTC) - timedelta(days=400)
    _backdate(old["id"], approved_at=long_ago)
    _backdate(used["id"], approved_at=long_ago)
    with Session(engine) as db:
        track_usage(db, DEFAULT_WORKSPACE_ID, used["id"], "answer", "demos")
        db.commit()

    report = client.get("/api/v1/gardening", headers=headers).json()
    ids = {key: [entry["knowledge_id"] for entry in report[key]] for key in report["counts"]}
    assert ids["due_for_review"] == [due["id"]]
    assert ids["expired"] == [expired["id"]]
    assert ids["source_changed"] == [changed["id"]]
    assert {positive["id"], negative["id"]} == {
        report["conflicts"][0]["knowledge_id"],
        report["conflicts"][0]["related_id"],
    }
    assert old["id"] in ids["unused"]
    assert used["id"] not in ids["unused"]
    assert report["total"] == sum(report["counts"].values())


def test_gardening_and_the_daily_digest_respect_sensitivity(client, headers):
    _member()
    _approve_text(client, headers, PRICE, sensitivity="private", review_by="2020-01-01T00:00:00Z")
    _capture(
        client,
        headers,
        "Private plan: acquire the design studio next spring.",
        sensitivity="private",
    )
    _capture(client, headers, "Team plan: ship the onboarding checklist before launch.")
    owner_report = client.get("/api/v1/gardening", headers=headers).json()
    assert owner_report["counts"]["due_for_review"] == 1
    member_report = client.get("/api/v1/gardening", headers=MEMBER).json()
    assert member_report["total"] == 0

    member_digest = client.get("/api/v1/routines/digest", headers=MEMBER).json()
    assert member_digest["pending_proposals"] == 1
    assert all("acquire" not in p["statement"] for p in member_digest["top_proposals"])
    owner_digest = client.get("/api/v1/routines/digest", headers=headers).json()
    assert owner_digest["pending_proposals"] == 2


def test_the_weekly_digest_is_sent_once_through_hermes(client, headers, monkeypatch):
    _approve_text(client, headers, PRICE, review_by="2020-01-01T00:00:00Z")
    unconfigured = client.post("/api/v1/routines/gardening/send", headers=headers).json()
    assert unconfigured["sent"] is False
    assert "not configured" in unconfigured["reason"]
    assert "Due for review (1)" in unconfigured["text"]
    assert "/#/console/brain?record=" in unconfigured["text"]

    sent: list[str] = []
    monkeypatch.setattr(
        HermesConfig, "from_env", classmethod(lambda cls: cls(api_url="http://hermes.test"))
    )
    monkeypatch.setattr(
        HermesMessenger, "send", lambda self, message, channel=None: sent.append(message) or True
    )
    first = client.post("/api/v1/routines/gardening/send", headers=headers).json()
    assert first["sent"] is True
    again = client.post("/api/v1/routines/gardening/send", headers=headers).json()
    assert again["sent"] is False
    assert again["reason"].startswith("Already sent")
    forced = client.post("/api/v1/routines/gardening/send?force=true", headers=headers).json()
    assert forced["sent"] is True
    assert len(sent) == 2

    _member()
    assert client.post("/api/v1/routines/gardening/send", headers=MEMBER).status_code == 403


def test_gardening_runs_from_the_shell(client, headers, capsys):
    _approve_text(client, headers, PRICE, review_by="2020-01-01T00:00:00Z")
    assert gardening_main(["default"]) == 0
    assert "Due for review (1)" in capsys.readouterr().out
    assert gardening_main(["nope"]) == 2


# --- backups ---------------------------------------------------------------------------


def test_backups_keep_dates(client, headers):
    item = _approve_text(
        client,
        headers,
        PRICE,
        as_of="2026-03-01T00:00:00Z",
        review_by="2027-03-01T00:00:00Z",
    )
    backup = client.get("/api/v1/export", headers=headers).json()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        workspace = ensure_default_workspace(db)
        grant_workspace(db, workspace, "test-token", role="owner")
        db.commit()
    restored = client.post(
        "/api/v1/restore",
        headers=headers,
        json={"backup": backup, "confirm_empty_workspace": True},
    )
    assert restored.status_code == 200, restored.text
    again = client.get("/api/v1/knowledge", headers=headers).json()[0]
    assert again["id"] == item["id"]
    assert again["as_of"].startswith("2026-03-01")
    assert again["review_by"].startswith("2027-03-01")
