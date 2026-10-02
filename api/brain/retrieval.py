"""Full-text search over canonical knowledge — dialect aware.

Two backends behind one interface:

- **SQLite** uses an FTS5 virtual table (`knowledge_fts`) ranked by BM25. FTS5
  is a separate structure from `knowledge`, so it must be synced manually after
  every approval, supersession and deletion.
- **PostgreSQL** uses `to_tsvector` / `plainto_tsquery` over an expression GIN
  index, ranked by `ts_rank_cd`. The engine maintains that index itself, so the
  sync functions are no-ops and there is no second copy of the text to drift.

ILIKE remains the last-resort fallback so a read never hard-fails when neither
backend is available.

Transaction hygiene — read this before adding a probe:

On PostgreSQL a statement error aborts the *entire* transaction, and every
later statement fails with `InFailedSqlTransaction` until it is rolled back. An
earlier `_fts_available()` swallowed the exception without rolling back, which
meant the failed `CREATE VIRTUAL TABLE` probe poisoned the session and took
`POST /api/v1/chat` down with a 500 — while plain GET routes, which never touch
FTS, kept working. Every `except` here rolls back before returning.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import Knowledge

log = logging.getLogger(__name__)

FTS_TABLE = "knowledge_fts"

# Bump this whenever the index's SHAPE or CONTENT changes: new columns indexed,
# a different tokenizer, or — as happened here — the table being declared in a
# form that cannot store what we read back out of it. `ensure_fts` compares the
# installed version with this constant and rebuilds on mismatch, which turns
# "an old index silently behaves incorrectly" into "old index detected, rebuilt,
# version recorded". The roadmap anticipated index-version tracking; this is it.
#
#   1 = original FTS5 table, declared contentless (broken: ids read back NULL)
#   2 = content-storing FTS5 on SQLite; tsvector GIN index on PostgreSQL
SEARCH_INDEX_VERSION = 2

# Single-row bookkeeping table. Created by ensure_fts rather than as a
# SQLAlchemy model on purpose: it is part of the index lifecycle, so it must not
# depend on `create_all` having already run and registered this module.
INDEX_STATE_TABLE = "search_index_state"

# The PostgreSQL search expression. It MUST be textually identical in the index
# DDL and in every query, or the planner will not match the query to the index
# and every search silently degrades to a sequential scan. Build both from this
# constant — never retype the expression.
PG_TSV_EXPR = (
    "to_tsvector('english', "
    "coalesce(statement, '') || ' ' || coalesce(rationale, '') || ' ' || "
    "coalesce(type, '') || ' ' || coalesce(source_excerpt, ''))"
)
PG_TSV_INDEX = "knowledge_tsv_idx"


def dialect_name(db: Session) -> str:
    """The SQLAlchemy dialect in use: 'sqlite', 'postgresql', ..."""
    bind = db.get_bind()
    return bind.dialect.name if bind is not None else ""


def is_postgres(db: Session) -> bool:
    return dialect_name(db).startswith("postgres")


def _probe(db: Session, sql: str) -> bool:
    """Run a cheap capability probe, always leaving the session usable.

    The rollback in `except` is the whole point: without it a failed probe on
    PostgreSQL aborts the transaction and poisons every later query.
    """
    try:
        db.execute(text(sql))
        return True
    except Exception as exc:
        db.rollback()
        log.debug("capability probe failed (%s): %s", sql.split()[0:3], exc)
        return False


def _fts_available(db: Session) -> bool:
    """Whether the dialect's ranked index exists and is queryable."""
    if is_postgres(db):
        return _probe(db, "SELECT to_tsvector('english', '') @@ plainto_tsquery('english', '')")
    return _probe(db, f"SELECT * FROM {FTS_TABLE} LIMIT 0")


# --- schema ---------------------------------------------------------------


def ensure_fts(db: Session) -> bool:
    """Bring the ranked index up to SEARCH_INDEX_VERSION.

    Creates it when absent, and drops-and-recreates it when the installed
    version is behind, so an index shape that no longer matches the code can
    never linger on an upgraded deployment. Returns True when ranked search is
    available; False means callers fall back to ILIKE, which still returns
    correct (if less well ordered) results.

    The version is written by `rebuild_fts`, not here, so it is only recorded
    once the index actually holds data. Recording it in `ensure_fts` would mark
    a schema as current while its contents were still empty.
    """
    stale = index_is_stale(db)
    if stale:
        installed = _read_index_version(db)
        log.info(
            "Search index is stale (installed=%s, code=%d); rebuilding",
            installed,
            SEARCH_INDEX_VERSION,
        )
        _drop_stale_indexes(db)
    if is_postgres(db):
        return _ensure_postgres_index(db)
    return _ensure_sqlite_fts5(db)


