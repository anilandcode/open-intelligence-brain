"""People, companies, projects and topics: suggested at intake, linked by approval.

The chat model is a scripted stand-in (see test_claims_and_agent_tools.py).
"""

import pytest
from mcp import Client
from sqlalchemy.orm import Session

from brain.access import ensure_default_workspace, grant_workspace
from brain.database import Base, engine
from brain.entities import EntityIndex, EntityRef, clean_refs, entity_key
from brain.llm import reset_chat_model, set_chat_model
from brain.mcp_server import mcp
from brain.models import DEFAULT_WORKSPACE_ID, Entity, Workspace

MEMBER = {"X-Brain-Token": "member-token"}


class ScriptedModel:
    model = "scripted-test-model"

    def __init__(self, replies):
        self.replies = list(replies)

    def complete_json(self, system, user):
        return self.replies.pop(0) if self.replies else {"claims": []}


@pytest.fixture(autouse=True)
def _no_model():
    reset_chat_model()
    set_chat_model(None)
    yield
    reset_chat_model()


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


def _pending(client, headers):
    return client.get("/api/v1/proposals", headers=headers).json()


def _approve(client, headers, proposal_id, **body):
    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _claim(statement, quote, entities):
    return {
        "statement": statement,
        "type": "decision",
        "quote": quote,
        "confidence": 0.9,
        "entities": entities,
    }


def _approved_about(client, headers, statement, entities, sensitivity="internal", title="Note"):
    """Capture `statement`, suggest `entities` via the model and approve it."""
    set_chat_model(ScriptedModel([{"claims": [_claim(statement, statement, entities)]}]))
    _capture(client, headers, statement, title=title, sensitivity=sensitivity)
    set_chat_model(None)
    proposal = next(p for p in _pending(client, headers) if p["statement"] == statement)
    return _approve(client, headers, proposal["id"])


# --- helpers ------------------------------------------------------------------


def test_refs_are_cleaned_and_deduplicated():
    refs = clean_refs(
        [
            {"name": "  Dana  Lee ", "kind": "person"},
            {"name": "dana lee.", "kind": "person"},
            {"name": "Acme", "kind": "vendor"},
            {"name": "x", "kind": "topic"},
            "Billing",
            42,
        ]
    )
    assert refs == [
        EntityRef("Dana Lee", "person"),
        EntityRef("Acme", "topic"),
        EntityRef("Billing", "topic"),
    ]
    assert entity_key(" Acme  Corp. ") == "acme corp"
    assert clean_refs("not json") == []


def test_known_names_and_aliases_are_matched_on_word_boundaries():
    acme = Entity(id="e1", kind="company", name="Acme Corp", key="acme corp", aliases='["Acme"]')
    index = EntityIndex([acme])
    assert index.mentions("Acme renewed for two years.") == [EntityRef("Acme Corp", "company")]
    assert index.mentions("Acmeville is a town.") == []
    assert index.suggest("Nothing here.", [EntityRef("acme", "topic")]) == [
        EntityRef("Acme Corp", "company")
    ]


# --- intake and approval ------------------------------------------------------


def test_model_suggests_entities_and_approval_links_them(client, headers):
    item = _approved_about(
        client,
        headers,
        "Dana Lee owns the Acme renewal for Project Falcon.",
        [
            {"name": "Dana Lee", "kind": "person"},
            {"name": "Acme", "kind": "company"},
            {"name": "Project Falcon", "kind": "project"},
        ],
    )
    assert {(e["name"], e["kind"]) for e in item["entities"]} == {
        ("Dana Lee", "person"),
        ("Acme", "company"),
        ("Project Falcon", "project"),
    }
    listed = client.get("/api/v1/entities", headers=headers).json()
    assert {e["name"]: e["item_count"] for e in listed} == {
        "Dana Lee": 1,
        "Acme": 1,
        "Project Falcon": 1,
    }
    people = client.get("/api/v1/entities?kind=person", headers=headers).json()
    assert [e["name"] for e in people] == ["Dana Lee"]

    dana = people[0]
    detail = client.get(f"/api/v1/entities/{dana['id']}", headers=headers).json()
    assert [i["id"] for i in detail["items"]] == [item["id"]]
    assert {r["name"] for r in detail["related"]} == {"Acme", "Project Falcon"}
    filtered = client.get(f"/api/v1/knowledge?entity={dana['id']}", headers=headers).json()
    assert [i["id"] for i in filtered] == [item["id"]]


