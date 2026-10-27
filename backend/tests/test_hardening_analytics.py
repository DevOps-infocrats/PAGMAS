"""Analytics hardening: null-safe lists, plan vs achieved without plan rows, matched Overall %, block bands,
chronological week order across the year end, year rollover, AMC split masks, sort / search / threshold rules,
and the snapshot's active-dataset check."""

import dataclasses
import datetime as dt
import json
import threading

import numpy as np
import pandas as pd
import pytest

from app.analytics import store as store_mod
from app.analytics.metrics import BANDS
from app.analytics.store import Week
from app.config import get_settings

from .conftest import login
from .test_escalation import ESC_FILE

W, C = "W-41", "W-40"


@pytest.fixture(scope="module")
def escalation(imported):
    """The Escalation Matrix as the active import (uploaded here unless an earlier module already did)."""
    if not ESC_FILE.exists():
        pytest.skip("Escalation Matrix file not available")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://localhost", headers={"origin": "http://localhost:3000"}) as c:
        csrf = login(c)
        with ESC_FILE.open("rb") as fh:
            r = c.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("Escalation.xlsx", fh, "application/octet-stream")})
    assert r.status_code == 202 or (r.status_code == 409 and "active one" in r.text), r.text


def _copy(store, **changes):
    return dataclasses.replace(store, **changes, _week_cache={}, _memo={}, _memo_locks={})


@pytest.fixture(scope="module")
def plan_file():
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "data" / "review_plan.json"
    if not src.exists():
        pytest.skip("data/review_plan.json not available")
    dst = get_settings().data_dir / "review_plan.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    return dst


# ---------------------------------------------------------------- 1. blank Master Block cells


def test_new_gp_blocks_with_blank_master_block_counts(imported):
    from app.analytics.drilldown import kpi_list, kpi_xlsx

    mb = imported.master_blocks.copy()
    for c in ("existing_gps", "total_gp_count"):
        mb[c] = mb[c].astype(object)
    i = mb.index[0]
    mb.loc[i, "new_gps"] = max(3, mb.loc[i, "new_gps"] or 0)
    mb.loc[i, ["existing_gps", "total_gp_count"]] = None
    st = _copy(imported, master_blocks=mb)
    body = kpi_list(st, "new-gp-blocks", W, None, None, None, None, None, 1, 500)
    json.dumps(body, allow_nan=False)
    code = str(mb.loc[i, "block_code"])
    item = next(x for x in body["items"] if x["code"] == code)
    assert item["existingGps"] is None and item["totalGps"] is None and item["newGps"] == mb.loc[i, "new_gps"]
    assert kpi_xlsx(st, "new-gp-blocks", W, None, None, None, None, None)[0][:2] == b"PK"


# ---------------------------------------------------------------- 2 / 3. plan vs achieved, matched Overall %


def test_plan_achieved_is_none_without_file_plan_for_the_state(imported, plan_file):
    from app.analytics.metrics import r2
    from app.analytics.review import _circle_list
    from app.analytics.review_periods import reporting_periods
    from app.analytics.review_targets import targets_page

    d = dt.date
    rj = list(imported.gps.index[imported.gps["circle"] == "RAJASTHAN"][:4])
    hr = list(imported.gps.index[imported.gps["circle"] == "HARYANA"][:1])
    plan = pd.DataFrame(
        {
            # Rajasthan: Oct plan in the file; Haryana: plan rows only for November (its Oct plan comes from review_plan.json)
            "planned_date": [d(2026, 10, 3), d(2026, 10, 4), d(2026, 10, 5), d(2026, 10, 6), d(2026, 11, 3)],
            "ach_date": [d(2026, 10, 3), d(2026, 10, 6), None, None, d(2026, 10, 3)],
            "category": "Incremental",
            "current_status": None,
            "letter_status": None,
            "letter_date": None,
        },
        index=[*rj, *hr],
    )
    st = _copy(imported, amc_plan=plan)
    tp = targets_page(st, reporting_periods(st, st.week(W), st.week(C)), _circle_list(st))
    rows = {r["code"]: r for r in tp["roadmap"]["rows"]}
    total = tp["roadmap"]["total"]
    assert rows["RJ"]["mtdPlan"] == 4 and rows["RJ"]["planAchieved"] == 2 and rows["RJ"]["planAchievedPct"] == 50.0
    assert rows["HR"]["planAchieved"] is None and rows["HR"]["planAchievedPct"] is None  # plan from review_plan.json
    assert rows["AS"]["planAchieved"] is None  # no GP-wise plan rows at all – not "0 achieved"
    assert total["planAchieved"] == 2
    assert total["planAchievedPct"] == 50.0  # only states with both plan and achieved
    with_proj = [r for r in rows.values() if r["projection"] is not None]
    if with_proj:
        assert total["projectedCoveragePct"] == r2(sum(r["projection"] for r in with_proj) / sum(r["revisedScope"] for r in with_proj) * 100)


