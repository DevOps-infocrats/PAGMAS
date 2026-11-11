"""GP-wise weekly task of a ticket: the Area Manager's GPs to convert in a week, the assignment workbook and the
Area Manager's daily progress.

Area Manager      Escalation Matrix (latest upload; the master data's AM Name when there is none) – same mapping as
                  AMC Conversion → Area manager tables (amc_plan._am_names). The ticket goes to the dashboard user whose
                  e-mail is the Area Manager's e-mail in the matrix (no e-mail match = no ticket).
GPs of the task   the AM's GPs of the GP-wise AMC plan with a Planned Date in the selected week (WEEK) – the week's
                  target only. GPs planned before the week and not achieved (no AMC Date before the week starts) are the
                  BACKLOG: counted for information in the preview (never in the target, never in the ticket). Tickets
                  created before this rule may still hold such GPs (kind PENDING) – they are kept unchanged.
Target            1 per GP (one GP to convert) – fixed at creation, never edited
Already achieved  AMC Date filled in the master data at creation (same rule as "GP Achieved" on AMC Conversion)
Daily progress    the Area Manager / FE classifies each GP (CATEGORIES A–E), writes remarks and may attach proof
                  documents per GP; every submission is its own record (ticket_progress / _lines / _files – never
                  overwritten). The GP keeps ONE current category (ticket_task_gps.gp_category): choosing another one
                  replaces it (no duplicate counting), the line keeps the history. Only E "Letter Submission Done" counts
                  as achieved (reported = 1); any other category = not achieved by the user (reported = 0).
                  Cumulative = min(target, already achieved + reported); remaining gap = target − cumulative.
                  (The older Done / Pending form – status / achievedToday – is still accepted by the API.)
GP status         Done = cumulative has reached the target (AMC Date in the master data, or marked Done), else Pending.
                  The status of a history line is the GP's status right after that submission.
Field Engineer    Escalation Matrix "FE Name" + "FE Email ID" of each GP (snapshot on the task GP at creation). An FE
                  recipient of a ticket sees, reports and downloads ONLY the GPs mapped to them (same FE name and the
                  same matrix FE e-mail under that Area Manager); the Area Manager, CBH, SME and admins see every GP of
                  the ticket. A GP without an FE in the matrix is never given to an FE (counted as "FE not mapped").
Nothing here closes a ticket – only an admin does (service.close).
"""

from __future__ import annotations

import datetime as dt
import io
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.amc_plan import NOT_ASSIGNED, VACANT, _am_names
from ..analytics.store import Store
from ..config import get_settings
from ..models import Ticket, TicketProgress, TicketProgressFile, TicketProgressLine, TicketTask, TicketTaskGp, User
from ..security.deps import CurrentUser
from . import files
from .directory import split_emails

MAX_REMARK = 500
MAX_GP_FILES = 5  # proof documents per GP in one daily submission
MAX_PROGRESS_FILES = 50  # proof documents in one daily submission (all GPs)

# GP classification of the daily progress (code -> label); only ACHIEVED_CATEGORY counts as achieved
CATEGORIES: dict[str, str] = {
    "A": "Rectification Done",
    "B": "Ready for Letter Submitted",
    "C": "Revisit Required",
    "D": "Non-Doable – Proposed",
    "E": "Letter Submission Done",
}
ACHIEVED_CATEGORY = "E"


def category_label(code: str | None) -> str | None:
    return CATEGORIES.get(code) if code else None


class TaskError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _d(v: Any) -> dt.date | None:
    return v if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else (v.date() if isinstance(v, dt.datetime) else None)


def _text(v: Any) -> str | None:
    return " ".join(v.split()) if isinstance(v, str) and v.strip() and v.strip() != "0" else None


def _mail(v: Any) -> str | None:
    return v.strip().lower() if isinstance(v, str) and "@" in v else None


def fe_label(v: Any) -> str | None:
    """FE name of the matrix; blank, "0" and "Vacant…" = no FE mapped."""
    from ..analytics.escalation import is_vacant

    t = _text(v)
    return None if t is None or t == "0.0" or is_vacant(t) else t


def _directory(store: Store) -> tuple[pd.DataFrame, str]:
    """Per GP: area manager, AM e-mail, business area, Field Engineer and FE e-mail (Escalation Matrix first, master
    data otherwise – the master data has no FE)."""
    g = store.gps
    names, source, _file, esc = _am_names(store, g.index)

    def col(name: str) -> pd.Series:
        return esc[name] if esc is not None and name in esc.columns else pd.Series(None, index=g.index, dtype=object)

    ba = col("ba")
    ba = ba.where(ba.notna(), g["ba"] if "ba" in g.columns else None)
    return pd.DataFrame(
        {"am": names, "email": col("am_email").map(_mail), "ba": ba, "fe": col("fe_name").map(fe_label), "fe_email": col("fe_email").map(_mail)}, index=g.index
    ), source


def fe_key(name: Any, mail: Any) -> tuple[str, str]:
    from ..analytics.escalation import person_key

    return (person_key(name) or "", (mail or "").strip().lower() if isinstance(mail, str) else "")


@dataclass(frozen=True)
class FeScope:
    """One Field Engineer's part of a task: the GPs whose matrix FE name (case / spaces ignored) and FE e-mail match."""

    name: str
    mail: str | None

    def key(self) -> tuple[str, str]:
        return fe_key(self.name, self.mail)

    def owns(self, g: Any) -> bool:
        return g.fe_name is not None and fe_key(g.fe_name, g.fe_email) == self.key()


def scope_of(db: Session, t: Ticket, user: CurrentUser) -> FeScope | None:
    """The FE part a user may see of this ticket: None = the whole ticket (admins, Area Manager, CBH, SME, others)."""
    if user.is_admin:
        return None
    from ..models import TicketRecipient

    r = db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id).limit(1)).first()
    return FeScope(r.name, r.fe_mail) if r is not None and r.role == "FE" else None


def area_managers(db: Session, store: Store, week_code: str) -> dict[str, Any]:
    """Area Managers a task can be built for, with their GP counts for the week and the matching dashboard user."""
    w = store.week(week_code)
    d, source = _directory(store)
    users = {u.email.lower(): u for u in db.scalars(select(User).where(User.is_active.is_(True)))}
    rows = _task_rows(store, d, None, w.start, w.end)
    out = []
    for am, part in d.groupby("am"):
        if am in (NOT_ASSIGNED, VACANT):
            continue
        emails = sorted({e for v in part["email"] for e in split_emails(v)})
        user = next((users[e] for e in emails if e in users), None)
        mine = rows[rows["am"] == am]
        out.append(
            {
                "name": am,
                "emails": emails,
                "circles": sorted({str(c).title() for c in store.gps.loc[part.index, "circle"]}),
                "businessAreas": sorted({str(b).title() for b in part["ba"] if _text(b)}),
                "gps": len(part),
                "weekGps": int((mine["kind"] == "WEEK").sum()),
                "pendingGps": int((mine["kind"] == "PENDING").sum()),
                "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
            }
        )
    out.sort(key=lambda x: x["name"].lower())
    return {"week": {"id": w.code, "label": f"Week {w.number}", "start": w.start.isoformat(), "end": w.end.isoformat()}, "source": source, "areaManagers": out}


