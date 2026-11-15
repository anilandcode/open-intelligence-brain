# Dependency-ordered roadmap

## v1.1 — hosted identity and persistence (done)

- [x] `users` + `workspace_members` and the identity provider boundary
      (`identity.py`): identity is a verified provider assertion, never a
      request field. Human and machine credentials are separate classes.
- [x] Human login and session handling (`sessions.py`, `auth_api.py`):
      `X-Brain-Session` for people, `X-Brain-Token` unchanged for agents.
      Session secrets stored hashed only. Identity never comes from model
      output.
- [x] Audit events attributed to a caller (`actor_kind` / `actor_id` on
      `audit_events`): a human is named by `users.id`, a machine token only by a
      non-recoverable preview, unattributed work records `system`. Raw credentials
      never land in the audit table.
- [x] Persistent PostgreSQL as the hosted default: Neon free project
      `digital-brain` (id `ancient-queen-28972054`), restart proof against live
      Neon (`grounded=True` after reconnect), deploy script loads
      `~/.digital-brain/neon-database-url` into Secret Manager as
      `BRAIN_DATABASE_URL`. Local dev still defaults to SQLite; Compose still
      ships local Postgres 16.
- [x] Hashed machine API credentials (`api_credentials` + scopes):
      `brn_live_…` secrets returned once, stored as SHA-256 only; soft-revoke;
      `require_scope` on write/admin routes. Bootstrap owner token remains a
      legacy `workspace_grants` principal for one release (emergency unlock).
- [x] Firebase identity provider (`identity_provider=firebase` +
      `identity_firebase_project_id`); optional `google-auth` extra. Web gate
      offers human sign-in when `/api/v1/auth/status` reports a provider, and
      still accepts machine token paste.
- [x] Wire Google / Firebase sign-in on the hosted console (`web/src/google-signin.ts`)
      with fallback to token paste or `local` provider for dev.
- [x] First-owner bootstrap (`POST /api/v1/auth/bootstrap` in `auth_api.py` and
      console claim flow): auto-membership for the first verified human when
      a workspace has zero human owners.
- [x] Hosted Streamable HTTP MCP at `/mcp` with OAuth 2.1 paste-token consent
      and dual Bearer (OAuth token or raw Brain API key). Read-only tools only;
      approval stays in the console. `BRAIN_PUBLIC_BASE_URL` for issuer/resource.
- [x] MCP connection registry (`GET /api/v1/mcp/connections` + console
      **Agents & MCP** view): see which clients reached a workspace across both
      auth shapes, with last-seen/status and no credential exposure.

## v1.2 — context-stack port (Supermemory reference)

Capability gaps filled by porting Supermemory's stack into the governed
proposal→approve→canon model (never their auto-memory-write product):

- Hybrid retrieval (vector + keyword, reciprocal-rank fusion) — done.
- Knowledge graph (`GET /api/v1/graph` + console Brain Graph) — done.
- Richer extraction (semantic chunking + summarize/tag on proposals) — done.
- Connectors (Drive/Notion/OneDrive fetch → review) — done.

## v2.0 – v2.4 — Enterprise Governed Memory & Ecosystem (done)

- [x] **Bit 1 — Production Hardening (`v1.7.0`)**: Hermetic zero-leak test DBs, fail-closed production config validation (`config.py`), and HTTP security middleware (`RequestId`, `SecurityHeaders`, `RateLimit`, `AccessLog` in `middleware.py`).
- [x] **Bit 2 — Native AI Extraction & Exact-Span Verification (`v1.8.0`)**: `LLMExtractionEngine` (`llm_extractor.py`) with structured JSON schema extraction and anti-hallucination verbatim substring check (`verify_span`).
- [x] **Bit 3 — Bi-Temporal Knowledge & Fast Review (`v1.9.0`)**: Temporal validity windows (`valid_from`, `valid_to`, `superseded_by`), time-travel search (`as_of`), Conflict Radar at ingestion, and batch approval/rejection (`POST /api/v1/proposals/batch-approve`, `/batch-reject`).
- [x] **Bit 4 — Drop-in Mem0 Compatibility, SDKs & Benchmark (`v2.0.0`)**: Drop-in `/v1/memories` REST shim (`mem0_shim.py`), zero-dependency Python SDK (`sdks/python/openbrain`), TypeScript SDK (`sdks/typescript`), and reproducible Provenance Benchmark (`benchmarks/run_provenance_benchmark.py`).
- [x] **Bit 5 — Bi-Temporal MCP Tools & Time-Travel UI (`v2.1.0`)**: `as_of` and `include_superseded` support in `search_brain` plus `list_pending_reviews` across stdio and HTTP MCP transports; interactive Time-Travel picker in `BrainView`.
- [x] **Bit 6 — Policy-Based Auto-Approval Engine (`v2.2.0`)**: Deterministic `WorkspacePolicy` evaluation (`evaluate_auto_approval`), `GET/PUT /api/v1/workspaces/{slug}/policy`, and `GovernanceSettingsPanel` in the console.
- [x] **Bit 7 — Bi-Temporal Graph Lineage & On-Demand Reindexing (`v2.3.0`)**: Directed `updates` supersession edges in `GET /api/v1/graph?include_superseded=true`, interactive graph toggle, and `POST /api/v1/knowledge/reindex`.
- [x] **Bit 8 — Passphrase-Encrypted Backups, Developer Connectors & CLI (`v2.4.0`)**: Schema v4 AES-256 Fernet + PBKDF2 encrypted backups (`.oib`), `ExportRestoreDialog` modal, GitHub and Slack connectors (`connectors.py`), reviewed source deletion (`DELETE /api/v1/sources/{id}`), and the official `openbrain` developer CLI (`sdks/python/openbrain/cli.py`).

