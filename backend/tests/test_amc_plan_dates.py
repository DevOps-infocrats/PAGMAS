"""GP-wise plan dates outside the file's period (11-01-2026 typed for 01-11-2026) are never counted as a target or as
GP Ready anywhere, and are reported with their GP codes."""

import dataclasses
import datetime as dt

import pandas as pd

from app.analytics import amc_plan
from app.analytics.store import Week, _amc_plan, plan_date_range


def _raw(codes, planned, ach):
    return pd.DataFrame(
        {"gp_code": codes, "category": ["Additional Plan"] * len(codes), "planned_date": planned, "ach_date": ach,
         "current_status": [None] * len(codes), "letter_status": [None] * len(codes), "letter_date": [None] * len(codes), "approval_status": [None] * len(codes)}
    )


def test_out_of_period_plan_dates_are_set_aside():
    weeks = [Week("W-40", 40, dt.date(2026, 9, 26), dt.date(2026, 10, 2))]
    lo, hi = plan_date_range(weeks, dt.date(2026, 11, 3))
    assert lo == dt.date(2026, 6, 26) and hi == dt.date(2027, 11, 4)
    df = _raw(["A", "B", "C"], [dt.date(2026, 1, 11), dt.date(2026, 11, 1), None], [dt.date(2026, 11, 2), dt.date(2026, 1, 5), None])
    p = _amc_plan(df, pd.Index(["A", "B", "C"]), weeks, dt.date(2026, 11, 3))
    assert p.at["A", "planned_date"] is None and p.at["A", "planned_date_invalid"] == dt.date(2026, 1, 11)
    assert p.at["A", "ach_date"] == dt.date(2026, 11, 2)  # a valid Ach Date stays
    assert p.at["B", "planned_date"] == dt.date(2026, 11, 1) and p.at["B", "ach_date"] is None and p.at["B", "ach_date_invalid"] == dt.date(2026, 1, 5)
    assert p.at["C", "planned_date"] is None and p.at["C", "planned_date_invalid"] is None


def test_invalid_dates_are_reported_and_not_counted(imported):
    codes = list(imported.gps.index[:3])
    last = imported.weeks[-1]
    plan = pd.DataFrame(
        {
            "category": ["Additional Plan"] * 3, "planned_date": [None, last.start, last.start], "ach_date": [None, None, None],
            "current_status": [None] * 3, "letter_status": [None] * 3, "letter_date": [None] * 3, "approval_status": [None] * 3,
            "planned_date_invalid": [dt.date(2020, 1, 11), None, None], "ach_date_invalid": [None] * 3,
        },
        index=pd.Index(codes, name=imported.amc_plan.index.name),
    )
    st = dataclasses.replace(imported, amc_plan=plan, _memo={}, _memo_locks={})
    s = amc_plan.amc_plan_summary(st, last.code)
    assert s["total"]["weekTarget"] == 2
    w = [x for x in s["warnings"] if "outside the file's period" in x]
    assert len(w) == 1 and str(codes[0]) in w[0] and "not counted as a target" in w[0]
    t = amc_plan.amc_plan_timeline(st, last.code)
    assert "2020-01" not in [m["id"] for m in t["monthly"]["months"]]
    assert any("outside the file's period" in x for x in t["warnings"])