def _task_rows(store: Store, d: pd.DataFrame, am: str | None, start: dt.date, end: dt.date) -> pd.DataFrame:
    """GP rows of the plan that belong to a task of the week (all AMs when am is None)."""
    p = store.amc_plan
    cols = ["am", "kind", "planned", "ready", "amc", "category", "fe", "fe_email"]
    if p.empty:
        return pd.DataFrame(columns=cols)
    amc = store.gps["amc_date"].reindex(p.index)
    none = pd.Series(None, index=p.index, dtype=object)
    frame = pd.DataFrame(
        {
            "am": d["am"].reindex(p.index), "planned": p["planned_date"].map(_d), "ready": p["ach_date"].map(_d), "amc": amc.map(_d), "category": p["category"],
            "fe": d["fe"].reindex(p.index) if "fe" in d.columns else none, "fe_email": d["fe_email"].reindex(p.index) if "fe_email" in d.columns else none,
        },
        index=p.index,
    )
    if am is not None:
        frame = frame[frame["am"] == am]
    week = frame["planned"].map(lambda v: v is not None and start <= v <= end)
    pending = frame.apply(lambda r: r["planned"] is not None and r["planned"] < start and (r["amc"] is None or r["amc"] >= start), axis=1) if len(frame) else week
    frame = frame[week | pending].copy()
    frame["kind"] = ["WEEK" if w_ else "PENDING" for w_ in week[week | pending]]
    return frame[cols]


def _in_circle(store: Store, idx: pd.Index, circle: str | None) -> pd.Index:
    if not circle:
        return idx
    key = " ".join(circle.split()).lower()
    return idx[[" ".join(str(c).split()).lower() == key for c in store.gps.loc[idx, "circle"]]]


def circle_counts(store: Store, am: str, circle: str, week_code: str) -> dict[str, int]:
    """GPs of an Area Manager in one circle, and how many of them are this week's / pending task GPs."""
    w = store.week(week_code)
    d, _ = _directory(store)
    mine = _in_circle(store, d.index[d["am"] == am], circle)
    rows = _task_rows(store, d, am, w.start, w.end)
    rows = rows.loc[rows.index.isin(mine)]
    return {"gps": len(mine), "weekGps": int((rows["kind"] == "WEEK").sum()), "pendingGps": int((rows["kind"] == "PENDING").sum())}


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def fe_slots(store: Store, circle: str | None, week_code: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Field Engineers of a circle, one per (Area Manager, FE name, matrix FE e-mail) – the GPs mapped to each, with
    the week's task GP counts – and per Area Manager the week's task GPs that have no FE in the matrix."""
    w = store.week(week_code)
    d, _ = _directory(store)
    if "fe" not in d.columns:
        return [], {}
    d = d.loc[_in_circle(store, d.index, circle)]
    d = d[~d["am"].isin([NOT_ASSIGNED, VACANT])]
    rows = _task_rows(store, d, None, w.start, w.end)
    rows = rows.loc[rows.index.isin(d.index)]
    slots: dict[tuple[str, str, str], dict[str, Any]] = {}
    for am, fe, mail in zip(d["am"], d["fe"], d["fe_email"]):
        if not isinstance(fe, str):
            continue
        s = slots.setdefault((am, *fe_key(fe, mail)), {"name": fe, "am": am, "mappedEmail": _str(mail), "emails": split_emails(mail), "gps": 0, "weekGps": 0, "pendingGps": 0})
        s["gps"] += 1
    unmapped: dict[str, int] = {}
    for am, fe, mail, kind in zip(rows["am"], rows["fe"], rows["fe_email"], rows["kind"]):
        if not isinstance(fe, str):
            if kind == "WEEK":  # the week's target GPs without an FE
                unmapped[am] = unmapped.get(am, 0) + 1
            continue
        s = slots.get((am, *fe_key(fe, mail)))
        if s is not None:
            s["weekGps" if kind == "WEEK" else "pendingGps"] += 1
    return sorted(slots.values(), key=lambda s: (s["am"].lower(), s["name"].lower(), s["mappedEmail"] or "")), unmapped


def preview(store: Store, am: str, week_code: str, circle: str | None = None, fes: list[FeScope] | None = None, backlog: bool = False) -> list[dict[str, Any]]:
    """The task GPs of an Area Manager: Planned Date in the week (only that AM's GPs; only the selected circle's when
    one is given; only the GPs of these Field Engineers when `fes` is given). backlog=True: the backlog GPs instead
    (planned before the week, not achieved) – information only, never part of a ticket."""
    w = store.week(week_code)
    d, _ = _directory(store)
    if am not in set(d["am"]) or am in (NOT_ASSIGNED, VACANT):
        raise TaskError(422, "Unknown Area Manager")
    rows = _task_rows(store, d, am, w.start, w.end)
    rows = rows[rows["kind"] == ("PENDING" if backlog else "WEEK")]
    rows = rows.loc[rows.index.isin(_in_circle(store, rows.index, circle))]
    if fes is not None:
        keys = {f.key() for f in fes}
        rows = rows[[isinstance(fe, str) and fe_key(fe, mail) in keys for fe, mail in zip(rows["fe"], rows["fe_email"])]]
    g = store.gps.loc[rows.index]
    out = []
    for i, (code, r) in enumerate(rows.sort_values(["kind", "planned"], ascending=[False, True]).iterrows(), start=1):
        gp = g.loc[code]
        base = 1 if r["amc"] is not None and r["amc"] <= store.data_as_of else 0
        out.append(
            {
                "sort": i,
                "gpCode": str(code),
                "gpName": str(gp["name"]).title(),
                "circle": str(gp["circle"]).title(),
                "businessArea": (_text(d.at[code, "ba"]) or "").title() or None,
                "district": str(gp["district"]).title() if _text(gp["district"]) else None,
                "block": str(gp["block_name"]).title() if _text(gp["block_name"]) else None,
                "kind": r["kind"],
                "category": _text(r["category"]),
                "plannedDate": r["planned"].isoformat() if r["planned"] else None,
                "readyDate": r["ready"].isoformat() if r["ready"] else None,
                "amcDate": r["amc"].isoformat() if r["amc"] else None,
                "target": 1,
                "achieved": base,
                "gap": 1 - base,
                "feName": _str(r["fe"]),
                "feEmail": _str(r["fe_email"]),
            }
        )
    return out


def _figures(rows: list[dict[str, Any]], ready_by: dt.date, amc_by: dt.date, backlog: list[dict[str, Any]] | None = None) -> dict[str, dict[str, int]]:
    """Counts of task GPs (preview rows): this week's target (Planned Date in the week – the ticket's GPs) with how many
    are Ready (Ach Date filled by the plan data date) and AMC converted (AMC Date by the data date), and the backlog
    (planned earlier, not achieved – information only, not in the ticket). toReady = GPs − Ready, toConvert = GPs − AMC."""
    r_by, a_by = ready_by.isoformat(), amc_by.isoformat()

    def part(rs: list[dict[str, Any]]) -> dict[str, int]:
        n = len(rs)
        ready = sum(1 for x in rs if x["readyDate"] and x["readyDate"] <= r_by)
        amc = sum(1 for x in rs if x["amcDate"] and x["amcDate"] <= a_by)
        return {"gps": n, "ready": ready, "amc": amc, "toReady": n - ready, "toConvert": n - amc}

    week = [x for x in rows if x["kind"] == "WEEK"]
    return {"week": part(week), "backlog": part(backlog or []), "total": part(week)}


def breakdown(store: Store, am: str, week_code: str, circle: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Target and achievement of an Area Manager's task for the week, and of every FE mapped under them (only the GPs
    mapped to that FE; GPs without an FE in the matrix are a separate "not mapped" line – never given to anyone).
    `page` = the same AM's figures of AMC Conversion → area manager-wise table (Ach / AMC Date IN the week), to check."""
    from ..analytics.amc_plan import amc_plan_area_managers, plan_data_date, windows

    w = store.week(week_code)
    win = windows(store, week_code, month_of_week=True)
    ready_by, amc_by = plan_data_date(store), store.data_as_of
    slots = [s for s in fe_slots(store, circle, week_code)[0] if s["am"] == am] if circle else []
    back = preview(store, am, week_code, circle, backlog=True)
    fes = []
    for s in slots:
        key = fe_key(s["name"], s["mappedEmail"])
        owns = lambda x: bool(x["feName"]) and fe_key(x["feName"], x["feEmail"]) == key  # noqa: E731
        fes.append({"name": s["name"], "email": s["mappedEmail"], "emails": s["emails"], **_figures([x for x in rows if owns(x)], ready_by, amc_by, [x for x in back if owns(x)])})
    unmapped = [x for x in rows if not x["feName"]]
    unmapped_back = [x for x in back if not x["feName"]]
    page = None
    if circle:
        ckey = " ".join(circle.split()).lower()
        cid = next((i for i, c in zip(store.gps["circle_id"], store.gps["circle"]) if " ".join(str(c).split()).lower() == ckey), None)
        if cid is not None:
            t = next((r for r in amc_plan_area_managers(store, week_code, cid)["rows"] if r["name"] == am), None)
            if t is not None:
                page = {"weekTarget": t["weekTarget"], "weekReady": t["weekAchieved"], "weekConverted": t["weekConverted"]}
    return {
        "week": {"id": w.code, "number": w.number, "start": w.start.isoformat(), "end": w.end.isoformat(), "asOf": min(w.end, win.as_of).isoformat()},
        "readyAsOf": ready_by.isoformat(),
        "amcAsOf": amc_by.isoformat(),
        "am": {"name": am, **_figures(rows, ready_by, amc_by, back)},
        "fes": fes,
        "unmapped": _figures(unmapped, ready_by, amc_by, unmapped_back) if unmapped or unmapped_back else None,
        "page": page,
        "definitions": [
            f"Weekly Target = GPs whose Planned Date falls in Week {w.number} ({w.start:%d %b} – {w.end:%d %b %Y}) – only these GPs are in the ticket; Backlog = Planned Date before the week, no AMC Date before it (information only, not in the target).",
            f"Ready = Ach Date filled (up to {ready_by:%d %b %Y}); AMC Converted = AMC Date filled (up to {amc_by:%d %b %Y}).",
            "Remaining to be ready = GPs − Ready; Remaining to convert = GPs − AMC Converted.",
            "Each FE: only the GPs mapped to that FE (FE name + FE e-mail) in the Escalation Matrix. GPs without an FE are shown as not mapped.",
        ],
    }


