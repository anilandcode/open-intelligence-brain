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
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

FETCH_TIMEOUT = 30.0
NOTION_VERSION = "2022-06-28"
# Pages of a folder listing read per sync (100 entries each).
MAX_LIST_PAGES = 10
GOOGLE_DOC = "application/vnd.google-apps.document"
GOOGLE_FOLDER = "application/vnd.google-apps.folder"


class ConnectorError(RuntimeError):
    """A provider fetch failed (bad token, missing document, or provider outage)."""


@dataclass
class FetchedDocument:
    """One document read from a provider, ready for governed ingest."""

    title: str
    content: str
    kind: str = "research"
    external_id: str = ""


@dataclass
class FolderEntry:
    """One document in a watched folder, with the provider's modified time."""

    external_id: str
    title: str
    modified: str


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
        if meta.get("mimeType") == GOOGLE_DOC:
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

    def list_folder(self, folder_id: str, access_token: str) -> list[FolderEntry]:
        """Google Docs and plain-text files directly inside the folder."""
        entries: list[FolderEntry] = []
        page_token = ""
        for _ in range(MAX_LIST_PAGES):
            params = {
                "q": f"'{folder_id.replace(chr(39), '')}' in parents and trashed = false",
                "fields": "nextPageToken, files(id,name,mimeType,modifiedTime)",
                "pageSize": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            page = _http_get(
                "https://www.googleapis.com/drive/v3/files", access_token, params=params
            ).json()
            for item in page.get("files", []):
                mime = item.get("mimeType", "")
                if mime == GOOGLE_DOC or mime.startswith("text/"):
                    entries.append(
                        FolderEntry(item["id"], item.get("name", ""), item.get("modifiedTime", ""))
                    )
            page_token = page.get("nextPageToken", "")
            if not page_token:
                break
        return entries


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

    def list_folder(self, folder_id: str, access_token: str) -> list[FolderEntry]:
        """The sub-pages of a Notion page (the page acts as the folder)."""
        headers = {"Notion-Version": NOTION_VERSION}
        entries: list[FolderEntry] = []
        cursor = ""
        for _ in range(MAX_LIST_PAGES):
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            page = _http_get(
                f"https://api.notion.com/v1/blocks/{folder_id}/children",
                access_token,
                headers=headers,
                params=params,
            ).json()
            for block in page.get("results", []):
                if block.get("type") == "child_page":
                    entries.append(
                        FolderEntry(
                            block["id"],
                            block.get("child_page", {}).get("title", ""),
                            block.get("last_edited_time", ""),
                        )
                    )
            cursor = page.get("next_cursor") or ""
            if not page.get("has_more") or not cursor:
                break
        return entries


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

    def list_folder(self, folder_id: str, access_token: str) -> list[FolderEntry]:
        """Files directly inside the OneDrive folder (sub-folders are skipped)."""
        entries: list[FolderEntry] = []
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
        for _ in range(MAX_LIST_PAGES):
            page = _http_get(url, access_token).json()
            for item in page.get("value", []):
                if "folder" in item:
                    continue
                entries.append(
                    FolderEntry(
                        item["id"], item.get("name", ""), item.get("lastModifiedDateTime", "")
                    )
                )
            url = page.get("@odata.nextLink", "")
            if not url:
                break
        return entries


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


def capture_content(payload) -> tuple[str, str]:
    """Content and title for a quick capture (share sheet, clipper, voice note).

    The text is kept as given, with the link appended so the source says where
    it came from. Without a title, the first line (or the link's host and
    path) names it.
    """
    text = (payload.text or "").strip()
    url = (payload.url or "").strip()
    content = f"{text}\n\nSource: {url}" if text and url else text or url
    title = (payload.title or "").strip()
    if len(title) < 3:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first_line and payload.kind != "transcript":
            title = first_line if len(first_line) <= 80 else first_line[:79].rstrip() + "…"
        elif url:
            parts = urlsplit(url)
            title = (parts.netloc + parts.path).rstrip("/")[:120]
    if len(title) < 3:
        label = "Meeting transcript" if payload.kind == "transcript" else "Quick capture"
        title = f"{label} {datetime.now(UTC).date().isoformat()}"
    return content, title[:240]
