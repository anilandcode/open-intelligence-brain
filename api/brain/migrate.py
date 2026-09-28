"""Additive schema migration for workspaces.

`Base.metadata.create_all` creates missing tables but never adds a column to a
table that already exists, so an existing Brain would boot against a schema
without `workspace_id` and fail on the first query. This module adds the columns
in place with a default, which keeps every existing row and never rewrites
provenance-bearing data.

Migrations are additive and idempotent: running one twice is a no-op.
"""

from sqlalchemy import inspect, text

from .database import engine

# Tables that gain a workspace_id, in dependency order. Child tables
# (source_versions, source_spans, proposal_evidence, knowledge_revisions)
# deliberately do not: they are reached through their parent.
_SCOPED_TABLES = ("sources", "proposals", "knowledge", "audit_events")

_DEFAULT = "ws_default"


def _existing_columns(connection) -> dict[str, set[str]]:
    inspector = inspect(connection)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }


def add_engine_link_columns() -> list[str]:
    """Store the engine's own ids so the derivation bridge can round-trip.

    Additive and idempotent: two new columns with defaults, no existing row is
    read, rewritten, or dropped.

    The engine does not echo ingest metadata on `/inferred`, so linking a
    derived fact back to its source cannot be done from the queue. It is done
    from the document instead — which means the capture must remember the
    engine's document id, and a derived proposal must remember the engine's
    memory id so an approval can be echoed back to the index.
    """
    added: list[str] = []
    columns = _existing_columns(engine)
    wanted = {
        "sources": ("engine_document_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
        "proposals": ("engine_memory_id", "VARCHAR(64) NOT NULL DEFAULT ''"),
    }
    with engine.begin() as connection:
        for table, (column, definition) in wanted.items():
            if table not in columns:
                continue
            if column in columns[table]:
                continue
            connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            )
            added.append(f"{table}.{column}")
    return added


def add_nullable_evidence_span() -> list[str]:
    """Make `proposal_evidence.source_span_id` nullable for derived proposals.

    Additive and idempotent, and it only relaxes a constraint: it never drops,
    rewrites, or re-points a provenance-bearing row. An existing database has
    this column NOT NULL from schema v2, which would make every engine-derived
    proposal permanently unapprovable, because a derived fact has no single
    excerpt to point at.

    SQLite cannot drop a NOT NULL in place, so the table is rebuilt from its own
    rows. The rebuild copies every column and preserves the primary key, so the
    relationship a row encodes does not change.
    """
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "proposal_evidence" not in inspector.get_table_names():
            return []
        column = next(
            (
                c
                for c in inspector.get_columns("proposal_evidence")
                if c["name"] == "source_span_id"
            ),
            None,
        )
        if column is None or column.get("nullable", True):
            return []
        # Rebuild, because SQLite has no ALTER COLUMN ... DROP NOT NULL.
        connection.execute(
            text(
                """
                CREATE TABLE proposal_evidence_relaxed (
                    proposal_id VARCHAR(32) NOT NULL,
                    source_version_id VARCHAR(32) NOT NULL,
                    source_span_id VARCHAR(32),
                    PRIMARY KEY (proposal_id),
                    FOREIGN KEY(source_version_id) REFERENCES source_versions (id),
                    FOREIGN KEY(source_span_id) REFERENCES source_spans (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO proposal_evidence_relaxed
                    (proposal_id, source_version_id, source_span_id)
                SELECT proposal_id, source_version_id, source_span_id
                FROM proposal_evidence
                """
            )
        )
        connection.execute(text("DROP TABLE proposal_evidence"))
        connection.execute(text("ALTER TABLE proposal_evidence_relaxed RENAME TO proposal_evidence"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proposal_evidence_source_version_id "
                "ON proposal_evidence (source_version_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_proposal_evidence_source_span_id "
                "ON proposal_evidence (source_span_id)"
            )
        )
    return ["proposal_evidence.source_span_id"]


def add_workspace_columns() -> list[str]:
    """Add `workspace_id` to existing tables where it is missing.

    Returns the tables that were migrated, which is empty for a fresh database
    where `create_all` already made the columns.
    """
    applied: list[str] = []
    with engine.begin() as connection:
        tables = _existing_columns(connection)
        if "workspaces" not in tables:
            return []
        for table in _SCOPED_TABLES:
            if table not in tables or "workspace_id" in tables[table]:
                continue
            # SQLite cannot add a NOT NULL column without a default, so the
            # default is what assigns every pre-existing row to the one
            # workspace those rows already belonged to.
            connection.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN workspace_id "
                    f"VARCHAR(32) NOT NULL DEFAULT '{_DEFAULT}'"
                )
            )
            applied.append(table)
        for table in _SCOPED_TABLES:
            if table in tables:
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_workspace_id "
                        f"ON {table} (workspace_id)"
                    )
                )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_workspaces_slug ON workspaces (slug)")
        )
    return applied
