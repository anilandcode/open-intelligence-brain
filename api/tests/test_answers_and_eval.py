"""Written answers (checked sentence by sentence) and the question test set."""

import json

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.answer_eval import main as eval_main
from brain.answers import supported
from brain.config import get_settings
from brain.database import engine
from brain.llm import reset_chat_model, set_chat_model
from brain.mcp_server import mcp
from brain.models import DEFAULT_WORKSPACE_ID, Knowledge, Workspace

ANNUAL = "Enterprise customers pay for the platform annually, at 1200 dollars per seat."
OWNER = "Dana Lee owns the enterprise billing migration and reports progress weekly."
HIRING = "We hire a second product designer before the end of the year."


class ScriptedModel:
    """Returns its replies in order; counts calls so a test can assert none happened."""

    model = "scripted-test-model"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        return self.replies.pop(0) if self.replies else None


@pytest.fixture(autouse=True)
def _no_model():
    reset_chat_model()
    set_chat_model(None)
    yield
    reset_chat_model()


def _approve_text(client, headers, text, title):
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": "internal", "content": text},
    )
    assert response.status_code == 201, response.text
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    approved = client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})
    assert approved.status_code == 200, approved.text
    return approved.json()


@pytest.fixture
def brain(client, headers):
    return {
        "annual": _approve_text(client, headers, ANNUAL, "Pricing"),
        "owner": _approve_text(client, headers, OWNER, "Billing plan"),
        "hiring": _approve_text(client, headers, HIRING, "Hiring"),
    }


