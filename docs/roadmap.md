# Dependency-ordered roadmap

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

## M2 — durable knowledge (in progress)

- [x] Immutable source versions and content hashes.
- [x] Source-span offsets, optional speakers, and parser metadata.
- [x] Knowledge revisions, supersession, and historical queries.
- [x] Deterministic stale-source and possible-conflict signals.
- [x] Schema-v2 backup, empty-workspace restore, and deletion previews.
- [x] SQLite FTS5 full-text search with BM25 ranking.
- [x] Improved conflict detection with same-topic/same-type matching.
- [ ] Local embeddings with index-version tracking.
- [ ] Encrypted backup packaging and reviewed deletion execution.

Exit: a changed source cannot silently rewrite approved knowledge, and a fresh restore produces the same canonical results.

## M3 — Intelligence Studio (mostly done)

- [x] Interface architecture and clearly labeled non-functional previews.
- [x] Guided interview sessions with add questions, submit responses, complete & extract.
- [x] Thesis, story, lesson, framework, evidence, question, and decision proposal types.
- [x] Draft builder: assemble approved knowledge into briefs/articles/agent context.
- [x] Claim-to-source mapping in generated drafts with citations.
- [ ] Critic/evidence-gap pass as a separately labeled model opinion.

Exit: one new insight is captured from an interview and reused in two different drafts with inspectable evidence.

## M4 — portable agent context (in progress)

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
- Codex and Claude Code smoke tests.

Exit: each tested client retrieves the same current revision and cannot access a disabled tool or unrelated workspace.

## M5 — tasks and Jev experiment (mostly done)

- [x] Background worker for durable turn processing with lease-based claiming.
- [x] `DecisionProvider` interface with rule and local implementations.
- [x] Optional Jev adapter in shadow mode for intent routing and relevance scoring.
- [ ] Payload-bound approval cards.
- [ ] Held-out evaluation before any automatic route.

Exit: disabling Jev leaves every core workflow working, and measured results justify any route promoted from shadow mode.

## M6 — personal beta

- Opt-in routines with timezone and missed-run policy.
- Hermes messaging pairing.
- Manual outcome and reuse tracking.
- Four-week personal usage study.
- Release packaging, compatibility matrix, and hardening.

Enterprise tenancy, automatic publishing, broad connectors, graph databases, and autonomous browser work remain later decisions triggered by observed need.