def _ensure_postgres_index(db: Session) -> bool:
    """Expression GIN index over the knowledge text columns."""
    try:
        db.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {PG_TSV_INDEX} ON knowledge USING gin ({PG_TSV_EXPR})"
            )
        )
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        log.warning("PostgreSQL tsvector index unavailable, falling back to ILIKE: %s", exc)
        return False


def _read_index_version(db: Session) -> int | None:
    """The installed search-index version, or None when unrecorded.

    None means "this deployment predates version tracking", which is treated as
    stale so the first boot after an upgrade rebuilds once and records itself.
    """
    try:
        db.execute(
            text(f"CREATE TABLE IF NOT EXISTS {INDEX_STATE_TABLE} (version INTEGER NOT NULL)")
        )
        db.commit()
        row = db.execute(text(f"SELECT version FROM {INDEX_STATE_TABLE} LIMIT 1")).fetchone()
        return int(row[0]) if row else None
    except Exception as exc:
        db.rollback()
        log.warning("Could not read search index version: %s", exc)
        return None


def _write_index_version(db: Session, version: int) -> None:
    """Record the installed version. Best effort: never fail a boot over it."""
    try:
        db.execute(text(f"DELETE FROM {INDEX_STATE_TABLE}"))
        db.execute(text(f"INSERT INTO {INDEX_STATE_TABLE} (version) VALUES (:v)"), {"v": version})
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Could not record search index version %d: %s", version, exc)


def index_is_stale(db: Session) -> bool:
    """True when the installed index predates SEARCH_INDEX_VERSION.

    Callers rebuild on this rather than inspecting DDL shapes, so a future index
    change needs only a version bump instead of another bespoke detector.
    """
    installed = _read_index_version(db)
    return installed != SEARCH_INDEX_VERSION


def _drop_stale_indexes(db: Session) -> None:
    """Drop an index whose recorded (or unrecorded) version is behind.

    Both shapes have to go: a contentless FTS5 table from v1, and any SQLite
    table left over from a version whose shape we no longer build. PostgreSQL's
    GIN index is re-asserted by CREATE INDEX IF NOT EXISTS, so only the SQLite
    virtual table is dropped here.
    """
    if is_postgres(db):
        return
    try:
        db.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Could not drop stale FTS table: %s", exc)


def _fts_is_contentless(db: Session) -> bool:
    """True when the existing FTS5 table was declared with `content=''`.

    A contentless FTS5 table stores no column values at all — they exist only
    to be matched against, and any SELECT of them returns NULL. That made
    `search_fts` return `[None, None, ...]`, which is truthy, so
    `search_knowledge` took the ranked branch, matched `id IN (NULL)` against
    nothing, and returned an empty result list without ever reaching the ILIKE
    fallback that would have found the row. The visible symptom: after a
    restart (which runs `rebuild_fts` and so populates the index) the Brain
    could no longer find its own approved knowledge.

    The table is a derived index, so dropping and recreating it is safe —
    `rebuild_fts` runs immediately after in the lifespan and repopulates it
    from `knowledge`. No provenance lives here.
    """
    try:
        row = db.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": FTS_TABLE},
        ).fetchone()
    except Exception:
        db.rollback()
        return False
    if not row or not row[0]:
        return False
    # Match the declaration in any spacing/quoting variant.
    return "content=''" in row[0].replace(" ", "") or 'content=""' in row[0].replace(" ", "")


