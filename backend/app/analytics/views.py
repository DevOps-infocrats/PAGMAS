"""Build API payloads (camelCase dicts matching frontend/src/lib/api/contracts.ts)."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np
import pandas as pd

from ..config import get_settings
from .metrics import BANDS, band_counts, band_of, r2, summarize
from .store import Store, Week, circle_code, slug

OVERVIEW_KPIS = [
    "totalGps", "amcPct", "gpsAbove98", "penaltyBlocks",
    "totalStates", "totalBlocks", "revisedExisting", "hotoDoneBlocks", "hotoDoneGps",
    "amcGps", "gpsAtZero", "oneTimeUp", "incrementalGps", "amcRkm", "availability",
    "availabilityWeek", "gpsAbove98Week", "penaltyBlocksWeek",
]
CIRCLE_KPIS = ["revisedExisting", "hotoDoneGps", "amcGps", "availability", "totalDistricts", "totalBlocks", "totalRkm", "penaltyBlocks", "amcRkm", "availabilityWeek", "gpsAbove98Week", "penaltyBlocksWeek"]
BLOCK_KPIS = ["revisedExisting", "totalRkm", "hotoDoneGps", "amcGps", "bsnlRkm", "bbnlRkm", "hotoPendingGps", "nonAmcGps", "availability", "gpsAbove98", "availabilityWeek"]


class NotFound(Exception):
    pass


def clean(v: Any) -> Any:
    """NaN/NaT -> None, numpy scalars -> python, dates -> ISO."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.generic):
        return clean(v.item())
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if v is pd.NaT:
        return None
    return v


def week_json(w: Week) -> dict[str, Any]:
    return {"id": w.code, "number": w.number, "year": w.end.year, "label": f"Week {w.number}", "startDate": w.start.isoformat(), "endDate": w.end.isoformat()}


def history_weeks(store: Store, week_code: str) -> list[Week]:
    """The weeks up to and including `week_code`, in date order (week numbers wrap at the year end)."""
    return store.weeks[: store.week_index(week_code) + 1]


def kpis(store: Store, mask: Any, week: str, compare: str, keys: list[str]) -> list[dict[str, Any]]:
    cur = summarize(store, mask, week)
    prev = summarize(store, mask, compare)
    hist = [summarize(store, mask, w.code) for w in history_weeks(store, week)]
    return [{"key": k, "value": cur[k], "previous": prev[k], "history": [h[k] for h in hist]} for k in keys]


# ---------------------------------------------------------------- meta / lookups


def meta(store: Store) -> dict[str, Any]:
    g = store.gps
    s = get_settings()
    circles = sorted(g["circle"].unique())
    districts = g.drop_duplicates("district_id")[["district_id", "circle_id", "district"]].sort_values("district")
    blocks = g.drop_duplicates("block_id")[["block_id", "block_name", "block_code", "circle_id", "district_id"]].sort_values("block_name")
    return {
        "weeks": [week_json(w) for w in store.weeks],
        "latestWeekId": store.latest_week.code,
        "dataAsOf": store.data_as_of.isoformat(),
        "datasetFileName": store.file_name,
        "importedAt": clean(store.imported_at),
        "thresholds": {"healthy": s.healthy_threshold, "penalty": s.penalty_threshold},
        "circles": [{"id": slug(c), "code": circle_code(c), "name": c.title()} for c in circles],
        "districts": [{"id": r.district_id, "circleId": r.circle_id, "name": r.district.title()} for r in districts.itertuples()],
        "blocks": [
            {"id": r.block_id, "name": r.block_name.title(), "code": r.block_code, "circleId": r.circle_id, "districtId": r.district_id}
            for r in blocks.itertuples()
        ],
    }


def _circle_summary(store: Store, cid: str, week: str) -> dict[str, Any]:
    g = store.gps
    mask = (g["circle_id"] == cid).to_numpy()
    s = summarize(store, mask, week)
    name = g.loc[mask, "circle"].iloc[0]
    return {
        "id": cid,
        "name": name.title(),
        "code": circle_code(name),
        "districts": s["totalDistricts"],
        "blocks": s["totalBlocks"],
        "totalGps": s["totalGps"],
        "revisedExisting": s["revisedExisting"],
        "hotoDoneBlocks": s["hotoDoneBlocks"],
        "hotoDoneGps": s["hotoDoneGps"],
        "amcGps": s["amcGps"],
        "amcPct": s["amcPct"],
        "availability": s["availability"],
        "gpsAbove98": s["gpsAbove98"],
        "gpsAtZero": s["gpsAtZero"],
        "naGps": s["naGps"],
        "penaltyBlocks": s["penaltyBlocks"],
        "incrementalGps": s["incrementalGps"],
        "convertedNp": s["convertedNp"],
        "permanentlyClosed": s["permanentlyClosed"],
        "deductedGps": s["deductedGps"],
        "bsnlRkm": s["bsnlRkm"],
        "bbnlRkm": s["bbnlRkm"],
        "amcRkm": s["amcRkm"],
        "oneTimeUp": s["oneTimeUp"],
    }


def _new_gps(store: Store, circle: str | None = None) -> dict[str, int] | None:
    """New GPs come only from the Master Block sheet (not listed GP-wise)."""
    mb = store.master_blocks
    if mb.empty:
        return None
    if circle:
        mb = mb[mb["state"] == circle]
    return {"newGps": int(mb["new_gps"].fillna(0).sum()), "masterTotalGps": int(mb["total_gp_count"].fillna(0).sum())}


