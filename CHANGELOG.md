# Changelog

## 1.1.1 — Hosted Streamable HTTP MCP

First-party remote MCP comparable in *shape* to hosted MCP products (public
`/mcp` URL + OAuth client connect), while keeping Open Brain invariants:
read-only tools, human approval → canonical, no write-memory authority.

### Hosted MCP

- **`/mcp` Streamable HTTP** (`mcp_hosted.py`) — official MCP transport clients
  can add as `{ "url": "https://<host>/mcp" }`.
- **OAuth 2.1** (`mcp_oauth.py`) — dynamic client registration, authorize,
  paste Brain machine token on consent, PKCE code + refresh. Access/refresh
  tokens and clients stored in SQLAlchemy tables (survive Cloud Run cold starts).
- **Dual Bearer auth** — OAuth-issued tokens **or** raw `brn_live_…` / owner
  token as `Authorization: Bearer` (agents that set headers skip the browser).
- Tools remain the same read-only set (`brain_status`, `search_brain`,
  `ask_brain`, `list_pending_reviews`, `inspect_brain_integrity`), bound to the
  **caller's** workspace/role — never owner-by-default.
- Env: `BRAIN_MCP_HOSTED` (default true), `BRAIN_PUBLIC_BASE_URL` (issuer +
  resource base; set to the Cloud Run HTTPS origin in production).
- Stdio MCP and legacy `/api/v1/mcp/*` remain.
- **`capture_source` intake tool** (stdio + hosted): an agent files raw material
  as a source and candidate proposals for human review. Marked honestly
  `read_only_hint=False` (it writes proposal rows) but strictly non-approving
  and non-canonical — no tool can mint truth. Gated by `sources:write` exactly
  like REST `POST /api/v1/sources`; audit attributes the machine caller.
- **Connection registry** (`mcp_connections` + `GET /api/v1/mcp/connections`):
  which MCP clients have reached a workspace (owner/admin only, telemetry only
  — never a credential). Covers BOTH auth shapes — OAuth-issued clients and
  direct-bearer agents such as Antigravity — with principal, role, call count,
  last-seen and an `active`/`idle`/`expired` status. The console's **Agents &
  MCP** view renders it. User-agent is captured by an outermost ASGI middleware
  so a connection can name its client; principal previews are always
  `token_preview`-masked so a raw secret never lands in the registry.

### Docs / tests

- `docs/agent-integrations.md` documents the three surfaces.
- `api/tests/test_mcp_hosted.py` covers discovery, Bearer tools, and the full
  register → authorize → consent → token exchange path.
- `api/tests/test_mcp_connections.py` covers the connection registry: bearer
  visibility, credential-leak protection, per-client idempotency, admin gate.

## 1.1.0 — Human identity (v1.1, part 1)

First commit of the identity milestone: a real human identity model and the
trust boundary that produces it. Machine credentials keep working exactly as
they did, and identity stays optional.

### Identity

- **`users`**: a person, keyed on `(provider, provider_subject)` — the
  provider's stable external identity. Email is deliberately *not* a key: a
  provider may reassign an address, and keying on it would let a new person
  inherit the old one's memberships.
- **`workspace_members`**: a person's access to one workspace and the role they
  hold. The human counterpart to `workspace_grants` (a machine credential),
  kept as a separate table on purpose — a token is not a person and a person is
  not a token, so an audit trail that conflated them could never say who acted.
- **Identity provider boundary** (`identity.py`): identity is an *assertion from
  an identity provider*, verified before anything is written. Nothing in a
  request body, query parameter, or model output can name a user. A provider
  that fails to verify leaves no trace in `users`, because verification happens
  before the write. Verification failures raise one uninformative message
  (`Sign-in failed`) so the error is not a user-enumeration oracle.
- `VerifiedIdentity` is the only thing that may reach `upsert_user`; a hosted
  provider (Google, Firebase) is a drop-in that returns the same shape, behind
  a one-method `IdentityProvider` protocol.
- Deactivating a person revokes every workspace immediately (`is_active` is
  consulted on every membership read) — no walking the membership table.

### Credential boundary

- `WorkspaceAccess` now records `actor_kind` and `actor_id`, so an audit row can
  say a person acted rather than that a token did. `principal` alone is
  ambiguous: it holds a raw token or a user id depending on which class resolved
  it.
