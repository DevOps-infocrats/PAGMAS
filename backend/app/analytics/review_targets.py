"""Management Review – Page 2 "Target & Achievement" calculations (no rendering here).

Inputs
  * GP-wise data of the active workbook (scope, AMC dates, letter dates)
  * O&M KEY NUMBERS: "Target for Operational GP (<month>)" and "FRT Count (O&M)"
  * the management plan (data/review_plan.json): monthly conversion plans and weekly closure
    targets – these are not in the workbook, so they live in a validated config file instead of code
  * the GP-wise AMC plan of the master data file (GP sheet "Planned Date"): wherever the file has a plan
    for a state and month, that month's plan is counted from the file and replaces the review_plan.json value
    (see effective_plan) – so a new file with a changed / new month plan updates the review by itself

Formulas (month M = the cutoff month, D = cutoff date, P = last day of the previous month)
  Revised scope                  = existing GPs minus converted-to-NP / closed / deducted
  AMC completed till P           = GPs with AMC date <= P
  M MTD plan                     = plan for M (effective_plan: file Planned Dates, else review_plan.json)
  AMC conversion projection – M  = O&M "Target for Operational GP (M)"
  Projected AMC coverage %       = projection / revised scope
  AMC conversion plan – by M     = AMC completed till P + M MTD plan
  Cumulative AMC conversion MTD  = GPs with AMC date <= D
  M MTD achieved (plan)          = GPs whose Ach Date (GP-wise plan block) falls between the 1st of M and the plan
                                   cutoff – the same count as AMC Conversion → "Achieved this month (MTD)"
  Target vs achieve gap          = max(0, projection − cumulative AMC MTD)
  Pending GPs after M            = revised scope − projection
  Next months                    = plan for those months (effective_plan, same rule)
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


def _file_month_plan(store: Store) -> dict[str, dict[str, int]]:
    """GP-wise plan of the active master data file: {"YYYY-MM": {STATE: GPs with a Planned Date in that month}}.
    Same counting as AMC Conversion → Month target (analytics/amc_plan.py); states without any GP are left out."""
    p = store.amc_plan
    if p.empty:
        return {}
    circle_of = store.gps["circle"].reindex(p.index)
    out: dict[str, dict[str, int]] = {}
    for d, c in zip(p["planned_date"], circle_of):
        if isinstance(d, dt.date) and isinstance(c, str):
            month = out.setdefault(f"{d.year}-{d.month:02d}", {})
            month[c.upper()] = month.get(c.upper(), 0) + 1
    return out


def effective_plan(store: Store) -> tuple[_Plan | None, str | None, dict[str, str]]:
    """The monthly plan the review uses (web page, PPT, executive summary, AMC conversion).

    Per state and month: the master data file's GP-wise plan (count of Planned Dates in that month) when the file
    has one for that state and month; otherwise the value in review_plan.json. Months only in the file are added.
    Weekly closure targets and the baseline month always come from review_plan.json.

    Returns (plan, problem, sources) – sources = {"YYYY-MM": "file" | "plan file" | "file + plan file"}.
    """
    plan, problem = load_plan()
    from_file = _file_month_plan(store)
    base_monthly = plan.monthlyPlan if plan else {}
    sources: dict[str, str] = {}
    monthly: dict[str, dict[str, int | None]] = {}
    for month in sorted(set(base_monthly) | set(from_file)):
        configured = dict(base_monthly.get(month, {}))
        counted = from_file.get(month, {})
        merged = {**configured, **counted}  # the file wins for every state it has a plan for
        monthly[month] = merged
        if counted and set(merged) - set(counted):
            sources[month] = "file + plan file"
        else:
            sources[month] = "file" if counted else "plan file"
    if plan is None and not from_file:
        return None, problem, sources
    base = plan if plan is not None else _Plan()
    # With a valid file plan, a missing / broken review_plan.json only blanks the months the file does not cover.
    return base.model_copy(update={"monthlyPlan": monthly}), problem, sources


def _month_label(key: str) -> str:
    return dt.date(int(key[:4]), int(key[5:]), 1).strftime("%b-%y")


def _sum(vals: list[float | int | None]) -> tuple[float | None, bool]:
    """Sum of the available values and whether any value was missing."""
    have = [v for v in vals if v is not None]
    return (sum(have) if have else None), len(have) != len(vals)


def targets_page(store: Store, p: ReportingPeriods, circles: list[dict[str, Any]]) -> dict[str, Any]:
    g = store.gps
    plan, problem, plan_sources = effective_plan(store)
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

    # Achieved against the plan = Ach Date of the GP-wise plan block, counted like the AMC Conversion page:
    # up to the reporting week's end capped at the plan data date (amc_plan.windows), inside month M.
    from .amc_plan import windows  # local import: amc_plan is independent of the review modules

    ach_cutoff = windows(store, p.week.code).as_of
    month_start = D.replace(day=1)
    month_end = D.replace(day=calendar.monthrange(D.year, D.month)[1])
    plan_rows = store.amc_plan
    ach_state = g["circle"].reindex(plan_rows.index).to_numpy() if not plan_rows.empty else None

    def plan_achieved(state_key: str, a: dt.date, b: dt.date) -> int | None:
        """GPs of the state whose Ach Date falls in [a, b]; None when the file has no GP-wise plan."""
        if ach_state is None:
            return None
        hit = [isinstance(v, dt.date) and a <= v <= b for v in plan_rows["ach_date"]]
        return int(sum(1 for h, c in zip(hit, ach_state) if h and c == state_key))

    future = sorted(k for k in (plan.monthlyPlan if plan else {}) if k > month)[:3]
    month_plan = (plan.monthlyPlan.get(month) if plan else None) or {}
    if plan and not month_plan:
        warnings.append(f"No plan for {_month_label(month)} in the master data file or {PLAN_FILE}.")

    rows = []
    for c in circles:
        key = c["key"].upper()
        m = (g["circle"] == c["key"]).to_numpy()
        revised = int(g.loc[m, "revised"].sum())
        till_prev = int((amc[m] <= pd.Timestamp(prev_end)).sum())
        cumulative = int((amc[m] <= pd.Timestamp(D)).sum())
        mtd_plan = month_plan.get(key)
        projection = om["values"].get(key) if om else None
        achieved_plan = plan_achieved(c["key"], month_start, min(ach_cutoff, month_end))
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
                "planAchieved": achieved_plan,
                "planAchievedPct": r2(achieved_plan / mtd_plan * 100) if achieved_plan is not None and mtd_plan else None,
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
        **{f: tot(f) for f in ("revisedScope", "amcTillPrevMonth", "mtdPlan", "projection", "planByMonth", "cumulativeMtd", "mtdAchieved", "planAchieved", "gap", "pendingAfterMonth", "readyForIncremental")},
        "futurePlans": [_sum([r["futurePlans"][i] for r in rows])[0] for i in range(len(future))],
        "futurePlansPartial": [_sum([r["futurePlans"][i] for r in rows])[1] for i in range(len(future))],
    }
    total["planAchievedPct"] = r2(total["planAchieved"] / total["mtdPlan"] * 100) if total["planAchieved"] is not None and total["mtdPlan"] else None
    total["projectedCoveragePct"] = r2(total["projection"] / total["revisedScope"] * 100) if total["projection"] is not None and total["revisedScope"] else None

    # Weekly closure targets – computed from the GP-wise plan block of the file, like AMC Conversion → Weekly:
    #   new target = GPs whose Planned Date falls in the Fri–Thu week, achieved = Ach Date in the week (up to the
    #   cutoff); old target = the manually set target of review_plan.json, shown next to it for comparison.
    # Weeks shown: the first WEEKS_FROM_START weeks of the plan (from the first manual week, else the first week of
    # the month) and the reporting week when it comes later – the table stays narrow as the months go on.
    week_cols = _weekly_columns(store, p, plan, month_start, ach_cutoff)
    planned_state = ach_state
    wrows = []
    for c, r in zip(circles, rows):
        key = c["key"].upper()
        cells = []
        for wc in week_cols:
            a_, b_ = dt.date.fromisoformat(wc["start"]), dt.date.fromisoformat(wc["end"])
            new_target = None
            if planned_state is not None:
                hit = [isinstance(v, dt.date) and a_ <= v <= b_ for v in plan_rows["planned_date"]]
                new_target = int(sum(1 for h, s_ in zip(hit, planned_state) if h and s_ == c["key"]))
            old_target = plan.weeklyClosureTargets.get(wc["id"], {}).get(key) if plan else None
            achieved = plan_achieved(c["key"], a_, min(b_, ach_cutoff)) if wc["status"] != "not started" else None
            cells.append({"target": new_target, "oldTarget": old_target, "targetChange": _target_change(new_target, old_target), "achieved": achieved, "achievedPct": r2(achieved / new_target * 100) if achieved is not None and new_target else None})
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
                "oldTarget": _sum([x["weeks"][i]["oldTarget"] for x in wrows])[0],
                "achieved": _sum([x["weeks"][i]["achieved"] for x in wrows])[0],
            }
            for i in range(len(week_cols))
        ],
    }
    for cell in wtotal["weeks"]:
        cell["achievedPct"] = r2(cell["achieved"] / cell["target"] * 100) if cell["achieved"] is not None and cell["target"] else None
        cell["targetChange"] = _target_change(cell["target"], cell["oldTarget"])

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
        "achievedAsOf": ach_cutoff.isoformat(),
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
                "planAchieved": f"{ml} MTD Achieved",
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
        "weekly": {"title": "Weekly Closure Targets – Target vs Achieved", "weeks": week_cols, "rows": wrows, "total": wtotal},
        "circleCards": _circle_cards(store, p, circles, plan),
        "definitions": [
            _plan_source_note(month, future, plan_sources),
            f"{ml} MTD Achieved = GPs whose Ach Date (GP-wise plan block of the master data file) falls between 1 {D:%b} and {ach_cutoff:%d %b %Y} – the same count as AMC Conversion; % = of the {ml} plan.",
            f"Weekly: new target = GPs whose Planned Date falls in the Fri–Thu week (master data file); old target = the manually set target ({PLAN_FILE}); achieved = GPs whose Ach Date falls in the week, up to {ach_cutoff:%d %b %Y}; weeks not started show —. A new target LOWER than the old target is highlighted in red. Shown: the first {WEEKS_FROM_START} weeks of the plan and the current week.",
            "Circle cards: GPs converted to AMC = GPs whose AMC date falls in the period (AMC + incremental); week vs previous week, month-to-date vs the same days of the previous month, last four weeks, and the AMC count at the end of the baseline month (amcBaselineMonth in the plan file).",
        ],
        "warnings": warnings,
    }


WEEKS_FROM_START = 5


def _target_change(new: float | int | None, old: float | int | None) -> float | int | None:
    """New target − old (manual) target; negative = the data now plans FEWER GPs than the manual target (flagged).
    None when either is missing (no manual target for the week, or no plan block in the file)."""
    return None if new is None or old is None else new - old


def _weekly_columns(store: Store, p: ReportingPeriods, plan: _Plan | None, month_start: dt.date, cutoff: dt.date) -> list[dict[str, Any]]:
    """Week columns of the weekly closure table: the first WEEKS_FROM_START weeks of the plan + the reporting week
    (if later). The plan starts at the first manually set week (review_plan.json), else the week holding the 1st of
    the reporting month. Dates continue the file's Fri–Thu weeks after its last week."""
    weeks_known = {w.code: w for w in store.weeks}
    last = store.weeks[-1]

    def dates(n: int) -> tuple[dt.date, dt.date]:
        w = weeks_known.get(f"W-{n}")
        if w:
            return w.start, w.end
        return last.start + dt.timedelta(days=7 * (n - last.number)), last.end + dt.timedelta(days=7 * (n - last.number))

    manual = sorted(int(k[2:]) for k in (plan.weeklyClosureTargets if plan else {}))
    if manual:
        first = manual[0]
    else:
        first = next((w.number for w in store.weeks if w.start <= month_start <= w.end), p.week.number)
    numbers = list(range(first, first + WEEKS_FROM_START))
    if p.week.number > numbers[-1]:
        numbers.append(p.week.number)
    cols = []
    for n in numbers:
        start, end = dates(n)
        status = "done" if end <= cutoff else ("in progress" if start <= cutoff else "not started")
        cols.append({"id": f"W-{n}", "label": f"WK-{n}", "start": start.isoformat(), "end": end.isoformat(), "status": status, "current": n == p.week.number})
    return cols


def _plan_source_note(month: str, future: list[str], sources: dict[str, str]) -> str:
    """Definition line: where each month's plan comes from (file GP-wise plan or the management plan file)."""
    label = {"file": "GP-wise plan of the master data file (Planned Date)", "plan file": f"management plan ({PLAN_FILE})", "file + plan file": f"master data file where it has a plan for the state, else {PLAN_FILE}"}
    parts = [f"{_month_label(m)} = {label[sources.get(m, 'plan file')]}" for m in [month, *future]]
    return f"{_month_label(month)} = MTD conversion plan, the next months = monthly plans. Source: " + "; ".join(parts) + ". Overall = sum of circles."


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
