"""Management Review – every figure of the web "Management Review" page and of the PPT deck.

One payload feeds both, so the screen and the downloaded deck can never disagree.

Period columns (same as the Circle Insights period table): the last four completed months
(the workbook's monthly AMC columns), the current month to date ("TD", daily data up to the
reporting date), the selected week ("Till W-nn") and the three weeks before it (weekly W-nn
columns). A GP counts in a column only when it is under AMC by the column's end; NA = under
AMC but no value in the source – never treated as 0%.

Sources besides the GP-wise data:
  * O&M "KEY NUMBERS"  – the Operational GP target per circle (Target page)
  * circle sheets       – One-Time-Up GPs (external report, cannot be derived from GP data)
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
import threading
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import CircleSheetValue
from .metrics import BANDS, band_counts, r2
from .reconcile import reconcile
from .review_periods import reporting_periods
from .review_summary import executive_summary, pick_target
from .review_targets import targets_page
from .review_critical import critical_table
from .store import Store, Week, circle_code, slug
from .views import _block_values, _period_values, _periods, _with_previous_td, week_json

RFP_SHARE = 0.75  # RFP: 75% of existing GPs under AMC by the 4th AMC month
BANDS_DESC = [b[0] for b in reversed(BANDS)]  # ">98%" first, like the O&M tables


# ---------------------------------------------------------------- source reference values


def _source_targets(store: Store, td_end: dt.date) -> tuple[dict[str, float], str | None, bool]:
    """O&M KEY NUMBERS "Target for Operational GP (<month> Target)" per circle (upper-case name) for the month of
    `td_end`, else the latest month available – the same pick as the Executive Summary (review_summary.pick_target).
    Returns (targets, label, month matches)."""
    want = f"{td_end:%Y-%m}"
    month, t = pick_target(store, want)
    if not t:
        return {}, None, False
    label = t["label"]  # "Target for Operational GP (Oct-26Target)"
    period = re.search(r"\(([^)]*?)\s*target\s*\)", label, re.I)
    return dict(t["values"]), (f"Operational GP target ({period.group(1)})" if period else label), month == want


_ONE_TIME_UP = {
    "one time up gps": ("oneTimeUpGps", "One-Time Up GPs"),
    "one time up amc": ("oneTimeUpAmc", "One-Time Up AMC"),
    "one time up non-amc": ("oneTimeUpNonAmc", "One-Time Up Non-AMC"),
}
_sheet_cache: dict[int, dict[str, dict[str, dict[str, float]]]] = {}
_sheet_lock = threading.Lock()


def _source_circle_kpis(store: Store) -> dict[str, dict[str, dict[str, float]]]:
    """One-Time-Up rows of the per-circle sheets ("Rajasthan", "Haryana", "Assam"), stored in the database at
    import (table circle_sheet_values): {CIRCLE: {metricKey: {periodKey: value}}}. Empty when the file had no
    such sheets. The workbook itself is never opened here."""
    with _sheet_lock:
        if store.dataset_id in _sheet_cache:
            return _sheet_cache[store.dataset_id]
    out: dict[str, dict[str, dict[str, float]]] = {}
    with SessionLocal() as db:
        for r in db.scalars(select(CircleSheetValue).where(CircleSheetValue.dataset_id == store.dataset_id)):
            out.setdefault(r.circle, {}).setdefault(r.metric, {})[r.period] = r.value
    with _sheet_lock:
        _sheet_cache[store.dataset_id] = out
    return out


# ---------------------------------------------------------------- period metrics


def _circle_list(store: Store) -> list[dict[str, Any]]:
    """Circles ordered by size (revised existing GPs), as in the review deck."""
    g = store.gps
    sizes = g[g["revised"]].groupby("circle").size().reindex(g["circle"].unique(), fill_value=0).sort_values(ascending=False)
    return [{"id": slug(c), "code": circle_code(c), "name": str(c).title(), "key": str(c)} for c in sizes.index]


class _Frame:
    """GP values of every period column for ALL GPs, computed once and sliced per scope."""

    def __init__(self, store: Store, periods: list[dict[str, Any]]):
        g = store.gps
        self.store = store
        self.periods = periods
        self.hoto_dt = pd.to_datetime(g["hoto_date"], errors="coerce")
        self.amc_dt = pd.to_datetime(g["amc_date"], errors="coerce")
        self.values = {p["key"]: _period_values(store, g, p) for p in periods}

    def metrics(self, mask: np.ndarray, p: dict[str, Any]) -> dict[str, Any]:
        s = get_settings()
        g = self.store.gps[mask]
        ts = pd.Timestamp(p["end"])
        hoto = (self.hoto_dt[mask] <= ts).to_numpy()
        amc = (self.amc_dt[mask] <= ts).to_numpy()
        vals = self.values[p["key"]][mask].where(amc)
        blocks = _block_values(g, vals, p["end"])
        gp_counts = band_counts(vals)
        blk_counts = band_counts(blocks)
        return {
            "totalBlocks": int(g["block_id"].nunique()),
            "revisedExisting": int(g["revised"].sum()),
            "existingGps": len(g),
            "totalRkm": r2(g["total_rkm"].sum()),
            "hotoBlocks": int(g.loc[hoto, "block_id"].nunique()),
            "hotoGps": int(hoto.sum()),
            "hotoRkm": r2(g.loc[hoto, "total_rkm"].sum()),
            "amcBlocks": int(g.loc[amc, "block_id"].nunique()),
            "amcGps": int(amc.sum()),
            "amcRkm": r2(g.loc[amc, "total_rkm"].sum()),
            "incrementalGps": int((amc & (g["amc_category"] == "INCREMENTAL").to_numpy()).sum()),
            "availability": r2(vals.mean()) if vals.notna().any() else None,
            "gpsAbove98": int((vals > s.healthy_threshold).sum()),
            "gpsAtZero": int((vals == 0).sum()),
            "gpsBelowPenalty": int((vals < s.penalty_threshold).sum()),
            "gpsReported": int(vals.notna().sum()),
            "naGps": int((amc & vals.isna().to_numpy()).sum()),
            "blocksAbove98": int((blocks > s.healthy_threshold).sum()),
            "penaltyBlocks": int((blocks < s.penalty_threshold).sum()),
            "blocksBelow85": int((blocks < 85).sum()),
            "blocksReported": int(blocks.notna().sum()),
            "blocksNa": int(blocks.isna().sum()),
            "blockAvailability": r2(blocks.mean()) if blocks.notna().any() else None,
            "gpBands": gp_counts,
            "blockBands": blk_counts,
        }


KPI_ROWS: list[tuple[str, str, str, str]] = [
    # key, label, unit, polarity
    ("amcGps", "AMC GPs (scope)", "count", "up"),
    ("gpsAbove98", "GPs > 98% availability", "count", "up"),
    ("gpsAtZero", "GPs at 0% availability", "count", "down"),
    ("gpsBelowPenalty", "GPs < 90% availability", "count", "down"),
    ("penaltyBlocks", "Blocks < 90% availability – penalty prone", "count", "down"),
    ("blocksBelow85", "Blocks < 85% availability", "count", "down"),
    ("blocksAbove98", "Blocks > 98% availability", "count", "up"),
    ("availability", "Average AMC GP availability", "percent", "up"),
    ("naGps", "AMC GPs not reported (NA)", "count", "down"),
    ("incrementalGps", "Incremental GPs under AMC", "count", "neutral"),
]


def _kpi_table(metrics: list[dict[str, Any]], periods: list[dict[str, Any]], one_time_up: dict[str, dict[str, float]] | None) -> list[dict[str, Any]]:
    rows = [{"key": k, "label": label, "unit": unit, "polarity": pol, "source": "computed", "values": [m[k] for m in metrics]} for k, label, unit, pol in KPI_ROWS]
    for key, label in _ONE_TIME_UP.values():
        series = (one_time_up or {}).get(key)
        if not series:
            continue
        vals = []
        for p in periods:
            k = p["key"]
            if p["kind"] == "mtd":
                k = f"{p['end'].year}-{p['end'].month:02d}"
            vals.append(series.get(k))
        rows.append({"key": key, "label": label, "unit": "count", "polarity": "up" if key != "oneTimeUpNonAmc" else "neutral", "source": "circle sheet", "values": vals})
    return rows


def _band_table(metrics: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """Uptime distribution table (rows = bands, best first) with Total / NA rows."""
    counts = "gpBands" if kind == "gp" else "blockBands"
    reported = "gpsReported" if kind == "gp" else "blocksReported"
    na = "naGps" if kind == "gp" else "blocksNa"
    pen = get_settings().penalty_threshold
    low = [lb for lb, lo, hi in BANDS if hi <= pen]
    return {
        "bands": [{"band": b, "values": [m[counts][b] for m in metrics]} for b in BANDS_DESC],
        "scope": [m["amcGps"] for m in metrics] if kind == "gp" else [m["blocksReported"] + m["blocksNa"] for m in metrics],
        "total": [m[reported] for m in metrics],
        "na": [m[na] for m in metrics],
        "belowPenalty": [sum(m[counts][b] for b in low) for m in metrics],
        "average": [m["availability"] if kind == "gp" else m["blockAvailability"] for m in metrics],
    }


def _change(cur: float | int | None, prev: float | int | None, polarity: str) -> dict[str, Any]:
    if cur is None or prev is None:
        return {"previous": prev, "current": cur, "delta": None, "trend": "na"}
    d = round(float(cur) - float(prev), 2)
    trend = "flat" if d == 0 else ("better" if (d > 0) == (polarity == "up") else "worse")
    if polarity == "neutral" and d != 0:
        trend = "up" if d > 0 else "down"
    return {"previous": prev, "current": cur, "delta": d, "trend": trend}


def _insight(prev_label: str, cur_label: str, prev: dict[str, Any], cur: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Week-on-week call-outs shown under every circle table ("WK-40 → WK-41: >98% GPs ▲ …")."""
    items = (
        [("gpsAbove98", ">98% GPs", "up"), ("gpsBelowPenalty", "<90% GPs", "down"), ("gpsAtZero", "0% GPs", "down")]
        if kind == "gp"
        else [("blocksAbove98", ">98% blocks", "up"), ("penaltyBlocks", "Blocks <90%", "down"), ("blockAvailability", "Avg block availability", "up")]
        if kind == "block"
        else [("gpsAbove98", ">98% GPs", "up"), ("penaltyBlocks", "Penalty-prone blocks", "down"), ("gpsAtZero", "0% GPs", "down")]
    )
    return [{"label": label, "from": prev_label, "to": cur_label, **_change(cur[k], prev[k], pol), "unit": "percent" if k == "blockAvailability" else "count"} for k, label, pol in items]