def am_emails(store: Store, am: str) -> list[str]:
    d, _ = _directory(store)
    return sorted({e for v in d.loc[d["am"] == am, "email"] for e in split_emails(v)})


def _cbh_of(codes: list[str]) -> str | None:
    """CBH name(s) of the GPs in the Escalation Matrix (None without a matrix)."""
    from ..analytics.escalation import _active

    act = _active()
    if act is None or not codes:
        return None
    names = {" ".join(str(n).split()): None for n in act[1].reindex(codes)["cbh_name"] if isinstance(n, str) and n.strip() and n.strip() != "0"}
    return ", ".join(names)[:160] or None


def attach(db: Session, store: Store, t: Ticket, am: str, week_code: str, circle: str | None = None, am_email: str | None = None, fes: list[FeScope] | None = None) -> TicketTask:
    """Create the task rows of a ticket being created (same transaction) and its assignment workbook. `fes`: a ticket
    without the Area Manager – only the GPs of these Field Engineers."""
    rows = preview(store, am, week_code, circle, fes)
    if not rows:
        where = f" in {circle}" if circle else ""
        who = ", ".join(f"FE {f.name}" for f in fes) if fes is not None else am
        raise TaskError(422, f"{who} has no GP{where} with a Planned Date in this week – nothing to assign")
    w = store.week(week_code)
    emails = am_emails(store, am)
    circles = sorted({r["circle"] for r in rows})
    task = TicketTask(
        ticket_id=t.id, am_name=am, am_email=am_email or (emails[0] if emails else None), week_code=w.code, week_start=w.start, week_end=w.end, data_as_of=store.data_as_of,
        source_file=store.file_name, circle=circle or ", ".join(circles)[:80], cbh_name=_cbh_of([r["gpCode"] for r in rows]),
    )
    db.add(task)
    for r in rows:
        db.add(
            TicketTaskGp(
                ticket_id=t.id, sort=r["sort"], gp_code=r["gpCode"], gp_name=r["gpName"], circle=r["circle"], business_area=r["businessArea"], district=r["district"], block=r["block"],
                kind=r["kind"], category=r["category"], planned_date=_iso(r["plannedDate"]), ready_date=_iso(r["readyDate"]), amc_date=_iso(r["amcDate"]), target=1, base_achieved=r["achieved"], reported=0,
                fe_name=r["feName"], fe_email=r["feEmail"],
            )
        )
    db.flush()
    # the original assignment workbook (reference document, never rewritten)
    data = workbook(db, t, task, original=True)
    name = f"{uuid.uuid4().hex}.xlsx"
    folder = get_settings().ticket_dir / str(t.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    task.assignment_file = name
    return task


def _iso(v: str | None) -> dt.date | None:
    return dt.date.fromisoformat(v) if v else None


def _gps(db: Session, ticket_id: int) -> list[TicketTaskGp]:
    return list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == ticket_id).order_by(TicketTaskGp.sort)))


