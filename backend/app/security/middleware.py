"""HTTP hardening middleware (pure ASGI, so it also covers streaming responses)."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import get_settings
from .core import api_limiter

log = logging.getLogger("pratap.access")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; frame-ancestors 'none'"


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
                log.info("%s %s %s %s %.0fms", request_id, scope.get("method"), path, message["status"], (time.perf_counter() - started) * 1000)
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rejects bodies larger than the upload limit before they are read into memory."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.max_bytes = get_settings().upload_max_mb * 1024 * 1024

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > self.max_bytes:
                await _plain(send, 413, b'{"detail":"Request body too large"}')
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await _plain(send, 413, b'{"detail":"Request body too large"}')


class RateLimitMiddleware:
    """Coarse per-IP limit for all API calls (login has its own stricter limit)."""

    def __init__(self, app: ASGIApp, per_minute: int = 300) -> None:
        self.app = app
        self.per_minute = per_minute

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
            from .deps import real_ip

            xff = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-forwarded-for"), None)
            ip = real_ip((scope.get("client") or ("unknown", 0))[0], xff)
            if not api_limiter.hit(f"api:{ip}", self.per_minute, 60):
                await _plain(send, 429, b'{"detail":"Too many requests"}', [(b"retry-after", b"60")])
                return
        await self.app(scope, receive, send)


class _TooLarge(Exception):
    pass


async def _plain(send: Send, status: int, body: bytes, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), *(headers or [])]})
    await send({"type": "http.response.body", "body": body})
