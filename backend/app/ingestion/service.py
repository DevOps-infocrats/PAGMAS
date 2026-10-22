"""Import a workbook into the database as a new dataset and activate it."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.orm import Session

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


def create_dataset(db: Session, path: Path, file_name: str, user_id: int | None) -> Dataset:
    ds = Dataset(file_name=file_name, stored_path=str(path), sha256=sha256_of(path), status="PROCESSING", uploaded_by=user_id)
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
        try:
            parsed = parse_workbook(Path(ds.stored_path))
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
            # Activate atomically together with the data.
            db.execute(update(Dataset).where(Dataset.id != ds.id).values(is_active=False))
            ds.is_active = True
            db.commit()
        except WorkbookError as exc:
            db.rollback()
            _fail(db, ds.id, str(exc))
            return
        except Exception:  # unexpected – never leak internals to the UI
            db.rollback()
            log.exception("Ingestion %s failed", dataset_id)
            _fail(db, ds.id, "Unexpected error while processing the file. See server logs.")
            return
    log.info("Dataset %s imported in %.1fs", dataset_id, time.perf_counter() - started)
    from ..analytics.store import reload_store

    reload_store()  # dashboard switches to the new data once its snapshot is ready
    with SessionLocal() as db:
        _prune(db)


def _fail(db: Session, ds_id: int, message: str) -> None:
    ds = db.get(Dataset, ds_id)
    if ds:
        ds.status = "FAILED"
        ds.message = message
        ds.finished_at = datetime.now(UTC)
        db.commit()


def _prune(db: Session) -> None:
    """Keep the newest successful datasets (and their files' metadata) only."""
    ids = db.scalars(select(Dataset.id).where(Dataset.status.in_(["SUCCESS", "PARTIAL"])).order_by(Dataset.id.desc())).all()
    old = ids[KEEP_DATASETS:]
    if old:
        if is_postgres():
            db.execute(text("SET LOCAL statement_timeout = 0"))
        for model in DATA_TABLES:
            db.execute(delete(model).where(model.dataset_id.in_(old)))
        db.commit()


def import_file(path: Path, user_id: int | None = None) -> Dataset:
    """Synchronous import (CLI / first start)."""
    with SessionLocal() as db:
        ds = create_dataset(db, path, path.name, user_id)
    run_ingestion(ds.id)
    with SessionLocal() as db:
        return db.get(Dataset, ds.id)  # type: ignore[return-value]
