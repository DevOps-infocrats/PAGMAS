"""Management Review – Page 3 "Critical KPI – Blocks & GPs" monthly & weekly performance table.

Columns move forward automatically with the data: the last two completed months (workbook
monthly AMC columns), the previous month to the same day ("Sep-26 MTD": 1–21 Sep when the data
runs to 21 Oct – daily data, from the upload history when the active file no longer has those
days), the current month to date, and the three weeks ending with the reporting week (source
W-nn columns). When Week 42 arrives the weeks become WK-40, WK-41, WK-42.

Rows
  GPs > 98% availability                 AMC GPs strictly above 98% in the column
  < 90% availability blocks – penalty    blocks whose mean AMC GP availability is below the penalty threshold
                                         (90%) – the client sheet's COUNTIFS('Master Block' avg, "<90")
  GPs at 0% availability                 AMC GPs at exactly 0% (NA excluded)
  One-Time Up GPs / AMC / Non-AMC        circle sheet (external one-time-up report); the sheet has no
                                         previous-month-TD figure, so that cell stays empty
  Incremental GPs TD                     incremental GPs whose AMC date falls inside the column's period
Scope / Target
  GPs > 98% and One-Time Up AMC = AMC GPs as of the cutoff; One-Time Up GPs = revised scope;
  penalty-prone blocks and 0% GPs target 0; no source target for Non-AMC and incremental.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from .store import Store

ROWS = [
    # key, label, polarity
    ("gpsAbove98", "GPs > 98% Availability", "up"),
    ("penaltyBlocks", "< 90% Availability Blocks – Penalty Prone", "down"),
    ("gpsAtZero", "GPs at 0% Availability", "down"),
    ("oneTimeUpGps", "One-Time Up GPs", "up"),
    ("oneTimeUpAmc", "One-Time Up AMC", "up"),
    ("oneTimeUpNonAmc", "One Time Up Non-AMC", "neutral"),
    ("incrementalAdded", "Incremental GPs TD", "neutral"),
]


def _window(store: Store, p: dict[str, Any]) -> tuple[dt.date, dt.date]:
    if p["kind"] == "week":
        w = store.week(p["key"])
        return w.start, w.end
    return p["end"].replace(day=1), p["end"]


def critical_table(
    store: Store,
    mask: np.ndarray,
    name: str,
    periods: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    one_time_up: dict[str, dict[str, float]] | None,
    cur: dict[str, Any],
    prev: dict[str, Any],
    cur_label: str,
    prev_label: str,
) -> dict[str, Any]:
    """periods / metrics: the review's period columns and the frame metrics for this circle."""
    idx = {id(p): i for i, p in enumerate(periods)}
    months = [p for p in periods if p["kind"] == "month"][-2:]
    ptd = [p for p in periods if p["kind"] == "ptd"]
    td = [p for p in periods if p["kind"] == "mtd"]
    weeks = [p for p in periods if p["kind"] == "week"][:3][::-1]  # three weeks ending with the reporting week
    cols = months + ptd + td + weeks
    g = store.gps[mask]
    amc_dt = pd.to_datetime(g["amc_date"], errors="coerce")
    inc = (g["amc_category"] == "INCREMENTAL").to_numpy()
    td_m = metrics[idx[id(td[0])]] if td else metrics[-1]

    def label(p: dict[str, Any]) -> str:
        if p["kind"] == "week":
            return f"WK-{store.week(p['key']).number}"
        if p["kind"] in ("mtd", "ptd"):
            return f"{p['end']:%b-%y} MTD"
        return p["label"]

    def one_time(key: str, p: dict[str, Any]) -> float | None:
        if p["kind"] == "ptd":
            return None  # not in the circle sheet – never estimated
        series = (one_time_up or {}).get(key) or {}
        k = p["key"] if p["kind"] != "mtd" else f"{p['end'].year}-{p['end'].month:02d}"
        return series.get(k)

    def cell(key: str, p: dict[str, Any]) -> float | int | None:
        if key.startswith("oneTimeUp"):
            return one_time(key, p)
        if key == "incrementalAdded":
            a, b = _window(store, p)
            return int((inc & ((amc_dt >= pd.Timestamp(a)) & (amc_dt <= pd.Timestamp(b))).to_numpy()).sum())
        return metrics[idx[id(p)]][key]

    scope = {
        "gpsAbove98": td_m["amcGps"],
        "penaltyBlocks": 0,
        "gpsAtZero": 0,
        "oneTimeUpGps": td_m["revisedExisting"],
        "oneTimeUpAmc": td_m["amcGps"],
        "oneTimeUpNonAmc": None,
        "incrementalAdded": None,
    }
    rows = []
    for key, lbl, pol in ROWS:
        values = [cell(key, p) for p in cols]
        if key.startswith("oneTimeUp") and all(v is None for v in values):
            continue  # circle sheet not available
        rows.append({"key": key, "label": lbl, "polarity": pol, "scope": scope[key], "values": values, "source": "circle sheet" if key.startswith("oneTimeUp") else "computed"})

    def change(key: str, polarity: str) -> dict[str, Any]:
        c, p = cur[key], prev[key]
        d = None if c is None or p is None else c - p
        trend = "na" if d is None else "flat" if d == 0 else ("better" if (d > 0) == (polarity == "up") else "worse")
        return {"previous": p, "current": c, "delta": d, "trend": trend}

    return {
        "title": f"Monthly & Weekly Performance – {name}",
        "columns": [{"key": p["key"], "label": label(p), "kind": p["kind"], "startDate": _window(store, p)[0].isoformat(), "endDate": p["end"].isoformat()} for p in cols],
        "rows": rows,
        "insight": {
            "from": prev_label,
            "to": cur_label,
            "items": [
                {"label": ">98% GPs", **change("gpsAbove98", "up")},
                {"label": "Penalty-prone blocks (<90%)", **change("penaltyBlocks", "down")},
                {"label": "0% GPs", **change("gpsAtZero", "down")},
            ],
        },
    }
