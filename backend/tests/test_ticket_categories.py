"""GP classification of the daily progress (A–E): one current category per GP of a ticket (a change replaces it, the
progress lines keep the history), only E "Letter Submission Done" counts as achieved, FEs classify only their own GPs,
and the admin category KPIs / GP lists count each GP once with its Area Manager, FE, Block, documents and ticket."""

import datetime as dt

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import TicketProgressLine, TicketTaskGp
from app.tickets import task as tasks

from .conftest import VIEWER, login
from .test_ticket_fe import FE1, FE2, PDF, _fe, _gen, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _progress(client, h, tid, items):
    return client.post(f"/api/v1/tickets/{tid}/progress", json={"items": items}, headers=h)


def test_category_is_saved_replaced_and_drives_achievement(client, fe_org, mail):  # noqa: F811
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0]), _fe("Test FE Two", FE2[0])])
    assert r.status_code == 201, r.text
    tid, code = r.json()["id"], r.json()["code"]

    h1 = {"X-CSRF-Token": login(client, FE1)}
    mine = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]
    g = mine[0]
    base = g["baseAchieved"]
    assert g["gpCategory"] is None
    # invalid code / both forms / another FE's GP
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "Z"}]).status_code == 422
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A", "status": "DONE"}]).status_code == 422
    with SessionLocal() as db:
        other = db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == tid, TicketTaskGp.gp_code == fe_org["two"][0])).one()
    assert _progress(client, h1, tid, [{"taskGpId": other.id, "category": "B"}]).status_code == 403

    # B / E are not the FE's: they come from the AM / SME / COH review
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "B"}]).status_code == 422
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "E"}]).status_code == 422
    # C (not achieved) -> saved, persists
    d = _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "C", "remark": "Revisit with FRT"}])
    assert d.status_code == 200, d.text
    row = next(x for x in d.json()["task"]["gps"] if x["id"] == g["id"])
    assert row["gpCategory"] == "C" and row["cumulative"] == min(1, base)
    assert client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]["gpCategory"] == "C"  # after a reload
    # changed to A -> the same record is updated; same category again = nothing new
    d = _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A"}]).json()
    assert next(x for x in d["task"]["gps"] if x["id"] == g["id"])["gpCategory"] == "A"
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A"}]).status_code == 422
    assert d["task"]["totals"]["categories"]["A"] == 1 and d["task"]["totals"]["notClassified"] == len(mine) - 1
    assert d["task"]["totals"]["review"]["awaiting"] == 1

    # review chain: Area Manager approves (A -> B), SME forwards, COH records the letter (E = achieved) and the AMC
    today = dt.date.today().isoformat()

    def rev(hh, **b):
        return client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], **b}, headers=hh)

    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert client.get(f"/api/v1/tickets/{tid}").json()["can"]["reviewAs"] == ["AM"]
    assert rev(hv, action="SME_FORWARD", remark="ok", category="B").status_code == 403  # the AM is not the SME
    assert rev(hv, action="AM_APPROVE").status_code == 422  # remark required
    assert rev(hv, action="AM_APPROVE", remark="Evidence verified").status_code == 422  # no SME chosen
    sme = client.get(f"/api/v1/tickets/{tid}/review-contacts", params={"role": "SME"})
    assert sme.status_code == 200 and sme.json()["role"] == "SME"
    assert client.get(f"/api/v1/tickets/{tid}/review-contacts", params={"role": "COH"}).status_code == 403  # the AM does not choose the COH
    assert rev(hv, action="AM_APPROVE", remark="Evidence verified", to=[{"name": "x", "email": "not-an-email"}]).status_code == 422
    mail.sent.clear()
    d = rev(hv, action="AM_APPROVE", remark="Evidence verified", to=[{"name": "Typed SME", "email": "typed.sme@example.com"}])
    assert d.status_code == 200, d.text
    assert any(r["role"] == "SME" and r["email"] == "typed.sme@example.com" for r in d.json()["recipients"])
    assert [m["To"] for m in mail.sent] == ["typed.sme@example.com"] and "Evidence verified" in mail.sent[0].get_body(("plain",)).get_content()
    row = next(x for x in d.json()["task"]["gps"] if x["id"] == g["id"])
    assert row["gpCategory"] == "B" and row["review"] == "AM_APPROVED" and row["locked"]
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "C"}]).status_code == 409  # approved = locked
    ha = {"X-CSRF-Token": login(client)}
    assert rev(ha, action="COH_LETTER", date=today).status_code == 409  # not forwarded by the SME yet
    assert rev(ha, action="SME_FORWARD", remark="Confirmed", category="B").status_code == 422  # no COH chosen
    assert rev(ha, action="SME_FORWARD", remark="Confirmed", category="B", to=[{"name": "Typed COH", "email": "typed.coh@example.com"}]).status_code == 200
    d = rev(ha, action="COH_LETTER", date=today).json()
    row = next(x for x in d["task"]["gps"] if x["id"] == g["id"])
    assert row["gpCategory"] == "E" and row["cumulative"] == 1 and row["gap"] == 0 and row["review"] == "LETTER_SUBMITTED" and row["letterDate"] == today
    d = rev(ha, action="COH_AMC", date=today).json()
    row = next(x for x in d["task"]["gps"] if x["id"] == g["id"])
    assert row["review"] == "AMC_CONVERTED" and row["amcOn"] == today
    assert [(x["role"], x["action"]) for x in row["trail"]] == [("AM", "AM_APPROVE"), ("ADMIN", "SME_FORWARD"), ("ADMIN", "COH_LETTER"), ("ADMIN", "COH_AMC")]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid, TicketTaskGp.gp_code == g["gpCode"])) == 1
        hist = [ln.category for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.task_gp_id == g["id"]).order_by(TicketProgressLine.id))]
    assert hist == ["C", "A", "B", None, "E", None]
    h1 = {"X-CSRF-Token": login(client, FE1)}
    # proof document with a category (FE Two) -> Attached in the admin list
    h2 = {"X-CSRF-Token": login(client, FE2)}
    g2 = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    ok = client.post(
        f"/api/v1/tickets/{tid}/progress-form",
        data={"payload": '{"items": [{"taskGpId": %d, "category": "D", "remark": "Not doable"}]}' % g2["id"], "proofGps": [str(g2["id"])]},
        files=[("proofs", ("proposal.pdf", PDF, "application/pdf"))],
        headers=h2,
    )
    assert ok.status_code == 200, ok.text

    # admin: five KPIs, each GP once, lists with AM / FE / Block / documents / ticket
    login(client)
    s = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code}).json()
    assert s["categories"] == {"A": 0, "B": 0, "C": 0, "D": 1, "E": 1}
    assert s["notClassified"] == s["total"] - 2 and s["categoryWithDocument"]["D"] == 1 and s["categoryWithDocument"]["E"] == 0
    c = client.get("/api/v1/tickets/gp-monitor", params={"category": "E", "ticket": code}).json()
    assert c["total"] == 1 and c["kpis"]["categories"]["E"] == 1
    x = c["items"][0]
    assert x["gpCode"] == g["gpCode"] and x["gpCategory"] == "E" and x["fieldEngineer"] == "Test FE One" and x["areaManager"] == fe_org["am"]
    assert x["block"] == next(y["block"] for y in mine if y["id"] == g["id"]) and x["ticket"] == code and x["categoryTicket"] == code and x["files"] == []
    dd = client.get("/api/v1/tickets/gp-monitor", params={"category": "D", "ticket": code}).json()["items"][0]
    assert dd["fieldEngineer"] == "Test FE Two" and dd["files"][0]["fileName"] == "proposal.pdf"
    assert client.get(f"/api/v1/tickets/progress-files/{dd['files'][0]['id']}").status_code == 200
    # filters apply to the KPIs and the lists alike
    f1 = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code, "fe": "Test FE One"}).json()
    assert f1["categories"] == {"A": 0, "B": 0, "C": 0, "D": 0, "E": 1}
    assert client.get("/api/v1/tickets/gp-monitor", params={"category": "D", "ticket": code, "fe": "Test FE One"}).json()["total"] == 0
    fe_rows = {b["fieldEngineer"]: b for b in s["byFe"]}
    assert fe_rows["Test FE One"]["categories"]["E"] == 1 and fe_rows["Test FE Two"]["categories"]["D"] == 1
    # either a status or a category
    assert client.get("/api/v1/tickets/gp-monitor", params={"category": "A", "status": "DONE"}).status_code == 422
    assert client.get("/api/v1/tickets/gp-monitor").status_code == 422
    # GP detail: current category and the classified history
    det = client.get(f"/api/v1/tickets/gp-monitor/gps/{g['gpCode']}").json()
    assert det["gpCategory"] == "E" and {"A", "B", "C", "E"} <= {h_["gpCategory"] for h_ in det["history"] if h_["source"] == "progress"}
    assert tasks.CATEGORIES["B"] == "Ready for Letter Submission"


