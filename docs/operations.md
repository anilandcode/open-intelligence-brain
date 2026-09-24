# Operations

## Schema compatibility

Version 0.2 adds new tables without changing the columns in the 0.1 tables. On startup, the API creates the new tables and backfills one immutable source version, exact spans, proposal-evidence edges, and one knowledge revision for existing records. Backfill never changes canonical wording.

Create a backup before upgrading a real personal workspace.

## Backup

Download `GET /api/v1/export` with the owner token. The schema-v2 JSON contains stable IDs, timestamps, source versions, spans, proposal evidence, knowledge revisions, and audit events.

~~~bash
curl --fail --silent \
  -H 'X-Brain-Token: local-dev-token' \
  http://localhost:8000/api/v1/export \
  --output brain-backup.json
~~~

Store backups outside the repository. The JSON is portable but not encrypted.

## Restore

Restore never merges into or overwrites an existing workspace.

1. Start with an empty database.
2. Call `POST /api/v1/restore/preview` with `{"backup": ...}`.
3. Inspect every blocker and collection count.
4. Call `POST /api/v1/restore` with the same backup and `"confirm_empty_workspace": true`.
5. Compare canonical search and integrity results with the source workspace.

The automated suite verifies that a schema-v2 backup restores the same canonical IDs and wording.

## Deletion safety

`GET /api/v1/sources/{source_id}/deletion-preview` reports versions, spans, proposals, canonical dependencies, and audit records. It does not delete anything. A source with canonical dependents is marked blocked.

Deletion execution remains intentionally unavailable until retention rules, revision handling, and recoverability are complete.
