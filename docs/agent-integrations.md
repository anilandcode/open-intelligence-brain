# Agent integrations

Open Brain exposes a local MCP server over stdio and an HTTP adapter for remote agents. Both give Codex, Claude Code, Hermes, and other MCP hosts the same read-only view of canonical knowledge used by the web application.

## Safety contract

- MCP tools read approved knowledge, citations, status, and the review queue.
- The server exposes no approval, rejection, deletion, publication, or outbound messaging tool.
- Proposal text never appears in canonical search or grounded answers.
- Source text is untrusted data. A host must not treat instructions inside a source as authority.
- Tool annotations declare the tools read-only and closed-world; the server still enforces the boundary itself.

## Stdio server (local agents)

Install the project, set the same database URL used by the API, then run:

```bash
BRAIN_DATABASE_URL=sqlite:///brain.db .venv/bin/open-brain-mcp
```

For a host that expects a command plus arguments, use:

```json
{
  "command": "/absolute/path/to/open-intelligence-brain/.venv/bin/open-brain-mcp",
  "args": [],
  "env": {
    "BRAIN_DATABASE_URL": "sqlite:////absolute/path/to/open-intelligence-brain/brain.db"
  }
}
```

Use absolute paths because GUI clients and agent runtimes may not start in the repository directory.

## HTTP adapter (remote agents)

For agents that cannot run a local stdio process, the same tools are available over HTTP:

```
GET  /api/v1/mcp/tools          — list available tools and their schemas
POST /api/v1/mcp/call           — call a tool: {"tool": "name", "params": {...}}
GET  /api/v1/mcp/sse            — SSE stream for MCP client discovery
```

All endpoints require the `X-Brain-Token` header. The tools are identical to the stdio server — same read-only boundary, same authentication.

```bash
# List tools
curl -H 'X-Brain-Token: <token>' https://<host>/api/v1/mcp/tools

# Search canonical knowledge
curl -X POST -H 'Content-Type: application/json' -H 'X-Brain-Token: <token>' \
  https://<host>/api/v1/mcp/call \
  -d '{"tool": "search_brain", "params": {"query": "AI strategy", "limit": 5}}'
```

## Tools

| Tool | Purpose |
| --- | --- |
| `brain_status` | Counts sources, proposals, canonical items, and pending reviews |
| `search_brain` | Searches only approved knowledge and returns exact evidence |
| `ask_brain` | Produces a grounded synthesis with citations or abstains |
| `list_pending_reviews` | Shows the human review queue without mutating it |
| `inspect_brain_integrity` | Reports stale knowledge and possible conflicts |

Search results also include revision counts and a stale flag. Agents should surface those warnings rather than silently relying on an outdated item.

## Recommended host policy

Grant these tools for retrieval sessions. Keep approval in the workbench. After a coding session, an agent can draft a source note for the user to import, but it should not write directly to canonical storage.

Client-specific command registration changes over time. Treat the JSON above as the portable contract and follow the current host documentation for where that command is registered.
