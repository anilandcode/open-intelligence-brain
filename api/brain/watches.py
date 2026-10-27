"""Watched folders: keep a Drive, Notion or OneDrive folder flowing into review.

A watch names one provider folder. Each sync lists the folder, brings in
documents it has not seen as new sources, and adds a new source version when
a document's modified time changes. A new version only offers sentences that
are new, and approved knowledge resting on a changed sentence shows up as
"source changed" in gardening, so editing a doc in Drive flows through the
same review as everything else. Nothing becomes canonical without approval.

The provider token is never stored. The console passes one per sync, and a
cron passes one through its own environment:

    BRAIN_SYNC_TOKEN_GOOGLE_DRIVE=... python -m brain.watches default

(``BRAIN_SYNC_TOKEN_NOTION`` and ``BRAIN_SYNC_TOKEN_ONEDRIVE`` likewise; a
watch whose provider has no token is skipped.)
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import WorkspaceAccess
from .config import get_settings
from .connectors import ConnectorError, get_connector, ingest_fetched
from .models import ConnectorWatch, Source, WatchedDocument, Workspace, new_id
from .services import add_source_version, audit


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    deferred: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{len(self.added)} new",
            f"{len(self.updated)} updated",
            f"{self.unchanged} unchanged",
        ]
        if self.deferred:
            parts.append(f"{self.deferred} left for the next sync")
        if self.errors:
            parts.append(f"{len(self.errors)} failed")
        return ", ".join(parts)

    def to_dict(self) -> dict:
        return {**asdict(self), "summary": self.summary()}


def _record(db: Session, watch: ConnectorWatch, summary: str, now: datetime) -> None:
    watch.last_synced_at = now
    watch.last_result = summary
    db.commit()


def sync_watch(
    db: Session,
    watch: ConnectorWatch,
    access_token: str,
    *,
    actor: WorkspaceAccess | None = None,
    now: datetime | None = None,
) -> SyncResult:
    """Pull new and changed documents from the watched folder into review.

    A listing failure raises ``ConnectorError``; a failure on one document is
    recorded in the result and the rest of the folder still syncs.
    """
    now = now or datetime.now(UTC)
    connector = get_connector(watch.provider)
    try:
        entries = connector.list_folder(watch.folder_id, access_token)
    except ConnectorError as exc:
        _record(db, watch, f"Listing failed: {exc}", now)
        raise
    known = {
        doc.external_id: doc
        for doc in db.scalars(select(WatchedDocument).where(WatchedDocument.watch_id == watch.id))
    }
    result = SyncResult()
    budget = get_settings().watch_max_documents
    for entry in entries:
        doc = known.get(entry.external_id)
        source = db.get(Source, doc.source_id) if doc else None
        if source is not None and source.workspace_id != watch.workspace_id:
            source = None
        if doc and source and doc.modified == entry.modified:
            result.unchanged += 1
            continue
        if budget <= 0:
            result.deferred += 1
            continue
        budget -= 1
        name = entry.title or entry.external_id
        try:
            fetched = connector.fetch_document(entry.external_id, access_token)
            fetched.kind = watch.kind
            if source is None:
                source = ingest_fetched(
                    db, watch.workspace_id, fetched, sensitivity=watch.sensitivity, actor=actor
                )
                if doc is None:
                    doc = WatchedDocument(
                        id=new_id("wdoc"), watch_id=watch.id, external_id=entry.external_id
                    )
                    db.add(doc)
                doc.source_id = source.id
                result.added.append(name)
            else:
                content = (fetched.content or "").strip()
                if len(content) < 20:
                    raise ConnectorError("Fetched document has no usable text content")
                try:
                    add_source_version(
                        db,
                        source,
                        content,
                        f"Synced from {watch.provider}: changed {entry.modified or 'since last sync'}",
                        actor=actor,
                    )
                    result.updated.append(name)
                except ValueError:
                    # Same text under a new modified time (a rename, a share change).
                    result.unchanged += 1
            doc.modified = entry.modified
            doc.synced_at = now
            db.commit()
        except ConnectorError as exc:
            db.rollback()
            result.errors.append(f"{name}: {exc}")
    audit(
        db,
        watch.workspace_id,
        "watch.synced",
        "connector_watch",
        watch.id,
        f"{watch.provider} {watch.label or watch.folder_id}: {result.summary()}",
        actor=actor,
    )
    _record(db, watch, result.summary(), now)
    return result


TOKEN_ENV = {
    "google-drive": "BRAIN_SYNC_TOKEN_GOOGLE_DRIVE",
    "notion": "BRAIN_SYNC_TOKEN_NOTION",
    "onedrive": "BRAIN_SYNC_TOKEN_ONEDRIVE",
}


def main(argv: list[str] | None = None) -> int:
    from .database import SessionLocal

    args = argv if argv is not None else sys.argv[1:]
    slug = args[0] if args else "default"
    failed = False
    with SessionLocal() as db:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
        if workspace is None:
            print(f"No workspace with slug {slug!r}", file=sys.stderr)
            return 2
        watches = db.scalars(
            select(ConnectorWatch).where(ConnectorWatch.workspace_id == workspace.id)
        ).all()
        for watch in watches:
            token = os.environ.get(TOKEN_ENV.get(watch.provider, ""), "")
            label = watch.label or watch.folder_id
            if not token:
                print(f"{watch.provider} {label}: skipped, {TOKEN_ENV[watch.provider]} is not set")
                continue
            try:
                print(f"{watch.provider} {label}: {sync_watch(db, watch, token).summary()}")
            except ConnectorError as exc:
                failed = True
                print(f"{watch.provider} {label}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
