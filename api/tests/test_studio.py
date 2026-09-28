"""Tests for Intelligence Studio — interviews and drafts."""

import pytest
from sqlalchemy.orm import Session

from brain.database import SessionLocal
from brain.models import Knowledge, Source, new_id


@pytest.fixture
def workspace():
    from brain.access import ensure_default_workspace, grant_workspace
    with SessionLocal() as db:
        ws = ensure_default_workspace(db)
        grant_workspace(db, ws, "test-token", role="owner")
        db.commit()
        return ws


@pytest.fixture
def knowledge_items(workspace):
    """Create some approved knowledge for draft tests."""
    items = []
    with SessionLocal() as db:
        for i, (stmt, typ) in enumerate([
            ("We believe AI output becomes valuable when grounded in company experience", "belief"),
            ("The approval boundary protects against confident extraction mistakes", "lesson"),
            ("Our framework for evaluating tools prioritizes evidence over opinion", "framework"),
            ("Every canonical item must link back to its original source excerpt", "fact"),
        ]):
            source = Source(
                id=new_id("src"), workspace_id=workspace.id,
                title=f"Source {i}", content=f"Content for source {i}. " * 10,
            )
            db.add(source)
            db.flush()
            k = Knowledge(
                id=new_id("know"), workspace_id=workspace.id,
                proposal_id=new_id("prop"), source_id=source.id,
                type=typ, statement=stmt,
                rationale="Test rationale", source_excerpt=f"Excerpt {i}",
            )
            db.add(k)
            items.append(k)
        db.commit()
    return items


class TestInterviews:
    def test_create_interview(self, client, headers):
        response = client.post("/api/v1/studio/interviews", json={
            "title": "Founder interview",
            "topic": "Company vision",
            "person": "CEO",
            "audience": "Investors",
        }, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Founder interview"
        assert data["status"] == "drafting"

    def test_list_interviews(self, client, headers):
        client.post("/api/v1/studio/interviews", json={"title": "Interview 1"}, headers=headers)
        client.post("/api/v1/studio/interviews", json={"title": "Interview 2"}, headers=headers)
        response = client.get("/api/v1/studio/interviews", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_add_questions(self, client, headers):
        r = client.post("/api/v1/studio/interviews", json={"title": "Test"}, headers=headers)
        sid = r.json()["id"]
        q1 = client.post(f"/api/v1/studio/interviews/{sid}/questions",
                         json={"question_text": "What is the company vision?"}, headers=headers)
        assert q1.status_code == 201
        assert q1.json()["ordinal"] == 1
        q2 = client.post(f"/api/v1/studio/interviews/{sid}/questions",
                         json={"question_text": "What makes your approach unique?"}, headers=headers)
        assert q2.json()["ordinal"] == 2

    def test_submit_response(self, client, headers):
        r = client.post("/api/v1/studio/interviews", json={"title": "Test"}, headers=headers)
        sid = r.json()["id"]
        q = client.post(f"/api/v1/studio/interviews/{sid}/questions",
                        json={"question_text": "What is the vision?"}, headers=headers)
        qid = q.json()["id"]
        resp = client.post(f"/api/v1/studio/interviews/{sid}/questions/{qid}/respond",
                           json={"response_text": "We believe AI should be grounded in real experience."},
                           headers=headers)
        assert resp.status_code == 200
        assert resp.json()["response_text"] == "We believe AI should be grounded in real experience."

    def test_complete_interview_creates_source(self, client, headers):
        r = client.post("/api/v1/studio/interviews", json={
            "title": "Test Interview", "person": "CEO",
        }, headers=headers)
        sid = r.json()["id"]
        q = client.post(f"/api/v1/studio/interviews/{sid}/questions",
                        json={"question_text": "What do you believe?"}, headers=headers)
        qid = q.json()["id"]
        client.post(f"/api/v1/studio/interviews/{sid}/questions/{qid}/respond",
                    json={"response_text": "We believe that evidence should stay attached to every claim."},
                    headers=headers)
        complete = client.post(f"/api/v1/studio/interviews/{sid}/complete", headers=headers)
        assert complete.status_code == 200
        data = complete.json()
        assert data["status"] == "completed"
        assert data["source_id"] is not None
        assert data["response_count"] == 1

    def test_complete_empty_interview_fails(self, client, headers):
        r = client.post("/api/v1/studio/interviews", json={"title": "Empty"}, headers=headers)
        sid = r.json()["id"]
        client.post(f"/api/v1/studio/interviews/{sid}/questions",
                    json={"question_text": "Hello?"}, headers=headers)
        resp = client.post(f"/api/v1/studio/interviews/{sid}/complete", headers=headers)
        assert resp.status_code == 409


class TestDrafts:
    def test_create_draft(self, client, headers):
        response = client.post("/api/v1/studio/drafts", json={
            "title": "Investor brief", "intent": "brief", "audience": "VCs",
        }, headers=headers)
        assert response.status_code == 201
        assert response.json()["title"] == "Investor brief"

    def test_add_section(self, client, headers):
        r = client.post("/api/v1/studio/drafts", json={"title": "Test"}, headers=headers)
        did = r.json()["id"]
        section = client.post(f"/api/v1/studio/drafts/{did}/sections", json={
            "title": "Introduction", "content": "This is the intro.",
        }, headers=headers)
        assert section.status_code == 201
        assert section.json()["ordinal"] == 1

    def test_get_draft_with_sections(self, client, headers):
        r = client.post("/api/v1/studio/drafts", json={"title": "Test"}, headers=headers)
        did = r.json()["id"]
        client.post(f"/api/v1/studio/drafts/{did}/sections", json={
            "title": "Section 1", "content": "Content 1",
        }, headers=headers)
        client.post(f"/api/v1/studio/drafts/{did}/sections", json={
            "title": "Section 2", "content": "Content 2",
        }, headers=headers)
        detail = client.get(f"/api/v1/studio/drafts/{did}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["section_count"] == 2
        assert len(detail.json()["sections"]) == 2

    def test_assemble_draft_from_knowledge(self, client, headers, knowledge_items):
        kid = knowledge_items[0].id
        r = client.post("/api/v1/studio/drafts/assemble", json={
            "title": "Assembled brief",
            "intent": "brief",
            "audience": "Team",
            "knowledge_ids": [k.id for k in knowledge_items],
            "include_excerpts": True,
        }, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Assembled brief"
        assert data["section_count"] >= 1
        assert data["citation_count"] == len(knowledge_items)

    def test_assemble_empty_fails(self, client, headers):
        r = client.post("/api/v1/studio/drafts/assemble", json={
            "title": "Empty", "knowledge_ids": [],
        }, headers=headers)
        assert r.status_code == 422  # validation error: min_length=1

    def test_list_drafts(self, client, headers):
        client.post("/api/v1/studio/drafts", json={"title": "Draft 1"}, headers=headers)
        client.post("/api/v1/studio/drafts", json={"title": "Draft 2"}, headers=headers)
        r = client.get("/api/v1/studio/drafts", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_delete_section(self, client, headers):
        r = client.post("/api/v1/studio/drafts", json={"title": "Test"}, headers=headers)
        did = r.json()["id"]
        s = client.post(f"/api/v1/studio/drafts/{did}/sections", json={
            "title": "Temp", "content": "Temp content",
        }, headers=headers)
        sid = s.json()["id"]
        resp = client.delete(f"/api/v1/studio/drafts/{did}/sections/{sid}", headers=headers)
        assert resp.status_code == 204
        detail = client.get(f"/api/v1/studio/drafts/{did}", headers=headers)
        assert detail.json()["section_count"] == 0