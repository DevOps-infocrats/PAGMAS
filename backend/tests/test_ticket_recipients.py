"""Generate Ticket with Circle → CBH / SME / Area Manager recipients: database-driven directory, independent recipient
selection, optional e-mail (only the selected people; each Area Manager gets only their own workbook; a mail failure
never undoes a ticket; retry), one task ticket per Area Manager, read-only CBH / SME access, admin-only closing and
the admin monitoring filters. No real e-mail is ever sent (fake SMTP session)."""

import datetime as dt
import io

import pandas as pd
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.mail import smtp
from app.models import TicketRecipient, User
from app.security.core import hash_password
from app.tickets import directory
from app.tickets import task as tasks

from .conftest import ADMIN, VIEWER, login
from .test_ticket_tasks import am_week  # noqa: F401 - shared fixture

SME = ("sme@pratap-test.in", "Sme!Secure-Pass-91")
CBH_MAIL = "cbh.only@pratap-test.in"
AM2_MAIL = "second.am@pratap-test.in"


class FakeSmtp:
    sent: list = []
    fail_connect = False

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        if FakeSmtp.fail_connect:
            raise smtp.MailError("Could not connect to the mail server test:25 (TimeoutError)")
        return self

    def send(self, msg):
        FakeSmtp.sent.append(msg)

    def __exit__(self, *a):
        return None


@pytest.fixture
def mail(monkeypatch):
    FakeSmtp.sent, FakeSmtp.fail_connect = [], False
    monkeypatch.setattr(smtp, "SmtpSession", FakeSmtp)
    return FakeSmtp


@pytest.fixture
def org(imported, am_week, monkeypatch):  # noqa: F811
    """A circle with a CBH (no account), an SME (dashboard account) and two Area Managers: the test AM (the viewer's
    account) and a second AM without an account, each owning half of the week's task GPs."""
    am, week = am_week
    w = imported.week(week)
    d0, _ = tasks._directory(imported)
    rows = tasks._task_rows(imported, d0, am, w.start, w.end)
    rows = rows[rows["kind"] == "WEEK"]  # a ticket holds only the week's target GPs
    circle = str(imported.gps.at[rows.index[0], "circle"]).title()
    codes = [c for c in rows.index if str(imported.gps.at[c, "circle"]).title() == circle]
    if len(codes) < 2:
        pytest.skip("Need two task GPs in one circle")
    second = set(codes[len(codes) // 2 :])
    fake_dir = tasks._directory

    def two(store):
        d2, src = fake_dir(store)
        d2 = d2.copy()
        mine = d2.index.isin(list(second))
        d2.loc[mine, "am"] = "Second Area Manager"
        d2.loc[mine, "email"] = AM2_MAIL
        return d2, src

    monkeypatch.setattr(tasks, "_directory", two)
    esc = pd.DataFrame(
        {
            "circle": [circle.upper()] * len(codes),
            "cbh_name": ["Test CBH"] * len(codes),
            "cbh_email": [CBH_MAIL] * len(codes),
            "shq_name": ["Test SME"] * len(codes),
            "shq_email": [SME[0]] * len(codes),
        },
        index=pd.Index(codes, name="gp_code"),
    )
    monkeypatch.setattr(directory, "_active", lambda: ({"id": 1, "fileName": "test-matrix.xlsx"}, esc))
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.email == SME[0])).first() is None:
            db.add(User(email=SME[0], name="Test SME User", role="viewer", password_hash=hash_password(SME[1])))
            db.commit()
    return {"circle": circle, "week": week, "am": am, "first": [c for c in codes if c not in second], "second": sorted(second)}


def _gen(client, h, org, recipients, task=False, send=False, **over):
    body = {
        "circle": org["circle"],
        "recipients": recipients,
        "subject": "Weekly GP work",
        "description": "Please complete the GP conversion work of this week.",
        "priority": "MEDIUM",
        "sendEmail": send,
        **({"task": {"week": org["week"]}} if task else {}),
    } | over
    return client.post("/api/v1/tickets", json=body, headers=h)


CBH = {"role": "CBH", "name": "Test CBH", "email": CBH_MAIL}
SME_R = {"role": "SME", "name": "Test SME", "email": SME[0]}


