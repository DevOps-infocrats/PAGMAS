"""Validation report of a staged upload – shown BEFORE the admin confirms the import (nothing is written here).

Layered checks, strict order, the first failing layer stops the report (fail fast):
  1 file       type (.xlsx / .xlsb only), not empty, genuine workbook package, zip-bomb guard   (workbook.check_file_signature)
  2 kind       the content is the file the admin chose (master data workbook / Escalation Matrix)
  3 duplicate  the exact same file (SHA-256) was imported successfully before
  4 template   master data (template.py): both sheets, every REQUIRED column by name (any order, case / spaces /
               punctuation ignored), at least one day / week / month column. Optional columns may be absent, other
               columns are ignored ("not used"), day / week / month columns are never a reason to reject.
  4 structure  what the importer itself needs to read the sheet (parser / escalation)
  5 rows       business rules per row: rejected rows (critical), warnings, info – each with its Excel row number
A report with layers 1–4 passed can be imported (rows rejected in layer 5 are skipped and listed). The report also says
which required / optional columns were found, which periods the file has, its gaps, and which earlier weeks / months
stay on the dashboard from earlier uploads.
The master data's own O&M key numbers are cross-checked against what the rows contain (warning only, never blocks).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .workbook import WorkbookError, check_file_signature

KINDS = {"master": "Master Data workbook", "escalation": "Escalation Matrix"}
MAX_ISSUES = 1000  # issues listed in the report (all are counted; the full list is stored with the import)
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _fail(stage: str, message: str, base: dict[str, Any]) -> dict[str, Any]:
    return base | {"canImport": False, "stage": stage, "error": message}


def build(path: Path, kind: str, base: dict[str, Any], already: str | None) -> dict[str, Any]:
    """`base` = token / file facts, `already` = message when the same file was imported before (or None)."""
    from .escalation import detect_kind

    try:
        check_file_signature(path)
    except WorkbookError as exc:
        return _fail("file", str(exc), base)
    try:
        found = detect_kind(path)
    except WorkbookError as exc:
        return _fail("file", str(exc), base)
    if found is None:
        return _fail("kind", f"Not recognised as a {KINDS[kind]}: the master data workbook needs the sheet 'GP Wise Data', the Escalation Matrix the columns GP Code, FRT Code and FE Name.", base)
    if found != kind:
        return _fail("kind", f"You selected '{KINDS[kind]}', but this file is the {KINDS[found]}. Choose '{KINDS[found]}' in the file type list, or pick the right file.", base)
    if already:
        return _fail("duplicate", already, base)
    tpl_warnings: list[dict[str, Any]] = []
    if kind == "master":
        from . import template

        try:
            chk = template.validate_master(path)
        except WorkbookError as exc:
            return _fail("file", str(exc), base)
        columns = {"sheets": [sh.json() for sh in chk.sheets], "templateHint": template.TEMPLATE_HINT}
        if not chk.ok:
            return _fail("template", chk.message(), base) | {
                "templateErrors": [p.json() for p in chk.errors],
                "templateErrorCount": chk.error_count,
                "columnCheck": columns,
            }
        # duplicate optional columns: the importer reads the first one – listed so the admin knows
        tpl_warnings = [{"row": p.row, "severity": "warning", "code": "TEMPLATE", "column": p.column, "gpCode": None, "message": p.message, "sheet": p.sheet} for p in chk.warnings]
    try:
        body = _master(path) if kind == "master" else _escalation(path)
    except WorkbookError as exc:
        return _fail("structure", str(exc), base)
    if kind == "master":
        body["columnCheck"] = columns
    if tpl_warnings:
        body["issues"] = (body.get("issues") or []) + tpl_warnings[: max(0, MAX_ISSUES - len(body.get("issues") or []))]
        body["counts"]["warning"] += len(tpl_warnings)
        body["issueSummary"] = (body.get("issueSummary") or []) + [{"code": "TEMPLATE", "severity": "warning", "count": len(tpl_warnings)}]
    return base | {"canImport": True, "stage": "ok", "error": None} | body


def _issues(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    by = Counter((i["code"], i["severity"]) for i in items)
    sev = Counter(i["severity"] for i in items)
    ordered = sorted(items, key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), i.get("row") or 0))
    summary = [{"code": c, "severity": s, "count": n} for (c, s), n in sorted(by.items(), key=lambda x: (SEVERITY_ORDER.get(x[0][1], 3), -x[1]))]
    return ordered[:MAX_ISSUES], summary, sev


def _master(path: Path) -> dict[str, Any]:
    from .column_map import GP_COLUMNS, load_column_map
    from .parser import parse_workbook

    p = parse_workbook(path)
    items = [{"row": i.row_number, "severity": i.severity, "code": i.code, "column": i.column, "gpCode": i.gp_code, "message": i.message, "sheet": i.sheet} for i in p.issues]
    listed, summary, sev = _issues(items)
    circles = Counter(g["circle"] for g in p.gps)
    weeks = sorted(p.weeks, key=lambda w: w["start_date"])
    facts = [
        {"label": "GPs", "value": f"{len(p.gps):,}" + (f" ({', '.join(f'{c.title()} {n:,}' for c, n in sorted(circles.items()))})" if circles else "")},
        {"label": "Data as of", "value": p.data_as_of.strftime("%d %b %Y") if p.data_as_of else "—"},
        {"label": "Weeks", "value": f"{weeks[0]['code']} – {weeks[-1]['code']} ({weeks[0]['start_date']:%d %b} – {weeks[-1]['end_date']:%d %b %Y})" if weeks else "—"},
        {"label": "AMC plan GPs", "value": f"{len(p.amc_plan):,} (Planned Date {sum(1 for r in p.amc_plan if r['planned_date']):,} · Ach Date {sum(1 for r in p.amc_plan if r['ach_date']):,})"},
        {"label": "Sheets read", "value": ", ".join(s for s in ("GP Wise Data", "Master Block", "O&M") if s in p.sheet_names or s == "GP Wise Data")},
    ]
    labels = {k: v[0] for k, v in GP_COLUMNS.items()}
    return {
        "counts": {"rows": p.rows_total, "accepted": p.rows_total - p.rows_rejected, "rejected": p.rows_rejected, "critical": sev["critical"], "warning": sev["warning"], "info": sev["info"]},
        "facts": facts,
        "columns": {"missingOptional": [labels.get(k, k) for k in p.missing_optional], "unknown": list(p.unknown_columns), "mapProblems": load_column_map().problems},
        "crossCheck": cross_check(p),
        "periods": periods_report(p),
        "issues": listed,
        "issueSummary": summary,
    }


def periods_report(p: Any) -> dict[str, Any]:
    """Which days / weeks / months the file has, its gaps, and which earlier weeks / months stay on the dashboard from
    earlier uploads (period_history) – the file may start later than the previous one (only the current week / month)."""
    from .packs import wide_frames

    frames = wide_frames(p.availability)
    days = sorted(frames["D"].columns)
    weeks = sorted(p.weeks, key=lambda w: w["start_date"])
    months = sorted(frames["M"].columns)
    out: dict[str, Any] = {
        "days": {"count": len(days), "first": days[0] if days else None, "last": days[-1] if days else None},
        "weeks": [w["code"] for w in weeks],
        "weekRange": f"{weeks[0]['start_date']:%d %b} – {weeks[-1]['end_date']:%d %b %Y}" if weeks else None,
        "months": list(months),
        "amcMonths": sorted(frames["MA"].columns),
        "blockPeriodCount": len({(k, per) for _c, k, per, _v in getattr(p, "block_availability", [])}),
        "gaps": [i.message for i in p.issues if i.code in ("PERIOD_GAP", "WEEK_LABEL", "PERIOD_DUPLICATE", "DATE_COLUMN_IGNORED", "NO_WEEK_COLUMNS")][:20],
        "fromHistory": {"weeks": [], "months": []},
    }
    try:
        from ..db import SessionLocal
        from .history import earlier_periods

        with SessionLocal() as db:
            first = weeks[0]["start_date"] if weeks else None
            out["fromHistory"]["weeks"] = [per for per, *_ in earlier_periods(db, "W", {w["code"] for w in weeks}, before=first, upto=p.data_as_of)]
            out["fromHistory"]["months"] = [per for per, *_ in earlier_periods(db, "M", set(months), upto=p.data_as_of)]
    except Exception:  # noqa: BLE001 - a fact, never a reason to fail the report
        pass
    return out


# O&M key number -> how it is counted from the GP rows (only metrics with an unambiguous row rule)
def _revised(g: dict[str, Any]) -> bool:
    return not g.get("np_status")


CROSS = {
    "revised existing gps": ("Revised Existing GPs", lambda gs: sum(1 for g in gs if _revised(g))),
    "hoto done - gps": ("HOTO Done - GPs", lambda gs: sum(1 for g in gs if _revised(g) and g.get("hoto_date"))),
    "total blocks": ("Total Blocks", lambda gs: len({g["block_code"] for g in gs if g.get("block_code") not in (None, "UNKNOWN")})),
}


def cross_check(p: Any) -> list[dict[str, Any]]:
    """The file's O&M key numbers vs the same figure counted from its GP rows (warning only)."""
    out = []
    by_state: dict[str, list[dict[str, Any]]] = {}
    for g in p.gps:
        by_state.setdefault(g["circle"], []).append(g)
    for r in p.reported:
        key = " ".join(str(r["metric"]).split()).lower()
        if key not in CROSS or r["state"] not in by_state or r["value_num"] is None:
            continue
        label, count = CROSS[key]
        computed = count(by_state[r["state"]])
        reported = float(r["value_num"])
        out.append({"state": r["state"].title(), "metric": label, "reported": reported, "computed": computed, "difference": computed - reported, "match": abs(computed - reported) < 0.5})
    return out


