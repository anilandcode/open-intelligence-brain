"""The engine boundary.

The engine is allowed to be slow, wrong, and unreachable. It is not allowed to
be load-bearing for a read, to dial out in strict local mode, or to fail
silently in a way that makes a deployment believe it is running on a model when
it is running on regexes.

Every network-touching test uses a local stub server, never the real host.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from brain import engine as engine_module
from brain.config import get_settings
from brain.engine import (
    ContainerTagRejected,
    DeterministicEngine,
    SupermemoryEngine,
    container_tag_for,
    engine_status,
    get_engine,
)


class StubHandler(BaseHTTPRequestHandler):
    """Replies from a per-test script, and records what it was sent."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _respond(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        StubState.bodies.append((f"{self.command} {path}", body))
        # A probe document is polled by GET and cleaned by DELETE on the same
        # path, so a test can script them apart with a "METHOD /path" key.
        status, payload = StubState.responses.get(
            f"{self.command} {path}", StubState.responses.get(path, (200, {}))
        )
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _respond
    do_POST = _respond
    do_DELETE = _respond


class StubState:
    responses: dict = {}
    bodies: list = []


@pytest.fixture
def stub_server():
    StubState.responses = {}
    StubState.bodies = []
    server = HTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def reset_registry(monkeypatch):
    for key in (
        "SUPERMEMORY_API_KEY",
        "SUPERMEMORY_BASE_URL",
        "SUPERMEMORY_TIMEOUT",
        "STRICT_LOCAL",
    ):
        monkeypatch.delenv(f"BRAIN_{key}", raising=False)
    engine_module._registry = engine_module.EngineRegistry()
    get_settings.cache_clear()
    yield
    engine_module._registry = engine_module.EngineRegistry()
    get_settings.cache_clear()


def _configure(monkeypatch, **overrides):
    base = {
        "supermemory_api_key": "sm_test_key",
        "supermemory_base_url": "https://api.supermemory.ai",
        "supermemory_timeout": "2.0",
        "strict_local": "false",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(f"BRAIN_{key.upper()}", str(value))
    get_settings.cache_clear()


def _url(server) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def _no_sleep(monkeypatch) -> None:
    """Keep the probe's real timing constants, drop only the waiting.

    The probe polls a real engine, so the wait is the behaviour under test. The
    stub answers immediately, so the sleep buys nothing and would add seconds to
    every case.
    """
    monkeypatch.setattr(engine_module.time, "sleep", lambda _seconds: None)


# --- container tag naming -------------------------------------------------


def test_container_tag_is_namespaced_by_workspace():
    """One company's rows can never be addressed as another's."""
    assert container_tag_for("ws_acme") == "org_ws_acme"
    assert container_tag_for("ws_globex") != container_tag_for("ws_acme")


def test_engine_status_does_not_drop_the_degraded_flag(stub_server, monkeypatch):
    """A rebuilt status must carry degraded through, or it reports healthy.

    engine_status() composes a new status to append the tag and the recorded
    reason. It dropped degraded on the way, so a live check showed the correct
    detail text and still claimed the engine was fine. The detail alone is not
    proof: only the flag is what the interface branches on.
    """
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (200, {"status": "done", "memories": []}),
    }
    _no_sleep(monkeypatch)
    status = engine_status("ws_acme")
    assert status.available is True
    assert status.degraded is True
    assert "no model provider" in status.detail
    assert status.container_tag == "org_ws_acme"


def test_engine_status_drops_the_tag_for_the_local_engine(monkeypatch):
    """The deterministic engine addresses no container, so it reports none."""
    status = engine_status("ws_acme")
    assert status.name == "deterministic"
    assert status.container_tag == ""


def test_repeated_get_engine_keeps_the_probe_cache(stub_server, monkeypatch):
    """Each request must not rebuild the engine and re-probe from cold.

    A new engine per call discards the cached probe result, so every overview
    would wait out the full poll window for an answer already known.
    """
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/container-tags/healthcheck/inferred": (404, {}),
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (200, {"status": "done", "memories": []}),
    }
    _no_sleep(monkeypatch)
    first = get_engine()
    first.available()
    probes = sum(1 for p, _ in StubState.bodies if p == "POST /v3/documents")
    second = get_engine()
    second.available()
    again = sum(1 for p, _ in StubState.bodies if p == "POST /v3/documents")
    assert first is second, "a new engine replaced the live one"
    assert probes == 1
    assert again == 1, "probe re-ran despite the cache"


