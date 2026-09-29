"""The contentless-FTS5 regression — search returning nothing after a restart.

Bug (pre-existing since M2, shipped in v1.0.1):

`knowledge_fts` was declared `content=''`, making it a *contentless* FTS5 table.
Contentless tables store no column values, so `SELECT knowledge_id FROM
knowledge_fts` returns NULL for every row. `search_fts` therefore returned
`[None, None, ...]` — which is truthy — so `search_knowledge` took the ranked
branch, matched `id IN (NULL)` against nothing, and returned `[]` without ever
reaching the ILIKE fallback that would have found the row.

Why 221 tests missed it: the index is empty until `rebuild_fts` runs, and that
only happens in the lifespan (a server boot), not in unit tests. A fresh boot
with no knowledge yet also returns nothing, which looks correct. The break only
appears on the SECOND boot, once canonical knowledge exists — i.e. after any
restart of a deployment that has approved anything. The old assertion
`len(results) >= 1` also passes on `[None]`.

Three independent guards are asserted here, because any one of them alone
leaves a way to regress:
  1. the index stores content, so ids come back real
  2. `search_fts` filters NULL ids out
  3. `search_knowledge` falls through to ILIKE when ranked ids resolve to
     nothing
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from brain.access import ReadScope, ensure_default_workspace, grant_workspace
from brain.database import Base
from brain.models import Knowledge, Proposal, Source, new_id
from brain.retrieval import (
    FTS_TABLE,
    INDEX_STATE_TABLE,
    SEARCH_INDEX_VERSION,
    _fts_is_contentless,
    _read_index_version,
    ensure_fts,
    index_is_stale,
    rebuild_fts,
    search_fts,
)
from brain.services import search_knowledge


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/fts.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ws = ensure_default_workspace(session)
    grant_workspace(session, ws, "t", role="owner")
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _seed(db, statement: str, rationale: str, term: str) -> str:
    """One canonical knowledge row reachable by `term`. Returns its id."""
    ws_id = "ws_default"
    src = Source(
        id=new_id("src"),
        workspace_id=ws_id,
        title="Pricing policy",
        kind="document",
        sensitivity="public",
        content=f"{statement} {rationale}",
    )
    db.add(src)
    db.flush()
    prop = Proposal(
        id=new_id("prop"),
        workspace_id=ws_id,
        source_id=src.id,
        type="decision",
        statement=statement,
        rationale=rationale,
        source_excerpt=term,
        status="approved",
    )
    db.add(prop)
    db.flush()
    kid = new_id("know")
    db.add(
        Knowledge(
            id=kid,
            workspace_id=ws_id,
            proposal_id=prop.id,
            source_id=src.id,
            type="decision",
            statement=statement,
            rationale=rationale,
            source_excerpt=term,
            status="canonical",
            version=1,
        )
    )
    db.commit()
    return kid


class TestIndexStoresContent:
    """Guard 1: the root cause. The index must actually store its columns."""

    def test_index_is_not_declared_contentless(self, db):
        ensure_fts(db)
        assert _fts_is_contentless(db) is False

    def test_ddl_has_no_content_option(self, db):
        ensure_fts(db)
        ddl = db.scalar(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"),
            {"n": FTS_TABLE},
        )
        assert ddl, "FTS5 table was not created"
        assert "content=''" not in ddl.replace(" ", "")
        assert 'content=""' not in ddl.replace(" ", "")

    def test_knowledge_id_reads_back_real_not_null(self, db):
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        stored = db.scalar(text(f"SELECT knowledge_id FROM {FTS_TABLE} LIMIT 1"))
        assert stored == kid, f"index stored {stored!r}, expected the real id {kid!r}"

    def test_search_fts_returns_real_ids(self, db):
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        ids = search_fts(db, "annual fee")
        assert ids == [kid]
        assert all(i is not None for i in ids)


class TestNullIdsCannotShadowTheFallback:
    """Guards 2 and 3: even a broken index must not silence search."""

    def test_search_knowledge_finds_row_after_rebuild(self, db):
        """The exact production failure: boot -> rebuild -> search."""
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        scope = ReadScope("ws_default", "owner")
        items = search_knowledge(db, scope, "annual fee")
        assert [i.id for i in items] == [kid], (
            "search returned nothing for knowledge the Brain holds — "
            "the contentless-index regression"
        )

    def test_legacy_contentless_index_still_answers(self, db):
        """A deployment that never restarted onto the fix must keep working.

        Hand-builds the OLD shape and populates it, then asserts search still
        returns the row (guard 2 filters the NULLs, guard 3 falls through to
        ILIKE), and that the next ensure_fts() repairs the index.
        """
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        db.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        db.execute(
            text(f"""
            CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5(
                knowledge_id UNINDEXED, statement, rationale, type, source_excerpt,
                content='', tokenize='porter unicode61')
        """)
        )
        db.execute(
            text(f"""
            INSERT INTO {FTS_TABLE}(knowledge_id, statement, rationale, type, source_excerpt)
            SELECT id, statement, rationale, type, source_excerpt
            FROM knowledge WHERE status='canonical'
        """)
        )
        db.commit()

        # Precondition: this really is the broken legacy shape.
        assert _fts_is_contentless(db) is True
        assert db.scalar(text(f"SELECT count(*) FROM {FTS_TABLE}")) == 1
        # The contentless table cannot hand back the id.
        assert db.scalar(text(f"SELECT knowledge_id FROM {FTS_TABLE} LIMIT 1")) is None

        # Guard 2: NULLs are filtered, so the ranked path reports no hits...
        assert search_fts(db, "annual fee") == []

        # ...and guard 3 turns that into a working ILIKE fallback instead of an
        # abstention.
        scope = ReadScope("ws_default", "owner")
        items = search_knowledge(db, scope, "annual fee")
        assert [i.id for i in items] == [kid], "legacy index caused a false abstention"

        # Next boot repairs the index in place.
        assert ensure_fts(db) is True
        assert _fts_is_contentless(db) is False
        assert rebuild_fts(db) == 1
        assert search_fts(db, "annual fee") == [kid]

    def test_stale_id_falls_back_instead_of_abstaining(self, db):
        """A ranked id that no longer resolves must not produce an abstention.

        Same class of failure as the contentless bug: the index answers, the
        rows it names are not returned, and the caller must fall through.
        """
        _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        # Point the index at an id that does not exist in `knowledge`.
        db.execute(text(f"UPDATE {FTS_TABLE} SET knowledge_id = 'know_doesnotexist'"))
        db.commit()
        ids = search_fts(db, "annual fee")
        assert ids == ["know_doesnotexist"], "test setup: index should name the ghost id"

        scope = ReadScope("ws_default", "owner")
        items = search_knowledge(db, scope, "annual fee")
        assert len(items) == 1, "ghost index id suppressed the ILIKE fallback"


class TestSecondBootIsIdempotent:
    def test_repeated_boots_keep_search_working(self, db):
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        scope = ReadScope("ws_default", "owner")
        for boot in range(3):
            assert ensure_fts(db) is True
            rebuild_fts(db)
            items = search_knowledge(db, scope, "annual fee")
            assert [i.id for i in items] == [kid], f"search broke on boot {boot + 1}"

    def test_rebuild_does_not_duplicate_rows(self, db):
        _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        rebuild_fts(db)
        rebuild_fts(db)
        assert db.scalar(text(f"SELECT count(*) FROM {FTS_TABLE}")) == 1


class TestSearchIndexVersionTracking:
    """SEARCH_INDEX_VERSION turns "old schema silently misbehaves" into
    "old schema detected -> rebuilt -> version recorded".

    The version is written by rebuild_fts, not ensure_fts, so a schema is only
    marked current once it actually holds rows.
    """

    def test_untracked_index_counts_as_stale(self, db):
        """A deployment predating version tracking must rebuild once."""
        assert _read_index_version(db) is None
        assert index_is_stale(db) is True

    def test_rebuild_records_the_current_version(self, db):
        _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        assert _read_index_version(db) == SEARCH_INDEX_VERSION
        assert index_is_stale(db) is False

    def test_ensure_alone_does_not_mark_current(self, db):
        """Creating an empty index must not claim the version is installed.

        If it did, a boot that failed before populating the index would record
        itself as current and never repopulate.
        """
        ensure_fts(db)
        assert _read_index_version(db) is None
        assert index_is_stale(db) is True

    def test_a_stale_recorded_version_triggers_a_rebuild(self, db):
        kid = _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        assert _read_index_version(db) == SEARCH_INDEX_VERSION

        # Simulate an older release having stamped its own number.
        db.execute(text(f"UPDATE {INDEX_STATE_TABLE} SET version = :v"), {"v": 1})
        db.commit()
        assert index_is_stale(db) is True

        ensure_fts(db)  # must drop the stale index and recreate it
        rebuild_fts(db)  # must repopulate and re-stamp
        assert _read_index_version(db) == SEARCH_INDEX_VERSION

        scope = ReadScope("ws_default", "owner")
        items = search_knowledge(db, scope, "annual fee")
        assert [i.id for i in items] == [kid], "search broke across a version upgrade"

    def test_version_is_current_after_a_second_boot(self, db):
        _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        ensure_fts(db)
        rebuild_fts(db)
        # Boot 2: no longer stale, so nothing is dropped.
        assert index_is_stale(db) is False
        assert ensure_fts(db) is True
        assert rebuild_fts(db) == 1
        assert _read_index_version(db) == SEARCH_INDEX_VERSION

    def test_state_table_is_a_single_row(self, db):
        _seed(db, "We charge an annual fee", "monthly billing caused churn", "annual fee")
        for _ in range(3):
            ensure_fts(db)
            rebuild_fts(db)
        assert db.scalar(text(f"SELECT count(*) FROM {INDEX_STATE_TABLE}")) == 1
