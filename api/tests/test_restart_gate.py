"""RELEASE GATE: knowledge survives a restart and stays citable.

The bug this pins (pre-existing since M2, shipped in v1.0.1): `knowledge_fts`
was declared contentless, so after the FIRST restart — the moment lifespan ran
`rebuild_fts` over a database that already held approved knowledge — the ranked
index handed back NULL ids, `search_knowledge` matched `id IN (NULL)` against
nothing, and returned [] without reaching the ILIKE fallback. The Brain could no
longer find its own approved knowledge, and every question abstained.

It survived the suite because unit tests never boot the lifespan, and because the
assertion in test_retrieval.py was a bare count that `[None]` satisfied.

So this test is deliberately shaped like the incident, not like a unit test:
two separate application lifespans over one persistent database file, exercising
the public HTTP API end to end.

  create DB -> capture -> approve -> close app
    -> start app AGAIN -> search -> the same knowledge is retrievable
    -> ask -> grounded -> the citation still points at the real source excerpt

This is the shape that matters. Keep it as a release gate: if it fails, the
product's core promise is broken regardless of what else passes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VENV_PY = str(REPO / ".venv" / "bin" / "python")

STATEMENT = "We charge enterprise customers an annual fee"
RATIONALE = "because monthly billing caused churn"
QUESTION = "What is our enterprise pricing model?"
# A substring that must appear in the returned citation excerpt, proving the
# citation still resolves to real source text rather than an empty stub.
EXCERPT_PROBE = "annual fee"


# --- driver script: one boot of the real app, against a persistent database --

_DRIVER = textwrap.dedent(
    """
    import json, os, sys
    sys.path.insert(0, {api_path!r})
    import logging; logging.disable(logging.WARNING)

    import brain.main as M
    from fastapi.testclient import TestClient

    H = {{"X-Brain-Token": os.environ["BRAIN_OWNER_TOKEN"]}}
    phase = sys.argv[1]
    out = {{}}

    # A real lifespan: this is what a server start does, including ensure_fts
    # and rebuild_fts. That startup path is exactly where the bug lived.
    with TestClient(M.app) as client:
        if phase == "prepare":
            r = client.post("/api/v1/sources", headers=H, json={{
                "title": "Pricing policy",
                "content": "{statement} {rationale}.",
                "kind": "note",
                "sensitivity": "public",
            }})
            out["capture_status"] = r.status_code

            props = client.get("/api/v1/proposals", headers=H).json()
            props = props if isinstance(props, list) else props.get("items", [])
            pending = [p for p in props if p.get("status") == "proposed"]
            out["pending"] = len(pending)

            approved = []
            for p in pending:
                ar = client.post(
                    f"/api/v1/proposals/{{p['id']}}/approve", headers=H,
                    json={{"statement": p.get("statement", ""),
                          "type": p.get("type", "decision")}},
                )
                if ar.status_code == 200:
                    approved.append(p["id"])
            out["approved"] = approved

            k = client.get("/api/v1/knowledge", headers=H).json()
            k = k if isinstance(k, list) else k.get("items", [])
            out["canonical"] = [{{"id": i["id"], "statement": i["statement"]}} for i in k]
        else:
            # --- the restart: nothing above has run in THIS process ---
            k = client.get("/api/v1/knowledge", headers=H).json()
            k = k if isinstance(k, list) else k.get("items", [])
            out["canonical_after_restart"] = [
                {{"id": i["id"], "statement": i["statement"]}} for i in k
            ]

            # Raw index contents: proves ids are stored, not NULL. This table
            # is SQLite-only, so probe it ONLY on SQLite — querying it on
            # PostgreSQL raises, and because a failed statement aborts the whole
            # transaction there, the error would poison this session and make
            # the search_fts call below return [] (which is exactly the
            # poisoning pattern the production code was fixed for; the driver
            # must not reintroduce it).
            from brain.database import SessionLocal
            from brain.retrieval import FTS_TABLE, is_postgres, search_fts
            from sqlalchemy import text
            with SessionLocal() as db:
                if is_postgres(db):
                    out["fts_backend"] = "tsvector/gin"
                else:
                    out["fts_backend"] = "fts5"
                    try:
                        rows = db.execute(text(
                            f"SELECT knowledge_id FROM {{FTS_TABLE}}"
                        )).fetchall()
                        out["fts_ids"] = [r[0] for r in rows]
                    except Exception as exc:
                        db.rollback()
                        out["fts_error"] = f"{{type(exc).__name__}}: {{exc}}"
                        out["fts_ids"] = []
                out["search_fts"] = [
                    i for i in (search_fts(db, "{excerpt_probe}") or [])
                ]

            chat = client.post("/api/v1/chat", headers=H,
                               json={{"question": "{question}"}})
            out["chat_status"] = chat.status_code
            if chat.status_code == 200:
                d = chat.json()
                out["grounded"] = d.get("grounded")
                out["answer"] = d.get("answer")
                out["citations"] = [
                    {{
                        "knowledge_id": c.get("knowledge_id"),
                        "source_id": c.get("source_id"),
                        "source_title": c.get("source_title"),
                        # The schema field is `excerpt`, populated from the
                        # knowledge row's source_excerpt. Reading
                        # `source_excerpt` here silently yielded None.
                        "excerpt": c.get("excerpt"),
                    }}
                    for c in d.get("citations", [])
                ]
            else:
                out["chat_body"] = chat.text[:300]

    print("RESULT_JSON:" + json.dumps(out))
    """
)


def _boot(phase: str, db_path: Path, dialect_url: str | None = None) -> dict:
    """Run one full application lifespan in a subprocess and parse its report.

    A subprocess is essential: two lifespans inside one pytest process share
    module-level engine state, so they would not model a real restart.
    """
    import json

    script = _DRIVER.format(
        api_path=str(REPO / "api"),
        statement=STATEMENT,
        rationale=RATIONALE,
        question=QUESTION,
        excerpt_probe=EXCERPT_PROBE,
    )
    script_path = db_path.parent / f"_driver_{phase}.py"
    script_path.write_text(script)

    env = dict(os.environ)
    env["BRAIN_DATABASE_URL"] = dialect_url or f"sqlite:///{db_path}"
    env["BRAIN_OWNER_TOKEN"] = "release-gate-token"
    env["BRAIN_SEED_DEMO"] = "false"
    env["BRAIN_STRICT_LOCAL"] = "true"

    proc = subprocess.run(
        [VENV_PY if Path(VENV_PY).exists() else sys.executable, str(script_path), phase],
        capture_output=True,
        text=True,
        timeout=240,
        env=env,
        cwd=str(REPO),
    )
    script_path.unlink(missing_ok=True)
    marker = "RESULT_JSON:"
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise AssertionError(
        f"driver produced no result for phase={phase}\n"
        f"rc={proc.returncode}\nSTDOUT:\n{proc.stdout[-2500:]}\n"
        f"STDERR:\n{proc.stderr[-2500:]}"
    )


class TestKnowledgeSurvivesRestartSQLite:
    def test_restart_gate(self, tmp_path):
        db_path = tmp_path / "gate.db"

        # --- boot 1: create, capture, approve, then the process exits ---
        prep = _boot("prepare", db_path)
        assert prep["capture_status"] in (200, 201), prep
        assert prep["pending"] >= 1, f"extraction produced no proposals: {prep}"
        assert prep["approved"], f"nothing was approved: {prep}"
        assert prep["canonical"], f"no canonical knowledge created: {prep}"
        canonical_ids = {k["id"] for k in prep["canonical"]}

        # --- boot 2: a genuine restart against the same database file ---
        post = _boot("verify", db_path)

        # 0. This gate must be exercising the FTS5 backend on SQLite.
        assert post["fts_backend"] == "fts5", post

        # 1. The approved knowledge is still there.
        assert {k["id"] for k in post["canonical_after_restart"]} == canonical_ids, (
            f"knowledge did not survive the restart: {post}"
        )

        # 2. The index stored real ids, not NULLs (the contentless regression).
        assert post.get("fts_error") in (None, ""), f"index read failed: {post}"
        assert post["fts_ids"], "FTS index is empty after restart"
        assert all(i is not None for i in post["fts_ids"]), (
            f"FTS index returned NULL knowledge_ids: {post['fts_ids']}"
        )
        assert set(post["fts_ids"]) & canonical_ids, (
            f"index holds ids that are not canonical knowledge: {post}"
        )

        # 3. Search finds it again.
        assert post["search_fts"], f"ranked search found nothing after restart: {post}"
        assert set(post["search_fts"]) & canonical_ids

        # 4. The answer is grounded, not an abstention.
        assert post["chat_status"] == 200, post
        assert post["grounded"] is True, (
            f"the Brain abstained on its own approved knowledge after a restart: "
            f"answer={post.get('answer')!r}"
        )

        # 5. The citation survives with real provenance.
        assert post["citations"], f"grounded answer carried no citations: {post}"
        cite = post["citations"][0]
        assert cite["knowledge_id"] in canonical_ids
        assert cite["source_id"], "citation lost its source link"
        assert cite["excerpt"], "citation lost its exact excerpt"
        assert EXCERPT_PROBE in cite["excerpt"].lower(), (
            f"citation excerpt no longer matches the approved wording: {cite['excerpt']!r}"
        )


@pytest.fixture
def pg_gate_url():
    """A private PostgreSQL database for the same gate, on the other dialect."""
    import uuid as _uuid

    url = os.environ.get("BRAIN_TEST_POSTGRES_URL", "")
    if not url:
        if os.environ.get("BRAIN_REQUIRE_POSTGRES_TESTS"):
            raise RuntimeError(
                "BRAIN_REQUIRE_POSTGRES_TESTS is set but BRAIN_TEST_POSTGRES_URL "
                "is empty — the Postgres restart gate is required in CI."
            )
        pytest.skip("BRAIN_TEST_POSTGRES_URL not set")

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    name = f"brain_gate_{_uuid.uuid4().hex[:12]}"
    db_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - re-raised when required
        if os.environ.get("BRAIN_REQUIRE_POSTGRES_TESTS"):
            raise RuntimeError(
                f"Postgres restart gate required but CREATE DATABASE failed: {exc}"
            ) from exc
        admin.dispose()
        pytest.skip(f"Postgres unreachable and not required here: {exc}")

    yield db_url

    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


class TestKnowledgeSurvivesRestartPostgres:
    def test_restart_gate(self, tmp_path, pg_gate_url):
        """The same gate on the production dialect.

        This is where a hosted Brain would have failed first: the FTS5 index
        never existed there, so search silently used ILIKE, and a swallowed
        probe error aborted the transaction outright.
        """
        prep = _boot("prepare", tmp_path / "unused.db", dialect_url=pg_gate_url)
        assert prep["capture_status"] in (200, 201), prep
        assert prep["approved"], f"nothing was approved: {prep}"
        canonical_ids = {k["id"] for k in prep["canonical"]}

        post = _boot("verify", tmp_path / "unused.db", dialect_url=pg_gate_url)

        # 0. This gate must be exercising the tsvector/GIN backend, not ILIKE.
        # Without this a silent degradation to the fallback would still pass.
        assert post["fts_backend"] == "tsvector/gin", post

        assert {k["id"] for k in post["canonical_after_restart"]} == canonical_ids
        assert post["chat_status"] == 200, post
        assert post["grounded"] is True, (
            f"Postgres Brain abstained on its own approved knowledge after a "
            f"restart: answer={post.get('answer')!r}"
        )
        assert post["citations"], f"grounded answer carried no citations: {post}"
        cite = post["citations"][0]
        assert cite["knowledge_id"] in canonical_ids
        assert cite["source_id"] and cite["excerpt"]
        assert EXCERPT_PROBE in cite["excerpt"].lower()
        # On PostgreSQL there is no knowledge_fts table, so the ranked ids come
        # from the tsvector index instead. Either way they must be real.
        assert post["search_fts"], f"Postgres ranked search found nothing: {post}"
        assert all(i is not None for i in post["search_fts"])