def AM(org):
    return {"role": "AM", "name": org["am"], "email": VIEWER[0]}


AM2 = {"role": "AM", "name": "Second Area Manager", "email": AM2_MAIL}


def test_directory_is_circle_wise_and_from_the_database(client, org):
    login(client, ADMIN)
    d = client.get("/api/v1/tickets/directory", params={"circle": org["circle"], "week": org["week"]}).json()
    assert d["circle"] == org["circle"] and any(c["name"] == org["circle"] for c in d["circles"])
    assert [p["name"] for p in d["cbh"]] == ["Test CBH"] and d["cbh"][0]["emails"] == [{"email": CBH_MAIL, "user": None}]
    assert d["sme"][0]["emails"][0]["user"]["name"] == "Test SME User"
    ams = {a["name"]: a for a in d["am"]}
    assert ams[org["am"]]["emails"][0]["user"]["role"] == "viewer"
    assert ams["Second Area Manager"]["emails"] == [{"email": AM2_MAIL, "user": None}]
    assert ams[org["am"]]["weekGps"] == len(org["first"])
    other = next((c["name"] for c in d["circles"] if c["name"] != org["circle"]), None)
    if other:  # another circle shows none of these people
        o = client.get("/api/v1/tickets/directory", params={"circle": other, "week": org["week"]}).json()
        assert not any(p["name"] == "Test CBH" for p in o["cbh"]) and not any(a["name"] == "Second Area Manager" for a in o["am"])
    login(client, VIEWER)
    assert client.get("/api/v1/tickets/directory").status_code == 403


def test_recipient_validation(client, org):
    h = {"X-CSRF-Token": login(client, ADMIN)}
    cases = [
        ({"circle": "Nowhere"}, [CBH], "Circle"),
        ({}, [], "at least one recipient"),
        ({}, [{**CBH, "name": "Made Up Person"}], "not a CBH"),
        ({}, [{**CBH, "email": "not-an-email"}], "valid e-mail"),
        ({}, [CBH, {**SME_R, "email": CBH_MAIL}], "selected twice"),
        ({}, [CBH], "dashboard account"),  # CBH has no account and e-mail is off -> nobody would get it
    ]
    for over, recs, text in cases:
        r = _gen(client, h, org, recs, **over)
        assert r.status_code == 422 and text in r.json()["detail"], (text, r.text)
    r = _gen(client, h, org, [CBH, SME_R], task=True)
    assert r.status_code == 422 and "Area Manager" in r.json()["detail"]
    r = _gen(client, h, org, [AM2], task=True)  # AM without an account and no e-mail
    assert r.status_code == 422 and "no dashboard account" in r.json()["detail"]


def test_cbh_only_email_only(client, org, mail):
    h = {"X-CSRF-Token": login(client, ADMIN)}
    r = _gen(client, h, org, [CBH], send=True)
    assert r.status_code == 201, r.text
    assert r.json()["emailQueued"] == 1 and len(r.json()["tickets"]) == 1
    tid = r.json()["id"]
    assert [m["To"] for m in mail.sent] == [CBH_MAIL]
    assert not any(p.get_filename() for p in mail.sent[0].walk())  # no workbook for a CBH
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["circle"] == org["circle"] and d["assignee"]["id"] is None
    assert [(x["role"], x["access"], x["emailStatus"]) for x in d["recipients"]] == [("CBH", "email", "SENT")]


def test_sme_only_dashboard_without_email(client, org, mail):
    h = {"X-CSRF-Token": login(client, ADMIN)}
    r = _gen(client, h, org, [SME_R])
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert mail.sent == [] and r.json()["emailQueued"] == 0
    hs = {"X-CSRF-Token": login(client, SME)}
    mine = client.get("/api/v1/tickets", params={"scope": "mine"}).json()
    assert tid in [t["id"] for t in mine["items"]]
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["start"] is True and d["can"]["close"] is False and d["myRole"] == "SME"
    assert client.post(f"/api/v1/tickets/{tid}/start", headers=hs).status_code == 200
    assert client.post(f"/api/v1/tickets/{tid}/close", json={}, headers=hs).status_code == 403
    # the AM viewer was not selected: the ticket is invisible to them
    login(client, VIEWER)
    assert client.get(f"/api/v1/tickets/{tid}").status_code == 404


