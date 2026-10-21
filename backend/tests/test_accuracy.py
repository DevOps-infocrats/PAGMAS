"""Accuracy tests against the real workbook (skipped when the file is absent).

Expected values are the figures in the workbook's own O&M / Master Block sheets.
"""

import datetime as dt

import pytest

from app.analytics.metrics import summarize
from app.analytics.reconcile import reconcile

from .conftest import login

STATES = {
    # state: (blocks, existing, revised, hoto blocks, hoto GPs, AMC, incremental, AMC RKM)
    "RAJASTHAN": (314, 8746, 8425, 314, 8425, 4710, 1235, 30195.88),
    "HARYANA": (142, 6082, 6082, 142, 6082, 1949, 305, 5394.60),
    "ASSAM": (145, 1495, 1471, 133, 1337, 82, 30, 356.32),
}


@pytest.mark.parametrize("state", STATES)
def test_structural_numbers_match_om_sheet(imported, state):
    s = summarize(imported, (imported.gps["circle"] == state).to_numpy(), imported.latest_week.code)
    exp = STATES[state]
    got = (s["totalBlocks"], s["totalGps"], s["revisedExisting"], s["hotoDoneBlocks"], s["hotoDoneGps"], s["amcGps"], s["incrementalGps"], s["amcRkm"])
    assert got == pytest.approx(exp)


def test_mtd_over_source_range_reproduces_om_sheet(imported):
    """With the source column's date range (1-6 Oct) the O&M MTD figures are reproduced exactly."""
    m = imported.mtd(dt.date(2026, 10, 6))
    expected = {"RAJASTHAN": (3506, 9), "HARYANA": (530, 329), "ASSAM": (26, 17)}
    for state, (above, zero) in expected.items():
        sel = imported.gps["circle"] == state
        assert int((m[sel] >= 98).sum()) == above
        assert int((m[sel] == 0).sum()) == zero


def test_weekly_bands_match_om_sheet(imported):
    from app.analytics.metrics import band_counts

    wf = imported.week_frame("W-41")
    sel = (imported.gps["circle"] == "RAJASTHAN") & wf["amc"]
    counts = band_counts(wf.loc[sel, "weekly"])
    assert list(counts.values()) == [7, 37, 99, 204, 186, 169, 275, 309, 3423]


def test_reconciliation_has_no_unexplained_mismatch(imported):
    rows = reconcile(imported)["rows"]
    assert rows, "no reconciliation rows"
    assert not [r for r in rows if r["status"] == "MISMATCH"]


def test_na_is_never_zero(imported):
    wf = imported.week_frame("W-41")
    s = summarize(imported, None, "W-41")
    assert s["naGps"] == int((wf["amc"] & wf["mtd"].isna()).sum())
    assert s["gpsAtZero"] == int((wf["mtd"] == 0).sum())


def test_api_payloads(imported, client):
    login(client)
    meta = client.get("/api/v1/meta").json()
    assert meta["latestWeekId"] == "W-41" and meta["dataAsOf"] == "2026-10-08"
    ov = client.get("/api/v1/overview", params={"week": "W-41", "compare": "W-40"}).json()
    k = {x["key"]: x for x in ov["kpis"]}
    assert k["totalGps"]["value"] == 16323 and len(k["totalGps"]["history"]) == 6
    circle = client.get("/api/v1/circles/rajasthan/insights").json()
    assert len(circle["blocks"]) == 314
    gp = client.get("/api/v1/gps/262368").json()
    assert gp["gp"]["amcCategory"] == "INCREMENTAL"
    pdf = client.get("/api/v1/reports/weekly.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_upload_and_activate_new_dataset(imported, client):
    """A valid workbook upload is stored under a random name, imported in the background and activated."""
    from .conftest import REAL_FILE

    csrf = login(client)
    with REAL_FILE.open("rb") as fh:
        r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("../../evil name.xlsb", fh, "application/octet-stream")})
    assert r.status_code == 202, r.text
    assert r.json()["fileName"] == "evil name.xlsb"  # path components stripped
    runs = client.get("/api/v1/ingestion/runs").json()
    newest = runs[0]
    assert newest["status"] == "SUCCESS" and newest["isActive"] and newest["accepted"] == 16323
    assert sum(1 for x in runs if x["isActive"]) == 1


