"""KPI drill-down lists (Circle Overview cards -> list of GPs / blocks + Excel)."""

import io
import zipfile

from app.analytics.metrics import summarize

from .conftest import login


def test_list_totals_equal_the_cards(imported, client):
    login(client)
    s = summarize(imported, None, "W-41")
    for kind, key in (("gps-above-98", "gpsAbove98"), ("gps-at-zero", "gpsAtZero"), ("penalty-blocks", "penaltyBlocks"), ("hoto-gps", "hotoDoneGps"), ("hoto-blocks", "hotoDoneBlocks")):
        r = client.get(f"/api/v1/kpi-lists/{kind}", params={"week": "W-41"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cardTotal"] == s[key] == body["total"], kind
        assert len(body["items"]) == min(50, body["total"])


def test_rules_and_sorting(imported, client):
    login(client)
    above = client.get("/api/v1/kpi-lists/gps-above-98", params={"week": "W-41", "page_size": 200}).json()
    vals = [i["availability"] for i in above["items"]]
    assert all(v > 98 for v in vals) and vals == sorted(vals, reverse=True)  # strictly above 98, best first
    zero = client.get("/api/v1/kpi-lists/gps-at-zero", params={"week": "W-41", "page_size": 200}).json()
    assert all(i["availability"] == 0 for i in zero["items"])  # exactly 0 – NA never listed
    blocks = client.get("/api/v1/kpi-lists/penalty-blocks", params={"week": "W-41", "page_size": 200}).json()
    assert blocks["unit"] == "block" and all(i["availability"] < 90 for i in blocks["items"])
    assert [i["availability"] for i in blocks["items"]] == sorted(i["availability"] for i in blocks["items"])  # worst first


def test_filters_only_narrow_the_list(imported, client):
    login(client)
    full = client.get("/api/v1/kpi-lists/gps-above-98", params={"week": "W-41"}).json()
    parts = [client.get("/api/v1/kpi-lists/gps-above-98", params={"week": "W-41", "circle": c}).json() for c in ("rajasthan", "haryana", "assam")]
    assert sum(p["total"] for p in parts) == full["total"]
    assert all(p["cardTotal"] == full["cardTotal"] for p in parts)
    rj = parts[0]
    assert all(i["circleId"] == "rajasthan" for i in rj["items"])
    name = rj["items"][0]["name"]
    hit = client.get("/api/v1/kpi-lists/gps-above-98", params={"week": "W-41", "circle": "rajasthan", "search": name[:4]}).json()
    assert any(i["name"] == name for i in hit["items"])


def test_excel_download(imported, client):
    login(client)
    r = client.get("/api/v1/kpi-lists/gps-at-zero.xlsx", params={"week": "W-41"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    assert 'filename="Pratap_gps-at-zero_W-41_' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        strings = z.read("xl/sharedStrings.xml").decode()
    assert "<f>" not in sheet  # text is never written as a formula
    assert "GPs at 0% Availability (MTD)" in strings
    rows = client.get("/api/v1/kpi-lists/gps-at-zero", params={"week": "W-41"}).json()["total"]
    assert sheet.count("<row ") == 4 + rows  # 3 title lines + header (the blank line is not stored), then one row per GP


def test_drilldown_requires_session_and_validates_input(client):
    assert client.get("/api/v1/kpi-lists/gps-above-98").status_code == 401
    assert client.get("/api/v1/kpi-lists/gps-above-98.xlsx").status_code == 401
    login(client)
    assert client.get("/api/v1/kpi-lists/all-gps").status_code == 422
    assert client.get("/api/v1/kpi-lists/gps-above-98", params={"sort": "drop table"}).status_code == 422
    assert client.get("/api/v1/kpi-lists/gps-above-98", params={"circle": "../etc"}).status_code == 422
    assert client.get("/api/v1/kpi-lists/gps-above-98", params={"page_size": 5000}).status_code == 422


def test_hoto_lists(imported, client):
    login(client)
    end = imported.week("W-41").end.isoformat()
    gps = client.get("/api/v1/kpi-lists/hoto-gps", params={"week": "W-41", "page_size": 200, "sort": "value-desc"}).json()
    assert gps["unit"] == "gp" and all(i["hotoDate"] and i["hotoDate"] <= end for i in gps["items"])
    dates = [i["hotoDate"] for i in gps["items"]]
    assert dates == sorted(dates, reverse=True)  # latest handover first
    assert all(i["amcDate"] is None or i["amcDate"] <= end for i in gps["items"])  # AMC date only when under AMC by the week end
    blocks = client.get("/api/v1/kpi-lists/hoto-blocks", params={"week": "W-41", "page_size": 200}).json()
    assert blocks["unit"] == "block"
    for b in blocks["items"]:
        assert 1 <= b["hotoGps"] <= b["totalGps"] and b["hotoPct"] == round(b["hotoGps"] / b["totalGps"] * 100, 2)
    rj = client.get("/api/v1/kpi-lists/hoto-blocks", params={"week": "W-41", "circle": "rajasthan"}).json()
    assert rj["total"] == 314  # every Rajasthan block has at least one HOTO-done GP (O&M)
    x = client.get("/api/v1/kpi-lists/hoto-gps.xlsx", params={"week": "W-41", "circle": "assam"})
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_state_lists_equal_the_circle_insights_cards(imported, client):
    """Circle Insights -> Summary cards open the list for that state: the list total equals the card."""
    login(client)
    pairs = (("gps-above-98", "gpsAbove98"), ("gps-at-zero", "gpsAtZero"), ("penalty-blocks", "penaltyBlocks"), ("hoto-gps", "hotoDoneGps"), ("hoto-blocks", "hotoDoneBlocks"))
    for circle in ("rajasthan", "haryana", "assam"):
        card = client.get(f"/api/v1/circles/{circle}/insights", params={"week": "W-41"}).json()["summary"]
        for kind, key in pairs:
            body = client.get(f"/api/v1/kpi-lists/{kind}", params={"week": "W-41", "circle": circle}).json()
            assert body["total"] == card[key], (circle, kind)


def test_missing_dates_are_null_not_nan(imported, client):
    """GPs handed over but not yet under AMC have no AMC date: the API must send null (NaN is not valid JSON)."""
    login(client)
    r = client.get("/api/v1/kpi-lists/hoto-gps", params={"week": "W-41", "page_size": 200})
    assert r.status_code == 200 and "NaN" not in r.text
    assert any(i["amcDate"] is None for i in r.json()["items"])


def test_amc_gp_list_and_amc_at_hoto_counts(imported, client):
    login(client)
    g = imported.gps
    wf = imported.week_frame("W-41")
    expected = int((wf["amc"] & (g["amc_category"] != "INCREMENTAL")).sum())
    overview = client.get("/api/v1/overview", params={"week": "W-41"}).json()
    s = overview["summary"]
    assert s["amcAtHotoGps"] == expected == s["amcOriginalGps"]
    assert sum(state["amcAtHotoGps"] for state in overview["stateDetails"]) == expected
    # The AMC page cards add up: AMC at HOTO + Incremental + Non-AMC + NP/closed = existing GPs.
    for d in [s, *overview["stateDetails"]]:
        assert d["amcAtHotoGps"] + d["incrementalGps"] + d["nonAmcGps"] + d["convertedOrClosed"] == d["existingGps"]
        assert d["hotoDoneGps"] + d["hotoPendingGps"] + d["convertedOrClosed"] == d["existingGps"]

    rows = client.get("/api/v1/kpi-lists/amc-gps", params={"week": "W-41", "page_size": 200}).json()
    assert rows["total"] == summarize(imported, None, "W-41")["amcGps"]
    assert all(row["category"] in {"AMC", "INCREMENTAL"} for row in rows["items"])
    assert all(row["amcDate"] and row["amcDate"] <= imported.week("W-41").end.isoformat() for row in rows["items"])
    assert client.get("/api/v1/kpi-lists/amc-gps.xlsx", params={"week": "W-41"}).content[:2] == b"PK"


def test_state_comparison_figures(imported, client):
    """State Performance Comparison: GP and block thresholds computed separately, states add up to the total."""
    login(client)
    o = client.get("/api/v1/overview", params={"week": "W-41"}).json()
    g = imported.gps
    wf = imported.week_frame("W-41")
    mtd = wf["mtd"].where(wf["amc"])
    block_mean = mtd.groupby(g["block_id"]).mean()
    s = o["summary"]
    assert s["gpsBelowPenalty"] == int((mtd < 90).sum())  # 0% GPs included, NA never counted
    assert s["reportingGps"] == int(mtd.notna().sum())
    assert s["blocksAbove98"] == int((block_mean > 98).sum())  # block mean, not "any GP above 98%"
    assert s["reportingBlocks"] == int(block_mean.notna().sum())
    for key in ("gpsBelowPenalty", "blocksAbove98", "reportingGps", "reportingBlocks", "hotoPendingBlocks", "nonAmcGps", "gpsAtZero", "gpsAbove98"):
        assert sum(d[key] for d in o["stateDetails"]) == s[key], key


def test_hoto_block_rows_include_gp_details_and_hoto_pending_reason(imported, client):
    login(client)
    response = client.get("/api/v1/kpi-lists/hoto-blocks", params={"week": "W-41", "page_size": 200})
    assert response.status_code == 200, response.text
    for block in response.json()["items"]:
        assert len(block["gpDetails"]) == block["totalGps"]
        assert sum(gp["hotoDate"] is not None for gp in block["gpDetails"]) == block["hotoGps"]
        assert all(gp["code"] and gp["name"] for gp in block["gpDetails"])

    pending = client.get("/api/v1/kpi-lists/hoto-pending-gps", params={"week": "W-41", "page_size": 200}).json()
    assert all(row["reason"] == "HOTO not done" for row in pending["items"])
    assert "amName" not in pending["items"][0] if pending["items"] else True


def test_state_detail_lists_equal_the_overview_tables(imported, client):
    """States & Network Health tables -> state page: every list total equals the figure in the table row."""
    login(client)
    states = client.get("/api/v1/overview", params={"week": "W-41"}).json()["stateDetails"]
    pairs = (("existing-gps", "existingGps"), ("na-gps", "naGps"), ("one-time-up", "oneTimeUp"), ("gps-above-98", "gpsAbove98"), ("gps-at-zero", "gpsAtZero"), ("penalty-blocks", "penaltyBlocks"))
    for st in states:
        for kind, key in pairs:
            body = client.get(f"/api/v1/kpi-lists/{kind}", params={"week": "W-41", "circle": st["id"]}).json()
            assert body["total"] == st[key], (st["id"], kind)
        new = client.get("/api/v1/kpi-lists/new-gp-blocks", params={"week": "W-41", "circle": st["id"]}).json()
        assert new["valueTotal"] == st["newGps"] and new["unit"] == "block", st["id"]
    ex = client.get("/api/v1/kpi-lists/existing-gps", params={"week": "W-41", "page_size": 200}).json()
    assert {i["status"] for i in ex["items"]} <= {"In scope", "Converted to NP", "Closed / removed", "Deducted (portal entry)"}
    assert client.get("/api/v1/kpi-lists/new-gp-blocks.xlsx", params={"week": "W-41"}).content[:2] == b"PK"


def test_handover_state_lists_equal_the_overview_tables(imported, client):
    """Handover & Scope tables (HOTO, converted / closed) -> state page: list totals equal the table row."""
    login(client)
    states = client.get("/api/v1/overview", params={"week": "W-41"}).json()["stateDetails"]
    pairs = (("hoto-gps", "hotoDoneGps"), ("hoto-pending-gps", "hotoPendingGps"), ("hoto-blocks", "hotoDoneBlocks"), ("removed-gps", "convertedOrClosed"))
    for st in states:
        for kind, key in pairs:
            body = client.get(f"/api/v1/kpi-lists/{kind}", params={"week": "W-41", "circle": st["id"]}).json()
            assert body["total"] == st[key], (st["id"], kind)
    removed = client.get("/api/v1/kpi-lists/removed-gps", params={"week": "W-41", "page_size": 200}).json()
    assert removed["items"] and {i["status"] for i in removed["items"]} <= {"Converted to NP", "Closed / removed", "Deducted (portal entry)"}
    assert all(i["remark"] for i in removed["items"])
    assert client.get("/api/v1/kpi-lists/removed-gps.xlsx", params={"week": "W-41"}).content[:2] == b"PK"