def test_paired_overall_pct():
    from app.analytics.review_targets import _paired_pct

    rows = [{"a": 50, "b": 100}, {"a": None, "b": 300}, {"a": 10, "b": None}, {"a": 30, "b": 100}]
    assert _paired_pct(rows, "a", "b") == 40.0
    assert _paired_pct([{"a": None, "b": 5}], "a", "b") is None


def test_amc_conversion_overall_pct_uses_planned_circles_only(imported, monkeypatch):
    from app.analytics import amc_conversion as ac
    from app.analytics.review_targets import _Plan

    plan = _Plan(monthlyPlan={"2026-09": {"RAJASTHAN": 100}}, weeklyClosureTargets={W: {"RAJASTHAN": 10}})
    monkeypatch.setattr(ac, "effective_plan", lambda store: (plan, None, {}))
    r = ac.amc_conversion(imported, W, C)
    rj = next(x for x in r["monthly"]["rows"] if x["code"] == "RJ")["months"][0]
    tot = r["monthly"]["total"]["months"][0]
    assert tot["planPartial"] and tot["plan"] == 100
    assert tot["achievedPct"] == rj["achievedPct"] and tot["gap"] == rj["gap"]
    assert tot["achieved"] >= rj["achieved"]  # the executed count itself still covers every circle
    rj_w = next(x for x in r["weekly"]["rows"] if x["code"] == "RJ")["weeks"][0]
    assert r["weekly"]["total"]["weeks"][0]["achievedPct"] == rj_w["achievedPct"]


# ---------------------------------------------------------------- 6. block uptime trend includes 0% blocks


def test_block_trend_counts_zero_blocks_below_penalty(imported):
    from app.analytics.views import _band_series

    g = imported.gps
    wf = imported.week_frame(W)
    rj = g["circle"] == "RAJASTHAN"
    block = g.loc[rj & wf["amc"], "block_id"].iloc[0]
    weekly = imported.weekly.copy()
    weekly.loc[g.index[g["block_id"] == block], W] = 0.0
    st = _copy(imported, weekly=weekly)
    series, table = _band_series(st, rj.to_numpy(), st.weeks, per_block=True)
    pen = get_settings().penalty_threshold
    low_bands = [lb for lb, lo, hi in BANDS if hi <= pen]
    assert "0%" in low_bands and table[-1]["counts"]["0%"] >= 1
    low = next(s for s in series if s["name"].startswith("<"))
    assert [p["value"] for p in low["points"]] == [sum(t["counts"][b] for b in low_bands) for t in table]
    gp_series, _ = _band_series(st, rj.to_numpy(), st.weeks, per_block=False)
    assert any(s["name"] == "0%" for s in gp_series)  # GPs keep their own 0% series


# ---------------------------------------------------------------- 7. week order across the year end


def _wrapped(store):
    """The same data with weeks numbered across a year end: …, W-51, W-52, W-1, W-2."""
    n = len(store.weeks)
    nums = [(i - (n - 2)) % 52 + 1 for i in range(n)]
    weeks = [Week(f"W-{k}", k, w.start, w.end) for k, w in zip(nums, store.weeks)]
    weekly = store.weekly.rename(columns={w.code: f"W-{k}" for k, w in zip(nums, store.weeks)})
    return _copy(store, weeks=weeks, weekly=weekly), nums