def _detail(store: Store, mask: np.ndarray | None, week: str, circle: str | None = None) -> dict[str, Any]:
    """Every figure shown on the Circle Overview, computed with the shared metric rules."""
    s = summarize(store, mask, week)
    extra = _new_gps(store, circle)
    new = extra["newGps"] if extra else None
    return {
        "states": s["totalStates"],
        "blocks": s["totalBlocks"],
        "existingGps": s["totalGps"],
        "newGps": new,
        "totalGps": s["totalGps"] + new if new is not None else None,
        "revisedExisting": s["revisedExisting"],
        "convertedOrClosed": s["convertedNp"] + s["permanentlyClosed"] + s["deductedGps"],
        "convertedNp": s["convertedNp"],
        "permanentlyClosed": s["permanentlyClosed"],
        "deductedGps": s["deductedGps"],
        "hotoDoneBlocks": s["hotoDoneBlocks"],
        "hotoPendingBlocks": s["totalBlocks"] - s["hotoDoneBlocks"],
        "hotoDoneGps": s["hotoDoneGps"],
        "hotoPendingGps": s["hotoPendingGps"],
        "amcAtHotoGps": s["amcAtHotoGps"],
        "amcGps": s["amcGps"],
        "amcOriginalGps": s["amcOriginalGps"],
        "incrementalGps": s["incrementalGps"],
        "nonAmcGps": s["nonAmcGps"],
        "amcPct": s["amcPct"],
        "availability": s["availability"],
        "gpsAbove98": s["gpsAbove98"],
        "gpsAtZero": s["gpsAtZero"],
        "naGps": s["naGps"],
        "penaltyBlocks": s["penaltyBlocks"],
        "gpsBelowPenalty": s["gpsBelowPenalty"],
        "blocksAbove98": s["blocksAbove98"],
        "reportingGps": s["reportingGps"],
        "reportingBlocks": s["reportingBlocks"],
        "oneTimeUp": s["oneTimeUp"],
        "totalRkm": s["totalRkm"],
        "bsnlRkm": s["bsnlRkm"],
        "bbnlRkm": s["bbnlRkm"],
        "amcRkm": s["amcRkm"],
        "rkmPartsDifference": r2(s["bsnlRkm"] + s["bbnlRkm"] - s["totalRkm"]),
    }


def overview(store: Store, week: str, compare: str) -> dict[str, Any]:
    g = store.gps
    cids = sorted(g["circle_id"].unique())
    wf = store.week_frame(week)
    mtd = wf["mtd"].where(wf["amc"])
    am = g["am_name"].fillna("Unassigned")
    managers = []
    for (cid, name), idx in g.groupby([g["circle_id"], am]).groups.items():
        sub_mtd = mtd.loc[idx]
        blocks = sub_mtd.groupby(g.loc[idx, "block_id"]).mean()
        managers.append(
            {
                "circleId": cid,
                "manager": {"id": f"{cid}~{slug(name)}", "circleId": cid, "label": name},
                "gps": len(idx),
                "amcGps": int(wf.loc[idx, "amc"].sum()),
                "availability": r2(sub_mtd.mean()) if sub_mtd.notna().any() else None,
                "gpsAbove98": int((sub_mtd > get_settings().healthy_threshold).sum()),
                "gpsAtZero": int((sub_mtd == 0).sum()),
                "penaltyBlocks": int((blocks < get_settings().penalty_threshold).sum()),
                "blocks": int(g.loc[idx, "block_id"].nunique()),
                "revisedExisting": int(g.loc[idx, "revised"].sum()),
            }
        )
    return {
        "weeks": [week_json(w) for w in history_weeks(store, week)],
        "kpis": kpis(store, None, week, compare, OVERVIEW_KPIS),
        "circles": [_circle_summary(store, c, week) for c in cids],
        "circlesPrevious": [_circle_summary(store, c, compare) for c in cids],
        "areaManagers": sorted(managers, key=lambda m: (m["circleId"], m["availability"] is None, -(m["availability"] or 0))),
        "summary": _detail(store, None, week),
        "stateDetails": [
            {"id": c, "name": g.loc[g["circle_id"] == c, "circle"].iloc[0].title(), **_detail(store, (g["circle_id"] == c).to_numpy(), week, g.loc[g["circle_id"] == c, "circle"].iloc[0])}
            for c in cids
        ],
        "asOf": min(store.week(week).end, store.data_as_of).isoformat(),
    }


# ---------------------------------------------------------------- circle


def _new_gps_by_block(store: Store) -> dict[str, int]:
    mb = store.master_blocks
    if mb.empty:
        return {}
    return {str(k): int(v) for k, v in zip(mb["block_code"], mb["new_gps"].fillna(0))}


def _block_rows(store: Store, mask: np.ndarray, week: str) -> list[dict[str, Any]]:
    g = store.gps[mask]
    wf = store.week_frame(week).loc[g.index]
    mtd = wf["mtd"].where(wf["amc"])
    new_by_block = _new_gps_by_block(store)
    out = []
    for bid, idx in g.groupby("block_id").groups.items():
        sub = g.loc[idx]
        w = wf.loc[idx]
        m = mtd.loc[idx]
        first = sub.iloc[0]
        out.append(
            {
                "id": bid,
                "name": first["block_name"].title(),
                "code": first["block_code"],
                "districtId": first["district_id"],
                "districtName": first["district"].title(),
                "totalGps": len(sub),
                "existingGps": len(sub),
                "newGps": new_by_block.get(str(first["block_code"])),
                "revisedExisting": int(sub["revised"].sum()),
                "hotoDone": int(w["hoto_done"].sum()),
                "hotoPending": int((sub["revised"] & ~w["hoto_done"]).sum()),
                "amcGps": int(w["amc"].sum()),
                # AMC split – same masks as metrics.summarize (amcOriginalGps / incrementalGps / nonAmcGps)
                "amcOriginalGps": int((w["amc"] & (sub["amc_category"] != "INCREMENTAL")).sum()),
                "incrementalGps": int((w["amc"] & (sub["amc_category"] == "INCREMENTAL")).sum()),
                "nonAmcGps": int((sub["revised"] & ~w["amc"]).sum()),
                "availability": r2(m.mean()) if m.notna().any() else None,
                "totalRkm": r2(sub["total_rkm"].sum()),
            }
        )
    return out