def test_task_one_ticket_per_area_manager(client, org, mail):
    h = {"X-CSRF-Token": login(client, ADMIN)}
    r = _gen(client, h, org, [CBH, SME_R, AM(org), AM2], task=True, send=True)
    assert r.status_code == 201, r.text
    made = r.json()["tickets"]
    assert len(made) == 2 and r.json()["emailQueued"] == 6  # 2 tickets x (CBH, SME, AM)
    by_am = {}
    for t in made:
        d = client.get(f"/api/v1/tickets/{t['id']}").json()
        by_am[d["task"]["areaManager"]] = d
    first, second = by_am[org["am"]], by_am["Second Area Manager"]
    # every ticket of the batch names ITS OWN Area Manager and the week with its dates (not the subject typed once)
    wk = org["week"][2:]
    assert first["subject"].startswith(f"Weekly GP task – {org['am']} – Week {wk} (") and org["circle"] in first["subject"]
    assert second["subject"].startswith(f"Weekly GP task – Second Area Manager – Week {wk} (")
    # list rows carry the week dates; the AM's week filter lists the week with its ticket count
    row = next(x for x in client.get("/api/v1/tickets", params={"scope": "all", "week": org["week"]}).json()["items"] if x["id"] == first["id"])
    assert row["week"] == org["week"] and row["weekStart"] == first["task"]["week"]["start"] and row["weekEnd"] == first["task"]["week"]["end"]
    login(client, VIEWER)
    weeks = client.get("/api/v1/tickets/my-weeks").json()["weeks"]
    w = next(x for x in weeks if x["id"] == org["week"])
    assert w["total"] >= 1 and w["open"] >= 1 and w["start"] == first["task"]["week"]["start"]
    login(client, ADMIN)
    assert sorted(g["gpCode"] for g in first["task"]["gps"]) == sorted(org["first"])  # no GP of another AM
    assert sorted(g["gpCode"] for g in second["task"]["gps"]) == org["second"]
    assert first["task"]["circle"] == org["circle"] and first["assignee"]["email"] == VIEWER[0]
    assert second["assignee"]["id"] is None and second["assignee"]["email"] == AM2_MAIL
    # e-mail: everyone selected, workbook only to each AM and only their own
    files = {m["To"]: [p.get_filename() for p in m.walk() if p.get_filename()] for m in mail.sent}
    assert len(mail.sent) == 6
    assert files[VIEWER[0]] and "Weekly_GP_Assignment_Week_" in files[VIEWER[0]][0]
    assert files[AM2_MAIL] and files[AM2_MAIL][0].startswith("Second_Area_Manager")
    for m in mail.sent:
        if m["To"] in (CBH_MAIL, SME[0]):
            assert not [p for p in m.walk() if p.get_filename()]
    att = next(p for m in mail.sent if m["To"] == AM2_MAIL for p in m.walk() if p.get_filename())
    from python_calamine import CalamineWorkbook

    rows = CalamineWorkbook.from_filelike(io.BytesIO(att.get_payload(decode=True))).get_sheet_by_name("GP Task").to_python()
    assert sorted(r[7] for r in rows[5:] if r[7]) == org["second"] and all(r[2] == "Second Area Manager" for r in rows[5:] if r[7])

    # SME follows the AM's ticket read-only; the AM reports progress; nobody but the admin closes
    tid = first["id"]
    hs = {"X-CSRF-Token": login(client, SME)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["progress"] is False and d["can"]["start"] is False and d["myRole"] == "SME"
    # an SME sees only the GPs the Area Manager approved and forwarded to them – none yet
    assert d["task"]["scope"]["kind"] == "SME" and d["task"]["gps"] == []
    gp = first["task"]["gps"][0]
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": gp["id"], "achievedToday": 0, "remark": "x"}]}, headers=hs).status_code == 403
    ha = {"X-CSRF-Token": login(client, VIEWER)}
    assert client.get(f"/api/v1/tickets/{tid}").json()["can"]["progress"] is True
    assert client.get(f"/api/v1/tickets/{second['id']}").status_code == 404  # another AM's task
    open_gp = next(g for g in first["task"]["gps"] if g["gap"] > 0)
    r = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": open_gp["id"], "achievedToday": 1, "remark": "Done"}]}, headers=ha)
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS"
    assert client.post(f"/api/v1/tickets/{tid}/close", json={}, headers=ha).status_code == 403

    # admin monitoring filters
    h = {"X-CSRF-Token": login(client, ADMIN)}
    q = lambda **p: [t["id"] for t in client.get("/api/v1/tickets", params={"scope": "all", **p}).json()["items"]]  # noqa: E731
    assert tid in q(circle=org["circle"]) and tid in q(areaManager=org["am"]) and tid not in q(areaManager="Second Area Manager")
    assert tid in q(week=org["week"]) and tid in q(gp=open_gp["gpCode"]) and tid in q(progressDate=dt.date.today().isoformat())
    opts = client.get("/api/v1/tickets/filter-options").json()
    assert org["circle"] in opts["circles"] and org["am"] in opts["areaManagers"] and org["week"] in opts["weeks"]

    # admin closes: the closed status reaches every recipient with an account
    # (every GP of this ticket is achieved by now – nothing waits for the AM, so no reason is needed)
    assert client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "Reviewed"}, headers=h).json()["status"] == "CLOSED"
    login(client, SME)
    assert client.get(f"/api/v1/tickets/{tid}").json()["status"] == "CLOSED"
    assert any(n["kind"] == "CLOSED" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    ha = {"X-CSRF-Token": login(client, VIEWER)}
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": open_gp["id"], "achievedToday": 0, "remark": "late"}]}, headers=ha).status_code == 409


def test_mail_failure_keeps_the_ticket_and_can_be_retried(client, org, mail):
    h = {"X-CSRF-Token": login(client, ADMIN)}
    mail.fail_connect = True
    r = _gen(client, h, org, [SME_R, CBH], send=True)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert {x["emailStatus"] for x in d["recipients"]} == {"FAILED"} and "connect" in d["recipients"][0]["emailError"]
    mail.fail_connect = False
    cbh = next(x for x in d["recipients"] if x["role"] == "CBH")
    d = client.post(f"/api/v1/tickets/{tid}/recipients/{cbh['id']}/email", headers=h).json()
    with SessionLocal() as db:
        st = {x.role: x.email_status for x in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == tid))}
    assert st == {"CBH": "SENT", "SME": "FAILED"} and [m["To"] for m in mail.sent] == [CBH_MAIL]
    # the error text is for admins only
    login(client, SME)
    assert all(x["emailError"] is None for x in client.get(f"/api/v1/tickets/{tid}").json()["recipients"])


