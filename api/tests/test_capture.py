"""Easier capture: meeting transcripts, quick capture, and watched folders."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import brain.connectors as connectors
from brain.config import get_settings
from brain.database import engine
from brain.llm import reset_chat_model, set_chat_model
from brain.models import AuditEvent, ConnectorWatch, SourceSpan, SourceVersion
from brain.transcripts import normalize_transcript, speaker_at, transcript_spans
from brain.watches import main as watches_main

LAUNCH = "The launch date for the analytics product moves from April to the first week of May."
BUDGET = "The research budget for the pilot stays at forty thousand dollars for this quarter."
PRICING = "Annual pricing for the team plan increases by ten percent from next quarter onward."
REFUND = "Customers on the legacy plan keep their current price until their renewal date."
SECRET = "provider-secret-token"


class FakeResponse:
    def __init__(self, *, json_data=None, text=""):
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


VTT = f"""WEBVTT

1
00:00:01.000 --> 00:00:05.000
<v Anil Pervaiz>{LAUNCH}</v>

2
00:00:05.500 --> 00:00:09.000
<v Sara Lee>Okay. {BUDGET}

3
00:00:09.500 --> 00:00:11.000
I will tell finance today.
"""


class TestTranscriptParsing:
    def test_webvtt_becomes_one_line_per_turn(self):
        text = normalize_transcript(VTT)
        assert text.splitlines() == [
            f"Anil Pervaiz: {LAUNCH}",
            f"Sara Lee: Okay. {BUDGET} I will tell finance today.",
        ]

    def test_otter_headers_and_timestamped_lines(self):
        otter = (
            "Anil Pervaiz  0:03\nPricing goes up.\nSara  0:15\nAgreed.\n[01:02] Omar: Fine by me."
        )
        assert normalize_transcript(otter).splitlines() == [
            "Anil Pervaiz: Pricing goes up.",
            "Sara: Agreed.",
            "Omar: Fine by me.",
        ]

    def test_normalizing_twice_changes_nothing(self):
        once = normalize_transcript(VTT)
        assert normalize_transcript(once) == once

    def test_spans_carry_the_speaker_without_the_name_prefix(self):
        text = normalize_transcript(VTT)
        spans = transcript_spans(text)
        assert (LAUNCH, "Anil Pervaiz") in [(s[2], s[3]) for s in spans]
        budget = next(s for s in spans if s[2] == BUDGET)
        assert budget[3] == "Sara Lee"
        assert text[budget[0] : budget[1]] == BUDGET
        assert speaker_at(text, text.index("finance")) == "Sara Lee"

    def test_headings_are_not_speakers(self):
        assert speaker_at("Note: remember the agenda", 10) is None


class TestTranscriptCapture:
    def test_transcript_source_keeps_speakers_on_evidence(self, client, headers):
        response = client.post(
            "/api/v1/sources",
            headers=headers,
            json={"title": "Weekly sync", "kind": "transcript", "content": VTT},
        )
        assert response.status_code == 201, response.text
        source = response.json()
        assert "-->" not in source["content"] and source["content"].startswith("Anil Pervaiz: ")
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        by_statement = {p["statement"]: p for p in proposals}
        assert "Said by Anil Pervaiz" in by_statement[LAUNCH]["rationale"]
        assert "Said by Sara Lee" in by_statement[BUDGET]["rationale"]
        with Session(engine) as db:
            version = db.scalar(
                select(SourceVersion).where(SourceVersion.source_id == source["id"])
            )
            speakers = {
                span.text: span.speaker
                for span in db.scalars(
                    select(SourceSpan).where(SourceSpan.source_version_id == version.id)
                )
            }
        assert speakers[LAUNCH] == "Anil Pervaiz"
        assert speakers[BUDGET] == "Sara Lee"
        assert client.get("/api/v1/knowledge", headers=headers).json() == []


class _ScriptedModel:
    model = "scripted-test-model"

    def __init__(self, reply):
        self.reply = reply

    def complete_json(self, system, user):
        return self.reply


def test_model_claims_from_a_transcript_name_the_speaker(client, headers):
    set_chat_model(
        _ScriptedModel(
            {
                "claims": [
                    {
                        "statement": "The pilot research budget stays at $40,000 this quarter.",
                        "type": "decision",
                        "quote": BUDGET,
                        "confidence": 0.9,
                    }
                ]
            }
        )
    )
    try:
        response = client.post(
            "/api/v1/sources",
            headers=headers,
            json={"title": "Weekly sync", "kind": "transcript", "content": VTT},
        )
    finally:
        reset_chat_model()
    assert response.status_code == 201, response.text
    (proposal,) = client.get("/api/v1/proposals", headers=headers).json()
    assert proposal["rationale"].endswith("Said by Sara Lee in the transcript.")


class TestQuickCapture:
    def test_shared_text_and_link_become_a_source_for_review(self, client, headers):
        response = client.post(
            "/api/v1/capture",
            headers=headers,
            json={
                "text": f"{PRICING}\n{REFUND}",
                "url": "https://example.com/pricing",
                "via": "share",
            },
        )
        assert response.status_code == 201, response.text
        source = response.json()
        assert source["title"] == PRICING[:79].rstrip() + "…"
        assert source["content"].endswith("Source: https://example.com/pricing")
        assert source["sensitivity"] == "private" and source["proposal_count"] == 2
        assert client.get("/api/v1/knowledge", headers=headers).json() == []
        with Session(engine) as db:
            event = db.scalar(select(AuditEvent).where(AuditEvent.action == "source.captured"))
        assert event.detail == "via share"

    def test_title_from_link_when_text_is_short(self, client, headers):
        response = client.post(
            "/api/v1/capture",
            headers=headers,
            json={"text": "Read later", "url": "https://example.com/blog/post-1"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["title"] == "Read later"
        clip = client.post(
            "/api/v1/capture",
            headers=headers,
            json={"text": " ", "url": "https://example.com/blog/a-long-article-path"},
        )
        assert clip.status_code == 201, clip.text
        assert clip.json()["title"] == "example.com/blog/a-long-article-path"

    def test_voice_transcript_gets_a_dated_title(self, client, headers):
        response = client.post(
            "/api/v1/capture",
            headers=headers,
            json={"text": f"Anil: {LAUNCH}", "kind": "transcript", "via": "voice"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["title"].startswith("Meeting transcript 20")

    def test_too_short_or_bad_link_is_rejected(self, client, headers):
        short = client.post("/api/v1/capture", headers=headers, json={"text": "hi"})
        assert short.status_code == 422
        bad = client.post(
            "/api/v1/capture", headers=headers, json={"text": LAUNCH, "url": "javascript:alert(1)"}
        )
        assert bad.status_code == 422

    def test_capture_needs_a_credential(self, client):
        assert client.post("/api/v1/capture", json={"text": LAUNCH}).status_code == 401


class FakeDrive:
    """A Drive folder whose files can be edited between syncs."""

    def __init__(self):
        self.files = {
            "doc-a": {"name": "Launch plan", "modified": "2026-10-01T10:00:00Z", "text": LAUNCH},
            "doc-b": {"name": "Budget", "modified": "2026-10-01T10:00:00Z", "text": BUDGET},
        }
        self.broken: set[str] = set()
        self.list_fails = False
        self.tokens: list[str] = []

    def get(self, url, token, *, params=None, headers=None):
        self.tokens.append(token)
        if url == "https://www.googleapis.com/drive/v3/files":
            if self.list_fails:
                raise connectors.ConnectorError("Provider returned 401")
            assert "'folder-1' in parents" in params["q"]
            return FakeResponse(
                json_data={
                    "files": [
                        {
                            "id": key,
                            "name": value["name"],
                            "mimeType": "application/vnd.google-apps.document",
                            "modifiedTime": value["modified"],
                        }
                        for key, value in self.files.items()
                    ]
                    + [{"id": "img", "name": "Logo", "mimeType": "image/png", "modifiedTime": "x"}]
                }
            )
        file_id = url.split("/files/")[1].split("/")[0]
        if file_id in self.broken:
            raise connectors.ConnectorError("Provider returned 404")
        if url.endswith("/export"):
            return FakeResponse(text=self.files[file_id]["text"])
        return FakeResponse(
            json_data={
                "name": self.files[file_id]["name"],
                "mimeType": "application/vnd.google-apps.document",
            }
        )


def _watch(client, headers, **body):
    response = client.post(
        "/api/v1/watches",
        headers=headers,
        json={"provider": "google-drive", "folder_id": "folder-1", "label": "Plans", **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _sync(client, headers, watch_id):
    return client.post(
        f"/api/v1/watches/{watch_id}/sync", headers=headers, json={"access_token": SECRET}
    )


class TestWatchedFolders:
    def test_sync_adds_new_documents_then_versions_changed_ones(self, client, headers, monkeypatch):
        drive = FakeDrive()
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        watch = _watch(client, headers, sensitivity="internal")
        assert watch["document_count"] == 0 and watch["last_synced_at"] is None

        first = _sync(client, headers, watch["id"])
        assert first.status_code == 200, first.text
        assert sorted(first.json()["added"]) == ["Budget", "Launch plan"]
        sources = client.get("/api/v1/sources", headers=headers).json()
        assert {s["sensitivity"] for s in sources} == {"internal"}
        assert len(client.get("/api/v1/proposals", headers=headers).json()) == 2

        again = _sync(client, headers, watch["id"]).json()
        assert again["added"] == [] and again["updated"] == [] and again["unchanged"] == 2

        drive.files["doc-a"].update(modified="2026-10-20T09:00:00Z", text=f"{LAUNCH}\n{PRICING}")
        drive.files["doc-b"]["modified"] = "2026-10-20T09:00:00Z"  # renamed, same text
        changed = _sync(client, headers, watch["id"]).json()
        assert changed["updated"] == ["Launch plan"] and changed["unchanged"] == 1
        proposals = client.get("/api/v1/proposals", headers=headers).json()
        # Only the new sentence is offered; the unchanged one is not offered twice.
        assert sorted(p["statement"] for p in proposals) == sorted([LAUNCH, BUDGET, PRICING])
        launch = next(
            s
            for s in client.get("/api/v1/sources", headers=headers).json()
            if s["title"] == "Launch plan"
        )
        assert launch["current_version"] == 2

        listed = client.get("/api/v1/watches", headers=headers).json()
        assert listed[0]["document_count"] == 2
        assert listed[0]["last_result"].startswith("0 new, 1 updated")
        assert client.get("/api/v1/knowledge", headers=headers).json() == []

    def test_one_failing_document_does_not_stop_the_folder(self, client, headers, monkeypatch):
        drive = FakeDrive()
        drive.broken.add("doc-b")
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        watch = _watch(client, headers)
        result = _sync(client, headers, watch["id"]).json()
        assert result["added"] == ["Launch plan"]
        assert result["errors"] == ["Budget: Provider returned 404"]
        drive.broken.clear()
        retry = _sync(client, headers, watch["id"]).json()
        assert retry["added"] == ["Budget"] and retry["unchanged"] == 1

    def test_listing_failure_is_a_502_and_is_recorded(self, client, headers, monkeypatch):
        drive = FakeDrive()
        drive.list_fails = True
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        watch = _watch(client, headers)
        response = _sync(client, headers, watch["id"])
        assert response.status_code == 502
        listed = client.get("/api/v1/watches", headers=headers).json()[0]
        assert listed["last_result"] == "Listing failed: Provider returned 401"

    def test_large_folders_sync_in_batches(self, client, headers, monkeypatch):
        drive = FakeDrive()
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        monkeypatch.setattr(get_settings(), "watch_max_documents", 1)
        watch = _watch(client, headers)
        first = _sync(client, headers, watch["id"]).json()
        assert len(first["added"]) == 1 and first["deferred"] == 1
        assert "1 left for the next sync" in first["summary"]
        second = _sync(client, headers, watch["id"]).json()
        assert len(second["added"]) == 1 and second["deferred"] == 0

    def test_token_is_used_but_never_stored(self, client, headers, monkeypatch):
        drive = FakeDrive()
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        watch = _watch(client, headers)
        _sync(client, headers, watch["id"])
        assert set(drive.tokens) == {SECRET}
        with Session(engine) as db:
            row = db.get(ConnectorWatch, watch["id"])
            assert SECRET not in f"{row.last_result} {row.folder_id} {row.label}"
            details = db.scalars(select(AuditEvent.detail)).all()
        assert all(SECRET not in detail for detail in details)

    def test_duplicates_unknown_ids_and_delete(self, client, headers, monkeypatch):
        drive = FakeDrive()
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        watch = _watch(client, headers)
        duplicate = client.post(
            "/api/v1/watches",
            headers=headers,
            json={"provider": "google-drive", "folder_id": "folder-1"},
        )
        assert duplicate.status_code == 409
        assert (
            client.post(
                "/api/v1/watches", headers=headers, json={"provider": "dropbox", "folder_id": "x"}
            ).status_code
            == 422
        )
        assert _sync(client, headers, "watch_missing").status_code == 404
        _sync(client, headers, watch["id"])
        assert client.delete(f"/api/v1/watches/{watch['id']}", headers=headers).status_code == 204
        assert client.get("/api/v1/watches", headers=headers).json() == []
        # Stopping a watch keeps what it already brought in.
        assert len(client.get("/api/v1/sources", headers=headers).json()) == 2

    def test_cli_syncs_watches_with_a_token_from_the_environment(
        self, client, headers, monkeypatch, capsys
    ):
        drive = FakeDrive()
        monkeypatch.setattr(connectors, "_http_get", drive.get)
        _watch(client, headers)
        monkeypatch.delenv("BRAIN_SYNC_TOKEN_GOOGLE_DRIVE", raising=False)
        assert watches_main(["default"]) == 0
        assert "skipped" in capsys.readouterr().out
        monkeypatch.setenv("BRAIN_SYNC_TOKEN_GOOGLE_DRIVE", SECRET)
        assert watches_main(["default"]) == 0
        assert "2 new" in capsys.readouterr().out
        assert watches_main(["nope"]) == 2


class TestFolderListings:
    def test_notion_lists_child_pages_across_pages(self, monkeypatch):
        calls = []

        def fake_get(url, token, *, params=None, headers=None):
            calls.append(params.get("start_cursor"))
            if not params.get("start_cursor"):
                return FakeResponse(
                    json_data={
                        "results": [
                            {"type": "paragraph"},
                            {
                                "type": "child_page",
                                "id": "p1",
                                "child_page": {"title": "Notes"},
                                "last_edited_time": "t1",
                            },
                        ],
                        "has_more": True,
                        "next_cursor": "c2",
                    }
                )
            return FakeResponse(
                json_data={
                    "results": [
                        {
                            "type": "child_page",
                            "id": "p2",
                            "child_page": {"title": "Plan"},
                            "last_edited_time": "t2",
                        }
                    ],
                    "has_more": False,
                }
            )

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        entries = connectors.NotionConnector().list_folder("root", "tok")
        assert [(e.external_id, e.title, e.modified) for e in entries] == [
            ("p1", "Notes", "t1"),
            ("p2", "Plan", "t2"),
        ]
        assert calls == [None, "c2"]

    def test_onedrive_skips_folders_and_follows_next_link(self, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            if url.endswith("/children"):
                return FakeResponse(
                    json_data={
                        "value": [
                            {"id": "f", "name": "Sub", "folder": {}},
                            {"id": "a", "name": "a.txt", "lastModifiedDateTime": "t1"},
                        ],
                        "@odata.nextLink": "https://graph.microsoft.com/next",
                    }
                )
            return FakeResponse(
                json_data={"value": [{"id": "b", "name": "b.md", "lastModifiedDateTime": "t2"}]}
            )

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        entries = connectors.OneDriveConnector().list_folder("root", "tok")
        assert [e.external_id for e in entries] == ["a", "b"]
