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

- **Token `scope` is stored and returned but NOT enforced.** `TokenCreate` accepts a `scope` string and grants carry it, but no route checks it — a "read-only" scoped token can still write. Do not rely on scope for restriction until it is enforced; use role and expiry, which are enforced.
- **Human identity exists (`users`, `workspace_members`, `identity.py`) but no login route consumes it yet.** The provider boundary is real and tested — a credential is verified before any row is written, and one uninformative error covers every failure so it cannot be used to enumerate people — but sessions and HTTP login land in the next v1.1 commit. Until then every authenticated request is a machine token.
- **A `User` is not a credential and a token is not a person.** `X-Brain-Token` carries only machine tokens (`workspace_grants`); a user id, provider subject, or email is rejected as a token. That separation is pinned by tests and must not be collapsed for convenience — an audit trail that cannot say whether a person or a token acted is worthless when it matters.
- The owner token is a long-lived static bearer credential.
- SQLite/Postgres access control is application-level only; there is no row-level security in the database.

Proven fixed in v1.0.2 (search persistence, not auth, but it is a safety property):
a contentless FTS5 index made `search_knowledge` return empty on every restart,
so the Brain abstained on its own approved knowledge. Three independent guards
now prevent a silent false abstention (content-storing FTS5 DDL, NULL-id
filtering, ILIKE fall-through when ranked ids resolve to nothing), with a
restart release gate on both dialects.

## Before remote deployment

- Replace the long-lived owner token with standard identity and short-lived scoped sessions.
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