def cumulative(g: TicketTaskGp) -> int:
    return min(g.target, g.base_achieved + g.reported)


def gp_status(g: TicketTaskGp) -> str:
    """DONE once the GP's cumulative achievement reached its target, else PENDING."""
    return "DONE" if cumulative(g) >= g.target else "PENDING"


def line_status(ln: TicketProgressLine, g: TicketTaskGp | None) -> str:
    """The GP's status right after that daily submission."""
    return "DONE" if g is not None and ln.cumulative >= g.target else "PENDING"


def file_json(f: TicketProgressFile, iso) -> dict[str, Any]:
    return {"id": f.id, "fileName": f.file_name, "contentType": f.content_type, "size": f.size, "uploadedAt": iso(f.uploaded_at), "previewable": f.content_type in files.INLINE_TYPES}


def _fe_summary(gps: list[TicketTaskGp], files_of_gp: dict[int, list[Any]], last_update: dict[int, Any], fe_recipients: set[tuple[str, str]], iso) -> list[dict[str, Any]]:
    """FE-wise allocation and progress of a task (GPs without an FE in the matrix = one "not mapped" row, name None)."""
    out: dict[tuple[str, str] | None, dict[str, Any]] = {}
    for g in gps:
        k = fe_key(g.fe_name, g.fe_email) if g.fe_name else None
        r = out.setdefault(
            k,
            {"name": g.fe_name, "email": g.fe_email, "gps": 0, "target": 0, "achieved": 0, "doneGps": 0, "pendingGps": 0, "proofFiles": 0, "lastUpdated": None, "recipient": k in fe_recipients,
             "categories": dict.fromkeys(CATEGORIES, 0), "notClassified": 0, "approvedGps": 0, "returnedGps": 0, "awaitingGps": 0, "addedGps": 0},
        )
        r["gps"] += 1
        if g.review == "RETURNED":
            r["returnedGps"] += 1
        elif g.review is not None:
            r["approvedGps"] += 1
        elif g.gp_category == "A":
            r["awaitingGps"] += 1
        r["addedGps"] += g.kind == "ADDED"
        if g.gp_category in CATEGORIES:
            r["categories"][g.gp_category] += 1
        else:
            r["notClassified"] += 1
        r["target"] += g.target
        r["achieved"] += cumulative(g)
        r["doneGps" if gp_status(g) == "DONE" else "pendingGps"] += 1
        r["proofFiles"] += len(files_of_gp.get(g.id, []))
        when = last_update.get(g.id)
        if when is not None and (r["lastUpdated"] is None or when > r["lastUpdated"]):
            r["lastUpdated"] = when
    rows = sorted(out.values(), key=lambda r: (r["name"] is None, (r["name"] or "").lower(), r["email"] or ""))
    return [r | {"gap": r["target"] - r["achieved"], "lastUpdated": iso(r["lastUpdated"])} for r in rows]


