"""AMC conversion – GP-wise plan vs achievement, straight from the GP sheet's
"Incremental AMC GPs Plan vs Achievement" block (Planned Date / Ach Date per GP). Only counts, no formulas.

Plan data date M = the later of the file's data date and its latest Ach Date (capped at the file's last week end).
Month KPIs (month target, month-to-date, overdue) are always "so far": as of M, in M's month, so they roll over to the
next month by themselves and do not move with the week picker.
Week KPIs use the selected week, as of D = the week's end capped at M.

  Month target        GPs whose Planned Date falls in the month (whole month)
  MTD target          GPs whose Planned Date falls on day 1 .. M
  MTD achieved        GPs whose Ach Date falls on day 1 .. M
  Week target         GPs whose Planned Date falls in the reporting week (the master data sheet's week, whole week)
  Week achieved       GPs whose Ach Date falls in the reporting week, up to D
  Overdue             Planned Date on or before M but no Ach Date on or before M

Management view (same periods; the numbers of the review deck):
  Target              Planned Date in the period (as above)
  GP Ready            Ach Date in the period, up to the cutoff (= "achieved" above – the field work is done)
  GP Achieved         AMC Date (GP sheet column "AMC Date") of the plan GPs in the period, up to the cutoff – the
                      letter was accepted and the GP is under AMC
  Gap                 Target − GP Achieved
  Letters (of the period's GP Ready GPs – a letter is sent after the field work; cutoff = the same date):
                      submitted = "Letter submission date AMC Incremental" filled, not submitted = the rest of the
                      ready GPs, accepted = "AMC Date" filled (a part of submitted). Same as the review deck
                      ("Letter submitted" there = submitted − accepted, "Ready to submit" = not submitted).

An Ach Date after D (the file's date) is not counted and is reported as a warning. A Planned / Ach Date outside the
file's period (store.plan_date_range – e.g. 11-01-2026 typed for 01-11-2026) is never counted and is listed in a
warning with its GP codes. Targets are ALWAYS the Planned Date count; the management plan (amc_month_targets.json) is
shown next to it for reference only and never replaces or adds to a target, total or gap.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import get_settings
from .metrics import r2
from .store import Store, circle_code, slug

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Windows:
    as_of: dt.date  # week cutoff: the selected week's end, capped at the data date
    month_as_of: dt.date  # month-to-date cutoff: the file's data date (or the picked date; or, month_of_week, the week cutoff)
    month_start: dt.date
    month_end: dt.date
    week_start: dt.date
    week_end: dt.date


def plan_data_date(store: Store) -> dt.date:
    """How far the AMC plan data goes: the later of the file's data date and its latest Ach Date, so achievements are
    counted as far as the sheet records them. Capped at the end of the file's last week (a mistyped far-future Ach Date
    must not move the month / week)."""
    d = store.data_as_of
    p = store.amc_plan
    if not p.empty:
        cap = store.weeks[-1].end if store.weeks else d
        ach = [v for v in p["ach_date"] if isinstance(v, dt.date) and v <= cap]
        if ach:
            d = max(d, max(ach))
    return d


def windows(store: Store, week_code: str, as_of: dt.date | None = None, month_of_week: bool = False) -> Windows:
    """Periods of the KPIs. Default: weeks as of the selected week's end, months "so far" – both capped at the plan data
    date (plan_data_date). With `as_of` (a picked date): as of that date, its month and its week (as in the master data sheet).
    With `month_of_week` (AMC Conversion summary and its lists): the month follows the selected week – the month of its
    last day with data (week end capped at the plan data date), counted up to that day. Week 44 (24–30 Oct) shows the
    whole of October even when the file already has 1 Nov."""
    last = plan_data_date(store)
    if as_of is not None:
        d = max(min(as_of, last), store.weeks[0].start)  # never before the file's first week
        _, _, start, end = _week_of(store, d)
        return Windows(d, d, d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1]), start, end)
    w = store.week(week_code)
    d = min(w.end, last)
    m = d if month_of_week else last  # default: month KPIs are "so far this month", whatever week is selected
    return Windows(d, m, m.replace(day=1), m.replace(day=calendar.monthrange(m.year, m.month)[1]), w.start, w.end)


def available_dates(store: Store) -> list[str]:
    """Dates that can be picked on the page: every day with data from the file's first week on, newest first."""
    first = min(store.daily.columns) if len(store.daily.columns) else store.data_as_of
    first = min(max(first, store.weeks[0].start), store.data_as_of)
    n = (store.data_as_of - first).days
    return [(store.data_as_of - dt.timedelta(days=i)).isoformat() for i in range(n + 1)]


def _between(values: pd.Series, a: dt.date, b: dt.date) -> np.ndarray:
    return np.array([isinstance(v, dt.date) and a <= v <= b for v in values], dtype=bool)


