"""Intake that a person can keep up with, and answers that do not overclaim.

Covers the review-queue and answering changes together because they share one
promise: the queue only holds statements worth a decision, and an answer only
cites approved knowledge that actually addresses the question.
"""

from sqlalchemy.orm import Session

from brain.access import grant_workspace
from brain.database import engine
from brain.extraction import (
    candidate_score,
    is_low_value_fragment,
    is_near_duplicate,
    normalize_tags,
    statement_terms,
)


def _capture(client, headers, content, title="Note", sensitivity="internal"):
    response = client.post(
        "/api/v1/sources",
        headers=headers,
        json={"title": title, "kind": "note", "sensitivity": sensitivity, "content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _other_workspace(slug: str) -> dict:
    """A second company with its own owner token, seeded like test_workspaces."""
    from brain.models import Workspace

    with Session(engine) as db:
        workspace_id = f"ws_{slug.replace('-', '_')}"
        if db.get(Workspace, workspace_id) is None:
            db.add(Workspace(id=workspace_id, slug=slug, name=slug.title()))
            db.flush()
        grant_workspace(db, db.get(Workspace, workspace_id), f"token-{slug}", role="owner")
        db.commit()
    return {"X-Brain-Token": f"token-{slug}"}


def _pending(client, headers):
    return client.get("/api/v1/proposals", headers=headers).json()


def _approve_all(client, headers):
    for proposal in _pending(client, headers):
        client.post(f"/api/v1/proposals/{proposal['id']}/approve", headers=headers, json={})


# --- intake ------------------------------------------------------------------


class TestLowValueSpans:
    def test_structure_is_not_knowledge(self):
        assert is_low_value_fragment("## Pricing decisions for the enterprise tier")
        assert is_low_value_fragment("The plan we agreed on in the offsite was as follows:")
        assert is_low_value_fragment("| Plan | Price | Seats | Notes about the tier |")
        assert is_low_value_fragment("https://example.com/a/very/long/link/to/a/document")
        assert is_low_value_fragment("- [ ] Check the invoice template before Friday please")

    def test_prose_stays_eligible(self):
        assert not is_low_value_fragment(
            "We charge enterprise customers an annual fee because monthly billing caused churn."
        )

    def test_decisions_outrank_plain_facts(self):
        decision = "We decided to drop the free tier because support cost exceeded revenue."
        fact = "The office kitchen is on the second floor near the lifts."
        assert candidate_score(decision, "decision") > candidate_score(fact, "fact")


class TestDuplicateDetection:
    def test_near_identical_statements_match(self):
        left = statement_terms("We charge enterprise customers an annual fee.")
        right = statement_terms("We charge Enterprise customers an annual fee!")
        assert is_near_duplicate(left, right)

    def test_opposite_polarity_is_never_a_duplicate(self):
        left = statement_terms("Agents should retain approved evidence in every context package.")
        right = statement_terms(
            "Agents should not retain approved evidence in every context package."
        )
        assert not is_near_duplicate(left, right)


def test_headings_and_tables_do_not_reach_the_queue(client, headers):
    source = _capture(
        client,
        headers,
        "## Pricing review notes from the October offsite\n"
        "| Plan | Price | Seats | Notes |\n"
        "We decided to move enterprise customers to annual billing because churn fell.\n",
    )
    assert source["proposal_count"] == 1
    assert "annual billing" in _pending(client, headers)[0]["statement"]


def test_new_version_only_proposes_changed_sentences(client, headers):
    source = _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.\n"
        "Support tickets are answered within one business day by the core team.\n",
    )
    assert source["proposal_count"] == 2
    _approve_all(client, headers)

    version = client.post(
        f"/api/v1/sources/{source['id']}/versions",
        headers=headers,
        json={
            "content": (
                "We decided to move enterprise customers to annual billing because churn fell.\n"
                "Support tickets are answered within one business day by the core team.\n"
                "Refunds are issued within thirty days when a customer cancels annual plans.\n"
            ),
            "change_note": "Added the refund rule",
        },
    )
    assert version.status_code == 201
    pending = _pending(client, headers)
    assert [p["statement"] for p in pending] == [
        "Refunds are issued within thirty days when a customer cancels annual plans."
    ]
    # The two approved facts rest on sentences that did not change.
    knowledge = client.get("/api/v1/knowledge", headers=headers).json()
    assert len(knowledge) == 2
    assert all(item["stale"] is False for item in knowledge)
    assert client.get("/api/v1/integrity", headers=headers).json()["stale_count"] == 0


def test_a_statement_already_known_is_not_proposed_again(client, headers):
    sentence = "We decided to move enterprise customers to annual billing because churn fell."
    _capture(client, headers, sentence, title="Offsite notes")
    _approve_all(client, headers)
    # Pending duplicates are skipped too, not only approved ones.
    second = _capture(client, headers, sentence.replace("We decided", "we decided"), title="Copy")
    assert second["proposal_count"] == 0
    third = _capture(
        client,
        headers,
        sentence + "\nThe finance team owns the billing calendar and its review dates.",
        title="Longer copy",
    )
    assert third["proposal_count"] == 1


def test_per_version_cap_keeps_the_strongest_candidates(client, headers, monkeypatch):
    from brain.config import get_settings

    monkeypatch.setattr(get_settings(), "max_proposals_per_version", 3)
    filler = [
        f"Meeting room number {n} has a whiteboard and a projector for teams." for n in range(6)
    ]
    decisions = [
        "We decided to hire a second designer because the review backlog doubled.",
        "We learned that weekly demos catch scope creep earlier than monthly reviews.",
    ]
    content = "\n".join([*filler[:3], decisions[0], *filler[3:], decisions[1]])
    source = _capture(client, headers, content)
    assert source["proposal_count"] == 3
    statements = [p["statement"] for p in _pending(client, headers)]
    assert all(decision in statements for decision in decisions)
    # Every sentence is still kept as evidence on the source version.
    versions = client.get(f"/api/v1/sources/{source['id']}/versions", headers=headers).json()
    assert versions[0]["span_count"] == 8


# --- batch review ------------------------------------------------------------


def test_batch_approve_and_reject(client, headers):
    _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.\n"
        "We learned that weekly demos catch scope creep earlier than monthly reviews.\n"
        "Meeting room four has a whiteboard and a projector for the design team.\n",
    )
    pending = _pending(client, headers)
    by_text = {p["statement"].split()[2]: p["id"] for p in pending}
    approve = client.post(
        "/api/v1/proposals/review",
        headers=headers,
        json={
            "action": "approve",
            "proposal_ids": [by_text["to"], by_text["that"], "prop_does_not_exist"],
        },
    ).json()
    assert len(approve["approved"]) == 2
    assert approve["skipped"] == [{"proposal_id": "prop_does_not_exist", "reason": "Not found"}]

    reject = client.post(
        "/api/v1/proposals/review",
        headers=headers,
        json={"action": "reject", "proposal_ids": [by_text["four"], by_text["to"]]},
    ).json()
    assert reject["rejected"] == [by_text["four"]]
    assert reject["skipped"][0]["proposal_id"] == by_text["to"]
    assert _pending(client, headers) == []
    assert len(client.get("/api/v1/knowledge", headers=headers).json()) == 2


