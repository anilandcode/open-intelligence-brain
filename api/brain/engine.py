"""The memory engine boundary.

The engine extracts facts and answers questions. It does not decide what is
true: that is the review gate, and canonical knowledge stays in our database
whether or not the engine is reachable.

Two implementations ship:

- `DeterministicEngine` — the local regex extractor, no network. Always
  available, never the source of a claim about intelligence.
- `SupermemoryEngine` — the hosted engine. Its graph derives facts it was never
  told, flags them `isInference: true`, down-weights them in search, and serves
  a review queue we adopt as our proposal queue.

Two rules this module exists to enforce:

1. **Strict local mode rejects a hosted request before any network call.** The
   check is in `get_engine`, not inside the client, so a code path that forgets
   to ask still cannot dial out.
2. **An engine failure is never allowed to fail a read.** Every call degrades
   to empty rather than raising, because the product's system of record is our
   database and losing access to it is worse than losing a suggestion.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# The engine's own vocabulary for the three review decisions, mapped onto ours.
REVIEW_ACTIONS = {"approve", "decline", "undo"}

# The engine will accept a document long before it has run a model over it, so
# the readiness probe has to wait long enough to see extraction actually
# happen. These bound a slow check rather than a request; it is cached, and
# live extraction is far quicker than the full window.
PROBE_POLL_SECONDS = 3
PROBE_POLLS = 5
PROBE_TTL_SECONDS = 300.0

# The engine validates container tags on every request against
# `^[a-zA-Z0-9_:-]+$` and a 100-character ceiling. A tag it rejects is not an
# error we see at read time: the write that carried it fails, so that company's
# content silently never reaches the engine. Validating here turns a silent
# data gap into a refused capture.
CONTAINER_TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_:-]{1,100}$")


class ContainerTagRejected(ValueError):
    """A workspace id cannot be expressed as a valid container tag."""


def container_tag_for(workspace_id: str) -> str:
    """The container tag that isolates one workspace inside the hosted org.

    Container tags are the engine's hard authorization boundary, so this is the
    only place a workspace id becomes an engine identifier. Team and sensitivity
    travel as metadata and are filtered by us, never by a second tag: a hard
    team boundary would break cross-team questions the Brain exists to answer.

    Scoped engine keys cannot be used here. Their allowed endpoints cover
    documents, memories, search and profiles, but not the inferred-memory
    review queue, so a scoped key cannot read derived facts or record a
    decision. The org master key is therefore the only usable credential, and
    this function is the only thing isolating one company from another on the
    engine side.

    Today every workspace id is `ws_` plus 16 hex characters, so the pattern
    cannot fail from a user-supplied value. The check exists because that is a
    property of the current creation path rather than of the type, and a
    restored or imported workspace is exactly the kind of change that breaks
    such an assumption.
    """
    tag = f"org_{workspace_id}"
    if not CONTAINER_TAG_PATTERN.match(tag):
        raise ContainerTagRejected(
            f"workspace id {workspace_id!r} cannot be expressed as a container tag"
        )
    return tag


@dataclass(frozen=True)
class DerivedFact:
    """One fact the engine derived, awaiting review."""

    memory_id: str
    text: str
    support_count: int = 0
    created_at: str = ""

    @property
    def confidence_hint(self) -> str:
        return "strong" if self.support_count >= 3 else "weak"


@dataclass(frozen=True)
class EngineStatus:
    name: str
    available: bool
    detail: str = ""
    container_tag: str = ""
    degraded: bool = False


class MemoryEngine(Protocol):
    name: str

    def available(self) -> EngineStatus: ...

    def ingest(
        self, content: str, container_tag: str, metadata: dict | None = None
    ) -> str: ...

    def derived(self, document_id: str, limit: int = 50) -> list[DerivedFact]: ...

    def review(
        self, container_tag: str, memory_id: str, action: str
    ) -> bool: ...

    def forget(self, container_tag: str) -> None: ...


class DeterministicEngine:
    """No network, no model, no derivation. The floor, not the ceiling.

    It reports what the existing extractor already does, so the interface has a
    working implementation before any hosted key exists. It never claims to
    have inferred anything, because it has not.
    """

    name = "deterministic"

    def available(self) -> EngineStatus:
        return EngineStatus(name=self.name, available=True, detail="Local extraction, no inference")

    def ingest(self, content: str, container_tag: str, metadata: dict | None = None) -> str:
        return ""

    def derived(self, document_id: str, limit: int = 50) -> list[DerivedFact]:
        return []

    def review(self, container_tag: str, memory_id: str, action: str) -> bool:
        return False

    def forget(self, container_tag: str) -> None:
        return None


class SupermemoryEngine:
    """The hosted engine.

    Every call is wrapped: a timeout, a 500, or a malformed body must not take
    the API down with it. A failed call returns empty and the caller proceeds on
    our own data, which is the whole reason the product still works when this
    is unreachable.
    """

    name = "supermemory"

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        # Readiness is observed, not read, so it is cached: -inf forces the
        # first call to probe, and a probe that cannot run assumes healthy
        # rather than reporting a fault it did not observe.
        self._probe_checked_at = float("-inf")
        self._probe_result = True

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def available(self) -> EngineStatus:
        """Probe by listing an inferred queue we do not expect to exist.

        A cheap authenticated read. It proves the key and the network, and it
        is read-only, so a misconfigured engine never writes anything on the
        way to finding out it is misconfigured.

        Reachability is not the same as usefulness. A self-hosted engine with
        no model provider configured answers every request, accepts every
        document, and then extracts nothing from any of them, so a reachable
        engine is reported as degraded rather than healthy. Otherwise a company
        ingests everything and gets an empty proposal queue with no signal that
        anything went wrong.
        """
        try:
            response = httpx.get(
                f"{self.base_url}/v3/container-tags/healthcheck/inferred",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return EngineStatus(name=self.name, available=False, detail=type(exc).__name__)
        # 200 and 404 both mean the engine answered: the first for a real
        # queue, the second because the tag is empty. 401 and 5xx do not.
        if response.status_code not in (200, 404):
            return EngineStatus(
                name=self.name, available=False, detail=f"HTTP {response.status_code}"
            )
        if self._model_provider_configured():
            return EngineStatus(name=self.name, available=True, detail="reachable")
        return EngineStatus(
            name=self.name,
            available=True,
            degraded=True,
            detail="engine reachable but no model provider configured, so it "
            "accepts content and extracts nothing from it",
        )

    def _delete_probe_document(self, document_id: str) -> None:
        """Remove the probe document so readiness checks leave nothing behind.

        Without this the probe grows the healthcheck container by one document
        every cache window, forever, in a store whose own license counts
        documents against a 10k ceiling. Cleanup is best effort: a probe that
        cannot delete has still answered its question, and must not turn a
        health check into an error.
        """
        if not document_id:
            return
        try:
            httpx.delete(
                f"{self.base_url}/v3/documents/{document_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("engine probe cleanup failed: %s", type(exc).__name__)

    def _model_provider_configured(self) -> bool:
        """Whether the engine can actually extract, by asking it to try.

        The engine exposes no endpoint for its own model configuration, so
        readiness cannot be read and has to be observed. Extraction is
        asynchronous: a document is accepted, then chunked and embedded
        locally, and only then does the model run. So a fresh probe document
        that produces no memory shortly after acceptance means no working
        model, which is the state that otherwise fails silently.

        Probing writes to the healthcheck tag, which is why it targets that and
        never a real workspace. The document is deleted afterwards whatever the
        outcome, so a readiness check cannot slowly fill a company's store. The
        answer is cached because it cannot change quickly and the probe sits on
        the overview request path.
        """
        if time.monotonic() < self._probe_checked_at + PROBE_TTL_SECONDS:
            return self._probe_result

        self._probe_checked_at = time.monotonic()
        tag = "org_brain_healthcheck"
        # A long, specific claim. Short or generic text tends to be stored as a
        # document chunk without ever reaching the memory agent.
        #
        # Every probe must assert facts the store has never seen. The engine
        # de-duplicates semantically, not textually: a fixed sentence works
        # exactly once, and a probe that merely adds a new reference number
        # still describes facts already in memory, so the engine correctly
        # creates no memory and this check reports a healthy engine as having no
        # model provider at all. The uniqueness therefore has to sit in the
        # SUBJECT of the claim — a declaration number the store has never held.
        nonce = f"{time.time_ns() % 100_000_000:08d}"
        probe = (
            f"Readiness probe HD{nonce}: Halden Logistics filed customs "
            f"declaration {nonce} for the Bergen corridor, and the port "
            f"authority confirmed receipt of declaration {nonce} on the day "
            "it was submitted."
        )
        document_id = ""
        try:
            response = httpx.post(
                f"{self.base_url}/v3/documents",
                headers=self._headers(),
                json={"content": probe, "containerTag": tag},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                # Cannot probe, so do not assert health we did not observe.
                log.warning("engine probe rejected with %s", response.status_code)
                self._probe_result = True
                return self._probe_result
            try:
                document_id = str(response.json().get("id") or "")
            except ValueError:
                document_id = ""
        except httpx.HTTPError:
            self._probe_result = True
            return self._probe_result

        try:
            for _ in range(PROBE_POLLS):
                time.sleep(PROBE_POLL_SECONDS)
                if not document_id:
                    continue
                try:
                    doc = httpx.get(
                        f"{self.base_url}/v3/documents/{document_id}",
                        headers=self._headers(),
                        timeout=self.timeout,
                    )
                except httpx.HTTPError:
                    continue
                if doc.status_code != 200:
                    continue
                try:
                    body = doc.json()
                except ValueError:
                    continue
                if body.get("memories"):
                    # The document finished with at least one memory: a model
                    # ran. Any memory counts, not only inferences — a short
                    # probe text may yield verbatim memories without ever
                    # triggering a causal inference, and that still proves
                    # extraction works.
                    self._probe_result = True
                    return self._probe_result
                if body.get("status") in ("done", "failed"):
                    # Finalized with zero memories. The server's own log for
                    # this shape reads "0 memories (memory generation failed)".
                    break

            self._probe_result = False
            log.warning(
                "engine finalized a document with no memories, so no model "
                "provider is configured"
            )
            return self._probe_result
        finally:
            # Runs on every exit above, including the early returns, so a probe
            # that has to be retried does not stack documents in the engine.
            self._delete_probe_document(document_id)

    def ingest(self, content: str, container_tag: str, metadata: dict | None = None) -> bool:
        """Send content for extraction. Accepts fast, indexes in the background.

        The engine queues this, so a slow ingest is expected and must not block
        the capture request that triggered it.
        """
        payload: dict = {"content": content, "containerTag": container_tag}
        if metadata:
            payload["metadata"] = metadata
        try:
            response = httpx.post(
                f"{self.base_url}/v3/documents",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("engine ingest failed: %s", type(exc).__name__)
            return ""
        if response.status_code >= 400:
            log.warning("engine ingest returned %s", response.status_code)
            return ""
        try:
            return str(response.json().get("id") or "")
        except ValueError:
            return ""

    def derived(self, document_id: str, limit: int = 50) -> list[DerivedFact]:
        """The inferred facts one ingested document produced.

        Read from the document itself, not the container's `/inferred` list:
        live testing against the self-hosted engine showed the list endpoint
        reports an empty queue even when the document carries inferred
        memories, while `GET /v3/documents/{id}` returns every memory with its
        `isInference` flag. Matching by container was also wrong for a second
        reason — it attached one source's facts to whichever source synced
        first. The document id is the only key that knows what it came from.
        """
        if not document_id:
            return []
        try:
            response = httpx.get(
                f"{self.base_url}/v3/documents/{document_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("engine derived failed: %s", type(exc).__name__)
            return []
        if response.status_code != 200:
            return []
        try:
            body = response.json()
        except ValueError:
            return []
        facts = []
        for row in body.get("memories") or []:
            text = (row.get("memory") or "").strip()
            if not text or not row.get("isInference"):
                # Only inferences need a human decision. Verbatim memories
                # already carry their own provenance and skip the queue.
                continue
            facts.append(
                DerivedFact(
                    memory_id=row.get("id", ""),
                    text=text,
                    support_count=int(row.get("parentCount") or 0),
                    created_at=row.get("createdAt") or "",
                )
            )
        return facts[:limit]

    def review(self, container_tag: str, memory_id: str, action: str) -> bool:
        """Record an approval decision with the engine.

        Our table is the system of record; this tells the engine which way the
        fact resolved so its search ranking agrees with our canonical state.
        """
        if action not in REVIEW_ACTIONS:
            raise ValueError(f"Unknown review action: {action}")
        try:
            response = httpx.post(
                f"{self.base_url}/v3/container-tags/{container_tag}/inferred/{memory_id}/review",
                headers=self._headers(),
                json={"action": action},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("engine review failed: %s", type(exc).__name__)
            return False
        return response.status_code < 400

    def forget(self, container_tag: str) -> None:
        """Drop a container. Only used when a workspace itself is removed."""
        try:
            httpx.delete(
                f"{self.base_url}/v3/container-tags/{container_tag}",
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("engine forget failed: %s", type(exc).__name__)


@dataclass
class EngineRegistry:
    """Holds the active engine and remembers why if there is not one."""

    _engine: MemoryEngine = field(default_factory=DeterministicEngine)
    reason: str = ""


_registry = EngineRegistry()


def get_engine() -> MemoryEngine:
    """The active engine, honouring strict local mode.

    Strict mode is checked here, before a client is constructed, so a hosted
    request is refused without a socket ever being opened.

    The reason is recorded on every call rather than only on a change, because a
    cold start with no key never transitions: the registry already holds the
    local engine, so the cause would go unrecorded and the interface would show
    only the generic fallback.
    """
    settings = get_settings()
    if settings.strict_local:
        _registry._engine = DeterministicEngine()
        _registry.reason = "strict local mode: hosted engine refused"
        return _registry._engine

    if not settings.supermemory_api_key:
        _registry._engine = DeterministicEngine()
        _registry.reason = "no BRAIN_SUPERMEMORY_API_KEY configured"
        return _registry._engine

    # Reuse the live engine rather than building a new one per call. A fresh
    # instance would discard the probe cache, so every overview would re-probe
    # and pay the full wait for an answer we already have.
    if (
        isinstance(_registry._engine, SupermemoryEngine)
        and _registry._engine.base_url == settings.supermemory_base_url.rstrip("/")
        and _registry._engine.api_key == settings.supermemory_api_key
    ):
        return _registry._engine

    engine = SupermemoryEngine(
        base_url=settings.supermemory_base_url,
        api_key=settings.supermemory_api_key,
        timeout=settings.supermemory_timeout,
    )
    _registry._engine = engine
    _registry.reason = ""
    return engine


def engine_status(workspace_id: str | None = None) -> EngineStatus:
    """The engine plus why it is not in use, for the interface to show.

    A silent fallback is how a deployment ends up quietly running on regexes
    and believing it is running on a model, so the reason travels with it. A
    recorded cause wins over the generic one: "no key configured" is actionable
    in a way that "no hosted engine configured" is not.
    """
    engine = get_engine()
    status = engine.available()
    reason = _registry.reason
    if not reason and engine.name == "deterministic":
        reason = "no hosted engine configured"
    detail = f"{status.detail}; {reason}" if reason else status.detail
    tag = container_tag_for(workspace_id) if workspace_id and engine.name != "deterministic" else ""
    if tag:
        detail = f"{detail}; tag={tag}"
    # Rebuilt, not passed through: a dropped field here is what makes a degraded
    # engine report as healthy, which is the exact failure being guarded.
    return EngineStatus(
        name=status.name,
        available=status.available,
        detail=detail.strip("; "),
        container_tag=tag,
        degraded=status.degraded,
    )
