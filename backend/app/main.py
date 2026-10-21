"""FastAPI application entry point.

Run (development):  uvicorn app.main:app --reload --port 8010
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .analytics.store import NoDataError
from .analytics.views import NotFound
from .api import admin, analytics, auth, escalation
from .config import get_settings
from .db import SessionLocal, init_db
from .models import Dataset, User
from .security.core import hash_password, password_problems, verify_password
from .security.middleware import BodySizeLimitMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pratap")


def _ensure_env_admin(db) -> None:
    """Create / sync the administrator defined in .env (ADMIN_EMAIL + ADMIN_PASSWORD_HASH or ADMIN_PASSWORD).

    * missing account  -> created as an active admin
    * existing account -> password only replaced when ADMIN_SYNC_PASSWORD=true and it differs;
                          every existing session is then revoked (token_version + 1)
    A plain password must pass the same strength policy as every other password.
    """
    s = get_settings()
    if not s.admin_email or not (s.admin_password or s.admin_password_hash):
        return
    email = s.admin_email.strip().lower()
    if s.admin_password:
        problems = password_problems(s.admin_password, email)
        if problems:
            log.error("ADMIN_PASSWORD in .env rejected (needs %s) - admin account not changed", "; ".join(problems))
            return
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    if user is None:
        db.add(User(email=email, name=s.admin_name, role="admin", password_hash=s.admin_password_hash or hash_password(s.admin_password)))
        db.commit()
        log.info("Admin %s created from .env", email)
        return
    if not s.admin_sync_password:
        return
    same = user.password_hash == s.admin_password_hash if s.admin_password_hash else verify_password(s.admin_password, user.password_hash)
    if same and user.role == "admin" and user.is_active:
        return
    if not same:
        user.password_hash = s.admin_password_hash or hash_password(s.admin_password)
        user.token_version += 1
    user.role, user.is_active, user.failed_logins, user.locked_until = "admin", True, 0, None
    db.commit()
    log.warning("Admin %s synced from .env (ADMIN_SYNC_PASSWORD=true)%s", email, " - password replaced, sessions revoked" if not same else "")


def _bootstrap() -> None:
    s = get_settings()
    with SessionLocal() as db:
        _ensure_env_admin(db)
        has_data = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True)))
    if not has_data:
        files = sorted(p for p in s.raw_dir.glob("*") if p.suffix.lower() in {".xlsb", ".xlsx", ".xlsm"}) if s.raw_dir.exists() else []
        if files:
            from .ingestion.service import import_file

            log.info("No data yet - importing %s in the background", files[-1].name)
            threading.Thread(target=import_file, args=(files[-1],), daemon=True).start()
    else:
        from .analytics.store import reload_store

        # Load + warm the snapshot now so the first dashboard visit does not wait for it.
        threading.Thread(target=reload_store, daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _bootstrap()
    yield


settings = get_settings()
app = FastAPI(
    title="Pratap Network Analytics API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Order: last added = outermost.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["content-type", "x-csrf-token"], max_age=600)
app.add_middleware(RateLimitMiddleware, per_minute=600)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(SecurityHeadersMiddleware)

_allowed_origins = {o.rstrip("/") for o in settings.cors_origins}


@app.middleware("http")
async def origin_check(request: Request, call_next):
    """Blocks cross-site state-changing requests (defence in depth next to SameSite + CSRF token)."""
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            parsed = urlparse(origin)
            if f"{parsed.scheme}://{parsed.netloc}" not in _allowed_origins:
                return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    return await call_next(request)


@app.exception_handler(NoDataError)
async def _no_data(_: Request, exc: NoDataError):
    return JSONResponse({"detail": "No data imported yet. An admin must upload the master data file."}, status_code=503)


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    # Return field locations only - no echo of submitted values (passwords etc.).
    return JSONResponse({"detail": "Invalid request", "errors": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]}, status_code=422)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    log.exception("Unhandled error")
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(escalation.router, prefix="/api/v1")
