"""Full-text search over canonical knowledge using SQLite FTS5.

Falls back to ILIKE when FTS5 is unavailable (e.g. some hosted SQLite
providers). The index is kept in sync by `sync_fts` after every approval,
supersession, or deletion. Rank is BM25, which is what FTS5 exposes natively.

The FTS table mirrors only the columns needed for search: id, statement,
rationale, type, and source_excerpt. It does not duplicate the knowledge
table's schema because FTS5 is a virtual table, not a relational one.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from .models import Knowledge

log = logging.getLogger(__name__)

FTS_TABLE = "knowledge_fts"

# FTS5 uses its own tokenizer; we mirror the columns that matter for search.


def _fts_available(db: Session) -> bool:
    """Check whether this SQLite connection supports FTS5."""
    try:
        db.execute(text(f"SELECT * FROM {FTS_TABLE} LIMIT 0"))
        return True
    except Exception:
        return False


def ensure_fts(db: Session) -> bool:
    """Create the FTS5 virtual table if it does not exist.

    Returns True if FTS5 is available and the table exists.
    """
    try:
        db.execute(text(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
                knowledge_id UNINDEXED,
                statement,
                rationale,
                type,
                source_excerpt,
                content='',
                tokenize='porter unicode61'
            )
        """))
        db.commit()
        return True
    except Exception as exc:
        log.warning("FTS5 unavailable, falling back to ILIKE: %s", exc)
        db.rollback()
        return False


def rebuild_fts(db: Session) -> int:
    """Full rebuild of the FTS index from the knowledge table.

    Called once at startup and after any schema migration. Returns the number
    of rows indexed.
    """
    db.execute(text(f"DELETE FROM {FTS_TABLE}"))
    rows = db.execute(
        text(f"""
            INSERT INTO {FTS_TABLE}(knowledge_id, statement, rationale, type, source_excerpt)
            SELECT id, statement, rationale, type, source_excerpt
            FROM knowledge
            WHERE status = 'canonical'
        """)
    )
    db.commit()
    return rows.rowcount


def sync_fts_insert(db: Session, item: Knowledge) -> None:
    """Add one knowledge item to the FTS index after approval."""
    if not _fts_available(db):
        return
    db.execute(
        text(f"""
            INSERT INTO {FTS_TABLE}(knowledge_id, statement, rationale, type, source_excerpt)
            VALUES (:kid, :statement, :rationale, :type, :excerpt)
        """),
        {
            "kid": item.id,
            "statement": item.statement,
            "rationale": item.rationale,
            "type": item.type,
            "excerpt": item.source_excerpt,
        },
    )


def sync_fts_update(db: Session, item: Knowledge) -> None:
    """Update one knowledge item in the FTS index after supersession."""
    if not _fts_available(db):
        return
    db.execute(
        text(f"DELETE FROM {FTS_TABLE} WHERE knowledge_id = :kid"),
        {"kid": item.id},
    )
    sync_fts_insert(db, item)


def sync_fts_delete(db: Session, knowledge_id: str) -> None:
    """Remove one knowledge item from the FTS index."""
    if not _fts_available(db):
        return
    db.execute(
        text(f"DELETE FROM {FTS_TABLE} WHERE knowledge_id = :kid"),
        {"kid": knowledge_id},
    )


def search_fts(db: Session, query: str, limit: int = 20) -> list[str]:
    """Search canonical knowledge using FTS5 BM25 ranking.

    Returns a list of knowledge_ids ordered by relevance. Falls back to
    empty list if FTS5 is not available (caller should use ILIKE fallback).
    """
    if not _fts_available(db):
        return []
    # FTS5 query syntax: escape special characters, join terms with AND
    cleaned = re.sub(r'[^\w\s]', '', query.lower()).strip()
    if not cleaned:
        return []
    terms = cleaned.split()
    if not terms:
        return []
    # Use OR for broader recall; BM25 handles ranking
    fts_query = " OR ".join(f'"{term}"' for term in terms)
    try:
        rows = db.execute(
            text(f"""
                SELECT knowledge_id, rank
                FROM {FTS_TABLE}
                WHERE {FTS_TABLE} MATCH :query
                ORDER BY rank
                LIMIT :limit
            """),
            {"query": fts_query, "limit": limit},
        ).fetchall()
        return [row[0] for row in rows]
    except Exception as exc:
        log.warning("FTS query failed, falling back to ILIKE: %s", exc)
        return []