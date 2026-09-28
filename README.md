# Open Intelligence Brain

A local-first, open-source workspace for turning source material into reviewed, reusable intelligence.

The project deliberately separates three layers:

1. **Raw sources** — what a note, interview, or decision record literally contains.
2. **Proposals** — what the extraction process thinks might be useful knowledge.
3. **Canonical knowledge** — exact wording a person has reviewed and approved.

Version 0.4 adds an engine abstraction, a harness layer (event intake, triage, and turn orchestration), workspace isolation with role-based access and sensitivity scoping, and a single-image Cloud Run deployment. The core trust model — nothing becomes canonical without human approval — is unchanged.

## Screens

- Overview — live pipeline health, review priorities, recent knowledge, and clear next actions.
- Inbox — choose a proposal from the queue and edit canonical wording beside its exact evidence.
- Brain — search canonical knowledge, inspect warnings, and create immutable revisions.
- Sources — inspect hashes and create immutable source versions without overwriting history.
- Ask — get an answer from approved knowledge with exact source citations and abstention.
- Audit — inspect integrity signals and recent domain events.
- Studio, Activate, and Analytics — clearly labeled workflow previews for planned milestones.

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

### Cloud Run (free tier)

See [docs/deploy-cloud-run.md](docs/deploy-cloud-run.md). The `Dockerfile` builds a single image serving both the API and the frontend from one origin. Cloud Build configs and a deploy script are included. A live deployment exists at `digital-brain-7wyy76ncea-uc.a.run.app`.

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

### Event intake and turns

Events arrive at `POST /api/v1/events`, are triaged deterministically, and become turns — rows with a budget, a plan, and a gate. Turns can be stepped, steered, suspended, resumed, and stopped. See [docs/harness.md](docs/harness.md) for the full route surface and invariants.

## Repository map

```text
api/                  FastAPI domain, services, and tests
  brain/
    access.py         Workspace resolution, roles, sensitivity scoping
    config.py         Settings from environment
    database.py       SQLAlchemy session and engine
    engine.py         Engine abstraction (deterministic + Supermemory)
    harness.py        Event intake, triage, and turn tables
    main.py           API routes and lifespan
    mcp_server.py     Read-only stdio MCP server
    migrate.py        Additive schema migrations
    models.py         SQLAlchemy models (sources, proposals, knowledge, workspaces)
    schemas.py        Pydantic request/response schemas
    services.py       Domain logic (extraction, approval, search, backup)
    triage.py         Deterministic triage with policy enforcement
    turns.py          Turn orchestration (step, steer, suspend, resume, stop)
  tests/              113 backend tests across 9 modules
web/                  React + TypeScript workbench
  src/
    App.tsx           Main application with all views
    api.ts            API client
    tokens.css        Design tokens
    primitives.css    Base components
    shell.css         App shell and navigation
    system.css        System-level styles
    views.css         View-specific styles
    flows.css         Workflow and flow styles
    refine.css        Refinement and detail styles
  public/
    favicon.svg       App favicon
engine/               Self-hosted LLM proxy (Dockerfile + entrypoint + proxy)
scripts/              Deploy scripts (Cloud Run, engine, fetch)
docs/                 Architecture, security, roadmap, interface, deploy, harness
docker-compose.yml    PostgreSQL + API + frontend development stack
Dockerfile            Single-image build for Cloud Run
cloudbuild.yaml       Cloud Build config (API + frontend)
cloudbuild-engine.yaml  Cloud Build config (engine proxy)
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
- Research-aligned application shell with judgement-first review and honest future-state previews.
- Schema-v2 JSON backup, dry-run preview, empty-workspace restore, and deletion previews.
- Read-only MCP access for Hermes, Codex, Claude Code, and compatible hosts.
- Workspace isolation with role-based access control and sensitivity scoping.
- Engine abstraction with deterministic local and optional hosted Supermemory provider.
- Harness layer: event intake, deterministic triage, turn orchestration with budgets and gates.
- Per-channel proactivity policy.
- Single-image Cloud Run deployment with Cloud Build.
- Self-hosted LLM proxy for engine deployment.
- 113 backend tests and 5 frontend tests.

Next:

- PostgreSQL full-text search and local embeddings with index-version tracking.
- Evaluation-backed conflict detection and review policy.
- Encrypted backup packaging, retention execution, and workspace-level grants.
- Guided interview sessions and drafting workflows (M3 — Intelligence Studio).
- Scoped workspace principals, expiring tokens, and MCP HTTP adapter (M4).
- Durable background tasks and optional Jev decision adapter (M5).

See [docs/roadmap.md](docs/roadmap.md) for the dependency-ordered plan.
See [docs/interface.md](docs/interface.md) for the information architecture and live/preview boundary.
See [docs/operations.md](docs/operations.md) before restoring or planning deletion.

## Privacy

The default profile runs locally and makes no model-provider calls. The seeded content is synthetic. Database files, exports, secrets, and model caches are ignored by Git.

The included authentication is appropriate for a loopback-bound personal demo. Before remote access, add TLS, durable identity, short-lived scoped credentials, CSRF/Origin controls where cookies are used, rate limits, and a reviewed deployment threat model.

## License

Apache-2.0 for original project code. External packages and optional model artifacts keep their own licenses.