def _escalation(path: Path) -> dict[str, Any]:
    from .escalation import parse_escalation

    p = parse_escalation(path)
    listed, summary, sev = _issues([i | {"sheet": p.sheet} for i in p.issues])
    circles = Counter(r["circle"] for r in p.rows)
    ams = {(r["circle"], " ".join(str(r["am_name"]).split()).lower()) for r in p.rows if r.get("am_name")}
    fes = {(r["circle"], " ".join(str(r["fe_name"]).split()).lower()) for r in p.rows if r.get("fe_name")}
    no_am = Counter(r["circle"] for r in p.rows if not r.get("am_name"))
    facts = [
        {"label": "GPs", "value": f"{len(p.rows):,} ({', '.join(f'{c.title()} {n:,}' for c, n in sorted(circles.items()))})"},
        {"label": "Area Managers", "value": f"{len(ams):,}"},
        {"label": "Field Engineers", "value": f"{len(fes):,}"},
        {"label": "GPs without AM Name", "value": f"{sum(no_am.values()):,}" + (f" ({', '.join(f'{c.title()} {n:,}' for c, n in sorted(no_am.items()))})" if no_am else "")},
        {"label": "GPs without FE e-mail", "value": f"{sum(1 for r in p.rows if not r.get('fe_email')):,}"},
        {"label": "Sheet read", "value": p.sheet},
    ]
    try:  # GP codes not in the active master data (would show without a location)
        from sqlalchemy import select

        from ..db import SessionLocal
        from ..models import Dataset, Gp
        from .workbook import code_key

        with SessionLocal() as db:
            master = {code_key(c) for c in db.scalars(select(Gp.gp_code).join(Dataset, Dataset.id == Gp.dataset_id).where(Dataset.is_active.is_(True)))}
        if master:
            outside = sum(1 for r in p.rows if code_key(r["gp_code"]) not in master)
            facts.append({"label": "GP codes not in the active master data", "value": f"{outside:,}"})
    except Exception:  # noqa: BLE001 - a fact, never a reason to fail the report
        pass
    from .column_map import ESCALATION_COLUMNS

    return {
        "counts": {"rows": p.rows_total, "accepted": len(p.rows), "rejected": p.rows_rejected, "critical": sev["critical"], "warning": sev["warning"], "info": sev["info"]},
        "facts": facts,
        "columns": {"missingOptional": [ESCALATION_COLUMNS[k][0] for k in p.missing if k in ESCALATION_COLUMNS], "unknown": [], "mapProblems": []},
        "crossCheck": [],
        "issues": listed,
        "issueSummary": summary,
    }
