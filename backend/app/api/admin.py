"""Admin-only endpoints: data ingestion, reconciliation, users, audit log."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.reconcile import reconcile
from ..analytics.store import Store, get_store
from ..config import get_settings
from ..db import get_db
from ..ingestion.escalation import create_import, detect_kind, run_escalation_import
from ..ingestion.service import create_dataset, run_ingestion, sha256_of
from ..ingestion.workbook import ALLOWED_SUFFIXES, WorkbookError, check_file_signature
from ..models import AuditLog, Dataset, EscalationImport, ImportReport, User, ValidationIssue
from ..security.core import hash_password, password_problems
from ..security.deps import CurrentUser, audit, require_admin

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])
def _run_locked(dataset_id: int) -> None:
    run_ingestion(dataset_id)  # one import at a time (lock inside run_ingestion)


def _run_json(ds: Dataset, db: Session) -> dict:
    issues = db.scalars(
        select(ValidationIssue)
        .where(ValidationIssue.dataset_id == ds.id, ValidationIssue.severity.in_(["critical", "warning"]))
        .order_by(ValidationIssue.severity, ValidationIssue.row_number)
        .limit(25)
    ).all()
    counts = dict(db.execute(select(ValidationIssue.severity, func.count()).where(ValidationIssue.dataset_id == ds.id).group_by(ValidationIssue.severity)).all())
    duration = (ds.finished_at - ds.started_at).total_seconds() if ds.finished_at and ds.started_at else None
    return {
        "id": str(ds.id),
        "fileName": ds.file_name,
        "startedAt": ds.started_at.isoformat() if ds.started_at else None,
        "durationSec": round(duration) if duration is not None else None,
        "status": ds.status,
        "message": ds.message,
        "accepted": ds.rows_accepted,
        "rejected": ds.rows_rejected,
        "dataAsOf": ds.data_as_of.isoformat() if ds.data_as_of else None,
        "isActive": ds.is_active,
        "hasReport": db.get(ImportReport, ds.id) is not None,
        "issueCounts": {"critical": counts.get("critical", 0), "warning": counts.get("warning", 0), "info": counts.get("info", 0)},
        "validationErrors": [{"row": i.row_number or 0, "column": i.column or "—", "message": i.message, "code": i.code, "gpCode": i.gp_code} for i in issues],
    }


# ---------------------------------------------------------------- ingestion


@router.get("/ingestion/runs")
def runs(db: Session = Depends(get_db)) -> list[dict]:
    return [_run_json(d, db) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()).limit(50))]


@router.get("/ingestion/runs/{run_id}/issues")
def run_issues(
    run_id: int,
    severity: Annotated[Literal["critical", "warning", "info"] | None, Query()] = None,
    code: Annotated[str | None, Query(pattern=r"^[A-Z_]{2,40}$")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    db: Session = Depends(get_db),
) -> dict:
    q = select(ValidationIssue).where(ValidationIssue.dataset_id == run_id)
    if severity:
        q = q.where(ValidationIssue.severity == severity)
    if code:
        q = q.where(ValidationIssue.code == code)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(q.order_by(ValidationIssue.row_number).offset((page - 1) * page_size).limit(page_size)).all()
    by_code = db.execute(
        select(ValidationIssue.code, ValidationIssue.severity, func.count()).where(ValidationIssue.dataset_id == run_id).group_by(ValidationIssue.code, ValidationIssue.severity)
    ).all()
    return {
        "total": total,
        "summary": [{"code": c, "severity": s, "count": n} for c, s, n in by_code],
        "items": [{"row": i.row_number, "column": i.column, "gpCode": i.gp_code, "severity": i.severity, "code": i.code, "message": i.message, "sheet": i.sheet} for i in items],
    }


@router.post("/ingestion/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload(file: UploadFile, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    original = Path(file.filename or "upload").name
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Only {', '.join(sorted(ALLOWED_SUFFIXES))} files are accepted")
    safe_display = re.sub(r"[^\w .()\-]", "_", original)[:200]
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    target = s.upload_dir / f"{uuid.uuid4().hex}{suffix}"  # never trust the client file name for paths
    size = 0
    limit = s.upload_max_mb * 1024 * 1024
    with target.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {s.upload_max_mb} MB")
            out.write(chunk)
    try:
        check_file_signature(target)
        # Master data or Escalation Matrix – decided by the content, so either file can be uploaded alone or together.
        kind = await run_in_threadpool(detect_kind, target)
    except WorkbookError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    if kind is None:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"{safe_display}: not recognised – expected the master data workbook (sheet 'GP Wise Data') or the Escalation Matrix (columns GP Code, FRT Code, FE Name …).",
        )
    if kind == "escalation":
        imp = create_import(db, target, safe_display, sha256_of(target), user.id)
        audit(db, "upload_escalation", request, user.id, f"{safe_display} ({size} bytes) -> escalation import {imp.id}")
        background.add_task(run_escalation_import, imp.id)
        return {"id": f"esc-{imp.id}", "status": imp.status, "fileName": imp.file_name, "kind": "escalation"}
    ds = create_dataset(db, target, safe_display, user.id)
    audit(db, "upload", request, user.id, f"{safe_display} ({size} bytes) -> dataset {ds.id}")
    background.add_task(_run_locked, ds.id)
    return {"id": str(ds.id), "status": ds.status, "fileName": ds.file_name, "kind": "master"}


@router.get("/ingestion/escalation")
def escalation_imports(db: Session = Depends(get_db)) -> list[dict]:
    """Escalation Matrix uploads, newest first (the active one is used by Field Team & Escalation)."""
    out = []
    for imp in db.scalars(select(EscalationImport).order_by(EscalationImport.id.desc()).limit(10)):
        duration = (imp.finished_at - imp.started_at).total_seconds() if imp.finished_at and imp.started_at else None
        out.append(
            {
                "id": str(imp.id),
                "fileName": imp.file_name,
                "startedAt": imp.started_at.isoformat() if imp.started_at else None,
                "durationSec": round(duration) if duration is not None else None,
                "status": imp.status,
                "message": imp.message,
                "rows": imp.rows_total - imp.rows_rejected,
                "rejected": imp.rows_rejected,
                "isActive": imp.is_active,
            }
        )
    return out


@router.get("/ingestion/runs/{run_id}/report")
def run_report(run_id: int, db: Session = Depends(get_db)) -> dict:
    """What changed compared with the previous upload (built during the import)."""
    row = db.get(ImportReport, run_id)
    if row is None:
        raise HTTPException(404, "No upload report for this run (imported before reports existed, or the import failed).")
    report = json.loads(row.report)
    report.pop("layout", None)  # internal: used by the next upload's comparison
    return {"runId": str(run_id), "createdAt": row.created_at.isoformat() if row.created_at else None, **report}


@router.post("/ingestion/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(run_id: int, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, run_id)
    if not ds:
        raise HTTPException(404, "Run not found")
    if not Path(ds.stored_path).exists():
        return {"accepted": False, "message": "The original file is no longer available. Please upload it again."}
    ds.status = "PROCESSING"
    db.commit()
    audit(db, "retry_import", request, user.id, f"dataset {run_id}")
    background.add_task(_run_locked, ds.id)
    return {"accepted": True, "message": f"Re-processing {ds.file_name} started."}


@router.get("/ingestion/reconciliation")
def reconciliation(store: Store = Depends(get_store)) -> dict:
    return store.memo(("reconciliation",), lambda: reconcile(store))


# ---------------------------------------------------------------- users


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    role: Literal["admin", "viewer"] = "viewer"
    password: str = Field(min_length=1, max_length=128)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: Literal["admin", "viewer"] | None = None
    is_active: bool | None = Field(default=None, alias="isActive")
    password: str | None = Field(default=None, max_length=128)


def _user_json(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "isActive": u.is_active,
        "lastLoginAt": u.last_login_at.isoformat() if u.last_login_at else None,
        "locked": bool(u.locked_until),
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db)) -> list[dict]:
    return [_user_json(u) for u in db.scalars(select(User).order_by(User.email))]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    email = body.email.lower()
    if db.scalars(select(User).where(func.lower(User.email) == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    problems = password_problems(body.password, email)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password needs " + "; ".join(problems))
    u = User(email=email, name=body.name.strip(), role=body.role, password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    audit(db, "user_created", request, admin.id, f"{email} ({body.role})")
    return _user_json(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role == "viewer" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate your own account")
    revoke = False
    if body.name:
        u.name = body.name.strip()
    if body.role and body.role != u.role:
        u.role, revoke = body.role, True
    if body.is_active is not None and body.is_active != u.is_active:
        u.is_active, revoke = body.is_active, True
    if body.password:
        problems = password_problems(body.password, u.email)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password needs " + "; ".join(problems))
        u.password_hash, revoke = hash_password(body.password), True
        u.locked_until, u.failed_logins = None, 0
    if revoke:
        u.token_version += 1
    db.commit()
    audit(db, "user_updated", request, admin.id, f"{u.email}: {body.model_dump(exclude_none=True, exclude={'password'})}{' +password' if body.password else ''}")
    return _user_json(u)


@router.get("/audit")
def audit_log(limit: Annotated[int, Query(ge=1, le=500)] = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [{"at": a.at.isoformat() if a.at else None, "action": a.action, "user": email, "ip": a.ip, "detail": a.detail} for a, email in rows]
