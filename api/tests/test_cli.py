"""Hermetic tests for openbrain CLI."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from openbrain.cli import build_parser
from starlette.testclient import TestClient

from brain.access import ensure_default_workspace
from brain.database import SessionLocal


@pytest.fixture
def cli_bridge(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENBRAIN_TOKEN", "test-token")
    monkeypatch.setenv("NO_COLOR", "1")
    with SessionLocal() as db:
        ensure_default_workspace(db)
        db.commit()

    def fake_urlopen(req, timeout=30.0):
        method = req.get_method()
        url = req.full_url.replace("http://localhost:8000", "")
        data = req.data.decode("utf-8") if req.data else None
        req_headers = dict(req.headers)
        json_body = None
        if data:
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
        yield


class TestOpenBrainCLI:
    def test_cli_parser_builds(self):
        parser = build_parser()
        args = parser.parse_args(["search", "test query", "--limit", "5"])
        assert args.command == "search"
        assert args.query == "test query"
        assert args.limit == 5

    def test_cli_status(self, cli_bridge, capsys):
        parser = build_parser()
        args = parser.parse_args(["status", "--json"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "online"

    def test_cli_ingest_and_search(self, cli_bridge, capsys):
        parser = build_parser()

        # 1. Ingest
        ingest_args = parser.parse_args(
            [
                "ingest",
                "Redis cache cluster is designated for distributed caching and session storage.",
                "--title",
                "Cache Architecture",
            ]
        )
        ret = ingest_args.func(ingest_args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Ingested source:" in captured.out

        # 2. Review list
        review_args = parser.parse_args(["review", "--json"])
        ret = review_args.func(review_args)
        assert ret == 0
        captured = capsys.readouterr()
        proposals = json.loads(captured.out)
        assert len(proposals) >= 1
        pid = proposals[0]["id"]

        # 3. Approve
        approve_args = parser.parse_args(["review", "--approve", pid])
        ret = approve_args.func(approve_args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Approved proposal" in captured.out

        # 4. Search
        search_args = parser.parse_args(["search", "Redis", "--json"])
        ret = search_args.func(search_args)
        assert ret == 0
        captured = capsys.readouterr()
        results = json.loads(captured.out)
        assert len(results) >= 1
        assert "Redis" in results[0]["statement"]

        # 5. Ask
        ask_args = parser.parse_args(["ask", "What cache do we use?", "--json"])
        ret = ask_args.func(ask_args)
        assert ret == 0
        captured = capsys.readouterr()
        ask_data = json.loads(captured.out)
        assert "answer" in ask_data
        assert "grounded" in ask_data

    def test_cli_policy(self, cli_bridge, capsys):
        parser = build_parser()

        # Policy get
        args_get = parser.parse_args(["policy", "get", "--json"])
        ret = args_get.func(args_get)
        assert ret == 0
        captured = capsys.readouterr()
        policy = json.loads(captured.out)
        assert "auto_approve_enabled" in policy

        # Policy set
        args_set = parser.parse_args(["policy", "set", "--auto-approve", "true", "--json"])
        ret = args_set.func(args_set)
        assert ret == 0
        captured = capsys.readouterr()
        updated = json.loads(captured.out)
        assert updated["auto_approve_enabled"] is True

    def test_cli_graph(self, cli_bridge, capsys):
        parser = build_parser()
        args = parser.parse_args(["graph", "--json"])
        ret = args.func(args)
        assert ret == 0
        captured = capsys.readouterr()
        graph = json.loads(captured.out)
        assert "nodes" in graph or "documents" in graph
        assert "edges" in graph

    def test_cli_delete_source(self, cli_bridge, capsys):
        parser = build_parser()
        ingest_args = parser.parse_args(
            [
                "ingest",
                "Temporary scratch note that will be deleted before approval.",
                "--title",
                "Scratch Note",
                "--json",
            ]
        )
        assert ingest_args.func(ingest_args) == 0
        src = json.loads(capsys.readouterr().out)
        sid = src["id"]

        preview_args = parser.parse_args(["delete-source", sid, "--preview", "--json"])
        assert preview_args.func(preview_args) == 0
        prev = json.loads(capsys.readouterr().out)
        assert prev["blocked"] is False

        del_args = parser.parse_args(["delete-source", sid, "--json"])
        assert del_args.func(del_args) == 0
        deleted = json.loads(capsys.readouterr().out)
        assert deleted["deleted"] is True
        assert deleted["source_id"] == sid
