"""Field Engineers in the GP-wise task: FE list from the Escalation Matrix under each Area Manager, the Area Manager
gets every GP, each FE only the GPs mapped to them (screen, daily progress, proof files, own Excel, e-mail), FE-only
tickets, FE-wise monitoring and admin-only closing. No real e-mail is ever sent (fake SMTP session)."""

import io
import shutil

import pytest
from python_calamine import CalamineWorkbook
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Ticket, TicketNotification, User
from app.security.core import hash_password
from app.tickets import task as tasks

from .conftest import ADMIN, VIEWER, login
from .test_ticket_recipients import mail  # noqa: F401 - shared fixture (fake SMTP)
from .test_ticket_tasks import am_week  # noqa: F401 - shared fixture

FE1 = ("fe.one@pratap-test.in", "FeOne!Secure-Pass-71")
FE2 = ("fe.two@pratap-test.in", "FeTwo!Secure-Pass-72")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def fe_org(imported, am_week, monkeypatch):  # noqa: F811
    """The test Area Manager's task GPs of one circle split between FE One, FE Two and one GP without an FE; a GP of
    another Area Manager with its own FE in the same circle."""
    am, week = am_week
    w = imported.week(week)
    d0, _ = tasks._directory(imported)
    rows = tasks._task_rows(imported, d0, am, w.start, w.end)
    backlog = list(rows.index[rows["kind"] == "PENDING"])
    rows = rows[rows["kind"] == "WEEK"]  # a ticket holds only the week's target GPs
    circle = str(imported.gps.at[rows.index[0], "circle"]).title()
    codes = sorted(c for c in rows.index if str(imported.gps.at[c, "circle"]).title() == circle)
    if len(codes) < 3:
        pytest.skip("Need three task GPs in one circle")
    k = max(1, (len(codes) - 1) // 2)
    one, two, unmapped = codes[:k], codes[k:-1], codes[-1:]
    other = next(c for c in imported.gps.index if str(imported.gps.at[c, "circle"]).title() == circle and c not in codes and c not in backlog)
    base = tasks._directory

    def with_fes(store):
        d2, src = base(store)
        d2 = d2.copy()
        d2["fe"], d2["fe_email"] = None, None
        d2.loc[d2.index.isin(one), ["fe", "fe_email"]] = ["Test FE One", FE1[0]]
        d2.loc[d2.index.isin(two), ["fe", "fe_email"]] = ["Test FE Two", FE2[0]]
        d2.loc[[other], ["am", "fe", "fe_email"]] = ["Other Area Manager", "Other FE", "other.fe@pratap-test.in"]
        return d2, src

    monkeypatch.setattr(tasks, "_directory", with_fes)
    with SessionLocal() as db:
        for email, pw in (FE1, FE2):
            if db.scalars(select(User).where(User.email == email)).first() is None:
                db.add(User(email=email, name=email.split("@")[0], role="viewer", password_hash=hash_password(pw)))
        db.commit()
        first_new = (db.scalar(select(func.max(Ticket.id))) or 0) + 1
    yield {"circle": circle, "week": week, "am": am, "one": one, "two": two, "unmapped": unmapped, "backlog": backlog}
    # the tickets of these tests are removed again (other test files count the same GPs in their own tickets)
    with SessionLocal() as db:
        ids = list(db.scalars(select(Ticket.id).where(Ticket.id >= first_new)))
        db.execute(delete(Ticket).where(Ticket.id.in_(ids)))
        db.commit()
    for i in ids:
        shutil.rmtree(get_settings().ticket_dir / str(i), ignore_errors=True)


def _fe(name, email, am="Test Area Manager", fe_email=None):
    return {"role": "FE", "name": name, "email": email, "am": am, "feEmail": fe_email or email}


def _gen(client, h, org, recipients, send=False):
    body = {
        "circle": org["circle"], "recipients": recipients, "subject": "Weekly GP work", "description": "Convert the GPs of the week and report daily.",
        "priority": "HIGH", "sendEmail": send, "task": {"week": org["week"]},
    }
    return client.post("/api/v1/tickets", json=body, headers=h)


def _sheet(content: bytes):
    return CalamineWorkbook.from_filelike(io.BytesIO(content)).get_sheet_by_name("GP Task").to_python()


def test_directory_lists_fes_under_their_area_manager(client, fe_org):
    login(client)
    d = client.get("/api/v1/tickets/directory", params={"circle": fe_org["circle"], "week": fe_org["week"]}).json()
    mine = {f["name"]: f for f in d["fe"] if f["am"] == fe_org["am"]}
    assert set(mine) == {"Test FE One", "Test FE Two"}
    assert mine["Test FE One"]["mappedEmail"] == FE1[0] and mine["Test FE One"]["emails"][0]["user"]["name"] == "fe.one"
    assert mine["Test FE One"]["weekGps"] == len(fe_org["one"])
    assert any(f["name"] == "Other FE" and f["am"] == "Other Area Manager" for f in d["fe"])  # another AM's FE keeps its AM
    am = next(a for a in d["am"] if a["name"] == fe_org["am"])
    assert am["unmappedFeGps"] == 1  # the GP without an FE is reported, never guessed


def test_am_gets_all_gps_each_fe_only_their_own(client, fe_org):
    h = {"X-CSRF-Token": login(client)}
    am_r = {"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}
    r = _gen(client, h, fe_org, [am_r, _fe("Test FE One", FE1[0]), _fe("Test FE Two", FE2[0])])
    assert r.status_code == 201, r.text
    assert len(r.json()["tickets"]) == 1  # one ticket per Area Manager, the FEs are on it
    tid = r.json()["id"]
    all_codes = sorted(fe_org["one"] + fe_org["two"] + fe_org["unmapped"])

    # admin: every GP with its FE, FE-wise split incl. "not mapped"
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert sorted(g["gpCode"] for g in d["task"]["gps"]) == all_codes
    split = {(f["name"], f["gps"]) for f in d["task"]["fes"]}
    assert split == {("Test FE One", len(fe_org["one"])), ("Test FE Two", len(fe_org["two"])), (None, 1)}
    assert {x["role"] for x in d["recipients"]} == {"AM", "FE"}

    # FE One: only their GPs, no other FE in the recipients, can report progress
    h1 = {"X-CSRF-Token": login(client, FE1)}
    d1 = client.get(f"/api/v1/tickets/{tid}").json()
    assert sorted(g["gpCode"] for g in d1["task"]["gps"]) == sorted(fe_org["one"])
    assert d1["task"]["totals"]["gps"] == len(fe_org["one"]) and d1["task"]["scope"]["fieldEngineer"] == "Test FE One" and d1["task"]["fes"] == []
    assert d1["myRole"] == "FE" and d1["can"]["progress"] is True and d1["can"]["close"] is False
    assert not any(x["email"] == FE2[0] for x in d1["recipients"])
    # FE One cannot report FE Two's GP
    d_admin = d
    two_gp = next(g for g in d_admin["task"]["gps"] if g["gpCode"] == fe_org["two"][0])
    bad = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": two_gp["id"], "status": "DONE"}]}, headers=h1)
    assert bad.status_code == 403
    own = next(g for g in d1["task"]["gps"] if g["status"] == "PENDING")
    ok = client.post(
        f"/api/v1/tickets/{tid}/progress-form",
        data={"payload": '{"items": [{"taskGpId": %d, "status": "DONE", "remark": "FE: letter accepted"}], "note": "FE day 1"}' % own["id"], "proofGps": [str(own["id"])]},
        files=[("proofs", ("fe_letter.pdf", PDF, "application/pdf"))],
        headers=h1,
    )
    assert ok.status_code == 200, ok.text
    mine = next(g for g in ok.json()["task"]["gps"] if g["id"] == own["id"])
    assert mine["status"] == "DONE" and mine["files"][0]["fileName"] == "fe_letter.pdf"
    file_id = mine["files"][0]["id"]
    # FE One's own Excel: only their GPs, FE columns filled
    x = client.get(f"/api/v1/tickets/{tid}/task/progress.xlsx")
    assert x.status_code == 200 and 'filename="FE_Test_FE_One_' in x.headers["content-disposition"]
    rows = _sheet(x.content)
    assert sorted(str(r[7]) for r in rows[5:] if r[7]) == sorted(fe_org["one"]) and all(r[3] == "Test FE One" for r in rows[5:] if r[7])
    assert any(r[14] == "fe_letter.pdf" for r in rows[5:] if r[7])
    assert client.post(f"/api/v1/tickets/{tid}/close", json={}, headers=h1).status_code == 403

    # FE Two: never sees FE One's GPs or proof file
    login(client, FE2)
    d2 = client.get(f"/api/v1/tickets/{tid}").json()
    assert sorted(g["gpCode"] for g in d2["task"]["gps"]) == sorted(fe_org["two"]) and d2["task"]["history"] == []
    assert client.get(f"/api/v1/tickets/progress-files/{file_id}").status_code == 404
    assert sorted(str(r[7]) for r in _sheet(client.get(f"/api/v1/tickets/{tid}/task/assignment.xlsx").content)[5:] if r[7]) == sorted(fe_org["two"])

    # the Area Manager sees everything, the FE progress and was notified
    login(client, VIEWER)
    da = client.get(f"/api/v1/tickets/{tid}").json()
    assert sorted(g["gpCode"] for g in da["task"]["gps"]) == all_codes
    fe1_row = next(f for f in da["task"]["fes"] if f["name"] == "Test FE One")
    assert fe1_row["doneGps"] >= 1 and fe1_row["proofFiles"] == 1 and fe1_row["recipient"] is True
    assert client.get(f"/api/v1/tickets/progress-files/{file_id}").status_code == 200
    all_rows = _sheet(client.get(f"/api/v1/tickets/{tid}/task/progress.xlsx").content)
    assert sorted(str(r[7]) for r in all_rows[5:] if r[7]) == all_codes and any(r[3] == "FE not mapped" for r in all_rows[5:] if r[7])
    with SessionLocal() as db:
        uid = db.scalars(select(User.id).where(User.email == VIEWER[0])).one()
        assert db.scalars(select(TicketNotification).where(TicketNotification.ticket_id == tid, TicketNotification.user_id == uid, TicketNotification.title.like("%FE daily progress"))).first()
    assert client.post(f"/api/v1/tickets/{tid}/close", json={}, headers={"X-CSRF-Token": client.cookies.get("pratap_csrf")}).status_code == 403

    # admin monitoring: FE filter, FE-wise split; only the admin closes (no auto-close)
    ha = {"X-CSRF-Token": login(client)}
    code = r.json()["code"]
    s = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code}).json()
    assert {(b["fieldEngineer"], b["total"]) for b in s["byFe"]} == {("Test FE One", len(fe_org["one"])), ("Test FE Two", len(fe_org["two"])), ("FE not mapped", 1)}
    assert "FE not mapped" in s["options"]["fieldEngineers"]
    f1 = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code, "fe": "Test FE One"}).json()
    assert f1["total"] == len(fe_org["one"]) and f1["done"] >= 1
    row = next(x for x in client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "ticket": code, "fe": "Test FE One"}).json()["items"] if x["gpCode"] == own["gpCode"])
    assert row["fieldEngineer"] == "Test FE One" and row["completedBy"].startswith("Marked Done by")
    assert client.get(f"/api/v1/tickets/{tid}").json()["status"] != "CLOSED"
    assert client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "Week reviewed"}, headers=ha).status_code == 409  # GPs not AM-approved (SOP rule 4)
    assert client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "Week reviewed by the admin", "force": True}, headers=ha).status_code == 200