def test_manually_typed_recipient(client, org, mail):
    """Admin types any name + e-mail (not in the database): e-mail only without an account, User Tickets with one;
    on a GP task the typed recipient follows the ticket view only (like CBH / SME)."""
    h = {"X-CSRF-Token": login(client, ADMIN)}
    typed = {"role": "OTHER", "name": "Someone Typed", "email": "typed.person@example.com"}
    r = _gen(client, h, org, [{**typed, "email": "not-an-email"}])
    assert r.status_code == 422 and "valid e-mail" in r.json()["detail"]
    r = _gen(client, h, org, [typed])  # no account, e-mail off -> nobody would get it
    assert r.status_code == 422 and "dashboard account" in r.json()["detail"]
    r = _gen(client, h, org, [typed], send=True)
    assert r.status_code == 201, r.text
    assert [m["To"] for m in mail.sent] == ["typed.person@example.com"]
    d = client.get(f"/api/v1/tickets/{r.json()['id']}").json()
    assert [(x["role"], x["name"], x["access"]) for x in d["recipients"]] == [("OTHER", "Someone Typed", "email")]
    # typed e-mail of a dashboard account (any name): the account sees the task ticket, view only
    r = _gen(client, h, org, [AM(org), {"role": "OTHER", "name": "Typed Name", "email": SME[0].upper()}], task=True)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    login(client, SME)
    assert tid in [t["id"] for t in client.get("/api/v1/tickets", params={"scope": "mine"}).json()["items"]]
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["myRole"] == "OTHER" and d["can"]["progress"] is False and d["can"]["start"] is False
