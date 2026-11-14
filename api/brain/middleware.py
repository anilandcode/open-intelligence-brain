"""Production middleware for Open Intelligence Brain.

Includes:
1. RequestIdMiddleware: Propagates or generates X-Request-ID for distributed tracing.
2. SecurityHeadersMiddleware: Sets HSTS, nosniff, frame denial, and referrer policies.
3. RateLimitMiddleware: Token-preview / IP based rate limiting to prevent abuse.
4. AccessLogMiddleware: Safe structured access logging without leaking raw secrets.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("brain.access")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Binds an X-Request-ID to each incoming request and response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 128:
            request_id = f"req_{uuid4().hex[:16]}"
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard defensive HTTP headers."""

    def __init__(self, app, is_production: bool = False):
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = "accelerometer=(), camera=(), geolocation=(), microphone=()"

        if self.is_production or request.url.scheme == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding window rate limiter keyed by principal preview or client IP.

    Safe for single-instance or container sidecars; never logs or stores raw tokens.
    """

    def __init__(
        self,
        app,
        auth_limit: int = 30,  # req/minute on /api/v1/auth/*
        write_limit: int = 150,  # req/minute on POST/PATCH/DELETE
        read_limit: int = 600,  # req/minute on GET/HEAD
        enabled: bool = True,
    ):
        super().__init__(app)
        self.auth_limit = auth_limit
        self.write_limit = write_limit
        self.read_limit = read_limit
        self.enabled = enabled
        # Key -> list of timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)

    def _get_key(self, request: Request) -> str:
        token = request.headers.get("x-brain-token")
        if token:
            # Preview only (never raw secret)
            return f"tok_{token[:8]}"
        session = request.headers.get("x-brain-session")
        if session:
            return f"sess_{session[:8]}"
        client = request.client
        return f"ip_{client.host}" if client else "ip_unknown"

    def _cleanup_and_check(self, key: str, limit: int, now: float) -> bool:
        timestamps = self._windows[key]
        cutoff = now - 60.0
        # prune older than 60 seconds
        valid = [t for t in timestamps if t > cutoff]
        if len(valid) >= limit:
            self._windows[key] = valid
            return False
        valid.append(now)
        self._windows[key] = valid
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Healthchecks and static assets bypass rate limit
        path = request.url.path
        if path.startswith(("/health", "/favicon", "/assets")):
            return await call_next(request)

        now = time.time()
        key = self._get_key(request)

        if path.startswith("/api/v1/auth"):
            limit = self.auth_limit
            bucket = f"{key}:auth"
        elif request.method in ("POST", "PATCH", "DELETE", "PUT"):
            limit = self.write_limit
            bucket = f"{key}:write"
        else:
            limit = self.read_limit
            bucket = f"{key}:read"

        if not self._cleanup_and_check(bucket, limit, now):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry in a moment."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs non-sensitive request metrics with request-id and actor preview."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        request_id = getattr(request.state, "request_id", "-")
        # Masked actor
        actor = "-"
        if "x-brain-token" in request.headers:
            actor = f"token:{request.headers['x-brain-token'][:6]}…"
        elif "x-brain-session" in request.headers:
            actor = f"session:{request.headers['x-brain-session'][:6]}…"
        elif request.client:
            actor = f"ip:{request.client.host}"

        log.info(
            "%s %s -> %d (%.1fms) [%s] [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
            actor,
        )
        return response
