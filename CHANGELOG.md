# Changelog

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