- Pinned by tests in both directions: a `User` row is not sendable in
  `X-Brain-Token`, and a machine token never creates or implies a `User`.
- The machine-token path is byte-for-byte unchanged for existing callers
  (`actor_kind="token"`, `actor_id=None` defaults).

### Optional by construction

With `identity_provider` unset, `get_identity_provider()` returns None and the
whole machine-token surface behaves as before — invariant 10 holds. A typo in
the provider name raises rather than silently disabling login, because an
operator error must be visible and fail closed.

### Login and sessions

- `POST /api/v1/auth/login` exchanges a **provider credential** for a session;
  `POST /api/v1/auth/logout` ends it; `GET /api/v1/auth/me` reports who is
  signed in and what they belong to.
- **The session secret is never stored.** Only its SHA-256 hash is written to
  `user_sessions`, so an export, a backup, or a leaked dump yields no usable
  session. The raw value appears exactly once, in the login response.
- **Sessions and machine tokens travel in different headers** —
  `X-Brain-Session` vs `X-Brain-Token` — and resolve through different tables.
  Neither is accepted where the other belongs, and sending *both* is refused
  rather than silently picking one: a request whose actor is ambiguous is
  exactly what the separation exists to prevent.
- **Login grants identity, not reach.** A sign-in creates a `User` and a
  session but reaches no workspace until `workspace_members` says so. Inviting
  someone and accepting their sign-in are different acts by different people.
- **Revocation is immediate without a session walk.** Reach is resolved per
  request, so dropping a membership or deactivating a person takes effect on
  the next call even though their session rows still exist.
- Login failures are one indistinguishable 401 for an unknown person, a wrong
  credential, and a deployment with no provider configured — the route cannot
  be used to enumerate people or fingerprint which providers are enabled.
- Logout is idempotent and answers 204 even for an unknown secret, so it is not
  a validity probe.

Full suites: **319 passed on SQLite** (28 new), **337 passed on PostgreSQL**.

### Audit attribution

The final v1.1 piece: an audit event says **who** acted, not merely that
something happened.

- `audit_events` gains `actor_kind` and `actor_id`. `user` carries a `users.id`;
  `system` means no caller was resolved; `token` carries only a
  **non-recoverable preview** of the machine credential.
- **The raw token is never written to the audit log.** An audit table that
  stored live credentials would be a credential store with a misleading name,
  and every backup and export of it would leak access. A test asserts the raw
  value appears in no column of any row.
- **Work nobody asked for is not blamed on anyone.** Engine derivation, startup
  backfill, and scheduled routines record `system` rather than inventing a
  human or crediting a token that did not act. Passing `actor=None` is the
  honest answer for those paths.
- The migration is additive and idempotent with a `system` default, so an
  existing audit trail keeps working and — importantly — an old row never
  claims a human that it cannot name.

Full suites: **332 passed on SQLite** (13 new), **350 passed on PostgreSQL**.

### Hosted Postgres (Neon)

- Neon free project `digital-brain` is the hosted database. Connection URL lives
  only in `~/.digital-brain/neon-database-url` (mode 600) and, at deploy time, in
  Secret Manager (`brain-database-url`) — never in git, never in plain Cloud Run
  env vars.
- `scripts/deploy-cloud-run.sh` auto-loads that file and mounts it as
  `BRAIN_DATABASE_URL`. Without it, the image keeps ephemeral `/tmp` SQLite and
  the script warns.
- Live restart proof on Neon 18: capture → approve → new process → search hits +
  grounded chat with citations.
- Secret Manager IAM grants for the runtime SA now **fail the deploy** instead of
  logging a soft note — a green build with a failed revision was the first live
  ship failure mode.

### Hosted engine embeddings

- Bake `Xenova/bge-base-en-v1.5` quantized ONNX into the image at build time
  (`scripts/fetch-embedding-model.sh` → `/opt/engine/models`).
- `engine/entrypoint.sh` seeds `SUPERMEMORY_DATA_DIR/models` from that cache on
  every cold start. Cloud Run's `/tmp` is empty tmpfs; Hugging Face 429 on Google
  egress was the cause of live `degraded: true` / "no model provider" with a
  valid `PROXY_API_KEY`.

## 1.0.2 — Retrieval persistence and PostgreSQL correctness

A PostgreSQL readiness pass found that the default SQLite deployment had been
silently losing its own approved knowledge on every restart since M2. The bug is
fixed on both dialects, PostgreSQL is now genuinely supported rather than
nominally, and the restart is a permanent release gate.

