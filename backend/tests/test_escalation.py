"""Escalation Matrix: recognised by content on upload, imported on its own, served by Field Team & Escalation."""

from pathlib import Path

import pytest

from .conftest import REAL_FILE, VIEWER, login

ESC_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "Escalation_Matrix_15.10.xlsx"


@pytest.fixture(scope="module")
def escalation(imported):
    if not ESC_FILE.exists():
        pytest.skip("Escalation Matrix file not available")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://localhost", headers={"origin": "http://localhost:3000"}) as c:
        csrf = login(c)
        with ESC_FILE.open("rb") as fh:
            r = c.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("Escalation.xlsx", fh, "application/octet-stream")})
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "escalation"
    return r.json()


def test_kind_is_detected_from_content():
    from app.ingestion.escalation import detect_kind

    if REAL_FILE.exists():
        assert detect_kind(REAL_FILE) == "master"
    if ESC_FILE.exists():
        assert detect_kind(ESC_FILE) == "escalation"


def test_escalation_upload_is_separate_from_master_data(escalation, client):
    login(client)
    runs = client.get("/api/v1/ingestion/escalation").json()
    assert runs[0]["status"] == "SUCCESS" and runs[0]["isActive"] and runs[0]["rows"] == 16323
    # the master dataset is untouched: still exactly one active master dataset
    assert sum(1 for x in client.get("/api/v1/ingestion/runs").json() if x["isActive"]) == 1


def test_field_team_summary_counts(escalation, client):
    login(client)
    s = client.get("/api/v1/field-team/summary", params={"week": "W-41"}).json()
    t = s["total"]
    # each person once: same state + same name ignoring case/spaces/punctuation; "Vacant" AM entries are posts, not people
    assert t["gps"] == 16323 and t["frtTeams"] == 267 and t["splicers"] == 240 and t["fes"] == 59 and t["ams"] == 12
    assert t["amVacantPosts"] == 2
    states = {x["id"]: x for x in s["states"]}
    assert states["assam"]["ams"] == 0 and states["assam"]["missingAm"] == 1495
    assert states["haryana"]["invalidPhones"] == 137 and states["haryana"]["missingSplicer"] == 517
    assert states["rajasthan"]["shq"] == ["Abhinav Singhal"] and states["rajasthan"]["cbh"] == ["Ashish Sharma"]


def test_phones_full_for_admin_masked_for_viewer(escalation, client):
    login(client)
    admin = client.get("/api/v1/field-team/lookup", params={"circle": "rajasthan", "search": "jaimala"}).json()
    fe = next(s for s in admin["items"][0]["chain"] if s["role"] == "fe")
    assert admin["phonesMasked"] is False and fe["phone"] and "X" not in fe["phone"]
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    login(client, VIEWER)
    viewer = client.get("/api/v1/field-team/lookup", params={"circle": "rajasthan", "search": "jaimala"}).json()
    fe_v = next(s for s in viewer["items"][0]["chain"] if s["role"] == "fe")
    assert viewer["phonesMasked"] is True and "XXXXX" in fe_v["phone"] and fe_v["phone"][:2] == fe["phone"][:2]


def test_workload_down_and_gaps(escalation, client):
    login(client)
    w = client.get("/api/v1/field-team/workload", params={"role": "fe", "week": "W-41"}).json()
    assert w["people"] == 59 and sum(x["gps"] for x in w["items"]) == 16323 - w["unassignedGps"]
    d = client.get("/api/v1/field-team/down", params={"mode": "zero", "week": "W-41"}).json()
    summary = client.get("/api/v1/field-team/summary", params={"week": "W-41"}).json()
    assert d["total"] == summary["total"]["downGps"]
    g = client.get("/api/v1/field-team/gaps", params={"issue": "invalid-splicer-phone"}).json()
    assert g["total"] == 137 and all(not next(s for s in x["chain"] if s["role"] == "splicer")["phoneValid"] for x in g["items"])
    assert client.get("/api/v1/field-team/gaps", params={"issue": "nonsense"}).status_code == 422


def test_team_directory_counts_each_person_once(escalation, client):
    login(client)
    summary = client.get("/api/v1/field-team/summary", params={"week": "W-41"}).json()["total"]
    for role, key in (("am", "ams"), ("splicer", "splicers"), ("frt", "frtTeams"), ("fe", "fes")):
        body = client.get("/api/v1/field-team/people", params={"role": role, "week": "W-41"}).json()
        assert body["count"] == summary[key], role  # the card and its list agree
        assert sum(p["gps"] for p in body["items"]) + body["gpsWithout"] == 16323, role  # every GP once
        assert all(p["districtCount"] == len(p["districts"]) and p["blockCount"] >= p["districtCount"] for p in body["items"])
    am = client.get("/api/v1/field-team/people", params={"role": "am", "week": "W-41"}).json()
    assert am["vacantPosts"] == 2 and sum(1 for p in am["items"] if p["vacant"]) == 2
    hemant = next(p for p in am["items"] if p["name"] == "Hemant")
    assert hemant["districtCount"] == 6 and hemant["blockCount"] == 39 and len(hemant["frtTeams"]) == 14
    splicers = client.get("/api/v1/field-team/people", params={"role": "splicer", "week": "W-41"}).json()["items"]
    om = next(p for p in splicers if p["circleId"] == "rajasthan" and p["name"].replace(" ", "").lower() == "omprakash")
    assert set(om["spellings"]) == {"OMPRAKASH", "Om Prakash", "omprakash"}
