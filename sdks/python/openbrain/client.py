"""Open Intelligence Brain Python SDK.

Official Python client for Open Intelligence Brain: local-first governed intelligence
with span verification, conflict radar, bi-temporal history, and immutable provenance.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Self


class BrainError(Exception):
    """Base exception for Open Intelligence Brain SDK errors."""

    def __init__(
        self, message: str, status_code: int | None = None, detail: Any = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class Brain:
    """Client for interacting with Open Intelligence Brain API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        workspace_id: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.workspace_id = workspace_id
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            if query:
                url = f"{url}?{query}"

        req_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "openbrain-python-sdk/2.4.0",
        }
        if self.api_key:
            req_headers["X-Brain-Token"] = self.api_key
        if self.workspace_id:
            req_headers["X-Brain-Workspace"] = self.workspace_id
        if headers:
            req_headers.update(headers)

        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            raw_err = exc.read().decode("utf-8")
            try:
                detail = json.loads(raw_err)
                msg = (
                    detail.get("detail", raw_err)
                    if isinstance(detail, dict)
                    else raw_err
                )
            except (json.JSONDecodeError, ValueError):
                detail = raw_err
                msg = raw_err
            raise BrainError(
                f"HTTP {exc.code}: {msg}", status_code=exc.code, detail=detail
            ) from exc
        except urllib.error.URLError as exc:
            raise BrainError(
                f"Network error connecting to {self.base_url}: {exc.reason}"
            ) from exc

    def health(self) -> dict[str, Any]:
        """Check Brain service health and status."""
        return self._request("GET", "/health/live")

    def add(
        self,
        content: str,
        title: str | None = None,
        kind: str = "note",
        sensitivity: str = "internal",
    ) -> dict[str, Any]:
        """Ingest raw content into Brain as an immutable source with span extraction.

        Args:
            content: Raw text content to ingest.
            title: Title for the source. Defaults to opening line or timestamp.
            kind: Source kind ("note", "decision", "interview", "conversation").
            sensitivity: Access sensitivity ("public", "internal", "restricted").
        """
        payload = {
            "content": content,
            "title": title or (content.strip().split("\n")[0][:60] or "Captured Note"),
            "kind": kind,
            "sensitivity": sensitivity,
        }
        return self._request("POST", "/api/v1/sources", data=payload)

    def deletion_preview(self, source_id: str) -> dict[str, Any]:
        """Preview deletion of a source and check for canonical dependencies."""
        return self._request("GET", f"/api/v1/sources/{source_id}/deletion-preview")

    def delete_source(self, source_id: str) -> dict[str, Any]:
        """Execute reviewed deletion of a source (blocked if canonical knowledge depends on it)."""
        return self._request("DELETE", f"/api/v1/sources/{source_id}")

    def search(
        self,
        query: str = "",
        limit: int = 20,
        as_of: datetime | str | None = None,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        """Search canonical knowledge using hybrid BM25 and vector retrieval.

        Args:
            query: Keyword or conceptual query. Empty returns latest knowledge.
            limit: Maximum items to return.
            as_of: Bi-temporal time-travel filter: retrieve facts valid on this date.
            include_superseded: Whether to include historically superseded facts.
        """
        as_of_str = as_of.isoformat() if isinstance(as_of, datetime) else as_of
        params = {
            "q": query,
            "limit": limit,
            "as_of": as_of_str,
            "include_superseded": str(include_superseded).lower()
            if include_superseded
            else None,
        }
        return self._request("GET", "/api/v1/knowledge", params=params)

    def ask(self, question: str) -> dict[str, Any]:
        """Ask a grounded question against canonical knowledge.

        Returns:
            dict containing "answer", "citations", and "grounded" flag.
        """
        return self._request("POST", "/api/v1/chat", data={"question": question})

    def proposals(self, status: str = "proposed") -> list[dict[str, Any]]:
        """List proposals awaiting human review or resolution."""
        return self._request("GET", "/api/v1/proposals", params={"status": status})

    def approve(
        self,
        proposal_id: str,
        statement: str | None = None,
        rationale: str | None = None,
        supersedes_knowledge_id: str | None = None,
        valid_from: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Approve a proposal to become canonical knowledge.

        Args:
            proposal_id: The proposal to approve.
            statement: Optional edited statement. Defaults to proposal statement.
            rationale: Optional updated rationale.
            supersedes_knowledge_id: Optional ID of existing knowledge item superseded by this.
            valid_from: Bi-temporal start timestamp in the real world.
        """
        v_from_str = (
            valid_from.isoformat() if isinstance(valid_from, datetime) else valid_from
        )
        payload = {
            "statement": statement,
            "rationale": rationale,
            "supersedes_knowledge_id": supersedes_knowledge_id,
            "valid_from": v_from_str,
        }
        return self._request(
            "POST", f"/api/v1/proposals/{proposal_id}/approve", data=payload
        )

    def batch_approve(self, proposal_ids: list[str]) -> dict[str, Any]:
        """Batch approve multiple proposals in one call."""
        return self._request(
            "POST",
            "/api/v1/proposals/batch-approve",
            data={"proposal_ids": proposal_ids},
        )

    def reject(
        self, proposal_id: str, reason: str = "Rejected by reviewer"
    ) -> dict[str, Any]:
        """Reject a proposed candidate fact."""
        return self._request(
            "POST", f"/api/v1/proposals/{proposal_id}/reject", data={"reason": reason}
        )

    def batch_reject(
        self, proposal_ids: list[str], reason: str = "Batch rejected"
    ) -> dict[str, Any]:
        """Batch reject multiple proposals in one call."""
        return self._request(
            "POST",
            "/api/v1/proposals/batch-reject",
            data={"proposal_ids": proposal_ids, "reason": reason},
        )

    def history(self, knowledge_id: str) -> list[dict[str, Any]]:
        """Retrieve the immutable revision history for a canonical knowledge atom."""
        return self._request("GET", f"/api/v1/knowledge/{knowledge_id}/revisions")

    def graph(self, include_superseded: bool = False) -> dict[str, Any]:
        """Fetch the knowledge graph nodes and edges."""
        return self._request(
            "GET",
            "/api/v1/graph",
            params={
                "include_superseded": str(include_superseded).lower()
                if include_superseded
                else None
            },
        )

    def reindex(self) -> dict[str, Any]:
        """Trigger reindexing of vector embeddings and full-text search."""
        return self._request("POST", "/api/v1/knowledge/reindex")

    def get_policy(self, workspace_slug: str = "default") -> dict[str, Any]:
        """Get the deterministic auto-approval policy for a workspace."""
        return self._request("GET", f"/api/v1/workspaces/{workspace_slug}/policy")

    def update_policy(
        self, workspace_slug: str = "default", **kwargs: Any
    ) -> dict[str, Any]:
        """Update the auto-approval policy for a workspace."""
        return self._request(
            "PUT", f"/api/v1/workspaces/{workspace_slug}/policy", data=kwargs
        )

    def export_backup(self, passphrase: str | None = None) -> dict[str, Any]:
        """Export a full workspace backup, optionally encrypted with a passphrase."""
        params = {"passphrase": passphrase} if passphrase else None
        return self._request("GET", "/api/v1/export", params=params)

    def preview_restore(
        self, backup_data: dict[str, Any], passphrase: str | None = None
    ) -> dict[str, Any]:
        """Preview restoration of a backup archive into the workspace."""
        headers = {"X-Brain-Encryption-Passphrase": passphrase} if passphrase else None
        return self._request(
            "POST", "/api/v1/restore/preview", data=backup_data, headers=headers
        )

    def restore_backup(
        self, backup_data: dict[str, Any], passphrase: str | None = None
    ) -> dict[str, Any]:
        """Restore a backup archive into the workspace (requires empty workspace)."""
        headers = {"X-Brain-Encryption-Passphrase": passphrase} if passphrase else None
        return self._request(
            "POST", "/api/v1/restore", data=backup_data, headers=headers
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass
