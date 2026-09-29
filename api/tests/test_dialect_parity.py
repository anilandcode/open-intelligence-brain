"""Dialect parity — SQLite and PostgreSQL must behave the same.

Two failure classes this file exists to prevent:

1. **Silent degradation.** FTS5 is SQLite-only, so on PostgreSQL the ranked
   index never existed and every search fell back to ILIKE. Reads still
   returned 200, which is why nothing caught it. The Postgres path now uses a
   tsvector GIN index and these tests assert it is real.

2. **Dialect-specific SQL that only one engine rejects.** A failed statement on
   PostgreSQL aborts the whole transaction (`InFailedSqlTransaction`), so one
   swallowed exception in a capability probe took `POST /api/v1/chat` down with
   a 500 while plain GET routes kept working. And `GROUP BY` that SQLite accepts
   as an extension is a hard error in PostgreSQL.

The Postgres tests skip when `BRAIN_TEST_POSTGRES_URL` is unset, so a machine
without a server still gets a clean run — but they are NOT skipped in CI, which
provisions a real PostgreSQL service. A skip is a gap, not a pass.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from brain.access import ReadScope, ensure_default_workspace, grant_workspace
from brain.database import Base
from brain.models import Knowledge, Proposal, Source, new_id
from brain.retrieval import (
    PG_TSV_INDEX,
    _build_or_tsquery,
    dialect_name,
    ensure_fts,
    is_postgres,
    rebuild_fts,
    search_fts,
    sync_fts_insert,
)
from brain.services import search_knowledge

PG_URL = os.environ.get("BRAIN_TEST_POSTGRES_URL", "")
# CI sets this so a missing/broken Postgres service fails loudly instead of
# reporting "14 skipped, green". Local developers without a server still get
# skips, which is the right trade for a laptop but not for CI.
REQUIRE_PG = os.environ.get("BRAIN_REQUIRE_POSTGRES_TESTS", "") not in ("", "0", "false", "False")
needs_postgres = pytest.mark.skipif(
    not PG_URL and not REQUIRE_PG,
    reason="BRAIN_TEST_POSTGRES_URL not set; Postgres parity unverified",
)


def _admin_url() -> str:
    """The supplied URL, used only to reach the server for CREATE DATABASE."""
    return PG_URL


def _pg_url() -> str:
    """A unique per-test database URL.

    The database component is REPLACED, not appended: `BRAIN_TEST_POSTGRES_URL`
    normally points at an existing maintenance database (`postgres`), and
    concatenating would yield the invalid `.../postgres/brain_test_x`.
    """
    from sqlalchemy.engine import make_url

    return (
        make_url(PG_URL)
        .set(database=f"brain_test_{uuid.uuid4().hex[:12]}")
        .render_as_string(hide_password=False)
    )


def _seed_canonical(db, ws_id: str, rows: list[tuple[str, str, str]]) -> list[str]:
    """Insert real sources -> proposals -> knowledge so FKs hold on BOTH
    dialects. Postgres enforces foreign keys; SQLite does not unless
    PRAGMA foreign_keys=ON, so a test that cheats here passes on SQLite and
    fails on Postgres.
    """
    src = Source(
        id=new_id("src"),
        workspace_id=ws_id,
        title="Pricing doc",
        kind="document",
        sensitivity="public",
        content=" ".join(r[0] for r in rows),
    )
    db.add(src)
    db.flush()
    ids = []
    for statement, rationale, ktype in rows:
        prop = Proposal(
            id=new_id("prop"),
            workspace_id=ws_id,
            source_id=src.id,
            type=ktype,
            statement=statement,
            rationale=rationale,
            source_excerpt=statement,
            status="approved",
        )
        db.add(prop)
        # Knowledge has no relationship() to Proposal, so the unit of work
        # cannot infer insert order. Flush explicitly or Postgres sees an
        # orphan proposal_id.
        db.flush()
        kid = new_id("know")
        db.add(
            Knowledge(
                id=kid,
                workspace_id=ws_id,
                proposal_id=prop.id,
                source_id=src.id,
                type=ktype,
                statement=statement,
                rationale=rationale,
                source_excerpt=statement,
                status="canonical",
                version=1,
            )
        )
        ids.append(kid)
    db.commit()
    return ids


ROWS = [
    (
        "We charge enterprise customers an annual fee",
        "Monthly billing caused churn and unpredictable revenue",
        "decision",
    ),
    (
        "Enterprise pricing is reviewed each quarter",
        "The pricing committee meets to adjust annual fee tiers",
        "decision",
    ),
    ("The office kitchen restocks coffee on Mondays", "Facilities keeps a standing order", "fact"),
]


@pytest.fixture
def sqlite_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ws = ensure_default_workspace(session)
    grant_workspace(session, ws, "t", role="owner")
    session.commit()
    session._ws_id = ws.id  # type: ignore[attr-defined]
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def pg_db():
    """A private Postgres database, dropped afterwards.

    Raises instead of skipping when Postgres is REQUIRED but unreachable. A skip
    in CI reads as green, which is exactly how 14 parity tests went unproven;
    the service being absent or misconfigured must fail the build.
    """
    if not PG_URL:
        if REQUIRE_PG:
            raise RuntimeError(
                "BRAIN_REQUIRE_POSTGRES_TESTS is set but BRAIN_TEST_POSTGRES_URL "
                "is empty — Postgres parity tests are required in this environment."
            )
        pytest.skip("BRAIN_TEST_POSTGRES_URL not set")

    from sqlalchemy.engine import make_url

    name = f"brain_test_{uuid.uuid4().hex[:12]}"
    url = make_url(PG_URL).set(database=name).render_as_string(hide_password=False)
    # CREATE DATABASE cannot run inside a transaction, so autocommit on admin.
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - re-raised, never swallowed
        if REQUIRE_PG:
            raise RuntimeError(
                f"Postgres parity tests are required but the server at "
                f"BRAIN_TEST_POSTGRES_URL refused CREATE DATABASE: {exc}"
            ) from exc
        admin.dispose()
        pytest.skip(f"Postgres unreachable and not required here: {exc}")

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ws = ensure_default_workspace(session)
    grant_workspace(session, ws, "t", role="owner")
    session.commit()
    session._ws_id = ws.id  # type: ignore[attr-defined]
    yield session
    session.close()
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


class TestDialectDetection:
    def test_sqlite_reports_sqlite(self, sqlite_db):
        assert dialect_name(sqlite_db) == "sqlite"
        assert is_postgres(sqlite_db) is False

    @needs_postgres
    def test_postgres_reports_postgres(self, pg_db):
        assert dialect_name(pg_db).startswith("postgres")
        assert is_postgres(pg_db) is True


class TestOrTsqueryConstruction:
    """The OR-parity builder: `plainto_tsquery` ANDs, which would make a
    hosted Brain abstain where a local one answers."""

    def test_terms_are_ored_not_anded(self):
        assert _build_or_tsquery("annual fee churn") == "'annual' | 'fee' | 'churn'"

    def test_punctuation_stripped_before_tsquery_grammar(self):
        # Quotes, operators and wildcards must not survive into the tsquery.
        assert _build_or_tsquery("'; DROP TABLE x; --") == "'drop' | 'table' | 'x'"
        assert "|" not in _build_or_tsquery("a|b").replace("'a' | 'b'", "")

    def test_empty_and_symbol_only_queries_return_blank(self):
        assert _build_or_tsquery("") == ""
        assert _build_or_tsquery("   ") == ""
        assert _build_or_tsquery("!@#$%^&*()") == ""

    def test_case_folded(self):
        assert _build_or_tsquery("ANNUAL Fee") == "'annual' | 'fee'"


class TestSqliteFtsPath:
    """SQLite keeps using FTS5/BM25 — the Postgres work must not regress it."""

    def test_ensure_fts_creates_table(self, sqlite_db):
        assert ensure_fts(sqlite_db) is True

    def test_ranked_search_finds_needle(self, sqlite_db):
        ids = _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS)
        assert ensure_fts(sqlite_db)
        rebuild_fts(sqlite_db)
        hits = search_fts(sqlite_db, "annual fee churn")
        assert hits, "FTS5 returned nothing for a matching query"
        assert hits[0] == ids[0], "BM25 did not rank the best match first"

    def test_sync_insert_indexes_new_approval(self, sqlite_db):
        assert ensure_fts(sqlite_db)
        ids = _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS[:1])
        item = sqlite_db.get(Knowledge, ids[0])
        sync_fts_insert(sqlite_db, item)
        sqlite_db.commit()
        assert search_fts(sqlite_db, "annual fee")

    def test_no_match_returns_empty(self, sqlite_db):
        _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS)
        ensure_fts(sqlite_db)
        rebuild_fts(sqlite_db)
        assert search_fts(sqlite_db, "zzzznomatchzzz") == []


class TestPostgresFtsPath:
    """The whole point of v1.1's retrieval work: ranked search on Postgres."""

    @needs_postgres
    def test_index_is_created_and_named_as_expected(self, pg_db):
        assert ensure_fts(pg_db) is True
        found = pg_db.scalar(
            text("SELECT indexname FROM pg_indexes WHERE indexname = :n"), {"n": PG_TSV_INDEX}
        )
        assert found == PG_TSV_INDEX

    @needs_postgres
    def test_index_is_a_gin_on_the_search_expression(self, pg_db):
        ensure_fts(pg_db)
        ddl = pg_db.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": PG_TSV_INDEX}
        )
        assert "gin" in ddl.lower()
        assert "to_tsvector" in ddl.lower()

    @needs_postgres
    def test_ranked_search_finds_needle(self, pg_db):
        ids = _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        assert ensure_fts(pg_db)
        hits = search_fts(pg_db, "annual fee churn")
        assert hits, "Postgres ranked search returned nothing for a matching query"
        assert hits[0] == ids[0]

    @needs_postgres
    def test_or_parity_with_sqlite(self, pg_db, sqlite_db):
        """Same data, same query, same hit count on both dialects.

        This is the regression the AND-vs-OR bug caused: Postgres found 1 row
        where SQLite found 2, so a hosted Brain abstained on questions a local
        one answered.
        """
        _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        ensure_fts(pg_db)
        _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS)
        ensure_fts(sqlite_db)
        rebuild_fts(sqlite_db)

        q = "annual fee churn"
        pg_hits = search_fts(pg_db, q)
        lite_hits = search_fts(sqlite_db, q)
        assert len(pg_hits) == len(lite_hits), (
            f"dialect divergence: postgres={len(pg_hits)} sqlite={len(lite_hits)}"
        )
        assert len(pg_hits) >= 2, "expected the OR semantics to match both pricing rows"

    @needs_postgres
    def test_service_layer_returns_ranked_items(self, pg_db):
        ids = _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        ensure_fts(pg_db)
        scope = ReadScope(pg_db._ws_id, "owner")
        items = search_knowledge(pg_db, scope, "annual fee churn")
        assert items and items[0].id == ids[0]

    @needs_postgres
    def test_sync_functions_are_noops_not_errors(self, pg_db):
        """The GIN index is engine-maintained; sync must not raise or write."""
        ids = _seed_canonical(pg_db, pg_db._ws_id, ROWS[:1])
        assert ensure_fts(pg_db)
        item = pg_db.get(Knowledge, ids[0])
        sync_fts_insert(pg_db, item)  # must not raise
        rebuild_fts(pg_db)  # must not raise
        assert search_fts(pg_db, "annual fee")

    @needs_postgres
    def test_no_match_returns_empty(self, pg_db):
        _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        ensure_fts(pg_db)
        assert search_fts(pg_db, "zzzznomatchzzz") == []


class TestTransactionNotPoisoned:
    """The v1.1 chat 500. On PostgreSQL a failed statement aborts the whole
    transaction; swallowing the exception without rolling back leaves every
    later query failing with InFailedSqlTransaction."""

    def test_failed_capability_probe_leaves_session_usable_sqlite(self, sqlite_db):
        with pytest.raises(SQLAlchemyError):
            sqlite_db.execute(text("SELECT * FROM definitely_absent LIMIT 0"))
        sqlite_db.rollback()
        assert sqlite_db.scalar(text("SELECT 1")) == 1

    @needs_postgres
    def test_failed_statement_leaves_session_usable(self, pg_db):
        with pytest.raises(SQLAlchemyError):
            pg_db.execute(text("SELECT * FROM definitely_absent LIMIT 0"))
        pg_db.rollback()
        # Without the rollback discipline this raises InFailedSqlTransaction.
        assert pg_db.scalar(text("SELECT 1")) == 1

    @needs_postgres
    def test_search_after_a_failing_probe_still_works(self, pg_db):
        ids = _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        ensure_fts(pg_db)
        # Poison attempt: a statement that will fail, exercised through the same
        # session that then has to answer a search.
        with pytest.raises(SQLAlchemyError):
            pg_db.execute(text("SELECT bogus_function_that_does_not_exist()"))
        pg_db.rollback()
        hits = search_fts(pg_db, "annual fee")
        assert hits and hits[0] == ids[0]


class TestStandardSqlGrouping:
    """SQLite accepts non-aggregated columns missing from GROUP BY; PostgreSQL
    raises GroupingError. usage.top_used hit exactly that and 500'd two routes."""

    def test_top_used_is_standard_sql(self, sqlite_db):
        from brain.usage import top_used, track_batch

        ids = _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS[:1])
        scope = ReadScope(sqlite_db._ws_id, "owner")
        track_batch(sqlite_db, sqlite_db._ws_id, ids, context="answer", query="q")
        sqlite_db.commit()
        rows = top_used(sqlite_db, scope, limit=5)
        assert rows and rows[0]["count"] >= 1
        assert rows[0]["statement"]

    @needs_postgres
    def test_top_used_does_not_raise_grouping_error(self, pg_db):
        from brain.usage import top_used, track_batch

        ids = _seed_canonical(pg_db, pg_db._ws_id, ROWS[:1])
        scope = ReadScope(pg_db._ws_id, "owner")
        track_batch(pg_db, pg_db._ws_id, ids, context="answer", query="q")
        pg_db.commit()
        rows = top_used(pg_db, scope, limit=5)
        assert rows and rows[0]["count"] >= 1
        assert rows[0]["statement"]

    @needs_postgres
    def test_usage_summary_does_not_raise(self, pg_db):
        from brain.usage import usage_summary

        _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        scope = ReadScope(pg_db._ws_id, "owner")
        summary = usage_summary(pg_db, scope)
        assert summary["total_knowledge"] == len(ROWS)


class TestInjectionSurface:
    """Query text must reach the database as a bind parameter only."""

    def test_sqlite_survives_hostile_query(self, sqlite_db):
        _seed_canonical(sqlite_db, sqlite_db._ws_id, ROWS)
        ensure_fts(sqlite_db)
        rebuild_fts(sqlite_db)
        for evil in ["'; DROP TABLE knowledge; --", 'a" OR 1=1 --', "*:*"]:
            search_fts(sqlite_db, evil)  # must not raise
        assert sqlite_db.scalar(text("SELECT count(*) FROM knowledge")) == len(ROWS)

    @needs_postgres
    def test_postgres_survives_hostile_query(self, pg_db):
        _seed_canonical(pg_db, pg_db._ws_id, ROWS)
        ensure_fts(pg_db)
        for evil in ["'; DROP TABLE knowledge; --", "a' | 'b", "!&|:*()"]:
            search_fts(pg_db, evil)  # must not raise
        assert pg_db.scalar(text("SELECT count(*) FROM knowledge")) == len(ROWS)


class TestGinIndexIsActuallyUsed:
    """An index the planner ignores is a write cost with no read benefit. With
    few rows Postgres correctly seq-scans, so this loads enough rows that a
    bitmap index scan is the cheaper plan and asserts the plan uses it."""

    @needs_postgres
    def test_bitmap_index_scan_at_scale(self, pg_db):
        ensure_fts(pg_db)
        n = 3000
        ws_id = pg_db._ws_id
        src = Source(
            id=new_id("src"),
            workspace_id=ws_id,
            title="Bulk",
            kind="document",
            sensitivity="public",
            content="bulk",
        )
        pg_db.add(src)
        pg_db.flush()
        src_id = src.id
        # Set-based insert: one distinct proposal id per row because
        # knowledge.proposal_id is UNIQUE. mod() avoids '%' escaping issues
        # between SQLAlchemy and psycopg.
        for table in ("proposals", "knowledge"):
            id_prefix = "prop_" if table == "proposals" else "know_"
            cols = (
                "id, workspace_id, source_id, type, statement, rationale, "
                "source_excerpt, status, critic_notes, engine_memory_id, created_at"
                if table == "proposals"
                else "id, workspace_id, proposal_id, source_id, type, statement, "
                "rationale, source_excerpt, status, version, approved_at"
            )
            select_list = (
                f"'{id_prefix}' || lpad(g::text, 24, '0'), :ws, :src, 'decision', "
                f"CASE WHEN mod(g,300)=0 THEN 'enterprise customers pay an annual fee to avoid churn' "
                f"ELSE 'unrelated operational note ' || g || ' about logistics and staffing' END, "
                f"CASE WHEN mod(g,300)=0 THEN 'monthly billing caused churn' ELSE 'facilities note ' || g END, "
                f"'excerpt ' || g, 'approved', '', '', now()"
                if table == "proposals"
                else f"'{id_prefix}' || lpad(g::text, 24, '0'), :ws, "
                f"'prop_' || lpad(g::text, 24, '0'), :src, 'decision', "
                f"CASE WHEN mod(g,300)=0 THEN 'enterprise customers pay an annual fee to avoid churn' "
                f"ELSE 'unrelated operational note ' || g || ' about logistics and staffing' END, "
                f"CASE WHEN mod(g,300)=0 THEN 'monthly billing caused churn' ELSE 'facilities note ' || g END, "
                f"'excerpt ' || g, 'canonical', 1, now()"
            )
            pg_db.execute(
                text(
                    f"INSERT INTO {table} ({cols}) SELECT {select_list} "
                    f"FROM generate_series(1, :n) AS g"
                ),
                {"ws": ws_id, "src": src_id, "n": n},
            )
        pg_db.commit()
        pg_db.execute(text("ANALYZE knowledge"))

        from brain.retrieval import PG_TSV_EXPR

        plan_rows = pg_db.execute(
            text(
                f"EXPLAIN (FORMAT TEXT) SELECT id FROM knowledge "
                f"WHERE status='canonical' AND {PG_TSV_EXPR} @@ to_tsquery('english', :tsq) "
                f"LIMIT 20"
            ),
            {"tsq": _build_or_tsquery("annual fee churn")},
        ).fetchall()
        plan = "\n".join(r[0] for r in plan_rows)
        assert PG_TSV_INDEX in plan, f"planner ignored {PG_TSV_INDEX}; plan was:\n{plan}"
