"""Reconcile dashboard calculations with the figures typed into the O&M sheet.

For month-to-date metrics the O&M sheet uses the "Oct'26 (AMC)" column, which
the source workbook computes over a shorter date range than the daily data
available. We therefore also recompute those metrics over the *source's* range
so a difference can be explained instead of hidden.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import numpy as np
import pandas as pd

from ..config import get_settings
from .metrics import summarize
from .store import Store

# normalised O&M label -> (metric key, kind)
MAP: dict[str, tuple[str, str]] = {
    "total blocks": ("totalBlocks", "exact"),
    "total existing gps": ("totalGps", "exact"),
    "converted to np/permanently closed": ("_closed", "exact"),
    "revised existing gps": ("revisedExisting", "exact"),
    "hoto done - blocks": ("hotoDoneBlocks", "exact"),
    "hoto done - gps": ("hotoDoneGps", "exact"),
    "amc gps (total)": ("amcGps", "exact"),
    "incremental gps": ("incrementalGps", "exact"),
    "total scope fibre": ("totalRkm", "rkm"),
    "amc fibre rkm": ("amcRkm", "rkm"),
    "gps above 98% (mtd)": ("gpsAbove98", "mtd"),
    "gps at 0% (mtd)": ("gpsAtZero", "mtd"),
    "penalty prone blocks <90%": ("penaltyBlocks", "mtd"),
    "one-time up gps (sept-26)": ("oneTimeUp", "external"),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _source_mtd_end(store: Store) -> dt.date | None:
    """Find the last day the source's current-month AMC column actually covers."""
    month = f"{store.data_as_of.year}-{store.data_as_of.month:02d}"
    if month not in store.monthly_amc.columns:
        return None
    src = store.monthly_amc[month]
    best: tuple[int, dt.date] | None = None
    for day in range(1, store.data_as_of.day + 1):
        end = store.data_as_of.replace(day=day)
        m = store.mtd(end)
        both = src.notna() & m.notna()
        if not both.any():
            continue
        matches = int((np.abs(src[both] - m[both]) < 1e-6).sum())
        if best is None or matches > best[0]:
            best = (matches, end)
    return best[1] if best else None


def reconcile(store: Store) -> dict[str, Any]:
    latest = store.latest_week.code
    src_end = _source_mtd_end(store)
    rows = []
    for state in sorted(store.reported["state"].unique()) if not store.reported.empty else []:
        mask = (store.gps["circle"] == state).to_numpy()
        if not mask.any():
            continue
        comp = summarize(store, mask, latest)
        comp["_closed"] = comp["convertedNp"] + comp["permanentlyClosed"] + comp["deductedGps"]
        alt: dict[str, Any] = {}
        if src_end and src_end != store.data_as_of:
            alt = _mtd_metrics(store, mask, src_end)
        for r in store.reported[store.reported["state"] == state].itertuples():
            key = MAP.get(_norm(r.metric))
            if not key:
                continue
            metric, kind = key
            reported = None if pd.isna(r.value_num) else float(r.value_num)
            computed = comp[metric]
            tol = 0.05 if kind == "rkm" else 0
            match = reported is not None and computed is not None and abs(float(computed) - reported) <= tol
            note = None
            alt_value = alt.get(metric)
            if reported is None:
                note = "No value in the O&M sheet"
            elif not match and kind == "mtd" and alt_value is not None:
                note = (
                    f"O&M uses the Oct'26 (AMC) column, which covers 1–{src_end.day} {src_end:%b}; the dashboard uses daily data up to "
                    f"{store.data_as_of:%d %b}. Recomputed for 1–{src_end.day} {src_end:%b}: {alt_value}"
                    + (" (matches)" if abs(alt_value - reported) < 1e-9 else "")
                )
            elif not match and kind == "external":
                note = "O&M figure comes from the external one-time-up report; dashboard counts GPs with September availability > 0%"
            rows.append(
                {
                    "state": state.title(),
                    "metric": r.metric.strip(),
                    "reported": reported,
                    "computed": computed,
                    "difference": None if reported is None or computed is None else round(float(computed) - reported, 2),
                    "status": "NO_REFERENCE" if reported is None else ("MATCH" if match else ("EXPLAINED" if note else "MISMATCH")),
                    "note": note,
                }
            )
    return {
        "dataAsOf": store.data_as_of.isoformat(),
        "sourceMtdEnd": src_end.isoformat() if src_end else None,
        "penaltyThreshold": get_settings().penalty_threshold,
        "rows": rows,
    }


def _mtd_metrics(store: Store, mask: np.ndarray, end: dt.date) -> dict[str, Any]:
    s = get_settings()
    g = store.gps[mask]
    m = store.mtd(end).loc[g.index]
    blocks = m.groupby(g["block_id"]).mean()
    return {
        "gpsAbove98": int((m > s.healthy_threshold).sum()),
        "gpsAtZero": int((m == 0).sum()),
        "penaltyBlocks": int((blocks < s.penalty_threshold).sum()),
    }