def test_changing_the_key_builds_a_new_engine(stub_server, monkeypatch):
    """The reuse must not pin a stale credential if the key is rotated."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    first = get_engine()
    _configure(
        monkeypatch,
        supermemory_base_url=_url(stub_server),
        supermemory_timeout="2",
        supermemory_api_key="sm_rotated_key",
    )
    second = get_engine()
    assert first is not second
    assert second.api_key == "sm_rotated_key"


def test_probe_deletes_its_document(stub_server, monkeypatch):
    """A readiness check must not grow the engine's document count.

    The engine's own license counts documents against a 10k ceiling, so a probe
    that never cleans up would slowly consume a company's allowance purely by
    being asked whether it is healthy.
    """
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d-probe", "status": "queued"}),
        "/v3/documents/d-probe": (200, {"status": "done", "memories": []}),
    }
    _no_sleep(monkeypatch)
    engine = get_engine()
    engine.available()
    deletions = [p for p, _ in StubState.bodies if p == "DELETE /v3/documents/d-probe"]
    assert deletions, "probe document was never deleted"


def test_probe_cleans_up_even_when_extraction_succeeds(stub_server, monkeypatch):
    """The early return on a working engine must still clean up."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d-probe", "status": "queued"}),
        "GET /v3/documents/d-probe": (
            200,
            {"status": "done", "memories": [{"id": "m1", "memory": "x", "isInference": False}]},
        ),
    }
    _no_sleep(monkeypatch)
    engine = get_engine()
    assert engine.available().degraded is False
    assert "DELETE /v3/documents/d-probe" in [p for p, _ in StubState.bodies]


def test_probe_cleanup_failure_does_not_break_the_probe(stub_server, monkeypatch):
    """Cleanup is best effort: it must never turn a health check into an error."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d-probe", "status": "queued"}),
        "/v3/documents/d-probe": (404, {"error": "Document not found"}),
    }
    _no_sleep(monkeypatch)
    engine = get_engine()
    status = engine.available()
    assert status.degraded is True


def test_container_tag_is_never_empty():
    """A blank workspace id must not collapse to a shared, unnamespaced tag."""
    assert container_tag_for("") == "org_"


# --- a reachable engine that extracts nothing -----------------------------


def test_reachable_engine_without_a_model_is_degraded(stub_server, monkeypatch):
    """The silent failure: content is accepted and nothing is ever derived.

    A self-hosted engine with no model provider configured answers every
    request, so reachability alone reports healthy. The only symptom a company
    sees is a proposal queue that stays empty, so this has to be caught by
    probing rather than by asking whether the socket answers.
    """
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (200, {"status": "done", "memories": []}),
    }
    engine = get_engine()
    _no_sleep(monkeypatch)
    status = engine.available()
    assert status.available is True
    assert status.degraded is True
    assert "no model provider" in status.detail


def test_a_working_engine_is_not_degraded(stub_server, monkeypatch):
    """A probe that derives a memory means extraction genuinely works."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (
            200,
            {"status": "done", "memories": [{"id": "m1", "memory": "x", "isInference": True}]},
        ),
    }
    engine = get_engine()
    _no_sleep(monkeypatch)
    status = engine.available()
    assert status.available is True
    assert status.degraded is False


def test_probe_writes_only_to_the_healthcheck_tag(stub_server, monkeypatch):
    """Probing must never write into a company's own container."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (
            200,
            {"status": "done", "memories": [{"id": "m1", "memory": "x", "isInference": True}]},
        ),
    }
    engine = get_engine()
    _no_sleep(monkeypatch)
    engine.available()
    written = [
        json.loads(body or b"{}").get("containerTag", "")
        for path, body in StubState.bodies
        if path == "POST /v3/documents"
    ]
    assert written, "probe never wrote its document"
    assert all(tag.startswith("org_brain_healthcheck") for tag in written), written


def test_unreachable_engine_is_not_called_degraded(stub_server, monkeypatch):
    """A dead engine is unavailable, which is a different and clearer fault."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {"/v3/container-tags/healthcheck/inferred": (401, {})}
    engine = get_engine()
    status = engine.available()
    assert status.available is False
    assert status.degraded is False


def test_probe_result_is_cached(stub_server, monkeypatch):
    """The overview path must not re-probe on every request."""
    _configure(monkeypatch, supermemory_base_url=_url(stub_server), supermemory_timeout="2")
    StubState.responses = {
        "/v3/documents": (200, {"id": "d1", "status": "queued"}),
        "/v3/documents/d1": (
            200,
            {"status": "done", "memories": [{"id": "m1", "memory": "x", "isInference": True}]},
        ),
    }
    engine = get_engine()
    _no_sleep(monkeypatch)
    engine.available()
    first = sum(1 for p, _ in StubState.bodies if p == "POST /v3/documents")
    engine.available()
    engine.available()
    second = sum(1 for p, _ in StubState.bodies if p == "POST /v3/documents")
    assert first == 1
    assert second == 1, "probe re-ran inside the cache window"


def test_container_tag_rejects_what_the_engine_would_reject():
    """The engine validates tags on every request; we refuse first.

    A tag it rejects fails at write time, so that company's content silently
    never reaches the engine — a data gap nobody sees until they need the
    index. Better to refuse the tag where the id is turned into one.
    """
    for bad in ("acme corp", "team/sub", "a@b", 'quote"d'):
        with pytest.raises(ContainerTagRejected):
            container_tag_for(bad)


def test_container_tag_accepts_the_engine_permitted_shapes():
    for good in ("ws_default", "ws_a1b2c3", "org:acme:ws_1", "ws-acme"):
        assert container_tag_for(good) == f"org_{good}"


