"""Management Review – Page 1 "Executive Summary" calculations (no rendering here).

Definitions (configurable thresholds come from Settings):
  * Availability     the source's own percentage values (weekly W-nn columns); a GP counts in a week
                     only when it is under AMC by that week's end. NA (no value) is never 0%.
  * GPs > 98%        AMC GPs with weekly availability strictly above the healthy threshold;
                     denominator = AMC GPs with a reported value that week.
  * Blocks > 98%     blocks whose mean AMC GP availability is strictly above the threshold;
                     denominator = blocks with at least one reported AMC GP value.
  * GPs at 0%        AMC GPs with availability exactly 0 (NA excluded).
  * AMC conversion   an existing GP whose AMC date falls inside the period and whose AMC category is
                     "AMC"; GPs with category "Incremental" are counted separately as incremental
                     additions. Each GP has one AMC date, so every GP is counted at most once.
  * Target           O&M KEY NUMBERS "Target for Operational GP (<month>)" – a cumulative operational
                     GP target, compared with AMC GPs as of the month cutoff.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import numpy as np
import pandas as pd

from ..config import get_settings
from .metrics import r2
from .review_periods import ReportingPeriods, window_label
from .store import Store, Week

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _change(cur: float | None, prev: float | None, polarity: str) -> dict[str, Any]:
    """Absolute change, % change (only when the base is non-zero) and direction."""
    if cur is None or prev is None:
        return {"current": cur, "previous": prev, "delta": None, "pctChange": None, "trend": "na"}
    d = round(float(cur) - float(prev), 2)
    pct = round(d / float(prev) * 100, 1) if prev else None
    trend = "flat" if d == 0 else ("better" if (d > 0) == (polarity == "up") else "worse")
    if polarity == "neutral" and d:
        trend = "up" if d > 0 else "down"
    return {"current": cur, "previous": prev, "delta": d, "pctChange": pct, "trend": trend}


def _share(n: int, d: int) -> float | None:
    return r2(n / d * 100) if d else None


# ---------------------------------------------------------------- availability KPIs


def _week_availability(store: Store, week: Week, mask: np.ndarray) -> dict[str, Any]:
    s = get_settings()
    g = store.gps[mask]
    vals = store.week_frame(week.code)["weekly"][mask]  # already NaN unless under AMC by week end
    blocks = vals.groupby(g["block_id"]).mean().dropna()
    gps_rep, blk_rep = int(vals.notna().sum()), int(len(blocks))
    above, zero, b_above = int((vals > s.healthy_threshold).sum()), int((vals == 0).sum()), int((blocks > s.healthy_threshold).sum())
    return {
        "amcGps": int(store.week_frame(week.code)["amc"][mask].sum()),
        "gpsReported": gps_rep,
        "naGps": int(store.week_frame(week.code)["amc"][mask].sum()) - gps_rep,
        "blocksReported": blk_rep,
        "gpsAbove98": above,
        "gpsAbove98Pct": _share(above, gps_rep),
        "blocksAbove98": b_above,
        "blocksAbove98Pct": _share(b_above, blk_rep),
        "gpsAtZero": zero,
        "gpsAtZeroPct": _share(zero, gps_rep),
    }


KPI_CARDS = [
    # key, pct key, denominator key, label, polarity
    ("gpsAbove98", "gpsAbove98Pct", "gpsReported", "GPs > {h:g}% availability", "up"),
    ("blocksAbove98", "blocksAbove98Pct", "blocksReported", "Blocks > {h:g}% availability", "up"),
    ("gpsAtZero", "gpsAtZeroPct", "gpsReported", "GPs at 0% availability", "down"),
]


def _kpi_cards(cur: dict[str, dict], prev: dict[str, dict], circles: list[dict]) -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    for key, pkey, dkey, label, pol in KPI_CARDS:
        c, p = cur["all"], prev["all"]
        pp = None if c[pkey] is None or p[pkey] is None else round(c[pkey] - p[pkey], 2)
        out.append(
            {
                "key": key,
                "label": label.format(h=s.healthy_threshold),
                "unitOfCount": "blocks" if key.startswith("blocks") else "GPs",
                **_change(c[key], p[key], pol),
                "currentPct": c[pkey],
                "previousPct": p[pkey],
                "ppChange": pp,
                "currentDenominator": c[dkey],
                "previousDenominator": p[dkey],
                "breakdown": [{"id": x["id"], "code": x["code"], **_change(cur[x["id"]][key], prev[x["id"]][key], pol)} for x in circles],
            }
        )
    return out


# ---------------------------------------------------------------- AMC conversions


def _conversions(store: Store, mask: np.ndarray, start: dt.date, end: dt.date) -> dict[str, int]:
    g = store.gps[mask]
    amc = pd.to_datetime(g["amc_date"], errors="coerce")
    inside = (amc >= pd.Timestamp(start)) & (amc <= pd.Timestamp(end))
    cat = g["amc_category"].fillna("")
    return {
        "amc": int((inside & (cat == "AMC")).sum()),
        "incremental": int((inside & (cat == "INCREMENTAL")).sum()),
        "uncategorised": int((inside & ~cat.isin(["AMC", "INCREMENTAL"])).sum()),
    }


def _conversion_cards(store: Store, p: ReportingPeriods, circles: list[dict]) -> list[dict[str, Any]]:
    out = []
    for c in circles:
        mask = (store.gps["circle"] == c["key"]).to_numpy()
        wk = _conversions(store, mask, p.week.start, p.week.end)
        pw = _conversions(store, mask, p.compare.start, p.compare.end)
        mo = _conversions(store, mask, *p.month)
        pm = _conversions(store, mask, *p.previous_month)
        out.append(
            {
                "id": c["id"],
                "code": c["code"],
                "name": c["name"],
                "week": {"amc": _change(wk["amc"], pw["amc"], "up"), "incremental": _change(wk["incremental"], pw["incremental"], "up")},
                "month": {"amc": _change(mo["amc"], pm["amc"], "up"), "incremental": _change(mo["incremental"], pm["incremental"], "up")},
                "uncategorised": wk["uncategorised"] + pw["uncategorised"] + mo["uncategorised"] + pm["uncategorised"],
            }
        )
    return out


# ---------------------------------------------------------------- targets


def _target_month(label: str, year_hint: int) -> str | None:
    m = re.search(r"\(\s*([A-Za-z]{3})[a-z]*[\s'-]*(\d{2,4})?", label)
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    year = int(m.group(2)) if m.group(2) else year_hint
    return f"{year + 2000 if year < 100 else year}-{_MONTHS[m.group(1).lower()]:02d}"


def _targets(store: Store) -> dict[str, dict[str, Any]]:
    """{"YYYY-MM": {"label": source label, "values": {CIRCLE: n}}} from the O&M KEY NUMBERS."""
    out: dict[str, dict[str, Any]] = {}
    rep = store.reported
    if rep.empty:
        return out
    for r in rep.itertuples():
        label = re.sub(r"\s+", " ", str(r.metric)).strip()
        if not re.match(r"target for operational gp", label, re.I) or r.value_num is None or pd.isna(r.value_num):
            continue
        month = _target_month(label, store.data_as_of.year)
        if month:
            out.setdefault(month, {"label": label, "values": {}})["values"][str(r.state).upper()] = float(r.value_num)
    return out


def _highlight_table(store: Store, p: ReportingPeriods, circles: list[dict], cards: list[dict]) -> dict[str, Any]:
    targets = _targets(store)
    want = f"{p.cutoff.year}-{p.cutoff.month:02d}"
    month = want if want in targets else (max(targets) if targets else None)
    t = targets.get(month) if month else None
    label = dt.date(int(month[:4]), int(month[5:]), 1).strftime("%b-%y") if month else None
    amc_dt = pd.to_datetime(store.gps["amc_date"], errors="coerce")
    letter = pd.to_datetime(store.gps["letter_date"], errors="coerce")
    # Weekly conversion columns: the last four source weeks ending with the reporting week
    # (W-38 … W-41 today; W-39 … W-42 once Week 42 is in the file).
    codes = [w.code for w in store.weeks]
    weeks = store.weeks[max(0, codes.index(p.week.code) - 3) : codes.index(p.week.code) + 1]
    # Month plan (management plan file) for the cutoff month.
    from .review_targets import load_plan  # local import: review_targets imports this module

    plan, _ = load_plan()
    month_plan = (plan.monthlyPlan.get(want) if plan else None) or {}
    rows = []
    for c, card in zip(circles, cards):
        mask = (store.gps["circle"] == c["key"]).to_numpy()
        amc_now = int((amc_dt[mask] <= pd.Timestamp(p.cutoff)).sum())
        target = t["values"].get(c["key"].upper()) if t else None
        under_amc = (amc_dt <= pd.Timestamp(p.cutoff)).to_numpy()
        weekly = [int(((amc_dt[mask] >= pd.Timestamp(w.start)) & (amc_dt[mask] <= pd.Timestamp(w.end))).sum()) for w in weeks]
        rows.append(
            {
                "id": c["id"],
                "code": c["code"],
                "name": c["name"],
                "weekAmc": card["week"]["amc"]["current"],
                "weekIncremental": card["week"]["incremental"]["current"],
                "previousWeekAmc": card["week"]["amc"]["previous"],
                "target": target,
                "amcGpsAsOfCutoff": amc_now,
                "targetProgressPct": r2(amc_now / target * 100) if target else None,
                "targetGap": r2(max(0.0, target - amc_now)) if target else None,
                # Key Highlights | AMC & monthly plan
                "currentAmc": amc_now,
                "weeklyConversions": weekly,
                "readyForIncremental": int((mask & letter.notna().to_numpy() & ~under_amc).sum()),
                "monthPlan": month_plan.get(c["key"].upper()),
            }
        )
    plans = [r["monthPlan"] for r in rows]
    total = {
        "id": "all",
        "code": "ALL",
        "name": "Overall",
        "currentAmc": sum(r["currentAmc"] for r in rows),
        "weeklyConversions": [sum(r["weeklyConversions"][i] for r in rows) for i in range(len(weeks))],
        "readyForIncremental": sum(r["readyForIncremental"] for r in rows),
        "monthPlan": sum(v for v in plans if v is not None) if any(v is not None for v in plans) else None,
    }
    plan_label = dt.date(p.cutoff.year, p.cutoff.month, 1).strftime("%b")
    return {
        "title": f"Key Highlights | AMC & {plan_label}’{p.cutoff:%y} Plan",
        "weeks": [{"id": w.code, "label": f"WK-{w.number}", "start": w.start.isoformat(), "end": w.end.isoformat()} for w in weeks],
        "monthPlanLabel": f"{plan_label} Plan",
        "cutoff": p.cutoff.isoformat(),
        "total": total,
        "basis": (
            f"Current AMC = GPs under AMC as of {p.cutoff:%d %b %Y}; WK columns = GPs converted to AMC in that week (AMC + incremental, by AMC date); "
            f"Ready for Inc = AMC / incremental letter submitted but not yet under AMC; {plan_label} Plan = management plan."
        ),
        "targetMonth": month,
        "targetLabel": f"{label} target" if label else "Target",
        "targetSource": t["label"] if t else None,
        "targetBasis": "Cumulative operational GP target (O&M KEY NUMBERS); progress = AMC GPs as of the cutoff ÷ target",
        "targetMonthMatches": month == want,
        "rows": rows,
    }


# ---------------------------------------------------------------- insights & validation


def _fmt(v: float | int | None) -> str:
    return "NA" if v is None else f"{v:,.0f}"


def _signed(v: float | None, unit: str = "") -> str:
    return "NA" if v is None else f"{'+' if v >= 0 else '−'}{abs(v):,.{1 if unit == 'pp' else 0}f}{' pp' if unit == 'pp' else ''}"


def _insights(p: ReportingPeriods, kpis: list[dict], conv: list[dict], table: dict, latest_amc: dt.date | None) -> list[dict[str, str]]:
    wk, pw = f"WK-{p.week.number}", f"WK-{p.compare.number}"
    out: list[dict[str, str]] = []
    k = {x["key"]: x for x in kpis}
    a, b, z = k["gpsAbove98"], k["blocksAbove98"], k["gpsAtZero"]
    out.append(
        {
            "kind": "observation",
            "text": f"{a['label']}: {_fmt(a['current'])} in {wk} vs {_fmt(a['previous'])} in {pw} ({_signed(a['delta'])}; {_signed(a['ppChange'], 'pp')} share of reporting GPs). "
            f"{b['label']}: {_fmt(b['current'])} vs {_fmt(b['previous'])} ({_signed(b['delta'])}).",
        }
    )
    worst = max(z["breakdown"], key=lambda x: x["delta"] or 0)
    out.append(
        {
            "kind": "observation",
            "text": f"GPs at 0% availability: {_fmt(z['current'])} in {wk} vs {_fmt(z['previous'])} in {pw} ({_signed(z['delta'])})"
            + (f"; largest increase in {worst['code']} ({_signed(worst['delta'])})." if (worst["delta"] or 0) > 0 else "."),
        }
    )
    moves = [(c, (c["week"]["amc"]["delta"] or 0) + (c["week"]["incremental"]["delta"] or 0)) for c in conv]
    c, d = max(moves, key=lambda x: abs(x[1]))
    total_w = sum((x["week"]["amc"]["current"] or 0) + (x["week"]["incremental"]["current"] or 0) for x in conv)
    total_pw = sum((x["week"]["amc"]["previous"] or 0) + (x["week"]["incremental"]["previous"] or 0) for x in conv)
    total_m = sum((x["month"]["amc"]["current"] or 0) + (x["month"]["incremental"]["current"] or 0) for x in conv)
    total_pm = sum((x["month"]["amc"]["previous"] or 0) + (x["month"]["incremental"]["previous"] or 0) for x in conv)
    out.append(
        {
            "kind": "observation",
            "text": f"GPs added to AMC (conversions + incremental): {_fmt(total_w)} in {wk} vs {_fmt(total_pw)} in {pw}; largest change in {c['name']} ({_signed(d)}). "
            f"Month: {_fmt(total_m)} in {window_label(*p.month)} vs {_fmt(total_pm)} in {window_label(*p.previous_month)}.",
        }
    )
    tot_t = [r["target"] for r in table["rows"]]
    if all(v is not None for v in tot_t) and tot_t:
        t, done = sum(tot_t), sum(r["amcGpsAsOfCutoff"] for r in table["rows"])
        text = f"{table['targetLabel']}: {_fmt(done)} of {_fmt(t)} operational GPs as of {p.cutoff:%d %b %Y} ({done / t * 100:.1f}%), gap {_fmt(max(0, t - done))}."
        month_end = (p.cutoff.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        days_left = (month_end - p.cutoff).days
        if t > done and days_left > 0 and table["targetMonthMatches"]:
            text += f" Required run-rate: about {(t - done) / days_left:,.0f} GPs/day for the remaining {days_left} days."
        out.append({"kind": "observation", "text": text})
    if latest_amc and latest_amc < p.cutoff:
        out.append({"kind": "data", "text": f"Latest AMC date in the file is {latest_amc:%d %b %Y}; no AMC conversion is recorded after it, so later periods show 0 as recorded in the source."})
    return out[:5]


def _checks(store: Store, p: ReportingPeriods, cur: dict, prev: dict, circles: list[dict], conv: list[dict]) -> list[dict[str, Any]]:
    """Validate aggregates against the underlying records before anything is rendered."""
    checks = []
    for key in ("gpsAbove98", "blocksAbove98", "gpsAtZero", "gpsReported"):
        ok = all(sum(d[x["id"]][key] for x in circles) == d["all"][key] for d in (cur, prev))
        checks.append({"name": f"Overall {key} = sum of circles", "ok": ok})
    # AMC conversions in the reporting week = change in the AMC GP count across that week (independent path).
    amc_np = store.gps["amc_np"]
    before = int((amc_np <= np.datetime64(p.week.start - dt.timedelta(days=1), "D")).sum())
    after = int((amc_np <= np.datetime64(p.week.end, "D")).sum())
    added = sum((c["week"]["amc"]["current"] or 0) + (c["week"]["incremental"]["current"] or 0) for c in conv)
    uncategorised = _conversions(store, np.ones(len(store.gps), dtype=bool), p.week.start, p.week.end)["uncategorised"]
    checks.append({"name": f"WK-{p.week.number}: conversions + incremental = change in AMC GP count", "ok": added + uncategorised == after - before})
    checks.append({"name": "Every AMC GP in the comparison periods has an AMC category", "ok": all(c["uncategorised"] == 0 for c in conv), "warningOnly": True})
    return checks


# ---------------------------------------------------------------- entry point


def executive_summary(store: Store, p: ReportingPeriods, circles: list[dict[str, Any]]) -> dict[str, Any]:
    """Page 1 payload. circles: [{id, code, name, key}] in display order."""
    scopes = [(c["id"], (store.gps["circle"] == c["key"]).to_numpy()) for c in circles] + [("all", np.ones(len(store.gps), dtype=bool))]
    cur = {sid: _week_availability(store, p.week, m) for sid, m in scopes}
    prev = {sid: _week_availability(store, p.compare, m) for sid, m in scopes}
    kpis = _kpi_cards(cur, prev, circles)
    conv = _conversion_cards(store, p, circles)
    table = _highlight_table(store, p, circles, conv)
    amc_dates = pd.to_datetime(store.gps["amc_date"], errors="coerce")
    latest_amc = amc_dates.max().date() if amc_dates.notna().any() else None
    checks = _checks(store, p, cur, prev, circles, conv)
    warnings = list(p.warnings)
    if not table["targetMonthMatches"] and table["targetMonth"]:
        warnings.append(f"No target for {p.cutoff:%b %Y} in the O&M sheet; showing the latest available target ({table['targetLabel']}).")
    if not table["targetMonth"]:
        warnings.append("No “Target for Operational GP” row in the O&M sheet – target column left blank.")
    return {
        "title": "Executive Summary",
        "kicker": "Management Governance Review",
        "subtitle": "Weekly Performance",
        "periods": p.as_json(),
        "latestAmcDate": latest_amc.isoformat() if latest_amc else None,
        "availability": {"current": cur["all"], "previous": prev["all"]},
        "kpis": kpis,
        "conversions": conv,
        "highlightTable": table,
        "insights": _insights(p, kpis, conv, table, latest_amc),
        "checks": checks,
        "valid": all(c["ok"] for c in checks if not c.get("warningOnly")),
        "warnings": warnings,
        "definitions": [
            "Availability = the source's weekly W-nn availability %; a GP counts only when under AMC by the week end; NA is never 0%.",
            "GPs / blocks > 98%: strictly above 98%; % = share of AMC GPs / blocks that reported a value that week.",
            "AMC conversion = existing GP with category “AMC” whose AMC date falls in the period; “Incremental” GPs are counted separately.",
            "Month comparison = day 1 to the cutoff day of the current month vs the same days of the previous month.",
        ],
    }
