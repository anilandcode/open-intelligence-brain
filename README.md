# Open Intelligence Brain

A local-first, open-source workspace for turning source material into reviewed, reusable intelligence.

The project deliberately separates three layers:

1. **Raw sources** — what a note, interview, or decision record literally contains.
2. **Proposals** — what the extraction process thinks might be useful knowledge.
3. **Canonical knowledge** — exact wording a person has reviewed and approved.

Version 0.2 is a functional vertical slice, not a static mockup. It supports source capture, immutable source versions and exact spans, human review, append-only knowledge revisions, integrity warnings, canonical search, source-grounded answers, tested backup/restore, an audit trail, and a read-only MCP server for coding agents.

## Screens

- Home — metrics, recent approvals, next review, and audit activity.
- Review inbox — edit and approve exact wording beside its original evidence.
- Brain — search canonical knowledge only.
- Sources — inspect hashes and create immutable source versions without overwriting history.
- Ask — get an answer from approved knowledge with exact source citations.

## Quick start

Requirements: Python 3.12+, Node.js 22+, and npm.

```bash
cp .env.example .env
make install
```

Run the API and frontend in two terminals:

```bash
make dev-api
make dev-web
```

Open [http://localhost:5173](http://localhost:5173). The local demo token and seeded synthetic data are enabled by default. Do not reuse the demo token for a remote deployment.

### Docker Compose

```bash
docker compose up --build
```

This starts PostgreSQL, the API at `http://localhost:8000`, and the workbench at `http://localhost:5173`.

## Verify

```bash
make test
make lint
make build
```

Backend API documentation is available at `http://localhost:8000/docs` during development.

### Connect an MCP agent

Run the local stdio server against the same database as the API:

```bash
BRAIN_DATABASE_URL=sqlite:///brain.db .venv/bin/open-brain-mcp
```

It exposes read-only `brain_status`, `search_brain`, `ask_brain`, `list_pending_reviews`, and `inspect_brain_integrity` tools. See [docs/agent-integrations.md](docs/agent-integrations.md) for the portable host configuration and security boundary.

## API workflow

All application endpoints require an `X-Brain-Token` header.

```bash
curl -X POST http://localhost:8000/api/v1/sources \
  -H 'Content-Type: application/json' \
  -H 'X-Brain-Token: local-dev-token' \
  -d '{
    "title": "Project lesson",
    "kind": "note",
    "sensitivity": "private",
    "content": "We learned that evidence should stay attached to every reusable claim. The review step protects the Brain from confident extraction mistakes."
  }'
```

Then review proposals at `/api/v1/proposals`, approve one through `/api/v1/proposals/{id}/approve`, and ask a grounded question at `/api/v1/chat`.

## Repository map

```text
api/                  FastAPI domain and tests
web/                  React + TypeScript workbench
docs/                 Architecture, security, roadmap
docker-compose.yml    PostgreSQL + API + frontend development stack
AGENTS.md             Guardrails for coding agents
```

## What is real and what is still intentionally simple

Implemented:

- SQLite for zero-config local development and PostgreSQL through Compose.
- Persisted sources, proposals, canonical knowledge, and audit events.
- SHA-256-addressed immutable source versions, exact offsets, span hashes, and parser metadata.
- Append-only knowledge revision history and explicit supersession.
- Stale-source and deterministic possible-conflict signals.
- Owner-token protection for every application API.
- Deterministic extraction that works offline and is easy to test.
- Approval boundary and double-approval protection.
- Keyword search and source-grounded answers with abstention.
- Responsive and keyboard-accessible review experience.
- Schema-v2 JSON backup, dry-run preview, empty-workspace restore, and deletion previews.
- Read-only MCP access for Hermes, Codex, Claude Code, and compatible hosts.
- Backend and frontend tests.

Next:

- Local embeddings and hybrid retrieval.
- Guided interview sessions and drafting workflows.
- Client-specific MCP registration examples and compatibility CI.
- Durable background tasks and optional Jev decision adapter.
- Encrypted backup packaging, retention execution, and workspace-level grants.

See [docs/roadmap.md](docs/roadmap.md) for the dependency-ordered plan.
See [docs/operations.md](docs/operations.md) before restoring or planning deletion.

## Privacy

The default profile runs locally and makes no model-provider calls. The seeded content is synthetic. Database files, exports, secrets, and model caches are ignored by Git.

The included authentication is appropriate for a loopback-bound personal demo. Before remote access, add TLS, durable identity, short-lived scoped credentials, CSRF/Origin controls where cookies are used, rate limits, and a reviewed deployment threat model.

## License

Apache-2.0 for original project code. External packages and optional model artifacts keep their own licenses.