def test_store_weeks_are_chronological(imported):
    starts = [w.start for w in imported.weeks]
    assert starts == sorted(starts) and imported.latest_week is imported.weeks[-1]
    assert imported.week_index(imported.weeks[-1].code) == len(imported.weeks) - 1


def test_week_helpers_across_year_end(imported):
    from app.analytics import amc_plan
    from app.analytics.views import history_weeks

    st, nums = _wrapped(imported)
    first, last = st.weeks[0], st.weeks[-1]
    assert st.latest_week.code == "W-2"
    assert history_weeks(st, "W-2") == st.weeks
    assert history_weeks(st, "W-52") == st.weeks[: len(st.weeks) - 2]
    seven = dt.timedelta(days=7)
    assert st.week_by_number(3).start == last.start + seven
    prev_n = (nums[0] - 2) % 52 + 1
    assert st.week_by_number(prev_n).start == first.start - seven
    assert st.week_containing(last.end + dt.timedelta(days=1)).code == "W-3"
    assert st.week_containing(first.start - dt.timedelta(days=1)).number == prev_n
    for back in (1, 10, 60, 120):  # never W-0 / negative weeks
        code, number, start, _ = amc_plan._week_of(st, first.start - back * seven)
        assert 1 <= number <= 52 and code == f"W-{number}" and start == first.start - back * seven


def test_weekly_closure_columns_follow_dates_across_year_end(imported):
    from app.analytics.review_periods import reporting_periods
    from app.analytics.review_targets import _Plan, _weekly_columns

    st, _ = _wrapped(imported)
    p = reporting_periods(st, st.week("W-2"), st.week("W-1"))
    plan = _Plan(weeklyClosureTargets={"W-1": {"RAJASTHAN": 6}, "W-52": {"RAJASTHAN": 5}})
    cols = _weekly_columns(st, p, plan, p.cutoff.replace(day=1), p.cutoff)
    assert [c["id"] for c in cols] == ["W-52", "W-1", "W-2", "W-3", "W-4"]
    starts = [c["start"] for c in cols]
    assert starts == sorted(starts) and [c["id"] for c in cols if c["current"]] == ["W-2"]


def test_amc_conversion_weeks_follow_dates_across_year_end(imported, monkeypatch):
    from app.analytics import amc_conversion as ac
    from app.analytics.review_targets import _Plan

    st, _ = _wrapped(imported)
    plan = _Plan(weeklyClosureTargets={"W-3": {"RAJASTHAN": 1}, "W-1": {"RAJASTHAN": 2}, "W-52": {"RAJASTHAN": 3}})
    monkeypatch.setattr(ac, "effective_plan", lambda store: (plan, None, {}))
    weeks = ac.amc_conversion(st, "W-2", "W-1")["weekly"]["weeks"]
    assert [w["id"] for w in weeks] == ["W-52", "W-1", "W-3"]
    assert weeks[2]["start"] == (st.weeks[-1].start + dt.timedelta(days=7)).isoformat()


def test_picked_amc_plan_date_is_clamped_to_first_week(imported):
    from app.analytics.amc_plan import available_dates, windows

    first = imported.weeks[0].start
    assert min(available_dates(imported)) >= first.isoformat()
    win = windows(imported, W, first - dt.timedelta(days=40))
    assert win.as_of == first and win.week_start == first


# ---------------------------------------------------------------- 8. year rollover


def test_one_time_up_uses_latest_september_not_after_data_date(imported):
    base = imported.one_time_up_sept
    assert base.sum() > 0
    monthly = imported.monthly.copy()
    monthly["2027-09"] = 100.0
    jan = _copy(imported, data_as_of=dt.date(2027, 1, 10), monthly=monthly)
    assert jan.one_time_up_sept.equals(base)  # Jan 2027 -> September 2026
    octo = _copy(imported, data_as_of=dt.date(2027, 10, 1), monthly=monthly)
    assert bool(octo.one_time_up_sept.all())  # Oct 2027 -> September 2027


