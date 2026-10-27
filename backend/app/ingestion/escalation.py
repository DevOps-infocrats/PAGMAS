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
from ..models import Dataset, EscalationContact, EscalationImport, Gp
from .column_map import ESCALATION_REQUIRED, load_column_map, locate, resolve_sheet
from .workbook import WorkbookError, clean_code, code_key, norm, open_workbook, read_sheet

log = logging.getLogger(__name__)
KEEP_IMPORTS = 3
ESC_LOCK = threading.Lock()

# Accepted header names per field: built-in list in column_map.ESCALATION_COLUMNS, plus any names added to the
# "escalationColumns" section of data/column_map.json (matched case- and space-insensitively).
REQUIRED = ESCALATION_REQUIRED
TEXT_FIELDS = ("ba", "district", "block_name", "gp_name", "frt_code", "splicer_name", "fe_name", "am_name", "shq_name", "coh_name", "cbh_name")
PHONE_FIELDS = ("splicer_phone", "fe_phone", "am_phone", "shq_phone", "coh_phone", "cbh_phone")
EMAIL_FIELDS = ("am_email", "shq_email", "coh_email", "cbh_email")
EMAIL_RE = re.compile(r"[^@\s,;/]+@[^@\s,;/]+\.[^@\s,;/]+")


def _names() -> dict[str, tuple[str, ...]]:
    return load_column_map().escalation


@dataclass
class ParsedEscalation:
    sheet: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    rows_total: int = 0
    rows_rejected: int = 0
    rejected: list[str] = field(default_factory=list)  # "row 12: no GP code"
    missing: list[str] = field(default_factory=list)  # optional fields whose column was not found

    def summary(self, limit: int = 20) -> str | None:
        """Rejected rows and columns not found, for the import message (escalation imports have no issue table)."""
        parts = []
        if self.rejected:
            more = f"; … {len(self.rejected) - limit} more" if len(self.rejected) > limit else ""
            parts.append(f"{len(self.rejected)} row(s) of '{self.sheet}' rejected: " + "; ".join(self.rejected[:limit]) + more)
        if self.missing:
            parts.append(f"Columns not found (left empty – add the file's header to escalationColumns in data/column_map.json): {', '.join(self.missing)}")
        return ". ".join(parts) or None


def _header_row(grid: list[list[Any]], names: dict[str, tuple[str, ...]] | None = None) -> int | None:
    names = names or _names()
    for i, row in enumerate(grid[:15]):
        cells = {norm(c) for c in row}
        if all(cells & set(names[k]) for k in REQUIRED):
            return i
    return None


def detect_kind(path: Path) -> Literal["master", "escalation"] | None:
    """What an uploaded workbook is, from its content (only the first 15 rows of each sheet are read)."""
    wb = open_workbook(path)
    try:
        if resolve_sheet(wb.sheet_names, "gp", load_column_map()):
            return "master"
        for name in wb.sheet_names:
            if _header_row(read_sheet(wb, name, nrows=15)) is not None:
                return "escalation"
    except WorkbookError:
        raise
    except Exception as exc:  # corrupt workbook content
        raise WorkbookError(f"Workbook could not be read: {exc}") from exc
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


_code = clean_code


def phone(v: Any) -> str | None:
    """Phone number(s) as digits, several numbers joined by " / " (Excel stores them as floats: 9876543210.0)."""
    s = _text(v)
    if not s:
        return None
    parts = [re.sub(r"\D", "", p) for p in re.split(r"[/,;]| {2,}", s)]
    parts = [p for p in parts if p.strip("0")]  # "0" = no number in the sheet
    return " / ".join(parts) or None


def email(v: Any) -> str | None:
    """E-mail address(es), lower-case, several joined by " / "; text that is not an address is dropped."""
    s = _text(v)
    if not s:
        return None
    found = [e.lower() for e in EMAIL_RE.findall(s)]
    return " / ".join(dict.fromkeys(found)) or None


