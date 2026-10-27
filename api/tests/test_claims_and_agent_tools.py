"""Model-written claims, update/contradiction proposals, and the agent tools.

A chat model is never called here: `set_chat_model` installs a scripted stand-in,
so the tests pin what intake does with a model's answer (keep only claims whose
quote is verbatim in the source, fall back when the model fails) rather than
what any particular model says.
"""

import pytest
from mcp import Client
from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.claims import locate_quote, windows
from brain.database import SessionLocal, engine
from brain.llm import parse_json_reply, reset_chat_model, set_chat_model
from brain.mcp_server import mcp
from brain.models import DEFAULT_WORKSPACE_ID, AuditEvent, KnowledgeRevision, Workspace

NOTE = (
    "Offsite notes, 3 March.\n\n"
    "We agreed that enterprise customers move to annual billing from April because "
    "monthly billing drove churn. Dana owns the migration.\n\n"
    "Lunch was good."
)


class ScriptedModel:
    model = "scripted-test-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        return self.replies.pop(0) if self.replies else {"claims": []}


@pytest.fixture(autouse=True)
def _no_model():
    reset_chat_model()
    set_chat_model(None)
    yield
    reset_chat_model()


def _capture(client, headers, content, title="Note", sensitivity="internal"):
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": sensitivity, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _pending(client, headers):
    return client.get("/api/v1/proposals", headers=headers).json()


def _approve(client, headers, proposal_id, **body):
    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


# --- helpers ------------------------------------------------------------------


def test_windows_cover_the_content_with_exact_offsets():
    content = ("Paragraph one is here.\n\n" * 40).strip()
    parts = windows(content, 200)
    assert len(parts) > 1
    for start, text in parts:
        assert content[start : start + len(text)] == text


def test_quotes_must_be_verbatim():
    window = "We agreed that enterprise customers move to annual billing."
    assert locate_quote(window, "enterprise customers move") == (15, 40)
    assert locate_quote(window, "ENTERPRISE customers move") == (15, 40)
    assert locate_quote(window, "enterprise clients move") is None
    assert locate_quote(window, "short") is None


def test_parse_json_reply_tolerates_fences_and_prose():
    assert parse_json_reply('```json\n{"claims": []}\n```') == {"claims": []}
    assert parse_json_reply('Here you go: {"claims": [1]} thanks') == {"claims": [1]}
    assert parse_json_reply("no json here") is None


# --- model intake -------------------------------------------------------------


def test_model_claims_become_proposals_pinned_to_exact_quotes(client, headers):
    model = ScriptedModel(
        [
            {
                "claims": [
                    {
                        "statement": "Enterprise customers move to annual billing from April.",
                        "type": "decision",
                        "quote": "enterprise customers move to annual billing from April",
                        "confidence": 0.9,
                    },
                    {
                        "statement": "Dana owns the annual billing migration.",
                        "type": "fact",
                        "quote": "Dana owns the migration.",
                        "confidence": 0.8,
                    },
                    {
                        "statement": "The offsite was in Lisbon.",
                        "type": "fact",
                        "quote": "The offsite was held in Lisbon",  # not in the source
                        "confidence": 0.9,
                    },
                ]
            }
        ]
    )
    set_chat_model(model)
    source = _capture(client, headers, NOTE)
    assert model.calls == 1
    assert source["proposal_count"] == 2
    pending = _pending(client, headers)
    statements = {p["statement"] for p in pending}
    assert "The offsite was in Lisbon." not in statements
    billing = next(p for p in pending if "annual billing from April" in p["statement"])
    assert billing["type"] == "decision"
    assert billing["confidence"] == 0.9
    assert billing["source_excerpt"] == "enterprise customers move to annual billing from April"
    assert billing["rationale"].startswith("Claim extracted by scripted-test-model")
    with SessionLocal() as db:
        detail = db.scalar(select(AuditEvent.detail).where(AuditEvent.action == "source.versioned"))
    assert "2 proposed by model" in detail

    # The quote is a real span of the immutable version, so approval keeps it.
    knowledge = _approve(client, headers, billing["id"])
    revisions = client.get(f"/api/v1/knowledge/{knowledge['id']}/revisions", headers=headers).json()
    assert revisions[0]["source_excerpt"] == billing["source_excerpt"]


def test_model_failure_falls_back_to_deterministic_extraction(client, headers):
    set_chat_model(ScriptedModel([None]))
    source = _capture(client, headers, NOTE)
    assert source["proposal_count"] >= 1
    assert all(
        not p["rationale"].startswith("Claim extracted by") for p in _pending(client, headers)
    )


def test_model_finding_nothing_proposes_nothing(client, headers):
    set_chat_model(ScriptedModel([{"claims": []}]))
    assert _capture(client, headers, NOTE)["proposal_count"] == 0


# --- update and contradiction --------------------------------------------------


def _approved_fee(client, headers):
    _capture(
        client,
        headers,
        "Enterprise customers pay an annual platform fee of 1200 dollars per seat.",
        title="Pricing 2025",
    )
    return _approve(client, headers, _pending(client, headers)[0]["id"])