def test_fe_only_ticket_has_only_that_fes_gps(client, fe_org):
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [_fe("Test FE One", FE1[0])])  # no Area Manager selected
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["assignee"]["email"] == FE1[0]
    d = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert sorted(g["gpCode"] for g in d["task"]["gps"]) == sorted(fe_org["one"]) and d["task"]["areaManager"] == fe_org["am"]


def test_fe_mapping_and_account_are_checked(client, fe_org):
    h = {"X-CSRF-Token": login(client)}
    wrong_am = _gen(client, h, fe_org, [_fe("Test FE One", FE1[0], am="Other Area Manager")])
    assert wrong_am.status_code == 422 and "not mapped" in wrong_am.json()["detail"]
    unknown = _gen(client, h, fe_org, [_fe("Nobody", "nobody@pratap-test.in")])
    assert unknown.status_code == 422
    # a typed address without a dashboard account needs the e-mail switched on
    typed = _gen(client, h, fe_org, [{**_fe("Test FE Two", FE2[0]), "email": "typed.fe@pratap-test.in"}])
    assert typed.status_code == 422 and "no dashboard account" in typed.json()["detail"]


def test_fe_email_has_only_their_workbook(client, fe_org, mail):  # noqa: F811
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE Two", FE2[0])], send=True)
    assert r.status_code == 201, r.text
    assert r.json()["emailQueued"] == 2 and len(mail.sent) == 2
    by_to = {m["To"]: m for m in mail.sent}
    fe_mail = by_to[FE2[0]]
    parts = [p for p in fe_mail.walk() if p.get_filename()]
    assert len(parts) == 1 and parts[0].get_filename().startswith("FE_Test_FE_Two_")
    rows = _sheet(parts[0].get_payload(decode=True))
    assert sorted(str(r[7]) for r in rows[5:] if r[7]) == sorted(fe_org["two"])
    assert "Assigned GPs: %d" % len(fe_org["two"]) in fe_mail.get_body(("plain",)).get_content()

    # the e-mail body carries the dashboard's totals and FE-wise split (AM only) – never the GP list (on the dashboard)
    tid = r.json()["id"]
    whole = client.get(f"/api/v1/tickets/{tid}").json()["task"]
    fe_html = fe_mail.get_body(("html",)).get_content()
    am_html = by_to[VIEWER[0]].get_body(("html",)).get_content()
    every = fe_org["one"] + fe_org["two"] + fe_org["unmapped"]
    assert not any(f">{c}<" in fe_html + am_html for c in every) and "GP-wise list" not in fe_html + am_html
    assert "To see which GPs are your target GPs" in fe_html and "To see which GPs are your target GPs" in am_html
    assert "Field Engineer-wise" not in fe_html
    T = whole["totals"]
    assert "Field Engineer-wise" in am_html and "Test FE One" in am_html and "FE not mapped" in am_html
    assert "Assigned GPs" in am_html and f">{T['gps']:,}</div>" in am_html  # KPI tile of the PAGMAS e-mail layout


