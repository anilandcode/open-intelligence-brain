---
name: digital-brain
description: Use when querying the Open Intelligence Brain for approved knowledge, grounded answers, or source citations. Connects via MCP (stdio or HTTP) to the local Brain instance.
---

# Digital Brain — Hermes Skill

Query the Open Intelligence Brain for approved knowledge, grounded answers, and source citations.

## Quick setup

The Brain exposes two MCP transports:

### Stdio (local, recommended)

Add to Hermes `config.yaml`:

```yaml
mcp:
  servers:
    brain:
      command: python
      args: ["-m", "brain.mcp_server"]
      cwd: "/Users/macmini/Projects/Digital Brain/api"
      env:
        BRAIN_DATABASE_URL: "sqlite:///brain.db"
```

### HTTP (remote)

```yaml
mcp:
  servers:
    brain:
      url: "http://localhost:8000/mcp/"
      headers:
        X-Brain-Token: "your-token-here"
```

## Available tools

| Tool | What it does |
|---|---|
| `brain_status` | Overview: source count, knowledge count, pending proposals |
| `search_brain` | Full-text search over canonical knowledge with BM25 ranking |
| `ask_brain` | Ask a question, get a grounded answer with source citations |
| `list_pending_reviews` | Proposals waiting for human approval |
| `inspect_brain_integrity` | Integrity warnings and conflict signals |

## Usage patterns

**Quick fact check:**
> Use the Brain to verify: "What is our churn rate?"

**Source-grounded research:**
> Search the Brain for knowledge about customer onboarding and cite your sources.

**Review queue:**
> What proposals are waiting for approval in the Brain?

## Notes

- All tools are read-only. The Brain never approves proposals through MCP — that stays human-only.
- The Brain must be running (`make dev-api`) for stdio mode to work.
- For HTTP mode, the Brain must be deployed and accessible at the configured URL.
- Workspace isolation is enforced — the token determines which workspace you see.

## Install

```bash
# Copy to Hermes skills directory
cp -r hermes-skill/ ~/.hermes/skills/digital-brain/
```

Or add the MCP server config directly to your Hermes config.yaml.