def plan_gp_dates(store: Store, column: str) -> pd.Series:
    """A GP-sheet date column ("amc_date", "letter_date") for the plan rows (same index as store.amc_plan)."""
    p = store.amc_plan
    if column not in store.gps.columns:
        return pd.Series([None] * len(p), index=p.index, dtype=object)
    return store.gps[column].reindex(p.index)


def masks(store: Store, win: Windows) -> dict[str, np.ndarray]:
    """Boolean masks over store.amc_plan rows, one per KPI / list."""
    p = store.amc_plan
    planned, ach = p["planned_date"], p["ach_date"]
    amc = plan_gp_dates(store, "amc_date")
    achieved_by_m = _between(ach, dt.date.min, win.month_as_of)
    return {
        # GP Achieved = AMC Date in the period (letter accepted, GP under AMC)
        "mtd-converted": _between(amc, win.month_start, win.month_as_of),
        "week-converted": _between(amc, win.week_start, min(win.week_end, win.as_of)),
        "month-target": _between(planned, win.month_start, win.month_end),
        "mtd-target": _between(planned, win.month_start, win.month_as_of),
        "mtd-achieved": _between(ach, win.month_start, win.month_as_of),
        "week-target": _between(planned, win.week_start, win.week_end),
        "week-achieved": _between(ach, win.week_start, min(win.week_end, win.as_of)),
        "overdue": _between(planned, dt.date.min, win.month_as_of) & ~achieved_by_m,
    }


def approval_masks(values: pd.Series) -> dict[str, np.ndarray]:
    """'Approval Status' of the plan rows. The letter goes to IE first, then to BSNL, so a GP approved by BSNL has also
    been accepted by IE. Case and spacing are ignored ("Pending by IE" = "Pending By IE")."""
    s = values.fillna("").astype(str).str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
    bsnl = s.str.startswith("approved by bsnl").to_numpy()
    ie_ok = s.str.startswith("approved by ie").to_numpy()
    return {"bsnl-accepted": bsnl, "ie-accepted": bsnl | ie_ok, "ie-rejected": s.str.startswith("rejected by ie").to_numpy(), "ie-pending": s.str.startswith("pending by ie").to_numpy()}


def _pct(a: int, b: int) -> float | None:
    return r2(a / b * 100) if b else None


def invalid_date_warnings(store: Store) -> list[str]:
    """Plan dates outside the file's period (not counted anywhere) – with the GP codes, so they can be corrected."""
    from .store import plan_date_range

    p = store.amc_plan
    out = []
    if p.empty:
        return out
    lo, hi = plan_date_range(store.weeks, store.data_as_of)
    for col, what, effect in (("planned_date_invalid", "Planned Date", "not counted as a target"), ("ach_date_invalid", "Ach Date", "not counted as GP Ready")):
        if col not in p.columns:
            continue
        bad = [(code, v) for code, v in p[col].items() if isinstance(v, dt.date)]
        if bad:
            dates = sorted({v for _, v in bad})
            shown = ", ".join(f"{v:%d %b %Y}" for v in dates[:3]) + (" …" if len(dates) > 3 else "")
            codes = ", ".join(str(c) for c, _ in bad[:12]) + (f" … (+{len(bad) - 12})" if len(bad) > 12 else "")
            out.append(
                f"{len(bad)} GP{'s have a' if len(bad) != 1 else ' has a'} {what} outside the file's period ({shown}; valid {lo:%d %b %Y} – {hi:%d %b %Y}) – {effect}. "
                f"Day and month swapped? Please correct in the master data: GP {codes}."
            )
    return out


