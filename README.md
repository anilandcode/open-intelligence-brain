# Open Intelligence Brain

A local-first, open-source workspace for turning source material into reviewed, reusable intelligence.

The project deliberately separates three layers:

1. **Raw sources** — what a note, interview, or decision record literally contains.
2. **Proposals** — what the extraction process thinks might be useful knowledge.
3. **Canonical knowledge** — exact wording a person has reviewed and approved.

The current release is a functional vertical slice, not a static mockup. It supports source capture, deterministic extraction, human review, canonical search, source-grounded answers, an audit trail, portable JSON export, and a read-only MCP server for coding agents.

## Screens

- Home — metrics, recent approvals, next review, and audit activity.
- Review inbox — edit and approve exact wording beside its original evidence.
- Brain — search canonical knowledge only.
- Sources — inspect imported original material and extraction counts.
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

It exposes read-only `brain_status`, `search_brain`, `ask_brain`, and `list_pending_reviews` tools. See [docs/agent-integrations.md](docs/agent-integrations.md) for the portable host configuration and security boundary.

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
- Owner-token protection for every application API.
- Deterministic extraction that works offline and is easy to test.
- Approval boundary and double-approval protection.
- Keyword search and source-grounded answers with abstention.
- Responsive and keyboard-accessible review experience.
- Portable, versioned JSON export.
- Read-only MCP access for Hermes, Codex, Claude Code, and compatible hosts.
- Backend and frontend tests.

Next:

- Immutable source versions and fine-grained source spans.
- Local embeddings and hybrid retrieval.
- Guided interview sessions and drafting workflows.
- Client-specific MCP registration examples and compatibility CI.
- Durable background tasks and optional Jev decision adapter.
- Backup/restore commands, deletion previews, and workspace-level grants.

See [docs/roadmap.md](docs/roadmap.md) for the dependency-ordered plan.

## Privacy

The default profile runs locally and makes no model-provider calls. The seeded content is synthetic. Database files, exports, secrets, and model caches are ignored by Git.

The included authentication is appropriate for a loopback-bound personal demo. Before remote access, add TLS, durable identity, short-lived scoped credentials, CSRF/Origin controls where cookies are used, rate limits, and a reviewed deployment threat model.

## License

Apache-2.0 for original project code. External packages and optional model artifacts keep their own licenses.
