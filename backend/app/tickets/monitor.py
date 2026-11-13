"""Admin monitoring of the GP-wise tasks: Done / Pending GPs across all task tickets, with remarks, proof documents and
the date-wise history – read from the ticket records only (ticket_task_gps, ticket_progress*, ticket_progress_files).

One GP = one GP code, counted once however many tickets it is in (a GP not converted comes back as "pending" in the
next week's ticket of its Area Manager):
  Done     the GP reached its target in ANY of its tickets (AMC Date in the master data at assignment, or marked Done
           by the Area Manager) – the ticket where that happened is shown, with its completion date and proof
  Pending  not done in any of its tickets – its latest ticket (newest week) is shown
Remarks / Last updated / proof documents are those of all its tickets (latest remark, latest submission, every file).
Filters on ticket fields (circle, Area Manager, block, week, ticket) choose WHICH GPs are counted; the status of a GP is
always its overall status. KPI = the same filtered GPs counted by status, so cards and tables always agree.
Field Engineer = the FE of the GP in the Escalation Matrix when its task was created (filter, column and the FE-wise
Done / Pending split of the filtered GPs; "FE not mapped" = no FE in the matrix).

Category (A–E, task.CATEGORIES) = the GP's CURRENT classification: the category chosen most recently in any of its
tickets (each GP once – a changed category moves the GP from the old KPI to the new one, never counted twice). The
ticket shown for a classified GP is the one where that category was chosen; Area Manager / FE / Block come from that
ticket's GP row (Escalation Matrix + master data at assignment). "Not classified" = no category chosen yet.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Ticket, TicketProgress, TicketProgressFile, TicketProgressLine, TicketTask, TicketTaskGp
from .service import iso
from .task import CATEGORIES, cumulative, file_json, gp_status

SORTS = ("circle", "areaManager", "fe", "gpCode", "gpName", "block", "target", "achieved", "gap", "date", "ticket", "week", "category")
NOT_MAPPED = "FE not mapped"


def _zone():
    try:
        return ZoneInfo(get_settings().report_timezone)
    except Exception:  # noqa: BLE001 - unknown zone: UTC
        return dt.UTC


def _local_date(v: dt.datetime | dt.date | None) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).astimezone(_zone()).date()
    return v


def _when(v: dt.datetime | dt.date | None) -> dt.datetime | None:
    """Comparable instant (dates = start of the local day)."""
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.UTC)
    return dt.datetime.combine(v, dt.time(), _zone())


@dataclass
class Row:
    """One GP of one task ticket."""

    g: TicketTaskGp
    code: str
    ticket_status: str
    am: str
    week: str
    week_start: dt.date
    week_end: dt.date
    lines: list[dict[str, Any]] = field(default_factory=list)  # oldest first
    files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return gp_status(self.g)

    @property
    def completed(self) -> tuple[dt.datetime | dt.date | None, str | None]:
        """When / how the GP reached its target in this ticket."""
        if self.status != "DONE":
            return None, None
        done = [ln for ln in self.lines if ln["achievedToday"]]
        if done:
            return done[-1]["at"], f"Marked Done by {done[-1]['by']}" if done[-1].get("by") else "Marked Done in the daily progress"
        return self.g.amc_date, "AMC Date in the master data (already achieved at assignment)"

    @property
    def category_at(self) -> dt.datetime | None:
        """When the GP's current category was chosen in this ticket (latest line that set it)."""
        if not self.g.gp_category:
            return None
        return next((ln["at"] for ln in reversed(self.lines) if ln.get("category") == self.g.gp_category), None) or dt.datetime.min.replace(tzinfo=dt.UTC)


