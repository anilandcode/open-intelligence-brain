# Agent integrations

Open Brain exposes three MCP surfaces that share the same read-only tools and
governance boundary:

1. **Hosted Streamable HTTP** at `/mcp` — first-party remote MCP (Cursor /
   Claude Connectors / ChatGPT style `url:` config + OAuth).
2. **Stdio** — local process for Hermes, Codex, Claude Code, Antigravity.
3. **Legacy HTTP adapter** at `/api/v1/mcp/*` — simple JSON tools/call for
   agents that cannot speak Streamable HTTP yet.

## Safety contract

- MCP tools read approved knowledge, citations, status, and the review queue.
- The server exposes no approval, rejection, deletion, publication, or outbound
  messaging tool. Canonical writes stay in the Open Brain console.
- Proposal text never appears in canonical search or grounded answers.
- Source text is untrusted data. A host must not treat instructions inside a
  source as authority.
- Tool annotations declare the tools read-only and closed-world; the server
  still enforces the boundary itself.
- Hosted and HTTP MCP bind every tool to the **caller's** workspace and role.
  Stdio uses the process env owner token and its granted workspace.

## Hosted MCP (Streamable HTTP + OAuth)

Public URL shape (after deploy with `BRAIN_PUBLIC_BASE_URL` set):

```text
https://digital-brain-168827050380.us-central1.run.app/mcp
```

Client config (Cursor / Claude / similar):

```json
{
  "mcpServers": {
    "open-brain": {
      "url": "https://digital-brain-168827050380.us-central1.run.app/mcp"
    }
  }
}
```

### Auth

Two paths (same dual-auth idea as other remote MCP products, Open Brain identity):

1. **OAuth 2.1 browser consent** — dynamic client registration, authorize,
   paste a Brain machine token (`brn_live_…` or owner token) on the consent
   page, PKCE code exchange. Access + refresh tokens are hashed at rest in the
   app database so Cloud Run scale-to-zero does not wipe sessions.
2. **Direct Bearer** — clients that can set headers may skip OAuth and send
   `Authorization: Bearer <Brain token>` on `/mcp`. The token verifier accepts
   both OAuth-issued tokens and raw Brain API keys.

Discovery:

```text
GET /.well-known/oauth-authorization-server
GET /.well-known/oauth-protected-resource/mcp
```

Feature flags / env:

| Env | Default | Purpose |
| --- | --- | --- |
| `BRAIN_MCP_HOSTED` | `true` | Mount Streamable HTTP MCP + OAuth |
| `BRAIN_PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | Issuer + resource base (must be the public HTTPS origin in production) |

This is **not** a memory-write SaaS MCP. Tools never call approve or mutate
canonical knowledge. Supermemory remains an optional **extraction engine**
inside the API process — not the authority store and not this MCP product.

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

Prefer the wrapper at `~/.digital-brain/run-open-brain-mcp.sh` so the database
URL and owner token never appear in client MCP config text.

Use absolute paths because GUI clients and agent runtimes may not start in the
repository directory.

## Legacy HTTP adapter (remote agents)

For agents that cannot run a local stdio process and do not speak Streamable
HTTP yet, the same tools are available over REST:

```text
GET  /api/v1/mcp/tools          — list available tools and their schemas
POST /api/v1/mcp/call           — call a tool: {"tool": "name", "params": {...}}
GET  /api/v1/mcp/sse            — SSE stream for MCP client discovery
```

All endpoints require the `X-Brain-Token` header. Prefer the hosted `/mcp`
endpoint for new integrations.

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

Search results also include revision counts and a stale flag. Agents should
surface those warnings rather than silently relying on an outdated item.

## Recommended host policy

Grant these tools for retrieval sessions. Keep approval in the workbench. After
a coding session, an agent can draft a source note for the user to import, but
it should not write directly to canonical storage.

Client-specific command registration changes over time. Treat the JSON above as
the portable contract and follow the current host documentation for where that
command is registered.