def test_preview_shows_am_and_fe_target_and_achievement(client, fe_org):
    """Generate Ticket preview: the AM's weekly target / ready / AMC / remaining and each FE's – only their GPs; the
    FE lines and the not-mapped line add up to the AM; the AM's weekly target equals the AMC Conversion AM table."""
    login(client)
    r = client.get("/api/v1/tickets/task/preview", params={"am": fe_org["am"], "week": fe_org["week"], "circle": fe_org["circle"]}).json()
    rows, s = r["rows"], r["summary"]
    am = s["am"]
    # only the week's target GPs are in the ticket; the backlog (planned earlier, not achieved) is information only
    assert am["total"]["gps"] == len(rows) == am["week"]["gps"] and all(x["kind"] == "WEEK" for x in rows)
    assert not set(fe_org["backlog"]) & {x["gpCode"] for x in rows}
    assert am["backlog"]["gps"] == sum(1 for c in fe_org["backlog"] if str(c) not in {x["gpCode"] for x in rows})
    assert am["total"]["amc"] == sum(x["achieved"] for x in rows)  # same rule as the ticket / Excel "Existing Achievement"
    for part in ("week", "backlog", "total"):
        f = am[part]
        assert f["toReady"] == f["gps"] - f["ready"] and f["toConvert"] == f["gps"] - f["amc"]
    by = {f["name"]: f for f in s["fes"]}
    assert by["Test FE One"]["total"]["gps"] == len(fe_org["one"]) and by["Test FE Two"]["total"]["gps"] == len(fe_org["two"])
    assert "Other FE" not in by  # another Area Manager's FE
    assert s["unmapped"]["total"]["gps"] == 1
    for k in ("gps", "ready", "amc"):
        assert sum(f["total"][k] for f in s["fes"]) + s["unmapped"]["total"][k] == am["total"][k]
    if s["page"] is not None:
        assert s["page"]["weekTarget"] == am["week"]["gps"]


