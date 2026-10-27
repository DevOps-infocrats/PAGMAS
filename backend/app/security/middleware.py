"""HTTP hardening middleware (pure ASGI, so it also covers streaming responses)."""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import urlparse

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import get_settings
from .core import api_limiter

log = logging.getLogger("pratap.access")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; frame-ancestors 'none'"
# Probes are polled every few seconds: no access log line and no rate limit.
HEALTH_PATHS = frozenset({"/api/health", "/api/ready"})
UPLOAD_PATHS = frozenset({"/api/v1/ingestion/upload"})
SMALL_BODY_BYTES = 64 * 1024


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.hsts = get_settings().is_production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        path: str = scope.get("path", "")
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), payment=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                    b"content-security-policy": (DOCS_CSP if path in ("/docs", "/redoc") else API_CSP).encode(),
                    b"x-request-id": request_id.encode(),
                }
                if path.startswith("/api/"):
                    extra[b"cache-control"] = b"no-store"
                if self.hsts:
                    extra[b"strict-transport-security"] = b"max-age=63072000; includeSubDomains"
                existing = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in extra.items() if k not in existing)
                if path not in HEALTH_PATHS:
                    log.info("%s %s %s %s %.0fms", request_id, scope.get("method"), path, message["status"], (time.perf_counter() - started) * 1000)
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rejects bodies larger than the limit before they are read into memory: the upload limit for the workbook
    upload, SMALL_BODY_BYTES for every other path (JSON bodies are tiny)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.upload_bytes = get_settings().upload_max_mb * 1024 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        max_bytes = self.upload_bytes if scope.get("path", "") in UPLOAD_PATHS else SMALL_BODY_BYTES
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > max_bytes:
                await _plain(send, 413, b'{"detail":"Request body too large"}')
                return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _TooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if started:
                raise
            await _plain(send, 413, b'{"detail":"Request body too large"}')


class RateLimitMiddleware:
    """Coarse per-IP limit for all API calls (login has its own stricter limit)."""

    def __init__(self, app: ASGIApp, per_minute: int = 300) -> None:
        self.app = app
        self.per_minute = per_minute

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/api/") and path not in HEALTH_PATHS:
            from .deps import real_ip

            xff = ", ".join(v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-forwarded-for") or None
            ip = real_ip((scope.get("client") or ("unknown", 0))[0], xff)
            if not api_limiter.hit(f"api:{ip}", self.per_minute, 60):
                await _plain(send, 429, b'{"detail":"Too many requests"}', [(b"retry-after", b"60")])
                return
        await self.app(scope, receive, send)


class OriginCheckMiddleware:
    """Blocks cross-site state-changing requests (defence in depth next to SameSite + CSRF token)."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {o.rstrip("/") for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and scope.get("path", "").startswith("/api/"):
            headers = dict(reversed(scope.get("headers", [])))  # first value wins, as with Request.headers.get
            origin = (headers.get(b"origin") or headers.get(b"referer") or b"").decode("latin-1")
            if origin:
                parsed = urlparse(origin)
                if f"{parsed.scheme}://{parsed.netloc}" not in self.allowed:
                    await _plain(send, 403, b'{"detail":"Cross-site request blocked"}')
                    return
        await self.app(scope, receive, send)


class ServerErrorMiddleware:
    """Innermost: turns an unhandled exception into the generic JSON 500, so the response still passes through
    the outer middleware (security headers, x-request-id, CORS). Nothing internal is sent to the client."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            if started:
                raise  # too late for a clean error response (e.g. a failing background task)
            logging.getLogger("pratap").exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            await _plain(send, 500, b'{"detail":"Internal server error"}')


class _TooLarge(HTTPException):
    """Also an HTTPException, so FastAPI's body parsing re-raises it (as 413) instead of turning it into a 400."""

    def __init__(self) -> None:
        super().__init__(413, "Request body too large")


async def _plain(send: Send, status: int, body: bytes, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), *(headers or [])]})
    await send({"type": "http.response.body", "body": body})
