"""HTTP client for the mcp-auth-bridge control plane (OAuth + tool broker).

Open Brain is the bridge's first-party caller: it authenticates with a static
service token and asserts the user id it has already verified through its own
sign-in (the launch-auth model documented in the bridge's control_plane.py).
No bridge credential ever reaches a response body or an audit row.
"""

from __future__ import annotations

from typing import Any

import httpx


class BridgeError(RuntimeError):
    """The bridge refused or failed a call."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"bridge_error:{code}")
        self.status = status
        self.code = code


class BridgeClient:
    def __init__(self, base_url: str, service_token: str, timeout: float = 20.0) -> None:
        self._base = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self._base}{path}",
                headers=self._headers(),
                timeout=self._timeout,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise BridgeError(502, "bridge_unreachable") from exc
        if response.status_code >= 400:
            try:
                code = str(response.json().get("error", "bridge_error"))
            except ValueError:
                code = "bridge_error"
            raise BridgeError(response.status_code, code)
        return response.json()

    def list_accounts(self, user_id: str) -> list[dict[str, Any]]:
        payload = self._call("GET", "/v1/connected_accounts", params={"user_id": user_id})
        accounts = payload.get("accounts", [])
        return list(accounts) if isinstance(accounts, list) else []

    def start_link(
        self, *, user_id: str, toolkit_slug: str, alias: str, redirect_uri: str
    ) -> dict[str, Any]:
        result = self._call(
            "POST",
            "/v1/connected_accounts/link",
            json={
                "user_id": user_id,
                "toolkit_slug": toolkit_slug,
                "alias": alias,
                "redirect_uri": redirect_uri,
            },
        )
        return dict(result)

    def complete_auth(self, *, session_uri: str, user_id: str) -> dict[str, Any]:
        result = self._call(
            "POST",
            "/v1/connected_accounts/complete_auth",
            json={"session_uri": session_uri, "user_id": user_id},
        )
        return dict(result)

    def rename_alias(self, account_id: str, alias: str) -> None:
        self._call("PATCH", f"/v1/connected_accounts/{account_id}", json={"alias": alias})

    def call_tool(
        self, *, user_id: str, pinned_aliases: list[str], tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute one tool call for the user inside a pinned MCP session."""
        session = self._call(
            "POST",
            "/v1/mcp_sessions",
            json={"user_id": user_id, "pinned_aliases": pinned_aliases},
        )
        session_id = str(session.get("session_id", ""))
        if not session_id:
            raise BridgeError(502, "bridge_session_missing")
        result = self._call(
            "POST",
            f"/mcp/s/{session_id}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        if isinstance(result, dict) and result.get("error"):
            error = result["error"]
            raise BridgeError(int(error.get("code", 400)), str(error.get("message", "tool_error")))
        return dict(result)
