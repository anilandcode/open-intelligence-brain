# Open Intelligence Brain

A local-first, open-source workspace for turning source material into reviewed, reusable intelligence.

The project deliberately separates three layers:

1. **Raw sources** — what a note, interview, or decision record literally contains.
2. **Proposals** — what the extraction process thinks might be useful knowledge.
3. **Canonical knowledge** — exact wording a person has reviewed and approved.

- Version 1.0 — all milestones complete. Daily routines, usage tracking, held-out evaluation, Hermes messaging, and release packaging. The Brain is ready for personal beta across all your AI tools.

## Screens

- Overview — live pipeline health, review priorities, recent knowledge, and clear next actions.
- Inbox — choose a proposal from the queue and edit canonical wording beside its exact evidence.
- Brain — search canonical knowledge, inspect warnings, and create immutable revisions.
- Sources — inspect hashes and create immutable source versions without overwriting history.
- Ask — get an answer from approved knowledge with exact source citations and abstention.
- Audit — inspect integrity signals and recent domain events.
- Studio — guided interviews and draft builder (live).
- Activate, and Analytics — clearly labeled workflow previews for planned milestones.

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
    models.py          SQLAlchemy models (sources, proposals, knowledge, workspaces, users)
    identity.py        Identity provider boundary: users, workspace_members, verified assertions
    schemas.py         Pydantic request/response schemas
    services.py        Domain logic (extraction, approval, search, backup)
    retrieval.py       Dialect-aware ranked search (FTS5 / tsvector GIN) + index versioning
    mcp_http.py        MCP HTTP transport (binds the caller's ReadScope into tools)
    studio.py         Interview session and draft data models
    studio_api.py     Intelligence Studio API (interviews, drafts, sections)
    studio_schemas.py Pydantic schemas for Studio
    triage.py         Deterministic triage with policy enforcement
    turns.py          Turn orchestration (step, steer, suspend, resume, stop)
    worker.py         Background worker for durable turn processing
    decision.py       Decision provider interface (deterministic + Jev shadow)
    critic.py         Critic pass: evidence gap detection and quality signals
    routines.py       Daily routine digests and delivery
    usage.py          Knowledge usage tracking and analytics
    evaluation.py     Held-out evaluation for Jev promotion decisions
    messaging.py       Hermes messaging pairing for digest delivery
  tests/              255 backend tests across 21 modules (273 against PostgreSQL)
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
hermes-skill/         Hermes skill for one-command MCP connection
docs/                 Architecture, security, roadmap, interface, deploy, harness
docker-compose.yml    PostgreSQL + API + frontend development stack
Dockerfile            Single-image build for Cloud Run
cloudbuild.yaml       Cloud Build config (API + frontend)
cloudbuild-engine.yaml  Cloud Build config (engine proxy)
AGENTS.md             Guardrails for coding agents
```

## What is real and what is still intentionally simple

Implemented:

- SQLite for zero-config local development and PostgreSQL through Compose. Both dialects run the same suite on every push (SQLite locally, PostgreSQL 16 in a CI service job).
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
- Critic pass: evidence gap detection, vague language, type mismatches, weak sourcing.
- Payload-bound approval cards with inline critic notes and severity color-coding.
- Background worker for durable turn processing with lease-based claiming.
- Decision provider interface with deterministic and Jev shadow adapters.
- Hermes skill for one-command Brain connection via MCP.
- Daily routine digests with pending proposals, stale knowledge, conflicts.
- Usage tracking: which knowledge atoms get cited and reused.
- MCP smoke tests verifying all 5 tools for Codex/Claude/Hermes.
- Held-out evaluation for comparing deterministic vs Jev shadow decisions.
- Hermes messaging pairing for routine digest delivery.
- Release packaging script for distribution.
- Intelligence Studio: guided interview sessions and draft builder.
- Interview responses auto-extract into proposals after completion.
- Drafts assemble approved knowledge into briefs/articles/agent context with citations.
- Dialect-aware ranked search over canonical knowledge: SQLite FTS5/BM25 and PostgreSQL `tsvector` + `ts_rank_cd` over an expression GIN index, OR-term query semantics on both so the same question abstains or answers the same way either way. A versioned index (`SEARCH_INDEX_VERSION`) rebuilds itself when the schema it was built with is stale.
- Scoped workspace grants and expiring tokens with create/list/revoke API.
- MCP HTTP adapter for remote agents (tool listing, call, SSE).
- Richer proposal types: framework, evidence, story, question.
- Improved conflict detection with same-topic/same-type matching.
- Security hardening (v1.0.1): static-file containment, MCP scope binding, export/usage sensitivity ceiling, token previews, SSRF-free evaluation config, admin-gated restore — each pinned by a regression test.
- Retrieval persistence and PostgreSQL correctness (v1.0.2): search broke after the first restart on SQLite (contentless FTS5 returned NULL ids and shadowed the fallback) — fixed, plus PostgreSQL ranked search, transaction rollback safety, standard `GROUP BY`, FK-preserving migrations — each pinned, and a restart release gate on both dialects.
- 255 backend tests (273 against PostgreSQL) and 5 frontend tests.

Next:

- Local embeddings and a fused full-text + vector retrieval path (PostgreSQL full-text and index-version tracking landed in v1.0.2).
- Evaluation-backed conflict detection and review policy.
- Encrypted backup packaging, retention execution, and workspace-level grants.
- Four-week personal usage study.
- Enterprise tenancy, automatic publishing, broad connectors.

See [docs/roadmap.md](docs/roadmap.md) for the dependency-ordered plan.
See [docs/interface.md](docs/interface.md) for the information architecture and live/preview boundary.
See [docs/operations.md](docs/operations.md) before restoring or planning deletion.

## Privacy

The default profile runs locally and makes no model-provider calls. The seeded content is synthetic. Database files, exports, secrets, and model caches are ignored by Git.

The included authentication is appropriate for a loopback-bound personal demo. Before remote access, add TLS, durable identity, short-lived scoped credentials, CSRF/Origin controls where cookies are used, rate limits, and a reviewed deployment threat model.

## License

Apache-2.0 for original project code. External packages and optional model artifacts keep their own licenses.