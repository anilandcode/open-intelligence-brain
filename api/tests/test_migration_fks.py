"""FK preservation across the proposal_evidence rebuild — exact targets.

`add_nullable_evidence_span` relaxes a NOT NULL. SQLite cannot do that in place,
so the table is rebuilt from its own rows. The rebuild DDL once re-declared only
two of the model's three foreign keys, silently dropping
`proposal_id -> proposals.id` on every legacy upgrade — the constraint that
keeps an evidence edge pointing at a real proposal.

Asserting "three FKs exist" would still pass if a future edit preserved the
count while pointing one FK at the wrong table. These tests assert the exact
(column -> table.column) mapping, which is what actually protects provenance.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from brain.database import Base
from brain.models import ProposalEvidence

# The contract this migration must not lose, derived from the model itself so
# the expectation cannot drift from the schema by hand.
EXPECTED_FKS = {
    ("proposal_id", "proposals", "id"),
    ("source_version_id", "source_versions", "id"),
    ("source_span_id", "source_spans", "id"),
}


def _fk_edges(engine) -> set[tuple[str, str, str]]:
    """The (local column, referred table, referred column) set for the table."""
    inspector = inspect(engine)
    return {
        (fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0])
        for fk in inspector.get_foreign_keys("proposal_evidence")
    }


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/mig.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


class TestModelIsTheContract:
    def test_model_declares_all_three_fks(self, sqlite_engine):
        """Guards the guard: if the expectation set is wrong the rest is noise."""
        assert _fk_edges(sqlite_engine) == EXPECTED_FKS

    def test_expectation_matches_the_orm_model(self):
        declared = {
            (col.name, fk.target_fullname.split(".")[0], fk.target_fullname.split(".")[1])
            for col in ProposalEvidence.__table__.columns
            for fk in col.foreign_keys
        }
        assert declared == EXPECTED_FKS


class TestSqliteRebuildPreservesEveryFk:
    def _make_legacy(self, engine) -> None:
        """Rebuild the table in the OLD broken shape: NOT NULL span, 2 FKs."""
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE proposal_evidence"))
            conn.execute(
                text(
                    """
                    CREATE TABLE proposal_evidence (
                        proposal_id VARCHAR(32) NOT NULL,
                        source_version_id VARCHAR(32) NOT NULL,
                        source_span_id VARCHAR(32) NOT NULL,
                        PRIMARY KEY (proposal_id),
                        FOREIGN KEY(source_version_id) REFERENCES source_versions (id),
                        FOREIGN KEY(source_span_id) REFERENCES source_spans (id)
                    )
                    """
                )
            )

    def test_legacy_shape_really_is_missing_the_proposal_fk(self, sqlite_engine):
        """Precondition: the simulated legacy DB has the bug we are testing for."""
        self._make_legacy(sqlite_engine)
        assert _fk_edges(sqlite_engine) == {
            ("source_version_id", "source_versions", "id"),
            ("source_span_id", "source_spans", "id"),
        }

    def test_migration_restores_all_three_exact_targets(self, sqlite_engine):
        import brain.migrate as migrate_module

        self._make_legacy(sqlite_engine)
        before = _fk_edges(sqlite_engine)
        assert before != EXPECTED_FKS, "precondition: legacy must be missing an FK"

        original = migrate_module.engine
        migrate_module.engine = sqlite_engine
        try:
            applied = migrate_module.add_nullable_evidence_span()
        finally:
            migrate_module.engine = original

        assert applied == ["proposal_evidence.source_span_id"]
        after = _fk_edges(sqlite_engine)
        assert after == EXPECTED_FKS, (
            f"rebuild changed the FK set.\n  lost:     {before - after}\n"
            f"  expected: {EXPECTED_FKS}\n  got:      {after}"
        )

    def test_span_is_nullable_and_rows_survive(self, sqlite_engine):
        import brain.migrate as migrate_module

        self._make_legacy(sqlite_engine)
        with sqlite_engine.begin() as conn:
            # Only the evidence rows matter here: this test asserts they survive
            # the rebuild and that the constraint is relaxed. SQLite does not
            # enforce FKs unless PRAGMA foreign_keys=ON, and _make_legacy turns
            # them off, so the parent rows are not needed and inserting into
            # source_versions would trip its own unrelated NOT NULL columns.
            conn.execute(
                text(
                    "INSERT INTO proposal_evidence VALUES "
                    "('p_1','sv_1','sp_1'), ('p_2','sv_1','sp_1')"
                )
            )

        original = migrate_module.engine
        migrate_module.engine = sqlite_engine
        try:
            migrate_module.add_nullable_evidence_span()
        finally:
            migrate_module.engine = original

        with sqlite_engine.connect() as conn:
            kept = conn.execute(
                text(
                    "SELECT proposal_id, source_version_id, source_span_id "
                    "FROM proposal_evidence ORDER BY proposal_id"
                )
            ).all()
            nullable = {
                c["name"]: c["nullable"]
                for c in inspect(sqlite_engine).get_columns("proposal_evidence")
            }
        assert kept == [("p_1", "sv_1", "sp_1"), ("p_2", "sv_1", "sp_1")]
        assert nullable["source_span_id"] is True, "the constraint was not relaxed"
        assert nullable["proposal_id"] is False, "the PK must stay NOT NULL"

    def test_migration_is_idempotent_on_sqlite(self, sqlite_engine):
        import brain.migrate as migrate_module

        self._make_legacy(sqlite_engine)
        original = migrate_module.engine
        migrate_module.engine = sqlite_engine
        try:
            assert migrate_module.add_nullable_evidence_span() == [
                "proposal_evidence.source_span_id"
            ]
            assert migrate_module.add_nullable_evidence_span() == []
            assert _fk_edges(sqlite_engine) == EXPECTED_FKS
        finally:
            migrate_module.engine = original


@pytest.fixture
def pg_engine():
    """A private Postgres database for the native DROP NOT NULL path."""
    import os
    import uuid as _uuid

    url = os.environ.get("BRAIN_TEST_POSTGRES_URL", "")
    if not url:
        if os.environ.get("BRAIN_REQUIRE_POSTGRES_TESTS"):
            raise RuntimeError(
                "BRAIN_REQUIRE_POSTGRES_TESTS is set but BRAIN_TEST_POSTGRES_URL "
                "is empty — Postgres migration tests are required in this "
                "environment."
            )
        pytest.skip("BRAIN_TEST_POSTGRES_URL not set")

    from sqlalchemy.engine import make_url

    name = f"brain_mig_{_uuid.uuid4().hex[:12]}"
    db_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - re-raised when required
        if os.environ.get("BRAIN_REQUIRE_POSTGRES_TESTS"):
            raise RuntimeError(f"Postgres required but CREATE DATABASE failed: {exc}") from exc
        admin.dispose()
        pytest.skip(f"Postgres unreachable and not required here: {exc}")

    engine = create_engine(db_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


class TestPostgresTakesTheNativePath:
    """Postgres must not run the SQLite rebuild at all."""

    def test_fresh_schema_keeps_all_three_fks(self, pg_engine):
        assert _fk_edges(pg_engine) == EXPECTED_FKS

    def test_relaxing_not_null_preserves_every_fk(self, pg_engine):
        import brain.migrate as migrate_module

        with pg_engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE proposal_evidence ALTER COLUMN source_span_id SET NOT NULL")
            )
        assert inspect(pg_engine).get_columns("proposal_evidence")[2]["nullable"] is False

        original = migrate_module.engine
        migrate_module.engine = pg_engine
        try:
            applied = migrate_module.add_nullable_evidence_span()
            # Idempotent, and the table is never dropped or renamed.
            assert migrate_module.add_nullable_evidence_span() == []
        finally:
            migrate_module.engine = original

        assert applied == ["proposal_evidence.source_span_id"]
        cols = {
            c["name"]: c["nullable"] for c in inspect(pg_engine).get_columns("proposal_evidence")
        }
        assert cols["source_span_id"] is True
        assert cols["proposal_id"] is False
        # The point of the native path: constraints are untouched.
        assert _fk_edges(pg_engine) == EXPECTED_FKS

    def test_table_identity_is_unchanged(self, pg_engine):
        """The rebuild path would change the table's oid; native must not.

        An oid comparison is what distinguishes "constraint relaxed in place"
        from "table dropped and recreated under the same name", which the
        column and FK assertions alone cannot see.
        """
        import brain.migrate as migrate_module

        def oid() -> int:
            # Engine has no .scalar(); go through a Connection.
            with pg_engine.connect() as conn:
                return conn.execute(text("SELECT 'proposal_evidence'::regclass::oid")).scalar_one()

        oid_before = oid()
        with pg_engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE proposal_evidence ALTER COLUMN source_span_id SET NOT NULL")
            )
        original = migrate_module.engine
        migrate_module.engine = pg_engine
        try:
            migrate_module.add_nullable_evidence_span()
        finally:
            migrate_module.engine = original
        assert oid_before == oid(), "the table was rebuilt on Postgres"