def parse_escalation(path: Path) -> ParsedEscalation:
    names = _names()
    wb = open_workbook(path)
    for name in wb.sheet_names:
        grid = read_sheet(wb, name)
        hdr = _header_row(grid, names)
        if hdr is not None:
            break
    else:
        raise WorkbookError("No sheet with the Escalation Matrix columns (GP Code, FRT Code, FE Name …) was found")
    cols: dict[str, int | None] = {k: None for k in names}
    cols.update(locate(grid[hdr], names).columns)
    out = ParsedEscalation(sheet=name)
    missing = [k for k in (*PHONE_FIELDS, "ba", *EMAIL_FIELDS) if cols[k] is None]
    if missing:
        out.missing = missing
    seen: dict[str, int] = {}  # code key -> Excel row
    for i, row in enumerate(grid[hdr + 1 :], start=hdr + 2):
        if all(_text(v) is None for v in row[:12]):
            continue
        cell = lambda k: row[cols[k]] if cols[k] is not None and cols[k] < len(row) else None  # noqa: E731
        circle = _text(cell("circle"))
        if circle == "@":
            continue
        out.rows_total += 1
        gp = _code(cell("gp_code"))
        reason = "no GP code" if not gp else "no circle" if not circle else f"duplicate GP code {gp} (first on row {seen[code_key(gp)]})" if code_key(gp) in seen else None
        if reason:
            out.rows_rejected += 1
            out.rejected.append(f"row {i}: {reason}")
            continue
        seen[code_key(gp)] = i
        rec: dict[str, Any] = {"gp_code": gp, "circle": circle.upper(), "block_code": _code(cell("block_code"))}
        for k in TEXT_FIELDS:
            v = _text(cell(k))
            rec[k] = None if v == "0" else v  # "0" = nobody in the sheet
        for k in PHONE_FIELDS:
            rec[k] = phone(cell(k))
        for k in EMAIL_FIELDS:
            rec[k] = email(cell(k))
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
            path = Path(imp.stored_path)
        try:
            parsed = parse_escalation(path)  # outside any transaction
            with SessionLocal() as db:
                imp = db.get(EscalationImport, import_id)
                if is_postgres():
                    db.execute(text("SET LOCAL statement_timeout = 0"))
                db.execute(delete(EscalationContact).where(EscalationContact.import_id == imp.id))
                from .service import _bulk_insert

                # Spell each GP code as the active master data does ('33977' in the matrix, '033977' in the master file).
                master = {code_key(c): c for c in db.scalars(select(Gp.gp_code).join(Dataset, Dataset.id == Gp.dataset_id).where(Dataset.is_active.is_(True)))}
                _bulk_insert(db, EscalationContact, [{**r, "gp_code": master.get(code_key(r["gp_code"]), r["gp_code"]), "import_id": imp.id} for r in parsed.rows])
                imp.rows_total, imp.rows_rejected = parsed.rows_total, parsed.rows_rejected
                imp.status, imp.message, imp.finished_at = "SUCCESS", parsed.summary(), datetime.now(UTC)
                newer = db.scalar(select(EscalationImport.id).where(EscalationImport.status == "SUCCESS", EscalationImport.id > imp.id).limit(1))
                activated = newer is None
                if activated:
                    db.execute(update(EscalationImport).where(EscalationImport.id != imp.id).values(is_active=False))
                    imp.is_active = True
                else:
                    imp.message = "; ".join(filter(None, [f"Imported but not activated: the newer import #{newer} stays active", imp.message]))
                db.commit()
        except WorkbookError as exc:
            _fail(import_id, str(exc))
            return
        except Exception:
            log.exception("Escalation import %s failed", import_id)
            _fail(import_id, "Unexpected error while processing the file. See server logs.")
            return
        with SessionLocal() as db:
            _prune(db)
        if activated:
            from ..analytics.escalation import invalidate_escalation

            invalidate_escalation()
        log.info("Escalation matrix %s imported in %.1fs", import_id, time.perf_counter() - started)


def _fail(import_id: int, message: str) -> None:
    with SessionLocal() as db:
        imp = db.get(EscalationImport, import_id)
        if imp is None:
            return
        imp.status, imp.message, imp.finished_at = "FAILED", message, datetime.now(UTC)
        was_active, imp.is_active = imp.is_active, False
        if was_active and (other := db.scalar(select(EscalationImport.id).where(EscalationImport.status == "SUCCESS", EscalationImport.id != imp.id).order_by(EscalationImport.id.desc()).limit(1))):
            db.execute(update(EscalationImport).where(EscalationImport.id == other).values(is_active=True))
        db.commit()
        _prune(db)
    if was_active:
        from ..analytics.escalation import invalidate_escalation

        invalidate_escalation()


def _prune(db: Session) -> None:
    """Keep the contacts of the newest successful imports and of the active one; delete upload files nobody needs."""
    from .service import prune_files

    rows = db.execute(select(EscalationImport.id, EscalationImport.status, EscalationImport.is_active, EscalationImport.stored_path).order_by(EscalationImport.id.desc())).all()
    ok = [r for r in rows if r.status == "SUCCESS"]
    keep = {r.id for r in ok[:KEEP_IMPORTS]} | {r.id for r in rows if r.is_active}
    old = [r.id for r in ok if r.id not in keep]
    if old:
        db.execute(delete(EscalationContact).where(EscalationContact.import_id.in_(old)))
        db.commit()
    prune_files(rows, keep)