def test_dismiss_rest_of_a_source(client, headers):
    keep = _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.\n"
        "Meeting room four has a whiteboard and a projector for the design team.\n",
        title="Keep one",
    )
    other = _capture(
        client,
        headers,
        "We learned that weekly demos catch scope creep earlier than monthly reviews.",
        title="Untouched",
    )
    first = next(p for p in _pending(client, headers) if p["source_id"] == keep["id"])
    client.post(f"/api/v1/proposals/{first['id']}/approve", headers=headers, json={})

    result = client.post(
        f"/api/v1/sources/{keep['id']}/proposals/dismiss",
        headers=headers,
        json={"reason": "Took what mattered"},
    ).json()
    assert result == {"source_id": keep["id"], "rejected": 1}
    remaining = _pending(client, headers)
    assert [p["source_id"] for p in remaining] == [other["id"]]
    assert len(client.get("/api/v1/knowledge", headers=headers).json()) == 1


def test_batch_review_cannot_reach_another_workspace(client, headers):
    _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.",
    )
    proposal_id = _pending(client, headers)[0]["id"]
    other = _other_workspace("other-co")
    result = client.post(
        "/api/v1/proposals/review",
        headers=other,
        json={"action": "approve", "proposal_ids": [proposal_id]},
    ).json()
    assert result["approved"] == []
    assert result["skipped"] == [{"proposal_id": proposal_id, "reason": "Not found"}]