def test_reviewer_choice_replaces_suggestions(client, headers):
    statement = "Dana Lee prefers written recaps after every pricing call."
    set_chat_model(
        ScriptedModel(
            [{"claims": [_claim(statement, statement, [{"name": "Dana Lee", "kind": "person"}])]}]
        )
    )
    _capture(client, headers, statement)
    proposal = _pending(client, headers)[0]
    assert proposal["entities"] == [{"id": None, "name": "Dana Lee", "kind": "person"}]
    item = _approve(
        client,
        headers,
        proposal["id"],
        entities=[{"name": "Dana Lee", "kind": "person"}, {"name": "Pricing", "kind": "topic"}],
    )
    assert sorted(e["name"] for e in item["entities"]) == ["Dana Lee", "Pricing"]

    statement2 = "Dana Lee runs the onboarding calls for new enterprise customers."
    set_chat_model(
        ScriptedModel(
            [{"claims": [_claim(statement2, statement2, [{"name": "Dana", "kind": "person"}])]}]
        )
    )
    _capture(client, headers, statement2, title="Second")
    second = _approve(client, headers, _pending(client, headers)[0]["id"], entities=[])
    assert second["entities"] == []


def test_known_entities_are_suggested_without_a_model(client, headers):
    created = client.post(
        "/api/v1/entities",
        headers=headers,
        json={"name": "Acme Corp", "kind": "company", "aliases": ["Acme"]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["item_count"] == 0
    _capture(client, headers, "Acme renewed their enterprise contract for another two years.")
    proposal = _pending(client, headers)[0]
    assert proposal["entities"] == [{"id": None, "name": "Acme Corp", "kind": "company"}]
    item = _approve(client, headers, proposal["id"])
    assert [e["name"] for e in item["entities"]] == ["Acme Corp"]


def test_creating_an_entity_links_items_that_already_name_it(client, headers):
    _capture(client, headers, "Northwind asked for quarterly invoices instead of monthly ones.")
    item = _approve(client, headers, _pending(client, headers)[0]["id"])
    assert item["entities"] == []
    created = client.post(
        "/api/v1/entities", headers=headers, json={"name": "Northwind", "kind": "company"}
    ).json()
    assert created["item_count"] == 1
    duplicate = client.post(
        "/api/v1/entities", headers=headers, json={"name": "northwind", "kind": "company"}
    )
    assert duplicate.status_code == 409


def test_an_update_keeps_and_adds_links(client, headers):
    original = _approved_about(
        client,
        headers,
        "Enterprise customers pay an annual platform fee of 1200 dollars per seat.",
        [{"name": "Enterprise pricing", "kind": "topic"}],
    )
    statement = "Enterprise customers now pay an annual platform fee of 1500 dollars per seat."
    set_chat_model(
        ScriptedModel(
            [{"claims": [_claim(statement, statement, [{"name": "Acme", "kind": "company"}])]}]
        )
    )
    _capture(client, headers, statement, title="Pricing 2026")
    proposal = _pending(client, headers)[0]
    assert proposal["relation"] == "update"
    updated = _approve(client, headers, proposal["id"])
    assert updated["id"] == original["id"]
    assert sorted(e["name"] for e in updated["entities"]) == ["Acme", "Enterprise pricing"]


# --- visibility ---------------------------------------------------------------


def test_entities_named_only_in_private_material_stay_hidden_from_members(client, headers):
    _member()
    _approved_about(
        client,
        headers,
        "Project Falcon will acquire a small design studio next spring.",
        [{"name": "Project Falcon", "kind": "project"}],
        sensitivity="private",
    )
    _approved_about(
        client,
        headers,
        "Dana Lee leads the public roadmap review every quarter.",
        [{"name": "Dana Lee", "kind": "person"}],
        title="Team note",
    )
    owner_view = {
        e["name"]: e["id"] for e in client.get("/api/v1/entities", headers=headers).json()
    }
    assert set(owner_view) == {"Project Falcon", "Dana Lee"}
    member_view = [e["name"] for e in client.get("/api/v1/entities", headers=MEMBER).json()]
    assert member_view == ["Dana Lee"]
    falcon = owner_view["Project Falcon"]
    assert client.get(f"/api/v1/entities/{falcon}", headers=MEMBER).status_code == 404
    assert client.get(f"/api/v1/knowledge?entity={falcon}", headers=MEMBER).json() == []
    assert (
        client.patch(
            f"/api/v1/entities/{falcon}", headers=MEMBER, json={"name": "Hawk"}
        ).status_code
        == 404
    )
    graph = client.get("/api/v1/graph", headers=MEMBER).json()
    assert [e["name"] for e in graph["entities"]] == ["Dana Lee"]
    owner_graph = client.get("/api/v1/graph", headers=headers).json()
    assert {e["name"] for e in owner_graph["entities"]} == {"Project Falcon", "Dana Lee"}
    assert any(edge["edgeType"] == "mentions" for edge in owner_graph["edges"])


def test_entities_in_another_workspace_are_not_found(client, headers):
    item = _approved_about(
        client, headers, "Dana Lee owns the billing migration plan.", [{"name": "Dana Lee"}]
    )
    dana = item["entities"][0]["id"]
    with Session(engine) as db:
        other = Workspace(id="ws_other", slug="other", name="Other")
        db.add(other)
        db.flush()
        grant_workspace(db, other, "other-token", role="owner")
        db.commit()
    other_headers = {"X-Brain-Token": "other-token", "X-Brain-Workspace": "other"}
    assert client.get("/api/v1/entities", headers=other_headers).json() == []
    assert client.get(f"/api/v1/entities/{dana}", headers=other_headers).status_code == 404


# --- curation ------------------------------------------------------------------


def test_rename_keeps_the_old_name_and_merge_folds_duplicates(client, headers):
    first = _approved_about(
        client,
        headers,
        "Dana owns the billing migration plan for enterprise accounts.",
        [{"name": "Dana", "kind": "person"}],
    )
    second = _approved_about(
        client,
        headers,
        "D. Lee approved the onboarding checklist for new customers.",
        [{"name": "D. Lee", "kind": "person"}],
        title="Second",
    )
    dana = first["entities"][0]["id"]
    duplicate = second["entities"][0]["id"]

    renamed = client.patch(f"/api/v1/entities/{dana}", headers=headers, json={"name": "Dana Lee"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Dana Lee"
    assert renamed.json()["aliases"] == ["Dana"]

    merged = client.post(
        f"/api/v1/entities/{duplicate}/merge", headers=headers, json={"into_id": dana}
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["item_count"] == 2
    assert set(merged.json()["aliases"]) == {"Dana", "D. Lee"}
    assert client.get(f"/api/v1/entities/{duplicate}", headers=headers).status_code == 404
    items = client.get(f"/api/v1/knowledge?entity={dana}", headers=headers).json()
    assert {i["id"] for i in items} == {first["id"], second["id"]}

    clash = client.post(
        "/api/v1/entities", headers=headers, json={"name": "D. Lee", "kind": "person"}
    )
    assert clash.status_code == 409
    bad_kind = client.patch(f"/api/v1/entities/{dana}", headers=headers, json={"kind": "vendor"})
    assert bad_kind.status_code == 422


# --- agents --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_can_look_up_an_entity(client, headers):
    item = _approved_about(
        client,
        headers,
        "Dana Lee owns the Acme renewal and reports to the finance lead.",
        [{"name": "Dana Lee", "kind": "person"}, {"name": "Acme", "kind": "company"}],
    )
    other = _approved_about(
        client,
        headers,
        "The Acme renewal closes before the end of the fiscal year.",
        [{"name": "Acme", "kind": "company"}],
        title="Renewals",
    )
    async with Client(mcp, raise_exceptions=True) as agent:
        listed = (await agent.call_tool("list_entities", {"kind": "company"})).structured_content
        assert [e["name"] for e in listed["items"]] == ["Acme"]
        assert listed["items"][0]["item_count"] == 2

        profile = (await agent.call_tool("entity_profile", {"name": "acme"})).structured_content
        assert profile["name"] == "Acme"
        assert {i["knowledge_id"] for i in profile["items"]} == {item["id"], other["id"]}
        assert profile["related"] == [{"name": "Dana Lee", "kind": "person", "shared_items": 1}]

        about = (
            await agent.call_tool("search_brain", {"query": "renewal", "about": "Dana Lee"})
        ).structured_content
        assert [i["knowledge_id"] for i in about["items"]] == [item["id"]]
        assert sorted(about["items"][0]["entities"]) == ["Acme", "Dana Lee"]

        nobody = (
            await agent.call_tool("search_brain", {"query": "renewal", "about": "Nobody"})
        ).structured_content
        assert nobody["count"] == 0

        missing = await agent.call_tool("entity_profile", {"name": "Nobody"})
        assert missing.is_error is True

        detail = (
            await agent.call_tool("get_knowledge", {"knowledge_id": item["id"]})
        ).structured_content
        assert sorted(detail["entities"]) == ["Acme", "Dana Lee"]


# --- backup --------------------------------------------------------------------


def test_backup_carries_entities_and_links(client, headers):
    item = _approved_about(
        client,
        headers,
        "Dana Lee owns the billing migration plan for enterprise accounts.",
        [{"name": "Dana Lee", "kind": "person"}],
    )
    backup = client.get("/api/v1/export", headers=headers).json()
    assert [e["name"] for e in backup["entities"]] == ["Dana Lee"]
    assert backup["knowledge_entities"] == [
        {"knowledge_id": item["id"], "entity_id": item["entities"][0]["id"]}
    ]

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
    knowledge = client.get("/api/v1/knowledge", headers=headers).json()
    assert [e["name"] for e in knowledge[0]["entities"]] == ["Dana Lee"]
