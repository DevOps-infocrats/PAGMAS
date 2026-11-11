"""GP-wise weekly task of a ticket: Area Manager GPs + targets from the plan, assignment workbook, daily progress
(every submission kept), no automatic closing, admin-only closing, and the e-mail rule for the assignee."""

import datetime as dt
import io
import zipfile

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import TicketProgress, TicketTaskGp, User
from app.tickets import task as tasks

from .conftest import ADMIN, VIEWER, login


def _uid(email):
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == email)).one()


@pytest.fixture
def am_week(imported, monkeypatch):
    """A test Area Manager owning the plan GPs of the test file (its master data has no AM names), with the test
    viewer's e-mail as their Escalation Matrix e-mail; the latest week has planned or pending GPs."""
    am, week = "Test Area Manager", imported.weeks[-1].code
    w0 = imported.week(week)
    plan = imported.amc_plan
    if plan.empty:  # the test file has no GP-wise plan: a small one for this test only (restored afterwards)
        codes = [c for c in imported.gps.index[imported.gps["revised"].to_numpy()] if not isinstance(imported.gps.at[c, "amc_date"], dt.date)][:4]
        plan = pd.DataFrame(
            {
                "category": ["5% Incremental", "Additional Plan", "Additional Plan", "5% Incremental"],
                "planned_date": [w0.start, w0.start + dt.timedelta(days=2), w0.end, w0.start - dt.timedelta(days=5)],
                "ach_date": [w0.start, None, None, None],
                "current_status": [None] * 4,
                "letter_status": [None] * 4,
                "letter_date": [None] * 4,
                "approval_status": [None] * 4,
            },
            index=pd.Index(codes, name=imported.amc_plan.index.name),
        )
        monkeypatch.setattr(imported, "amc_plan", plan)
    real = tasks._directory

    def fake(store):
        d2, src = real(store)
        d2 = d2.copy()
        mine = d2.index.isin(plan.index)
        d2.loc[mine, "am"] = am
        d2["email"] = pd.Series([VIEWER[0] if m else None for m in mine], index=d2.index, dtype=object)
        return d2, src

    monkeypatch.setattr(tasks, "_directory", fake)
    # every request of the test uses this snapshot (a background re-warm must not drop the test plan)
    import app.api.tickets as tickets_api
    from app.analytics.store import get_store
    from app.main import app

    monkeypatch.setattr(tickets_api, "get_store", lambda: imported)
    app.dependency_overrides[get_store] = lambda: imported
    yield_value = (am, week)
    w = imported.week(week)
    if tasks._task_rows(imported, fake(imported)[0], am, w.start, w.end).empty:
        app.dependency_overrides.pop(get_store, None)
        pytest.skip("No planned or pending GP in the latest week of the test file")
    yield yield_value
    app.dependency_overrides.pop(get_store, None)


def _create(client, h, am, week, **over):
    body = {"assigneeId": _uid(VIEWER[0]), "subject": f"Weekly GP task {week}", "description": "Convert the GPs of the week and report daily.", "priority": "HIGH", "task": {"amName": am, "week": week}} | over
    return client.post("/api/v1/tickets", json=body, headers=h)