def _ask(client, headers, question):
    response = client.post("/api/v1/chat", headers=headers, json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


# --- the sentence check --------------------------------------------------------


def test_a_sentence_must_be_traceable_to_what_it_cites():
    item = Knowledge(statement=ANNUAL, rationale="")
    assert supported("Enterprise customers pay annually, 1200 dollars per seat.", [item])
    # A number the item does not contain.
    assert not supported("Enterprise customers pay 1500 dollars per seat.", [item])
    # Mostly words the item does not contain.
    assert not supported("Startups get a generous free tier with priority support.", [item])
    assert not supported("Enterprise customers pay annually.", [])


# --- written answers ---------------------------------------------------------------


def test_model_writes_the_answer_and_untraceable_sentences_are_dropped(client, headers, brain):
    annual, owner = brain["annual"]["id"], brain["owner"]["id"]
    model = ScriptedModel(
        [
            {
                "sentences": [
                    {
                        "text": "Enterprise customers pay annually, 1200 dollars per seat.",
                        "cites": [annual],
                    },
                    {
                        "text": "Dana Lee owns the enterprise billing migration [" + owner + "].",
                        "cites": [owner],
                    },
                    {"text": "Enterprise customers get a 20 percent discount.", "cites": [annual]},
                    {"text": "Enterprise billing is handled by finance.", "cites": ["know_fake"]},
                ]
            }
        ]
    )
    set_chat_model(model)
    result = _ask(
        client, headers, "Who owns enterprise billing, and how do enterprise customers pay?"
    )
    assert model.calls == 1
    assert result["grounded"] is True
    assert result["written"] is True
    assert [s["knowledge_ids"] for s in result["sentences"]] == [[annual], [owner]]
    assert result["sentences"][1]["text"] == "Dana Lee owns the enterprise billing migration."
    assert result["dropped_sentences"] == 2
    assert [c["knowledge_id"] for c in result["citations"]] == [annual, owner]
    assert "20 percent" not in result["answer"]


def test_when_nothing_survives_the_answer_quotes_the_items(client, headers, brain):
    set_chat_model(
        ScriptedModel([{"sentences": [{"text": "Enterprise plans cost 99 dollars.", "cites": []}]}])
    )
    result = _ask(client, headers, "How do enterprise customers pay for the platform?")
    assert result["grounded"] is True
    assert result["written"] is False
    assert result["dropped_sentences"] == 1
    assert ANNUAL.rstrip(".") in result["answer"]


def test_a_failed_model_call_quotes_the_items(client, headers, brain):
    set_chat_model(ScriptedModel([None]))
    result = _ask(client, headers, "How do enterprise customers pay for the platform?")
    assert result["grounded"] is True
    assert result["written"] is False
    assert result["sentences"] == []


def test_the_model_is_not_asked_when_the_brain_abstains(client, headers, brain):
    model = ScriptedModel([])
    set_chat_model(model)
    result = _ask(client, headers, "What is our office dog called?")
    assert result["grounded"] is False
    assert model.calls == 0


def test_writing_can_be_turned_off(client, headers, brain, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_write_answers", False)
    model = ScriptedModel([])
    set_chat_model(model)
    result = _ask(client, headers, "How do enterprise customers pay for the platform?")
    assert result["grounded"] is True
    assert model.calls == 0


def test_the_answer_leads_with_the_item_that_covers_the_question(client, headers):
    _approve_text(
        client,
        headers,
        "Pricing reviews happen often; pricing pages, pricing emails and pricing calls all change.",
        "Noise",
    )
    best = _approve_text(
        client, headers, "Enterprise pricing uses annual billing for every seat.", "Pricing model"
    )
    result = _ask(client, headers, "What is our enterprise annual pricing?")
    assert result["grounded"] is True
    assert result["citations"][0]["knowledge_id"] == best["id"]


@pytest.mark.asyncio
async def test_agents_get_the_written_answer_with_its_citations(client, headers, brain):
    annual = brain["annual"]["id"]
    set_chat_model(
        ScriptedModel(
            [
                {
                    "sentences": [
                        {
                            "text": "Enterprise customers pay annually, 1200 dollars per seat.",
                            "cites": [annual],
                        }
                    ]
                }
            ]
        )
    )
    async with Client(mcp, raise_exceptions=True) as agent:
        answer = (
            await agent.call_tool(
                "ask_brain", {"question": "How do enterprise customers pay for the platform?"}
            )
        ).structured_content
    assert answer["written"] is True
    assert answer["sentences"] == [
        {
            "text": "Enterprise customers pay annually, 1200 dollars per seat.",
            "knowledge_ids": [annual],
        }
    ]


# --- the question test set ---------------------------------------------------------


def test_question_set_scores_answers_abstentions_and_stale_questions(client, headers, brain):
    def add(body):
        response = client.post("/api/v1/eval/questions", headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    add({"question": "How do enterprise customers pay?", "expected_ids": [brain["annual"]["id"]]})
    add({"question": "Who owns the billing migration?", "expected_ids": [brain["owner"]["id"]]})
    add({"question": "What is our office dog called?", "expect_abstain": True})
    # The brain answers this one, so as an abstain question it is a false answer.
    add({"question": "Does Dana Lee own the billing migration?", "expect_abstain": True})
    gone = add({"question": "When do we hire a designer?", "expected_ids": [brain["hiring"]["id"]]})

    with Session(engine) as db:
        db.get(Knowledge, brain["hiring"]["id"]).status = "superseded"
        db.commit()

    report = client.post("/api/v1/eval/run", headers=headers, json={"label": "baseline"})
    assert report.status_code == 200, report.text
    body = report.json()
    summary = body["summary"]
    assert summary["questions"] == 5
    assert summary["answerable"] == 2
    assert summary["answered_correctly"] == 2
    assert summary["recall_at_8"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["abstained_correctly"] == 1
    assert summary["false_answers"] == 1
    assert summary["stale_questions"] == 1
    assert summary["passed"] == 3
    stale = next(r for r in body["results"] if r["id"] == gone["id"])
    assert stale["passed"] is False
    assert "update the question" in stale["reason"]

    runs = client.get("/api/v1/eval/runs", headers=headers).json()
    assert [run["label"] for run in runs] == ["baseline"]
    assert runs[0]["summary"]["passed"] == 3

    assert client.delete(f"/api/v1/eval/questions/{gone['id']}", headers=headers).status_code == 204
    assert len(client.get("/api/v1/eval/questions", headers=headers).json()) == 4


def test_question_set_validation_and_access(client, headers, brain):
    post = lambda body, h=headers: client.post("/api/v1/eval/questions", headers=h, json=body)  # noqa: E731
    assert post({"question": "No answer named"}).status_code == 422
    assert (
        post(
            {"question": "Both", "expected_ids": [brain["annual"]["id"]], "expect_abstain": True}
        ).status_code
        == 422
    )
    assert post({"question": "Unknown item", "expected_ids": ["know_missing"]}).status_code == 409

    with Session(engine) as db:
        grant_workspace(db, db.get(Workspace, DEFAULT_WORKSPACE_ID), "member-token", role="member")
        db.commit()
    member = {"X-Brain-Token": "member-token"}
    assert post({"question": "Mine", "expect_abstain": True}, member).status_code == 403
    assert client.get("/api/v1/eval/questions", headers=member).status_code == 403
    assert client.post("/api/v1/eval/run", headers=member, json={}).status_code == 403


def test_question_set_travels_in_backups_and_runs_from_the_shell(client, headers, brain, capsys):
    client.post(
        "/api/v1/eval/questions",
        headers=headers,
        json={
            "question": "How do enterprise customers pay?",
            "expected_ids": [brain["annual"]["id"]],
        },
    )
    backup = client.get("/api/v1/export", headers=headers).json()
    assert [q["question"] for q in backup["eval_questions"]] == ["How do enterprise customers pay?"]

    assert eval_main(["default"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["summary"]["passed"] == 1
    assert eval_main(["no-such-workspace"]) == 2
