"""Escalation Matrix workbook: GP-wise field team and escalation contacts.

The file is separate from the master data workbook and can be uploaded on its own or together with it (several files
in one go). `detect_kind` looks at the content, not the file name:
  * a workbook with the GP sheet ("GP Wise Data") is master data;
  * otherwise a sheet whose header row has GP Code + FRT Code + FE Name is an Escalation Matrix.

Each import is kept as its own version (escalation_imports); the newest successful one is active.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from ..db import SessionLocal, is_postgres
from ..models import EscalationContact, EscalationImport
from .column_map import load_column_map, resolve_sheet
from .workbook import WorkbookError, norm, open_workbook

log = logging.getLogger(__name__)
KEEP_IMPORTS = 3
ESC_LOCK = threading.Lock()

# field -> accepted header names (matched case- and space-insensitively)
COLUMNS: dict[str, tuple[str, ...]] = {
    "circle": ("Circle", "State"),
    "district": ("District",),
    "block_name": ("Block", "Block Name"),
    "block_code": ("Block Code",),
    "gp_name": ("GP", "GP Name"),
    "gp_code": ("GP Code",),
    "frt_code": ("FRT Code",),
    "splicer_name": ("Name of splicer", "Splicer Name"),
    "splicer_phone": ("Splicer Contact No.", "Splicer Contact No", "Splicer Contact Number"),
    "fe_name": ("FE Name",),
    "fe_phone": ("FE Contact No", "FE Contact No.", "FE Contact Number"),
    "am_name": ("AM Name",),
    "am_phone": ("AM Contact No", "AM Contact No.", "AM Contact Number"),
    "shq_name": ("SHQ Spoc", "SHQ SPOC"),
    "shq_phone": ("SHQ Spoc Contact No", "SHQ SPOC Contact No", "SHQ Spoc Contact No."),
    "coh_name": ("COH",),
    "coh_phone": ("COH Number", "COH Contact No"),
    "cbh_name": ("CBH",),
    "cbh_phone": ("CBH Number", "CBH Contact No"),
}
REQUIRED = ("circle", "gp_code", "frt_code", "fe_name")
_NAMES = {k: {norm(n) for n in v} for k, v in COLUMNS.items()}


@dataclass
class ParsedEscalation:
    sheet: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    rows_total: int = 0
    rows_rejected: int = 0


def _header_row(grid: list[list[Any]]) -> int | None:
    for i, row in enumerate(grid[:15]):
        cells = {norm(c) for c in row}
        if all(cells & _NAMES[k] for k in REQUIRED):
            return i
    return None


def detect_kind(path: Path) -> Literal["master", "escalation"] | None:
    """What an uploaded workbook is, from its content."""
    wb = open_workbook(path)
    if resolve_sheet(wb.sheet_names, "gp", load_column_map()):
        return "master"
    for name in wb.sheet_names:
        grid = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        if _header_row(grid[:15]) is not None:
            return "escalation"
    return None


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        if v.is_integer():
            v = int(v)
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _code(v: Any) -> str | None:
    s = _text(v)
    return s[:-2] if s and s.endswith(".0") else s


def phone(v: Any) -> str | None:
    """Phone number(s) as digits, several numbers joined by " / " (Excel stores them as floats: 9876543210.0)."""
    s = _text(v)
    if not s:
        return None
    parts = [re.sub(r"\D", "", p) for p in re.split(r"[/,;]| {2,}", s)]
    parts = [p for p in parts if p]
    return " / ".join(parts) or None


def parse_escalation(path: Path) -> ParsedEscalation:
    wb = open_workbook(path)
    for name in wb.sheet_names:
        grid = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        hdr = _header_row(grid)
        if hdr is not None:
            break
    else:
        raise WorkbookError("No sheet with the Escalation Matrix columns (GP Code, FRT Code, FE Name …) was found")
    header = [norm(c) for c in grid[hdr]]
    cols = {k: next((i for i, h in enumerate(header) if h in names), None) for k, names in _NAMES.items()}
    out = ParsedEscalation(sheet=name)
    seen: set[str] = set()
    for row in grid[hdr + 1 :]:
        if all(_text(v) is None for v in row[:12]):
            continue
        cell = lambda k: row[cols[k]] if cols[k] is not None and cols[k] < len(row) else None  # noqa: E731
        circle = _text(cell("circle"))
        if circle == "@":
            continue
        out.rows_total += 1
        gp = _code(cell("gp_code"))
        if not gp or not circle or gp in seen:
            out.rows_rejected += 1
            continue
        seen.add(gp)
        rec: dict[str, Any] = {"gp_code": gp, "circle": circle.upper(), "block_code": _code(cell("block_code"))}
        for k in ("district", "block_name", "gp_name", "frt_code", "splicer_name", "fe_name", "am_name", "shq_name", "coh_name", "cbh_name"):
            rec[k] = _text(cell(k))
        for k in ("splicer_phone", "fe_phone", "am_phone", "shq_phone", "coh_phone", "cbh_phone"):
            rec[k] = phone(cell(k))
        out.rows.append(rec)
    if not out.rows:
        raise WorkbookError(f"'{name}': no GP rows found below the header")
    return out


def create_import(db: Session, path: Path, file_name: str, sha: str, user_id: int | None) -> EscalationImport:
    imp = EscalationImport(file_name=file_name, stored_path=str(path), sha256=sha, status="PROCESSING", uploaded_by=user_id)
    db.add(imp)
    db.commit()
    db.refresh(imp)
    return imp


def run_escalation_import(import_id: int) -> None:
    """Parse + load an Escalation Matrix (background thread, own session; one at a time)."""
    with ESC_LOCK:
        started = time.perf_counter()
        with SessionLocal() as db:
            imp = db.get(EscalationImport, import_id)
            if imp is None:
                return
            try:
                parsed = parse_escalation(Path(imp.stored_path))
                if is_postgres():
                    db.execute(text("SET LOCAL statement_timeout = 0"))
                db.execute(delete(EscalationContact).where(EscalationContact.import_id == imp.id))
                from .service import _bulk_insert

                _bulk_insert(db, EscalationContact, [{**r, "import_id": imp.id} for r in parsed.rows])
                imp.rows_total, imp.rows_rejected = parsed.rows_total, parsed.rows_rejected
                imp.status, imp.message, imp.finished_at = "SUCCESS", None, datetime.now(UTC)
                db.execute(update(EscalationImport).where(EscalationImport.id != imp.id).values(is_active=False))
                imp.is_active = True
                db.commit()
            except WorkbookError as exc:
                db.rollback()
                _fail(db, import_id, str(exc))
                return
            except Exception:
                db.rollback()
                log.exception("Escalation import %s failed", import_id)
                _fail(db, import_id, "Unexpected error while processing the file. See server logs.")
                return
            _prune(db)
        from ..analytics.escalation import invalidate_escalation

        invalidate_escalation()
        log.info("Escalation matrix %s imported in %.1fs", import_id, time.perf_counter() - started)


def _fail(db: Session, import_id: int, message: str) -> None:
    imp = db.get(EscalationImport, import_id)
    if imp:
        imp.status, imp.message, imp.finished_at = "FAILED", message, datetime.now(UTC)
        db.commit()


def _prune(db: Session) -> None:
    ids = db.scalars(select(EscalationImport.id).where(EscalationImport.status == "SUCCESS").order_by(EscalationImport.id.desc())).all()
    old = ids[KEEP_IMPORTS:]
    if old:
        db.execute(delete(EscalationContact).where(EscalationContact.import_id.in_(old)))
        db.commit()