def test_target_month_year_is_closest_to_data_date():
    from app.analytics.review_summary import _target_month

    assert _target_month("Target for Operational GP (Oct-26Target)", dt.date(2027, 1, 5)) == "2026-10"
    assert _target_month("Target for Operational GP (Jan Target)", dt.date(2026, 12, 20)) == "2027-01"
    assert _target_month("Target for Operational GP (Dec Target)", dt.date(2027, 1, 5)) == "2026-12"
    assert _target_month("Target for Operational GP (Oct Target)", dt.date(2026, 10, 8)) == "2026-10"


def test_review_target_is_month_keyed(imported):
    from app.analytics.review import _source_targets

    rep = pd.DataFrame(
        [
            ("RAJASTHAN", "Target for Operational GP (Oct-26Target)", 600.0, None),
            ("RAJASTHAN", "Target for Operational GP (Sep-26Target)", 500.0, None),
        ],
        columns=["state", "metric", "value_num", "value_text"],
    )
    st = _copy(imported, reported=rep)
    assert _source_targets(st, dt.date(2026, 10, 8)) == ({"RAJASTHAN": 600.0}, "Operational GP target (Oct-26)", True)
    assert _source_targets(st, dt.date(2026, 9, 20))[0] == {"RAJASTHAN": 500.0}
    assert _source_targets(st, dt.date(2026, 11, 2))[2] is False  # no Nov target: latest one, flagged


# ---------------------------------------------------------------- 9 / 10 / 11. AMC split masks, report unit


def test_blank_category_amc_gp_counts_as_amc_original(imported):
    from app.analytics.views import block_insights

    g = imported.gps.copy()
    wf = imported.week_frame(W)
    code = g.index[wf["amc"] & (g["amc_category"] != "INCREMENTAL")][0]
    g.loc[code, "amc_category"] = None
    st = _copy(imported, gps=g)
    r = block_insights(st, g.loc[code, "block_id"], W, C)
    cats = {c["label"]: c["count"] for c in r["classification"]}
    assert code in r["amcGroups"]["amc"]
    assert cats["AMC (original)"] == len(r["amcGroups"]["amc"]) and cats["Incremental"] == len(r["amcGroups"]["incremental"])
    assert cats["Non-AMC"] == len(r["amcGroups"]["nonAmc"])


def test_circle_hoto_amc_non_amc_uses_metrics_mask(imported):
    from app.analytics.views import circle_insights

    g = imported.gps
    wf = imported.week_frame(W)
    r = circle_insights(imported, "assam", W, C)
    for row in r["hotoAmc"]:
        m = g["district_id"] == row["districtId"]
        assert row["nonAmc"] == int((g.loc[m, "revised"] & ~wf.loc[m[m].index, "amc"]).sum())


def test_weekly_report_ranks_blocks_for_district_scope(imported):
    from app.analytics.views import weekly_report

    did = imported.gps["district_id"].iloc[0]
    r = weekly_report(imported, W, C, None, did, None, [])
    blocks = set(imported.gps.loc[imported.gps["district_id"] == did, "block_id"])
    assert r["ranking"] and {x["id"] for x in r["ranking"]} == blocks


# ---------------------------------------------------------------- 13. area-manager sort


def test_area_managers_zero_availability_sorts_before_none(imported):
    from app.analytics.views import overview

    g = imported.gps.copy()
    wf = imported.week_frame(W)
    rj = g["circle"] == "RAJASTHAN"
    zero_gp = g.index[rj & wf["amc"]][0]
    none_gp = g.index[rj & ~wf["amc"] & g["revised"]][0]
    g["am_name"] = g["am_name"].astype(object)
    g.loc[zero_gp, "am_name"], g.loc[none_gp, "am_name"] = "ZZ Zero", "AA None"
    daily = imported.daily.copy()
    daily.loc[zero_gp] = 0.0
    st = _copy(imported, gps=g, daily=daily)
    ams = [m for m in overview(st, W, C)["areaManagers"] if m["circleId"] == "rajasthan"]
    labels = [m["manager"]["label"] for m in ams]
    zero, none = ams[labels.index("ZZ Zero")], ams[labels.index("AA None")]
    assert zero["availability"] == 0.0 and none["availability"] is None
    assert labels.index("ZZ Zero") < labels.index("AA None")
    vals = [m["availability"] for m in ams]
    known = [v for v in vals if v is not None]
    assert known == sorted(known, reverse=True) and vals[len(known):] == [None] * (len(vals) - len(known))


