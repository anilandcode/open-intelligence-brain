import pytest
from mcp import Client

from brain.mcp_server import mcp


@pytest.mark.asyncio
async def test_mcp_tools_are_read_only_and_query_canonical_knowledge(client, headers):
    client.post(
        "/api/v1/sources",
        headers=headers,
        json={
            "title": "Agent context",
            "kind": "decision",
            "sensitivity": "private",
            "content": (
                "We decided that coding agents may retrieve approved project context, "
                "but only a person can approve new canonical knowledge."
            ),
        },
    )
    proposal = client.get("/api/v1/proposals", headers=headers).json()[0]
    client.post(
        f"/api/v1/proposals/{proposal['id']}/approve",
        headers=headers,
        json={},
    )

    async with Client(mcp, raise_exceptions=True) as mcp_client:
        listed = await mcp_client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "ask_brain",
            "brain_status",
            "list_pending_reviews",
            "search_brain",
        }
        assert all(tool.annotations.read_only_hint for tool in listed.tools)

        result = await mcp_client.call_tool("search_brain", {"query": "coding agents"})

    assert result.is_error is False
    assert result.structured_content["count"] == 1
    assert "only a person" in result.structured_content["items"][0]["statement"]