### Critical — search broke after the first restart

- **Ranked search returned nothing once the index was rebuilt (critical, on the
  default database).** `knowledge_fts` was declared `content=''` — a *contentless*
  FTS5 table, which stores no column values. `SELECT knowledge_id` therefore
  returned `NULL` for every row, `search_fts` handed back `[None, None, …]`, and
  that truthy list made `search_knowledge` take the ranked branch, match
  `id IN (NULL)` against nothing, and return `[]` — never reaching the ILIKE
  fallback that would have found the row. Because `rebuild_fts()` runs in
  `lifespan`, the trigger was the *second* boot: capture and approve normally,
  restart, and the Brain could no longer find any of its own canonical knowledge
  while every question abstained. Proven end-to-end before and after the fix
  (`grounded=False, citations=0` → `grounded=True, citations=1`).

  Fixed with three independent guards, because any one alone still leaves a path
  into a silent false abstention: the table is declared with content stored,
  `NULL` ids are filtered out of the ranked list, and ranked ids that resolve to
  zero workspace-visible rows fall through to ILIKE. An existing deployment still
  carrying the old index **self-heals on the next boot**, and stays correct even
  before it does.

- **A test-design failure let it ship.** Unit tests never boot the lifespan, so
  the index stayed empty and a broken index looked identical to a fresh one; and
  `test_retrieval.py` asserted only `len(results) >= 1`, which `[None]` satisfies.
  That assertion now checks the returned identity, and
  `api/tests/test_restart_gate.py` runs the whole lifecycle — create → approve →
  close app → **start it again** → search → grounded answer → citation still
  carries its exact excerpt — as two separate application lifespans in
  subprocesses against one persistent database, on both dialects.

### Index versioning

- `SEARCH_INDEX_VERSION = 2` is persisted in `search_index_state` and compared on
  boot. A deployment whose stored version is behind (or absent) is rebuilt rather
  than trusted, which turns "old index schema silently misbehaves" into "old
  schema detected → rebuild → version recorded". The version is written only
  *after* the rebuild has actually indexed rows.

### PostgreSQL support

PostgreSQL is a first-class database now, not a config value that degraded:

- **Ranked search existed only as SQLite FTS5.** PostgreSQL has no virtual
  tables, so `_ensure_sqlite_fts5` raised; the exception was swallowed without a
  rollback, which **aborted the entire transaction** and made unrelated routes
  500 — `POST /api/v1/chat` failed while GETs kept working, which made a
  search-index problem look like a chat-handler problem. Every failure path now
  rolls back, and PostgreSQL gets its own `to_tsvector` + `ts_rank_cd` path over
  an expression GIN index. Verified in use at scale, not just present: at 5,000
  rows the plan shows `Bitmap Index Scan on knowledge_tsv_idx`, 10/10 needles
  found, ~0.8 ms.
- **Term semantics differed between dialects.** `plainto_tsquery` ANDs its terms
  while FTS5 and the ILIKE fallback OR them, so a multi-word question could
  answer on SQLite and *abstain* on PostgreSQL. Since abstention is this
  product's safety signal, over-abstention is a correctness bug rather than a
  ranking nit; terms are now OR'd on both.
- **`/api/v1/usage` and `/usage/top` 500'd.** `top_used` relied on SQLite's
  `GROUP BY` extension, selecting columns it did not group by; PostgreSQL raises
  `GroupingError`. The functionally dependent columns are now grouped
  explicitly, which cannot change which rows return.
- **Migrations are dialect-aware and safe.** Relaxing `proposal_evidence`'s
  NOT NULL used a table rebuild on both dialects; PostgreSQL now takes the native
  `ALTER COLUMN … DROP NOT NULL`, with no rebuild and no data movement. Idempotent
  across repeated boots, FKs intact.
- **The same rebuild dropped a foreign key on both dialects.** Its DDL re-declared
  only two of three keys, silently losing
  `proposal_evidence.proposal_id → proposals.id` on any legacy upgrade — an
  integrity hole in the audit trail, invisible until something tried to insert an
  orphan. The rebuild now preserves all three, and `test_migration_fks.py` asserts
  the *exact* targets rather than a count, so a future migration that keeps three
  keys but points one at the wrong table still fails.

### CI