def test_overview_summary_matches_workbook(imported, client):
    """Overview KPIs: GP split from Master Block, AMC split, HOTO and RKM totals."""
    login(client)
    o = client.get("/api/v1/overview", params={"week": "W-41", "compare": "W-40"}).json()
    s = o["summary"]
    assert (s["states"], s["blocks"]) == (3, 601)
    assert (s["totalGps"], s["existingGps"], s["newGps"], s["revisedExisting"]) == (17980, 16323, 1657, 15978)
    assert s["amcGps"] == s["amcOriginalGps"] + s["incrementalGps"] == 6741
    assert (s["amcOriginalGps"], s["incrementalGps"], s["nonAmcGps"]) == (5171, 1570, 9237)
    assert (s["hotoDoneBlocks"], s["hotoDoneGps"], s["hotoPendingGps"]) == (589, 15844, 134)
    assert s["totalRkm"] == 82606.9 and s["convertedOrClosed"] == 345
    by_state = {d["name"]: d for d in o["stateDetails"]}
    assert by_state["Rajasthan"]["totalGps"] == 10104 and by_state["Haryana"]["newGps"] == 173
    # state rows add up to the totals
    for k in ("totalGps", "amcGps", "hotoDoneGps", "gpsAbove98", "gpsAtZero", "penaltyBlocks"):
        assert sum(d[k] for d in o["stateDetails"]) == s[k], k


def test_circle_insights_rajasthan(imported, client):
    """Circle KPIs, district table and day-wise / weekly bands are internally consistent and match O&M."""
    login(client)
    c = client.get("/api/v1/circles/rajasthan/insights", params={"week": "W-41"}).json()
    s = c["summary"]
    assert (s["districts"], s["blocks"], s["totalGps"], s["existingGps"], s["newGps"], s["revisedExisting"]) == (33, 314, 10104, 8746, 1358, 8425)
    assert (s["hotoDoneGps"], s["hotoDoneBlocks"], s["amcGps"], s["incrementalGps"]) == (8425, 314, 4710, 1235)
    # district rows add up to the state
    d = c["hotoAmc"]
    assert sum(r["applicable"] for r in d) == 8425 and sum(r["amc"] for r in d) == 4710 and sum(r["newGps"] for r in d) == 1358
    # weekly bands = O&M "Till W-41" column
    w41 = c["gpBandTable"][-1]["counts"]
    assert [w41[b] for b in c["bands"]] == [7, 37, 99, 204, 186, 169, 275, 309, 3423]
    # day-wise: every AMC GP is either in a band or NA on each day of W-41
    days = c["gpDailyBands"]
    assert [x["date"] for x in days] == [f"2026-10-0{i}" for i in range(2, 9)]
    for x in days:
        assert sum(x["counts"][b] for b in c["bands"]) == x["reported"]
        assert x["reported"] + x["counts"]["NA"] == 4710
    for x in c["blockDailyBands"]:
        assert x["reported"] + x["counts"]["NA"] == 314


def test_circle_period_table_matches_om(imported, client):
    """Month/week columns computed from GP data reproduce the O&M HOTO/AMC and uptime tables."""
    login(client)
    c = client.get("/api/v1/circles/rajasthan/insights", params={"week": "W-41"}).json()
    t = c["periodTable"]
    col = {p["label"]: i for i, p in enumerate(t["periods"])}
    hoto = lambda lbl: t["hotoAmc"][col[lbl]]  # noqa: E731
    assert (hoto("Jun-26")["hotoDoneBlocks"], hoto("Jun-26")["hotoDoneGps"], hoto("Jun-26")["amcGps"], hoto("Jun-26")["amcRkm"]) == (210, 5762, 3263, 20860.15)
    assert (hoto("Aug-26")["hotoDoneBlocks"], hoto("Aug-26")["hotoDoneGps"], hoto("Aug-26")["amcGps"]) == (301, 8133, 4353)
    assert (hoto("WK-39")["amcGps"], hoto("WK-39")["amcRkm"]) == (4626, 29644.56)
    assert (hoto("WK-38")["hotoDoneBlocks"], hoto("WK-38")["amcGps"]) == (301, 4590)
    assert t["rfpTarget"]["value"] == 6559.5 and t["rfpTarget"]["periodKey"] == "2026-08"
    bands = c["bands"]
    gp = lambda lbl: [t["gpBands"][col[lbl]]["counts"][b] for b in bands]  # noqa: E731
    assert gp("Jun-26") == [3, 10, 34, 162, 220, 210, 405, 437, 1782]
    assert gp("Aug-26") == [10, 63, 99, 244, 305, 226, 467, 517, 2422]  # exactly-98 GP falls in 95–98 like O&M
    assert gp("Sep-26") == [1, 18, 77, 210, 337, 295, 582, 647, 2466]
    assert gp("Till W-41") == [7, 37, 99, 204, 186, 169, 275, 309, 3423]
    assert gp("WK-40") == [5, 47, 109, 208, 188, 188, 329, 296, 3340]
    blk = t["blockBands"][col["Till W-41"]]
    assert [blk["counts"][b] for b in bands] == [0, 0, 1, 12, 19, 24, 69, 79, 99] and blk["na"] == 11