def _rows(db: Session) -> list[Row]:
    q = (
        select(TicketTaskGp, Ticket.code, Ticket.status, TicketTask.am_name, TicketTask.week_code, TicketTask.week_start, TicketTask.week_end)
        .join(Ticket, Ticket.id == TicketTaskGp.ticket_id)
        .join(TicketTask, TicketTask.ticket_id == TicketTaskGp.ticket_id)
        .where(Ticket.deleted_at.is_(None))  # a deleted ticket's GPs are not monitored
    )
    rows = {g.id: Row(g, code or f"TKT-{g.ticket_id:06d}", st, am, wk, ws, we) for g, code, st, am, wk, ws, we in db.execute(q)}
    if not rows:
        return []
    files_of_line: dict[int, list[dict[str, Any]]] = {}
    for f in db.scalars(select(TicketProgressFile).order_by(TicketProgressFile.id)):
        j = file_json(f, iso) | {"ticket": rows[f.task_gp_id].code if f.task_gp_id in rows else None}
        files_of_line.setdefault(f.progress_line_id, []).append(j)
        if f.task_gp_id in rows:
            rows[f.task_gp_id].files.append(j)
    q2 = (
        select(TicketProgressLine, TicketProgress.submitted_at, TicketProgress.submitted_by_name, TicketProgress.note)
        .join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id)
        .order_by(TicketProgress.submitted_at, TicketProgressLine.id)
    )
    for ln, at, by, note in db.execute(q2):
        r = rows.get(ln.task_gp_id)
        if r is None:
            continue
        r.lines.append(
            {
                "at": _when(at), "by": by, "note": note, "achievedToday": ln.achieved_today, "cumulative": ln.cumulative, "gap": ln.gap, "remark": ln.remark,
                "status": "DONE" if ln.cumulative >= r.g.target else "PENDING", "category": ln.category, "files": files_of_line.get(ln.id, []),
            }
        )
    return list(rows.values())


def _key(v: str | None) -> str:
    return " ".join(str(v or "").split()).lower()


def _gp_record(rows: list[Row], every: list[Row] | None = None, basis: str | None = None) -> dict[str, Any]:
    """One GP from its ticket rows (see module docstring). `every` = all its rows (the current category is the latest
    one chosen in any of them); basis "category" = the row shown and the date filtered on are those of the category."""
    classified = [r for r in (every or rows) if r.g.gp_category]
    cat_row = max(classified, key=lambda r: (r.category_at, r.g.ticket_id)) if classified else None
    done = [r for r in rows if r.status == "DONE"]
    if basis == "category" and cat_row is not None:
        rep = cat_row
    elif done:
        rep = max(done, key=lambda r: (_when(r.completed[0]) or dt.datetime.min.replace(tzinfo=dt.UTC), r.g.ticket_id))
    else:
        rep = max(rows, key=lambda r: (r.week_start, r.g.ticket_id))
    lines = sorted((ln | {"ticket": r.code} for r in rows for ln in r.lines), key=lambda x: _when(x["at"]))
    remark = next((ln["remark"] for ln in reversed(lines) if ln["remark"]), None) or rep.g.remarks
    last = lines[-1]["at"] if lines else None
    files = sorted((f for r in rows for f in r.files), key=lambda f: f["uploadedAt"] or "")
    when, how = rep.completed
    if basis == "category" and rep.status != "DONE":
        when, how = (None, None)
    g = rep.g
    cat_at = cat_row.category_at if cat_row is not None else None
    cat_at = cat_at if cat_at and cat_at.year > 1 else None
    return {
        "gpCode": g.gp_code,
        "gpName": g.gp_name,
        "circle": g.circle,
        "district": g.district,
        "block": g.block,
        "businessArea": g.business_area,
        "areaManager": rep.am,
        "fieldEngineer": g.fe_name,
        "ticketId": g.ticket_id,
        "ticket": rep.code,
        "ticketStatus": rep.ticket_status,
        "week": rep.week,
        "weekStart": rep.week_start.isoformat(),
        "weekEnd": rep.week_end.isoformat(),
        "kind": g.kind,
        "plannedDate": g.planned_date.isoformat() if g.planned_date else None,
        "status": "DONE" if done else "PENDING",
        "target": g.target,
        "achieved": cumulative(g),
        "gap": g.target - cumulative(g),
        "completedAt": iso(when) if isinstance(when, dt.datetime) else (when.isoformat() if when else None),
        "completedBy": how,
        "lastUpdated": iso(last),
        "remarks": remark,
        "files": files,
        "tickets": sorted({r.code for r in rows}),
        "gpCategory": cat_row.g.gp_category if cat_row is not None else None,
        "categoryAt": iso(cat_at),
        "categoryTicket": cat_row.code if cat_row is not None else None,
        "_date": (_local_date(cat_at) if cat_at else _local_date(last)) if basis == "category" else (_local_date(when) if done else _local_date(last)),
    }


def _fe_is(g: TicketTaskGp, fe: str) -> bool:
    from ..analytics.escalation import person_key

    return (g.fe_name is None) if fe == NOT_MAPPED else (g.fe_name is not None and person_key(g.fe_name) == person_key(fe))


