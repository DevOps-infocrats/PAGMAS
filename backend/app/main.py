"""FastAPI application entry point.

Run (development):  uvicorn app.main:app --reload --port 8010
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text, update
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .analytics.store import NoDataError
from .analytics.views import NotFound
from .api import admin, analytics, auth, escalation, mail
from .config import get_settings
from .db import SessionLocal, engine, init_db
from .models import Dataset, EscalationImport, User
from .security.core import hash_password, password_problems, valid_email, verify_password
from .security.middleware import BodySizeLimitMiddleware, OriginCheckMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, ServerErrorMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pratap")
WORKBOOK_SUFFIXES = {".xlsb", ".xlsx", ".xlsm"}


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
    email = valid_email(s.admin_email)
    if email is None:
        log.error("ADMIN_EMAIL %r is not a valid e-mail address (it could never sign in) - admin account not changed", s.admin_email)
        return
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


INTERRUPTED = "Interrupted by a server restart – retry the import"


def _fail_interrupted(db) -> None:
    """Imports still PROCESSING at start-up were cut off by a restart: no thread will ever finish them."""
    from .ingestion.escalation import ESC_LOCK
    from .ingestion.service import INGEST_LOCK

    now = datetime.now(UTC)
    for model, lock in ((Dataset, INGEST_LOCK), (EscalationImport, ESC_LOCK)):
        if not lock.acquire(blocking=False):
            continue  # an import of this process is running (only possible when the app is started twice, e.g. tests)
        try:
            n = db.execute(update(model).where(model.status == "PROCESSING").values(status="FAILED", message=INTERRUPTED, finished_at=now)).rowcount
            db.commit()
        finally:
            lock.release()
        if n:
            log.warning("%s %s import(s) left PROCESSING by a restart marked FAILED", n, model.__tablename__)


def _newest_master_file(raw_dir: Path) -> Path | None:
    """Newest workbook in data/raw by modification time (names carry dd-mm-yy dates, so they do not sort)."""
    if not raw_dir.exists():
        return None
    files = [p for p in raw_dir.iterdir() if p.is_file() and p.suffix.lower() in WORKBOOK_SUFFIXES and "escalation" not in p.name.lower()]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def _auto_import(path: Path) -> None:
    from .ingestion.escalation import detect_kind
    from .ingestion.service import import_file

    try:
        kind = detect_kind(path)
    except Exception:
        log.exception("Start-up import: cannot read %s", path.name)
        return
    if kind != "master":
        log.warning("Start-up import: %s is not a master data workbook - skipped", path.name)
        return
    import_file(path)


def _bootstrap() -> None:
    s = get_settings()
    with SessionLocal() as db:
        _fail_interrupted(db)
        _ensure_env_admin(db)
        has_data = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True)))
    if not has_data:
        newest = _newest_master_file(s.raw_dir)
        if newest:
            log.info("No data yet - importing %s in the background", newest.name)
            threading.Thread(target=_auto_import, args=(newest,), daemon=True).start()
    else:
        from .analytics.store import reload_store

        # Load + warm the snapshot now so the first dashboard visit does not wait for it.
        threading.Thread(target=reload_store, daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    _bootstrap()
    from .mail.service import ensure_default_templates, start_scheduler, stop_scheduler

    with SessionLocal() as db:
        ensure_default_templates(db)  # the 3 built-in templates; never overwrites an edited one
    start_scheduler()  # only with AMC_REPORT_EMAILS_ENABLED=true; first check one minute later – start-up sends nothing
    yield
    stop_scheduler()


settings = get_settings()
app = FastAPI(
    title="Pratap Network Analytics API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Order: last added = outermost. Every response (also 403 / 413 / 429 / 500) passes SecurityHeadersMiddleware.
# Pure ASGI only: BaseHTTPMiddleware (@app.middleware) would wrap the body-limit error in an ExceptionGroup (-> 400).
app.add_middleware(ServerErrorMiddleware)
app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["content-type", "x-csrf-token"], max_age=600)
app.add_middleware(RateLimitMiddleware, per_minute=600)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(SecurityHeadersMiddleware)


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


@app.get("/api/health", tags=["health"])
def health() -> dict:
    """Liveness: the process answers (no database access)."""
    return {"status": "ok"}


@app.get("/api/ready", tags=["health"])
def ready() -> JSONResponse:
    """Readiness: the database answers. snapshotLoaded = the dashboard data is in memory (first visit is fast)."""
    from .analytics import store

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        log.warning("Readiness check: database unavailable", exc_info=True)
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok", "snapshotLoaded": store._cache is not None})


app.include_router(auth.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(escalation.router, prefix="/api/v1")
app.include_router(mail.router, prefix="/api/v1")