def _band_series(store: Store, mask: np.ndarray, weeks: list[Week], per_block: bool) -> tuple[list[dict], list[dict]]:
    """Weekly band counts (source weekly columns) for GPs or blocks."""
    g = store.gps[mask]
    table = []
    for w in weeks:
        vals = store.week_frame(w.code).loc[g.index, "weekly"]
        if per_block:
            vals = vals.groupby(g["block_id"]).mean()
        counts = band_counts(vals)
        counts["NA"] = int(vals.isna().sum()) if per_block else int((store.week_frame(w.code).loc[g.index, "amc"] & vals.isna()).sum())
        table.append(
            {
                "weekId": w.code,
                "date": w.end.isoformat(),
                "label": f"W-{w.number}",
                "counts": counts,
                "reported": int(vals.notna().sum()),
                "average": r2(vals.mean()) if vals.notna().any() else None,
            }
        )
    healthy, penalty = get_settings().healthy_threshold, get_settings().penalty_threshold

    def grouped(name: str, labels: list[str]) -> dict:
        return {"name": name, "points": [{"weekId": t["weekId"], "date": t["date"], "value": sum(t["counts"][lb] for lb in labels)} for t in table]}

    labels = [b[0] for b in BANDS]
    above = [lb for lb, lo, _ in BANDS if lo >= healthy]
    mid = [lb for lb, lo, hi in BANDS if lo >= penalty and hi <= healthy and lo != hi]
    # GPs: 0% is its own series; blocks have no 0% series, so a 0% block belongs to "<90%" (as in review._band_table).
    low = [lb for lb, lo, hi in BANDS if hi <= penalty and (per_block or lb != "0%")]
    series = [grouped(f">{healthy:g}%", above), grouped(f"{penalty:g}–{healthy:g}%", mid), grouped(f"<{penalty:g}%", low)]
    if not per_block:
        series.append(grouped("0%", ["0%"]))
    del labels
    return series, table


def circle_insights(store: Store, cid: str, week: str, compare: str) -> dict[str, Any]:
    g = store.gps
    mask = (g["circle_id"] == cid).to_numpy()
    if not mask.any():
        raise NotFound(f"Circle {cid} not found")
    name = g.loc[mask, "circle"].iloc[0]
    wf = store.week_frame(week)
    sub = g[mask]
    new_by_block = _new_gps_by_block(store)
    hoto_amc = []
    for did, idx in sub.groupby("district_id").groups.items():
        d = sub.loc[idx]
        w = wf.loc[idx]
        amc = int(w["amc"].sum())
        inc = int((w["amc"] & (d["amc_category"] == "INCREMENTAL")).sum())
        blocks = d["block_code"].astype(str).unique()
        hoto_by_block = w["hoto_done"].groupby(d["block_id"]).any()
        hoto_amc.append(
            {
                "districtId": did,
                "districtName": d["district"].iloc[0].title(),
                "blocks": len(blocks),
                "hotoDoneBlocks": int(hoto_by_block.sum()),
                "existingGps": len(d),
                "newGps": sum(new_by_block.get(b, 0) for b in blocks) if new_by_block else None,
                "applicable": int(d["revised"].sum()),
                "hotoDone": int(w["hoto_done"].sum()),
                "hotoPending": int((d["revised"] & ~w["hoto_done"]).sum()),
                "amc": amc,
                "amcOriginal": amc - inc,
                "incremental": inc,
                "nonAmc": int((d["revised"] & ~w["amc"]).sum()),
            }
        )
    weeks = history_weeks(store, week)
    gp_series, gp_table = _band_series(store, mask, weeks, per_block=False)
    blk_series, blk_table = _band_series(store, mask, weeks, per_block=True)
    return {
        "circle": {"id": cid, "code": circle_code(name), "name": name.title()},
        "weeks": [week_json(w) for w in weeks],
        "kpis": kpis(store, mask, week, compare, CIRCLE_KPIS),
        "blocks": _block_rows(store, mask, week),
        "hotoAmc": sorted(hoto_amc, key=lambda r: r["districtName"]),
        "gpUptimeTrend": gp_series,
        "blockUptimeTrend": blk_series,
        "gpBandTable": gp_table,
        "blockBandTable": blk_table,
        "periodTable": _period_table(store, mask, week),
        "gpDailyBands": _daily_bands(store, mask, week, per_block=False),
        "blockDailyBands": _daily_bands(store, mask, week, per_block=True),
        "bands": [b[0] for b in BANDS],
        "summary": {**_detail(store, mask, week, name), "districts": int(sub["district_id"].nunique())},
        "asOf": min(store.week(week).end, store.data_as_of).isoformat(),
        "currentWeek": week_json(store.week(week)),
    }


def _daily_bands(store: Store, mask: np.ndarray, week: str, per_block: bool) -> list[dict[str, Any]]:
    """Day-by-day availability bands for the days of `week` that have data.

    A GP counts on a day when it is under AMC on that day (AMC date <= day),
    matching how the workbook starts AMC availability from the AMC date.
    Block value = mean of its AMC GPs' daily values (blocks without any are NA).
    """
    g = store.gps[mask]
    w = store.week(week)
    days = [d for d in store.daily.columns if w.start <= d <= min(w.end, store.data_as_of)]
    amc_dates = pd.to_datetime(g["amc_date"], errors="coerce")
    out = []
    for day in days:
        under_amc = (amc_dates <= pd.Timestamp(day)).to_numpy()
        vals = store.daily.loc[g.index, day].where(under_amc)
        if per_block:
            vals = _block_values(g, vals, day)
            na = int(vals.isna().sum())
        else:
            na = int((under_amc & vals.isna().to_numpy()).sum())
        counts = band_counts(vals)
        counts["NA"] = na
        out.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%a %d %b"),
                "counts": counts,
                "reported": int(vals.notna().sum()),
                "average": r2(vals.mean()) if vals.notna().any() else None,
            }
        )
    return out


