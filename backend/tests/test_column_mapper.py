"""Column mapper (Data Operations → Column names): recognise renamed sheets / columns, add the admin's choice to
column_map.json safely, and re-process a finished import without losing data when it fails."""

import json

import pytest
import xlsxwriter

from app.config import get_settings
from app.ingestion import column_map as cm
from app.ingestion import column_mapper as mapper

from .conftest import VIEWER, login

GP_HEADER = [
    "Circle", "BA", "District", "Block", "Block Code", "GP", "GP Code", "TOTAL RKM", "HOTO Date", "AMC Date", "AM Name", "W-40", "W-41",
]
ROWS = [
    ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One", "10001", 12.5, "01-04-2026", "15-05-2026", "Ravi", 99.1, 98.2],
    ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp Two", "10002", 8.0, "02-04-2026", "16-05-2026", "Ravi", 97.0, 96.5],
    ["HARYANA", "Ambala", "Ambala", "Naraingarh", "502", "Gp Three", "10003", 4.25, "03-04-2026", "17-05-2026", "Mohan", 0.0, 50.0],
]


def _book(path, sheets: dict[str, list[list]]) -> None:
    wb = xlsxwriter.Workbook(str(path))
    for name, rows in sheets.items():
        ws = wb.add_worksheet(name)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                ws.write(r, c, v)
    wb.close()


def _master(tmp_path, rename: dict[str, str] | None = None, sheet: str = "GP Wise Data"):
    header = [rename.get(h, h) for h in GP_HEADER] if rename else GP_HEADER
    path = tmp_path / "master.xlsx"
    _book(path, {sheet: [["Title row"], [], header, *ROWS]})
    return path


ESC_HEADER = ["Circle", "BA", "District", "Block Code", "GP", "GP Code", "FRT Code", "FE name", "FE Number", "AM Name", "AM Number", "AM Email ID"]
ESC_ROWS = [["HARYANA", "Ambala", "Ambala", "501", "Gp One", "10001", "F-1", "Fe A", "9876543210", "Ravi", "9876500000", "ravi@x.in"]]


@pytest.fixture(autouse=True)
def clean_map():
    """Every test starts and ends without data/column_map.json (the test data folder, never the real one)."""
    path = cm.map_path()
    assert "pratap-test-" in str(path)  # safety: tests must never touch the real data folder

    def wipe():
        for p in (path, path.with_suffix(".json.bak"), path.with_suffix(".json.tmp")):
            p.unlink(missing_ok=True)
        with cm._lock:
            cm._cache.update(map=None, mtime=None)

    wipe()
    yield
    wipe()


def _field(report, section, field):
    sec = next(s for s in report["sections"] if s["key"] == section)
    return next(f for f in sec["fields"] if f["field"] == field)


def test_check_recognises_a_normal_file(tmp_path):
    r = mapper.check(_master(tmp_path))
    assert r["kind"] == "master" and r["ready"] and r["missingRequired"] == 0
    f = _field(r, "gp", "amc_date")
    assert f["status"] == "found" and f["header"] == "AMC Date" and f["fit"]["kind"] == "date" and not f["fit"]["warning"]
    gp = r["sections"][0]
    assert all(c["header"] not in ("W-40", "W-41") for c in gp["columns"])  # period columns are not mapper material


def test_renamed_column_is_suggested_never_applied(tmp_path):
    r = mapper.check(_master(tmp_path, {"AMC Date": "AMC Dt"}))
    assert not r["ready"] and r["missingRequired"] == 1
    f = _field(r, "gp", "amc_date")
    assert f["status"] == "missing" and f["required"] and f["suggestion"] == "AMC Dt" and f["similarity"] >= 70
    col = next(c for c in r["sections"][0]["columns"] if c["header"] == "AMC Dt")
    assert col["samples"][0] == "15-05-2026" and col["fit"]["amc_date"]["pct"] == 100
    assert not cm.map_path().exists()  # checking never writes


def test_renamed_anchor_and_sheet_are_found(tmp_path):
    """A renamed header-row anchor (GP Code) and a renamed GP sheet: the file is still read, with suggestions."""
    r = mapper.check(_master(tmp_path, {"GP Code": "GP_Code"}, sheet="GP Data"))
    assert r["kind"] == "master"
    gp_sheet = next(x for x in r["sheetMap"] if x["key"] == "gp")
    assert gp_sheet["sheet"] is None and gp_sheet["suggestion"] == "GP Data"
    sec = r["sections"][0]
    assert sec["headerFound"] and sec["headerRow"] == 3 and sec["headerExact"] is False
    assert _field(r, "gp", "gp_code")["suggestion"] == "GP_Code"


