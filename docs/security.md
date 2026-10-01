# Security baseline

This is a personal-first demo with a deliberate path to stronger isolation. It is not yet an internet-facing multi-tenant service.

## Implemented

- Every application endpoint checks `X-Brain-Token`.
- CORS accepts only configured origins.
- Input lengths, enumerated kinds, and sensitivity values are validated server-side.
- No HTML from source content is injected into the UI.
- No arbitrary shell, browser, SQL, or filesystem tool is exposed.
- No hosted-model call or telemetry is performed.
- Secrets, local databases, and exports are excluded from Git.
- Approval and rejection events are audited.
- Source versions and source spans are immutable and SHA-256 addressed.
- Knowledge revisions are append-only; supersession is an explicit owner action.
- Restore refuses to overwrite a non-empty workspace, and both restore endpoints require an owner or admin.
- Source deletion is preview-only and reports blocking canonical dependencies.
- The SPA static fallback containment-checks every resolved path inside `web/dist`; encoded traversal (`%2f`) cannot reach files outside it.
- The sensitivity ceiling applies to every read path, including export and usage analytics: a member's export and usage counts exclude private material exactly like the list endpoints.
- MCP over HTTP binds every tool to the resolved caller's workspace and role; a member token reads as a member, and a token granted only to another workspace cannot read the default one.
- Token listings return a non-recoverable preview; a raw token string is shown exactly once, in the creation response.
- Outbound URLs (Jev evaluation) come from server configuration only — no endpoint accepts a caller-supplied destination URL.
- Every boundary above is pinned by a regression test in `api/tests/test_security_regressions.py`, each proven to fail when its fix is reverted.

## Known gaps (deliberate, documented)

- **Hashed API credentials enforce scopes.** New machine keys are
  `brn_live_…` secrets stored only as SHA-256 digests in `api_credentials`,
  with optional rows in `api_credential_scopes`. `require_scope` gates write
  and admin routes. Legacy free-form `workspace_grants.scope` is still
  listed but not operation-enforced; the bootstrap owner token remains a
  plaintext principal for emergency unlock during the v1.1 transition.
- **Human sign-in** (`user_sessions`, `sessions.py`, `auth_api.py`) supports
  `local` (dev claims) and `firebase` (ID token verification via optional
  `google-auth`). The provider boundary is real and tested — a credential is
  verified before any row is written, and one uninformative error covers every
  failure so it cannot be used to enumerate people. Session secrets are stored
  only as a SHA-256 hash; the raw value appears exactly once, in the login
  response. The web gate shows human sign-in when `/api/v1/auth/status`
  reports a provider; machine token paste always remains available.
- **A `User` is not a credential and a token is not a person.** `X-Brain-Token`
  carries only machine tokens; `X-Brain-Session` carries human sessions. A user
  id, provider subject, or email is rejected as a token. That separation is
  pinned by tests and must not be collapsed for convenience.
- **Audit events name a caller without storing credentials.** `actor_kind` is
  `user` / `token` / `system`; a token is recorded only as a non-recoverable
  preview. Tests assert the raw token appears in no audit column. Rows written
  before attribution existed resolve to `system`, never a fabricated person.
- The owner token is a long-lived static bearer credential (bootstrap only).
- SQLite/Postgres access control is application-level only; there is no
  row-level security in the database.
- **Still open for hosted Google UX:** Firebase web SDK button + first-owner
  membership bootstrap so a fresh Google account can be invited/joined without
  a prior `workspace_members` row.

Proven fixed in v1.0.2 (search persistence, not auth, but it is a safety property):
a contentless FTS5 index made `search_knowledge` return empty on every restart,
so the Brain abstained on its own approved knowledge. Three independent guards
now prevent a silent false abstention (content-storing FTS5 DDL, NULL-id
filtering, ILIKE fall-through when ranked ids resolve to nothing), with a
restart release gate on both dialects.

## Before remote deployment

- Replace the long-lived owner token with a hosted identity provider (Google/Firebase) behind the existing `IdentityProvider` protocol; short-lived sessions already exist for humans.
- Enforce or remove token `scope` — a field that promises restriction and delivers none is worse than no field.
- Enforce TLS, strict host/origin policy, rate limits, and secure headers.
- Add workspace-scoped grants and PostgreSQL row-level security as defense in depth.
- Store original uploaded files outside the database with malware-safe parsing.
- Add payload-hash-bound action approvals.
- Encrypt backup archives and implement reviewed deletion propagation.
- Add SSRF protections before URL import and isolated parsers before PDFs/archives.
- Add dependency scanning, image pinning, an SBOM, and secret scanning in CI.
- Conduct prompt-injection, cross-workspace, and data-egress tests.

## Agent integrations

The first MCP server must expose read-only search, knowledge, evidence, and context tools. Proposal tools can be added after workspace grants. Approval, policy changes, deletion, publication, and unrestricted execution must remain unavailable to ordinary agent tokens.
