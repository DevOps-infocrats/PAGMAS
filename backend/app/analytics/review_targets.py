"""Management Review – Page 2 "Target & Achievement" calculations (no rendering here).

Inputs
  * GP-wise data of the active workbook (scope, AMC dates, letter dates)
  * O&M KEY NUMBERS: "Target for Operational GP (<month>)" and "FRT Count (O&M)"
  * the management plan (data/review_plan.json): monthly conversion plans and weekly closure
    targets – these are not in the workbook, so they live in a validated config file instead of code

Formulas (month M = the cutoff month, D = cutoff date, P = last day of the previous month)
  Revised scope                  = existing GPs minus converted-to-NP / closed / deducted
  AMC completed till P           = GPs with AMC date <= P
  M MTD plan                     = management plan for M
  AMC conversion projection – M  = O&M "Target for Operational GP (M)"
  Projected AMC coverage %       = projection / revised scope
  AMC conversion plan – by M     = AMC completed till P + M MTD plan
  Cumulative AMC conversion MTD  = GPs with AMC date <= D
  Target vs achieve gap          = max(0, projection − cumulative AMC MTD)
  Pending GPs after M            = revised scope − projection
  Next months                    = management plan
  Ready for incremental          = GPs with an AMC / incremental letter submitted but not under AMC by D
  Weekly: pending scope          = revised scope − cumulative AMC by D; total FRT = O&M FRT count;
          achieved in a week     = GPs whose AMC date falls inside that week (AMC + incremental)
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import get_settings
from .metrics import r2
from .review_periods import ReportingPeriods
from .review_summary import _targets as om_targets
from .store import Store

log = logging.getLogger("pratap.review")
PLAN_FILE = "review_plan.json"


class _Plan(BaseModel):
    source: str = Field("Management plan", max_length=200)
    monthlyPlan: dict[str, dict[str, int | None]] = {}
    weeklyClosureTargets: dict[str, dict[str, int | None]] = {}
    # Month whose month-end AMC count is shown as the baseline on the circle cards ("YYYY-MM").
    amcBaselineMonth: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @field_validator("monthlyPlan")
    @classmethod
    def _months(cls, v):
        for k, vals in v.items():
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", k):
                raise ValueError(f"month key {k!r} must be YYYY-MM")
            if any(x is not None and x < 0 for x in vals.values()):
                raise ValueError("plan values must be >= 0")
        return v

    @field_validator("weeklyClosureTargets")
    @classmethod
    def _weeks(cls, v):
        for k, vals in v.items():
            if not re.fullmatch(r"W-\d{1,2}", k):
                raise ValueError(f"week key {k!r} must look like W-41")
            if any(x is not None and x < 0 for x in vals.values()):
                raise ValueError("weekly targets must be >= 0")
        return v


_plan_cache: dict[str, tuple[float, _Plan | None, str | None]] = {}
_plan_lock = threading.Lock()


def load_plan() -> tuple[_Plan | None, str | None]:
    """The management plan (re-read whenever the file changes). Returns (plan, problem)."""
    path: Path = get_settings().data_dir / PLAN_FILE
    if not path.exists():
        return None, f"Plan file {PLAN_FILE} not found in the data folder – plan columns are blank."
    mtime = path.stat().st_mtime
    with _plan_lock:
        hit = _plan_cache.get(str(path))
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError("file too large")
        plan, problem = _Plan.model_validate(json.loads(path.read_text(encoding="utf-8"))), None
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        log.warning("Invalid %s: %s", PLAN_FILE, exc)
        plan, problem = None, f"Plan file {PLAN_FILE} is invalid – plan columns are blank."
    with _plan_lock:
        _plan_cache[str(path)] = (mtime, plan, problem)
    return plan, problem


def _month_label(key: str) -> str:
    return dt.date(int(key[:4]), int(key[5:]), 1).strftime("%b-%y")


def _sum(vals: list[float | int | None]) -> tuple[float | None, bool]:
    """Sum of the available values and whether any value was missing."""
    have = [v for v in vals if v is not None]
    return (sum(have) if have else None), len(have) != len(vals)


def targets_page(store: Store, p: ReportingPeriods, circles: list[dict[str, Any]]) -> dict[str, Any]:
    g = store.gps
    plan, problem = load_plan()
    warnings = [problem] if problem else []
    D = p.cutoff
    month = f"{D.year}-{D.month:02d}"
    prev_end = D.replace(day=1) - dt.timedelta(days=1)
    amc = pd.to_datetime(g["amc_date"], errors="coerce")
    letter = pd.to_datetime(g["letter_date"], errors="coerce")
    om = om_targets(store).get(month)
    if not om:
        warnings.append(f"No “Target for Operational GP ({_month_label(month)})” in the O&M sheet – projection columns are blank.")
    rep = store.reported
    frt = {r.state: float(r.value_num) for r in rep.itertuples() if str(r.metric).strip().lower() == "frt count (o&m)" and r.value_num is not None and not pd.isna(r.value_num)} if not rep.empty else {}

    future = sorted(k for k in (plan.monthlyPlan if plan else {}) if k > month)[:3]
    month_plan = (plan.monthlyPlan.get(month) if plan else None) or {}
    if plan and not month_plan:
        warnings.append(f"No plan for {_month_label(month)} in {PLAN_FILE}.")

    rows = []
    for c in circles:
        key = c["key"].upper()
        m = (g["circle"] == c["key"]).to_numpy()
        revised = int(g.loc[m, "revised"].sum())
        till_prev = int((amc[m] <= pd.Timestamp(prev_end)).sum())
        cumulative = int((amc[m] <= pd.Timestamp(D)).sum())
        mtd_plan = month_plan.get(key)
        projection = om["values"].get(key) if om else None
        rows.append(
            {
                "id": c["id"],
                "code": c["code"],
                "name": c["name"],
                "revisedScope": revised,
                "amcTillPrevMonth": till_prev,
                "mtdPlan": mtd_plan,
                "projection": projection,
                "projectedCoveragePct": r2(projection / revised * 100) if projection is not None and revised else None,
                "planByMonth": till_prev + mtd_plan if mtd_plan is not None else None,
                "cumulativeMtd": cumulative,
                "mtdAchieved": cumulative - till_prev,
                "gap": r2(max(0.0, projection - cumulative)) if projection is not None else None,
                "pendingAfterMonth": r2(revised - projection) if projection is not None else None,
                "futurePlans": [(plan.monthlyPlan[f].get(key) if plan else None) for f in future],
                "readyForIncremental": int((m & letter.notna().to_numpy() & ~(amc <= pd.Timestamp(D)).to_numpy()).sum()),
            }
        )

    def tot(field: str) -> float | None:
        return _sum([r[field] for r in rows])[0]

    total = {
        "id": "all",
        "code": "ALL",
        "name": "Overall",
        **{f: tot(f) for f in ("revisedScope", "amcTillPrevMonth", "mtdPlan", "projection", "planByMonth", "cumulativeMtd", "mtdAchieved", "gap", "pendingAfterMonth", "readyForIncremental")},
        "futurePlans": [_sum([r["futurePlans"][i] for r in rows])[0] for i in range(len(future))],
        "futurePlansPartial": [_sum([r["futurePlans"][i] for r in rows])[1] for i in range(len(future))],
    }
    total["projectedCoveragePct"] = r2(total["projection"] / total["revisedScope"] * 100) if total["projection"] is not None and total["revisedScope"] else None

    # Weekly closure targets: weeks of the plan from the reporting week on (dates continue the file's Fri–Thu weeks).
    weeks_known = {w.code: w for w in store.weeks}
    last = store.weeks[-1]
    plan_weeks = sorted((plan.weeklyClosureTargets if plan else {}), key=lambda k: int(k[2:]))
    week_cols = []
    for code in plan_weeks:
        n = int(code[2:])
        if n < p.week.number:
            continue
        w = weeks_known.get(code)
        start = w.start if w else last.start + dt.timedelta(days=7 * (n - last.number))
        end = w.end if w else last.end + dt.timedelta(days=7 * (n - last.number))
        status = "done" if end <= store.data_as_of else ("in progress" if start <= store.data_as_of else "not started")
        week_cols.append({"id": code, "label": f"WK-{n}", "start": start.isoformat(), "end": end.isoformat(), "status": status})
        if len(week_cols) == 4:
            break
    wrows = []
    for c, r in zip(circles, rows):
        key = c["key"].upper()
        m = (g["circle"] == c["key"]).to_numpy()
        cells = []
        for wc in week_cols:
            target = plan.weeklyClosureTargets[wc["id"]].get(key) if plan else None
            achieved = None
            if wc["status"] != "not started":
                inside = (amc[m] >= pd.Timestamp(wc["start"])) & (amc[m] <= pd.Timestamp(min(dt.date.fromisoformat(wc["end"]), store.data_as_of)))
                achieved = int(inside.sum())
            cells.append({"target": target, "achieved": achieved, "achievedPct": r2(achieved / target * 100) if achieved is not None and target else None})
        wrows.append({"id": c["id"], "code": c["code"], "name": c["name"], "pendingScope": r["revisedScope"] - r["cumulativeMtd"], "frt": frt.get(key), "weeks": cells})
    wtotal = {
        "id": "all",
        "code": "ALL",
        "name": "Overall",
        "pendingScope": sum(x["pendingScope"] for x in wrows),
        "frt": _sum([x["frt"] for x in wrows])[0],
        "weeks": [
            {
                "target": _sum([x["weeks"][i]["target"] for x in wrows])[0],
                "achieved": _sum([x["weeks"][i]["achieved"] for x in wrows])[0],
            }
            for i in range(len(week_cols))
        ],
    }
    for cell in wtotal["weeks"]:
        cell["achievedPct"] = r2(cell["achieved"] / cell["target"] * 100) if cell["achieved"] is not None and cell["target"] else None

    if total["mtdAchieved"] == 0 and month_plan:
        latest = amc.max()
        if pd.notna(latest) and latest.date() < D:
            warnings.append(f"Latest AMC date in the file is {latest.date():%d %b %Y}: no conversion is recorded in {_month_label(month)} yet.")

    ml = _month_label(month)
    phasing = f"{_month_label(future[0])[:3]}–{_month_label(future[-1])[:3]}" if future else "Next-month"
    return {
        "title": "Target & Achievement",
        "month": month,
        "monthLabel": ml,
        "cutoff": D.isoformat(),
        "previousMonthEnd": prev_end.isoformat(),
        "daysLeft": (D.replace(day=calendar.monthrange(D.year, D.month)[1]) - D).days,
        "planSource": plan.source if plan else None,
        "roadmap": {
            "title": "GP AMC Conversion & Liquidation Roadmap",
            "subtitle": f"{ml} plan vs actual  |  {phasing} phasing  |  Weekly closure targets",
            "planHeader": f"{ml} AMC Conversion – Plan, Projection & Actual Achievement Status",
            "liquidationHeader": "Pending GPs Closure Liquidation Plan",
            "columns": {
                "amcTillPrevMonth": f"AMC Completed Till {prev_end:%b-%y}",
                "mtdPlan": f"{ml} MTD Plan",
                "projection": f"AMC Conversion Projection – Till {ml}",
                "projectedCoveragePct": f"Projected AMC Coverage (%) – Till {ml}",
                "planByMonth": f"AMC Conversion Plan – By {ml}",
                "cumulativeMtd": "Cumulative AMC Conversion – MTD",
                "gap": f"Target VS Achieve ({ml[:3]}) Gap",
                "pendingAfterMonth": f"Pending GP After {ml}",
                "readyForIncremental": "Ready for incremental (As on date)",
            },
            "futureMonths": [_month_label(f) for f in future],
            "rows": rows,
            "total": total,
        },
        "weekly": {"title": "Pending GP Scope & FRT Allocation – Weekly Closure Targets", "weeks": week_cols, "rows": wrows, "total": wtotal},
        "circleCards": _circle_cards(store, p, circles, plan),
        "definitions": [
            f"{ml} = MTD conversion plan; {', '.join(_month_label(f) for f in future) or 'next months'} = monthly plans – all from the management plan ({PLAN_FILE}); Overall = sum of circles.",
            f"Pending scope GPs = revised scope − GPs under AMC as of {D:%d %b %Y}; Total FRT = O&M “FRT Count (O&M)”.",
            "Weekly target = management plan; achieved = GPs whose AMC date falls inside that Fri–Thu week (AMC + incremental); weeks not started show —.",
            "Circle cards: GPs converted to AMC = GPs whose AMC date falls in the period (AMC + incremental); week vs previous week, month-to-date vs the same days of the previous month, last four weeks, and the AMC count at the end of the baseline month (amcBaselineMonth in the plan file).",
        ],
        "warnings": warnings,
    }


def _circle_cards(store: Store, p: ReportingPeriods, circles: list[dict[str, Any]], plan: _Plan | None) -> dict[str, Any]:
    """Rajasthan / Haryana / Assam – GPs converted to AMC. A conversion = a GP whose AMC date falls in the period
    (AMC + incremental). Shows the AMC count now, week vs previous week, month window vs the same days of the previous
    month, the last four weeks, and the month-end AMC count of the baseline month (plan file amcBaselineMonth)."""
    g = store.gps
    amc = pd.to_datetime(g["amc_date"], errors="coerce")
    D = p.cutoff
    codes = [w.code for w in store.weeks]
    i = codes.index(p.week.code)
    trend_weeks = store.weeks[max(0, i - 3) : i + 1]
    base = plan.amcBaselineMonth if plan and plan.amcBaselineMonth else None
    base_end = None
    if base:
        y, m = int(base[:4]), int(base[5:])
        base_end = dt.date(y, m, calendar.monthrange(y, m)[1])
        if base_end > D:
            base_end = None

    def count(mask, a: dt.date, b: dt.date) -> int:
        return int((mask & (amc >= pd.Timestamp(a)) & (amc <= pd.Timestamp(b))).sum())

    def change(cur: int, prev: int) -> dict[str, Any]:
        d = cur - prev
        return {"current": cur, "previous": prev, "delta": d, "pctChange": round(d / prev * 100, 1) if prev else None, "trend": "flat" if d == 0 else ("better" if d > 0 else "worse")}

    cards = []
    for c in circles:
        mask = g["circle"] == c["key"]
        revised = int(g.loc[mask, "revised"].sum())
        now = int((mask & (amc <= pd.Timestamp(D))).sum())
        baseline = int((mask & (amc <= pd.Timestamp(base_end))).sum()) if base_end else None
        cards.append(
            {
                "id": c["id"],
                "code": c["code"],
                "name": c["name"],
                "amcNow": now,
                "revisedScope": revised,
                "amcPct": r2(now / revised * 100) if revised else None,
                "week": change(count(mask, p.week.start, p.week.end), count(mask, p.compare.start, p.compare.end)),
                "month": change(count(mask, *p.month), count(mask, *p.previous_month)),
                "trend": [{"label": f"WK-{w.number}", "value": count(mask, w.start, w.end)} for w in trend_weeks],
                "baseline": None if baseline is None else {"label": f"{base_end:%b-%y}", "value": baseline, "sinceChange": now - baseline},
            }
        )
    return {
        "asOf": D.isoformat(),
        "weekLabel": f"WK-{p.week.number}",
        "compareLabel": f"WK-{p.compare.number}",
        "monthLabel": f"{p.month[0].day}–{p.month[1].day} {p.month[0]:%b}",
        "previousMonthLabel": f"{p.previous_month[0].day}–{p.previous_month[1].day} {p.previous_month[0]:%b}",
        "baselineLabel": f"{base_end:%b-%y}" if base_end else None,
        "cards": cards,
    }