# ---------------------------------------------------------------- 15. search case / escalation threshold


def test_gp_code_search_is_case_insensitive(imported):
    from app.analytics.views import list_gps, search

    g = imported.gps.copy()
    old = g.index[0]
    g.index = pd.Index(["GPx-AbC9" if c == old else c for c in g.index], name=g.index.name)
    st = _copy(imported, gps=g)
    for q in ("gpx-abc9", "GPX-ABC9", "abc9"):
        assert [i["id"] for i in list_gps(st, W, None, None, None, q, 1, 20)["items"]] == ["GPx-AbC9"], q
    assert any(h["id"] == "GPx-AbC9" for h in search(st, "gpx-ab"))


def test_escalation_uses_penalty_threshold(imported, escalation, monkeypatch):
    from app.analytics import escalation as esc

    def count(threshold: float) -> int:
        _, df = esc._frame(imported)
        mtd = esc._mtd(imported, W).reindex(df.index)
        return int((mtd < threshold).sum())

    base = esc.down(imported, W, "below90", None, None, None, None, 1, 10, False)["total"]
    assert base == count(get_settings().penalty_threshold)
    real = get_settings()
    monkeypatch.setattr(esc, "get_settings", lambda: type("S", (), {"penalty_threshold": 95.0, "healthy_threshold": real.healthy_threshold})())
    assert esc.down(imported, W, "below90", None, None, None, None, 1, 10, False)["total"] == count(95.0) >= base
    frt = esc.workload(imported, W, "frt", None, False)["items"]
    assert sum(p["gpsBelow90"] for p in frt) <= count(95.0)


# ---------------------------------------------------------------- 16. snapshot follows the active dataset


def test_store_reloads_when_another_process_activates_a_dataset(imported, monkeypatch):
    new_id = imported.dataset_id + 1000
    fresh = _copy(imported, dataset_id=new_id)
    started, release = threading.Event(), threading.Event()

    def slow_load():
        started.set()
        assert release.wait(10)
        return fresh

    # Snapshot loads started by earlier tests (every TestClient start-up reloads in a thread) must finish first.
    assert store_mod._load_lock.acquire(timeout=300)
    try:
        monkeypatch.setattr(store_mod, "_cache", imported)
        monkeypatch.setattr(store_mod, "_checked_at", float("-inf"))
        monkeypatch.setattr(store_mod, "_failed_at", float("-inf"))
        monkeypatch.setattr(store_mod, "_active_dataset_id", lambda: new_id)
        monkeypatch.setattr(store_mod, "_load", slow_load)
        monkeypatch.setattr(store_mod, "warm", lambda s: None)
    finally:
        store_mod._load_lock.release()

    assert store_mod.get_store() is imported  # served from the current snapshot while the new one loads
    assert started.wait(5)
    assert store_mod.get_store() is imported  # throttled: no second check / load
    release.set()
    for _ in range(100):
        if store_mod._cache is fresh:
            break
        threading.Event().wait(0.05)
    assert store_mod.get_store() is fresh

    # A failed load keeps the current snapshot and backs off.
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(store_mod, "_load", broken)
    monkeypatch.setattr(store_mod, "_active_dataset_id", lambda: new_id + 1)
    monkeypatch.setattr(store_mod, "_checked_at", float("-inf"))
    assert store_mod.get_store() is fresh
    for _ in range(100):
        if store_mod._failed_at != float("-inf") and not store_mod._load_lock.locked():
            break
        threading.Event().wait(0.05)
    assert store_mod._failed_at != float("-inf") and store_mod.get_store() is fresh
    monkeypatch.setattr(store_mod, "_checked_at", float("-inf"))
    calls = []
    monkeypatch.setattr(store_mod, "_active_dataset_id", lambda: calls.append(1) or new_id + 1)
    store_mod.get_store()
    assert not calls  # within the back-off window: not even the check query runs
    assert np.isfinite(store_mod._failed_at)
