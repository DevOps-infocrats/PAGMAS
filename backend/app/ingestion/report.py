"""Upload report: what changed compared with the previous upload.

Built inside the import transaction from the freshly parsed workbook and the previous upload's rows that are
still in the database, then stored as JSON (table import_reports). It only describes the data – nothing in the
import depends on it, and a failure while building it is recorded in the report instead of failing the import.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Dataset, DatasetWeek, Gp, ImportReport, ValidationIssue
from .parser import ParsedWorkbook

SAMPLE = 15  # example rows per change list


def _iso(d: Any) -> str | None:
    return d.isoformat() if isinstance(d, (dt.date, dt.datetime)) else None


def _previous(db: Session, ds: Dataset) -> Dataset | None:
    """The newest earlier successful upload whose rows are still stored."""
    for prev in db.scalars(select(Dataset).where(Dataset.id < ds.id, Dataset.status.in_(["SUCCESS", "PARTIAL"])).order_by(Dataset.id.desc())):
        if db.scalar(select(func.count()).select_from(Gp).where(Gp.dataset_id == prev.id)):
            return prev
    return None


def _diff_lists(cur: list[str], prev: list[str] | None) -> dict[str, Any]:
    if prev is None:
        return {"compared": False, "added": [], "removed": []}
    p, c = set(prev), set(cur)
    return {"compared": True, "added": [x for x in cur if x not in p], "removed": [x for x in prev if x not in c]}


def build_report(db: Session, ds: Dataset, parsed: ParsedWorkbook) -> dict[str, Any]:
    prev = _previous(db, ds)
    prev_report = None
    if prev is not None:
        row = db.get(ImportReport, prev.id)
        if row is not None:
            try:
                prev_report = json.loads(row.report)
            except ValueError:
                prev_report = None
    prev_layout = (prev_report or {}).get("layout") or {}

    # ---- GPs: new vs previous upload
    cur = {g["gp_code"]: g for g in parsed.gps}
    old: dict[str, dict[str, Any]] = {}
    if prev is not None:
        for r in db.execute(select(Gp.gp_code, Gp.name, Gp.circle, Gp.hoto_date, Gp.amc_date).where(Gp.dataset_id == prev.id)):
            old[r.gp_code] = {"name": r.name, "circle": r.circle, "hoto_date": r.hoto_date, "amc_date": r.amc_date}

    def gp(code: str, g: dict[str, Any]) -> dict[str, Any]:
        return {"code": code, "name": str(g.get("name") or code).title(), "circle": str(g.get("circle") or "").title()}

    added = [c for c in cur if prev is not None and c not in old]
    removed = [c for c in old if c not in cur]
    hoto_new, amc_new, amc_changed, hoto_changed = [], [], [], []
    for code, g in cur.items():
        o = old.get(code)
        if o is None:
            continue
        if g.get("hoto_date") and not o["hoto_date"]:
            hoto_new.append(code)
        elif g.get("hoto_date") and o["hoto_date"] and g["hoto_date"] != o["hoto_date"]:
            hoto_changed.append({**gp(code, g), "from": _iso(o["hoto_date"]), "to": _iso(g["hoto_date"])})
        if g.get("amc_date") and not o["amc_date"]:
            amc_new.append(code)
        elif g.get("amc_date") and o["amc_date"] and g["amc_date"] != o["amc_date"]:
            amc_changed.append({**gp(code, g), "from": _iso(o["amc_date"]), "to": _iso(g["amc_date"])})
        elif not g.get("amc_date") and o["amc_date"]:
            amc_changed.append({**gp(code, g), "from": _iso(o["amc_date"]), "to": None})

    circles = sorted({g["circle"] for g in cur.values()} | {o["circle"] for o in old.values()})
    by_circle = [
        {"circle": c.title(), "current": sum(1 for g in cur.values() if g["circle"] == c), "previous": sum(1 for o in old.values() if o["circle"] == c) if prev else None}
        for c in circles
    ]

    # ---- weeks, issues
    weeks = [w["code"] for w in sorted(parsed.weeks, key=lambda w: w["number"])]
    prev_weeks = [w.code for w in db.scalars(select(DatasetWeek).where(DatasetWeek.dataset_id == prev.id).order_by(DatasetWeek.number))] if prev else None
    sev = {"critical": 0, "warning": 0, "info": 0}
    for i in parsed.issues:
        sev[i.severity] = sev.get(i.severity, 0) + 1
    prev_sev = None
    if prev is not None:
        prev_sev = {"critical": 0, "warning": 0, "info": 0}
        for s, n in db.execute(select(ValidationIssue.severity, func.count()).where(ValidationIssue.dataset_id == prev.id).group_by(ValidationIssue.severity)):
            prev_sev[s] = n

    # ---- attention points (plain-language)
    notes: list[str] = []
    if prev is not None and parsed.data_as_of and prev.data_as_of and parsed.data_as_of < prev.data_as_of:
        notes.append(f"Data as of {parsed.data_as_of:%d %b %Y} is OLDER than the previous upload ({prev.data_as_of:%d %b %Y}) – was an old file uploaded by mistake?")
    if prev is not None and parsed.data_as_of and prev.data_as_of and parsed.data_as_of == prev.data_as_of:
        notes.append("Data as of is the same as in the previous upload – no new day of data.")
    if prev is not None and old and len(removed) > 0.05 * len(old):
        notes.append(f"{len(removed):,} GPs of the previous upload are missing in this file (more than 5%) – check the GP Wise Data sheet.")
    cols = _diff_lists(parsed.gp_headers, prev_layout.get("gpHeaders"))
    if cols["removed"]:
        notes.append(f"{len(cols['removed'])} column(s) of the previous file are missing: {', '.join(cols['removed'][:8])}")
    if parsed.missing_optional:
        notes.append(f"Optional columns not found (shown as NA on the dashboard): {', '.join(parsed.missing_optional)}")

    return {
        "version": 1,
        "fileName": ds.file_name,
        "previous": {"id": str(prev.id), "fileName": prev.file_name, "dataAsOf": _iso(prev.data_as_of)} if prev else None,
        "dataAsOf": {
            "current": _iso(parsed.data_as_of),
            "previous": _iso(prev.data_as_of) if prev else None,
            "newDays": (parsed.data_as_of - prev.data_as_of).days if prev and parsed.data_as_of and prev.data_as_of else None,
        },
        "sheets": {"found": parsed.sheet_names, **_diff_lists(parsed.sheet_names, prev_layout.get("sheets"))},
        "columns": {**cols, "notUsed": parsed.unknown_columns, "missingOptional": parsed.missing_optional},
        "gps": {
            "current": len(cur),
            "previous": len(old) if prev else None,
            "added": len(added),
            "removed": len(removed),
            "addedSample": [gp(c, cur[c]) for c in added[:SAMPLE]],
            "removedSample": [{"code": c, "name": str(old[c]["name"] or c).title(), "circle": str(old[c]["circle"]).title()} for c in removed[:SAMPLE]],
            "hotoNew": len(hoto_new),
            "amcNew": len(amc_new),
            "hotoDateChanged": len(hoto_changed),
            "hotoDateChangedSample": hoto_changed[:SAMPLE],
            "amcDateChanged": len(amc_changed),
            "amcDateChangedSample": amc_changed[:SAMPLE],
            "byCircle": by_circle,
        },
        "weeks": {"current": weeks, **_diff_lists(weeks, prev_weeks)},
        "issues": {"current": sev, "previous": prev_sev},
        "notes": notes,
        # kept so the next upload can compare its layout with this one
        "layout": {"sheets": parsed.sheet_names, "gpHeaders": parsed.gp_headers},
    }


def save_report(db: Session, ds: Dataset, parsed: ParsedWorkbook) -> None:
    """Build and store the report of this upload (replacing one from an earlier attempt). Never raises."""
    try:
        with db.begin_nested():  # savepoint: a failing query here cannot abort the import transaction
            report = build_report(db, ds, parsed)
    except Exception as exc:  # the report only describes the upload; it must never stop the import
        report = {"version": 1, "fileName": ds.file_name, "error": f"Report could not be built ({type(exc).__name__})"}
    existing = db.get(ImportReport, ds.id)
    payload = json.dumps(report, default=str)
    if existing:
        existing.report = payload
        existing.previous_id = int(report["previous"]["id"]) if report.get("previous") else None
    else:
        db.add(ImportReport(dataset_id=ds.id, previous_id=int(report["previous"]["id"]) if report.get("previous") else None, report=payload))