def test_task_workflow(imported, client, am_week):
    am, week = am_week
    h = {"X-CSRF-Token": login(client, ADMIN)}
    opts = client.get("/api/v1/tickets/task/area-managers", params={"week": week}).json()
    row = next(a for a in opts["areaManagers"] if a["name"] == am)
    assert row["user"]["email"] == VIEWER[0] and row["weekGps"] + row["pendingGps"] > 0
    prev = client.get("/api/v1/tickets/task/preview", params={"am": am, "week": week}).json()["rows"]
    assert prev and all(r["target"] == 1 and r["gap"] == 1 - r["achieved"] for r in prev)

    r = _create(client, h, am, week)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    d = client.get(f"/api/v1/tickets/{tid}").json()
    task = d["task"]
    assert task["areaManager"] == am and task["totals"]["gps"] == len(prev) and task["totals"]["target"] == len(prev)
    assert [g["gpCode"] for g in task["gps"]] == [x["gpCode"] for x in prev]
    # assignment workbook attached (a real .xlsx) and the progress report
    for kind in ("assignment", "progress"):
        x = client.get(f"/api/v1/tickets/{tid}/task/{kind}.xlsx")
        assert x.status_code == 200 and x.content[:2] == b"PK" and "_Weekly_GP_Assignment_Week_" in x.headers["content-disposition"]
        assert "xl/worksheets/sheet1.xml" in zipfile.ZipFile(io.BytesIO(x.content)).namelist()
        from python_calamine import CalamineWorkbook

        rows = CalamineWorkbook.from_filelike(io.BytesIO(x.content)).get_sheet_by_name("GP Task").to_python()
        assert rows[4][:15] == [
            "S.No.", "Circle", "Area Manager", "FE Name", "Business Area", "District", "Block Name", "GP Code", "GP Name",
            "Weekly Target", "Existing Achievement", "Remaining Gap", "Daily Achievement", "Remarks", "Proof Document",
        ]
        assert rows[5][2] == am and len([r for r in rows[5:] if r[7]]) == len(prev)

    # the Area Manager (viewer) sees it and submits daily progress
    h = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["progress"] is True and d["can"]["close"] is False
    open_gp = next((g for g in d["task"]["gps"] if g["gap"] > 0), None)
    other = next((g for g in d["task"]["gps"] if g is not open_gp), None)
    items = [{"taskGpId": open_gp["id"], "achievedToday": 1, "remark": "Converted today"}] if open_gp else [{"taskGpId": d["task"]["gps"][0]["id"], "achievedToday": 0, "remark": "Checked"}]
    r = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": items, "note": "Day 1"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "IN_PROGRESS"  # started by the first submission, NOT closed
    if open_gp:
        g = next(x for x in d["task"]["gps"] if x["id"] == open_gp["id"])
        assert g["cumulative"] == 1 and g["gap"] == 0 and g["remarks"] == "Converted today"
        # counting the same GP again is refused
        again = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": open_gp["id"], "achievedToday": 1}]}, headers=h)
        assert again.status_code == 422
    # an empty submission is refused; a second day with a remark is kept as its own record
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": d["task"]["gps"][0]["id"], "achievedToday": 0}]}, headers=h).status_code == 422
    target_gp = other or d["task"]["gps"][0]
    r = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": target_gp["id"], "achievedToday": 0, "remark": "Day 2: OTDR pending"}]}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["task"]["history"]) == 2 and d["task"]["history"][0]["lines"][0]["remark"] == "Day 2: OTDR pending"
    assert d["status"] != "CLOSED"
    # the Area Manager cannot close; GP of another ticket / unknown GP refused
    assert client.post(f"/api/v1/tickets/{tid}/close", json={}, headers=h).status_code == 403
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": 999999, "achievedToday": 1}]}, headers=h).status_code == 422
    rep = client.get(f"/api/v1/tickets/{tid}/task/progress.xlsx")
    assert rep.status_code == 200 and "xl/worksheets/sheet2.xml" in zipfile.ZipFile(io.BytesIO(rep.content)).namelist()  # daily history sheet

    # the admin sees the progress and closes the ticket from In Progress (task tickets need no review submission)
    h = {"X-CSRF-Token": login(client, ADMIN)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["close"] is True and d["task"]["latestSubmission"]
    r = client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "Week done"}, headers=h)
    assert r.json()["status"] == "CLOSED" and r.json()["closedBy"]["name"] == "Admin"
    h = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["status"] == "CLOSED" and d["can"]["progress"] is False
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": target_gp["id"], "achievedToday": 0, "remark": "late"}]}, headers=h).status_code == 409
    with SessionLocal() as db:  # history preserved; the original target never changed
        assert db.scalar(select(func.count()).where(TicketProgress.ticket_id == tid)) == 2
        assert all(g.target == 1 for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == tid)))


def test_task_assignee_must_be_the_area_managers_account(imported, client, am_week):
    am, week = am_week
    h = {"X-CSRF-Token": login(client, ADMIN)}
    with SessionLocal() as db:
        other = db.scalars(select(User).where(User.email != VIEWER[0], User.email != ADMIN[0], User.is_active.is_(True))).first()
        if other is None:
            from app.security.core import hash_password

            other = User(email="someone-else@pratap-test.in", name="Someone", role="viewer", password_hash=hash_password("S0meone!Secure-Pass"))
            db.add(other)
            db.commit()
        oid = other.id
    r = _create(client, h, am, week, assigneeId=oid)
    assert r.status_code == 422 and "Escalation Matrix" in r.json()["detail"]
    assert _create(client, h, "Nobody Such", week).status_code == 422
    assert _create(client, h, am, "W-99").status_code == 422
    # viewers cannot use the task endpoints
    login(client, VIEWER)
    assert client.get("/api/v1/tickets/task/area-managers", params={"week": week}).status_code == 403


def test_plain_ticket_rules_unchanged(client):
    """A ticket without a task still closes only after an approved submission."""
    h = {"X-CSRF-Token": login(client, ADMIN)}
    t = client.post("/api/v1/tickets", json={"assigneeId": _uid(VIEWER[0]), "subject": "Plain ticket", "description": "Nothing GP-wise here.", "priority": "LOW"}, headers=h).json()
    assert client.get(f"/api/v1/tickets/{t['id']}").json()["task"] is None
    assert client.post(f"/api/v1/tickets/{t['id']}/close", json={}, headers=h).status_code == 409
