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

## Before remote deployment

- Replace the long-lived owner token with standard identity and short-lived scoped sessions.
- Enforce TLS, strict host/origin policy, rate limits, and secure headers.
- Add workspace-scoped grants and PostgreSQL row-level security as defense in depth.
- Store original files outside the database with content hashes and malware-safe parsing.
- Add immutable revisions and payload-hash-bound action approvals.
- Implement encrypted backups, restore tests, and deletion propagation.
- Add SSRF protections before URL import and isolated parsers before PDFs/archives.
- Add dependency scanning, image pinning, an SBOM, and secret scanning in CI.
- Conduct prompt-injection, cross-workspace, and data-egress tests.

## Agent integrations

The first MCP server must expose read-only search, knowledge, evidence, and context tools. Proposal tools can be added after workspace grants. Approval, policy changes, deletion, publication, and unrestricted execution must remain unavailable to ordinary agent tokens.

