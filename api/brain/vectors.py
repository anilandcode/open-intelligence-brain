"""pgvector: nearest-neighbour search inside PostgreSQL when the extension exists.

Embeddings stay in ``knowledge.embedding`` as JSON text, the one format every
database and the export understand. On PostgreSQL with the ``vector``
extension, a shadow column ``embedding_vec`` mirrors it, kept in step by a
trigger on every insert or update, so no write path has to remember it. Search
then orders by cosine distance in SQL, with an HNSW index per embedding
dimension, instead of loading every embedding into Python.

Everything here is optional and additive. Without PostgreSQL, without the
extension, or without permission to create it, ``pgvector_ready`` is false and
``retrieval.vector_search`` keeps its Python cosine path; results agree either
way (the parity test checks it).
"""

from __future__ import annotations

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Session
from sqlalchemy.types import NullType

log = logging.getLogger(__name__)

# Let schema inspection (the additive migrations) read the shadow column
# without warning; the ORM never maps it.
ischema_names.setdefault("vector", NullType)

COLUMN = "embedding_vec"
MAX_INDEXED_DIMENSIONS = 4
# Distance below 1 means cosine similarity above 0, the same cut the Python path uses.
MAX_DISTANCE = 1.0

_ready: dict[str, bool] = {}


def _key(db: Session) -> str:
    return str(db.get_bind().url)


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _has_extension(db: Session) -> bool:
    return bool(db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first())


def _has_column(db: Session) -> bool:
    return bool(
        db.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'knowledge' AND column_name = :column"
            ),
            {"column": COLUMN},
        ).first()
    )


def ensure_pgvector(db: Session) -> bool:
    """Set up the shadow column, trigger, backfill and indexes. Idempotent; never raises."""
    if not _is_postgres(db):
        return False
    try:
        if not _has_extension(db):
            try:
                db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                db.commit()
            except Exception as exc:  # no permission, or the extension is not installed
                db.rollback()
                log.info("pgvector unavailable, using in-process vector search: %s", exc)
                _ready[_key(db)] = False
                return False
        db.execute(text(f"ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS {COLUMN} vector"))
        db.execute(
            text(f"""
            CREATE OR REPLACE FUNCTION brain_sync_embedding_vec() RETURNS trigger AS $$
            BEGIN
              IF NEW.embedding IS NULL OR NEW.embedding = '' THEN
                NEW.{COLUMN} := NULL;
              ELSE
                BEGIN
                  NEW.{COLUMN} := NEW.embedding::vector;
                EXCEPTION WHEN others THEN
                  NEW.{COLUMN} := NULL;
                END;
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        db.execute(text("DROP TRIGGER IF EXISTS knowledge_embedding_vec ON knowledge"))
        db.execute(
            text(
                "CREATE TRIGGER knowledge_embedding_vec BEFORE INSERT OR UPDATE OF embedding "
                "ON knowledge FOR EACH ROW EXECUTE FUNCTION brain_sync_embedding_vec()"
            )
        )
        # Rows embedded before the trigger existed: touching `embedding` fires it.
        db.execute(
            text(
                f"UPDATE knowledge SET embedding = embedding "
                f"WHERE embedding IS NOT NULL AND {COLUMN} IS NULL"
            )
        )
        db.commit()
        index_dimensions(db)
        _ready[_key(db)] = True
        return True
    except Exception as exc:
        db.rollback()
        log.warning("pgvector setup failed, using in-process vector search: %s", exc)
        _ready[_key(db)] = False
        return False


def index_dimensions(db: Session) -> list[int]:
    """An HNSW cosine index for each embedding dimension in use (a model change adds one)."""
    dims = [
        int(row[0])
        for row in db.execute(
            text(
                f"SELECT DISTINCT vector_dims({COLUMN}) FROM knowledge "
                f"WHERE {COLUMN} IS NOT NULL LIMIT {MAX_INDEXED_DIMENSIONS}"
            )
        )
    ]
    for dim in dims:
        db.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_knowledge_embedding_hnsw_{dim} ON knowledge "
                f"USING hnsw (({COLUMN}::vector({dim})) vector_cosine_ops) "
                f"WHERE vector_dims({COLUMN}) = {dim}"
            )
        )
    db.commit()
    return dims


def pgvector_ready(db: Session) -> bool:
    if not _is_postgres(db):
        return False
    key = _key(db)
    if key not in _ready:
        try:
            _ready[key] = _has_extension(db) and _has_column(db)
        except Exception:
            db.rollback()
            _ready[key] = False
    return _ready[key]


def forget(db: Session | None = None) -> None:
    """Drop the cached readiness (tests recreate tables underneath it)."""
    if db is None:
        _ready.clear()
    else:
        _ready.pop(_key(db), None)


def pgvector_search(
    db: Session, query_vec: list[float], scope_sql: str, scope_params: dict, limit: int
) -> list[str] | None:
    """Knowledge ids by cosine distance, nearest first; None when the query fails."""
    dim = len(query_vec)
    if not dim:
        return []
    literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"
    statement = text(f"""
        SELECT knowledge.id
        FROM knowledge
        WHERE knowledge.status = 'canonical'
          AND knowledge.{COLUMN} IS NOT NULL
          AND vector_dims(knowledge.{COLUMN}) = {dim}
          AND (knowledge.{COLUMN}::vector({dim}) <=> CAST(:query AS vector({dim}))) < :max_distance
          {scope_sql}
        ORDER BY knowledge.{COLUMN}::vector({dim}) <=> CAST(:query AS vector({dim}))
        LIMIT :limit
    """)
    if scope_params:
        statement = statement.bindparams(bindparam("scope_sens", expanding=True))
    try:
        # A savepoint, so a failed query never rolls back the caller's own work.
        with db.begin_nested():
            rows = db.execute(
                statement,
                {"query": literal, "limit": limit, "max_distance": MAX_DISTANCE, **scope_params},
            ).fetchall()
    except Exception as exc:
        _ready[_key(db)] = False
        log.warning("pgvector search failed, using in-process vector search: %s", exc)
        return None
    return [row[0] for row in rows]
