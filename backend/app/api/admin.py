"""Admin-only endpoints: data ingestion, reconciliation, users, audit log."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Path as PathParam, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..analytics import plan_files
from ..analytics.reconcile import reconcile
from ..analytics.store import Store, get_store
from ..config import get_settings
from ..db import get_db
from ..ingestion.escalation import create_import, detect_kind, run_escalation_import
from ..ingestion import column_mapper, preview, staging
from ..ingestion.column_map import load_column_map
from ..ingestion.service import create_dataset, reprocess, run_ingestion, sha256_of
from ..ingestion.workbook import ALLOWED_SUFFIXES, WorkbookError, check_file_signature
from ..mail.audience import Assignment, assignments_of, check_assignments, location_tree, locations
from ..models import AuditLog, Dataset, EscalationImport, ImportReport, User, UserScope, ValidationIssue
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
    missing_cols = db.scalar(select(func.count()).where(ValidationIssue.dataset_id == ds.id, ValidationIssue.code.in_(["COLUMN_MISSING", "REFERENCE_SHEET"]))) or 0
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
        "missingColumns": missing_cols,  # optional columns / reference sheets not found -> "Check columns"
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


@router.get("/ingestion/runs/{run_id}/issues.xlsx")
def run_issues_xlsx(
    run_id: int,
    severity: Annotated[Literal["critical", "warning", "info"] | None, Query()] = None,
    code: Annotated[str | None, Query(pattern=r"^[A-Z_]{2,40}$")] = None,
    db: Session = Depends(get_db),
) -> Response:
    """All data-quality issues of a run as Excel (to send to the team that maintains the source file)."""
    import io

    import xlsxwriter

    ds = db.get(Dataset, run_id)
    if not ds:
        raise HTTPException(404, "Run not found")
    q = select(ValidationIssue).where(ValidationIssue.dataset_id == run_id)
    if severity:
        q = q.where(ValidationIssue.severity == severity)
    if code:
        q = q.where(ValidationIssue.code == code)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Issues")
    head = wb.add_format({"bold": True, "bg_color": "#E8F1FB", "border": 1})
    cols = [("Sheet", 18), ("Excel row", 10), ("GP code", 14), ("Column", 22), ("Severity", 10), ("Code", 18), ("Message", 90)]
    for c, (title, width) in enumerate(cols):
        ws.write(0, c, title, head)
        ws.set_column(c, c, width)
    r = 0
    for r, i in enumerate(db.scalars(q.order_by(ValidationIssue.severity, ValidationIssue.code, ValidationIssue.row_number)), start=1):
        ws.write_row(r, 0, [i.sheet or "", i.row_number or "", i.gp_code or "", i.column or "", i.severity, i.code, i.message])
    ws.autofilter(0, 0, max(r, 1), len(cols) - 1)
    ws.freeze_panes(1, 0)
    wb.close()
    stem = re.sub(r"[^\w.-]+", "_", Path(ds.file_name).stem)[:60]
    name = f"issues_{stem}{'_' + code if code else ''}.xlsx"
    return Response(
        buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _already_imported(db: Session, sha: str, upload_dir: Path) -> str | None:
    """Message for an upload whose exact content was imported successfully before and whose stored upload still exists
    (files imported from data/raw by the CLI / start-up do not count)."""
    root = upload_dir.resolve()
    for model, label, ok in ((Dataset, "run", ("SUCCESS", "PARTIAL")), (EscalationImport, "Escalation Matrix import", ("SUCCESS",))):
        for rec in db.scalars(select(model).where(model.sha256 == sha, model.status.in_(ok)).order_by(model.id.desc())):
            p = Path(rec.stored_path).resolve()
            if p.is_relative_to(root) and p.exists():
                when = f" on {rec.started_at:%d %b %Y %H:%M}" if rec.started_at else ""
                active = "it is the active one" if rec.is_active else "it is not the active one"
                return f"This file was already imported as {label} #{rec.id} ('{rec.file_name}'{when}; {active}) - nothing to do."
    return None


UploadKind = Literal["master", "escalation"]


def _display(name: str | None) -> str:
    return re.sub(r"[^\w .()\-]", "_", Path(name or "upload").name)[:200]


def _suffix_ok(name: str | None) -> str:
    """Layer 1 (type) – also checked by the browser's file picker, but never trusted from it."""
    suffix = Path(name or "upload").suffix.lower()
    if suffix == ".xlsm":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Macro workbooks (.xlsm) are not accepted – save the file as .xlsx or .xlsb and upload again")
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Only {', '.join(sorted(ALLOWED_SUFFIXES))} files are accepted")
    return suffix