def _ensure_sqlite_fts5(db: Session) -> bool:
    """FTS5 virtual table storing the searchable knowledge columns.

    Deliberately NOT contentless: we select `knowledge_id` back out of this
    table to rank results, so the values have to be stored. See
    `_fts_is_contentless` for what went wrong when they were not.
    """
    try:
        if _fts_is_contentless(db):
            # Legacy index from an earlier release. Drop so the CREATE below
            # rebuilds it in the content-storing shape.
            db.execute(text(f"DROP TABLE {FTS_TABLE}"))
            db.commit()
            log.info("Recreated %s as a content-storing FTS5 table", FTS_TABLE)
        db.execute(
            text(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
                knowledge_id UNINDEXED,
                statement,
                rationale,
                type,
                source_excerpt,
                tokenize='porter unicode61'
            )
        """)
        )
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        log.warning("FTS5 unavailable, falling back to ILIKE: %s", exc)
        return False


def rebuild_fts(db: Session) -> int:
    """Full rebuild from the knowledge table. Returns rows indexed.

    Called at startup and after a schema migration. Records
    `SEARCH_INDEX_VERSION` on success so the next boot knows the installed index
    matches the code and does not rebuild again.

    On PostgreSQL the GIN index is maintained by the engine, so this only
    reports how many canonical rows the index covers.
    """
    if is_postgres(db):
        try:
            count = db.scalar(text("SELECT count(*) FROM knowledge WHERE status = 'canonical'"))
            db.commit()
        except Exception as exc:
            db.rollback()
            log.warning("PostgreSQL index rowcount unavailable: %s", exc)
            return 0
        _write_index_version(db, SEARCH_INDEX_VERSION)
        return int(count or 0)

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
    _write_index_version(db, SEARCH_INDEX_VERSION)
    return rows.rowcount


# --- sync (SQLite only) ---------------------------------------------------
#
# PostgreSQL maintains its expression index automatically, so these are no-ops
# there. Keeping the signatures stable means services.py calls the same three
# functions on both dialects and cannot forget one.


def sync_fts_insert(db: Session, item: Knowledge) -> None:
    """Add one knowledge item to the index after approval."""
    if is_postgres(db) or not _fts_available(db):
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
    """Update one knowledge item in the index after supersession."""
    if is_postgres(db) or not _fts_available(db):
        return
    db.execute(
        text(f"DELETE FROM {FTS_TABLE} WHERE knowledge_id = :kid"),
        {"kid": item.id},
    )
    sync_fts_insert(db, item)


def sync_fts_delete(db: Session, knowledge_id: str) -> None:
    """Remove one knowledge item from the index."""
    if is_postgres(db) or not _fts_available(db):
        return
    db.execute(
        text(f"DELETE FROM {FTS_TABLE} WHERE knowledge_id = :kid"),
        {"kid": knowledge_id},
    )


# --- search ---------------------------------------------------------------


def search_fts(db: Session, query: str, limit: int = 20) -> list[str]:
    """Ranked knowledge ids for a query, best match first.

    Returns an empty list when ranked search is unavailable or the query has no
    terms, which tells the caller to use the ILIKE fallback. Never raises: a
    search backend problem must not turn a read into a 500.
    """
    if not query or not query.strip():
        return []
    if is_postgres(db):
        return _search_postgres(db, query, limit)
    return _search_sqlite_fts5(db, query, limit)


def _search_postgres(db: Session, query: str, limit: int) -> list[str]:
    """ts_rank_cd over the expression GIN index.

    Terms are OR'd, matching the SQLite FTS5 path and the ILIKE fallback. This
    matters for correctness, not just ranking: `plainto_tsquery` ANDs its terms,
    so a multi-word question that SQLite answers would abstain on PostgreSQL.
    Abstention is this product's safety mechanism, so over-abstention on one
    dialect is a real behavioural divergence — a hosted Brain would answer fewer
    questions than a local one over identical data.

    The tsquery string is built from terms already stripped to `\\w+` by the same
    regex the FTS5 path uses, then quoted per term so nothing inside a term can
    be read as a tsquery operator. It still travels as a bind parameter, so
    there is no string interpolation into SQL.
    """
    tsquery = _build_or_tsquery(query)
    if not tsquery:
        return []
    try:
        rows = db.execute(
            text(f"""
                SELECT id
                FROM knowledge
                WHERE status = 'canonical'
                  AND {PG_TSV_EXPR} @@ to_tsquery('english', :tsq)
                ORDER BY ts_rank_cd({PG_TSV_EXPR}, to_tsquery('english', :tsq)) DESC
                LIMIT :limit
            """),
            {"tsq": tsquery, "limit": limit},
        ).fetchall()
        return [row[0] for row in rows]
    except Exception as exc:
        db.rollback()
        log.warning("PostgreSQL tsvector search failed, falling back to ILIKE: %s", exc)
        return []


def _build_or_tsquery(query: str) -> str:
    """Turn free text into a safe OR'd `to_tsquery` expression.

    Returns "" when the query has no word characters, which tells the caller to
    fall through to ILIKE rather than issue a tsquery Postgres would reject.
    """
    # Same sanitisation as the FTS5 path: drop everything that is not a word
    # character or whitespace. That removes quotes, `&`, `|`, `!`, `*` and `:`
    # before the terms reach the tsquery grammar.
    cleaned = re.sub(r"[^\w\s]", "", query.lower()).strip()
    terms = [term for term in cleaned.split() if term]
    if not terms:
        return ""
    # Quote each term so the parser treats it as a literal lexeme, and let
    # 'english' stemming apply. `'a' | 'b'` is OR.
    return " | ".join(f"'{term}'" for term in terms)


def _search_sqlite_fts5(db: Session, query: str, limit: int) -> list[str]:
    """BM25 over the FTS5 virtual table."""
    if not _fts_available(db):
        return []
    # Strip FTS5 syntax characters before building the match expression, then
    # quote each term so a stray `*`, `"` or `-` cannot change query meaning.
    cleaned = re.sub(r"[^\w\s]", "", query.lower()).strip()
    terms = cleaned.split()
    if not terms:
        return []
    # OR for broader recall; BM25 does the ranking.
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
        # Drop NULL ids. A truthy `[None]` once told search_knowledge that the
        # ranked path had answered, so the ILIKE fallback — which would have
        # found the row — never ran. Filtering here means no future index
        # misconfiguration can silence search again.
        ids = [row[0] for row in rows if row[0] is not None]
        if len(ids) != len(rows):
            log.warning(
                "FTS5 returned %d NULL knowledge_id(s); index shape is wrong — "
                "recreate it with content stored",
                len(rows) - len(ids),
            )
        return ids
    except Exception as exc:
        db.rollback()
        log.warning("FTS query failed, falling back to ILIKE: %s", exc)
        return []


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))  # L2-normalised, so dot == cosine


def vector_search(db: Session, query_vec: list[float], scope, limit: int = 20) -> list[str]:
    """Rank knowledge ids by cosine similarity to query_vec, best first.

    Only rows that carry an embedding, narrowed by the caller's ReadScope. Empty
    when nothing is embedded yet, so the caller keeps the keyword path. Never
    raises: a vector problem must not turn a read into a 500.
    """
    if not query_vec:
        return []
    try:
        rows = list(
            db.scalars(
                scope.apply(
                    select(Knowledge).where(Knowledge.status == "canonical"),
                    Knowledge,
                )
            ).all()
        )
    except Exception as exc:
        db.rollback()
        log.warning("vector candidate load failed: %s", exc)
        return []
    scored: list[tuple[float, str]] = []
    for item in rows:
        if not item.embedding:
            continue
        try:
            vec = json.loads(item.embedding)
        except Exception:
            continue
        sim = _cosine(query_vec, vec)
        if sim > 0:
            scored.append((sim, item.id))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [kid for _, kid in scored[:limit]]


def _rrf(rankings: list[list[str]], limit: int, k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion across result lists.

    score(id) = sum(1 / (k + rank)) over every list it appears in. Rank-based, so
    it needs no score calibration between BM25 and cosine — the standard fusion
    for hybrid retrieval.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, kid in enumerate(ranking, start=1):
            scores[kid] = scores.get(kid, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores, key=lambda kid: scores[kid], reverse=True)
    return ordered[:limit]


def hybrid_search(db: Session, scope, query: str, limit: int = 20) -> list[str]:
    """Fuse keyword (FTS) and vector rankings with reciprocal-rank fusion.

    Falls back to whichever single source answers, and to an empty list when
    neither does (sending the caller to the ILIKE fallback). Never raises.
    """
    from .embeddings import get_embedder  # local import avoids a settings cycle

    fts_ids = search_fts(db, query, limit=limit)
    vec_ids: list[str] = []
    embedder = get_embedder()
    if embedder is not None:
        qv = embedder.embed(query)
        if qv:
            vec_ids = vector_search(db, qv, scope, limit=limit)
    if fts_ids and vec_ids:
        return _rrf([fts_ids, vec_ids], limit)
    return fts_ids or vec_ids
