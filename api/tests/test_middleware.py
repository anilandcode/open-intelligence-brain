"""Tests for production middleware: RequestID, SecurityHeaders, and RateLimit."""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from brain.middleware import (
    AccessLogMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)


def _hello(request):
    return JSONResponse({"status": "ok"})


def test_request_id_generated_and_echoed():
    app = Starlette(
        routes=[Route("/test", _hello)],
        middleware=[Middleware(RequestIdMiddleware)],
    )
    client = TestClient(app)

    # Generated when missing
    resp = client.get("/test")
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-ID")
    assert req_id and req_id.startswith("req_")

    # Echoed when provided
    resp2 = client.get("/test", headers={"X-Request-ID": "custom-trace-123"})
    assert resp2.headers.get("X-Request-ID") == "custom-trace-123"


def test_security_headers_present():
    app = Starlette(
        routes=[Route("/test", _hello)],
        middleware=[Middleware(SecurityHeadersMiddleware, is_production=False)],
    )
    client = TestClient(app)
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")


def test_hsts_set_in_production():
    app = Starlette(
        routes=[Route("/test", _hello)],
        middleware=[Middleware(SecurityHeadersMiddleware, is_production=True)],
    )
    client = TestClient(app)
    resp = client.get("/test")
    assert "max-age=31536000" in resp.headers.get("Strict-Transport-Security", "")


def test_rate_limit_enforcement():
    app = Starlette(
        routes=[Route("/api/v1/auth/login", _hello, methods=["POST"])],
        middleware=[
            Middleware(
                RateLimitMiddleware,
                auth_limit=3,
                write_limit=10,
                read_limit=10,
                enabled=True,
            )
        ],
    )
    client = TestClient(app)

    # First 3 requests succeed
    for _ in range(3):
        res = client.post("/api/v1/auth/login", headers={"X-Brain-Token": "test-tok-1"})
        assert res.status_code == 200

    # 4th request is rate-limited
    res4 = client.post("/api/v1/auth/login", headers={"X-Brain-Token": "test-tok-1"})
    assert res4.status_code == 429
    assert res4.headers.get("Retry-After") == "60"
    assert "Rate limit exceeded" in res4.json()["detail"]

    # Different principal bucket is NOT affected
    res_other = client.post("/api/v1/auth/login", headers={"X-Brain-Token": "diff-tok-2"})
    assert res_other.status_code == 200


def test_access_log_middleware_passes():
    app = Starlette(
        routes=[Route("/test", _hello)],
        middleware=[Middleware(AccessLogMiddleware)],
    )
    client = TestClient(app)
    resp = client.get("/test")
    assert resp.status_code == 200
