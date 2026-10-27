"""Import a workbook into the database as a new dataset and activate it."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, is_postgres
from ..models import CircleSheetValue, Dataset, DatasetWeek, Gp, GpAmcPlan, GpAvailability, GpAvailabilityPack, MasterBlock, ReportedNumber, ValidationIssue
from .history import merge_daily
from .packs import pack, wide_frames
from .parser import ParsedWorkbook, parse_workbook
from .workbook import WorkbookError

log = logging.getLogger(__name__)
KEEP_DATASETS = 3
# Every per-dataset table (data rows are deleted on retry and when an old dataset is pruned).
DATA_TABLES = (GpAmcPlan, GpAvailabilityPack, GpAvailability, Gp, DatasetWeek, ReportedNumber, MasterBlock, CircleSheetValue, ValidationIssue)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def create_dataset(db: Session, path: Path, file_name: str, user_id: int | None, sha: str | None = None) -> Dataset:
    ds = Dataset(file_name=file_name, stored_path=str(path), sha256=sha or sha256_of(path), status="PROCESSING", uploaded_by=user_id)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def _bulk_insert(db: Session, model: type, rows: list[dict]) -> None:
    """INSERT many rows; on PostgreSQL via COPY inside the import transaction (row-by-row inserts of the
    16k GPs took ~8 s). A key missing from a row gets the column's scalar default, as with insert()."""
    if not rows:
        return
    if not is_postgres():
        db.execute(insert(model), rows)
        return
    keys = set().union(*rows)
    cols = [c for c in model.__table__.columns if c.name in keys]
    fill = {c.name: (c.default.arg if c.default is not None and c.default.is_scalar else None) for c in cols}
    raw = db.connection().connection.driver_connection  # psycopg connection of this session's transaction
    names = ", ".join(f'"{c.name}"' for c in cols)
    with raw.cursor() as cur, cur.copy(f"COPY {model.__tablename__} ({names}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(tuple(r.get(c.name, fill[c.name]) for c in cols))


def _write(db: Session, ds_id: int, parsed: ParsedWorkbook, file_name: str = "") -> None:
    _bulk_insert(db, Gp, [{**g, "dataset_id": ds_id} for g in parsed.gps])
    # ~800k availability values -> four compressed matrices (row-per-value inserts took ~60 s on PostgreSQL).
    frames = wide_frames(parsed.availability)
    db.execute(insert(GpAvailabilityPack), [pack(ds_id, kind, frame) for kind, frame in frames.items()])
    # Daily values also go into the cross-upload history (previous month to date needs days later files drop).
    if parsed.data_as_of is not None:
        merge_daily(db, frames.get("D"), parsed.data_as_of, file_name)
    _bulk_insert(db, GpAmcPlan, [{**r, "dataset_id": ds_id} for r in parsed.amc_plan])
    if parsed.circle_sheets:
        db.execute(insert(CircleSheetValue), [{**c, "dataset_id": ds_id} for c in parsed.circle_sheets])
    if parsed.weeks:
        db.execute(insert(DatasetWeek), [{**w, "dataset_id": ds_id} for w in parsed.weeks])
    if parsed.reported:
        db.execute(insert(ReportedNumber), [{**r, "dataset_id": ds_id} for r in parsed.reported])
    if parsed.master_blocks:
        uniq = {m["block_code"]: m for m in parsed.master_blocks}
        db.execute(insert(MasterBlock), [{**m, "dataset_id": ds_id} for m in uniq.values()])
    if parsed.issues:
        _bulk_insert(
            db,
            ValidationIssue,
            [
                {
                    "dataset_id": ds_id,
                    "sheet": i.sheet,
                    "row_number": i.row_number,
                    "column": i.column,
                    "gp_code": i.gp_code,
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message[:2000],
                }
                for i in parsed.issues
            ],
        )


# One import at a time for the whole process: uploads, retries, the start-up import and the CLI all go through it.
INGEST_LOCK = threading.Lock()


def run_ingestion(dataset_id: int) -> None:
    """Parse + load a dataset. Safe to run in a background thread (own session); imports run one after another."""
    with INGEST_LOCK:
        _run_ingestion(dataset_id)


def _run_ingestion(dataset_id: int) -> None:
    started = time.perf_counter()
    with SessionLocal() as db:
        ds = db.get(Dataset, dataset_id)
        if ds is None:
            return
        path = Path(ds.stored_path)
    try:
        parsed = parse_workbook(path)  # outside any transaction: parsing takes many seconds
        with SessionLocal() as db:
            ds = db.get(Dataset, dataset_id)
            if is_postgres():
                db.execute(text("SET LOCAL statement_timeout = 0"))  # bulk import: no per-statement limit
            # Remove partial rows from a previous attempt of the same dataset (retry).
            for model in DATA_TABLES:
                db.execute(delete(model).where(model.dataset_id == ds.id))
            _write(db, ds.id, parsed, ds.file_name)
            from .report import save_report

            save_report(db, ds, parsed)  # what changed vs the previous upload (never fails the import)
            ds.rows_total = parsed.rows_total
            ds.rows_rejected = parsed.rows_rejected
            ds.rows_accepted = parsed.rows_total - parsed.rows_rejected
            ds.data_as_of = parsed.data_as_of
            ds.status = "PARTIAL" if parsed.rows_rejected else "SUCCESS"
            ds.message = None
            ds.finished_at = datetime.now(UTC)
            db.flush()
            # Activate atomically together with the data – unless another stored dataset has newer data.
            best_id = _best_dataset(db)
            activated = best_id in (None, ds.id)
            if activated:
                db.execute(update(Dataset).where(Dataset.id != ds.id).values(is_active=False))
                ds.is_active = True
            else:
                best = db.get(Dataset, best_id)
                ds.is_active = False
                ds.message = f"Imported but not activated: run #{best.id} has newer data (as of {best.data_as_of}) and stays active."
            db.commit()
    except WorkbookError as exc:
        _fail(dataset_id, str(exc))
        return
    except Exception:  # unexpected – never leak internals to the UI
        log.exception("Ingestion %s failed", dataset_id)
        _fail(dataset_id, "Unexpected error while processing the file. See server logs.")
        return
    log.info("Dataset %s imported in %.1fs (%s)", dataset_id, time.perf_counter() - started, "active" if activated else "not activated")
    if activated:
        from ..analytics.store import reload_store

        reload_store()  # dashboard switches to the new data once its snapshot is ready
    with SessionLocal() as db:
        _prune(db)


OK_STATUSES = ("SUCCESS", "PARTIAL")


def _best_dataset(db: Session, exclude: int | None = None) -> int | None:
    """The successful dataset with rows still stored and the newest data date (tie: the later import)."""
    has_rows = select(Gp.gp_code).where(Gp.dataset_id == Dataset.id).exists()
    q = select(Dataset.id).where(Dataset.status.in_(OK_STATUSES), has_rows)
    if exclude is not None:
        q = q.where(Dataset.id != exclude)
    return db.scalar(q.order_by(Dataset.data_as_of.is_(None), Dataset.data_as_of.desc(), Dataset.id.desc()).limit(1))


def _fail(ds_id: int, message: str) -> None:
    switched = False
    with SessionLocal() as db:
        ds = db.get(Dataset, ds_id)
        if ds is None:
            return
        ds.status = "FAILED"
        ds.message = message
        ds.finished_at = datetime.now(UTC)
        if ds.is_active:  # a failed dataset is never served: fall back to the best remaining one
            ds.is_active = False
            if (other := _best_dataset(db, exclude=ds.id)) is not None:
                db.execute(update(Dataset).where(Dataset.id == other).values(is_active=True))
            switched = True
        db.commit()
        _prune(db)
    if switched:
        from ..analytics.store import reload_store

        reload_store()


def unlink_upload(path: str | Path) -> None:
    """Delete a stored upload; files outside the upload folder (CLI / start-up imports from data/raw) are never touched."""
    p = Path(path).resolve()
    if p.is_relative_to(get_settings().upload_dir.resolve()):
        p.unlink(missing_ok=True)


def prune_files(rows: Sequence[Any], keep_ids: set[int]) -> None:
    """Delete the upload files of pruned imports and of failed ones beyond the newest KEEP_DATASETS (rows: id, status,
    is_active, stored_path – newest first). Files still referenced by a kept import or the active one stay."""
    failed = [r.id for r in rows if r.status == "FAILED"][KEEP_DATASETS:]
    drop = {r.id for r in rows if r.status in OK_STATUSES and r.id not in keep_ids} | set(failed)
    keep_paths = {r.stored_path for r in rows if r.id not in drop or r.is_active}
    for r in rows:
        if r.id in drop and not r.is_active and r.stored_path not in keep_paths:
            unlink_upload(r.stored_path)


def _prune(db: Session) -> None:
    """Keep the rows of the newest successful datasets and of the active one; delete upload files nobody needs."""
    rows = db.execute(select(Dataset.id, Dataset.status, Dataset.is_active, Dataset.stored_path).order_by(Dataset.id.desc())).all()
    ok = [r for r in rows if r.status in OK_STATUSES]
    keep = {r.id for r in ok[:KEEP_DATASETS]} | {r.id for r in rows if r.is_active}
    old = [r.id for r in ok if r.id not in keep]
    if old:
        if is_postgres():
            db.execute(text("SET LOCAL statement_timeout = 0"))
        for model in DATA_TABLES:
            db.execute(delete(model).where(model.dataset_id.in_(old)))
        db.commit()
    prune_files(rows, keep)


def import_file(path: Path, user_id: int | None = None) -> Dataset:
    """Synchronous import (CLI / first start)."""
    with SessionLocal() as db:
        ds = create_dataset(db, path, path.name, user_id)
    run_ingestion(ds.id)
    with SessionLocal() as db:
        return db.get(Dataset, ds.id)  # type: ignore[return-value]
