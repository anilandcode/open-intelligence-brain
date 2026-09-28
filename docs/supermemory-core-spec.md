# Supermemory as core — Option B spec

Status: adopted. Deployment decision made: **hosted, multi-tenant**. S0, S1 and
the approval half of S2 are implemented; retrieval (S3) and context packages
(S4) are not.

## Decision

Supermemory becomes the retrieval and extraction engine, hosted and multi-tenant.
Our application keeps the parts it is actually good at: provenance, approval,
tenancy, and audit.

**Deployment: hosted, one org, many containers.** This is now settled and it
had consequences that were deferred while the choice was open:

- Connectors and Supermemory MCP are available, so on-prem ingestion is no
  longer ours to build and our own MCP server stays authoritative for agents.
- Multi-tenancy is a hosted feature, so serving many companies from one
  deployment is real rather than one engine per customer.
- `strict_local` mode still exists and still refuses a hosted engine before any
  network call, for the customer who needs it. It is the exception, not the
  default.

**System of record = our Postgres. Retrieval index = supermemory.**

That split is what makes this survivable. Canonical `knowledge` rows still live
in our database, so a dead supermemory degrades to today's keyword search
instead of losing the product. The engine is load-bearing, not load-bearing-only.

## Why the review queue made this viable

Supermemory's graph `derive`s facts it was never told. Those are flagged
`isInference: true` and down-weighted in search until reviewed, and the engine
ships a queue for exactly this:

| Operation | Endpoint |
| --- | --- |
| List unreviewed inferred memories | `GET /v3/container-tags/{ct}/inferred` |
| Decide | `POST /v3/container-tags/{ct}/inferred/{id}/review` with `approve` / `decline` / `undo` |

- **approve** clears `isInference` — ranks like a stated fact
- **decline** sets `isForgotten` — leaves search entirely
- **undo** returns it to the queue
- queue returns up to 50, ordered by `parentCount` desc, excluding forgotten,
  expired, and already-reviewed

This is our proposal/approval model, already built and already correct. The
mapping is close to one-to-one:

| Ours | Supermemory |
| --- | --- |
| `proposal` (untrusted, awaiting review) | derived memory, `isInference: true` |
| `POST /proposals/{id}/approve` | `review {action: "approve"}` |
| `POST /proposals/{id}/reject` | `review {action: "decline"}` |
| `audit_events` | the review stamp is `reviewStatus` in metadata |
| `source_excerpt` exactness | `parentCount` — how many memories backed the derivation |

The "derive then gate" pattern is their design, not a workaround. Adopting the
core does not mean inventing a governance layer; it means using the one that
ships.

## Layer map

```
  capture ──► sources + source_versions + source_spans   (our Postgres, unchanged)
                │
                ├─► supermemory.add({content, containerTag, entityContext})
                │     └─ derives facts, queues them as inferences
                │
                ▼
  our workbench ──GET {ct}/inferred──► proposals + proposal_evidence
                │                            │
                │                    human reviews (exact wording)
                │                            │
                │              ┌─────────────┴─────────────┐
                │        approve                      decline
                │              │                            │
                │   POST review approve          POST review decline
                │              └─────────────┬─────────────┘
                ▼                            ▼
  knowledge  (our Postgres, system of record)   audit_events
         │
         └─► push canonical items into supermemory as documents
                    │
                    ▼
           supermemory search / profile / SMFS  ──► agents (MCP), answers
```

## Mapping our tenancy onto container tags

Container tags are a hard authorization boundary in supermemory: a search scoped
to one tag never returns another's memories, and out-of-scope tag access is
rejected 403. Metadata is a soft filter for organisation.

| Our concept | Supermemory | Kind |
| --- | --- | --- |
| `workspace_id` (`ws_*`) | `org_{workspace_id}` | container tag — hard |
| team | `metadata.team` | filter — soft, enforced by us |
| `sensitivity` | `metadata.sensitivity` | filter — soft, **enforced by us** |
| principal / grant | scoped API key, one per workspace | auth |

Team is deliberately **not** a container tag. Supermemory's own guidance is to
reserve tags for the isolation boundary and use metadata for everything inside
it; making team hard would break cross-team questions like "who touched this
across the org".

## Conflicts with our invariants, stated plainly

**1. Invariant 10 is abandoned.** "Optional providers must not become required
for reading, review, or export." Under B, supermemory is required for extraction
and for semantic retrieval. Mitigation is the system-of-record split above, not
a claim that the invariant still holds. The honest rewrite: *supermemory is
required for good retrieval; the product must still read, review, and export
without it, degraded.*