def test_container_tag_respects_the_length_ceiling():
    with pytest.raises(ContainerTagRejected):
        container_tag_for("w" * 100)


# --- strict local mode ----------------------------------------------------


def test_strict_local_refuses_the_hosted_engine(monkeypatch):
    _configure(monkeypatch, strict_local="true")
    assert get_engine().name == "deterministic"


def test_strict_local_never_constructs_a_client(monkeypatch):
    """The check must precede the client, not live inside it.

    If the refusal lived in the client's request method, a path that built one
    directly would still be able to dial out.
    """
    _configure(monkeypatch, strict_local="true")
    built = []
    original = SupermemoryEngine.__init__

    def spy(self, *args, **kwargs):
        built.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SupermemoryEngine, "__init__", spy)
    get_engine()
    assert built == [], "strict local mode constructed a hosted client"


def test_no_api_key_falls_back_with_a_reason(monkeypatch):
    """A silent fallback is how a deployment believes it is on a model."""
    _configure(monkeypatch, supermemory_api_key="")
    assert get_engine().name == "deterministic"
    assert "BRAIN_SUPERMEMORY_API_KEY" in engine_status().detail


def test_key_present_uses_the_hosted_engine(monkeypatch):
    _configure(monkeypatch)
    assert get_engine().name == "supermemory"


# --- failure isolation ----------------------------------------------------


def test_unreachable_engine_never_raises():
    """A dead engine must not take the API down; our database is the fallback."""
    engine = SupermemoryEngine("http://127.0.0.1:9", "k", timeout=0.5)
    assert engine.available().available is False
    assert engine.ingest("content", "org_ws") == ""
    assert engine.derived("d1") == []
    assert engine.review("org_ws", "m1", "approve") is False


def test_auth_failure_is_not_availability(stub_server):
    StubState.responses = {"/v3/container-tags/healthcheck/inferred": (401, {})}
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "bad", timeout=2.0)
    assert engine.available().available is False


def test_empty_tag_404_still_counts_as_reachable(stub_server):
    """404 means the engine answered: the tag simply has no queue yet."""
    StubState.responses = {"/v3/container-tags/org_ws/inferred": (404, {})}
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "k", timeout=2.0)
    assert engine.available().available is True


# --- the review queue contract -------------------------------------------


def test_derived_facts_map_to_the_documented_shape(stub_server):
    """Derived facts come from the document itself, inferences only.

    Live proof against the self-hosted engine: GET /v3/documents/{id} returns
    every memory with an isInference flag, while the container's /inferred list
    reported an empty queue for the very document that had produced an
    inference. Only an inference needs a human decision, so a verbatim memory
    is filtered out here.
    """
    StubState.responses = {
        "/v3/documents/d1": (
            200,
            {
                "status": "done",
                "memories": [
                    {
                        "id": "mem_a",
                        "memory": "The billing migration ships in Q3.",
                        "parentCount": 4,
                        "createdAt": "2026-01-15T10:30:00.000Z",
                        "isInference": True,
                    },
                    {"id": "mem_b", "memory": "   ", "parentCount": 1, "isInference": True},
                    {
                        "id": "mem_c",
                        "memory": "A verbatim quote.",
                        "parentCount": 1,
                        "isInference": False,
                    },
                ],
            },
        )
    }
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "k", timeout=2.0)
    facts = engine.derived("d1")
    assert len(facts) == 1, "blank text and non-inferences must be dropped"
    assert facts[0].memory_id == "mem_a"
    assert facts[0].support_count == 4
    assert facts[0].confidence_hint == "strong"


def test_review_rejects_an_unknown_action(stub_server):
    """A typo must fail loudly here, not become a silent no-op upstream."""
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "k", timeout=2.0)
    with pytest.raises(ValueError):
        engine.review("org_ws", "mem_a", "approv")


def test_review_sends_the_documented_action(stub_server):
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "k", timeout=2.0)
    assert engine.review("org_ws", "mem_a", "decline") is True
    path, body = StubState.bodies[-1]
    assert path == "POST /v3/container-tags/org_ws/inferred/mem_a/review"
    assert json.loads(body)["action"] == "decline"


def test_ingest_sends_the_container_tag(stub_server):
    """The container tag on the write is the isolation boundary; omitting it
    would file a company's content outside its own namespace."""
    StubState.responses = {"/v3/documents": (200, {"id": "d1", "status": "queued"})}
    engine = SupermemoryEngine(f"http://127.0.0.1:{stub_server.server_port}", "k", timeout=2.0)
    assert engine.ingest("Some content", "org_ws", {"team": "platform"}) == "d1"
    _, body = StubState.bodies[-1]
    payload = json.loads(body)
    assert payload["containerTag"] == "org_ws"
    assert payload["metadata"] == {"team": "platform"}


# --- the local floor ------------------------------------------------------


def test_deterministic_engine_claims_no_inference():
    """It must not report derivation it never performed."""
    engine = DeterministicEngine()
    assert engine.derived("d1") == []
    status = engine.available()
    assert status.available is True
    assert "no inference" in status.detail
