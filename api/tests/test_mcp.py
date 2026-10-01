import pytest
from mcp import Client
from sqlalchemy import func, select

from brain.database import SessionLocal
from brain.mcp_server import mcp
from brain.models import Knowledge, Proposal


@pytest.mark.asyncio
async def test_mcp_query_tools_read_only_and_capture_non_approving(client, headers):
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
        names = {tool.name for tool in listed.tools}
        assert names == {
            "ask_brain",
            "brain_status",
            "capture_source",
            "inspect_brain_integrity",
            "list_pending_reviews",
            "search_brain",
        }
        by_name = {tool.name: tool for tool in listed.tools}
        # Query tools are read-only.
        for read_only_name in (
            "ask_brain",
            "brain_status",
            "inspect_brain_integrity",
            "list_pending_reviews",
            "search_brain",
        ):
            assert by_name[read_only_name].annotations.read_only_hint is True
        # Capture is intake (writes proposal rows) but cannot approve.
        assert by_name["capture_source"].annotations.read_only_hint is False
        # The approval boundary holds: no tool can approve, reject, or mint truth.
        assert not any("approve" in n or "reject" in n or "canonical" in n for n in names)

        result = await mcp_client.call_tool("search_brain", {"query": "coding agents"})

    assert result.is_error is False
    assert result.structured_content["count"] == 1
    assert "only a person" in result.structured_content["items"][0]["statement"]


@pytest.mark.asyncio
async def test_capture_files_proposals_but_never_canonical(client):
    content = (
        "We decided that coding agents capture raw session context into the review "
        "queue as candidate knowledge. A person must still approve each candidate "
        "before it becomes canonical truth that other agents may retrieve and cite."
    )
    async with Client(mcp, raise_exceptions=True) as mcp_client:
        result = await mcp_client.call_tool(
            "capture_source",
            {"title": "Agent session capture", "content": content},
        )
    assert result.is_error is False
    data = result.structured_content
    assert data["status"] == "awaiting_review"
    assert data["proposal_count"] >= 1
    source_id = data["source_id"]
    with SessionLocal() as db:
        canonical = (
            db.scalar(select(func.count(Knowledge.id)).where(Knowledge.source_id == source_id)) or 0
        )
        proposals = (
            db.scalar(select(func.count(Proposal.id)).where(Proposal.source_id == source_id)) or 0
        )
    assert canonical == 0  # capture NEVER writes canonical knowledge
    assert proposals >= 1  # it filed candidates for human review