# ---------------------------------------------------------------- blocks & GPs detail


def _block_detail(store: Store, mask: np.ndarray, week: Week, compare: Week, td_end: dt.date, limit: int = 15) -> dict[str, Any]:
    s = get_settings()
    g = store.gps[mask]
    wf = store.week_frame(week.code).loc[g.index]
    wc = store.week_frame(compare.code).loc[g.index]
    amc = wf["amc"]
    mtd = store.mtd(td_end).loc[g.index].where(amc)
    wk = wf["weekly"].where(amc)
    pw = wc["weekly"].where(wc["amc"])
    by = g["block_id"]
    tbl = pd.DataFrame(
        {
            "mtd": mtd.groupby(by).mean(),
            "week": wk.groupby(by).mean(),
            "previous": pw.groupby(by).mean(),
            "amcGps": amc.groupby(by).sum(),
            "zero": (mtd == 0).groupby(by).sum(),
            "above98": (mtd > s.healthy_threshold).groupby(by).sum(),
        }
    )
    first = g.groupby("block_id").first()
    penalty = tbl[tbl["mtd"] < s.penalty_threshold].sort_values("mtd")
    blocks = [
        {
            "id": bid,
            "name": str(first.loc[bid, "block_name"]).title(),
            "districtName": str(first.loc[bid, "district"]).title(),
            "amName": first.loc[bid, "am_name"] if isinstance(first.loc[bid, "am_name"], str) else None,
            "amcGps": int(r["amcGps"]),
            "availability": r2(r["mtd"]),
            "weekAvailability": r2(r["week"]),
            "previousWeek": r2(r["previous"]),
            "gpsAtZero": int(r["zero"]),
        }
        for bid, r in penalty.head(limit).iterrows()
    ]
    districts = []
    for did, idx in g.groupby("district_id").groups.items():
        m = mtd.loc[idx]
        b = m.groupby(g.loc[idx, "block_id"]).mean()
        districts.append(
            {
                "id": did,
                "name": str(g.loc[idx, "district"].iloc[0]).title(),
                "blocks": int(g.loc[idx, "block_id"].nunique()),
                "amcGps": int(amc.loc[idx].sum()),
                "availability": r2(m.mean()) if m.notna().any() else None,
                "gpsAbove98": int((m > s.healthy_threshold).sum()),
                "gpsAtZero": int((m == 0).sum()),
                "penaltyBlocks": int((b < s.penalty_threshold).sum()),
            }
        )
    districts.sort(key=lambda d: (d["availability"] is None, d["availability"] if d["availability"] is not None else 0))
    return {"penaltyBlocks": blocks, "penaltyBlockCount": int(len(penalty)), "districts": districts}