def task_json(db: Session, t: Ticket, scope: FeScope | None = None) -> dict[str, Any] | None:
    """The task as one viewer sees it: `scope` = a Field Engineer – only their GPs, proof files and history lines."""
    task = db.get(TicketTask, t.id)
    if task is None:
        return None
    gps = [g for g in _gps(db, t.id) if scope is None or scope.owns(g)]
    mine = {g.id for g in gps}
    subs = list(db.scalars(select(TicketProgress).where(TicketProgress.ticket_id == t.id).order_by(TicketProgress.submitted_at.desc(), TicketProgress.id.desc())))
    lines = list(db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id.in_([s.id for s in subs])).order_by(TicketProgressLine.id))) if subs else []
    lines = [ln for ln in lines if ln.task_gp_id in mine]
    if scope is not None:
        with_lines = {ln.progress_id for ln in lines}
        subs = [s for s in subs if s.id in with_lines]
    from ..models import TicketRecipient
    from .service import iso  # local import: service imports this module

    by_gp = {g.id: g for g in gps}
    at = {s.id: (s.submitted_at if s.submitted_at is None or s.submitted_at.tzinfo else s.submitted_at.replace(tzinfo=dt.UTC)) for s in subs}  # SQLite: naive UTC
    proofs = [f for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)) if f.task_gp_id in mine]
    files_of_line: dict[int, list[dict[str, Any]]] = {}
    files_of_gp: dict[int, list[dict[str, Any]]] = {}
    for f in proofs:
        j = file_json(f, iso)
        files_of_line.setdefault(f.progress_line_id, []).append(j)
        files_of_gp.setdefault(f.task_gp_id, []).append(j)
    last_update: dict[int, Any] = {}
    last_by: dict[int, str] = {}  # who submitted the GP's latest line (Area Manager / FE)
    who = {s.id: s.submitted_by_name for s in subs}
    by_sub: dict[int, list[dict[str, Any]]] = {}
    for ln in lines:
        g = by_gp.get(ln.task_gp_id)
        when = at.get(ln.progress_id)
        if when is not None and (ln.task_gp_id not in last_update or when >= last_update[ln.task_gp_id]):
            last_update[ln.task_gp_id] = when
            last_by[ln.task_gp_id] = who.get(ln.progress_id, "")
        by_sub.setdefault(ln.progress_id, []).append(
            {
                "taskGpId": ln.task_gp_id, "gpCode": g.gp_code if g else None, "gpName": g.gp_name if g else None, "block": g.block if g else None,
                "achievedToday": ln.achieved_today, "cumulative": ln.cumulative, "gap": ln.gap, "remark": ln.remark,
                "status": line_status(ln, g), "gpCategory": ln.category, "files": files_of_line.get(ln.id, []),
            }
        )

    target = sum(g.target for g in gps)
    achieved = sum(cumulative(g) for g in gps)
    blocks: dict[str, dict[str, Any]] = {}
    for g in gps:
        b = blocks.setdefault(g.block or "—", {"block": g.block or "—", "gps": 0, "target": 0, "achieved": 0})
        b["gps"] += 1
        b["target"] += g.target
        b["achieved"] += cumulative(g)
    fe_recipients = {fe_key(r.name, r.fe_mail) for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE"))}
    from . import review as rv

    trail = rv.trails(db, t, mine, iso)
    from . import nondoable as nd

    nd_refs = nd.case_refs(db, t.id)
    reviewed = [g.review for g in gps]
    return {
        "areaManager": task.am_name,
        "amEmail": task.am_email,
        # a Field Engineer's view: only their GPs; everyone else sees the whole task with the FE-wise split
        "scope": {"fieldEngineer": scope.name, "email": scope.mail} if scope is not None else None,
        "fes": [] if scope is not None else _fe_summary(gps, files_of_gp, last_update, fe_recipients, iso),
        "circle": task.circle,
        "cbhName": task.cbh_name,
        "week": {"id": task.week_code, "start": task.week_start.isoformat(), "end": task.week_end.isoformat()},
        "dataAsOf": task.data_as_of.isoformat(),
        "sourceFile": task.source_file,
        "totals": {
            "gps": len(gps), "target": target, "achieved": achieved, "gap": target - achieved, "pct": round(achieved / target * 100, 1) if target else None,
            "weekGps": sum(g.kind == "WEEK" for g in gps), "pendingGps": sum(g.kind == "PENDING" for g in gps),
            "doneGps": sum(gp_status(g) == "DONE" for g in gps), "openGps": sum(gp_status(g) == "PENDING" for g in gps), "proofFiles": len(proofs),
            "categories": {c: sum(g.gp_category == c for g in gps) for c in CATEGORIES}, "notClassified": sum(g.gp_category is None for g in gps),
            "addedGps": sum(g.kind == "ADDED" for g in gps),
            # review chain: awaiting = Rectification Done by the FE, not yet approved or returned by the Area Manager
            "review": {
                "awaiting": sum(g.review is None and g.gp_category == "A" for g in gps), "returned": reviewed.count("RETURNED"),
                "amApproved": reviewed.count("AM_APPROVED"), "smeForwarded": reviewed.count("SME_FORWARDED"),
                "letterSubmitted": reviewed.count("LETTER_SUBMITTED"), "amcConverted": reviewed.count("AMC_CONVERTED"),
                "ndOpen": sum(1 for g in gps if nd_refs.get(g.id, {}).get("open")), "ndApproved": reviewed.count(nd.ND_REVIEW),
            },
        },
        "blocks": [{**b, "gap": b["target"] - b["achieved"]} for b in sorted(blocks.values(), key=lambda x: x["block"])],
        "gps": [
            {
                "id": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "circle": g.circle, "businessArea": g.business_area, "district": g.district, "block": g.block, "kind": g.kind,
                "category": g.category, "plannedDate": g.planned_date.isoformat() if g.planned_date else None, "readyDate": g.ready_date.isoformat() if g.ready_date else None,
                "amcDate": g.amc_date.isoformat() if g.amc_date else None, "target": g.target, "baseAchieved": g.base_achieved, "reported": g.reported,
                "cumulative": cumulative(g), "gap": g.target - cumulative(g), "remarks": g.remarks,
                "status": gp_status(g), "gpCategory": g.gp_category, "files": files_of_gp.get(g.id, []), "lastUpdated": iso(last_update.get(g.id)), "lastUpdatedBy": last_by.get(g.id), "feName": g.fe_name,
                "review": g.review, "reviewLabel": rv.REVIEW_LABEL.get(g.review) if g.review else None, "reviewAt": iso(g.review_at), "locked": g.review in rv.LOCKED,
                "letterDate": g.letter_date.isoformat() if g.letter_date else None, "amcOn": g.amc_on.isoformat() if g.amc_on else None, "addedBy": g.added_by,
                "trail": trail.get(g.id, []), "ndCase": nd_refs.get(g.id),
            }
            for g in gps
        ],
        "latestSubmission": iso(subs[0].submitted_at) if subs else None,
        "history": [{"id": s.id, "submittedAt": iso(s.submitted_at), "submittedBy": s.submitted_by_name, "note": s.note, "lines": by_sub.get(s.id, [])} for s in subs],
    }


GP_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,39}$")
MAX_NEW_GPS = 50  # GPs added in one daily submission