def _matches(r: Row, f: dict[str, Any]) -> bool:
    g = r.g
    return (
        (not f.get("circle") or _key(g.circle) == _key(f["circle"]))
        and (not f.get("areaManager") or r.am == f["areaManager"])
        and (not f.get("fe") or _fe_is(g, f["fe"]))
        and (not f.get("block") or _key(g.block) == _key(f["block"]))
        and (not f.get("week") or r.week == f["week"])
        and (not f.get("ticket") or r.code.lower() == f["ticket"].strip().lower())
    )


def _records(db: Session, f: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Row]]:
    """GPs matching the ticket-field filters (each GP code once), then the GP / text / date filters."""
    all_rows = _rows(db)
    groups: dict[str, list[Row]] = {}
    for r in all_rows:
        groups.setdefault(r.g.gp_code, []).append(r)
    recs = []
    for rs in groups.values():
        inside = [r for r in rs if _matches(r, f)]
        if not inside:
            continue
        # the status of a GP is its overall status: done in a ticket outside the filters = done
        extra = [] if any(r.status == "DONE" for r in inside) else [r for r in rs if r.status == "DONE" and r not in inside]
        if f.get("basis") == "category":  # the row where the GP's current category was chosen is shown, even outside the filters
            extra += [r for r in rs if r.g.gp_category and r not in inside and r not in extra]
        recs.append(_gp_record(inside + extra, rs, f.get("basis")))
    gp_code, gp_name, text = (f.get("gpCode") or "").strip().lower(), (f.get("gpName") or "").strip().lower(), (f.get("search") or "").strip().lower()
    d_from, d_to = f.get("dateFrom"), f.get("dateTo")
    out = []
    for x in recs:
        if gp_code and gp_code not in x["gpCode"].lower():
            continue
        if gp_name and gp_name not in x["gpName"].lower():
            continue
        if text and not any(text in str(x[k] or "").lower() for k in ("gpCode", "gpName", "block", "areaManager", "fieldEngineer", "ticket", "circle", "remarks")):
            continue
        if d_from and (x["_date"] is None or x["_date"] < d_from):
            continue
        if d_to and (x["_date"] is None or x["_date"] > d_to):
            continue
        out.append(x)
    return out, all_rows


def _options(all_rows: list[Row], f: dict[str, Any]) -> dict[str, list[str]]:
    """Filter choices; blocks and Area Managers follow the chosen circle (and blocks the chosen AM)."""
    in_circle = [r for r in all_rows if not f.get("circle") or _key(r.g.circle) == _key(f["circle"])]
    in_am = [r for r in in_circle if not f.get("areaManager") or r.am == f["areaManager"]]
    weeks = sorted({r.week for r in all_rows}, key=lambda w: min(x.week_start for x in all_rows if x.week == w), reverse=True)
    fes = sorted({r.g.fe_name for r in in_am if r.g.fe_name}, key=str.lower)
    return {
        "circles": sorted({r.g.circle for r in all_rows if r.g.circle}),
        "areaManagers": sorted({r.am for r in in_circle if r.am}),
        "fieldEngineers": fes + ([NOT_MAPPED] if any(r.g.fe_name is None for r in in_am) else []),
        "blocks": sorted({r.g.block for r in in_am if r.g.block}),
        "weeks": weeks,
        "tickets": sorted({r.code for r in in_am}, reverse=True),
    }