# ---------------------------------------------------------------- targets


def _targets(store: Store, circles: list[dict[str, Any]], frame: _Frame, td: dict[str, Any], month_start: dt.date) -> dict[str, Any]:
    targets, label, month_matches = _source_targets(store, td["end"])
    g = store.gps
    amc_dt = frame.amc_dt
    month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])
    days_left = max(0, (month_end - td["end"]).days)
    rows = []
    for c in [*circles, None]:
        mask = (g["circle"] == c["key"]).to_numpy() if c else np.ones(len(g), dtype=bool)
        m = frame.metrics(mask, td)
        if c:
            target = targets.get(c["key"].upper())
        else:
            vals = [targets.get(x["key"].upper()) for x in circles]
            target = sum(vals) if vals and all(v is not None for v in vals) else None
        added = int(((amc_dt[mask] >= pd.Timestamp(month_start)) & (amc_dt[mask] <= pd.Timestamp(td["end"]))).sum())
        gap = None if target is None else max(0.0, target - m["amcGps"])
        rfp = round(m["existingGps"] * RFP_SHARE, 2)
        rows.append(
            {
                "id": c["id"] if c else "all",
                "name": c["name"] if c else "Overall",
                "code": c["code"] if c else "ALL",
                "revisedExisting": m["revisedExisting"],
                "existingGps": m["existingGps"],
                "hotoGps": m["hotoGps"],
                "amcGps": m["amcGps"],
                "amcPct": r2(m["amcGps"] / m["revisedExisting"] * 100) if m["revisedExisting"] else None,
                "target": target,
                "targetGap": r2(gap),
                "targetAchievedPct": r2(m["amcGps"] / target * 100) if target else None,
                "targetCoveragePct": r2(target / m["revisedExisting"] * 100) if target and m["revisedExisting"] else None,
                "requiredPerDay": r2(gap / days_left) if gap and days_left and month_matches else None,
                "addedThisMonth": added,
                "rfpTarget": rfp,
                "rfpGap": r2(max(0.0, rfp - m["amcGps"])),
                "rfpAchievedPct": r2(m["amcGps"] / rfp * 100) if rfp else None,
                "pendingConversion": m["revisedExisting"] - m["amcGps"],
            }
        )
    return {
        "label": label,
        "source": "O&M sheet – KEY NUMBERS" if targets else None,
        "monthEnd": month_end.isoformat(),
        "daysLeft": days_left,
        "rfpBasis": f"{RFP_SHARE:.0%} of existing GPs (RFP, 4th AMC month)",
        "rows": rows,
    }


