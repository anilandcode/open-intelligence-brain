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

## Watched folder sync

Watched folders (Connectors → Watched folders, or `/api/v1/watches`) pull new and changed documents from Google Drive, Notion or OneDrive into review. The console syncs on demand with a token pasted for that sync. To sync on a schedule, run the CLI with a provider token in the environment; the Brain never stores provider tokens, so the job has to get a fresh one each run (Google access tokens last an hour, so mint one from a refresh token or the auth broker first).

```
# crontab on the VM, hourly
0 * * * *  cd /path/to/open-intelligence-brain/api && BRAIN_SYNC_TOKEN_GOOGLE_DRIVE="$(/path/to/mint-drive-token)" .venv/bin/python -m brain.watches default
```

`BRAIN_SYNC_TOKEN_NOTION` and `BRAIN_SYNC_TOKEN_ONEDRIVE` work the same way; a watch whose provider has no token is skipped. Each run fetches at most `BRAIN_WATCH_MAX_DOCUMENTS` (default 50) changed documents per folder, and the next run picks up the rest. The exit code is 1 if a folder listing failed (a bad or expired token).
