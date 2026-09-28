"""Security regressions — one test per audited finding, pinned forever.

Every test here proves a NEGATIVE that once failed: a leak, a bypass, or a
crash found by live probing on 2026-09-28. If one of these goes red, a
boundary has been removed — fix the code, not the test.

Findings covered:
1. SPA catch-all served arbitrary files (../%2f traversal) — .env, the DB.
2. MCP HTTP ignored the caller's scope (hardcoded owner over the default ws).
3. ask_brain ValidationError: Citation vs CitationResult model_validate.
4. /export handed a member private sources (no ReadScope).
5. usage_events missing on fresh DBs (lazy import after create_all) + usage
   counts leaked private rows to members.
6. worker._execute_tool crashed on any search match (tuple indexing on ORM
   objects) and queried status "pending" instead of "proposed".
7. /workspaces/{slug}/tokens listed raw credentials.
8. /evaluation accepted a caller-named jev_url (SSRF) and any role.
9. /restore + /restore/preview accepted a member token.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from brain.access import ReadScope, ensure_default_workspace, grant_workspace
from brain.database import SessionLocal
from brain.harness import Turn
from brain.main import app
from brain.models import Knowledge, Proposal, Source, Workspace, new_id

OWNER = {"X-Brain-Token": "test-token"}
MEMBER = {"X-Brain-Token": "audit-member-token"}
OUTSIDER = {"X-Brain-Token": "audit-outsider-token", "X-Brain-Workspace": "audit-other"}

PRIVATE_SECRET = "nine million"
PUBLIC_FACT = "thirty days"


def _seed_ceiling_world(client: TestClient) -> None:
    """Default workspace: one private + one public APPROVED source, a member
    token, and a second workspace whose token must never see the default one.

    Uses the conftest `client` so lifespan (and therefore the FTS index) is up.
    """
    with SessionLocal() as db:
        ws = ensure_default_workspace(db)
        grant_workspace(db, ws, "audit-member-token", role="member")
        if db.get(Workspace, "ws_audit_other") is None:
            db.add(Workspace(id="ws_audit_other", slug="audit-other", name="Audit Other"))
            db.flush()
            grant_workspace(
                db, db.get(Workspace, "ws_audit_other"), "audit-outsider-token", role="owner"
            )
        db.commit()

    for title, sensitivity, secret in (
        (
            "Audit payroll",
            "private",
            f"Because of NDA, audit payroll totals {PRIVATE_SECRET} dollars "
            f"and must never be disclosed.",
        ),
        (
            "Audit handbook",
            "public",
            f"Therefore the audit refund window is {PUBLIC_FACT} for every customer.",
        ),
    ):
        r = client.post(
            "/api/v1/sources",
            headers=OWNER,
            json={
                "title": title,
                "kind": "note",
                "sensitivity": sensitivity,
                "content": secret,
            },
        )
        assert r.status_code == 201, r.text

    for proposal in client.get("/api/v1/proposals", headers=OWNER).json():
        r = client.post(
            f"/api/v1/proposals/{proposal['id']}/approve",
            headers=OWNER,
            json={
                "statement": proposal["statement"],
                "rationale": proposal.get("rationale") or "why",
            },
        )
        assert r.status_code == 200, r.text


def _frontend_mounted() -> bool:
    return any(getattr(route, "path", None) == "/{path:path}" for route in app.routes)


requires_dist = pytest.mark.skipif(
    not _frontend_mounted(),
    reason="web/dist not built; the SPA catch-all is not mounted (backend-only checkout)",
)


@requires_dist
class TestSpaCatchAllContainment:
    """Finding 1: unauthenticated arbitrary file read via %2f traversal."""

    @pytest.mark.parametrize(
        "path",
        [
            "/..%2f..%2f.env",
            "/%2e%2e/%2e%2e/.env",
            "/assets/..%2f..%2f..%2f.env",
            "/..%2f..%2fapi%2fbrain%2fconfig.py",
            "/..%2f..%2ftest-brain.db",
        ],
    )
    def test_encoded_traversal_never_serves_files_outside_dist(self, client, path):
        r = client.get(path)
        # Safe outcomes: 404 (containment check refused the resolved path) or
        # the SPA fallback answering index.html. NEVER a file from outside dist.
        assert r.status_code in (200, 404), path
        assert not r.content.startswith(b"SQLite"), f"{path} leaked the database file"
        if r.status_code == 200:
            assert r.headers["content-type"].startswith("text/html"), (
                f"{path} served a non-HTML file ({r.headers['content-type']})"
            )
        assert "BRAIN_OWNER_TOKEN" not in r.text, f"{path} leaked .env"
        assert "test-token" not in r.text, f"{path} leaked the owner token"
        assert "owner_token" not in r.text, f"{path} leaked backend source"

    def test_legitimate_spa_route_still_serves_index(self, client):
        r = client.get("/sources")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_built_asset_is_still_served(self, client):
        from pathlib import Path

        assets = Path(__file__).resolve().parents[2] / "web" / "dist" / "assets"
        if not assets.exists():
            pytest.skip("no built assets")
        asset = next(p for p in assets.iterdir() if p.is_file())
        r = client.get(f"/assets/{asset.name}")
        assert r.status_code == 200
        assert not r.headers["content-type"].startswith("text/html"), (
            "a real built asset fell through to index.html"
        )


class TestMcpHttpScopeBinding:
    """Findings 2+3: MCP over HTTP must read exactly what REST would."""

    def test_member_token_gets_member_reach_through_mcp(self, client):
        _seed_ceiling_world(client)
        rest = client.get("/api/v1/knowledge?q=audit", headers=MEMBER).json()
        assert PRIVATE_SECRET not in " ".join(item["statement"] for item in rest)

        r = client.post(
            "/api/v1/mcp/call",
            headers=MEMBER,
            json={"tool": "search_brain", "params": {"query": "payroll", "limit": 10}},
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body, body
        assert PRIVATE_SECRET not in str(body), (
            "MCP search_brain gave a member private content REST withholds"
        )

    def test_member_ask_brain_never_discloses_private_content(self, client):
        _seed_ceiling_world(client)
        r = client.post(
            "/api/v1/mcp/call",
            headers=MEMBER,
            json={"tool": "ask_brain", "params": {"question": "What does audit payroll total?"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body, body
        result = body["result"]
        # The word "audit" also appears in the PUBLIC atom, so a grounded
        # answer is legitimate here — what must never happen is the private
        # figure or the private source appearing in the answer or citations.
        assert PRIVATE_SECRET not in str(result)
        assert not any(
            "payroll" in str(c.get("source_title", "")).lower() for c in result["citations"]
        ), f"member received a citation to the private source: {result['citations']}"

    def test_member_ask_brain_abstains_when_only_private_evidence_exists(self, client):
        """A question whose ONLY match is private must produce an abstention."""
        _seed_ceiling_world(client)
        r = client.post(
            "/api/v1/mcp/call",
            headers=MEMBER,
            json={
                "tool": "ask_brain",
                "params": {"question": "How many dollars does payroll total?"},
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body, body
        result = body["result"]
        assert result["grounded"] is False, (
            f"member got a grounded answer to a private-only question: {result}"
        )
        assert result["citations"] == []
        assert PRIVATE_SECRET not in str(result)

    def test_ask_brain_returns_citations_when_grounded(self, client):
        """Finding 3: model_validate(Citation) raised ValidationError on every
        grounded answer — the flagship MCP tool never worked."""
        _seed_ceiling_world(client)
        r = client.post(
            "/api/v1/mcp/call",
            headers=OWNER,
            json={"tool": "ask_brain", "params": {"question": "What is the audit refund window?"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body, f"ask_brain still broken: {body}"
        result = body["result"]
        assert result["grounded"] is True
        assert len(result["citations"]) >= 1
        assert {"knowledge_id", "source_id", "source_title", "excerpt"} <= set(
            result["citations"][0]
        )

    def test_outsider_workspace_token_cannot_read_default_workspace(self, client):
        _seed_ceiling_world(client)
        r = client.post(
            "/api/v1/mcp/call",
            headers=OUTSIDER,
            json={"tool": "search_brain", "params": {"query": "refund", "limit": 10}},
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" not in body, body
        assert body["result"]["count"] == 0, (
            "a token granted only to another workspace read the default workspace"
        )
        assert PUBLIC_FACT not in str(body)

    def test_outsider_status_counts_only_own_workspace(self, client):
        _seed_ceiling_world(client)
        r = client.post(
            "/api/v1/mcp/call", headers=OUTSIDER, json={"tool": "brain_status", "params": {}}
        )
        assert r.status_code == 200
        counts = r.json()["result"]
        assert counts["sources"] == 0, (
            f"brain_status counted the default workspace for an outsider: {counts}"
        )


class TestExportCeiling:
    """Finding 4: export handed members private sources."""

    def test_member_export_excludes_private_sources(self, client):
        _seed_ceiling_world(client)
        r = client.get("/api/v1/export", headers=MEMBER)
        assert r.status_code == 200
        payload = r.json()
        assert "private" not in {s["sensitivity"] for s in payload["sources"]}, (
            "member export contains private sources: "
            f"{[s['title'] for s in payload['sources'] if s['sensitivity'] == 'private']}"
        )
        assert PRIVATE_SECRET not in r.text
        assert payload["knowledge"] == [] or all(
            k["statement"].find(PRIVATE_SECRET) == -1 for k in payload["knowledge"]
        )

    def test_owner_export_still_contains_everything(self, client):
        _seed_ceiling_world(client)
        payload = client.get("/api/v1/export", headers=OWNER).json()
        assert {"private", "public"} <= {s["sensitivity"] for s in payload["sources"]}
        assert payload["workspace"]["id"] == "ws_default"


class TestUsageOnFreshDatabase:
    """Finding 5: usage_events missing (lazy import) + ceiling on counts.

    Inside pytest this bug is invisible — other test modules import brain.usage
    at collection time, registering UsageEvent on Base before any create_all.
    The only honest pin is a FRESH interpreter that imports brain.main alone
    and checks the metadata, exactly like a production boot does.
    """

    def test_main_registers_usage_events_without_lazy_imports(self):
        import subprocess
        import sys

        code = (
            "import os;"
            "os.environ.setdefault('BRAIN_DATABASE_URL', 'sqlite:///:memory:');"
            "import brain.main;"
            "from brain.database import Base;"
            "assert 'usage_events' in Base.metadata.tables, "
            "'brain.main does not register UsageEvent — usage routes will 500 on a fresh database';"
            "print('registered')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert proc.returncode == 0, (
            f"fresh-process import of brain.main did not register usage_events:\n"
            f"{proc.stdout}\n{proc.stderr[-500:]}"
        )
        assert "registered" in proc.stdout

    def test_usage_events_table_exists_after_startup(self, client):
        client.get("/api/v1/overview", headers=OWNER)
        with SessionLocal() as db:
            db.execute(text("SELECT count(*) FROM usage_events"))

    def test_usage_endpoints_return_200(self, client):
        for path in ("/api/v1/usage", "/api/v1/usage/top", "/api/v1/usage/unused"):
            r = client.get(path, headers=OWNER)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"

    def test_member_usage_counts_exclude_private_atoms(self, client):
        _seed_ceiling_world(client)
        client.post(
            "/api/v1/chat", headers=OWNER, json={"question": "What does audit payroll total?"}
        )
        member = client.get("/api/v1/usage", headers=MEMBER)
        owner = client.get("/api/v1/usage", headers=OWNER)
        assert member.status_code == 200 and owner.status_code == 200
        assert member.json()["total_knowledge"] < owner.json()["total_knowledge"], (
            "member sees the owner's knowledge count — ceiling not applied"
        )

    def test_member_unused_list_stays_under_the_ceiling(self, client):
        _seed_ceiling_world(client)
        r = client.get("/api/v1/usage/unused", headers=MEMBER)
        assert r.status_code == 200
        with SessionLocal() as db:
            ws = ensure_default_workspace(db)
            readable = set(
                db.scalars(
                    select(Knowledge.id).where(
                        Knowledge.source_id.in_(ReadScope(ws.id, "member").source_ids())
                    )
                ).all()
            )
        for item in r.json():
            assert item["id"] in readable, (
                f"usage/unused leaked {item['id']} above the member ceiling"
            )


class TestWorkerTools:
    """Finding 6: worker crashed on every matching search; wrong status word."""

    @staticmethod
    def _turn(db, instructions: str) -> Turn:
        ws = ensure_default_workspace(db)
        turn = Turn(
            id=new_id("trn"),
            workspace_id=ws.id,
            channel="slack",
            action="investigate",
            status="pending",
            instructions=instructions,
            step_budget=3,
            steps_used=0,
        )
        db.add(turn)
        db.commit()
        db.refresh(turn)
        return turn

    def test_search_summary_survives_a_real_match(self, client):
        from brain.worker import _execute_tool

        _seed_ceiling_world(client)
        with SessionLocal() as db:
            summary = _execute_tool(db, self._turn(db, "payroll"), "search_knowledge")
        assert summary.startswith("Found"), summary
        assert "v1" in summary or "(v" in summary, summary

    def test_get_proposal_counts_proposed_status(self, client):
        from brain.worker import _execute_tool

        with SessionLocal() as db:
            ws = ensure_default_workspace(db)
            source = Source(
                id=new_id("src"),
                workspace_id=ws.id,
                title="W",
                kind="note",
                sensitivity="public",
                content="Whatever.",
            )
            db.add(source)
            db.flush()
            db.add(
                Proposal(
                    id=new_id("prop"),
                    workspace_id=ws.id,
                    source_id=source.id,
                    type="fact",
                    statement="S",
                    source_excerpt="Whatever.",
                    status="proposed",
                )
            )
            db.commit()
            summary = _execute_tool(db, self._turn(db, "w"), "get_proposal")
        assert summary == "Found 1 pending proposals.", summary

    def test_worker_scope_honours_the_sensitivity_ladder(self, client):
        """The duck-typed worker scope filtered by workspace only; the real
        ReadScope must still expose its ladder."""
        from brain.worker import _fake_scope

        turn = Turn(
            id="t", workspace_id="ws_x", channel="slack", action="investigate", status="pending"
        )
        scope = _fake_scope(turn)
        assert isinstance(scope, ReadScope)
        assert scope.may_read("private") is True
        assert scope.workspace_id == "ws_x"


class TestTokenListNeverLeaksCredentials:
    """Finding 7: the tokens listing returned raw principals."""

    def test_listing_shows_previews_not_tokens(self, client):
        created = client.post(
            "/api/v1/workspaces/default/tokens",
            headers=OWNER,
            json={"role": "member", "expires_in_hours": 24},
        )
        assert created.status_code == 201
        raw = created.json()["principal"]  # creation MAY return it exactly once
        assert raw.startswith("brn_")

        listed = client.get("/api/v1/workspaces/default/tokens", headers=OWNER)
        assert listed.status_code == 200
        assert raw not in listed.text, "listing returned a raw credential"
        assert "test-token" not in listed.text, "listing returned the owner token"
        rows = listed.json()
        previews = [row["principal_preview"] for row in rows]
        assert any(raw[:8] in preview for preview in previews), (
            f"the new token is not recognisable in the listing: {previews}"
        )
        assert all("principal" not in row for row in rows)

    def test_preview_cannot_reconstruct_the_token(self, client):
        from brain.access import token_preview

        raw = client.post(
            "/api/v1/workspaces/default/tokens", headers=OWNER, json={"role": "member"}
        ).json()["principal"]
        preview = token_preview(raw)
        assert len(preview) < len(raw)
        assert preview.count("…") == 1
        assert raw not in preview

    def test_member_cannot_list_tokens(self, client):
        _seed_ceiling_world(client)
        assert client.get("/api/v1/workspaces/default/tokens", headers=MEMBER).status_code == 403


class TestEvaluationNotAnSsrfVector:
    """Finding 8: caller-named jev_url + no admin gate."""

    def test_jev_url_query_param_is_not_a_route_input(self):
        query_params = None
        for route in app.routes:
            if getattr(route, "path", "") == "/api/v1/evaluation":
                query_params = {p.name for p in route.dependant.query_params}
        assert query_params is not None, "the evaluation route disappeared"
        assert "jev_url" not in query_params, (
            "the endpoint takes a caller-supplied URL again — SSRF"
        )

    def test_jev_url_comes_from_settings(self):
        from brain.config import Settings

        assert hasattr(Settings(), "jev_url")

    def test_member_cannot_run_evaluation(self, client):
        _seed_ceiling_world(client)
        assert client.get("/api/v1/evaluation", headers=MEMBER).status_code == 403


class TestRestoreIsAdminOnly:
    """Finding 9: any member token could preview or run a restore."""

    EMPTY = {
        "backup": {
            "schema_version": 3,
            "workspace": {"id": "ws_default"},
            "sources": [],
            "source_versions": [],
            "source_spans": [],
            "proposals": [],
            "proposal_evidence": [],
            "knowledge": [],
            "knowledge_revisions": [],
            "audit_events": [],
        }
    }

    def test_member_cannot_preview_restore(self, client):
        _seed_ceiling_world(client)
        assert (
            client.post("/api/v1/restore/preview", headers=MEMBER, json=self.EMPTY).status_code
            == 403
        )

    def test_member_cannot_restore(self, client):
        _seed_ceiling_world(client)
        payload = {**self.EMPTY, "confirm_empty_workspace": True}
        assert client.post("/api/v1/restore", headers=MEMBER, json=payload).status_code == 403

    def test_owner_preview_still_works(self, client):
        r = client.post("/api/v1/restore/preview", headers=OWNER, json=self.EMPTY)
        assert r.status_code == 200
        assert "valid" in r.json()