# ---------------------------------------------------------------- GP snapshot / block


def _hoto_status(row: pd.Series, hoto_done: bool) -> str:
    if row["lifecycle"] != "ACTIVE":
        return "NOT_APPLICABLE"
    return "DONE" if hoto_done else "PENDING"


def _recorded(v: Any) -> str | None:
    """Source text, or None when it is blank or a placeholder such as "Not Available" / "NA"."""
    v = clean(v)
    if not isinstance(v, str):
        return v
    v = v.strip()
    return None if v.upper() in ("", "-", "NA", "N/A", "NOT AVAILABLE") else v


def _olt_location(v: Any) -> str | None:
    """OLT location text, or None when the source leaves it blank / "-" / "NA"."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    return None if v.strip("-– ").upper() in ("", "NA", "N/A") else v


def gp_snapshots(store: Store, mask: np.ndarray, week: str) -> list[dict[str, Any]]:
    g = store.gps[mask]
    wf = store.week_frame(week).loc[g.index]
    out = []
    for code, row in g.iterrows():
        w = wf.loc[code]
        amc = bool(w["amc"])
        olt = _olt_location(row["olt_location"])
        out.append(
            {
                "id": code,
                "lgdCode": code,
                "locationCode": clean(row["location_code"]),
                "name": str(row["name"]).title(),
                "circleId": row["circle_id"],
                "circleName": row["circle"].title(),
                "districtId": row["district_id"],
                "districtName": row["district"].title(),
                "blockId": row["block_id"],
                "blockName": row["block_name"].title(),
                "classification": "INCREMENTAL" if row["amc_category"] == "INCREMENTAL" else "EXISTING",
                "amcCategory": clean(row["amc_category"]),
                "lifecycle": row["lifecycle"],
                "hotoStatus": _hoto_status(row, bool(w["hoto_done"])),
                "hotoDate": clean(row["hoto_date"]) if bool(w["hoto_done"]) else None,
                "amcStatus": "AMC" if amc else "NON_AMC",
                "amcStartDate": clean(row["amc_date"]) if amc else None,
                "amcEndDate": None,
                "bsnlRkm": r2(row["bsnl_km"]),
                "bbnlRkm": r2(row["bbnl_km"]),
                "totalRkm": r2(row["total_rkm"]) or 0.0,
                "availability": r2(w["mtd"]) if amc else None,
                "weeklyAvailability": r2(w["weekly"]) if amc else None,
                "oltId": f"{row['block_id']}~{slug(olt)}" if olt else None,
                "oltLocation": olt.title() if olt else None,
                "phase": _recorded(row["phase"]),
                "lot": _recorded(row["lot"]),
            }
        )
    return out


def block_insights(store: Store, block_id: str, week: str, compare: str) -> dict[str, Any]:
    g = store.gps
    mask = (g["block_id"] == block_id).to_numpy()
    if not mask.any():
        raise NotFound(f"Block {block_id} not found")
    sub = g[mask]
    first = sub.iloc[0]
    weeks = history_weeks(store, week)
    snaps = gp_snapshots(store, mask, week)
    olts: dict[str, dict] = {}
    for s in snaps:
        if s["oltId"]:
            o = olts.setdefault(s["oltId"], {"id": s["oltId"], "blockId": block_id, "location": s["oltLocation"], "ponPorts": None, "gpCount": 0})
            o["gpCount"] += 1
    trend = []
    for w in weeks:
        vals = store.week_frame(w.code).loc[sub.index, "weekly"]
        trend.append({"weekId": w.code, "date": w.end.isoformat(), "value": r2(vals.mean()) if vals.notna().any() else None})
    wf = store.week_frame(week).loc[sub.index]
    amc = wf["amc"]
    cats = [
        {"label": "AMC (original)", "count": int((amc & (sub["amc_category"] != "INCREMENTAL")).sum())},
        {"label": "Incremental", "count": int((amc & (sub["amc_category"] == "INCREMENTAL")).sum())},
        {"label": "Non-AMC", "count": int((sub["revised"] & ~amc).sum())},
        {"label": "Converted / closed", "count": int((~sub["revised"]).sum())},
    ]
    inc = []
    for w in weeks:
        d = sub["amc_date"]
        inc.append(
            {
                "weekId": w.code,
                "date": w.end.isoformat(),
                "added": int(sum(1 for a, c in zip(d, sub["amc_category"]) if isinstance(a, dt.date) and c == "INCREMENTAL" and w.start <= a <= w.end)),
            }
        )
    cname = first["circle"]
    return {
        "circle": {"id": first["circle_id"], "code": circle_code(cname), "name": cname.title()},
        "district": {"id": first["district_id"], "circleId": first["circle_id"], "name": first["district"].title()},
        "block": {"id": block_id, "code": first["block_code"], "circleId": first["circle_id"], "districtId": first["district_id"], "name": first["block_name"].title(), "oltIds": list(olts)},
        "weeks": [week_json(w) for w in weeks],
        "kpis": kpis(store, mask, week, compare, BLOCK_KPIS),
        "gps": snaps,
        "olts": sorted(olts.values(), key=lambda o: -o["gpCount"]),
        "uptimeTrend": [{"name": "Average weekly availability (AMC GPs)", "points": trend}],
        "classification": cats,
        "incrementalByWeek": inc,
        "summary": _block_summary(store, mask, week, str(first["block_code"])),
        "gpUptime": _gp_uptime(store, mask, week),
        "amcGroups": _amc_groups(sub, wf),
        "asOf": min(store.week(week).end, store.data_as_of).isoformat(),
    }


def _amc_groups(g: pd.DataFrame, wf: pd.DataFrame) -> dict[str, list[str]]:
    """GP codes behind the AMC KPI, with the exact masks of metrics.summarize:
    AMC (original) = AMC & not incremental, Incremental = AMC & incremental, Non-AMC = revised & not AMC."""
    amc = wf["amc"].astype(bool)
    inc = g["amc_category"] == "INCREMENTAL"
    return {
        "amc": list(g.index[amc & ~inc]),
        "incremental": list(g.index[amc & inc]),
        "nonAmc": list(g.index[g["revised"] & ~amc]),
    }


def _block_summary(store: Store, mask: np.ndarray, week: str, block_code: str) -> dict[str, Any]:
    """Block KPIs with the same rules as the circle; new GPs come from the Master Block row."""
    d = _detail(store, mask, week)
    new = _new_gps_by_block(store).get(block_code)
    d["newGps"] = new
    d["totalGps"] = d["existingGps"] + new if new is not None else d["existingGps"]
    return d


def _gp_uptime(store: Store, mask: np.ndarray, week: str) -> dict[str, Any]:
    """GP-wise availability of one block for every period column and each day of the week.

    A GP has a value in a column only when it is under AMC by the column's end (AMC date <= end);
    otherwise it is "not under AMC". NA = under AMC but no value in the source (never 0).
    Block value = mean of its AMC GPs' values (same rule as the circle's block uptime tables).
    """
    g = store.gps[mask]
    amc_dt = pd.to_datetime(g["amc_date"], errors="coerce")
    cols: list[dict[str, Any]] = []
    values: dict[str, pd.Series] = {}
    for p in _with_previous_td(store, _periods(store, g, week)):
        amc = (amc_dt <= pd.Timestamp(p["end"])).to_numpy()
        values[p["key"]] = _period_values(store, g, p).where(amc)
        cols.append({"key": p["key"], "label": p["label"], "kind": p["kind"], "endDate": p["end"].isoformat(), "amc": amc})
    w = store.week(week)
    for day in [d for d in store.daily.columns if w.start <= d <= min(w.end, store.data_as_of)]:
        amc = (amc_dt <= pd.Timestamp(day)).to_numpy()
        key = day.isoformat()
        values[key] = store.daily.loc[g.index, day].where(amc)
        cols.append({"key": key, "label": day.strftime("%a %d %b"), "kind": "day", "endDate": key, "amc": amc})

    columns = []
    for c in cols:
        v = values[c["key"]]
        amc = c.pop("amc")
        columns.append(
            {
                **c,
                "amcGps": int(amc.sum()),
                "reported": int(v.notna().sum()),
                "na": int((amc & v.isna().to_numpy()).sum()),
                "average": r2(v.mean()) if v.notna().any() else None,
                "counts": band_counts(v),
                "amcFlags": [bool(x) for x in amc],
            }
        )
    rows = []
    for i, (code, row) in enumerate(g.iterrows()):
        rows.append(
            {
                "id": code,
                "name": str(row["name"]).title(),
                "amcDate": clean(row["amc_date"]),
                "amcCategory": clean(row["amc_category"]),
                "values": [None if not col["amcFlags"][i] else ("NA" if pd.isna(values[col["key"]].iloc[i]) else r2(values[col["key"]].iloc[i])) for col in columns],
            }
        )
    for col in columns:
        col.pop("amcFlags")
    s = get_settings()
    return {
        "columns": columns,
        "rows": sorted(rows, key=lambda r: r["name"]),
        "bands": [b[0] for b in BANDS],
        "thresholds": {"healthy": s.healthy_threshold, "penalty": s.penalty_threshold},
    }


def gp_detail(store: Store, gp_code: str, week: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    if gp_code not in store.gps.index:
        raise NotFound(f"GP {gp_code} not found")
    mask = (store.gps.index == gp_code)
    snap = gp_snapshots(store, mask, week)[0]
    row = store.gps.loc[gp_code]
    w = store.week(week)
    weekly = store.weekly.loc[gp_code] if gp_code in store.weekly.index else pd.Series(dtype=float)
    weeks = history_weeks(store, week)
    amc_date = row["amc_date"] if isinstance(row["amc_date"], dt.date) else None
    weekly_hist = [{"weekId": x.code, "date": x.end.isoformat(), "value": r2(weekly.get(x.code))} for x in weeks if amc_date and amc_date <= x.end]
    daily = store.daily.loc[gp_code]
    daily_hist = [{"date": d.isoformat(), "value": r2(v)} for d, v in daily.items() if d <= min(w.end, store.data_as_of)]
    monthly = [{"month": m, "value": r2(v), "amcValue": r2(store.monthly_amc.loc[gp_code].get(m)) if m in store.monthly_amc.columns else None} for m, v in store.monthly.loc[gp_code].items()]
    events = []
    for label, d in (("HOTO completed", row["hoto_date"]), ("AMC coverage started", row["amc_date"]), ("AMC / incremental letter submitted", row["letter_date"]), ("LMS / AMC date recorded", row["lms_amc_date"])):
        if isinstance(d, dt.date) and d <= w.end:
            events.append({"date": d.isoformat(), "event": label})
    if row["lifecycle"] != "ACTIVE":
        events.append({"date": None, "event": f"Status: {row['np_status']} (date not recorded in source)"})
    na_weeks = [x for x in weekly_hist if x["value"] is None]
    for x in na_weeks:
        issues.append({"code": "NA_WEEK", "message": "Weekly availability not reported (NA)", "weekId": x["weekId"], "severity": "warning"})
    return {
        "gp": {**snap, "amName": clean(row["am_name"]), "ba": clean(row["ba"]), "gpType": clean(row["gp_type"])},
        "week": week_json(w),
        "availabilityHistory": weekly_hist or None,
        "dailyHistory": daily_hist if amc_date or any(p["value"] is not None for p in daily_hist) else None,
        "monthlyHistory": monthly,
        "hotoHistory": sorted(events, key=lambda e: e["date"] or "9999"),
        "olt": {"id": snap["oltId"], "blockId": snap["blockId"], "location": snap["oltLocation"], "ponPorts": None} if snap["oltId"] else None,
        "addedWeek": None,
        "revisedExisting": bool(row["revised"]),
        "issues": issues,
        "dataAsOf": store.data_as_of.isoformat(),
        "uptime": _gp_uptime_single(store, gp_code, week),
    }


def _gp_uptime_single(store: Store, gp_code: str, week: str) -> dict[str, Any]:
    """One GP's uptime per period column (months, TD, weeks, days of the week).

    For every column:
      * value / band   – the period's official availability (monthly AMC column, month to date,
                         weekly W-nn column or the day's value), via _gp_uptime;
      * days           – how many days the GP spent in each availability band in that period,
                         counted from the daily sheet over the days it was under AMC (AMC date ..
                         period end, capped at the data date). None when the daily sheet does not
                         cover the whole period (it starts later), so partial counts are never shown.
      * blockAverage   – the block's value for the same column (mean of its AMC GPs).
    value: number, "NA" (under AMC but not reported – never 0) or None (not under AMC yet).
    """
    gp = store.gps.loc[gp_code]
    u = _gp_uptime(store, (store.gps["block_id"] == gp["block_id"]).to_numpy(), week)
    row = next(r for r in u["rows"] if r["id"] == gp_code)
    daily = store.daily.loc[gp_code]
    daily_start = store.daily.columns.min()
    amc_date = gp["amc_date"] if isinstance(gp["amc_date"], dt.date) else None
    columns = []
    for col, v in zip(u["columns"], row["values"]):
        end = min(dt.date.fromisoformat(col["endDate"]), store.data_as_of)
        if col["kind"] == "day":
            start = end
        elif col["kind"] == "week":
            start = store.week(col["key"]).start
        else:  # month / month to date
            start = end.replace(day=1)
        days = None
        if amc_date and amc_date <= end:
            first = max(start, amc_date)
            if first >= daily_start:
                vals = daily[[d for d in daily.index if first <= d <= end]]
                counts = band_counts(vals)
                days = {"counts": counts, "reported": int(vals.notna().sum()), "na": int(vals.isna().sum()), "underAmc": len(vals)}
        columns.append(
            {
                "key": col["key"],
                "label": col["label"],
                "kind": col["kind"],
                "endDate": col["endDate"],
                "value": v,
                "band": band_of(v) if isinstance(v, (int, float)) else None,
                "blockAverage": col["average"],
                "days": days,
            }
        )
    return {"columns": columns, "bands": u["bands"], "thresholds": u["thresholds"], "dailyFrom": daily_start.isoformat()}


def list_gps(store: Store, week: str, circle: str | None, district: str | None, block: str | None, search: str | None, page: int, page_size: int) -> dict[str, Any]:
    g = store.gps
    mask = np.ones(len(g), dtype=bool)
    if circle:
        mask &= (g["circle_id"] == circle).to_numpy()
    if district:
        mask &= (g["district_id"] == district).to_numpy()
    if block:
        mask &= (g["block_id"] == block).to_numpy()
    if search:
        q = search.strip().lower()
        mask &= (g["name"].str.lower().str.contains(q, regex=False) | g.index.str.lower().str.contains(q, regex=False)).to_numpy()
    total = int(mask.sum())
    idx = np.flatnonzero(mask)[(page - 1) * page_size : page * page_size]
    sel = np.zeros(len(g), dtype=bool)
    sel[idx] = True
    return {"items": gp_snapshots(store, sel, week), "total": total, "page": page, "pageSize": page_size}


def search(store: Store, query: str) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if len(q) < 2:
        return []
    g = store.gps
    out: list[dict[str, Any]] = []
    for c in sorted(g["circle"].unique()):
        if q in c.lower() or q == circle_code(c).lower():
            out.append({"type": "circle", "id": slug(c), "label": c.title(), "sublabel": f"Circle · {circle_code(c)}", "circleId": slug(c)})
    blocks = g.drop_duplicates("block_id")
    hit = blocks[blocks["block_name"].str.lower().str.contains(q, regex=False) | (blocks["block_code"].astype(str) == q)]
    for r in hit.head(12).itertuples():
        out.append({"type": "block", "id": r.block_id, "label": r.block_name.title(), "sublabel": f"Block · {r.block_code} · {r.district.title()}, {r.circle.title()}", "circleId": r.circle_id, "districtId": r.district_id, "blockId": r.block_id})
    gh = g[g["name"].str.lower().str.contains(q, regex=False) | g.index.str.lower().str.startswith(q)]
    for code, r in gh.head(15).iterrows():
        out.append({"type": "gp", "id": code, "label": str(r["name"]).title(), "sublabel": f"GP · {code} · {r['block_name'].title()} block", "circleId": r["circle_id"], "districtId": r["district_id"], "blockId": r["block_id"]})
    return out


# ---------------------------------------------------------------- weekly report


REPORT_ROWS = [
    ("totalGps", "Total existing GPs", "count", "neutral"),
    ("revisedExisting", "Revised existing GPs", "count", "neutral"),
    ("hotoDoneGps", "HOTO done GPs", "count", "up"),
    ("hotoPendingGps", "HOTO pending GPs", "count", "down"),
    ("hotoDoneBlocks", "HOTO done blocks", "count", "up"),
    ("amcGps", "AMC GPs", "count", "up"),
    ("amcPct", "AMC GP percentage", "percent", "up"),
    ("availabilityWeek", "AMC availability (week)", "percent", "up"),
    ("gpsAbove98Week", "GPs >98% (week)", "count", "up"),
    ("gpsAtZeroWeek", "GPs at 0% (week)", "count", "down"),
    ("penaltyBlocksWeek", "Penalty-prone blocks (week)", "count", "down"),
    ("availability", "AMC availability (MTD at week end)", "percent", "up"),
    ("gpsAbove98", "GPs >98% (MTD at week end)", "count", "up"),
    ("gpsAtZero", "GPs at 0% (MTD at week end)", "count", "down"),
    ("penaltyBlocks", "Penalty-prone blocks (MTD at week end)", "count", "down"),
    ("naGps", "AMC GPs not reported (NA)", "count", "down"),
    ("incrementalGps", "Incremental GPs (AMC)", "count", "neutral"),
    ("amcRkm", "AMC fibre RKM", "rkm", "up"),
    ("totalRkm", "Total scope fibre RKM", "rkm", "neutral"),
]


def weekly_report(store: Store, week: str, compare: str, circle: str | None, district: str | None, block: str | None, dq: list[dict]) -> dict[str, Any]:
    g = store.gps
    mask = np.ones(len(g), dtype=bool)
    scope = "All circles"
    if circle:
        mask &= (g["circle_id"] == circle).to_numpy()
    if district:
        mask &= (g["district_id"] == district).to_numpy()
    if block:
        mask &= (g["block_id"] == block).to_numpy()
    if not mask.any():
        raise NotFound("No GPs in the selected scope")
    sub = g[mask]
    if block:
        scope = f"{sub['block_name'].iloc[0].title()} block"
    elif district:
        scope = f"{sub['district'].iloc[0].title()} district"
    elif circle:
        scope = sub["circle"].iloc[0].title()
    cur = summarize(store, mask, week)
    old = summarize(store, mask, compare)
    comparison = [{"key": k, "label": label, "unit": unit, "polarity": pol, "previous": old[k], "current": cur[k]} for k, label, unit, pol in REPORT_ROWS]

    by_block = bool(circle or district or block)
    unit_col = "block_id" if by_block else "circle_id"
    wf_cur = store.week_frame(week).loc[sub.index]
    wf_old = store.week_frame(compare).loc[sub.index]
    m_cur = wf_cur["mtd"].where(wf_cur["amc"])
    m_old = wf_old["mtd"].where(wf_old["amc"])
    ranking = []
    for uid, idx in sub.groupby(unit_col).groups.items():
        u = sub.loc[idx]
        amc_n = int(wf_cur.loc[idx, "amc"].sum())
        rev_n = int(u["revised"].sum())
        bl = m_cur.loc[idx].groupby(u["block_id"]).mean()
        ranking.append(
            {
                "id": uid,
                "name": (u["block_name"] if by_block else u["circle"]).iloc[0].title(),
                "availability": r2(m_cur.loc[idx].mean()) if m_cur.loc[idx].notna().any() else None,
                "previous": r2(m_old.loc[idx].mean()) if m_old.loc[idx].notna().any() else None,
                "amcPct": r2(amc_n / rev_n * 100) if rev_n else None,
                "penaltyBlocks": int((bl < get_settings().penalty_threshold).sum()),
            }
        )
    ranking.sort(key=lambda r: -(r["availability"] if r["availability"] is not None else -1))

    pen = get_settings().penalty_threshold
    b_cur = m_cur.groupby(sub["block_id"]).mean()
    b_old = m_old.groupby(sub["block_id"]).mean()
    penalty = []
    for bid, val in b_cur[b_cur < pen].sort_values().head(20).items():
        r = sub[sub["block_id"] == bid].iloc[0]
        penalty.append({"id": bid, "name": r["block_name"].title(), "circleName": r["circle"].title(), "districtName": r["district"].title(), "availability": r2(val), "previous": r2(b_old.get(bid))})

    low = m_cur[m_cur < pen].sort_values().head(20)
    low_gps = [{"id": c, "name": str(sub.loc[c, "name"]).title(), "blockName": sub.loc[c, "block_name"].title(), "availability": r2(v)} for c, v in low.items()]

    w_cur, w_old = store.week(week), store.week(compare)
    return {
        "scopeLabel": scope,
        "week": week_json(w_cur),
        "compareWeek": week_json(w_old),
        "generatedAt": dt.datetime.now(dt.UTC).isoformat(),
        "isDemo": False,
        "dataAsOf": store.data_as_of.isoformat(),
        "sourceFile": store.file_name,
        "comparison": comparison,
        "ranking": ranking,
        "hotoProgress": [
            {"label": f"Week {w_old.number}", "done": old["hotoDoneGps"], "pending": old["hotoPendingGps"]},
            {"label": f"Week {w_cur.number}", "done": cur["hotoDoneGps"], "pending": cur["hotoPendingGps"]},
        ],
        "penaltyBlocks": penalty,
        "lowAvailabilityGps": low_gps,
        "dataQuality": dq,
        "fibreChanges": [
            {"label": "AMC fibre RKM", "previous": old["amcRkm"], "current": cur["amcRkm"]},
            {"label": "Total scope fibre RKM", "previous": old["totalRkm"], "current": cur["totalRkm"]},
            {"label": "Incremental GPs (AMC)", "previous": old["incrementalGps"], "current": cur["incrementalGps"]},
            {"label": "AMC GPs", "previous": old["amcGps"], "current": cur["amcGps"]},
        ],
    }


def _block_values(g: pd.DataFrame, gp_values: pd.Series, end: dt.date) -> pd.Series:
    """Block value = mean of its AMC GPs' values, over the blocks with HOTO done by `end`
    (the workbook's block uptime tables count HOTO-done blocks; those without any value are NA).

    A block whose AMC GPs report availability is always counted, even when none of its GPs
    carries a HOTO date (e.g. 6 Assam blocks under AMC from 25 Sep with blank HOTO dates) –
    the Master Block sheet's own weekly columns include them too."""
    hoto = pd.to_datetime(g["hoto_date"], errors="coerce") <= pd.Timestamp(end)
    means = gp_values.groupby(g["block_id"]).mean()
    universe = pd.Index(g.loc[hoto.to_numpy(), "block_id"].unique()).union(means.dropna().index)
    return means.reindex(universe)


def _periods(store: Store, g: pd.DataFrame, week: str) -> list[dict[str, Any]]:
    """Period columns: the last four completed months, the current month to date,
    the selected week and the three weeks before it."""
    w = store.week(week)
    td_end = min(w.end, store.data_as_of)
    starts = [d for d in list(g["hoto_date"]) + list(g["amc_date"]) if isinstance(d, dt.date)]
    first = min(starts) if starts else td_end
    periods: list[dict[str, Any]] = []
    y, m = first.year, first.month
    while (y, m) < (td_end.year, td_end.month):
        last = dt.date(y, m, 28) + dt.timedelta(days=4)
        periods.append({"key": f"{y}-{m:02d}", "label": dt.date(y, m, 1).strftime("%b-%y"), "kind": "month", "end": last - dt.timedelta(days=last.day)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    periods = periods[-4:]  # last four completed months keep the table a fixed, readable width
    periods.append({"key": "td", "label": f"{td_end:%b-%y} TD", "kind": "mtd", "end": td_end})
    idx = [x.code for x in store.weeks].index(week)
    for i, wk in enumerate(reversed(store.weeks[max(0, idx - 3) : idx + 1])):
        periods.append({"key": wk.code, "label": f"Till W-{wk.number}" if i == 0 else f"WK-{wk.number}", "kind": "week", "end": wk.end})
    return periods


def _with_previous_td(store: Store, periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the previous month to date ("Sep-26 TD") just before the current month TD: day 1 .. the same
    day number as the current TD end, so both TD columns cover the same dates (a shorter previous month
    stops on its last day). Skipped when the daily sheet does not cover that window."""
    periods = list(periods)
    td = next((p for p in periods if p["kind"] == "mtd"), None)
    if td is not None:
        prev_last = td["end"].replace(day=1) - dt.timedelta(days=1)
        prev_end = prev_last.replace(day=min(td["end"].day, prev_last.day))
        if prev_end.replace(day=1) >= store.daily.columns.min():
            periods.insert(periods.index(td), {"key": "ptd", "label": f"{prev_end:%b-%y} TD", "kind": "ptd", "end": prev_end})
    return periods


def _period_values(store: Store, g: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    """Each GP's availability for a period column (before the AMC filter).

    Completed months use the workbook's monthly AMC column, "TD" = month-to-date from
    daily data, weeks = the workbook's weekly W-nn columns."""
    end = p["end"]
    if p["kind"] == "week":
        return store.week_frame(p["key"]).loc[g.index, "weekly"]
    if p["kind"] in ("mtd", "ptd"):  # month to date / previous month to the same day
        return store.mtd(end).loc[g.index]
    if p["key"] in store.monthly_amc.columns:
        return store.monthly_amc.loc[g.index, p["key"]]  # the workbook's own monthly AMC column
    if end.replace(day=1) >= store.daily.columns.min():
        return store.mtd(end).loc[g.index]
    return pd.Series(np.nan, index=g.index)


def _period_table(store: Store, mask: np.ndarray, week: str) -> dict[str, Any]:
    """Month-wise and week-wise HOTO / AMC progress and uptime bands, computed from GP-level data.

    Columns: the last four completed months, the current month to date, the selected
    week and the three weeks before it. Completed months use each GP's monthly AMC value
    (GP Wise Data "Mon'26 (AMC)" columns); "TD" = month-to-date from daily data up to the
    reporting date; weeks = the workbook's weekly W-nn columns. NA = AMC GP without a value.
    """
    g = store.gps[mask]
    periods = _with_previous_td(store, _periods(store, g, week))
    hoto_dt = pd.to_datetime(g["hoto_date"], errors="coerce")
    amc_dt = pd.to_datetime(g["amc_date"], errors="coerce")
    s = get_settings()
    out_periods, hoto_rows, gp_bands, blk_bands = [], [], [], []
    for p in periods:
        end = p["end"]
        ts = pd.Timestamp(end)
        hoto = (hoto_dt <= ts).to_numpy()
        amc = (amc_dt <= ts).to_numpy()
        hoto_rows.append(
            {
                "hotoDoneBlocks": int(g.loc[hoto, "block_id"].nunique()),
                "hotoDoneGps": int(hoto.sum()),
                "amcGps": int(amc.sum()),
                "amcRkm": r2(g.loc[amc, "total_rkm"].sum()),
            }
        )
        vals = _period_values(store, g, p).where(amc)
        counts = band_counts(vals)
        gp_bands.append({"counts": counts, "reported": int(vals.notna().sum()), "na": int((amc & vals.isna().to_numpy()).sum()), "average": r2(vals.mean()) if vals.notna().any() else None})
        bv = _block_values(g, vals, end)
        blk_bands.append({"counts": band_counts(bv), "reported": int(bv.notna().sum()), "na": int(bv.isna().sum()), "average": r2(bv.mean()) if bv.notna().any() else None})
        out_periods.append({"key": p["key"], "label": p["label"], "kind": p["kind"], "endDate": end.isoformat()})

    # RFP target: 75 % of existing GPs by the 4th month of the AMC contract (contract start = first AMC month in the data).
    all_amc = [d for d in store.gps["amc_date"] if isinstance(d, dt.date)]
    target_month = None
    if all_amc:
        f = min(all_amc)
        mm = f.month + 3
        target_month = f"{f.year + (mm - 1) // 12}-{(mm - 1) % 12 + 1:02d}"
    return {
        "periods": out_periods,
        "hotoAmc": hoto_rows,
        "rfpTarget": {"value": round(len(g) * 0.75, 2), "periodKey": target_month, "basis": "75% of existing GPs by the 4th AMC month (RFP)"},
        "gpBands": gp_bands,
        "blockBands": blk_bands,
        "thresholds": {"healthy": s.healthy_threshold, "penalty": s.penalty_threshold},
    }
