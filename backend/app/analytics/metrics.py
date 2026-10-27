"""Metric calculations (single source of truth for every number on the dashboard).

Definitions (validated against the O&M 'KEY NUMBERS' and 'Master Block' sheets):
  totalGps            existing GP rows in the master list (incl. converted/closed)
  revisedExisting     totalGps minus GPs converted to NP / closed / deducted
  hotoDoneGps         HOTO date <= reporting week end
  hotoPendingGps      revised GPs without HOTO by week end
  hotoDoneBlocks      blocks with at least one HOTO-done GP by week end
  amcGps              AMC date <= week end
  incrementalGps      AMC GPs whose category is 'Incremental'
  availability        mean AMC month-to-date availability (NA excluded, never 0)
  gpsAbove98/AtZero   AMC GPs with MTD > 98% / == 0%  (workbook: ">98%"; exactly 98 falls in 95–98)
  naGps               AMC GPs with no MTD value
  penaltyBlocks       blocks whose mean AMC MTD availability < penalty threshold (90%)
  totalRkm            sum of TOTAL RKM (all GP rows) ; amcRkm = sum for AMC GPs
  *Week variants      same rules on the source's weekly column (W-nn) – used for
                      week-on-week comparisons, as in the O&M weekly tables
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import get_settings
from .store import Store

BANDS: list[tuple[str, float, float]] = [
    ("0%", 0, 0),
    ("0–30%", 0, 30),
    ("30–50%", 30, 50),
    ("50–75%", 50, 75),
    ("75–85%", 75, 85),
    ("85–90%", 85, 90),
    ("90–95%", 90, 95),
    ("95–98%", 95, 98),
    (">98%", 98, 100),
]


def r2(v: float | None) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), 2)


def band_of(v: float) -> str:
    """Workbook band rule (verified on exact boundary values): 0 is its own band, every other
    band includes its lower limit (lower <= v < upper), and the top band is strictly above 98 –
    so exactly 98 stays in 95–98."""
    if v == 0:
        return "0%"
    for label, lo, hi in BANDS[1:-2]:
        if v < hi:
            return label
    return "95–98%" if v <= BANDS[-1][1] else ">98%"


def band_counts(values: pd.Series) -> dict[str, int]:
    out = {label: 0 for label, *_ in BANDS}
    for v in values.dropna():
        out[band_of(float(v))] += 1
    return out


def block_means(gps: pd.DataFrame, values: pd.Series) -> pd.Series:
    """Mean of AMC GP values per block (blocks without AMC values are NaN)."""
    return values.groupby(gps["block_id"]).mean()


def summarize(store: Store, mask: np.ndarray | pd.Series, week_code: str) -> dict[str, float | int | None]:
    s = get_settings()
    g = store.gps[mask] if mask is not None else store.gps
    wf = store.week_frame(week_code).loc[g.index]
    amc = wf["amc"]
    mtd = wf["mtd"].where(amc)
    weekly = wf["weekly"].where(amc)
    blocks = g["block_id"]
    block_avail = mtd.groupby(blocks).mean()
    block_week = weekly.groupby(blocks).mean()
    hoto_blocks = wf["hoto_done"].groupby(blocks).any()
    revised = g["revised"]
    amc_count = int(amc.sum())
    revised_count = int(revised.sum())
    # "AMC at HOTO" = AMC GPs not classified Incremental in the source column (same as amcOriginalGps),
    # so AMC at HOTO + Incremental + Non-AMC = revised existing GPs on every page.
    amc_original = int((amc & (g["amc_category"] != "INCREMENTAL")).sum())
    return {
        "totalStates": int(g["circle"].nunique()),
        "totalDistricts": int(g["district_id"].nunique()),
        "totalBlocks": int(blocks.nunique()),
        "totalGps": len(g),
        "revisedExisting": revised_count,
        "hotoDoneGps": int(wf["hoto_done"].sum()),
        "hotoPendingGps": int((revised & ~wf["hoto_done"]).sum()),
        "hotoDoneBlocks": int(hoto_blocks.sum()),
        "amcAtHotoGps": amc_original,
        "amcGps": amc_count,
        "nonAmcGps": int((revised & ~amc).sum()),
        "amcPct": r2(amc_count / revised_count * 100) if revised_count else None,
        "availability": r2(mtd.mean()) if mtd.notna().any() else None,
        "gpsAbove98": int((mtd > s.healthy_threshold).sum()),
        "gpsAtZero": int((mtd == 0).sum()),
        "naGps": int((amc & mtd.isna()).sum()),
        "penaltyBlocks": int((block_avail < s.penalty_threshold).sum()),
        # State Performance Comparison: GPs below the penalty threshold (0% included), blocks above the healthy
        # threshold (block mean of AMC GPs, like penaltyBlocks) and the reporting bases of the percentages.
        "gpsBelowPenalty": int((mtd < s.penalty_threshold).sum()),
        "blocksAbove98": int((block_avail > s.healthy_threshold).sum()),
        "reportingGps": int(mtd.notna().sum()),
        "reportingBlocks": int(block_avail.notna().sum()),
        "availabilityWeek": r2(weekly.mean()) if weekly.notna().any() else None,
        "gpsAbove98Week": int((weekly > s.healthy_threshold).sum()),
        "gpsAtZeroWeek": int((weekly == 0).sum()),
        "penaltyBlocksWeek": int((block_week < s.penalty_threshold).sum()),
        "oneTimeUp": int(store.one_time_up_sept.loc[g.index].sum()),
        "totalRkm": r2(g["total_rkm"].sum()),
        "bsnlRkm": r2(g["bsnl_km"].fillna(0).sum()),
        "bbnlRkm": r2(g["bbnl_km"].fillna(0).sum()),
        "amcRkm": r2(g.loc[amc[amc].index, "total_rkm"].sum()),
        "incrementalGps": int((amc & (g["amc_category"] == "INCREMENTAL")).sum()),
        "amcOriginalGps": amc_original,
        "convertedNp": int((g["lifecycle"] == "CONVERTED_NP").sum()),
        "permanentlyClosed": int((g["lifecycle"] == "PERMANENTLY_CLOSED").sum()),
        "deductedGps": int((g["lifecycle"] == "DEDUCTED").sum()),
    }