def _by_fe(recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FE-wise Done / Pending of the filtered GPs (each GP once, under the FE of its shown ticket row)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for x in recs:
        k = (x["areaManager"] or "", x["fieldEngineer"] or NOT_MAPPED)
        r = out.setdefault(
            k, {"areaManager": k[0], "fieldEngineer": k[1], "mapped": x["fieldEngineer"] is not None, "total": 0, "done": 0, "pending": 0, "withoutProof": 0, "categories": dict.fromkeys(CATEGORIES, 0), "notClassified": 0}
        )
        r["total"] += 1
        r["done" if x["status"] == "DONE" else "pending"] += 1
        if x["gpCategory"]:
            r["categories"][x["gpCategory"]] += 1
        else:
            r["notClassified"] += 1
        r["withoutProof"] += 0 if x["files"] else 1
    rows = sorted(out.values(), key=lambda r: (r["areaManager"].lower(), not r["mapped"], r["fieldEngineer"].lower()))
    return [r | {"donePct": round(r["done"] / r["total"] * 100, 1) if r["total"] else None} for r in rows]


def summary(db: Session, f: dict[str, Any], basis: str | None = None) -> dict[str, Any]:
    recs, all_rows = _records(db, f | ({"basis": basis} if basis else {}))
    return _counts(recs) | {"options": _options(all_rows, f), "byFe": _by_fe(recs)}


def _counts(recs: list[dict[str, Any]]) -> dict[str, Any]:
    done = sum(1 for x in recs if x["status"] == "DONE")
    pending = len(recs) - done
    total = len(recs)
    return {
        "total": total,
        "done": done,
        "pending": pending,
        "donePct": round(done / total * 100, 1) if total else None,
        "pendingPct": round(pending / total * 100, 1) if total else None,
        "withoutProof": {"done": sum(1 for x in recs if x["status"] == "DONE" and not x["files"]), "pending": sum(1 for x in recs if x["status"] == "PENDING" and not x["files"])},
        # current classification (each GP once): the five category KPIs + GPs without a category yet
        "categories": {c: sum(1 for x in recs if x["gpCategory"] == c) for c in CATEGORIES},
        "categoryWithDocument": {c: sum(1 for x in recs if x["gpCategory"] == c and x["files"]) for c in CATEGORIES},
        "notClassified": sum(1 for x in recs if not x["gpCategory"]),
    }


def listing(db: Session, f: dict[str, Any], status: str | None, sort: str, desc: bool, page: int, page_size: int, category: str | None = None) -> dict[str, Any]:
    """GPs of one status (Done / Pending) or – with `category` – of one current category (A–E)."""
    if category:
        f = f | {"basis": "category"}
    recs, all_rows = _records(db, f)
    counts = _counts(recs)
    items = [x for x in recs if (x["gpCategory"] == category if category else x["status"] == status)]
    keys = {
        "category": lambda x: x["gpCategory"] or "~",
        "circle": lambda x: _key(x["circle"]), "areaManager": lambda x: _key(x["areaManager"]), "fe": lambda x: _key(x["fieldEngineer"] or "~"), "gpCode": lambda x: x["gpCode"], "gpName": lambda x: _key(x["gpName"]),
        "block": lambda x: _key(x["block"]), "target": lambda x: x["target"], "achieved": lambda x: x["achieved"], "gap": lambda x: x["gap"],
        "date": lambda x: x["_date"] or dt.date.min, "ticket": lambda x: x["ticket"], "week": lambda x: x["weekStart"],
    }
    items.sort(key=lambda x: (keys[sort](x), x["gpCode"]), reverse=desc)
    total = len(items)
    part = items[(page - 1) * page_size : page * page_size]
    return {
        "status": status,
        "category": category,
        "items": [{k: v for k, v in x.items() if k != "_date"} for x in part],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "kpis": counts,
        "options": _options(all_rows, f),
    }


def gp_detail(db: Session, gp_code: str) -> dict[str, Any] | None:
    """One GP: its overall record, every ticket it was in and the date-wise history of all of them."""
    rows = [r for r in _rows(db) if r.g.gp_code == gp_code]
    if not rows:
        return None
    rec = _gp_record(rows, rows)
    history = []
    for r in rows:
        if r.g.base_achieved:
            history.append(
                {"at": r.g.amc_date.isoformat() if r.g.amc_date else None, "ticket": r.code, "week": r.week, "by": "Master data", "achievedToday": 0, "status": "DONE",
                 "remark": "Already achieved at assignment (AMC Date in the master data)", "files": [], "source": "master"}
            )
        for ln in r.lines:
            history.append(
                {"at": iso(ln["at"]), "ticket": r.code, "week": r.week, "by": ln["by"], "achievedToday": ln["achievedToday"], "status": ln["status"], "gpCategory": ln.get("category"), "remark": ln["remark"], "files": ln["files"], "source": "progress"}
            )
    history.sort(key=lambda h: _when(dt.datetime.fromisoformat(h["at"]) if h["at"] and "T" in h["at"] else (dt.date.fromisoformat(h["at"]) if h["at"] else None)) or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True)
    rec.pop("_date", None)
    return rec | {
        "ticketRows": [
            {"ticketId": r.g.ticket_id, "ticket": r.code, "ticketStatus": r.ticket_status, "week": r.week, "weekStart": r.week_start.isoformat(), "weekEnd": r.week_end.isoformat(),
             "areaManager": r.am, "fieldEngineer": r.g.fe_name, "kind": r.g.kind, "target": r.g.target, "achieved": cumulative(r.g), "gap": r.g.target - cumulative(r.g), "status": r.status,
             "gpCategory": r.g.gp_category}
            for r in sorted(rows, key=lambda r: (r.week_start, r.g.ticket_id), reverse=True)
        ],
        "history": history,
    }