# --- answers -----------------------------------------------------------------


def test_one_shared_word_is_a_near_match_not_an_answer(client, headers):
    _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.",
    )
    _approve_all(client, headers)
    answer = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "How should we onboard new enterprise designers into the studio?"},
    ).json()
    assert answer["grounded"] is False
    assert answer["citations"] == []
    assert len(answer["near_matches"]) == 1


def test_a_relevant_fact_still_answers(client, headers):
    _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.",
    )
    _approve_all(client, headers)
    answer = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"question": "Why did we move enterprise customers to annual billing?"},
    ).json()
    assert answer["grounded"] is True
    assert answer["citations"]
    assert answer["near_matches"] == []


def test_templated_rationale_does_not_make_a_match(client, headers):
    # Every extracted proposal carries "…Review wording and evidence…" as its
    # rationale; a question about evidence must not cite unrelated facts.
    _capture(
        client,
        headers,
        "Meeting room four has a whiteboard and a projector for the design team.",
    )
    _approve_all(client, headers)
    answer = client.post(
        "/api/v1/chat", headers=headers, json={"question": "What evidence supports this?"}
    ).json()
    assert answer["grounded"] is False


def test_ranked_search_is_scoped_before_its_limit(client, headers):
    from brain.access import ReadScope
    from brain.database import SessionLocal
    from brain.retrieval import search_fts

    _capture(
        client,
        headers,
        "Our onboarding checklist for enterprise accounts lives in the shared drive.",
        title="Mine",
    )
    _approve_all(client, headers)
    noisy_headers = _other_workspace("noisy")
    topics = ["payroll", "security", "billing", "legal", "hardware", "travel"]
    for topic in topics:
        _capture(
            client,
            noisy_headers,
            f"Enterprise onboarding for {topic}: enterprise onboarding owners run the {topic} "
            f"enterprise onboarding review.",
            title=f"Noise {topic}",
        )
    _approve_all(client, noisy_headers)

    with SessionLocal() as db:
        unscoped = search_fts(db, "enterprise onboarding", limit=3)
        scoped = search_fts(
            db, "enterprise onboarding", limit=3, scope=ReadScope("ws_default", "owner")
        )
    # Ranked across every workspace, the neighbour's denser matches fill the
    # top three and this workspace's fact is cut off before scope applies.
    assert len(unscoped) == 3
    assert len(scoped) == 1
    assert scoped[0] not in unscoped
    hits = client.get("/api/v1/knowledge?q=enterprise onboarding", headers=headers).json()
    assert [hit["source_title"] for hit in hits] == ["Mine"]


# --- tags ----------------------------------------------------------------------


def test_tags_carry_onto_knowledge_and_filter_it(client, headers):
    _capture(
        client,
        headers,
        "We decided to move enterprise customers to annual billing because churn fell.\n"
        "We learned that weekly demos catch scope creep earlier than monthly reviews.\n",
    )
    pending = _pending(client, headers)
    billing = next(p for p in pending if "billing" in p["statement"])
    demos = next(p for p in pending if "demos" in p["statement"])
    approved = client.post(
        f"/api/v1/proposals/{billing['id']}/approve",
        headers=headers,
        json={"tags": ["Pricing", " pricing ", "Billing"]},
    ).json()
    assert approved["tags"] == ["pricing", "billing"]
    assert approved["summary"]
    kept = client.post(f"/api/v1/proposals/{demos['id']}/approve", headers=headers, json={}).json()
    assert kept["tags"]  # the proposal's extracted tags survive approval

    by_tag = client.get("/api/v1/knowledge?tag=pricing", headers=headers).json()
    assert [item["id"] for item in by_tag] == [approved["id"]]
    by_type = client.get("/api/v1/knowledge?type=lesson", headers=headers).json()
    assert [item["id"] for item in by_type] == [kept["id"]]
    with_query = client.get("/api/v1/knowledge?q=billing&tag=pricing", headers=headers).json()
    assert [item["id"] for item in with_query] == [approved["id"]]

    exported = client.get("/api/v1/export", headers=headers).json()
    row = next(item for item in exported["knowledge"] if item["id"] == approved["id"])
    assert row["tags"] == '["pricing", "billing"]'


def test_tag_normalisation():
    assert normalize_tags(["  Go To Market ", "go to market", 'say "hi"', ""]) == [
        "go to market",
        "say hi",
    ]