def test_changed_fact_is_proposed_as_an_update_and_revises_the_original(client, headers):
    original = _approved_fee(client, headers)
    newer = _capture(
        client,
        headers,
        "Enterprise customers now pay an annual platform fee of 1500 dollars per seat.",
        title="Pricing 2026",
    )
    proposal = _pending(client, headers)[0]
    assert proposal["relation"] == "update"
    assert proposal["target_knowledge_id"] == original["id"]
    assert proposal["target_statement"] == original["statement"]

    updated = _approve(client, headers, proposal["id"])
    assert updated["id"] == original["id"]
    assert updated["version"] == 2
    assert "1500" in updated["statement"]
    assert updated["source_id"] == newer["id"]
    assert len(client.get("/api/v1/knowledge", headers=headers).json()) == 1
    revisions = client.get(f"/api/v1/knowledge/{original['id']}/revisions", headers=headers).json()
    assert [r["revision"] for r in revisions] == [2, 1]
    # The new revision carries the new evidence (C5), the old one keeps its own.
    assert revisions[0]["source_id"] == newer["id"]
    assert "1500" in revisions[0]["source_excerpt"]
    assert revisions[1]["source_id"] == original["source_id"]
    assert client.get("/api/v1/integrity", headers=headers).json()["stale_count"] == 0


def test_update_can_be_approved_as_a_separate_item(client, headers):
    original = _approved_fee(client, headers)
    _capture(
        client,
        headers,
        "Enterprise customers now pay an annual platform fee of 1500 dollars per seat.",
        title="Pricing 2026",
    )
    added = _approve(client, headers, _pending(client, headers)[0]["id"], as_new=True)
    assert added["id"] != original["id"]
    assert len(client.get("/api/v1/knowledge", headers=headers).json()) == 2


def test_opposite_polarity_is_labelled_a_contradiction(client, headers):
    _capture(
        client,
        headers,
        "Coding agents should retain approved evidence in every context package they build.",
    )
    original = _approve(client, headers, _pending(client, headers)[0]["id"])
    _capture(
        client,
        headers,
        "Coding agents should not retain approved evidence in context packages they build.",
        title="Later note",
    )
    proposal = _pending(client, headers)[0]
    assert proposal["relation"] == "contradiction"
    assert proposal["target_knowledge_id"] == original["id"]


def test_update_target_is_hidden_from_a_reviewer_who_cannot_read_it(client, headers):
    _capture(
        client,
        headers,
        "Enterprise customers pay an annual platform fee of 1200 dollars per seat.",
        title="Private pricing",
        sensitivity="private",
    )
    original = _approve(client, headers, _pending(client, headers)[0]["id"])
    _capture(
        client,
        headers,
        "Enterprise customers now pay an annual platform fee of 1500 dollars per seat.",
        title="Team pricing",
        sensitivity="internal",
    )
    with Session(engine) as db:
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "member-token", role="member")
        db.commit()
    member = {"X-Brain-Token": "member-token"}
    seen = _pending(client, member)
    assert len(seen) == 1
    assert seen[0]["relation"] == "new"
    assert seen[0]["target_knowledge_id"] is None
    assert seen[0]["target_statement"] == ""
    response = client.post(f"/api/v1/proposals/{seen[0]['id']}/approve", headers=member, json={})
    if response.status_code == 200:
        # A member who may review approves it as a separate item; the private
        # original is untouched.
        assert response.json()["id"] != original["id"]
    with SessionLocal() as db:
        count = db.scalar(
            select(KnowledgeRevision.revision)
            .where(KnowledgeRevision.knowledge_id == original["id"])
            .order_by(KnowledgeRevision.revision.desc())
        )
    assert count == 1


# --- agent tools -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_tools_read_deeply_and_suggest_without_changing_canon(client, headers):
    original = _approved_fee(client, headers)
    _capture(
        client,
        headers,
        "Enterprise customers pay the annual platform fee upfront every January.",
        title="Billing calendar",
    )
    sibling = _approve(client, headers, _pending(client, headers)[0]["id"], as_new=True)

    async with Client(mcp, raise_exceptions=True) as agent:
        detail = await agent.call_tool("get_knowledge", {"knowledge_id": original["id"]})
        assert detail.is_error is False
        data = detail.structured_content
        assert data["statement"] == original["statement"]
        assert data["revisions"][0]["revision"] == 1
        assert data["source_title"] == "Pricing 2025"

        related = (
            await agent.call_tool("related_knowledge", {"knowledge_id": original["id"]})
        ).structured_content
        assert sibling["id"] in {item["knowledge_id"] for item in related["items"]}

        pack = (
            await agent.call_tool("context_pack", {"task": "enterprise annual platform fee"})
        ).structured_content
        assert pack["count"] >= 1
        assert f"[{original['id']}]" in pack["brief"]

        suggestion = (
            await agent.call_tool(
                "propose_update",
                {
                    "knowledge_id": original["id"],
                    "statement": "Enterprise customers pay an annual fee of 1500 dollars per seat.",
                    "reason": "The 2026 price sheet raised the fee.",
                    "evidence": "2026 price sheet: enterprise seat fee is 1500 dollars per year.",
                },
            )
        ).structured_content
        assert suggestion["status"] == "awaiting_review"
        assert suggestion["relation"] == "update"

        missing = await agent.call_tool("get_knowledge", {"knowledge_id": "know_nope"})
        assert missing.is_error is True

    # Nothing changed until a person approves the suggestion.
    unchanged = client.get(f"/api/v1/knowledge/{original['id']}/revisions", headers=headers).json()
    assert len(unchanged) == 1
    updated = _approve(client, headers, suggestion["proposal_id"])
    assert updated["id"] == original["id"]
    assert "1500" in updated["statement"]
    revisions = client.get(f"/api/v1/knowledge/{original['id']}/revisions", headers=headers).json()
    assert revisions[0]["source_id"] == suggestion["source_id"]
    assert "2026 price sheet" in revisions[0]["source_excerpt"]