**2. Decline sets `isForgotten`, and we are append-only.** A declined inference
leaves supermemory's search index. Our `proposals.status` keeps the decision and
its evidence, so nothing is lost on our side — the forget is scoped to the
retrieval index, not to the record. Our `knowledge_revisions` and `audit_events`
are unaffected because canonical knowledge is never declined, only superseded.

**3. Supermemory reports 403; we must return 404.** `require_in_workspace`
returns 404 because confirming existence would leak another company. Container
tag access control returns 403. A 403 from the engine must be caught and
remapped at our edge — never passed through, or the tenancy guarantee in
invariant 13 is gone.

**4. `sensitivity` is not enforceable by the engine.** Metadata filtering answers
"which reachable memories match", not "which may this caller see". Row-level
authorisation stays ours. This is the existing defect: `sensitivity` is written,
validated, exported and restored, and read by no query —
`services.py:383 search_knowledge` filters on `workspace_id` and `status` only,
while `models.py:46` claims read scope comes from it. **Under this design that
becomes a cross-team data leak, not a cosmetic bug.** It is fixed as part of
this work, before any supermemory wiring.

## The enforcement point

Supermemory's metadata filter is an optimisation. The guarantee is a post-filter
in our own read path:

1. resolve principal → workspace → allowed `sensitivity` set
2. query supermemory scoped to `org_{workspace_id}`, with metadata filters as a
   narrowing optimisation
3. **re-check every returned memory's `sensitivity` against the caller**
4. drop anything not permitted, before it reaches an answer, an agent tool, or
   the UI

Step 3 is the only place the guarantee lives. If it is skipped, every other
layer still "works" and still leaks.

## Brand voice

Two distinct mechanisms, and they are not interchangeable:

- **Ingestion triage** — `settings.update({shouldLLMFilter: true, filterPrompt})`.
  Org-wide, 1–750 chars, applies to new content only. Supermemory documents a
  brand-guidelines assistant as the first example. Good for deciding what is
  worth indexing.
- **Voice as knowledge** — the guide itself, approved into canonical `knowledge`,
  cited by every generated draft. This is the product's existing thesis and it
  does not need supermemory at all.

The first shapes what enters. The second is what the Brain asserts.

## Engine credentials

`BRAIN_SUPERMEMORY_API_KEY` is our env var; the credential is Supermemory's,
minted at `console.supermemory.ai`. It is not something we can issue — what we
own is which of their keys we hold.

**Scoped keys are unusable here, and that is a real constraint.** Their allowed
endpoints are `/v3/documents`, `/v3/memories`, `/v4/memories`, `/v3/search`,
`/v4/search`, `/v4/profile`. The inferred-memory review queue is not on that
list, so a scoped key can neither read derived facts nor record a decision —
which is the whole S2 bridge.

Consequence: the **org master key** is the only usable credential, shared across
every workspace, so `container_tag_for()` is the *only* thing isolating one
company from another on the engine side. That function validates against the
engine's own pattern (`^[a-zA-Z0-9_:-]+$`, 100 chars) and refuses rather than
sending a tag the engine would reject at write time, because a rejected tag
means that company's content silently never reaches the index.

A rejected tag must never fail a capture. The source is already committed by
then, and the engine copy is a convenience; losing the customer's data to make
our indexing tidier is the wrong trade.

## Platform split

| Capability | Self-hosted | Hosted |
| --- | --- | --- |
| Graph memory, hybrid search, extraction | yes | yes |
| Local embeddings `Xenova/bge-base-en-v1.5` (768d) | default | managed |
| Inferred-memory review queue | yes | yes |
| Connectors (Drive, Notion, Gmail, OneDrive, GitHub, S3, Granola, crawler) | **no** | yes |
| Supermemory MCP | **no** | yes |
| Multi-member orgs, roles, scoped keys | **no** | Enterprise |
| Optimised extraction models | **no** | yes |

Consequences to plan around:

- **On-prem ingestion is entirely ours to build.** A customer with no egress
  gets our connector work, not theirs.
- **Multi-tenancy is not a self-hosted product.** Local is one binary, one
  auto-generated key, one org. Serving many companies means one engine per
  company, or the hosted platform. This decides our deployment topology before
  any code is written.