def _start_import(db: Session, request: Request, background: BackgroundTasks, user: CurrentUser, target: Path, display: str, sha: str, size: int, kind: str) -> dict:
    """Record the accepted file and start its import in the background (the existing pipeline: parse, write, activate
    atomically together with the data, keep the newest KEEP_DATASETS)."""
    if kind == "escalation":
        imp = create_import(db, target, display, sha, user.id)
        audit(db, "upload_escalation", request, user.id, f"{display} ({size} bytes) -> escalation import {imp.id}")
        background.add_task(run_escalation_import, imp.id)
        return {"id": f"esc-{imp.id}", "status": imp.status, "fileName": imp.file_name, "kind": "escalation"}
    ds = create_dataset(db, target, display, user.id, sha)
    audit(db, "upload", request, user.id, f"{display} ({size} bytes) -> dataset {ds.id}")
    background.add_task(_run_locked, ds.id)
    return {"id": str(ds.id), "status": ds.status, "fileName": ds.file_name, "kind": "master"}


@router.post("/ingestion/upload", status_code=status.HTTP_202_ACCEPTED)
def upload(
    file: UploadFile, request: Request, background: BackgroundTasks, kind: Annotated[UploadKind | None, Form()] = None, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    """One-step upload (kept for scripts and older pages; Data Operations uses preview -> confirm). With `kind` the file
    must be that kind. Sync endpoint (runs in the thread pool): hashing, sniffing and DB work never block the event loop."""
    s = get_settings()
    suffix = _suffix_ok(file.filename)
    display = _display(file.filename)
    try:
        token, staged, size, sha = staging.receive(file.file, suffix)
    except staging.StagingError as exc:
        raise HTTPException(exc.status, exc.message) from None
    stored = False
    target = staged
    try:  # any failure (rejected, duplicate, crash) removes the unused file
        try:
            check_file_signature(staged)
            if dup := _already_imported(db, sha, s.upload_dir):
                raise HTTPException(status.HTTP_409_CONFLICT, f"{display}: {dup}")
            # Master data or Escalation Matrix – decided by the content, so either file can be uploaded alone or together.
            found = detect_kind(staged)
        except WorkbookError as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
        if found is None:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"{display}: not recognised – expected the master data workbook (sheet 'GP Wise Data') or the Escalation Matrix (columns GP Code, FRT Code, FE Name …).",
            )
        if kind is not None and found != kind:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{display}: you selected '{preview.KINDS[kind]}', but this file is the {preview.KINDS[found]}.")
        if found == "master":  # the fixed PAGMAS template – the same check as the preview
            from ..ingestion import template

            chk = template.validate_master(staged)
            if not chk.ok:
                listed = "; ".join(f"{p.sheet}{f' row {p.row}' if p.row else ''}: {p.message}" for p in chk.errors[:15])
                more = f" (+{chk.error_count - 15} more)" if chk.error_count > 15 else ""
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{template.TEMPLATE_MESSAGE} {listed}{more}")
        target = staging.promote(staging.Staged(token, found, display, suffix, size, sha, user.id, 0.0))
        stored = True
        return _start_import(db, request, background, user, target, display, sha, size, found)
    except staging.StagingError as exc:
        raise HTTPException(exc.status, exc.message) from None
    finally:
        if not stored:
            staging.discard(token)
            if target != staged:
                target.unlink(missing_ok=True)


# ---------------------------------------------------------------- preview -> confirm (Data Operations)