def test_adding_names_makes_the_file_ready(tmp_path):
    path = _master(tmp_path, {"AMC Date": "AMC Dt", "GP Code": "GP_Code"}, sheet="GP Data")
    added = mapper.add_names(
        [{"section": "gp", "field": "amc_date", "name": " AMC  Dt "}, {"section": "gp", "field": "gp_code", "name": "GP_Code"}],
        [{"key": "gp", "name": "GP Data"}],
    )
    assert len(added) == 3
    raw = json.loads(cm.map_path().read_text(encoding="utf-8"))
    assert raw["gpColumns"]["amc_date"] == ["AMC Date", "AMC Dt"]  # built-in first, the new name after it
    assert raw["sheets"]["gp"] == ["GP Wise Data", "GP Data"]
    assert "amc dt" in cm.load_column_map().gp["amc_date"]
    r = mapper.check(path)
    assert r["ready"] and r["missingRequired"] == 0
    assert {n["name"] for n in mapper.custom_names()} == {"AMC Dt", "GP_Code", "GP Data"}
    # the same names again change nothing
    assert mapper.add_names([{"section": "gp", "field": "amc_date", "name": "amc dt"}], []) == []


@pytest.mark.parametrize(
    "columns,sheets,message",
    [
        ([{"section": "gp", "field": "amc_date", "name": "HOTO Date"}], [], "already the column of HOTO Date"),
        ([{"section": "gp", "field": "amc_date", "name": "X Dt"}, {"section": "gp", "field": "hoto_date", "name": "x dt"}], [], "chosen for both"),
        ([{"section": "gp", "field": "nope", "name": "A"}], [], "Unknown field"),
        ([{"section": "other", "field": "amc_date", "name": "A"}], [], "Unknown section"),
        ([{"section": "gp", "field": "amc_date", "name": "   "}], [], "Not a usable name"),
        ([{"section": "gp", "field": "amc_date", "name": "x" * 121}], [], "Not a usable name"),
        ([], [{"key": "gp", "name": "Master Block"}], "already used"),
    ],
)
def test_unsafe_names_are_refused_and_nothing_is_written(columns, sheets, message):
    with pytest.raises(mapper.MapperError, match=message):
        mapper.add_names(columns, sheets)
    assert not cm.map_path().exists()


def test_broken_file_is_never_overwritten():
    path = cm.map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(mapper.MapperError, match="cannot be read"):
        mapper.add_names([{"section": "gp", "field": "amc_date", "name": "AMC Dt"}], [])
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_remove_only_added_names_and_backup_kept():
    mapper.add_names([{"section": "escalation", "field": "frt_code", "name": "FRT Team Code"}], [])
    mapper.add_names([{"section": "escalation", "field": "fe_name", "name": "Field Engineer"}], [])
    assert cm.map_path().with_suffix(".json.bak").exists()
    with pytest.raises(mapper.MapperError, match="built-in"):
        mapper.remove_name("escalation", "frt_code", "FRT Code")
    with pytest.raises(mapper.MapperError, match="not in the column mapper"):
        mapper.remove_name("escalation", "frt_code", "Something")
    mapper.remove_name("escalation", "frt_code", "frt team code")
    names = cm.load_column_map().escalation
    assert "frt team code" not in names["frt_code"] and "frt code" in names["frt_code"] and "field engineer" in names["fe_name"]


def test_escalation_with_renamed_required_column(tmp_path):
    """Upload refuses an Escalation Matrix whose FRT Code column was renamed; the check finds it, and once the name
    is added the file is recognised."""
    from app.ingestion.escalation import detect_kind

    path = tmp_path / "esc.xlsx"
    _book(path, {"All": [["Escalation"], [h if h != "FRT Code" else "FRT Team Code" for h in ESC_HEADER], *ESC_ROWS]})
    assert detect_kind(path) is None
    r = mapper.check(path)
    assert r["kind"] == "escalation" and not r["ready"]
    assert _field(r, "escalation", "frt_code")["suggestion"] == "FRT Team Code"
    phone = _field(r, "escalation", "fe_phone")
    assert phone["status"] == "found" and not phone["fit"]["warning"]
    mapper.add_names([{"section": "escalation", "field": "frt_code", "name": "FRT Team Code"}], [])
    assert detect_kind(path) == "escalation" and mapper.check(path)["ready"]