## M1 — trusted thin slice (implemented)

- Source capture.
- Deterministic proposal extraction.
- Human review and exact-wording approval.
- Canonical knowledge search.
- Grounded answers and abstention.
- Audit activity and portable export.
- SQLite/PostgreSQL profiles.
- React workbench, tests, and local documentation.
- Research-aligned application shell and judgement-first review interface.

## M2 — durable knowledge (done)

- [x] Immutable source versions and content hashes.
- [x] Source-span offsets, optional speakers, and parser metadata.
- [x] Knowledge revisions, supersession, and historical queries.
- [x] Deterministic stale-source and possible-conflict signals.
- [x] Schema-v2/v4 backup, empty-workspace restore, and deletion previews.
- [x] SQLite FTS5 full-text search with BM25 ranking.
- [x] Improved conflict detection with same-topic/same-type matching.
- [x] Dialect parity (v1.0.2): PostgreSQL `tsvector`/`ts_rank_cd` ranked search over a GIN index, OR-term query semantics matching SQLite/ILIKE recall, standard `GROUP BY`, rollback-safe capability probing, native `DROP NOT NULL` migrations that preserve every foreign key.
- [x] Search-index versioning (`SEARCH_INDEX_VERSION` persisted in `search_index_state`, stale/absent versions rebuilt at boot).
- [x] Restart release gate on both dialects (`test_restart_gate.py`): create → approve → close → restart → search → grounded → citation survives.
- [x] Local embeddings and a fused full-text + vector candidate path (`hybrid_search` + `POST /api/v1/knowledge/reindex`).
- [x] Encrypted backup packaging (Schema v4 AES-256 Fernet + PBKDF2) and reviewed deletion execution (`DELETE /api/v1/sources/{id}`).

Exit: a changed source cannot silently rewrite approved knowledge, and a fresh restore produces the same canonical results.

## M3 — Intelligence Studio (done)

- [x] Interface architecture and clearly labeled non-functional previews.
- [x] Guided interview sessions with add questions, submit responses, complete & extract.
- [x] Thesis, story, lesson, framework, evidence, question, and decision proposal types.
- [x] Draft builder: assemble approved knowledge into briefs/articles/agent context.
- [x] Claim-to-source mapping in generated drafts with citations.
- [x] Critic/evidence-gap pass as a separately labeled model opinion.

Exit: one new insight is captured from an interview and reused in two different drafts with inspectable evidence.

## M4 — portable agent context (done)

- [x] Workspaces, workspace grants, and workspace-scoped reads and writes.
- [x] Workspace isolation with role-based access control (owner, admin, member).
- [x] Sensitivity scoping (public, internal, private) enforced on every read.
- [x] Engine abstraction with deterministic local and optional hosted provider.
- [x] Harness layer: event intake, deterministic triage, turn orchestration.
- [x] Single-image Cloud Run deployment.
- [x] Scoped workspace principals and expiring tokens.
- [x] MCP HTTP adapter (stdio + HTTP endpoints for remote agents).
- [x] Read tools for search, knowledge, evidence, profile, and context packages.
- [x] Hermes configuration and skill.
- [x] Codex and Claude Code smoke tests.

Exit: each tested client retrieves the same current revision and cannot access a disabled tool or unrelated workspace.

## M5 — tasks and Jev experiment (done)

- [x] Background worker for durable turn processing with lease-based claiming.
- [x] `DecisionProvider` interface with rule and local implementations.
- [x] Optional Jev adapter in shadow mode for intent routing and relevance scoring.
- [x] Payload-bound approval cards with critic notes and source context.
- [x] Held-out evaluation before any automatic route.

Exit: disabling Jev leaves every core workflow working, and measured results justify any route promoted from shadow mode.

## M6 — personal beta (done)

- [x] Opt-in routines with timezone and missed-run policy.
- [x] Manual outcome and reuse tracking.
- [x] Hermes messaging pairing.
- [x] Release packaging, compatibility matrix, and hardening.
- [x] Security audit pass (v1.0.1): static-file containment, MCP caller-scope binding, export/usage ceiling, token previews, SSRF-free evaluation, admin-gated restore, worker path fixes — 32 regression tests.
- [x] Enforce machine-credential scopes via `require_scope` on hashed
      `api_credentials` (legacy free-form `workspace_grants.scope` still
      stored for listing only).
- [x] mcp-auth-bridge integration: connections hub API, OAuth verifier,
      staged action queue with exactly-once approval and recorded post URNs.
- [x] Connections + staged actions console UI (Arc): accounts, staged queue,
      friendly collision handling, and a Composio-style developer-app
      credentials panel (copyable redirect URL, prefilled removable scopes,
      verb-phrase tool names).
- [ ] End-to-end launch test: connect a real account, stage and approve a
      cross-account post through Open Brain (LinkedIn app created and callback
      registered; the account connect and 72h burn-in remain).
- [x] Playwright suite codification for the connections hub and core workbench flows (`web/e2e/brain.spec.ts`).
- [x] Custom domain: `brain.trulyagentic.io` (console) and
      `bridge.trulyagentic.io` (broker + LinkedIn callback), TLS via Caddy.
- [ ] Four-week personal usage study.

Enterprise tenancy, automatic publishing, broad connectors, graph databases, and autonomous browser work remain later decisions triggered by observed need.