- A dedicated `postgres-parity` job runs the whole suite against a real
  PostgreSQL 16 service, with `BRAIN_REQUIRE_POSTGRES_TESTS=1` so a missing or
  misconfigured service **fails the job instead of reporting "14 skipped, green"**.
  Two guard steps assert the service is reachable and that the suite's engine
  dialect really is PostgreSQL, because `conftest` previously hardcoded
  `BRAIN_DATABASE_URL` to SQLite — a step named "full suite against PostgreSQL"
  would have quietly re-run SQLite.
- Full suites: **255 passed on SQLite**, **273 passed on PostgreSQL**, zero
  failures and zero errors, plus 5 frontend tests.

## 1.0.1 — Security hardening

Audited every boundary with live probes against a running server; all eleven
findings fixed and each pinned by a regression test.

### Security

- **Unauthenticated arbitrary file read (critical).** The SPA catch-all joined
  the request path onto `web/dist` without a containment check, and Starlette
  unquotes `%2f` only *after* routing — so `GET /..%2f..%2f.env` with no token
  at all returned the real `.env`, including `BRAIN_OWNER_TOKEN`, and the live
  SQLite database was downloadable in one request. Now resolved paths must stay
  inside `dist`; anything else 404s.
- **MCP HTTP ignored the caller's identity (critical).** `mcp_http` authenticated
  the token and then discarded it, calling tool functions that hardcode owner
  scope over the default workspace. A member token read private atoms the REST
  API correctly withheld, and a token granted only to *another* workspace read
  the default one. Every MCP tool now takes an explicit `ReadScope` and the HTTP
  transport passes the resolved caller's.
- **Export bypassed the sensitivity ceiling.** `export_workspace_data` took a
  bare `workspace_id`, so a member's export contained private sources with full
  content. It now takes a `ReadScope` like every other collection read.
- **Token listing returned raw credentials**, including the owner token. The
  listing now returns a non-recoverable `principal_preview`; the raw string
  appears exactly once, in the creation response.
- **SSRF via `GET /api/v1/evaluation?jev_url=`.** A caller-named URL made the
  server issue 15 outbound POSTs anywhere, including cloud metadata. The URL now
  comes from `BRAIN_JEV_URL` config only, and the endpoint is admin-only.
- **Restore had no admin gate.** `POST /api/v1/restore` and `/restore/preview`
  accepted any member token; both now require `can_administer`.

### Bugs

- **`ask_brain` never worked.** `CitationResult.model_validate(Citation)` raised a
  `ValidationError` on every grounded answer — the flagship MCP tool returned an
  error to every caller. The existing smoke test passed because it called
  `answer_question` directly instead of the tool.
- **`usage_events` was never created on a fresh database.** `brain.usage` was
  imported lazily inside route bodies, after `lifespan`'s `create_all` had
  already run, so `/api/v1/usage`, `/usage/top`, and `/usage/unused` all returned
  HTTP 500. Now imported at module level; a fresh-interpreter test pins it, since
  pytest collection masked the bug.
- **The background worker crashed on its main path.** `_execute_tool` indexed
  `Knowledge` ORM objects as tuples (`top[0]`, `top[4]`) → `TypeError` on every
  investigate turn that actually matched something. It also filtered proposals on
  status `"pending"` when the real vocabulary is `"proposed"`, so it always
  reported zero. The duck-typed worker scope also skipped the sensitivity ladder;
  it now builds a real `ReadScope`.
- **Token `scope` was decorative.** Still true, and now documented as unenforced
  rather than silently promised — see `docs/security.md`.

### Hygiene

- `make lint` was red with 72 ruff findings (unused imports across
  decision/evaluation/routines/worker/services, unsorted import blocks, a blind
  `pytest.raises(Exception)`, a shadowed `Session`). All cleared.
- 32 new regression tests in `api/tests/test_security_regressions.py`, one per
  finding. Every fix was mechanically negated and confirmed to fail its own test.
- 221 backend tests + 5 frontend tests.

## 1.0.0 — All milestones complete

- Held-out evaluation: compare deterministic vs Jev shadow decisions.
- Hermes messaging pairing for routine digest delivery.
- Release packaging script for distribution.
- 189 backend tests + 5 frontend tests.
- All 6 milestones (M1–M6) complete.

## 0.8.0 — Daily routines, usage tracking, MCP smoke tests