def test_last_updated_by_and_fe_wise_categories(client, fe_org):
    """The Area Manager sees who (which FE) updated each GP and the FE-wise category split of the ticket."""
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0])])
    tid = r.json()["id"]
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A"}]).status_code == 200
    login(client, VIEWER)
    task = client.get(f"/api/v1/tickets/{tid}").json()["task"]
    row = next(x for x in task["gps"] if x["id"] == g["id"])
    assert row["lastUpdatedBy"] == FE1[0].split("@")[0] and row["lastUpdated"]
    assert all(x["lastUpdatedBy"] is None for x in task["gps"] if x["id"] != g["id"])
    fe1 = next(f for f in task["fes"] if f["name"] == "Test FE One")
    assert fe1["categories"]["A"] == 1 and fe1["notClassified"] == fe1["gps"] - 1


def test_fe_edits_adds_gps_and_am_returns(client, fe_org, mail):  # noqa: F811
    """The FE corrects GP Name / Block, adds a GP (target 1, counted), the Area Manager is notified and e-mailed, and a
    GP returned by the Area Manager goes back to them with the FE's next change."""
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0])])
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    h1 = {"X-CSRF-Token": login(client, FE1)}
    t0 = client.get(f"/api/v1/tickets/{tid}").json()["task"]
    g = t0["gps"][0]
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "gpName": "  "}]).status_code == 422
    mail.sent.clear()
    d = _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A", "gpName": "Renamed  GP", "block": "Block X", "remark": "Rectified with FRT"}])
    assert d.status_code == 200, d.text
    row = next(x for x in d.json()["task"]["gps"] if x["id"] == g["id"])
    assert row["gpName"] == "Renamed GP" and row["block"] == "Block X" and row["trail"][0]["action"] == "EDIT" and "Renamed GP" in row["trail"][0]["remark"]
    body = mail.sent[0].get_body(("plain",)).get_content()
    assert [m["To"] for m in mail.sent] == [VIEWER[0]] and "Renamed GP" not in body and "To see which GPs are your target GPs" in body  # GP details: dashboard only

    add = lambda gps: client.post(f"/api/v1/tickets/{tid}/progress", json={"newGps": gps}, headers=h1)  # noqa: E731
    assert add([{"gpCode": "ZZNEW1"}]).status_code == 422  # not in the master data and no name
    assert add([{"gpCode": g["gpCode"], "gpName": "x"}]).status_code == 422  # already in the ticket
    assert add([{"gpCode": "bad code!", "gpName": "x"}]).status_code == 422
    assert add([{"gpCode": "ZZNEW1", "gpName": "Fresh", "category": "B"}]).status_code == 422  # FE categories only
    d = add([{"gpCode": "ZZNEW1", "gpName": "Fresh GP", "block": "B1", "category": "C", "remark": "Found during visit"}])
    assert d.status_code == 200, d.text
    task = d.json()["task"]
    new = next(x for x in task["gps"] if x["gpCode"] == "ZZNEW1")
    assert new["kind"] == "ADDED" and new["target"] == 1 and new["feName"] == "Test FE One" and new["gpCategory"] == "C" and new["trail"][0]["action"] == "ADD"
    assert task["totals"]["target"] == t0["totals"]["target"] + 1 and task["totals"]["addedGps"] == 1
    assert add([{"gpCode": "ZZNEW1", "gpName": "again"}]).status_code == 422

    hv = {"X-CSRF-Token": login(client, VIEWER)}
    am_view = client.get(f"/api/v1/tickets/{tid}").json()
    assert any(n["kind"] == "PROGRESS" for n in client.get("/api/v1/tickets/notifications").json()["items"])
    fe1 = next(f for f in am_view["task"]["fes"] if f["name"] == "Test FE One")
    assert fe1["awaitingGps"] == 1 and fe1["addedGps"] == 1
    d = client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], "action": "AM_RETURN", "remark": "Photo missing"}, headers=hv)
    assert d.status_code == 200, d.text
    assert next(x for x in d.json()["task"]["gps"] if x["id"] == g["id"])["review"] == "RETURNED"
    assert client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], "action": "AM_APPROVE", "remark": "Looks fine"}, headers=hv).status_code == 409
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert any(n["kind"] == "REVIEW" for n in client.get("/api/v1/tickets/notifications").json()["items"])
    d = _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A", "remark": "After photo attached"}])
    assert d.status_code == 200, d.text
    assert next(x for x in d.json()["task"]["gps"] if x["id"] == g["id"])["review"] is None