def _edits(g: TicketTaskGp, it: dict[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    """GP Name / Block changed by the FE / Area Manager: (field, label, old, new)."""
    out: list[tuple[str, str, str | None, str | None]] = []
    if it.get("gpName") is not None:
        v = " ".join(str(it["gpName"]).split())[:160]
        if not v:
            raise TaskError(422, f"GP {g.gp_code}: the GP name cannot be empty")
        if v != g.gp_name:
            out.append(("gp_name", "GP Name", g.gp_name, v))
    if it.get("block") is not None:
        b = " ".join(str(it["block"]).split())[:160] or None
        if b != g.block:
            out.append(("block", "Block", g.block, b))
    return out


def _master_gp(store: Store | None, code: str) -> Any:
    if store is None:
        return None
    idx = store.gps.index
    for key in (code, int(code) if code.isdigit() else None):
        if key is not None and key in idx:
            return store.gps.loc[key]
    return None


def submit_progress(
    db: Session, t: Ticket, user: CurrentUser, items: list[dict[str, Any]], note: str | None, uploads: list[tuple[int, Any]] | None = None,
    new_gps: list[dict[str, Any]] | None = None, store: Store | None = None,
) -> TicketProgress:
    """Save one daily submission. Only the assigned user, only while the ticket is not closed; nothing is overwritten.
    items: taskGpId, category A / C / D (or the older status DONE | PENDING / achievedToday 1 | 0), remark, and the
    GP Name / Block when the FE / Area Manager corrects them. new_gps: GPs added to the ticket (gpCode, gpName, block,
    category, remark) – target 1 each, details from the master data when the code is in it.
    uploads: (taskGpId, Upload) – proof documents of a GP, validated and stored like the submission attachments.
    A GP the Area Manager approved (review.LOCKED) can no longer be changed here; a returned GP goes back to the
    Area Manager with the next change."""
    from . import nondoable as nd
    from . import review as rv
    from .service import is_worker  # local import: service imports this module

    if not is_worker(db, t, user):
        raise TaskError(403, "Only the assigned Area Manager can submit daily progress")
    if t.status == "CLOSED":
        raise TaskError(409, "This ticket is closed – no more daily progress can be submitted")
    task = db.get(TicketTask, t.id)
    if task is None:
        raise TaskError(404, "This ticket has no GP-wise task")
    gps = {g.id: g for g in _gps(db, t.id)}
    scope = scope_of(db, t, user)
    role = "FE" if scope is not None else "AM"

    def own(g: TicketTaskGp) -> None:
        if scope is not None and not scope.owns(g):
            raise TaskError(403, f"GP {g.gp_code} is not one of your GPs in this ticket")
        if g.review in rv.LOCKED:
            raise TaskError(409, f"GP {g.gp_code} is {rv.REVIEW_LABEL[g.review]} – it can no longer be changed in the daily progress")
        try:
            nd.check_progress(db, g, None)
        except nd.NdError as exc:
            raise TaskError(exc.status, exc.message) from None

    uploads = [(int(gid), u) for gid, u in (uploads or []) if getattr(u, "file_name", None)]
    if len(uploads) > MAX_PROGRESS_FILES:
        raise TaskError(422, f"At most {MAX_PROGRESS_FILES} proof documents per daily submission")
    files_of: dict[int, list[Any]] = {}
    for gid, u in uploads:
        g = gps.get(gid)
        if g is None:
            raise TaskError(422, "A proof document belongs to a GP that is not in this ticket")
        own(g)
        files_of.setdefault(gid, []).append(u)
        if len(files_of[gid]) > MAX_GP_FILES:
            raise TaskError(422, f"GP {g.gp_code}: at most {MAX_GP_FILES} proof documents per submission")
        try:
            files.check_meta(u.file_name, u.content_type)  # names and types first, before anything is written
        except files.AttachmentError as exc:
            raise TaskError(exc.status, f"GP {g.gp_code}: {exc}") from None
    seen: set[int] = set()
    fe_only = "choose Rectification Done, Revisit Required or Non-Doable – Proposed (Ready for Letter and Letter Submission come from the AM / SME / COH review)"
    # (GP, change of `reported` (+1 / 0 / -1), remark, new category or None = unchanged, GP Name / Block edits)
    changes: list[tuple[TicketTaskGp, int, str | None, str | None, list[tuple[str, str, str | None, str | None]]]] = []
    for it in items:
        gid = int(it.get("taskGpId", 0))
        g = gps.get(gid)
        if g is None:
            raise TaskError(422, "A GP of the submission does not belong to this ticket")
        own(g)
        if gid in seen:
            raise TaskError(422, f"GP {g.gp_code} appears twice in the submission")
        seen.add(gid)
        edits = _edits(g, it)
        cat = it.get("category")
        remark = (it.get("remark") or "").strip()[:MAX_REMARK] or None
        if cat is not None:
            if cat not in CATEGORIES:
                raise TaskError(422, f"GP {g.gp_code}: choose one of the categories A–E")
            if cat not in rv.FE_CATEGORIES:
                raise TaskError(422, f"GP {g.gp_code}: {fe_only}")
            if it.get("status") is not None or it.get("achievedToday") is not None:
                raise TaskError(422, f"GP {g.gp_code}: send either a category or Done / Pending, not both")
            new_cat = None if cat == g.gp_category else cat
            if new_cat == "D":
                try:
                    nd.check_progress(db, g, new_cat)
                except nd.NdError as exc:
                    raise TaskError(exc.status, exc.message) from None
            delta = ((1 if cat == ACHIEVED_CATEGORY else 0) - g.reported) if new_cat else 0
            if new_cat or gid in files_of or (remark and remark != (g.remarks or None)) or edits:
                changes.append((g, delta, remark, new_cat, edits))
            continue
        status = it.get("status")
        today = int(it.get("achievedToday") or 0)
        if status is not None:
            if status not in ("DONE", "PENDING"):
                raise TaskError(422, f"GP {g.gp_code}: the status must be Done or Pending")
            want = 1 if status == "DONE" else 0
            if it.get("achievedToday") is not None and today != want:
                raise TaskError(422, f"GP {g.gp_code}: the status and today's achievement do not match")
            today = want
        if today not in (0, 1):
            raise TaskError(422, f"GP {g.gp_code}: today's achievement must be 0 or 1")
        if today and cumulative(g) >= g.target:
            raise TaskError(422, f"GP {g.gp_code} has already reached its target – it cannot be counted again")
        if status == "PENDING" and cumulative(g) >= g.target:
            raise TaskError(422, f"GP {g.gp_code} has already reached its target – it cannot be marked Pending")
        if today or status == "PENDING" or gid in files_of or (remark and remark != (g.remarks or None)) or edits:
            changes.append((g, today, remark, None, edits))
    for gid in files_of:  # a proof for a GP without a status / remark change still makes a line of the day
        if gid not in seen:
            changes.append((gps[gid], 0, None, None, []))

    added: list[dict[str, Any]] = []
    if len(new_gps or []) > MAX_NEW_GPS:
        raise TaskError(422, f"At most {MAX_NEW_GPS} new GPs per daily submission")
    for n in new_gps or []:
        code = str(n.get("gpCode") or "").strip()
        if not GP_CODE_RE.match(code):
            raise TaskError(422, f"'{code[:40]}' is not a valid GP code (letters and digits, up to 40 characters)")
        if any(x.gp_code == code for x in gps.values()) or any(a["code"] == code for a in added):
            raise TaskError(422, f"GP {code} is already in this ticket")
        other = db.scalar(
            select(Ticket.code)
            .join(TicketTask, TicketTask.ticket_id == Ticket.id)
            .join(TicketTaskGp, TicketTaskGp.ticket_id == Ticket.id)
            .where(TicketTaskGp.gp_code == code, TicketTask.week_code == task.week_code, Ticket.deleted_at.is_(None), Ticket.id != t.id)
            .limit(1)
        )
        if other:
            raise TaskError(422, f"GP {code} is already in ticket {other} of this week – it cannot be added twice")
        cat = n.get("category")
        if cat is not None and cat not in rv.FE_CATEGORIES:
            raise TaskError(422, f"New GP {code}: {fe_only}")
        m = _master_gp(store, code)
        name = " ".join(str(n.get("gpName") or "").split())[:160]
        if m is None and not name:
            raise TaskError(422, f"GP {code} is not in the master data – enter its GP name")
        added.append({"code": code, "name": name, "block": " ".join(str(n.get("block") or "").split())[:160] or None, "cat": cat, "remark": (n.get("remark") or "").strip()[:MAX_REMARK] or None, "m": m})
    if not changes and not added:
        raise TaskError(422, "Nothing to submit – choose a category for a GP, write a new remark, correct its details, add a GP or attach a proof document")

    from .service import _event, _move, _notify, _reviewers, now  # local import: service imports this module

    if t.status == "OPEN":
        frm = _move(db, t, ("OPEN",), "IN_PROGRESS", started_at=now())
        _event(db, t, user, "STARTED", frm, "IN_PROGRESS", "Started with the first daily progress")
    at = now()
    sub = TicketProgress(ticket_id=t.id, submitted_by_id=user.id, submitted_by_name=user.name, submitted_at=at, note=(note or "").strip()[:2000] or None)
    db.add(sub)
    db.flush()
    done = 0
    stored: list[str] = []
    budget = get_settings().ticket_upload_max_mb * 1024 * 1024
    try:
        sort = max((x.sort for x in gps.values()), default=0)
        for a in added:
            sort += 1
            m = a["m"]
            amc = _d(m["amc_date"]) if m is not None and "amc_date" in m.index else None
            g = TicketTaskGp(
                ticket_id=t.id, sort=sort, gp_code=a["code"], gp_name=a["name"] or str(m["name"]).title(), circle=(str(m["circle"]).title() if m is not None else (task.circle or "—"))[:80],
                business_area=None, district=str(m["district"]).title() if m is not None and _text(m["district"]) else None,
                block=a["block"] or (str(m["block_name"]).title() if m is not None and _text(m["block_name"]) else None), kind="ADDED", category=None, planned_date=None, ready_date=None,
                amc_date=amc, target=1, base_achieved=1 if amc is not None and store is not None and amc <= store.data_as_of else 0, reported=0,
                fe_name=scope.name if scope is not None else None, fe_email=scope.mail if scope is not None else None, added_by=user.name,
            )
            db.add(g)
            db.flush()
            gps[g.id] = g
            rv.record(db, t, g, user, role, "ADD", f"Added by {user.name}" + ("" if m is not None else " – not in the master data"), at)
            changes.append((g, 0, a["remark"], a["cat"], []))
        returned = 0
        cases: list[tuple[TicketTaskGp, Any]] = []
        for g, delta, remark, new_cat, edits in changes:
            before = cumulative(g)
            g.reported += delta
            if new_cat:
                g.gp_category = new_cat
            if remark:
                g.remarks = remark
            if edits:
                for field, _label, _old, new in edits:
                    setattr(g, field, new)
                rv.record(db, t, g, user, role, "EDIT", "; ".join(f"{label}: {old or '—'} → {new or '—'}" for _f, label, old, new in edits), at)
            if g.review == "RETURNED":  # corrected by the FE: back to the Area Manager
                g.review, g.review_at = None, at
                returned += 1
            today = 1 if cumulative(g) > before else 0  # 1 = became achieved with this line
            done += today
            ln = TicketProgressLine(progress_id=sub.id, task_gp_id=g.id, achieved_today=today, cumulative=cumulative(g), gap=g.target - cumulative(g), remark=remark, category=new_cat)
            db.add(ln)
            case = nd.on_progress(db, t, g, user, new_cat, remark, at)
            if case is not None:
                cases.append((g, case))
            if g.id in files_of:
                db.flush()
                for u in files_of[g.id]:
                    try:
                        f = files.save(t.id, u.file_name, u.content_type, u.stream, budget)
                    except files.AttachmentError as exc:
                        raise TaskError(exc.status, f"GP {g.gp_code}: {exc}") from None
                    stored.append(f.stored_name)
                    budget -= f.size
                    db.add(TicketProgressFile(ticket_id=t.id, progress_line_id=ln.id, task_gp_id=g.id, file_name=f.file_name, stored_name=f.stored_name, content_type=f.content_type, size=f.size, sha256=f.sha256, uploaded_at=now()))
        total = sum(x.target for x in gps.values())
        achieved = sum(cumulative(x) for x in gps.values())
        proof = f" · {len(stored)} proof document{'s' if len(stored) != 1 else ''}" if stored else ""
        cats = [CATEGORIES[c[3]] for c in changes if c[3]]
        what = f"{len(cats)} GP{'s' if len(cats) != 1 else ''} classified ({', '.join(f'{n} {lbl}' for lbl, n in sorted({x: cats.count(x) for x in cats}.items()))})" if cats else f"{done} GP{'s' if done != 1 else ''} marked Done today"
        n_edit = sum(1 for c in changes if c[4])
        extra = (f" · {len(added)} GP{'s' if len(added) != 1 else ''} added" if added else "") + (f" · {n_edit} GP{'s' if n_edit != 1 else ''} corrected" if n_edit else "")
        extra += f" · {returned} returned GP{'s' if returned != 1 else ''} sent back to the Area Manager" if returned else ""
        extra += f" · Non-Doable proposed: {', '.join(f'{c.ref} (GP {g.gp_code})' for g, c in cases)}" if cases else ""
        _event(db, t, user, "PROGRESS", t.status, t.status, f"Daily progress: {what}, {len(changes)} GP line{'s' if len(changes) != 1 else ''}{proof}{extra} · {achieved}/{total} achieved")
        _notify(db, _reviewers(db, t), t, "PROGRESS", f"{t.code}: daily progress", f"{user.name} submitted daily progress – {achieved} of {total} GPs achieved.")
        if scope is not None:  # an FE reported: their Area Manager follows it too (dashboard + e-mail)
            from ..models import TicketRecipient

            ams = set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "AM", TicketRecipient.user_id.is_not(None))))
            own_gps = [g for g in gps.values() if scope.owns(g)]
            _notify(
                db, ams - {user.id}, t, "PROGRESS", f"{t.code}: FE daily progress",
                f"FE {scope.name} submitted daily progress – {len(changes)} GP line{'s' if len(changes) != 1 else ''}{extra} · {sum(cumulative(g) for g in own_gps)} of their {len(own_gps)} GPs achieved.",
            )
            if cases:
                _notify(
                    db, ams - {user.id}, t, "NONDOABLE", f"{t.code}: Non-Doable proposed by FE {scope.name}",
                    "; ".join(f"{c.ref} – GP {g.gp_code} ({g.gp_name})" for g, c in cases) + ". The FE submits the E1 physical verification and the E2 justification for your review.",
                )
        t.updated_at = now()
        db.commit()
    except BaseException:
        db.rollback()
        files.remove(t.id, stored)
        raise
    return sub


