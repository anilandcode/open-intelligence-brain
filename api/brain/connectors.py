"""Content connectors — bring external documents into the review queue.

Ports Supermemory's connector boundary (`ToolProviderHandle`: list + call a
provider) into Open Brain's governed model. A connector FETCHES one document
from Google Drive / Notion / OneDrive and hands it to
``create_source_with_proposals``, so external content becomes a source + candidate
proposals for human review — never canonical. The provider access token is
supplied by the caller (the connector only reads); OAuth acquisition is out of
scope here and token material is never stored or logged.

Reuse: Open Brain's existing ingest path (``create_source_with_proposals``) and the
connection-registry masking pattern (``token_preview``). A provider outage raises
``ConnectorError`` for that fetch only — it never blocks reads, review, or export.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

FETCH_TIMEOUT = 30.0
NOTION_VERSION = "2022-06-28"


class ConnectorError(RuntimeError):
    """A provider fetch failed (bad token, missing document, or provider outage)."""


@dataclass
class FetchedDocument:
    """One document read from a provider, ready for governed ingest."""

    title: str
    content: str
    kind: str = "research"
    external_id: str = ""


def _http_get(url: str, token: str, *, params=None, headers=None) -> httpx.Response:
    """Single HTTP chokepoint (mocked in tests). Reads only; never stores a token."""
    merged = {"Authorization": f"Bearer {token}", **(headers or {})}
    try:
        response = httpx.get(url, headers=merged, params=params, timeout=FETCH_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Provider request failed: {exc}") from exc
    if response.status_code >= 400:
        raise ConnectorError(f"Provider returned {response.status_code}")
    return response


class GoogleDriveConnector:
    name = "google-drive"

    def fetch_document(self, document_id: str, access_token: str) -> FetchedDocument:
        meta = _http_get(
            f"https://www.googleapis.com/drive/v3/files/{document_id}",
            access_token,
            params={"fields": "name,mimeType"},
        ).json()
        title = meta.get("name") or document_id
        if meta.get("mimeType") == "application/vnd.google-apps.document":
            content = _http_get(
                f"https://www.googleapis.com/drive/v3/files/{document_id}/export",
                access_token,
                params={"mimeType": "text/plain"},
            ).text
        else:
            content = _http_get(
                f"https://www.googleapis.com/drive/v3/files/{document_id}",
                access_token,
                params={"alt": "media"},
            ).text
        return FetchedDocument(title=title, content=content, external_id=document_id)


class NotionConnector:
    name = "notion"

    def fetch_document(self, document_id: str, access_token: str) -> FetchedDocument:
        headers = {"Notion-Version": NOTION_VERSION}
        page = _http_get(
            f"https://api.notion.com/v1/pages/{document_id}", access_token, headers=headers
        ).json()
        title = _notion_title(page) or document_id
        blocks = _http_get(
            f"https://api.notion.com/v1/blocks/{document_id}/children",
            access_token,
            headers=headers,
            params={"page_size": 100},
        ).json()
        content = "\n".join(_block_text(b) for b in blocks.get("results", []))
        return FetchedDocument(title=title, content=content, external_id=document_id)


class OneDriveConnector:
    name = "onedrive"

    def fetch_document(self, document_id: str, access_token: str) -> FetchedDocument:
        item = _http_get(
            f"https://graph.microsoft.com/v1.0/me/drive/items/{document_id}", access_token
        ).json()
        title = item.get("name") or document_id
        content = _http_get(
            f"https://graph.microsoft.com/v1.0/me/drive/items/{document_id}/content", access_token
        ).text
        return FetchedDocument(title=title, content=content, external_id=document_id)


def _notion_title(page: dict) -> str:
    for value in page.get("properties", {}).values():
        if isinstance(value, dict) and value.get("type") == "title":
            return "".join(p.get("plain_text", "") for p in value.get("title", []))
    return ""


def _block_text(block: dict) -> str:
    block_type = block.get("type", "")
    data = block.get(block_type, {})
    rich = data.get("rich_text", []) if isinstance(data, dict) else []
    return "".join(p.get("plain_text", "") for p in rich)


_CONNECTORS = {
    "google-drive": GoogleDriveConnector,
    "notion": NotionConnector,
    "onedrive": OneDriveConnector,
}
PROVIDERS: tuple[str, ...] = tuple(_CONNECTORS)


def get_connector(provider: str):
    cls = _CONNECTORS.get(provider)
    if cls is None:
        raise ConnectorError(f"Unknown connector: {provider}")
    return cls()


def ingest_fetched(
    db, workspace_id: str, fetched: FetchedDocument, *, sensitivity: str = "private", actor=None
):
    """Hand a fetched document to the governed ingest path: source + proposals.

    ``create_source_with_proposals`` runs the same chunk → classify → critic →
    proposal pipeline as a manual capture, so the document lands in the review
    queue and is never approved automatically.
    """
    from .schemas import SourceCreate
    from .services import create_source_with_proposals

    content = (fetched.content or "").strip()
    if len(content) < 20:
        raise ConnectorError("Fetched document has no usable text content")
    title = (fetched.title or "").strip() or "Untitled document"
    if len(title) < 3:
        title = f"Document {fetched.external_id}".strip() or "Untitled document"
    payload = SourceCreate(
        title=title[:240], kind=fetched.kind, sensitivity=sensitivity, content=content
    )
    return create_source_with_proposals(db, payload, workspace_id, actor=actor)
