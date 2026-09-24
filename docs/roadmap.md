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

## M2 — durable knowledge (in progress)

- [x] Immutable source versions and content hashes.
- [x] Source-span offsets, optional speakers, and parser metadata.
- [x] Knowledge revisions, supersession, and historical queries.
- [x] Deterministic stale-source and possible-conflict signals.
- [x] Schema-v2 backup, empty-workspace restore, and deletion previews.
- [ ] PostgreSQL full-text search and local embeddings with index-version tracking.
- [ ] Evaluation-backed conflict detection and review policy.
- [ ] Encrypted backup packaging and reviewed deletion execution.

Exit: a changed source cannot silently rewrite approved knowledge, and a fresh restore produces the same canonical results.

## M3 — Intelligence Studio

- Guided interview sessions.
- Thesis, story, lesson, framework, and evidence proposal types.
- Critic/evidence-gap pass as a separately labeled model opinion.
- Article outline and website narrative draft workflows.
- Claim-to-source mapping in generated drafts.

Exit: one new insight is captured from an interview and reused in two different drafts with inspectable evidence.

## M4 — portable agent context

- Scoped workspace principals and expiring tokens.
- MCP stdio/HTTP adapter.
- Read tools for search, knowledge, evidence, profile, and context packages.
- Hermes configuration and skill.
- Codex and Claude Code smoke tests.

Exit: each tested client retrieves the same current revision and cannot access a disabled tool or unrelated workspace.

## M5 — tasks and Jev experiment

- Durable tasks, leases, checkpoints, cancellation, and activity timelines.
- Payload-bound approval cards.
- `DecisionProvider` interface with rule and local implementations.
- Optional Jev adapter in shadow mode for intent routing and relevance scoring.
- Held-out evaluation before any automatic route.

Exit: disabling Jev leaves every core workflow working, and measured results justify any route promoted from shadow mode.

## M6 — personal beta

- Opt-in routines with timezone and missed-run policy.
- Hermes messaging pairing.
- Manual outcome and reuse tracking.
- Four-week personal usage study.
- Release packaging, compatibility matrix, and hardening.

Enterprise tenancy, automatic publishing, broad connectors, graph databases, and autonomous browser work remain later decisions triggered by observed need.