@router.post("/ingestion/preview")
def upload_preview(file: UploadFile, kind: Annotated[UploadKind, Form()], user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Step 1: stage the file and validate it completely (type, size, genuine workbook, zip bomb, chosen kind,
    duplicate, structure, every row) – nothing is imported. Returns the validation report and, when it can be
    imported, a token for step 2. A failed check deletes the staged file; the active data is never touched."""
    s = get_settings()
    suffix = _suffix_ok(file.filename)
    display = _display(file.filename)
    try:
        token, path, size, sha = staging.receive(file.file, suffix)
    except staging.StagingError as exc:
        raise HTTPException(exc.status, exc.message) from None
    st = staging.Staged(token, kind, display, suffix, size, sha, user.id, time.time())
    base = {"token": token, "kind": kind, "kindLabel": preview.KINDS[kind], "fileName": display, "size": size, "sha256": sha, "expiresInMinutes": s.staging_ttl_minutes}
    try:
        report = preview.build(path, kind, base, _already_imported(db, sha, s.upload_dir))
    except Exception:  # unexpected – never leak internals, never keep the file
        staging.discard(token)
        raise
    if not report["canImport"]:
        staging.discard(token)
        report["token"] = None
        return report
    st.report = {"counts": report.get("counts"), "stage": report["stage"]}
    staging.save(st)
    return report


class ConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=64)


@router.post("/ingestion/confirm", status_code=status.HTTP_202_ACCEPTED)
def upload_confirm(body: ConfirmIn, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Step 2: the admin confirmed the report – move the staged file into the upload store (timestamp + checksum name)
    and import it. The file is checked again (checksum, duplicate) – a staged file is never trusted blindly."""
    s = get_settings()
    try:
        st = staging.load(body.token, user.id)
        if dup := _already_imported(db, st.sha256, s.upload_dir):
            staging.discard(st.token)
            raise HTTPException(status.HTTP_409_CONFLICT, f"{st.file_name}: {dup}")
        target = staging.promote(st)
    except staging.StagingError as exc:
        raise HTTPException(exc.status, exc.message) from None
    try:
        return _start_import(db, request, background, user, target, st.file_name, st.sha256, st.size, st.kind)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


@router.get("/ingestion/template/master.xlsx")
def master_template(request: Request, sample: bool = False, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> Response:
    """The PAGMAS master data template (every mandatory column; period columns of the current weeks / days / months)
    – generated from the same spec the upload check uses, so the two can never disagree. sample = 2 example rows."""
    from ..ingestion import template

    data = template.build_template(sample=sample)
    name = "PAGMAS Master Data Sample.xlsx" if sample else "PAGMAS Master Data Template.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.delete("/ingestion/preview/{token}")
def upload_discard(token: str, user: CurrentUser = Depends(require_admin)) -> dict:
    """Cancel a preview: the staged file is deleted (nothing was imported)."""
    try:
        staging.load(token, user.id)
    except staging.StagingError:
        return {"discarded": False}
    staging.discard(token)
    return {"discarded": True}


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
                "columnsMissing": "Columns not found" in (imp.message or ""),
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
    if ds.status != "FAILED":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only failed imports can be retried – run #{run_id} is {ds.status}.")
    if not Path(ds.stored_path).exists():
        raise HTTPException(status.HTTP_410_GONE, "The original file is no longer available. Please upload it again.")
    claimed = db.execute(
        update(Dataset).where(Dataset.id == run_id, Dataset.status == "FAILED").values(status="PROCESSING", message=None, started_at=datetime.now(UTC), finished_at=None)
    ).rowcount
    db.commit()
    if not claimed:  # a concurrent retry got there first
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run #{run_id} is already being re-processed.")
    audit(db, "retry_import", request, user.id, f"dataset {run_id}")
    background.add_task(_run_locked, ds.id)
    return {"accepted": True, "message": f"Re-processing {ds.file_name} started."}


# ---------------------------------------------------------------- column mapper (Data Operations → Column names)


def _mapper_error(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


def _check_stored(path_text: str) -> dict:
    path = Path(path_text)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "The original file is no longer available. Please choose it again with “Check a file”.")
    try:
        return column_mapper.check(path)
    except WorkbookError as exc:
        raise _mapper_error(exc) from None


@router.get("/ingestion/column-map")
def column_map_names() -> dict:
    """Sheet / column names admins added to the built-in ones (data/column_map.json)."""
    return {"names": column_mapper.custom_names(), "problems": load_column_map().problems}


@router.post("/ingestion/column-check")
def column_check(file: UploadFile) -> dict:
    """Which sheets / columns of a workbook the importer recognises – nothing is imported or stored (the file is
    deleted right after the check). Used before an upload, or after one was refused."""
    s = get_settings()
    suffix = _suffix_ok(file.filename)
    folder = s.upload_dir / "column-check"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}{suffix}"
    limit, size = s.upload_max_mb * 1024 * 1024, 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {s.upload_max_mb} MB")
                out.write(chunk)
        try:
            check_file_signature(target)
            return column_mapper.check(target)
        except WorkbookError as exc:
            raise _mapper_error(exc) from None
    finally:
        target.unlink(missing_ok=True)


@router.get("/ingestion/runs/{run_id}/column-check")
def run_column_check(run_id: int, db: Session = Depends(get_db)) -> dict:
    ds = db.get(Dataset, run_id)
    if not ds:
        raise HTTPException(404, "Run not found")
    return _check_stored(ds.stored_path)


@router.get("/ingestion/escalation/{import_id}/column-check")
def escalation_column_check(import_id: int, db: Session = Depends(get_db)) -> dict:
    imp = db.get(EscalationImport, import_id)
    if not imp:
        raise HTTPException(404, "Escalation Matrix import not found")
    return _check_stored(imp.stored_path)


class ColumnNameIn(BaseModel):
    section: str = Field(max_length=20)
    field: str = Field(max_length=40)
    name: str = Field(max_length=200)


class SheetNameIn(BaseModel):
    key: str = Field(max_length=20)
    name: str = Field(max_length=200)


class ColumnMapIn(BaseModel):
    columns: list[ColumnNameIn] = Field(default_factory=list, max_length=100)
    sheets: list[SheetNameIn] = Field(default_factory=list, max_length=10)


@router.post("/ingestion/column-map")
def add_column_names(body: ColumnMapIn, request: Request, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Add the file's own sheet / column names the admin chose (all or nothing; never guessed)."""
    try:
        added = column_mapper.add_names([c.model_dump() for c in body.columns], [x.model_dump() for x in body.sheets])
    except column_mapper.MapperError as exc:
        raise _mapper_error(exc) from None
    if added:
        audit(db, "column_map_added", request, user.id, "; ".join(added))
    return {"added": added, "names": column_mapper.custom_names()}


class ColumnRemoveIn(BaseModel):
    section: str = Field(max_length=20)
    field: str = Field(max_length=40)
    name: str = Field(max_length=200)


@router.post("/ingestion/column-map/remove")
def remove_column_name(body: ColumnRemoveIn, request: Request, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        done = column_mapper.remove_name(body.section, body.field, body.name)
    except column_mapper.MapperError as exc:
        raise _mapper_error(exc) from None
    audit(db, "column_map_removed", request, user.id, done)
    return {"removed": done, "names": column_mapper.custom_names()}


@router.post("/ingestion/runs/{run_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess_run(run_id: int, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Import a finished run's stored file again with the current column names (the same file cannot be uploaded
    twice). If that fails the run keeps its data and status."""
    ds = db.get(Dataset, run_id)
    if not ds:
        raise HTTPException(404, "Run not found")
    if ds.status not in ("SUCCESS", "PARTIAL"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run #{run_id} is {ds.status} – use Retry for a failed import.")
    if not Path(ds.stored_path).exists():
        raise HTTPException(status.HTTP_410_GONE, "The original file is no longer available. Please upload it again.")
    previous = (ds.status, ds.message)
    claimed = db.execute(update(Dataset).where(Dataset.id == run_id, Dataset.status == previous[0]).values(status="PROCESSING")).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run #{run_id} is already being processed.")
    audit(db, "reprocess_import", request, user.id, f"dataset {run_id}")
    background.add_task(reprocess, ds.id, previous)
    return {"accepted": True, "message": f"Re-processing {ds.file_name} with the current column names started."}


@router.post("/ingestion/escalation/{import_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
def reprocess_escalation(import_id: int, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    imp = db.get(EscalationImport, import_id)
    if not imp:
        raise HTTPException(404, "Escalation Matrix import not found")
    if imp.status != "SUCCESS":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Import #{import_id} is {imp.status} – upload the file again.")
    if not Path(imp.stored_path).exists():
        raise HTTPException(status.HTTP_410_GONE, "The original file is no longer available. Please upload it again.")
    previous = (imp.status, imp.message)
    claimed = db.execute(update(EscalationImport).where(EscalationImport.id == import_id, EscalationImport.status == "SUCCESS").values(status="PROCESSING")).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Import #{import_id} is already being processed.")
    audit(db, "reprocess_escalation", request, user.id, f"escalation import {import_id}")
    background.add_task(run_escalation_import, imp.id, previous)
    return {"accepted": True, "message": f"Re-processing {imp.file_name} with the current column names started."}


# ---------------------------------------------------------------- plan files (review_plan.json, amc_month_targets.json)

PlanFileName = Annotated[str, PathParam(pattern=r"^[a-z_]{3,40}\.json$")]


class PlanFileIn(BaseModel):
    data: dict


@router.get("/plan-files")
def plan_files_list() -> list[dict]:
    return plan_files.list_files()


@router.put("/plan-files/{name}")
def plan_file_save(name: PlanFileName, body: PlanFileIn, request: Request, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        out = plan_files.save(name, body.data, user.email)
    except plan_files.PlanFileError as exc:
        raise HTTPException(422, str(exc)) from None
    audit(db, "plan_file_saved", request, user.id, name)
    return out


@router.get("/plan-files/{name}/history")
def plan_file_history(name: PlanFileName) -> list[dict]:
    try:
        return plan_files.history(name)
    except plan_files.PlanFileError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.get("/ingestion/reconciliation")
def reconciliation(store: Store = Depends(get_store)) -> dict:
    return store.memo(("reconciliation",), lambda: reconcile(store))


# ---------------------------------------------------------------- users


class ScopeIn(BaseModel):
    level: Literal["circle", "district", "block"]
    id: str = Field(min_length=1, max_length=120)


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    role: Literal["admin", "viewer"] = "viewer"
    password: str = Field(min_length=1, max_length=128)
    # Circle / district / block areas of a viewer: what they see on the dashboard and receive in the AMC Conversion e-mails
    # (security/access.py, mail/audience.py); admins see and receive everything
    scopes: list[ScopeIn] = Field(default_factory=list, max_length=500)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    role: Literal["admin", "viewer"] | None = None
    is_active: bool | None = Field(default=None, alias="isActive")
    password: str | None = Field(default=None, max_length=128)
    scopes: list[ScopeIn] | None = Field(default=None, max_length=500)  # None = unchanged, [] = remove all


def _active_store() -> Store | None:
    from ..analytics.store import NoDataError

    try:
        return get_store()
    except NoDataError:
        return None


def _user_json(u: User, scopes: list[Assignment] | None = None, labels: dict[str, dict[str, str]] | None = None) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "isActive": u.is_active,
        "lastLoginAt": u.last_login_at.isoformat() if u.last_login_at else None,
        "locked": bool(u.locked_until),
        "scopes": [{"level": a.level, "id": a.id, "label": (labels or {}).get(a.level, {}).get(a.id), "valid": labels is None or a.id in labels.get(a.level, {})} for a in (scopes or [])],
    }


def _users_json(db: Session, users: list[User]) -> list[dict]:
    st = _active_store()
    labels = locations(st) if st is not None else None
    sc = assignments_of(db, [u.id for u in users])
    return [_user_json(u, sc.get(u.id, []), labels) for u in users]


def _set_scopes(db: Session, user: User, items: list[ScopeIn]) -> None:
    """Replace the user's areas (validated against the active data). Admins keep none – they receive everything."""
    wanted = list(dict.fromkeys(Assignment(s.level, s.id.strip()) for s in items)) if user.role == "viewer" else []
    if wanted:
        problems = check_assignments(_active_store(), wanted)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems[:5]))
    db.execute(delete(UserScope).where(UserScope.user_id == user.id))
    db.add_all(UserScope(user_id=user.id, level=a.level, scope_id=a.id) for a in wanted)


@router.get("/users")
def list_users(db: Session = Depends(get_db)) -> list[dict]:
    return _users_json(db, list(db.scalars(select(User).order_by(User.email))))


@router.get("/users/locations")
def user_locations() -> dict:
    """Circles → districts → blocks of the active data, for assigning user areas."""
    st = _active_store()
    return {"circles": location_tree(st) if st is not None else [], "hasData": st is not None}


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
    db.flush()
    _set_scopes(db, u, body.scopes)
    db.commit()
    from ..tickets.service import link_recipients

    link_recipients(db, u.id, u.email)  # tickets already sent to this e-mail (e.g. as SME / COH) appear for the new user
    audit(db, "user_created", request, admin.id, f"{email} ({body.role}, {len(body.scopes) if body.role == 'viewer' else 0} area(s))")
    return _users_json(db, [u])[0]


USER_IMPORT_MAX_MB = 5


@router.post("/users/import")
def import_users(
    file: UploadFile,
    request: Request,
    dry_run: Annotated[bool, Query(alias="dryRun")] = True,
    admin: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Create Viewer accounts from an Excel / CSV file with Name and Email columns, all with the temporary password
    USER_IMPORT_PASSWORD. Existing e-mail addresses are skipped (never changed). dryRun=true only previews."""
    from ..ingestion.users import USER_IMPORT_SUFFIXES, read_users

    s = get_settings()
    suffix = Path(file.filename or "users").suffix.lower()
    if suffix not in USER_IMPORT_SUFFIXES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"Only {', '.join(sorted(USER_IMPORT_SUFFIXES))} files are accepted")
    folder = s.upload_dir / "user-import"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid.uuid4().hex}{suffix}"
    limit, size = USER_IMPORT_MAX_MB * 1024 * 1024, 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {USER_IMPORT_MAX_MB} MB")
                out.write(chunk)
        try:
            rows = read_users(target)
        except WorkbookError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    finally:
        target.unlink(missing_ok=True)

    existing = {e.lower() for e in db.scalars(select(User.email).where(func.lower(User.email).in_([r.email for r in rows if not r.problem])))}
    items, new = [], []
    for r in rows:
        status_, reason = ("SKIPPED", r.problem) if r.problem else ("EXISTS", "Already a dashboard user – not changed") if r.email in existing else ("NEW", None)
        items.append({"row": r.row, "name": r.name, "email": r.email, "status": status_, "reason": reason})
        if status_ == "NEW":
            new.append(r)
    created = 0
    if not dry_run and new:
        pw = hash_password(s.user_import_password)  # same known temporary password -> hashed once
        db.add_all(User(email=r.email, name=r.name, role="viewer", password_hash=pw) for r in new)
        db.commit()
        created = len(new)
        for it in items:
            if it["status"] == "NEW":
                it["status"] = "CREATED"
        audit(db, "users_imported", request, admin.id, f"{created} viewer(s) from {(file.filename or 'file')[:80]}")
    count = lambda st: sum(1 for it in items if it["status"] == st)  # noqa: E731
    return {
        "dryRun": dry_run,
        "fileName": file.filename,
        "total": len(items),
        "new": len(new),
        "created": created,
        "exists": count("EXISTS"),
        "skipped": count("SKIPPED"),
        "temporaryPassword": s.user_import_password,
        "items": items,
    }


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role == "viewer" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate your own account")
    if u.id == admin.id and body.email and body.email.lower() != u.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Change your own e-mail address from a second admin account")
    revoke = False
    if body.name:
        u.name = body.name.strip()
    if body.email and body.email.lower() != u.email:
        email = body.email.lower()
        if db.scalars(select(User).where(func.lower(User.email) == email, User.id != u.id)).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
        u.email, revoke = email, True
    if body.role and body.role != u.role:
        u.role, revoke = body.role, True
        if body.role == "admin" and body.scopes is None:
            body.scopes = []  # admins keep no areas
    if body.scopes is not None:
        _set_scopes(db, u, body.scopes)
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
    changes = body.model_dump(exclude_none=True, exclude={"password", "scopes"})
    if body.scopes is not None:
        changes["areas"] = len(body.scopes) if u.role == "viewer" else 0
    audit(db, "user_updated", request, admin.id, f"{u.email}: {changes}{' +password' if body.password else ''}")
    return _users_json(db, [u])[0]


@router.get("/audit")
def audit_log(limit: Annotated[int, Query(ge=1, le=500)] = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).order_by(AuditLog.id.desc()).limit(limit)).all()
    return [{"at": a.at.isoformat() if a.at else None, "action": a.action, "user": email, "ip": a.ip, "detail": a.detail} for a, email in rows]
