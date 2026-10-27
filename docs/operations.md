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

## Weekly gardening digest

The gardening report lists approved knowledge that needs a person: review dates that have passed, expired items, items whose source sentence changed, possible conflicts and duplicates, and items nothing has cited for `BRAIN_UNUSED_AFTER_DAYS` (default 120). It is on the console Overview and at `GET /api/v1/gardening`.

To send it weekly through Hermes, set `BRAIN_HERMES_URL` (and optionally `BRAIN_HERMES_CHANNEL`) and schedule one of these. Either is safe to fire twice: the digest is not re-sent within `BRAIN_GARDENING_MIN_DAYS` (default 6) unless forced.

```
# crontab on the VM, Mondays 08:00, from the api directory with its environment loaded
0 8 * * 1  cd /path/to/open-intelligence-brain/api && .venv/bin/python -m brain.gardening default --send

# or from anywhere that can reach the API, with an owner or admin key
0 8 * * 1  curl -fsS -X POST -H "X-Brain-Token: $BRAIN_ADMIN_KEY" https://brain.example.com/api/v1/routines/gardening/send
```

Links in the digest use `BRAIN_PUBLIC_BASE_URL`.