def test_wrong_kind_of_values_is_flagged(tmp_path):
    path = _master(tmp_path, {"AMC Date": "AMC Remark"})
    rows = [[*r[:9], "pending", *r[10:]] for r in ROWS]
    _book(path, {"GP Wise Data": [["Title"], [], [("AMC Remark" if h == "AMC Date" else h) for h in GP_HEADER], *rows]})
    col = next(c for c in mapper.check(path)["sections"][0]["columns"] if c["header"] == "AMC Remark")
    assert col["fit"]["amc_date"] == {"kind": "date", "pct": 0, "warning": True}


# ---------------------------------------------------------------- API


def test_api_check_add_remove(client, tmp_path):
    from .conftest import login as admin_login

    csrf = admin_login(client)
    path = _master(tmp_path, {"AMC Date": "AMC Dt"})
    with path.open("rb") as fh:
        r = client.post("/api/v1/ingestion/column-check", headers={"x-csrf-token": csrf}, files={"file": ("m.xlsx", fh, "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["missingRequired"] == 1
    assert not any((get_settings().upload_dir / "column-check").glob("*"))  # the checked file is not kept
    r = client.post("/api/v1/ingestion/column-map", headers={"x-csrf-token": csrf}, json={"columns": [{"section": "gp", "field": "amc_date", "name": "AMC Dt"}]})
    assert r.status_code == 200 and r.json()["added"] and r.json()["names"][0]["name"] == "AMC Dt"
    assert client.post("/api/v1/ingestion/column-map", headers={"x-csrf-token": csrf}, json={"columns": [{"section": "gp", "field": "hoto_date", "name": "AMC Dt"}]}).status_code == 422
    audit = client.get("/api/v1/audit").json()
    assert any(a["action"] == "column_map_added" for a in (audit["items"] if isinstance(audit, dict) else audit))
    r = client.post("/api/v1/ingestion/column-map/remove", headers={"x-csrf-token": csrf}, json={"section": "gp", "field": "amc_date", "name": "AMC Dt"})
    assert r.status_code == 200 and r.json()["names"] == []
    with path.open("rb") as fh:
        bad = client.post("/api/v1/ingestion/column-check", headers={"x-csrf-token": csrf}, files={"file": ("m.txt", fh, "text/plain")})
    assert bad.status_code == 415


def test_viewer_cannot_use_the_mapper(client):
    csrf = login(client, VIEWER)
    assert client.get("/api/v1/ingestion/column-map").status_code == 403
    assert client.post("/api/v1/ingestion/column-map", headers={"x-csrf-token": csrf}, json={"columns": []}).status_code == 403


def test_reprocess_failure_keeps_the_import(imported, client, monkeypatch):
    """A re-process that fails puts the run back as it was: same status, still active, same data on the dashboard."""
    from app.analytics.store import get_store
    from app.ingestion import service
    from app.ingestion.workbook import WorkbookError
    from app.models import Dataset
    from app.db import SessionLocal
    from .conftest import login as admin_login

    csrf = admin_login(client)
    with SessionLocal() as db:
        ds = db.query(Dataset).filter(Dataset.is_active.is_(True)).one()
        ds_id, status = ds.id, ds.status
    before = len(get_store().gps)

    def boom(path):
        raise WorkbookError("'GP Wise Data' is missing required columns: amc_date")

    monkeypatch.setattr(service, "parse_workbook", boom)
    r = client.post(f"/api/v1/ingestion/runs/{ds_id}/reprocess", headers={"x-csrf-token": csrf})
    assert r.status_code == 202, r.text
    with SessionLocal() as db:
        ds = db.get(Dataset, ds_id)
        assert ds.status == status and ds.is_active and ds.message.startswith("Re-process failed")
    assert len(get_store().gps) == before
    # a failed run is not re-processed (Retry is for that); an unknown run is 404
    assert client.post("/api/v1/ingestion/runs/999999/reprocess", headers={"x-csrf-token": csrf}).status_code == 404


def test_reprocess_success_gives_the_same_data(imported, client):
    from app.analytics.metrics import summarize
    from app.analytics.store import get_store, invalidate_cache
    from app.db import SessionLocal
    from app.models import Dataset
    from .conftest import login as admin_login

    csrf = admin_login(client)
    store = get_store()
    week = store.latest_week.code
    before = summarize(store, None, week)
    with SessionLocal() as db:
        ds_id = db.query(Dataset).filter(Dataset.is_active.is_(True)).one().id
    assert client.post(f"/api/v1/ingestion/runs/{ds_id}/reprocess", headers={"x-csrf-token": csrf}).status_code == 202
    with SessionLocal() as db:
        ds = db.get(Dataset, ds_id)
        assert ds.status in ("SUCCESS", "PARTIAL") and ds.is_active, ds.message
    invalidate_cache()
    assert summarize(get_store(), None, week) == before
