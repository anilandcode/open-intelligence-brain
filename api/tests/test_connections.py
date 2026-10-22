"""Connections hub + staged action queue: the Open Brain side of the bridge.

The bridge is stubbed at the client seam so these tests pin Open Brain's own
contract: 503 when the bridge is not configured, credential-free connection
reads, exactly-once approval, 404 for foreign/unknown rows (never 403), and
the URN recorded on the executed row.
"""

from __future__ import annotations

from typing import Any

from brain import connections_api


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_accounts(self, user_id: str) -> list[dict[str, Any]]:
        self.calls.append(("list", {"user_id": user_id}))
        return [
            {
                "connected_account_id": "cac_1",
                "toolkit_slug": "x",
                "alias": "personal-x",
                "provider_account_id": "x-user-1",
                "display_name": "anil",
                "status": "ACTIVE",
                "expires_at": None,
                "access_token": "REDACTED",
            }
        ]

    def start_link(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("link", kwargs))
        return {"authorization_url": "https://mock.example/authorize", "session_uri": "su_1"}

    def complete_auth(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("verify", kwargs))
        return {"connected_account_id": "cac_1", "status": "ACTIVE"}

    def rename_alias(self, account_id: str, alias: str) -> None:
        self.calls.append(("rename", {"account_id": account_id, "alias": alias}))

    def set_app_credentials(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set_app_credentials", kwargs))
        return {
            "toolkit_slug": kwargs["toolkit_slug"],
            "client_id": kwargs["client_id"],
            "environment": kwargs.get("environment", "production"),
            "saved": True,
        }

    def call_tool(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("call_tool", kwargs))
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": '{"data": {"id": "urn:li:share:abc123"}}'}],
                "isError": False,
            },
        }


def _use_fake(monkeypatch: Any) -> FakeBridge:
    fake = FakeBridge()
    monkeypatch.setattr(connections_api, "get_bridge", lambda: fake)
    return fake


def test_bridge_not_configured_is_503(client, headers) -> None:  # type: ignore[no-untyped-def]
    # No BRAIN_MAB_* in the test environment: the surface stays offline.
    response = client.get("/api/v1/connections", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "bridge_not_configured"


def test_connections_list_is_credential_free(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = _use_fake(monkeypatch)
    response = client.get("/api/v1/connections", headers=headers)
    assert response.status_code == 200
    body = response.text
    assert "REDACTED" not in body or "credential_state" in body
    assert "access_token" not in body
    item = response.json()[0]
    assert item["alias"] == "personal-x"
    assert item["credential_state"] == "present"
    assert fake.calls[0][0] == "list"


def test_link_start_and_verify_redeem(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = _use_fake(monkeypatch)
    response = client.post(
        "/api/v1/connections/link",
        headers=headers,
        json={"toolkit_slug": "x", "alias": "work-x"},
    )
    assert response.status_code == 200
    assert response.json()["session_uri"] == "su_1"
    link_call = fake.calls[0][1]
    assert link_call["alias"] == "work-x"
    assert link_call["user_id"].startswith(("user:", "token:"))

    response = client.post("/api/v1/oauth/verify", headers=headers, json={"session_uri": "su_1"})
    assert response.status_code == 200
    assert response.json() == {"connected_account_id": "cac_1", "status": "ACTIVE"}
    assert fake.calls[1][1]["session_uri"] == "su_1"


def test_staged_approval_executes_exactly_once(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = _use_fake(monkeypatch)
    response = client.post(
        "/api/v1/staged-actions",
        headers=headers,
        json={
            "tool_name": "X_CREATE_POST",
            "account_alias": "personal-x",
            "payload": {"text": "hello"},
        },
    )
    assert response.status_code == 201
    action = response.json()
    assert action["status"] == "PENDING"

    response = client.post(f"/api/v1/staged-actions/{action['id']}/approve", headers=headers)
    assert response.status_code == 200
    executed = response.json()
    assert executed["status"] == "EXECUTED"
    assert executed["result_urn"] == "urn:li:share:abc123"

    # A second approve can never fire the post again.
    response = client.post(f"/api/v1/staged-actions/{action['id']}/approve", headers=headers)
    assert response.status_code == 409
    tool_calls = [c for c in fake.calls if c[0] == "call_tool"]
    assert len(tool_calls) == 1
    assert tool_calls[0][1]["arguments"]["account"] == "personal-x"


def test_reject_then_approve_conflicts(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake(monkeypatch)
    action = client.post(
        "/api/v1/staged-actions",
        headers=headers,
        json={
            "tool_name": "LINKEDIN_CREATE_POST",
            "account_alias": "personal-li",
            "payload": {"text": "hi"},
        },
    ).json()
    response = client.post(f"/api/v1/staged-actions/{action['id']}/reject", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    response = client.post(f"/api/v1/staged-actions/{action['id']}/approve", headers=headers)
    assert response.status_code == 409


def test_unknown_action_is_404_never_403(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake(monkeypatch)
    response = client.post("/api/v1/staged-actions/sta_missing/approve", headers=headers)
    assert response.status_code == 404


def test_app_credentials_save_never_echoes_the_secret(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = _use_fake(monkeypatch)
    response = client.put(
        "/api/v1/connections/app-credentials",
        headers=headers,
        json={
            "toolkit_slug": "x",
            "client_id": "real-x-client",
            "client_secret": "shh-secret",
            "environment": "production",
            "scopes": "tweet.read tweet.write",
        },
    )
    assert response.status_code == 200
    assert "shh-secret" not in response.text
    call = fake.calls[-1]
    assert call[0] == "set_app_credentials"
    assert call[1]["client_id"] == "real-x-client"
    assert call[1]["environment"] == "production"
    assert call[1]["scopes"] == "tweet.read tweet.write"


def test_app_config_returns_the_broker_redirect_uri(client, headers) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/connections/app-config", headers=headers)
    assert response.status_code == 200
    assert response.json()["redirect_uri"].endswith("/oauth/callback")


def test_unknown_tool_is_not_staged(client, headers, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake(monkeypatch)
    response = client.post(
        "/api/v1/staged-actions",
        headers=headers,
        json={"tool_name": "BRAIN_SEARCH", "account_alias": "personal-x", "payload": {}},
    )
    assert response.status_code == 400