def test_block_insights_recomputed_from_gp_rows(imported):
    """Block KPIs and GP-wise uptime are recomputed from GP rows with the same rules as the circle."""
    import numpy as np

    from app.analytics import views

    store = imported
    wk = store.latest_week.code
    for bid in ("rj-7458", store.gps["block_id"].iloc[0]):
        r = views.block_insights(store, bid, wk, store.weeks[-2].code)
        g = store.gps[store.gps["block_id"] == bid]
        wf = store.week_frame(wk).loc[g.index]
        s = r["summary"]
        assert s["existingGps"] == len(g)
        assert s["hotoDoneGps"] + s["hotoPendingGps"] == s["revisedExisting"]
        assert s["amcOriginalGps"] + s["incrementalGps"] + s["nonAmcGps"] == s["revisedExisting"]
        assert s["amcGps"] == int(wf["amc"].sum())
        assert s["totalRkm"] == pytest.approx(g["total_rkm"].sum(), abs=0.01)
        grp = r["amcGroups"]
        assert (len(grp["amc"]), len(grp["incremental"]), len(grp["nonAmc"])) == (s["amcOriginalGps"], s["incrementalGps"], s["nonAmcGps"])
        assert not set(grp["nonAmc"]) & (set(grp["amc"]) | set(grp["incremental"]))
        u = r["gpUptime"]
        td = next(i for i, c in enumerate(u["columns"]) if c["kind"] == "mtd")
        vals = [row["values"][td] for row in u["rows"]]
        nums = [v for v in vals if isinstance(v, float | int)]
        col = u["columns"][td]
        assert col["reported"] == len(nums)
        assert col["amcGps"] == sum(v is not None for v in vals)
        if nums:
            assert col["average"] == pytest.approx(np.mean(nums), abs=0.01)
            # identical to the GP snapshot MTD values (same formula on both sides)
            snap = [x["availability"] for x in r["gps"] if x["availability"] is not None]
            assert col["average"] == pytest.approx(np.mean(snap), abs=0.01)
        # NA is never 0 and non-AMC GPs never carry a value
        assert all(row["values"][td] is None for row in u["rows"] if row["amcDate"] is None)


def test_gp_uptime_matches_snapshot_and_block(imported):
    """GP uptime columns equal the GP's own MTD / weekly values and the block view's figures."""
    from app.analytics import views
    from app.analytics.metrics import band_of

    store = imported
    wk = store.latest_week.code
    for code in ("39894", "262723", "39891"):  # AMC, AMC, not under AMC
        d = views.gp_detail(store, code, wk, [])
        cols = {c["kind"] + ":" + c["key"]: c for c in d["uptime"]["columns"]}
        td = next(c for c in d["uptime"]["columns"] if c["kind"] == "mtd")
        wcol = next(c for c in d["uptime"]["columns"] if c["key"] == wk)
        snap = d["gp"]
        if snap["amcStatus"] == "AMC":
            assert td["value"] == snap["availability"]
            assert wcol["value"] == snap["weeklyAvailability"]
            assert td["band"] == band_of(td["value"])
        else:
            assert all(c["value"] is None and c["band"] is None for c in cols.values())
        for c in d["uptime"]["columns"]:
            if c["days"]:
                dd = c["days"]
                assert sum(dd["counts"].values()) == dd["reported"]
                assert dd["reported"] + dd["na"] == dd["underAmc"]
                if c["kind"] == "day" and isinstance(c["value"], float | int):
                    assert dd["counts"][c["band"]] == 1  # a day sits in exactly its own band
        if snap["amcStatus"] == "AMC":
            assert wcol["days"]["underAmc"] == 7  # a full reporting week
        blk = views.block_insights(store, snap["blockId"], wk, store.weeks[-2].code)["gpUptime"]
        assert [c["average"] for c in blk["columns"]] == [c["blockAverage"] for c in d["uptime"]["columns"]]
