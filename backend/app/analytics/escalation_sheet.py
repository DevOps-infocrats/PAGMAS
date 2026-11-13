"""Field Team & Escalation → Escalation Sheet: the active Escalation Matrix as an editable spreadsheet.

Read      every signed-in user, only the GPs of their areas (the viewer's scoped snapshot); phone numbers in full for
          admins only (masked otherwise – same rule as the rest of Field Team & Escalation).
Edit      admins only. A change is applied to the active import's row of that GP (escalation_contacts) – the table every
          page reads (Field Team & Escalation, AMC Conversion AM tables, Generate Ticket AM / FE lists, e-mail
          audiences) – so a corrected AM name shows everywhere at once. Each change is checked:
            * the column is editable (GP Code and Circle identify the row and are never edited here),
            * the value is valid for its column (phone: 10 digits starting 6–9, several joined by " / "; e-mail: a real
              address; text: trimmed, single spaces, within the column length). Blank = empty, never "0",
            * nobody changed the cell meanwhile (the value the browser showed must still be the stored one),
          all-or-nothing: one invalid / conflicting change saves nothing and every problem is returned with its cell.
          Every saved change is recorded (escalation_edits: who, when, old → new) and in the audit log.
Replace   "find and replace" in one column (e.g. an Area Manager's name on all their GPs) within the current filters,
          whole-cell match ignoring case and extra spaces; previewed (count) before it is applied.
Export    the filtered rows as .xlsx with the Escalation Matrix upload headers, so the edited matrix can be uploaded again.
A later Escalation Matrix upload replaces the contacts (and with them these edits) – the page says so.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..models import EscalationContact, EscalationEdit, EscalationImport
from .escalation import NoEscalationData, _active, _frame, invalidate_escalation, mask
from .store import Store

PHONE_PART = re.compile(r"[6-9]\d{9}")
EMAIL_RE = re.compile(r"[^@\s,;/]+@[^@\s,;/]+\.[^@\s,;/]+")


@dataclass(frozen=True)
class Col:
    key: str  # escalation_contacts column
    label: str  # Escalation Matrix upload header (export uses it, so the file can be uploaded again)
    kind: str = "text"  # text | phone | email
    editable: bool = True


COLUMNS: tuple[Col, ...] = (
    Col("circle", "Circle", editable=False),
    Col("ba", "BA"),
    Col("district", "District"),
    Col("block_name", "Block Name"),
    Col("block_code", "Block Code", editable=False),
    Col("gp_name", "GP"),
    Col("gp_code", "GP Code", editable=False),
    Col("frt_code", "FRT Code"),
    Col("splicer_name", "Splicer Name"),
    Col("splicer_phone", "Splicer number", "phone"),
    Col("fe_name", "FE Name"),
    Col("fe_phone", "FE Number", "phone"),
    Col("fe_email", "FE Email ID", "email"),
    Col("am_name", "AM Name"),
    Col("am_phone", "AM Number", "phone"),
    Col("am_email", "AM Email ID", "email"),
    Col("shq_name", "SME Name"),
    Col("shq_phone", "SME Number", "phone"),
    Col("shq_email", "SME Email ID", "email"),
    Col("coh_name", "COH"),
    Col("coh_phone", "COH No.", "phone"),
    Col("coh_email", "COH Email ID", "email"),
    Col("cbh_name", "CBH"),
    Col("cbh_phone", "CBH No.", "phone"),
    Col("cbh_email", "CBH Email ID", "email"),
)
BY_KEY = {c.key: c for c in COLUMNS}
EDITABLE = {c.key for c in COLUMNS if c.editable}
MAX_CHANGES = 300  # one save stays below the API's 64 KB JSON body limit; the page saves larger edits in parts


class SheetError(Exception):
    def __init__(self, status: int, message: str, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.problems = status, message, problems or []


def _length(key: str) -> int:
    return getattr(EscalationContact.__table__.columns[key].type, "length", None) or 200


def _str(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v)
    return s if s.strip() else None


def normalise(key: str, value: Any) -> str | None:
    """The value as it will be stored, or SheetError(422) with the reason. Blank -> None (empty, never '0')."""
    col = BY_KEY[key]
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if col.kind == "phone":
        parts = [re.sub(r"\D", "", p) for p in re.split(r"[/,;]", text) if p.strip()]
        bad = [p for p in parts if not PHONE_PART.fullmatch(p)]
        if bad or not parts:
            raise SheetError(422, f"'{text}' is not a valid mobile number (10 digits starting 6–9; several numbers separated by /)")
        text = " / ".join(dict.fromkeys(parts))
    elif col.kind == "email":
        found = [e.lower() for e in EMAIL_RE.findall(text)]
        leftover = EMAIL_RE.sub("", text).replace("/", "").replace(",", "").replace(";", "").strip()
        if not found or leftover:
            raise SheetError(422, f"'{text}' is not a valid e-mail address (several addresses separated by /)")
        text = " / ".join(dict.fromkeys(found))
    if len(text) > _length(key):
        raise SheetError(422, f"Too long – at most {_length(key)} characters")
    return text


def _same(a: Any, b: Any) -> bool:
    return (_str(a) or None) == (_str(b) or None)


# ---------------------------------------------------------------- reading


def _filtered(store: Store, circle: str | None, district: str | None, block: str | None, search: str | None) -> tuple[dict[str, Any], pd.DataFrame]:
    meta, df = _frame(store)  # scoped to the viewer's areas; joined to the master data's location ids
    if circle:
        df = df[df["circle_id"] == circle]
    if district:
        df = df[df["district_id"] == district]
    if block:
        df = df[df["block_id"] == block]
    if search and search.strip():
        q = search.strip().lower()
        hay = pd.Series("", index=df.index)
        for c in COLUMNS:
            if c.key == "gp_code":
                hay = hay + " " + df.index.astype(str)
            elif c.key in df.columns:
                hay = hay + " " + df[c.key].fillna("").astype(str)
        df = df[hay.str.lower().str.contains(re.escape(q), regex=True)]
    order = pd.DataFrame({"c": df["circle_name"].astype(str), "d": df["district_name"].astype(str), "b": df["block_label"].astype(str), "g": df.index.astype(str)}, index=df.index)
    return meta, df.loc[order.sort_values(["c", "d", "b", "g"]).index]


def _row(code: str, r: pd.Series, full: bool) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for c in COLUMNS:
        v = code if c.key == "gp_code" else r.get(c.key)
        v = _str(v)
        values[c.key] = mask(v, full) if c.kind == "phone" else v
    return {"gpCode": code, "values": values, "inMaster": bool(r.get("in_master"))}


def _edits_meta(db: Session, import_id: int) -> dict[str, Any]:
    from sqlalchemy import func

    n, last = db.execute(select(func.count(), func.max(EscalationEdit.edited_at)).where(EscalationEdit.import_id == import_id)).one()
    return {"edits": int(n or 0), "lastEditAt": last.isoformat() if last else None}


def sheet(db: Session, store: Store, circle: str | None, district: str | None, block: str | None, search: str | None, page: int, page_size: int, admin: bool) -> dict[str, Any]:
    meta, df = _filtered(store, circle, district, block, search)
    total = len(df)
    part = df.iloc[(page - 1) * page_size : page * page_size]
    return {
        "source": {"importId": meta["id"], "fileName": meta["fileName"], "importedAt": meta["importedAt"], **_edits_meta(db, meta["id"])},
        "columns": [{"key": c.key, "label": c.label, "kind": c.kind, "editable": admin and c.editable, "maxLength": _length(c.key)} for c in COLUMNS],
        "rows": [_row(str(code), r, admin) for code, r in part.iterrows()],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "canEdit": admin,
        "phonesMasked": not admin,
    }


# ---------------------------------------------------------------- editing (admins)


def _active_import(db: Session, import_id: int) -> EscalationImport:
    imp = db.get(EscalationImport, import_id)
    if imp is None or not imp.is_active:
        raise SheetError(409, "The Escalation Matrix was replaced by a newer upload meanwhile – reload the sheet (your unsaved changes were not applied)")
    return imp


def apply_changes(db: Session, store: Store, import_id: int, changes: list[dict[str, Any]], user_id: int, user_name: str) -> dict[str, Any]:
    """changes: {gpCode, field, old, new}. All-or-nothing (see module docstring). Returns the saved count and the new
    values of the changed rows."""
    if not changes:
        raise SheetError(422, "Nothing to save")
    if len(changes) > MAX_CHANGES:
        raise SheetError(422, f"At most {MAX_CHANGES} cells per save – save in parts")
    _active_import(db, import_id)
    allowed = set(_frame(store)[1].index.astype(str))  # an admin's snapshot has every GP; kept for safety
    codes = list(dict.fromkeys(str(c.get("gpCode") or "") for c in changes))
    rows = {r.gp_code: r for r in db.scalars(select(EscalationContact).where(EscalationContact.import_id == import_id, EscalationContact.gp_code.in_(codes)))}
    problems: list[dict[str, Any]] = []
    planned: list[tuple[EscalationContact, str, str | None, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for ch in changes:
        code, key = str(ch.get("gpCode") or ""), str(ch.get("field") or "")
        cell = {"gpCode": code, "field": key}
        if (code, key) in seen:
            problems.append(cell | {"message": "The same cell is changed twice"})
            continue
        seen.add((code, key))
        if key not in EDITABLE:
            problems.append(cell | {"message": f"'{BY_KEY[key].label if key in BY_KEY else key}' cannot be edited here"})
            continue
        row = rows.get(code)
        if row is None or code not in allowed:
            problems.append(cell | {"message": f"GP {code} is not in the active Escalation Matrix"})
            continue
        try:
            new = normalise(key, ch.get("new"))
        except SheetError as exc:
            problems.append(cell | {"message": exc.message})
            continue
        current = getattr(row, key)
        if not _same(current, ch.get("old")):
            problems.append(cell | {"message": f"Changed by someone else meanwhile (now '{current or ''}') – reload to see it", "conflict": True, "current": current})
            continue
        if _same(current, new):
            continue  # no real change (e.g. only spaces)
        planned.append((row, key, current, new))
    if problems:
        raise SheetError(409 if any(p.get("conflict") for p in problems) else 422, f"{len(problems)} cell(s) could not be saved – nothing was saved", problems)
    return _save(db, import_id, planned, user_id, user_name)


def _save(db: Session, import_id: int, planned: list[tuple[EscalationContact, str, str | None, str | None]], user_id: int, user_name: str) -> dict[str, Any]:
    if not planned:
        return {"saved": 0, "rows": []}
    from ..tickets.service import now

    stamp = now()
    for row, key, _old, new in planned:
        setattr(row, key, new)
    db.execute(
        insert(EscalationEdit),
        [{"import_id": import_id, "gp_code": row.gp_code, "field": key, "old_value": old, "new_value": new, "edited_by": user_id, "edited_by_name": user_name, "edited_at": stamp} for row, key, old, new in planned],
    )
    db.commit()
    invalidate_escalation()  # every page reads the new values from now on
    changed = {row.gp_code: row for row, *_ in planned}
    return {"saved": len(planned), "rows": [{"gpCode": code, "values": {c.key: (code if c.key == "gp_code" else getattr(r, c.key)) for c in COLUMNS}} for code, r in changed.items()]}


def replace_all(
    db: Session, store: Store, import_id: int, key: str, find: str, replace: str, circle: str | None, district: str | None, block: str | None, dry_run: bool, user_id: int, user_name: str
) -> dict[str, Any]:
    """Whole-cell find and replace in one column within the filters (case and extra spaces ignored)."""
    if key not in EDITABLE:
        raise SheetError(422, f"'{BY_KEY[key].label if key in BY_KEY else key}' cannot be edited here")
    _active_import(db, import_id)
    target = " ".join((find or "").split()).lower()
    if not target:
        raise SheetError(422, "Enter the value to find")
    new = normalise(key, replace)
    _, df = _filtered(store, circle, district, block, None)
    hits = [str(code) for code, v in df[key].items() if isinstance(v, str) and " ".join(v.split()).lower() == target]
    if dry_run or not hits:
        return {"matches": len(hits), "saved": 0, "sample": hits[:10]}
    rows = list(db.scalars(select(EscalationContact).where(EscalationContact.import_id == import_id, EscalationContact.gp_code.in_(hits))))
    planned = [(r, key, getattr(r, key), new) for r in rows if " ".join(str(getattr(r, key) or "").split()).lower() == target and not _same(getattr(r, key), new)]
    out = _save(db, import_id, planned, user_id, user_name)
    return {"matches": len(hits), "saved": out["saved"], "sample": hits[:10]}


def edits(db: Session, import_id: int, gp_code: str | None, limit: int = 100) -> list[dict[str, Any]]:
    q = select(EscalationEdit).where(EscalationEdit.import_id == import_id)
    if gp_code:
        q = q.where(EscalationEdit.gp_code == gp_code)
    out = []
    for e in db.scalars(q.order_by(EscalationEdit.edited_at.desc(), EscalationEdit.id.desc()).limit(limit)):
        col = BY_KEY.get(e.field)
        out.append({"gpCode": e.gp_code, "field": e.field, "label": col.label if col else e.field, "old": e.old_value, "new": e.new_value, "by": e.edited_by_name, "at": e.edited_at.isoformat() if e.edited_at else None})
    return out


# ---------------------------------------------------------------- export


def export(store: Store, circle: str | None, district: str | None, block: str | None, search: str | None, admin: bool) -> tuple[bytes, int]:
    """The filtered rows as an Escalation Matrix workbook (sheet 'All', upload headers in row 1)."""
    import xlsxwriter

    _, df = _filtered(store, circle, district, block, search)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("All")
    head = wb.add_format({"bold": True, "font_name": "Arial", "font_size": 10, "bg_color": "#1F5A8C", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter"})
    cell = wb.add_format({"font_name": "Arial", "font_size": 10})
    for j, c in enumerate(COLUMNS):
        ws.write_string(0, j, c.label, head)
        ws.set_column(j, j, 22 if c.kind == "email" else 16)
    for i, (code, r) in enumerate(df.iterrows(), start=1):
        for j, c in enumerate(COLUMNS):
            v = str(code) if c.key == "gp_code" else _str(r.get(c.key))
            if c.kind == "phone":
                v = mask(v, admin)
            if v is not None:
                ws.write_string(i, j, v, cell)
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, max(len(df), 1), len(COLUMNS) - 1)
    wb.close()
    return buf.getvalue(), len(df)


def active_import_id() -> int:
    act = _active()
    if act is None:
        raise NoEscalationData("No Escalation Matrix has been uploaded yet – upload it on Data Operations.")
    return int(act[0]["id"])


__all__ = ["COLUMNS", "SheetError", "apply_changes", "edits", "export", "normalise", "replace_all", "sheet"]