def test_sme_chosen_before_account_sees_ticket_on_dashboard(client, fe_org, mail):  # noqa: F811
    """The Area Manager sends GPs to an SME e-mail that has no dashboard account yet: once the account exists, the
    ticket is in the SME's User Tickets with a notification and the SME can forward it."""
    h = {"X-CSRF-Token": login(client)}
    tid = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0])]).json()["id"]
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    assert _progress(client, h1, tid, [{"taskGpId": g["id"], "category": "A"}]).status_code == 200
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], "action": "AM_APPROVE", "remark": "Verified", "to": [{"name": "Late SME", "email": "late.sme@pratap-test.in"}]}, headers=hv)
    assert d.status_code == 200, d.text
    sme = next(r for r in d.json()["recipients"] if r["email"] == "late.sme@pratap-test.in")
    assert sme["role"] == "SME" and sme["access"] == "email"

    ha = {"X-CSRF-Token": login(client)}
    pw = "Late!Sme-Pass123"
    assert client.post("/api/v1/users", json={"email": "late.sme@pratap-test.in", "name": "Late SME", "password": pw}, headers=ha).status_code == 201
    login(client, ("late.sme@pratap-test.in", pw))
    assert tid in [x["id"] for x in client.get("/api/v1/tickets", params={"scope": "mine"}).json()["items"]]
    assert any(n["kind"] == "REVIEW" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    det = client.get(f"/api/v1/tickets/{tid}").json()
    assert det["myRole"] == "SME" and det["can"]["reviewAs"] == ["SME"]