def _ops_snapshot(store: Store, circles: list[dict[str, Any]], frame: _Frame, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scope | HOTO | AMC | Gap (scope − AMC) for blocks, GPs and fibre RKM at several dates."""
    g = store.gps
    out = []
    for p in points:
        per = []
        for c in circles:
            m = frame.metrics((g["circle"] == c["key"]).to_numpy(), p)
            per.append(
                {
                    "circleId": c["id"],
                    "code": c["code"],
                    "blocks": {"scope": m["totalBlocks"], "hoto": m["hotoBlocks"], "amc": m["amcBlocks"], "gap": m["totalBlocks"] - m["amcBlocks"]},
                    "gps": {"scope": m["revisedExisting"], "hoto": m["hotoGps"], "amc": m["amcGps"], "gap": m["revisedExisting"] - m["amcGps"]},
                    "rkm": {"scope": m["totalRkm"], "hoto": m["hotoRkm"], "amc": m["amcRkm"], "gap": r2(m["totalRkm"] - m["amcRkm"])},
                }
            )
        out.append({"label": p["label"], "endDate": p["end"].isoformat(), "circles": per})
    return out


# ---------------------------------------------------------------- entry point


def _breakdown(per_circle: dict[str, dict[str, Any]], circles: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [{"code": c["code"], "value": per_circle[c["id"]][key]} for c in circles]


def management_review(store: Store, week_code: str, compare_code: str, data_quality: list[dict[str, Any]]) -> dict[str, Any]:
    s = get_settings()
    g = store.gps
    week, compare = store.week(week_code), store.week(compare_code)
    # Months, previous month to the same day ("Sep-26 TD", same helper as the Insights pages), month TD, weeks.
    periods = _with_previous_td(store, _periods(store, g, week_code))
    # In the review both month-to-date columns read "MTD": "Sep-26 MTD" (1st .. same day of the previous month)
    # next to "Oct-26 MTD" – the wording of the client deck.
    periods = [{**p, "label": f"{p['end']:%b-%y} MTD"} if p["kind"] in ("mtd", "ptd") else p for p in periods]
    td = next(p for p in periods if p["kind"] == "mtd")
    months = [p for p in periods if p["kind"] == "month"]
    last_month = months[-1] if months else None
    cmp_period = {"key": compare.code, "label": f"WK-{compare.number}", "kind": "week", "end": compare.end}
    cur_period = next(p for p in periods if p["key"] == week.code)
    extra = [cmp_period] if compare.code not in {p["key"] for p in periods} else []
    frame = _Frame(store, periods + extra)
    circles = _circle_list(store)
    sheets = _source_circle_kpis(store)
    all_mask = np.ones(len(g), dtype=bool)

    scopes: list[tuple[dict[str, Any] | None, np.ndarray]] = [(c, (g["circle"] == c["key"]).to_numpy()) for c in circles] + [(None, all_mask)]
    sections: dict[str, dict[str, Any]] = {}
    td_by_scope: dict[str, dict[str, Any]] = {}
    month_by_scope: dict[str, dict[str, Any] | None] = {}
    for c, mask in scopes:
        sid = c["id"] if c else "all"
        metrics = [frame.metrics(mask, p) for p in periods]
        cur = metrics[periods.index(cur_period)]
        prev = frame.metrics(mask, cmp_period)
        td_m = metrics[periods.index(td)]
        td_by_scope[sid] = td_m
        month_by_scope[sid] = metrics[periods.index(last_month)] if last_month else None
        one_time_up = sheets.get(c["key"]) if c else None
        if c is None and sheets and all(x["key"] in sheets for x in circles):
            one_time_up = {}
            for key, _ in _ONE_TIME_UP.values():
                series = [sheets[x["key"]].get(key, {}) for x in circles]
                common = set.intersection(*(set(x) for x in series)) if series else set()
                one_time_up[key] = {k: sum(x[k] for x in series) for k in common}
        prev_label, cur_label = f"WK-{compare.number}", f"WK-{week.number}"
        sections[sid] = {
            "id": sid,
            "name": c["name"] if c else "All circles",
            "code": c["code"] if c else "ALL",
            "kpis": _kpi_table(metrics, periods, one_time_up),
            "weekChange": [
                {"key": k, "label": label, "unit": unit, "polarity": pol, **_change(cur[k], prev[k], pol)} for k, label, unit, pol in KPI_ROWS
            ],
            "gpUptime": _band_table(metrics, "gp"),
            "blockUptime": _band_table(metrics, "block"),
            "insights": {
                "kpi": _insight(prev_label, cur_label, prev, cur, "kpi"),
                "gp": _insight(prev_label, cur_label, prev, cur, "gp"),
                "block": _insight(prev_label, cur_label, prev, cur, "block"),
            },
            "detail": _block_detail(store, mask, week, compare, td["end"]) if c else None,
            # Page 3 – Critical KPI – Blocks & GPs (monthly & weekly performance table)
            "critical": critical_table(store, mask, c["name"] if c else "All circles", periods, metrics, one_time_up, cur, prev, cur_label, prev_label),
        }

    overall_td, overall_month = td_by_scope["all"], month_by_scope["all"]

    def tile(key: str, label: str, polarity: str, caption: str) -> dict[str, Any]:
        base = overall_month[key] if overall_month else None
        return {
            "key": key,
            "label": label,
            "caption": caption,
            "value": overall_td[key],
            "compareLabel": last_month["label"] if last_month else None,
            **{k: v for k, v in _change(overall_td[key], base, polarity).items() if k != "current"},
            "breakdown": _breakdown(td_by_scope, circles, key),
        }

    month_start = td["end"].replace(day=1)
    targets = _targets(store, circles, frame, td, month_start)
    tiles = [
        tile("gpsAbove98", "GPs > 98% availability", "up", f"AMC GPs, {td['label']}"),
        tile("blocksAbove98", "Blocks > 98% availability", "up", f"AMC blocks, {td['label']}"),
        tile("penaltyBlocks", "Penalty-prone blocks (< 90%)", "down", f"Block average, {td['label']}"),
        tile("gpsAtZero", "GPs at 0% availability", "down", f"AMC GPs, {td['label']}"),
    ]
    overall_target = targets["rows"][-1]
    ops_points = ([{**last_month, "label": f"{last_month['label']} close"}] if last_month else []) + [
        {**cmp_period, "label": f"WK-{compare.number}"},
        {**cur_period, "label": f"WK-{week.number} ({td['label']})"},
    ]
    rec = reconcile(store)
    rec_counts: dict[str, int] = {}
    for r in rec["rows"]:
        rec_counts[r["status"]] = rec_counts.get(r["status"], 0) + 1

    return {
        "title": "Management Review",
        "week": week_json(week),
        "compareWeek": week_json(compare),
        "dataAsOf": store.data_as_of.isoformat(),
        "asOf": td["end"].isoformat(),
        "sourceFile": store.file_name,
        "generatedAt": dt.datetime.now(dt.UTC).isoformat(),
        "thresholds": {"healthy": s.healthy_threshold, "penalty": s.penalty_threshold},
        "periods": [{"key": p["key"], "label": p["label"], "kind": p["kind"], "endDate": p["end"].isoformat()} for p in periods],
        "circles": [{k: c[k] for k in ("id", "code", "name")} for c in circles],
        "executive": {
            "scope": {
                "gps": {"scope": overall_td["revisedExisting"], "hoto": overall_td["hotoGps"], "amc": overall_td["amcGps"]},
                "blocks": {"scope": overall_td["totalBlocks"], "hoto": overall_td["hotoBlocks"], "amc": overall_td["amcBlocks"]},
                "rkm": {"scope": overall_td["totalRkm"], "hoto": overall_td["hotoRkm"], "amc": overall_td["amcRkm"]},
            },
            "availability": {
                "value": overall_td["availability"],
                "previous": overall_month["availability"] if overall_month else None,
                "compareLabel": last_month["label"] if last_month else None,
                "breakdown": _breakdown(td_by_scope, circles, "availability"),
            },
            "tiles": tiles,
            "highlights": _highlights(circles, td_by_scope, overall_month, last_month, td, overall_target, targets, sections),
        },
        # Page 1 (Executive Summary) – its own calculation module and reporting-period rules
        "summary": executive_summary(store, periods_p1 := reporting_periods(store, week, compare), circles),
        # Page 2 (Target & Achievement) – roadmap + weekly closure targets
        "targetsPage": targets_page(store, periods_p1, circles),
        "targets": targets,
        "operations": _ops_snapshot(store, circles, frame, ops_points),
        "sections": sections,
        "dataNotes": {
            "definitions": [
                f"GPs > {s.healthy_threshold:g}%: AMC GPs with availability strictly above {s.healthy_threshold:g}% (exactly {s.healthy_threshold:g}% falls in 95–98%).",
                f"Penalty-prone block: block whose mean AMC GP availability is below {s.penalty_threshold:g}% (O&M rule).",
                "NA: AMC GP with no availability value in the source – excluded from averages, never counted as 0%.",
                "Months use the workbook's monthly AMC columns; TD = month to date from daily data; weeks use the source's W-nn columns (Fri–Thu).",
                "A GP is counted in a column only when it is under AMC by the column's end date.",
                "One-Time-Up figures come from the circle sheets (external report) and cannot be derived from GP data.",
            ],
            "reconciliation": {"sourceMtdEnd": rec["sourceMtdEnd"], "counts": rec_counts, "rows": rec["rows"]},
            "dataQuality": data_quality,
        },
    }


def _fmt_n(v: float | int | None) -> str:
    return "NA" if v is None else f"{v:,.0f}"


def _highlights(circles, td_by, month, last_month, td, overall_target, targets, sections) -> list[str]:
    """Plain-language key points, generated from the same numbers shown in the tables."""
    s = get_settings()
    out = []
    o = td_by["all"]
    pct = f"{o['amcGps'] / o['revisedExisting'] * 100:.1f}%" if o["revisedExisting"] else "NA"
    out.append(f"AMC coverage: {_fmt_n(o['amcGps'])} of {_fmt_n(o['revisedExisting'])} revised GPs ({pct}); {_fmt_n(o['revisedExisting'] - o['amcGps'])} GPs still to convert.")
    if overall_target["target"]:
        line = f"{targets['label'] or 'Operational GP target'}: {_fmt_n(overall_target['target'])} GPs – {overall_target['targetAchievedPct']:.1f}% achieved, gap {_fmt_n(overall_target['targetGap'])}"
        if overall_target["requiredPerDay"]:
            line += f" (≈{overall_target['requiredPerDay']:.0f} GPs/day for the remaining {targets['daysLeft']} days)"
        out.append(line + ".")
    if o["availability"] is not None:
        line = f"Average AMC GP availability {td['label']}: {o['availability']:.2f}%"
        if month and month["availability"] is not None:
            d = o["availability"] - month["availability"]
            line += f" ({'+' if d >= 0 else '−'}{abs(d):.2f} pp vs {last_month['label']})"
        out.append(line + f"; {_fmt_n(o['gpsAbove98'])} GPs above {s.healthy_threshold:g}%.")
    worst = max(circles, key=lambda c: td_by[c["id"]]["penaltyBlocks"])
    out.append(
        f"Penalty-prone blocks (< {s.penalty_threshold:g}%): {_fmt_n(o['penaltyBlocks'])} – highest in {worst['name']} "
        f"({td_by[worst['id']]['penaltyBlocks']} of {td_by[worst['id']]['blocksReported']} reporting blocks)."
    )
    zero = max(circles, key=lambda c: td_by[c["id"]]["gpsAtZero"])
    if o["gpsAtZero"]:
        out.append(f"{_fmt_n(o['gpsAtZero'])} AMC GPs at 0% {td['label']}; {zero['name']} accounts for {td_by[zero['id']]['gpsAtZero']}.")
    if o["naGps"]:
        out.append(f"{_fmt_n(o['naGps'])} AMC GPs did not report availability (NA) and are excluded from averages.")
    return out
