"""The engine bridge, end to end.

A derived proposal is a row an engine inferred, not a quote we extracted. It has
to survive the same review gate as any other proposal, and it must not acquire
an excerpt it never had.

The failure these tests exist to prevent: the approval gate requires immutable
evidence, a derived fact has no span, and the bridge that produced it forgot to
attach the evidence edge — leaving a permanently unapprovable row sitting in
the review queue.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from brain.access import ReadScope, ensure_default_workspace, grant_workspace
from brain.database import engine
from brain.models import Proposal, ProposalEvidence, Workspace

OWNER_TOKEN = "test-token"
WS = "ws_default"
HEADERS = {"X-Brain-Token": OWNER_TOKEN}

DERIVED = {
    "status": "done",
    "memories": [
        {
            "id": "mem_x",
            "memory": "The team keeps discussing payment retries, so the billing "
            "migration likely touches retry handling.",
            "parentCount": 5,
            "createdAt": "2026-09-01T00:00:00.000Z",
            "isInference": True,
        }
    ],
}

BODY = (
    "The platform team discussed payment retries repeatedly while planning the "
    "billing migration during the planning meetings held this quarter."
)

DOC = "d-stub"

# Recorded by the stub so a test can assert the review call actually left.
REVIEW_CALLS: list[tuple[str, bytes]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path = self.path.split("?")[0]
        if path.endswith("/review") and self.command == "POST":
            REVIEW_CALLS.append((path, json.loads(body or b"{}")))
        # The document readout is where derived facts live now: the container
        # /inferred list was observed returning empty for documents that had
        # produced inferences, so the bridge keys everything on document ids.
        payload: dict = {}
        if path == "/v3/documents" and self.command == "POST":
            payload = {"id": DOC, "status": "queued"}
        elif path == f"/v3/documents/{DOC}" and self.command == "GET":
            payload = DERIVED
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _respond
    do_POST = _respond


@pytest.fixture
def engine_stub(monkeypatch):
    """Point the engine at a local stub that always answers."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    from brain.config import get_settings

    monkeypatch.setenv("BRAIN_SUPERMEMORY_API_KEY", "sm_test")
    monkeypatch.setenv("BRAIN_SUPERMEMORY_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    get_settings.cache_clear()
    from brain import engine as engine_module

    engine_module._registry = engine_module.EngineRegistry()
    yield server
    server.shutdown()
    server.server_close()
    engine_module._registry = engine_module.EngineRegistry()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def default_workspace():
    with Session(engine) as db:
        ensure_default_workspace(db)
        grant_workspace(db, db.get(Workspace, WS), OWNER_TOKEN, role="owner")
        db.commit()


def _create_source(client) -> str:
    response = client.post(
        "/api/v1/sources",
        headers=HEADERS,
        json={"title": "derived probe", "kind": "note", "sensitivity": "internal", "content": BODY},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_derived_proposal_can_be_approved(client, engine_stub):
    """The regression: this used to return 409 forever.

    The gate requires immutable evidence before it will create canonical
    knowledge. A derived fact has no span, so the bridge has to attach the
    source version or the row is stuck.
    """
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        created = sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
    assert created == 1

    derived = [
        p
        for p in client.get("/api/v1/proposals", headers=HEADERS).json()
        if p["statement"].startswith("The team keeps discussing")
    ]
    assert len(derived) == 1

    approved = client.post(f"/api/v1/proposals/{derived[0]['id']}/approve", headers=HEADERS, json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["statement"] == derived[0]["statement"]


def test_derived_proposal_gets_an_evidence_edge(client, engine_stub):
    """Evidence is what makes it approvable, so assert the edge directly."""
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
    with Session(engine) as read_only:
        rows = (
            read_only.query(ProposalEvidence)
            .join(Proposal, Proposal.id == ProposalEvidence.proposal_id)
            .filter(Proposal.statement.like("The team keeps discussing%"))
            .all()
        )
    assert len(rows) == 1
    assert rows[0].source_version_id, "evidence must pin a source version"
    assert rows[0].source_span_id is None, "a derived fact has no single span"


def test_derived_statement_does_not_invent_an_excerpt(client, engine_stub):
    """A fabricated quote is the exact failure this product exists to prevent."""
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
    derived = [
        p
        for p in client.get("/api/v1/proposals", headers=HEADERS).json()
        if p["statement"].startswith("The team keeps discussing")
    ]
    assert derived[0]["source_excerpt"] == ""


def test_canonical_excerpt_falls_back_to_the_pinned_version(client, engine_stub):
    """No excerpt to quote, so the citation shows the bytes it came from."""
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
    derived = [
        p
        for p in client.get("/api/v1/proposals", headers=HEADERS).json()
        if p["statement"].startswith("The team keeps discussing")
    ]
    approved = client.post(f"/api/v1/proposals/{derived[0]['id']}/approve", headers=HEADERS, json={})
    assert "payment retries" in approved.json()["source_excerpt"]


def test_sync_is_idempotent(client, engine_stub):
    """Re-syncing must not fill the review queue with copies."""
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        first = sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
        second = sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
    assert first == 1
    assert second == 0


def test_derived_cannot_reach_canonical_without_approval(client, engine_stub):
    """The whole point: derived facts are proposals, not knowledge."""
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)

    statements = [k["statement"] for k in client.get("/api/v1/knowledge", headers=HEADERS).json()]
    assert not any(s.startswith("The team keeps discussing") for s in statements)


def test_strict_local_derives_nothing(client, monkeypatch):
    """Strict local mode must produce no derived rows at all."""
    from brain.config import get_settings
    from brain.services import sync_derived_proposals

    monkeypatch.setenv("BRAIN_SUPERMEMORY_API_KEY", "sm_test")
    monkeypatch.setenv("BRAIN_STRICT_LOCAL", "true")
    get_settings.cache_clear()

    source_id = _create_source(client)
    with Session(engine) as db:
        assert sync_derived_proposals(db, ReadScope(WS, "owner"), source_id) == 0
    get_settings.cache_clear()


def test_refused_approval_strands_nothing(client, engine_stub):
    """A refused approval must leave the proposal untouched, not half-applied.

    The gate checks evidence before it writes anything, because a check that
    runs afterwards can mark a proposal approved, raise, and leave a proposal
    that is decided but produced no canonical knowledge.
    """
    from sqlalchemy import select

    from brain.models import Knowledge
    from brain.services import sync_derived_proposals

    source_id = _create_source(client)
    with Session(engine) as db:
        sync_derived_proposals(db, ReadScope(WS, "owner"), source_id)
        proposal_id = db.scalar(
            select(Proposal.id).where(
                Proposal.statement.like("The team keeps discussing%")
            )
        )
    # Strip the evidence edge directly, so the gate has to refuse.
    with Session(engine) as db:
        db.query(ProposalEvidence).filter(ProposalEvidence.proposal_id == proposal_id).delete()
        db.commit()

    response = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=HEADERS, json={})
    assert response.status_code == 409

    with Session(engine) as db:
        still = db.get(Proposal, proposal_id)
        assert still is not None
        assert still.status == "proposed", "a refused approval must not consume the proposal"
        assert (
            db.scalar(select(Knowledge.id).where(Knowledge.proposal_id == proposal_id)) is None
        ), "a refused approval must not create canonical knowledge"
        # And the queue must still offer it, so the reviewer can retry.
        assert any(
            p["id"] == proposal_id
            for p in client.get("/api/v1/proposals", headers=HEADERS).json()
        )


# --- the migration on a database that already has the constraint ---------


def test_migration_relaxes_not_null_and_keeps_every_row(tmp_path):
    """An existing v2 database has this column NOT NULL.

    The migration must relax it without dropping, re-pointing, or losing a
    single provenance row.
    """
    path = tmp_path / "legacy.db"
    legacy = create_engine(f"sqlite:///{path}")
    with legacy.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE source_versions (id VARCHAR(32) NOT NULL PRIMARY KEY)
                """
            )
        )
        connection.execute(
            text("CREATE TABLE source_spans (id VARCHAR(32) NOT NULL PRIMARY KEY)")
        )
        connection.execute(
            text(
                """
                CREATE TABLE proposal_evidence (
                    proposal_id VARCHAR(32) NOT NULL,
                    source_version_id VARCHAR(32) NOT NULL,
                    source_span_id VARCHAR(32) NOT NULL,
                    PRIMARY KEY (proposal_id)
                )
                """
            )
        )
        connection.execute(text("INSERT INTO source_versions VALUES ('sv_1')"))
        connection.execute(text("INSERT INTO source_spans VALUES ('sp_1')"))
        connection.execute(
            text(
                "INSERT INTO proposal_evidence VALUES ('p_1', 'sv_1', 'sp_1'), "
                "('p_2', 'sv_1', 'sp_1')"
            )
        )

    before = inspect(legacy).get_columns("proposal_evidence")
    assert not next(c for c in before if c["name"] == "source_span_id")["nullable"]

    import brain.migrate as migrate_module

    original = migrate_module.engine
    migrate_module.engine = legacy
    try:
        applied = migrate_module.add_nullable_evidence_span()
    finally:
        migrate_module.engine = original
    assert applied == ["proposal_evidence.source_span_id"]

    after = inspect(legacy).get_columns("proposal_evidence")
    assert next(c for c in after if c["name"] == "source_span_id")["nullable"]
    with legacy.connect() as connection:
        kept = connection.execute(
            text("SELECT proposal_id, source_version_id, source_span_id FROM proposal_evidence")
        ).all()
    assert len(kept) == 2, "the migration dropped a provenance row"
    assert ("p_1", "sv_1", "sp_1") in kept

    # A null span is now accepted, which is the point.
    with legacy.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO proposal_evidence VALUES ('p_3', 'sv_1', NULL)"
            )
        )
    assert migrate_module.add_nullable_evidence_span() == []  # idempotent
    legacy.dispose()


def test_sync_route_pulls_the_sources_own_document(client, engine_stub):
    """The route exists, is scoped, and reports what it created.

    The bridge function was complete but unwired: nothing in production ever
    called it, so derived facts stayed in the engine forever. This is the
    proof the door is actually open, and the honest count behind it.
    """
    source_id = _create_source(client)
    response = client.post(
        f"/api/v1/sources/{source_id}/sync-derived", headers=HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1


def test_sync_route_is_workspace_scoped(client, engine_stub):
    """A source from another workspace must not sync anything here."""
    source_id = _create_source(client)
    other = "ws_someone_elses_brain"
    with Session(engine) as db:
        ws = Workspace(id=other, name="Other Corp", slug="other-corp")
        db.add(ws)
        db.commit()
        grant_workspace(db, ws, "someone-else", role="owner")
        db.commit()
    scoped_headers = {"X-Brain-Token": "someone-else"}
    response = client.post(
        f"/api/v1/sources/{source_id}/sync-derived", headers=scoped_headers
    )
    assert response.status_code in (403, 404)
    assert client.get("/api/v1/proposals", headers=scoped_headers).json() == []


def test_approval_is_sent_back_to_the_engine(client, engine_stub):
    """The review round-trip: a decision here updates the engine's index.

    record_review_with_engine was dead code and engine_memory_id was never
    stored, so the engine ranked facts as unresolved after our table had
    approved them. The stub records POSTs; asserting on its log is the only
    proof the call actually left.
    """
    REVIEW_CALLS.clear()
    source_id = _create_source(client)
    sync = client.post(f"/api/v1/sources/{source_id}/sync-derived", headers=HEADERS)
    assert sync.json()["created"] == 1
    derived = [
        p
        for p in client.get("/api/v1/proposals", headers=HEADERS).json()
        if p["statement"].startswith("The team keeps discussing")
    ]
    approved = client.post(
        f"/api/v1/proposals/{derived[0]['id']}/approve", headers=HEADERS, json={}
    )
    assert approved.status_code == 200

    calls = [p for p, _ in REVIEW_CALLS]
    assert len(calls) == 1, f"expected exactly one review call, got {calls}"
    assert "inferred/mem_x/review" in calls[0]
    assert REVIEW_CALLS[0][1].get("action") == "approve"


def test_unwired_source_syncs_nothing(client, engine_stub):
    """A source the engine never accepted must not borrow another's facts.

    Provenance is the product: attaching inferences to a source the engine
    never processed would fabricate the evidence chain. The document id on
    the row is the only honest link.
    """
    from brain.models import Source

    source_id = _create_source(client)
    with Session(engine) as db:
        row = db.get(Source, source_id)
        assert row.engine_document_id == DOC, "capture must store the document id"
        row.engine_document_id = ""
        db.commit()
    response = client.post(f"/api/v1/sources/{source_id}/sync-derived", headers=HEADERS)
    assert response.json()["created"] == 0