- Daily routine digest: pending proposals, stale knowledge, conflicts, recent activity.
- Usage tracking: which knowledge atoms get cited and reused.
- Auto-tracking citations from chat answers.
- MCP smoke tests verifying all 5 tools for Codex/Claude/Hermes.
- 177 backend tests + 5 frontend tests.

## 0.7.0 — Critic pass and payload-bound approval cards

- Critic pass reviews proposals after extraction, flagging evidence gaps, vague language, and type mismatches.
- Critic notes displayed inline on proposal review with severity color-coding.
- Payload-bound approval cards with source excerpt, similar knowledge, and conflict signals.
- 162 backend tests + 5 frontend tests.

## 0.6.0 — Background worker, decision provider, Hermes skill

- Background worker for durable turn processing with lease-based claiming.
- Decision provider interface with deterministic and Jev shadow adapters.
- Hermes skill for one-command Brain connection via MCP.
- Turn lease columns for multi-worker coordination.
- 154 backend tests + 5 frontend tests.

## 0.5.0 — Intelligence Studio

- Interview sessions: create, add questions, submit responses, extract proposals.
- Draft builder: assemble approved knowledge into briefs/articles/agent context.
- Studio API with 13 endpoints under `/api/v1/studio/`.
- Live Studio UI replacing preview: interviews tab, drafts tab, detail views.
- 160 backend tests + 5 frontend tests.

## 0.4.1 — FTS5 search, expiring tokens, MCP HTTP, richer types

- Added SQLite FTS5 full-text search with BM25 ranking, synced after approval/supersession.
- Added scoped grants and expiring tokens with create/list/revoke API.
- Added MCP HTTP adapter with tool listing, call, and SSE endpoints.
- Added framework, evidence, story, and question proposal types.
- Improved conflict detection with same-topic/same-type matching.
- Added 21 new tests (134 backend total, 5 frontend).

## 0.4.0 — Engine, harness, workspaces, and Cloud Run deployment

- Added engine abstraction with `DeterministicEngine` (local, always available) and `SupermemoryEngine` (hosted, optional) implementations.
- Added harness layer: event intake, deterministic triage, and turn orchestration with budgets, steering, suspension, and cooperative cancellation.
- Added workspace isolation with role-based access control (`owner`, `admin`, `member`) and sensitivity scoping (`public`, `internal`, `private`).
- Added proactivity policy per channel (`off`, `mentions`, `contextual`, `proactive`).
- Added database migration support for workspace and engine-link columns.
- Added single-image Dockerfile combining API and frontend for Cloud Run.
- Added Cloud Build configs and deploy scripts for Cloud Run free tier.
- Added self-hosted LLM proxy (`engine/`) with Dockerfile and entrypoint.
- Added 7 new backend test modules covering engine, engine bridge, sensitivity, triage, turns, turns API, and workspaces (113 tests total).
- Added harness, deploy, free-hosting-plan, and supermemory-core-spec documentation.
- Expanded frontend with engine status, triage queue, turn management, and workspace views.
- Added modular CSS architecture (tokens, primitives, shell, system, views, flows, refine).

## 0.3.0 — Intelligence workspace interface

- Rebuilt the React workbench around the research-defined Inbox, Brain, Studio, Activate, Analytics, and Audit model.
- Added a judgment-first master/detail review workspace with canonical editing and exact evidence side by side.
- Added a responsive application shell, clearer knowledge pipeline, richer overview, and mobile navigation.
- Redesigned Brain search, source provenance, revision history, grounded answers, and integrity monitoring.
- Added clearly labeled Studio, Activate, and Analytics previews without presenting unfinished workflows as live.
- Added native dialog behavior, visible focus states, reduced-motion support, forced-colors support, and larger touch targets.
- Expanded frontend coverage to verify live workflows and honest preview labeling.

## 0.2.0 — Durable knowledge

- Added immutable SHA-256-addressed source versions and exact source spans.
- Added proposal-to-span evidence edges.
- Added append-only knowledge revisions and explicit supersession.
- Added stale-source and deterministic possible-conflict integrity reporting.
- Added schema-v2 backup, empty-workspace restore, and deletion previews.
- Added provenance and revision controls to the workbench.
- Added read-only MCP integrity inspection and stale/revision metadata.

## 0.1.0 — Trusted thin slice

- Added source capture, deterministic proposals, human approval, canonical search, cited answers, audit events, JSON export, React workbench, Docker Compose, CI, and read-only MCP tools.