def test_admin_soft_deletes_a_ticket_everywhere(client, fe_org):
    h = {"X-CSRF-Token": login(client)}
    am_r = {"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}
    t = _gen(client, h, fe_org, [am_r, _fe("Test FE One", FE1[0])]).json()
    tid, code = t["id"], t["code"]
    k0 = client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()["total"]
    # FE One reports a GP (kept as history after the delete)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    gp = next(g for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if g["status"] == "PENDING")
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": gp["id"], "status": "PENDING", "remark": "kept"}]}, headers=h1).status_code == 200
    # nobody but an admin may delete
    assert client.delete(f"/api/v1/tickets/{tid}", headers=h1).status_code == 403
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert client.delete(f"/api/v1/tickets/{tid}", headers=hv).status_code == 403
    assert client.get("/api/v1/tickets/notifications").json()["items"]  # the AM has the ticket's notifications

    h = {"X-CSRF-Token": login(client)}
    r = client.delete(f"/api/v1/tickets/{tid}", headers=h)
    assert r.status_code == 200 and r.json()["code"] == code
    assert client.delete(f"/api/v1/tickets/{tid}", headers=h).status_code == 404
    assert client.get(f"/api/v1/tickets/{tid}").status_code == 404
    assert code not in [x["code"] for x in client.get("/api/v1/tickets", params={"scope": "all", "page_size": 100}).json()["items"]]
    assert client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()["total"] == k0 - 1
    assert code not in client.get("/api/v1/tickets/gp-monitor/summary").json()["options"]["tickets"]
    for creds in (VIEWER, FE1):
        login(client, creds)
        assert client.get(f"/api/v1/tickets/{tid}").status_code == 404
        assert code not in [x["code"] for x in client.get("/api/v1/tickets", params={"scope": "mine"}).json()["items"]]
        assert all(n["ticketId"] != tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    # history kept in the database (soft delete: nothing orphaned)
    from app.models import TicketEvent, TicketProgress, TicketRecipient, TicketTaskGp

    with SessionLocal() as db:
        t_row = db.get(Ticket, tid)
        assert t_row.deleted_at is not None and t_row.deleted_by_name
        assert db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == tid)).first() is not None
        assert db.scalars(select(TicketProgress).where(TicketProgress.ticket_id == tid)).first() is not None
        assert db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == tid)).first() is not None
        assert db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == tid, TicketEvent.action == "DELETED")).first() is not None
