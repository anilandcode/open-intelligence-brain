"""Tests for Mem0 Drop-In Compatibility Shim and OpenBrain Python SDK."""

from __future__ import annotations

from unittest.mock import patch

from openbrain import Brain
from starlette.testclient import TestClient

from brain.access import ensure_default_workspace
from brain.database import SessionLocal


class TestMem0CompatibilityShim:
    def test_post_memories_messages_auto_approves(
        self, client: TestClient, headers: dict[str, str]
    ):
        payload = {
            "messages": [
                {"role": "user", "content": "Our main server runs on Ubuntu 24.04 LTS."},
                {"role": "assistant", "content": "Got it, noting your operating system."},
            ],
            "user_id": "alice",
            "auto_approve": True,
        }
        res = client.post("/v1/memories", json=payload, headers=headers)
        assert res.status_code == 201
        data = res.json()
        assert "results" in data
        assert len(data["results"]) >= 1
        first = data["results"][0]
        assert first["event"] in ["ADD", "INGESTED"]
        assert first["id"].startswith("know_") or first["id"].startswith("src_")

    def test_post_memories_text_and_search(self, client: TestClient, headers: dict[str, str]):
        payload = {
            "text": "The billing currency for enterprise customers is strictly USD.",
            "user_id": "bob",
            "auto_approve": True,
        }
        res = client.post("/v1/memories/", json=payload, headers=headers)
        assert res.status_code == 201

        search_res = client.post(
            "/v1/memories/search",
            json={"query": "billing currency", "user_id": "bob"},
            headers=headers,
        )
        assert search_res.status_code == 200
        items = search_res.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        assert "billing" in items[0]["memory"].lower()
        assert "source_excerpt" in items[0]["metadata"]
        assert items[0]["metadata"]["provenance"] == "open-intelligence-brain"

    def test_list_and_delete_memory(self, client: TestClient, headers: dict[str, str]):
        with SessionLocal() as db:
            ensure_default_workspace(db)
            db.commit()

        # Ingest and approve a memory
        ingest_res = client.post(
            "/v1/memories",
            json={
                "text": "Temporary staging memory for deletion verification.",
                "auto_approve": True,
            },
            headers=headers,
        )
        assert ingest_res.status_code == 201
        res_data = ingest_res.json()
        mem_id = res_data["results"][0]["id"]

        # List memories
        list_res = client.get("/v1/memories?user_id=default_user", headers=headers)
        assert list_res.status_code == 200
        memories = list_res.json()
        assert any(m["id"] == mem_id for m in memories)

        # Delete memory
        del_res = client.delete(f"/v1/memories/{mem_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["message"] == "Memory deleted successfully"


class TestOpenBrainPythonSDK:
    def test_sdk_methods_against_testclient(self, client: TestClient, headers: dict[str, str]):
        brain = Brain(base_url="http://testserver", api_key="test-token")

        # Mock urllib with TestClient bridge
        def fake_urlopen(req, timeout=30.0):
            method = req.get_method()
            url = req.full_url.replace("http://testserver", "")
            data = req.data.decode("utf-8") if req.data else None
            req_headers = dict(req.headers)
            json_body = None
            if data:
                import json

                json_body = json.loads(data)

            response = client.request(method, url, json=json_body, headers=req_headers)

            class FakeResponse:
                def __init__(self, r):
                    self.status = r.status_code
                    self._content = r.content

                def read(self):
                    return self._content

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            return FakeResponse(response)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # 1. Add source
            src = brain.add(
                "Primary deployment target is AWS us-east-1 region.",
                title="Cloud Architecture",
                kind="decision",
            )
            assert "id" in src
            assert src["title"] == "Cloud Architecture"

            # 2. List proposals
            props = brain.proposals()
            assert isinstance(props, list)
            assert len(props) >= 1
            p = props[0]

            # 3. Approve proposal
            k = brain.approve(p["id"])
            assert "id" in k
            assert k["status"] == "canonical"

            # 4. Search knowledge
            results = brain.search("AWS us-east-1")
            assert len(results) >= 1
            assert any(item["id"] == k["id"] for item in results)

            # 5. Ask question
            answer = brain.ask("Where is our primary deployment target?")
            assert "answer" in answer
            assert "citations" in answer