def workbook(db: Session, t: Ticket, task: TicketTask, original: bool, scope: FeScope | None = None) -> bytes:
    """GP-wise workbook: the original assignment (achieved as at creation) or the latest progress report (cumulative,
    latest remarks, proof documents, plus the daily history). Identification and target columns are protected; Remarks
    are editable. `scope` = one Field Engineer's workbook: only the GPs mapped to them (and only their history lines)."""
    import xlsxwriter

    gps = [g for g in _gps(db, t.id) if scope is None or scope.owns(g)]
    proof_of_gp: dict[int, list[str]] = {}
    if not original:
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)):
            proof_of_gp.setdefault(f.task_gp_id, []).append(f.file_name)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet("GP Task")
    title = wb.add_format({"bold": True, "font_size": 14})
    note = wb.add_format({"italic": True, "font_color": "#555555"})
    head = wb.add_format({"bold": True, "bg_color": "#0E7490", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter", "locked": True})
    cell = wb.add_format({"border": 1, "locked": True})
    num = wb.add_format({"border": 1, "num_format": "#,##0", "locked": True})
    edit = wb.add_format({"border": 1, "locked": False, "bg_color": "#FFF8E1", "text_wrap": True})
    total_f = wb.add_format({"bold": True, "border": 1, "bg_color": "#F1F5F9", "locked": True})
    kind = "Assignment (original)" if original else f"Progress report – {dt.datetime.now():%d %b %Y %H:%M}"
    target_total = sum(g.target for g in gps)
    gap_total = sum(g.target - (g.base_achieved if original else cumulative(g)) for g in gps)
    who = f"FE {scope.name} ({task.am_name})" if scope is not None else task.am_name
    ws.write_string(0, 0, f"{t.code} · {who} · Week {task.week_code[2:]} ({task.week_start:%d %b} – {task.week_end:%d %b %Y}) · {kind}", title)
    fe_part = f" · Field Engineer: {scope.name}{f' ({scope.mail})' if scope.mail else ''}" if scope is not None else ""
    ws.write_string(1, 0, f"Circle: {task.circle or '—'} · CBH: {task.cbh_name or '—'} · Area Manager: {task.am_name}{fe_part} · {len(gps)} GPs · total weekly target {target_total} · remaining gap {gap_total}", note)
    ws.write_string(
        2, 0,
        f"Weekly target = 1 GP each (Planned Date in the week). Existing achievement = AMC Date in the master data at assignment (data as of {task.data_as_of:%d %b %Y}, {task.source_file}). "
        + ("Daily Achievement and Remarks can be filled in; " if original else "Daily Achievement = GPs reported in the daily progress of the ticket; ")
        + "the dashboard is the system of record – submit daily progress in the ticket.",
        note,
    )
    headers = [
        ("S.No.", 6), ("Circle", 12), ("Area Manager", 18), ("FE Name", 18), ("Business Area", 16), ("District", 16), ("Block Name", 18), ("GP Code", 12), ("GP Name", 24),
        ("Weekly Target", 10), ("Existing Achievement", 12), ("Remaining Gap", 11), ("Daily Achievement", 12), ("Remarks", 40), ("Proof Document", 36),
        ("Type", 9), ("Planned Date", 12), ("Ach Date (Ready)", 13), ("AMC Date", 12),
    ]
    hr = 4
    for c, (h, wdt) in enumerate(headers):
        ws.set_column(c, c, wdt)
        ws.write_string(hr, c, h, head)
    for i, g in enumerate(gps, start=1):
        r = hr + i
        ach = g.base_achieved if original else cumulative(g)
        vals = [i, g.circle, task.am_name, g.fe_name or "FE not mapped", g.business_area or "", g.district or "", g.block or "", g.gp_code, g.gp_name]
        for c, v in enumerate(vals):
            (ws.write_number(r, c, v, num) if isinstance(v, int) else ws.write_string(r, c, str(v), cell))
        ws.write_number(r, 9, g.target, num)
        ws.write_number(r, 10, g.base_achieved, num)
        ws.write_number(r, 11, g.target - ach, num)
        if original:
            ws.write_blank(r, 12, None, edit)
        else:
            ws.write_number(r, 12, g.reported, num)
        ws.write_string(r, 13, "" if original else (g.remarks or ""), edit)
        ws.write_string(r, 14, "" if original else (", ".join(proof_of_gp.get(g.id, [])) or "Proof Not Uploaded"), cell)
        ws.write_string(r, 15, {"WEEK": "This week", "ADDED": "Added by FE"}.get(g.kind, "Pending"), cell)
        for c, v in ((16, g.planned_date), (17, g.ready_date), (18, g.amc_date)):
            ws.write_string(r, c, f"{v:%d-%m-%Y}" if v else "", cell)
    tr = hr + len(gps) + 1
    ws.write_string(tr, 8, "Total", total_f)
    for c, v in ((9, target_total), (10, sum(g.base_achieved for g in gps)), (11, gap_total)):
        ws.write_number(tr, c, v, total_f)
    if not original:
        ws.write_number(tr, 12, sum(g.reported for g in gps), total_f)
    ws.freeze_panes(hr + 1, 0)
    ws.protect("", {"autofilter": True, "sort": True, "format_columns": True})
    if not original:
        hs = wb.add_worksheet("Daily History")
        for c, (h, wdt) in enumerate([("Submitted", 18), ("Submitted By", 20), ("GP Code", 12), ("GP Name", 24), ("Block", 18), ("Achieved Today", 12), ("Cumulative", 11), ("Remaining Gap", 12), ("Remark", 40), ("Status", 26), ("Proof", 40)]):
            hs.set_column(c, c, wdt)
            hs.write_string(0, c, h, head)
        subs = list(db.scalars(select(TicketProgress).where(TicketProgress.ticket_id == t.id).order_by(TicketProgress.submitted_at, TicketProgress.id)))
        by_gp = {g.id: g for g in gps}
        proof: dict[int, list[str]] = {}
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)):
            proof.setdefault(f.progress_line_id, []).append(f.file_name)
        r = 1
        for s in subs:
            for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id == s.id).order_by(TicketProgressLine.id)):
                g = by_gp.get(ln.task_gp_id)
                if g is None:  # another FE's GP (FE workbook)
                    continue
                at = s.submitted_at if s.submitted_at.tzinfo else s.submitted_at.replace(tzinfo=dt.UTC)
                hs.write_string(r, 0, at.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%d %b %Y %H:%M IST"), cell)
                for c, v in enumerate([s.submitted_by_name, g.gp_code if g else "", g.gp_name if g else "", (g.block or "") if g else ""], start=1):
                    hs.write_string(r, c, v, cell)
                hs.write_number(r, 5, ln.achieved_today, num)
                hs.write_number(r, 6, ln.cumulative, num)
                hs.write_number(r, 7, ln.gap, num)
                hs.write_string(r, 8, ln.remark or "", cell)
                hs.write_string(r, 9, category_label(ln.category) or ("Done" if line_status(ln, g) == "DONE" else "Pending"), cell)
                hs.write_string(r, 10, ", ".join(proof.get(ln.id, [])) or "Proof Not Uploaded", cell)
                r += 1
        hs.freeze_panes(1, 0)
    wb.close()
    return buf.getvalue()


def assignment_path(t: Ticket, task: TicketTask):
    if not task.assignment_file:
        return None
    try:
        return files.path_of(t.id, task.assignment_file)
    except files.AttachmentError:
        return None


def file_name(task: TicketTask, original: bool, scope: FeScope | None = None) -> str:
    def safe(v: str, fallback: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in v).strip("_")[:40] or fallback

    who = f"FE_{safe(scope.name, 'FieldEngineer')}" if scope is not None else safe(task.am_name, "AreaManager")
    return f"{who}_Weekly_GP_Assignment_Week_{task.week_code[2:]}{'' if original else '_Progress'}.xlsx"


def progress_count(db: Session, ticket_id: int) -> int:
    return db.scalar(select(func.count()).where(TicketProgress.ticket_id == ticket_id)) or 0
