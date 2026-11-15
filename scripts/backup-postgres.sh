#!/usr/bin/env bash
# backup-postgres.sh — nightly logical backup of the Brain's PostgreSQL database.
#
# Usage (on the VM, from cron or the systemd timer in deploy/oracle-vm/):
#   BRAIN_BACKUP_DATABASE_URL=postgresql://brain@127.0.0.1:5432/brain \
#   BRAIN_BACKUP_DIR=/var/backups/open-brain \
#   ./scripts/backup-postgres.sh
#
# Writes a compressed custom-format dump (restore with pg_restore), checks it is
# readable, and prunes dumps older than BRAIN_BACKUP_KEEP_DAYS. A dump that only
# lives on the VM is not a backup: set BRAIN_BACKUP_UPLOAD_CMD to copy it off the
# box (for example an `rclone copy` or `oci os object put` line). The file path
# is passed as $1 to that command.
#
# The URL uses the libpq form (no `+psycopg`). Keep the password in ~/.pgpass,
# never in the URL, so it does not show up in `ps` or logs.

set -euo pipefail

: "${BRAIN_BACKUP_DATABASE_URL:?set BRAIN_BACKUP_DATABASE_URL (libpq URL, password in ~/.pgpass)}"
BACKUP_DIR="${BRAIN_BACKUP_DIR:-/var/backups/open-brain}"
KEEP_DAYS="${BRAIN_BACKUP_KEEP_DAYS:-14}"
UPLOAD_CMD="${BRAIN_BACKUP_UPLOAD_CMD:-}"

umask 077
mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/brain-$stamp.dump"
partial="$target.partial"

pg_dump --format=custom --compress=9 --no-owner --no-privileges \
  --dbname="$BRAIN_BACKUP_DATABASE_URL" --file="$partial"

# A dump pg_restore cannot list is not a backup; fail loudly before keeping it.
pg_restore --list "$partial" >/dev/null
mv "$partial" "$target"
echo "backup written: $target ($(du -h "$target" | cut -f1))"

if [ -n "$UPLOAD_CMD" ]; then
  # shellcheck disable=SC2086
  $UPLOAD_CMD "$target"
  echo "backup uploaded"
else
  echo "warning: BRAIN_BACKUP_UPLOAD_CMD is empty; this backup exists only on this machine" >&2
fi

find "$BACKUP_DIR" -name 'brain-*.dump' -type f -mtime "+$KEEP_DAYS" -print -delete
