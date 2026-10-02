"""Content connectors: fetch a provider document → governed ingest (proposals)."""

from __future__ import annotations

import brain.connectors as connectors


class FakeResponse:
    def __init__(self, *, json_data=None, text=""):
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


LONG = (
    "We learned that evidence must stay attached to every reusable claim because "
    "provenance is the product's core promise to reviewers and agents."
)


class TestProviderFetch:
    def test_google_drive_reads_title_and_doc_export(self, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            if url.endswith("/export"):
                return FakeResponse(text=LONG)
            return FakeResponse(
                json_data={"name": "Spec", "mimeType": "application/vnd.google-apps.document"}
            )

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        doc = connectors.GoogleDriveConnector().fetch_document("abc", "tok")
        assert doc.title == "Spec"
        assert "provenance" in doc.content

    def test_notion_joins_block_text(self, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            if url.endswith("/children"):
                return FakeResponse(
                    json_data={
                        "results": [
                            {
                                "type": "paragraph",
                                "paragraph": {"rich_text": [{"plain_text": LONG}]},
                            }
                        ]
                    }
                )
            return FakeResponse(
                json_data={
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Notion page"}]}
                    }
                }
            )

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        doc = connectors.NotionConnector().fetch_document("page1", "tok")
        assert doc.title == "Notion page"
        assert "evidence" in doc.content

    def test_onedrive_reads_name_and_content(self, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            if url.endswith("/content"):
                return FakeResponse(text=LONG)
            return FakeResponse(json_data={"name": "Report.docx"})

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        doc = connectors.OneDriveConnector().fetch_document("item1", "tok")
        assert doc.title == "Report.docx"
        assert "claim" in doc.content

    def test_unknown_provider_is_rejected(self):
        try:
            connectors.get_connector("dropbox")
        except connectors.ConnectorError:
            return
        raise AssertionError("unknown connector must raise")

    def test_fetch_failure_raises_connector_error(self, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            raise connectors.ConnectorError("Provider returned 401")

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        try:
            connectors.GoogleDriveConnector().fetch_document("abc", "bad")
        except connectors.ConnectorError:
            return
        raise AssertionError("failed fetch must raise ConnectorError")


class TestIngestIsGoverned:
    def test_connector_ingest_creates_proposals_never_canonical(self, client, headers, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            if url.endswith("/export") or "alt=media" in str(params):
                return FakeResponse(text=LONG)
            return FakeResponse(
                json_data={"name": "Spec", "mimeType": "application/vnd.google-apps.document"}
            )

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        response = client.post(
            "/api/v1/connectors/google-drive/ingest",
            headers=headers,
            json={"document_id": "abc", "access_token": "tok"},
        )
        assert response.status_code == 201
        source_id = response.json()["id"]

        proposals = client.get("/api/v1/proposals", headers=headers).json()
        assert proposals and any(p["source_id"] == source_id for p in proposals)
        # governed: an external document is a proposal, never canonical truth
        assert client.get("/api/v1/knowledge", headers=headers).json() == []

    def test_empty_document_is_rejected(self, client, headers, monkeypatch):
        def fake_get(url, token, *, params=None, headers=None):
            return FakeResponse(json_data={"name": "Empty", "mimeType": "text/plain"})

        monkeypatch.setattr(connectors, "_http_get", fake_get)
        response = client.post(
            "/api/v1/connectors/onedrive/ingest",
            headers=headers,
            json={"document_id": "x", "access_token": "tok"},
        )
        assert response.status_code in (400, 422, 502)