- **We keep our own MCP server.** It stays the read-only, workspace-scoped
  surface, because supermemory's MCP is hosted-only.

## Scale

Today's retrieval is `ILIKE %term%` over the workspace plus Python scoring, with
no pagination on any list endpoint. Supermemory removes the retrieval ceiling.
It does not remove ours:

- list endpoints still need pagination
- canonical `knowledge` stays relational; it does not move into the graph
- ingestion is queued server-side (`POST /v3/documents` returns `queued`;
  searches are served ahead of the queue) — so the API must not block on
  extraction, and our proposal rows need a pending state that survives a restart
- embeddings have a **dimension lock**: changing provider or model invalidates
  stored vectors and requires re-ingestion. `SUPERMEMORY_EMBEDDING_DIMENSIONS`
  must be fixed at 768 before first ingest and never varied per environment.

## Sequenced work

**S0 — fix the leak, standalone. Done.** `sensitivity` is enforced in the read
path by a `ReadScope` that carries the caller's role into every collection
query. Nine tests, each proven to fail with the enforcement removed. Verified
live over HTTP: a member sees 2 of 4 rows, direct fetch is 404 not 403, counts
do not leak, and a grounded answer abstains.

**S1 — engine behind the provider boundary. Done.** `brain/engine.py` holds the
boundary: `DeterministicEngine` (no network, no claims of inference) and
`SupermemoryEngine` (hosted). Every engine call degrades to empty rather than
raising, because the system of record is our database. `strict_local` refuses a
hosted client before one is constructed. The active engine and the reason for
any fallback are reported on `/api/v1/overview` and shown in the interface, so
a deployment cannot quietly run on regexes believing it is on a model.

**S2 — bridge the review queue. Ingest side done, review fan-out not.**
`GET {ct}/inferred` → `proposals` with the engine's support count in the
rationale. Two things this forced:

1. **A derived fact has no excerpt, and the approval gate requires evidence.**
   Left alone, every engine-derived proposal landed in the review queue and was
   then permanently unapprovable — a dead row. `proposal_evidence.source_span_id`
   is now nullable and the bridge pins the source version instead, so evidence
   stays mandatory and a span does not. The canonical excerpt falls back to the
   pinned version rather than inventing a quote.
2. **The gate had to check before it wrote.** `approve_proposal` now resolves
   evidence first, so a refusal cannot mark a proposal approved and then raise,
   leaving a decided proposal that produced no canonical knowledge.

Both reversions are proven to break the suite: removing the evidence edge fails
3 tests, restoring the old check order fails 1.

Remaining for S2: approve/reject fan out to the engine's review endpoint, and
the Inbox shows the support count.

**S3 — retrieval. Not started.** Search answers from canonical knowledge via the
engine; fall back to `search_knowledge` when it is down. Enforce sensitivity on
both paths.

**S4 — context packages.** Versioned context bundle per workspace — SMFS and
`profile()` for the "infinite context" behaviour. Already planned in
`architecture.md` retrieval step 6.

**S5 — ingestion on-prem.** Connectors are platform-only, so the local path
gets file drop and webhook first; third-party connectors wait on a hosted
decision.

## What would reverse this

- Supermemory's `updates` relation supersedes a memory for search without an
  approved `knowledge` revision behind it — if that leaks into the canonical
  read path, the governance claim is false.
- Self-hosted multi-tenancy stays unavailable, and we need many companies per
  deployment rather than one engine each.
- The inferred-review queue is not available self-hosted in practice.

## Open questions

1. **Settled:** hosted multi-tenant.
2. Is the review-queue mapping acceptable as *our* approval gate, given the
   decision lives in supermemory's metadata rather than our table? Our table
   remains the system of record; the engine is told, not asked. Worth a
   customer's answer before it is load-bearing.
3. A 403 from the engine must be remapped to 404 at our edge. Not yet
   implemented, because our own workspace check runs first — but it becomes
   live the moment we call an engine endpoint that is workspace-scoped. It is
   more load-bearing than it looks, because the master key is not scoped at
   all: the engine will happily serve another company's tag to us, and the only
   thing standing between that and a cross-tenant leak is our own check.
4. Cost. Hosted extraction is metered by credits. The free plan carries $5 a
   month, which is enough to develop against and not enough for a customer. Any
   volume estimate has to come before S3 ships, not after.
5. Embedding dimensions are locked at 768 by the hosted default. If that is
   ever varied per environment, stored vectors are invalidated and the workspace
   must be re-ingested.
