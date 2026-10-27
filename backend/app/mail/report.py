"""AMC Conversion figures of one recipient's GPs – the content behind the e-mail templates.

Numbers follow AMC Conversion → Plan vs Execution exactly (analytics/amc_plan.py `windows` + `masks`, latest week of the
active data), but are counted only over the recipient's GP set, so an e-mail never contains a figure from outside the
recipient's area:

  Month target      GPs with a Planned Date in the current month
  Due so far        Planned Date from the 1st up to the data date
  Achieved (MTD)    Ach Date from the 1st up to the data date            MTD % = achieved / due so far
  Overdue           Planned on or before the data date, not achieved by then
  Week target       Planned Date in the latest Fri–Thu week
  Week achieved     Ach Date in that week, up to the data date           Week % = achieved / week target

The heavy part (masks over the whole plan) is computed once per run in ReportContext; each recipient only selects rows.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from ..analytics.amc_plan import _pct, _week_of, masks, windows
from ..analytics.store import Store
from .audience import gp_business_area, matrix_frame

KEYS = ("monthTarget", "mtdTarget", "mtdAchieved", "overdue", "weekTarget", "weekAchieved")
_MASK_OF = {"monthTarget": "month-target", "mtdTarget": "mtd-target", "mtdAchieved": "mtd-achieved", "overdue": "overdue", "weekTarget": "week-target", "weekAchieved": "week-achieved"}
NOT_ASSIGNED, VACANT = "Not assigned", "Vacant post"


class ReportContext:
    """Everything that is the same for all recipients of one run: periods and per-GP plan flags."""

    def __init__(self, store: Store):
        from .audience import is_open_post

        self.store = store
        week = store.latest_week
        self.win = windows(store, week.code)
        _, number, _, _ = _week_of(store, self.win.week_start)
        self.week_label = f"WK-{number}"
        g = store.gps
        matrix = matrix_frame(store)
        am = matrix["am_name"].reindex(g.index) if matrix is not None else g["am_name"]

        def am_label(v: Any) -> str:
            if not isinstance(v, str) or not v.strip() or v.strip() == "0":
                return NOT_ASSIGNED
            return VACANT if is_open_post(v) else " ".join(v.split())

        self.gp = pd.DataFrame(
            {
                "circle": g["circle"].astype(str).str.title(),
                "block": g["block_name"].astype(str).str.title() + " (" + g["block_code"].astype(str) + ")",
                "am": am.map(am_label),
                "ba": gp_business_area(store, matrix).fillna("—"),
            },
            index=g.index,
        )
        p = store.amc_plan
        self.has_plan = not p.empty
        if self.has_plan:
            m = masks(store, self.win)
            flags = pd.DataFrame({k: m[_MASK_OF[k]] for k in KEYS}, index=p.index).astype(int)
            self.plan = flags.join(self.gp)
        else:
            self.plan = pd.DataFrame(columns=[*KEYS, *self.gp.columns])

    # ---------------------------------------------------------------- per recipient

    def figures(self, gps: pd.Index) -> dict[str, Any]:
        plan = self.plan[self.plan.index.isin(gps)]
        sub = self.gp.loc[self.gp.index.intersection(gps)]
        total = self._row("Total", plan, len(sub))
        return {
            "hasPlan": self.has_plan,
            "gps": len(sub),
            "total": total,
            "block": self._table(plan, sub, "block", with_circle=True),
            "am": self._table(plan, sub, "am", with_circle=True),
            "ba": self._table(plan, sub, "ba", with_circle=True),
        }

    def _row(self, name: str, plan: pd.DataFrame, gps: int) -> dict[str, Any]:
        r: dict[str, Any] = {"name": name, "gps": gps, **{k: int(plan[k].sum()) if len(plan) else 0 for k in KEYS}}
        r["mtdPct"] = _pct(r["mtdAchieved"], r["mtdTarget"])
        r["weekPct"] = _pct(r["weekAchieved"], r["weekTarget"])
        return r

    def _table(self, plan: pd.DataFrame, sub: pd.DataFrame, by: str, with_circle: bool) -> list[dict[str, Any]]:
        counts = sub.groupby(["circle", by]).size()
        sums = plan.groupby(["circle", by])[list(KEYS)].sum() if len(plan) else pd.DataFrame(columns=list(KEYS))
        rows = []
        for (circle, key), n in counts.items():
            r: dict[str, Any] = {"name": str(key), "circle": circle, "gps": int(n)}
            for k in KEYS:
                r[k] = int(sums.at[(circle, key), k]) if (circle, key) in sums.index else 0
            r["mtdPct"] = _pct(r["mtdAchieved"], r["mtdTarget"])
            r["weekPct"] = _pct(r["weekAchieved"], r["weekTarget"])
            rows.append(r)
        if by == "block":  # a block list can be long: keep blocks with a target, an achievement or overdue GPs
            rows = [r for r in rows if any(r[k] for k in KEYS)]
        rows.sort(key=lambda r: (r["circle"], r["name"] in (NOT_ASSIGNED, VACANT), r["name"].lower()))
        return rows

    # ---------------------------------------------------------------- shared texts

    def periods(self) -> dict[str, str]:
        w = self.win

        def d(x: dt.date) -> str:
            return x.strftime("%d %b %Y")

        return {
            "data_date": d(self.store.data_as_of),
            "month": f"{w.month_start:%b %Y}",
            "week": self.week_label,
            "week_range": f"{w.week_start:%d %b} – {w.week_end:%d %b %Y}",
            "source_file": self.store.file_name or "",
        }
