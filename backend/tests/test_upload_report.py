"""Upload report: what changed compared with the previous upload."""

import copy
import datetime as dt
import json

import pytest

from app.db import SessionLocal
from app.ingestion.parser import parse_workbook
from app.ingestion.report import build_report
from app.models import Dataset, ImportReport

from .conftest import REAL_FILE, login


@pytest.fixture(scope="module")
def parsed(imported):
    return parse_workbook(REAL_FILE)


def _report_for(parsed_wb):
    """Build a report for a pretend new upload (rolled back – nothing is stored)."""
    with SessionLocal() as db:
        ds = Dataset(file_name="next.xlsb", stored_path="x", sha256="0" * 64, status="PROCESSING")
        db.add(ds)
        db.flush()
        try:
            return build_report(db, ds, parsed_wb)
        finally:
            db.rollback()


def test_first_import_has_a_report_without_a_comparison(imported, client):
    with SessionLocal() as db:
        row = db.get(ImportReport, imported.dataset_id)
    assert row is not None
    rep = json.loads(row.report)
    assert rep["gps"]["current"] == 16323 and rep["dataAsOf"]["current"] == "2026-10-08"
    assert "GP Wise Data" in rep["sheets"]["found"] and "error" not in rep
    login(client)
    api = client.get(f"/api/v1/ingestion/runs/{imported.dataset_id}/report").json()
    assert api["gps"]["current"] == 16323 and "layout" not in api  # internal layout is not sent


def test_same_file_again_reports_no_changes(parsed):
    rep = _report_for(parsed)
    assert rep["previous"] is not None
    g = rep["gps"]
    assert (g["added"], g["removed"], g["hotoNew"], g["amcNew"], g["amcDateChanged"]) == (0, 0, 0, 0, 0)
    assert rep["dataAsOf"]["newDays"] == 0 and any("same as in the previous upload" in n for n in rep["notes"])
    assert rep["columns"]["compared"] and rep["columns"]["added"] == [] and rep["columns"]["removed"] == []
    assert rep["weeks"]["added"] == [] and rep["weeks"]["removed"] == []


def test_changes_are_found(parsed):
    p = copy.deepcopy(parsed)
    gone = p.gps.pop(0)  # a GP removed
    amc_gp = next(g for g in p.gps if g.get("amc_date"))
    amc_gp["amc_date"] = amc_gp["amc_date"] + dt.timedelta(days=3)  # an AMC date corrected
    new_amc = next(g for g in p.gps if g.get("hoto_date") and not g.get("amc_date"))
    new_amc["amc_date"] = dt.date(2026, 10, 9)  # a GP newly under AMC
    p.gps.append({**p.gps[1], "gp_code": "999999", "name": "NEW GP"})  # a GP added
    p.gp_headers = [h for h in p.gp_headers if h != "AM Name"] + ["Splicer Rating"]  # a column removed, one added
    p.missing_optional = ["am_name"]
    p.data_as_of = dt.date(2026, 10, 1)  # older than the active upload
    rep = _report_for(p)
    g = rep["gps"]
    assert g["removed"] == 1 and g["removedSample"][0]["code"] == gone["gp_code"]
    assert g["added"] == 1 and g["addedSample"][0]["code"] == "999999"
    assert g["amcNew"] == 1 and g["amcDateChanged"] == 1 and g["amcDateChangedSample"][0]["code"] == amc_gp["gp_code"]
    assert rep["columns"]["added"] == ["Splicer Rating"] and rep["columns"]["removed"] == ["AM Name"]
    notes = " | ".join(rep["notes"])
    assert "OLDER than the previous upload" in notes and "AM Name" in notes and "am_name" in notes


def test_report_requires_admin(client, imported):
    from .conftest import VIEWER

    assert client.get(f"/api/v1/ingestion/runs/{imported.dataset_id}/report").status_code == 401
    login(client, VIEWER)
    assert client.get(f"/api/v1/ingestion/runs/{imported.dataset_id}/report").status_code == 403
