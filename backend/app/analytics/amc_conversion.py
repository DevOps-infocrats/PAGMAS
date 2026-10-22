"""AMC Conversion – Plan vs Execution page.

Plan      = monthly plans: the master data file's GP-wise plan where it has one, else data/review_plan.json
            (review_targets.effective_plan); weekly closure targets: data/review_plan.json.
Execution = GPs whose AMC date falls inside the month / week (AMC + incremental), counted up to the cutoff
            (the last date with data, capped at the reporting week's end) – the same rule as the
            Management Review "Target & Achievement" page, whose current-month roadmap is reused here.

  Monthly: plan vs converted for every month of the plan; a month that has not started has no execution.
           Cumulative plan starts from the GPs already under AMC at the end of the month before the plan.
  Weekly:  every week of the plan (Fri–Thu, continuing the file's weeks): target vs converted in the week.
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Any

import pandas as pd

from .metrics import r2
from .review import _circle_list
from .review_periods import reporting_periods
from .review_targets import PLAN_FILE, _month_label, _sum, effective_plan, targets_page
from .store import Store
from .views import week_json


def _status(start: dt.date, end: dt.date, cutoff: dt.date) -> str:
    return "done" if end <= cutoff else ("in progress" if start <= cutoff else "not started")


def _pct(achieved: int | None, plan: int | float | None) -> float | None:
    return r2(achieved / plan * 100) if achieved is not None and plan else None


def amc_conversion(store: Store, week_code: str, compare_code: str) -> dict[str, Any]:
    week, compare = store.week(week_code), store.week(compare_code)
    p = reporting_periods(store, week, compare)
    D = p.cutoff
    circles = _circle_list(store)
    tp = targets_page(store, p, circles)
    plan, _, _ = effective_plan(store)  # monthly plan: file Planned Dates where present, else review_plan.json
    g = store.gps
    amc = pd.to_datetime(g["amc_date"], errors="coerce")
    masks = {c["id"]: (g["circle"] == c["key"]).to_numpy() for c in circles}

    def converted(cid: str | None, a: dt.date, b: dt.date) -> int:
        inside = (amc >= pd.Timestamp(a)) & (amc <= pd.Timestamp(min(b, D)))
        return int((inside.to_numpy() & masks[cid]).sum()) if cid else int(inside.sum())

    # ---------------------------------------------------------------- monthly
    months = sorted(plan.monthlyPlan) if plan else []
    month_cols = []
    for key in months:
        y, m = int(key[:4]), int(key[5:])
        start, end = dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])
        month_cols.append({"id": key, "label": _month_label(key), "start": start.isoformat(), "end": end.isoformat(), "status": _status(start, end, D)})
    base_end = dt.date.fromisoformat(month_cols[0]["start"]) - dt.timedelta(days=1) if month_cols else None

    def month_cells(cid: str | None, key_of: str | None) -> list[dict[str, Any]]:
        cells, cum_plan, cum_actual = [], None, None
        if base_end is not None:
            under = (amc <= pd.Timestamp(base_end)).to_numpy()
            cum_plan = cum_actual = int((under & masks[cid]).sum()) if cid else int(under.sum())
        for mc in month_cols:
            vals = plan.monthlyPlan[mc["id"]] if plan else {}
            partial = False
            if key_of:
                target = vals.get(key_of)
            else:
                target, partial = _sum([vals.get(c["key"].upper()) for c in circles])
            started = mc["status"] != "not started"
            achieved = converted(cid, dt.date.fromisoformat(mc["start"]), dt.date.fromisoformat(mc["end"])) if started else None
            cum_plan = cum_plan + target if cum_plan is not None and target is not None else None
            if started and cum_actual is not None:
                cum_actual += achieved
            cells.append(
                {
                    "plan": target,
                    "planPartial": partial,  # Overall only: a circle has no plan for this month
                    "achieved": achieved,
                    "achievedPct": _pct(achieved, target),
                    "gap": max(0, target - achieved) if target is not None and achieved is not None else None,
                    "cumulativePlan": cum_plan,
                    "cumulativeAchieved": cum_actual if started else None,
                }
            )
        return cells

    monthly_rows = [{"id": c["id"], "code": c["code"], "name": c["name"], "months": month_cells(c["id"], c["key"].upper())} for c in circles]
    monthly_total = {"id": "all", "code": "ALL", "name": "Overall", "months": month_cells(None, None)}

    # ---------------------------------------------------------------- weekly
    known = {w.code: w for w in store.weeks}
    last = store.weeks[-1]
    week_cols = []
    for code in sorted(plan.weeklyClosureTargets if plan else {}, key=lambda k: int(k[2:])):
        n = int(code[2:])
        w = known.get(code)
        start = w.start if w else last.start + dt.timedelta(days=7 * (n - last.number))
        end = w.end if w else last.end + dt.timedelta(days=7 * (n - last.number))
        week_cols.append({"id": code, "label": f"WK-{n}", "start": start.isoformat(), "end": end.isoformat(), "status": _status(start, end, D)})

    def week_cells(cid: str | None, key_of: str | None) -> list[dict[str, Any]]:
        cells = []
        for wc in week_cols:
            vals = plan.weeklyClosureTargets[wc["id"]] if plan else {}
            target = vals.get(key_of) if key_of else _sum([vals.get(c["key"].upper()) for c in circles])[0]
            achieved = converted(cid, dt.date.fromisoformat(wc["start"]), dt.date.fromisoformat(wc["end"])) if wc["status"] != "not started" else None
            cells.append({"target": target, "achieved": achieved, "achievedPct": _pct(achieved, target)})
        return cells

    weekly_rows = [{"id": c["id"], "code": c["code"], "name": c["name"], "weeks": week_cells(c["id"], c["key"].upper())} for c in circles]
    weekly_total = {"id": "all", "code": "ALL", "name": "Overall", "weeks": week_cells(None, None)}

    # ---------------------------------------------------------------- headline (current month, overall)
    rm = tp["roadmap"]["total"]
    cur = next((i for i, mc in enumerate(month_cols) if mc["id"] == tp["month"]), None)
    under_amc = int((amc <= pd.Timestamp(D)).sum())
    revised = int(g["revised"].sum())
    headline = {
        "revisedScope": revised,
        "underAmc": under_amc,
        "underAmcPct": r2(under_amc / revised * 100) if revised else None,
        "monthPlan": rm["mtdPlan"],
        "monthAchieved": rm["mtdAchieved"],
        "monthAchievedPct": _pct(rm["mtdAchieved"], rm["mtdPlan"]),
        "projection": rm["projection"],
        "projectionGap": rm["gap"],
        "pendingScope": revised - under_amc,
        "totalPlan": _sum([c["plan"] for c in monthly_total["months"]])[0],
        "currentMonthIndex": cur,
    }

    ml = tp["monthLabel"]
    return {
        "week": week_json(week),
        "compareWeek": week_json(compare),
        "cutoff": D.isoformat(),
        "monthLabel": ml,
        "daysLeft": tp["daysLeft"],
        "planSource": tp["planSource"],
        "headline": headline,
        "circles": [{"id": c["id"], "code": c["code"], "name": c["name"]} for c in circles],
        "monthly": {"months": month_cols, "baselineDate": base_end.isoformat() if base_end else None, "rows": monthly_rows, "total": monthly_total},
        "weekly": {"weeks": week_cols, "rows": weekly_rows, "total": weekly_total},
        "roadmap": tp["roadmap"],
        "circleCards": tp["circleCards"],
        "definitions": [
            f"Plan = management plan ({PLAN_FILE}): monthly conversion plans and weekly closure targets. Overall = sum of the circles.",
            f"Executed (converted) = GPs whose AMC date falls inside the month / week (AMC + incremental), counted up to {D:%d %b %Y}; months and weeks not started show —.",
            f"Cumulative plan starts from the GPs already under AMC on {base_end:%d %b %Y} and adds each month's plan; cumulative executed adds the GPs actually converted."
            if base_end
            else "Cumulative columns need a monthly plan.",
            f"{ml} detail (projection, gap, pending after {ml}, ready for incremental) uses the same rules as Management Review → Target & Achievement.",
        ],
        "warnings": tp["warnings"],
    }