def amc_plan_summary(store: Store, week_code: str, as_of: dt.date | None = None) -> dict[str, Any]:
    win = windows(store, week_code, as_of, month_of_week=True)  # the month cards follow the selected week
    code, number, _, _ = _week_of(store, win.week_start)
    p = store.amc_plan
    has_plan = not p.empty
    warnings: list[str] = []
    if not has_plan:
        warnings.append("The active file has no GP-wise AMC plan (columns “Planned Date” / “Ach Date” in GP Wise Data) – upload a file that has them.")
        p = pd.DataFrame(columns=["category", "planned_date", "ach_date", "current_status", "letter_status", "letter_date"])
    g = store.gps
    m = masks(store, win) if has_plan else {k: np.zeros(0, dtype=bool) for k in ("month-target", "mtd-target", "mtd-achieved", "week-target", "week-achieved", "overdue", "mtd-converted", "week-converted")}
    # Letters of the GP Ready GPs: submitted = letter date filled (on or before the cutoff), accepted = AMC Date filled.
    letter_d = plan_gp_dates(store, "letter_date") if has_plan else pd.Series([], dtype=object)
    amc_d = plan_gp_dates(store, "amc_date") if has_plan else pd.Series([], dtype=object)
    sent_m, sent_w = _between(letter_d, dt.date.min, win.month_as_of), _between(letter_d, dt.date.min, win.as_of)
    accepted_m, accepted_w = _between(amc_d, dt.date.min, win.month_as_of), _between(amc_d, dt.date.min, win.as_of)
    circle_of = g["circle"].reindex(p.index).to_numpy()
    status = p["letter_status"].fillna("").astype(str).str.strip().str.lower()
    letter = {"submitted": status.str.startswith("submit").to_numpy(), "pending": status.str.startswith("pend").to_numpy()}
    letter["other"] = ~(letter["submitted"] | letter["pending"])
    approval = approval_masks(p["approval_status"] if "approval_status" in p.columns else pd.Series([None] * len(p), index=p.index))
    # Plan category of the GP ("5% Contractual Incremental+ Additional AMC" column): "5% Incremental" or "Additional Plan".
    # The 5% Incremental figures are a part of the totals above (never added on top), counted from this column.
    incremental = p["category"].fillna("").astype(str).str.lower().str.contains("incremental").to_numpy()

    # Circles in the same order as the rest of the dashboard (by revised scope), plan or not.
    sizes = g[g["revised"]].groupby("circle").size().reindex(g["circle"].unique(), fill_value=0).sort_values(ascending=False)
    rows = []
    for c in sizes.index:
        sel = circle_of == c
        row = {
            "id": slug(c),
            "code": circle_code(c),
            "name": str(c).title(),
            "planGps": int(sel.sum()),
            "withoutPlannedDate": int((sel & np.array([not isinstance(v, dt.date) for v in p["planned_date"]], dtype=bool)).sum()) if has_plan else 0,
        }
        for key, field in (("month-target", "monthTarget"), ("mtd-target", "mtdTarget"), ("mtd-achieved", "mtdAchieved"), ("week-target", "weekTarget"), ("week-achieved", "weekAchieved"), ("overdue", "overdue")):
            row[field] = int((sel & m[key]).sum())
        # Letter Status of the achieved GPs ("Letter Status" column): Submitted / Pending / anything else = not recorded
        for key, prefix in (("mtd-achieved", "mtd"), ("week-achieved", "week")):
            for status, field in (("submitted", "LetterSubmitted"), ("pending", "LetterPending"), ("other", "LetterNotRecorded")):
                row[prefix + field] = int((sel & m[key] & letter[status]).sum())
            for status, field in (("ie-accepted", "IeAccepted"), ("bsnl-accepted", "BsnlAccepted"), ("ie-rejected", "IeRejected"), ("ie-pending", "IePending")):
                row[prefix + field] = int((sel & m[key] & approval[status]).sum())
        for key, field in (("month-target", "incMonthTarget"), ("mtd-target", "incMtdTarget"), ("mtd-achieved", "incMtdAchieved"), ("week-target", "incWeekTarget"), ("week-achieved", "incWeekAchieved")):
            row[field] = int((sel & m[key] & incremental).sum())
        # Management view: Target / GP Ready (Ach Date) / GP Achieved (AMC Date) / Gap, and the letters of the target GPs
        row["monthReady"], row["weekReady"] = row["mtdAchieved"], row["weekAchieved"]
        row["monthConverted"] = int((sel & m["mtd-converted"]).sum())
        row["weekConverted"] = int((sel & m["week-converted"]).sum())
        row["incMonthConverted"] = int((sel & m["mtd-converted"] & incremental).sum())
        row["incWeekConverted"] = int((sel & m["week-converted"] & incremental).sum())
        for prefix, ready, sent, accepted in (("month", m["mtd-achieved"], sent_m, accepted_m), ("week", m["week-achieved"], sent_w, accepted_w)):
            row[prefix + "ReadyLetterSubmitted"] = int((sel & ready & sent).sum())
            row[prefix + "ReadyLetterNotSubmitted"] = int((sel & ready & ~sent).sum())
            row[prefix + "ReadyLetterAccepted"] = int((sel & ready & accepted).sum())
            # same letter split for the 5% Incremental part of the ready GPs
            row["inc" + prefix.title() + "ReadyLetterSubmitted"] = int((sel & ready & incremental & sent).sum())
            row["inc" + prefix.title() + "ReadyLetterNotSubmitted"] = int((sel & ready & incremental & ~sent).sum())
        rows.append(row)

    def total(field: str) -> int:
        return sum(r[field] for r in rows)

    letter_fields = [p_ + f for p_ in ("mtd", "week") for f in ("LetterSubmitted", "LetterPending", "LetterNotRecorded", "IeAccepted", "BsnlAccepted", "IeRejected", "IePending")] + [
        "incMonthTarget", "incMtdTarget", "incMtdAchieved", "incWeekTarget", "incWeekAchieved",
        "monthReady", "weekReady", "monthConverted", "weekConverted", "incMonthConverted", "incWeekConverted",
        *(p_ + f for p_ in ("month", "week") for f in ("ReadyLetterSubmitted", "ReadyLetterNotSubmitted", "ReadyLetterAccepted")),
        *(f"inc{p_}{f}" for p_ in ("Month", "Week") for f in ("ReadyLetterSubmitted", "ReadyLetterNotSubmitted")),
    ]
    tot = {"id": "all", "code": "ALL", "name": "Overall", **{f: total(f) for f in ("planGps", "withoutPlannedDate", "monthTarget", "mtdTarget", "mtdAchieved", "weekTarget", "weekAchieved", "overdue", *letter_fields)}}
    for r in [*rows, tot]:
        r["mtdAchievedPct"] = _pct(r["mtdAchieved"], r["mtdTarget"])
        r["monthAchievedPct"] = _pct(r["mtdAchieved"], r["monthTarget"])
        r["weekAchievedPct"] = _pct(r["weekAchieved"], r["weekTarget"])
        r["monthGap"] = r["monthTarget"] - r["monthConverted"]
        r["weekGap"] = r["weekTarget"] - r["weekConverted"]
        r["monthReadyPct"] = _pct(r["monthReady"], r["monthTarget"])
        r["weekReadyPct"] = _pct(r["weekReady"], r["weekTarget"])
        r["monthConvertedPct"] = _pct(r["monthConverted"], r["monthTarget"])
        r["weekConvertedPct"] = _pct(r["weekConverted"], r["weekTarget"])
    no_plan = [r["name"] for r in rows if r["planGps"] == 0]
    if has_plan and no_plan:
        warnings.append(f"No GP-wise plan in the file for {', '.join(no_plan)} – counted as 0.")
    if has_plan:
        # Only an Ach Date after the FILE's plan data date is suspicious; later dates seen from an earlier week or a
        # picked earlier date are normal.
        plan_end = plan_data_date(store)
        late = int(_between(p["ach_date"], plan_end + dt.timedelta(days=1), dt.date.max).sum())
        if late:
            warnings.append(f"{late} GP{'s have an Ach Date' if late != 1 else ' has an Ach Date'} after the file's last week ({plan_end:%d %b %Y}) – not counted; please check the date.")
        if tot["monthTarget"] == 0:
            warnings.append(f"No Planned Date in {win.month_start:%b %Y} in the file yet – the month target shows 0.")
        warnings += invalid_date_warnings(store)

    # Day-wise plan vs achievement of the month (cumulative), for the chart.
    days = []
    cum_p = cum_a = 0
    planned = p["planned_date"].to_numpy()
    ach = p["ach_date"].to_numpy()
    d = win.month_start
    while d <= win.month_end:
        n_p = int(sum(1 for v in planned if v == d))
        n_a = int(sum(1 for v in ach if v == d)) if d <= win.month_as_of else None
        cum_p += n_p
        if n_a is not None:
            cum_a += n_a
        days.append({"date": d.isoformat(), "planned": n_p, "achieved": n_a, "cumulativePlanned": cum_p, "cumulativeAchieved": cum_a if n_a is not None else None})
        d += dt.timedelta(days=1)

    return {
        "hasPlan": has_plan,
        # False when the file (or an import made before this column was read) has no 'Approval Status' – the page then
        # hides the approval line instead of showing zeros.
        "hasApproval": bool(has_plan and "approval_status" in p.columns and p["approval_status"].notna().any()),
        "asOf": win.as_of.isoformat(),
        "monthAsOf": win.month_as_of.isoformat(),
        "month": {"id": f"{win.month_start:%Y-%m}", "label": f"{win.month_start:%b %Y}", "start": win.month_start.isoformat(), "end": win.month_end.isoformat(), "daysElapsed": (win.month_as_of - win.month_start).days + 1, "daysInMonth": win.month_end.day},
        "dates": available_dates(store),
        "week": {"id": code, "number": number, "label": f"Week {number}", "start": win.week_start.isoformat(), "end": win.week_end.isoformat(), "complete": win.week_end <= win.as_of},
        "total": tot,
        "rows": rows,
        "days": days,
        "categories": [{"label": k, "gps": int(v)} for k, v in p["category"].fillna("Not specified").value_counts().items()] if has_plan else [],
        "definitions": [
            "Source: GP Wise Data → “Incremental AMC GPs Plan vs Achievement” (Planned Date, Ach Date per GP). Every figure is a count of GPs.",
            f"Month target = GPs with a Planned Date in {win.month_start:%B %Y}; it moves to the next month automatically when the data does.",
            f"Month-to-date = 1 – {win.month_as_of:%d %b} ({(win.month_as_of - win.month_start).days + 1} days, up to the latest data): target = Planned Date in that range, achieved = Ach Date in that range.",
            f"Week {number} = {win.week_start:%d %b} – {win.week_end:%d %b} (as in the master data sheet): target = Planned Date in the week, achieved = Ach Date in the week up to {win.as_of:%d %b}.",
            "Overdue = Planned Date on or before the latest data date but not achieved by then. GPs in the plan without a Planned Date are not in any target.",
            "Approval (“Approval Status” column) of the achieved GPs: IE accepted = Approved By IE or Approved By BSNL (BSNL approves after IE); BSNL accepted = Approved By BSNL; IE rejected = Rejected BY IE; IE pending = Pending by IE.",
            "5% Incremental = the part of each target / achievement whose plan category (column “5% Contractual Incremental+ Additional AMC”) is “5% Incremental”; the rest is “Additional Plan”.",
            f"GP Ready = Ach Date in the period; GP Achieved = “AMC Date” (GP sheet) of the plan GPs in the period, up to the cutoff (letter accepted, under AMC); Gap = Target − GP Achieved.",
            "Letters of the GP Ready GPs: submitted = “Letter submission date AMC Incremental” filled; not submitted = the rest of the ready GPs; accepted = “AMC Date” filled (a part of submitted; each up to the cutoff date).",
        ],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- month targets file (fallback)

TARGETS_FILE = "amc_month_targets.json"


class _MonthTargets(BaseModel):
    source: str = Field("Month targets", max_length=300)
    targets: dict[str, dict[str, int | None]] = {}

    @field_validator("targets")
    @classmethod
    def _check(cls, v: dict[str, dict[str, int | None]]) -> dict[str, dict[str, int | None]]:
        for k, vals in v.items():
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", k):
                raise ValueError(f"month key {k!r} must be YYYY-MM")
            if any(x is not None and x < 0 for x in vals.values()):
                raise ValueError("targets must be >= 0")
        return v


_targets_cache: dict[str, tuple[float, _MonthTargets | None, str | None]] = {}
_targets_lock = threading.Lock()


def load_month_targets() -> tuple[_MonthTargets | None, str | None]:
    """data/amc_month_targets.json (re-read when it changes). Returns (targets, problem); never raises."""
    path: Path = get_settings().data_dir / TARGETS_FILE
    if not path.exists():
        return None, None
    mtime = path.stat().st_mtime
    with _targets_lock:
        hit = _targets_cache.get(str(path))
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
    try:
        if path.stat().st_size > 64 * 1024:
            raise ValueError("file too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("_help", None)
        parsed, problem = _MonthTargets.model_validate(data), None
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        log.warning("Invalid %s: %s", TARGETS_FILE, exc)
        parsed, problem = None, f"{TARGETS_FILE} is invalid – months without Planned Dates in the file show no target."
    with _targets_lock:
        _targets_cache[str(path)] = (mtime, parsed, problem)
    return parsed, problem


def targets_stamp() -> float | None:
    """Modification time of the targets file (part of the cache key, so a saved change shows at once)."""
    path: Path = get_settings().data_dir / TARGETS_FILE
    return path.stat().st_mtime if path.exists() else None


# ---------------------------------------------------------------- month-wise / week-wise timeline


def _week_of(store: Store, d: dt.date) -> tuple[str, int, dt.date, dt.date]:
    """The file's week (as in the master data sheet) containing d (weeks outside the file's weeks continue its 7-day rhythm, numbered 1..52)."""
    w = store.week_containing(d)
    return w.code, w.number, w.start, w.end


def _status(start: dt.date, end: dt.date, as_of: dt.date) -> str:
    return "done" if end <= as_of else ("in progress" if start <= as_of else "not started")


def amc_plan_timeline(store: Store, week_code: str) -> dict[str, Any]:
    """Month-wise and week-wise plan (Planned Date) vs achieved (Ach Date), per state – counts only.
    Periods = every month / week with a planned or achieved GP, plus the current month and week, plus (months) every
    month of the targets file. Months and weeks are counted up to the selected week's end (capped at the latest data
    date); the current month is the selected week's month (as on the summary).
    Month target of a state = GPs with a Planned Date in the month when the file has any; otherwise the targets file."""
    win = windows(store, week_code, month_of_week=True)
    mt, mt_problem = load_month_targets()
    p = store.amc_plan
    g = store.gps
    has_plan = not p.empty
    planned = p["planned_date"] if has_plan else pd.Series([], dtype=object)
    ach = p["ach_date"] if has_plan else pd.Series([], dtype=object)
    amc_d = plan_gp_dates(store, "amc_date") if has_plan else pd.Series([], dtype=object)
    circle_of = g["circle"].reindex(p.index).to_numpy() if has_plan else np.array([], dtype=object)
    sizes = g[g["revised"]].groupby("circle").size().reindex(g["circle"].unique(), fill_value=0).sort_values(ascending=False)
    states = [(slug(c), circle_code(c), str(c).title(), c) for c in sizes.index]
    dates = [d for d in [*planned, *ach] if isinstance(d, dt.date)]

    M = win.month_as_of
    keys = {(d.year, d.month) for d in dates} | {(M.year, M.month)} | {(int(k[:4]), int(k[5:])) for k in (mt.targets if mt else {})}
    months = []
    for y, m in sorted(keys):
        start, end = dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])
        months.append({"id": f"{y}-{m:02d}", "label": start.strftime("%b %Y"), "start": start, "end": end, "status": _status(start, end, M), "current": (y, m) == (M.year, M.month)})

    found = {_week_of(store, d) for d in dates} | {_week_of(store, win.week_start)}
    weeks = [{"id": code, "number": n, "label": f"WK-{n}", "start": s, "end": e, "status": _status(s, e, win.as_of), "current": code == week_code} for code, n, s, e in sorted(found, key=lambda x: x[2])]

    def file_target(month_id: str, state_key: str) -> int | None:
        if store.full_circles is not None and state_key.upper() not in store.full_circles:
            return None  # data access: a whole-state target is never applied to part of a state
        vals = mt.targets.get(month_id) if mt else None
        return vals.get(state_key.upper()) if vals else None

    def cells(periods: list[dict[str, Any]], sel: np.ndarray | None, cutoff: dt.date, state_key: str | None, monthly: bool) -> list[dict[str, Any]]:
        out = []
        cum_t = cum_a = 0
        for per in periods:
            a, b = per["start"], per["end"]
            in_t = _between(planned, a, b)
            in_a = _between(ach, a, min(b, cutoff))
            in_c = _between(amc_d, a, min(b, cutoff))  # GP Achieved: AMC Date in the period
            due = _between(planned, a, min(b, cutoff))
            if sel is not None:
                in_t, in_a, in_c, due = in_t & sel, in_a & sel, in_c & sel, due & sel
            target, achieved, converted = int(in_t.sum()), int(in_a.sum()), int(in_c.sum())
            due_n: int | None = int(due.sum())
            # target = Planned Date count, always; the management plan figure is reference only (never counted)
            plan_t = file_target(per["id"], state_key) if monthly and state_key is not None else None
            started = per["status"] != "not started"
            cum_t += target
            cum_a += achieved
            out.append(
                {
                    "target": target,
                    "targetSource": "excel",
                    "planTarget": plan_t,
                    "achieved": achieved if started else None,
                    "achievedPct": _pct(achieved, target) if started else None,
                    # management view: GP Ready = Ach Date (= achieved), GP Achieved = AMC Date, Gap = target − GP Achieved
                    "ready": achieved if started else None,
                    "converted": converted if started else None,
                    "gap": target - converted if started else None,
                    # planned in the period on or before the data date (the part of the target already due); file targets only
                    "dueTarget": due_n if started else None,
                    "cumulativeTarget": cum_t,
                    "cumulativeAchieved": cum_a if started else None,
                }
            )
        return out

    def table(periods: list[dict[str, Any]], cutoff: dt.date, monthly: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = [{"id": i, "code": code, "name": name, "cells": cells(periods, circle_of == key, cutoff, key, monthly)} for i, code, name, key in states]
        if not monthly:
            return rows, {"id": "all", "code": "ALL", "name": "Overall", "cells": cells(periods, None, cutoff, None, False)}
        # Overall month = sum of the states (each state's target may come from the file or the targets file)
        total_cells = []
        cum_t = cum_a = 0
        for k, per in enumerate(periods):
            cs = [r["cells"][k] for r in rows]
            target = sum(c["target"] for c in cs)
            achieved = sum(c["achieved"] or 0 for c in cs)
            converted = sum(c["converted"] or 0 for c in cs)
            started = per["status"] != "not started"
            plans = [c["planTarget"] for c in cs if c.get("planTarget") is not None]
            cum_t += target
            cum_a += achieved
            total_cells.append(
                {
                    "target": target,
                    "targetSource": "excel",
                    "planTarget": sum(plans) if plans else None,
                    "achieved": achieved if started else None,
                    "achievedPct": _pct(achieved, target) if started else None,
                    "ready": achieved if started else None,
                    "converted": converted if started else None,
                    "gap": target - converted if started else None,
                    "dueTarget": sum(c["dueTarget"] or 0 for c in cs) if started else None,
                    "cumulativeTarget": cum_t,
                    "cumulativeAchieved": cum_a if started else None,
                }
            )
        return rows, {"id": "all", "code": "ALL", "name": "Overall", "cells": total_cells}

    def iso(per: dict[str, Any]) -> dict[str, Any]:
        return {**per, "start": per["start"].isoformat(), "end": per["end"].isoformat()}

    m_rows, m_total = table(months, M, True)
    w_rows, w_total = table(weeks, win.as_of, False)
    warnings = [mt_problem] if mt_problem else []
    warnings += invalid_date_warnings(store)
    if not has_plan:
        warnings.append("The active file has no GP-wise AMC plan (columns “Planned Date” / “Ach Date” in GP Wise Data) – upload a file that has them.")
    elif no_plan := [name for _, _, name, key in states if not (circle_of == key).any()]:
        warnings.append(f"No GP-wise plan in the file for {', '.join(no_plan)} – targets are 0 until a file with their Planned Dates is uploaded.")
    return {
        "hasPlan": has_plan,
        "asOf": win.as_of.isoformat(),
        "monthAsOf": M.isoformat(),
        "targetsSource": mt.source if mt else None,
        "monthly": {"months": [iso(m) for m in months], "rows": m_rows, "total": m_total},
        "weekly": {"weeks": [iso(w) for w in weeks], "rows": w_rows, "total": w_total},
        "definitions": [
            "Source: GP Wise Data → “Incremental AMC GPs Plan vs Achievement”. Target = GPs whose Planned Date falls in the month / week; achieved = GPs whose Ach Date falls in it, up to the data date.",
            f"Targets are always counted from the Planned Dates of the file. “Mgmt plan” = the management plan of {TARGETS_FILE}{' (' + mt.source + ')' if mt else ''}, shown for reference only – it is never used as a target, in totals or in the gap.",
            f"Data date {win.as_of:%d %b %Y}: later months / weeks show no achievement yet. “Due” = the part of the target whose Planned Date is on or before the data date.",
            "Weeks are the file's week (as in the master data sheet)s (weeks after the file's last week continue the same 7-day rhythm). Every month / week with a planned or achieved GP is shown.",
            "Overall = all states. A state without a plan in the file shows 0 until a file with its plan is uploaded.",
            "GP Ready = Ach Date in the month / week; GP Achieved = “AMC Date” of the plan GPs in it (letter accepted); Gap = Target − GP Achieved.",
        ],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- area manager breakdown (one state)

NOT_ASSIGNED = "Not assigned"
VACANT = "Vacant (no AM)"


def _am_names(store: Store, idx: pd.Index) -> tuple[pd.Series, str, str | None, pd.DataFrame | None]:
    """Area manager of each GP: the Escalation Matrix (latest upload, complete per GP) when there is one, else the
    master data's AM Name. Returns (names, source, source file, matrix rows of the GPs or None).
    Blank -> "Not assigned", "Vacant…" -> VACANT."""
    from .escalation import NoEscalationData, _frame, is_vacant

    esc_rows: pd.DataFrame | None = None
    try:
        meta, esc = _frame(store)
        esc_rows = esc.reindex(idx)
        raw = esc_rows["am_name"]
        source, file_name = "escalation", meta.get("fileName") or meta.get("file_name")
    except NoEscalationData:
        raw = store.gps.loc[idx, "am_name"]
        source, file_name = "master", store.file_name

    def label(v: Any) -> str:
        if not isinstance(v, str) or not v.strip() or v.strip() == "0":
            return NOT_ASSIGNED
        return VACANT if is_vacant(v) else " ".join(v.split())

    return raw.map(label), source, file_name, esc_rows


def _distinct(values: pd.Series, title: bool = False) -> list[str]:
    """Distinct non-blank texts in first-seen order ("a / b" cells are split)."""
    out: dict[str, None] = {}
    for v in values:
        if not isinstance(v, str):
            continue
        for part in v.split(" / "):
            part = " ".join(part.split())
            if part and part != "0":
                out[part.title() if title else part] = None
    return list(out)


def mask_email(v: str, full: bool) -> str:
    """E-mail in full for admins, otherwise the first 2 characters of the name part (sh*****@pratap.co.in)."""
    if full or "@" not in v:
        return v
    user, domain = v.split("@", 1)
    return f"{user[:2]}{'*' * max(3, len(user) - 2)}@{domain}"


def amc_plan_area_managers(store: Store, week_code: str, circle_id: str, full_contacts: bool = False) -> dict[str, Any]:
    """Area-manager-wise view of one state for AMC Conversion → Monthly / Weekly Plan vs Execution.

    Per area manager: blocks and existing GPs (GP Wise Data), AMC / non-AMC GPs as of the reporting week's end (same
    rule as the KPI cards), and – from the GP-wise plan block – the current month's target (Planned Date in the month)
    and achievement (Ach Date from the 1st up to the data date), and the selected week's target / achievement.
    Same windows and masks as the page's state table, so the AM rows add up to the state's figures."""
    g = store.gps
    sel = (g["circle_id"] == circle_id).to_numpy()
    if not sel.any():
        raise KeyError(circle_id)
    sub = g[sel]
    names, source, file_name, esc_rows = _am_names(store, sub.index)
    # Business area per GP: the matrix's BA column, else (no matrix, or a GP without a BA there) the master data's BA.
    master_ba = sub["ba"] if "ba" in sub.columns else pd.Series(None, index=sub.index, dtype=object)
    ba = esc_rows["ba"].where(esc_rows["ba"].notna(), master_ba) if esc_rows is not None and "ba" in esc_rows.columns else master_ba
    am_email = esc_rows["am_email"] if esc_rows is not None and "am_email" in esc_rows.columns else pd.Series(None, index=sub.index, dtype=object)
    wf = store.week_frame(week_code).loc[sub.index]
    win = windows(store, week_code, month_of_week=True)  # the month follows the selected week, as on the summary
    code, number, _, _ = _week_of(store, win.week_start)

    p = store.amc_plan
    has_plan = not p.empty
    plan = p[p.index.isin(sub.index)] if has_plan else p
    plan_am = names.reindex(plan.index) if has_plan else pd.Series([], dtype=object)
    month_t = _between(plan["planned_date"], win.month_start, win.month_end) if has_plan else np.zeros(0, dtype=bool)
    month_a = _between(plan["ach_date"], win.month_start, win.month_as_of) if has_plan else np.zeros(0, dtype=bool)
    week_t = _between(plan["planned_date"], win.week_start, win.week_end) if has_plan else np.zeros(0, dtype=bool)
    week_a = _between(plan["ach_date"], win.week_start, min(win.week_end, win.as_of)) if has_plan else np.zeros(0, dtype=bool)
    plan_amc = plan_gp_dates(store, "amc_date").reindex(plan.index) if has_plan else pd.Series([], dtype=object)
    month_c = _between(plan_amc, win.month_start, win.month_as_of) if has_plan else np.zeros(0, dtype=bool)
    week_c = _between(plan_amc, win.week_start, min(win.week_end, win.as_of)) if has_plan else np.zeros(0, dtype=bool)

    def plan_count(mask: np.ndarray, am: str) -> int:
        return int((mask & (plan_am.to_numpy() == am)).sum()) if has_plan else 0

    rows = []
    for am, idx in sub.groupby(names).groups.items():
        part = sub.loc[idx]
        amc = wf.loc[idx, "amc"]
        assigned = am not in (NOT_ASSIGNED, VACANT)
        row = {
            "name": am,
            "assigned": assigned,
            "businessAreas": sorted(_distinct(ba.loc[idx], title=True)),
            "emails": [mask_email(e, full_contacts) for e in _distinct(am_email.loc[idx])] if assigned else [],
            "blocks": int(part["block_id"].nunique()),
            "existingGps": len(idx),
            "amcGps": int(amc.sum()),
            "nonAmcGps": int((part["revised"] & ~amc).sum()),
            "monthTarget": plan_count(month_t, am),
            "monthAchieved": plan_count(month_a, am),
            "weekTarget": plan_count(week_t, am),
            "weekAchieved": plan_count(week_a, am),
            # GP Achieved = AMC Date of the plan GPs in the period (letter accepted) – never the Ach Date
            "monthConverted": plan_count(month_c, am),
            "weekConverted": plan_count(week_c, am),
        }
        rows.append(row)
    # real names A–Z, then Vacant / Not assigned
    rows.sort(key=lambda r: (not r["assigned"], r["name"] == NOT_ASSIGNED, r["name"].lower()))
    keys = ("existingGps", "amcGps", "nonAmcGps", "monthTarget", "monthAchieved", "weekTarget", "weekAchieved", "monthConverted", "weekConverted")
    total = {"name": "Total", "assigned": True, "businessAreas": sorted(_distinct(ba, title=True)), "emails": [], "blocks": int(sub["block_id"].nunique()), **{k: sum(r[k] for r in rows) for k in keys}}
    for r in [*rows, total]:
        r["monthAchievedPct"] = _pct(r["monthAchieved"], r["monthTarget"])
        r["weekAchievedPct"] = _pct(r["weekAchieved"], r["weekTarget"])
        r["monthConvertedPct"] = _pct(r["monthConverted"], r["monthTarget"])
        r["weekConvertedPct"] = _pct(r["weekConverted"], r["weekTarget"])

    warnings = invalid_date_warnings(store)
    if not has_plan:
        warnings.append("The active file has no GP-wise AMC plan (Planned Date / Ach Date) – targets and achievements are 0.")
    if source == "master":
        warnings.append("No Escalation Matrix uploaded – area managers are taken from the master data's AM Name column (many GPs are not assigned there).")
    unassigned = sum(r["existingGps"] for r in rows if not r["assigned"])
    if unassigned:
        warnings.append(f"{unassigned:,} GPs have no area manager in the {'Escalation Matrix' if source == 'escalation' else 'master data'} (shown as {NOT_ASSIGNED} / {VACANT}).")
    state = str(sub["circle"].iloc[0]).title()
    return {
        "circle": {"id": circle_id, "name": state},
        "amSource": source,
        "amSourceFile": file_name,
        # e-mails come from the matrix's AM Email ID column; shown in full to admins only (like phone numbers)
        "hasEmails": bool(am_email.notna().any()),
        "emailsMasked": not full_contacts,
        "month": {"id": f"{win.month_start:%Y-%m}", "label": f"{win.month_start:%b %Y}", "start": win.month_start.isoformat(), "end": win.month_end.isoformat(), "asOf": win.month_as_of.isoformat()},
        "week": {"id": code, "number": number, "label": f"WK-{number}", "start": win.week_start.isoformat(), "end": win.week_end.isoformat(), "asOf": min(win.week_end, win.as_of).isoformat(), "complete": win.week_end <= win.as_of},
        "amcAsOf": min(store.week(week_code).end, store.data_as_of).isoformat(),
        "rows": rows,
        "total": total,
        "warnings": warnings,
    }
