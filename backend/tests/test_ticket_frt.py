"""FRT team in the GP-wise task: FRT → FE → Area Manager.

* a dashboard account with an FRT code (User Management) is put on the task tickets whose GPs have that FRT code in the
  Escalation Matrix; it sees and reports ONLY those GPs (Rectification Done / Revisit Required, remark + photo);
* the FRT's Daily Achievement goes to the FE (Pending FE Verification) – never straight to the Area Manager; the FE
  verifies it (to the Area Manager) or returns it to the FRT, with a remark; the FE no longer reports such a GP;
* the Area Manager cannot approve / return a GP before the FE verified it; a GP the AM returns goes back FE → FRT;
* GPs without an FRT account on the ticket stay with the FE exactly as before; the FRT-wise target is shown.
"""

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import TicketGpReview, TicketRecipient, User
from app.security.core import hash_password
from app.tickets import task as tasks

from .conftest import VIEWER, login
from .evidence import JPG, progress, review
from .test_ticket_fe import FE1, FE2, _fe, _gen, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

FRT = ("frt.one@pratap-test.in", "FrtOne!Secure-Pass-73")
CODE = "FRT-T1"


@pytest.fixture
def frt_org(fe_org, monkeypatch):  # noqa: F811
    """fe_org with FE One's GPs under FRT team FRT-T1 (Escalation Matrix) and an FRT account for that code."""
    base = tasks._directory

    def with_frt(store):
        d, src = base(store)
        d = d.copy()
        d["frt"] = None
        d.loc[d.index.isin(fe_org["one"]), "frt"] = CODE
        return d, src

    monkeypatch.setattr(tasks, "_directory", with_frt)
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == FRT[0])).first()
        if u is None:
            db.add(User(email=FRT[0], name="Frt One", role="viewer", password_hash=hash_password(FRT[1]), frt_code=CODE))
        else:
            u.frt_code, u.is_active = CODE, True
        db.commit()
    yield fe_org
    with SessionLocal() as db:  # other tests never see an FRT account
        u = db.scalars(select(User).where(User.email == FRT[0])).first()
        if u is not None:
            u.frt_code = None
            db.commit()


def _ticket(client, org):
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, org, [{"role": "AM", "name": org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0]), _fe("Test FE Two", FE2[0])])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _check(client, tid, ids, action, remark, h):
    return client.post(f"/api/v1/tickets/{tid}/fe-check", json={"taskGpIds": ids, "action": action, "remark": remark}, headers=h)


def _gp(client, tid, gid):
    return next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["id"] == gid)


def test_frt_reports_fe_verifies_am_approves(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    login(client)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert any(r["role"] == "FRT" and r["email"] == FRT[0] for r in d["recipients"])
    frt_gps = [g for g in d["task"]["gps"] if g["gpCode"] in frt_org["one"]]
    assert frt_gps and all(g["frtCode"] == CODE and g["frtAssigned"] for g in frt_gps)
    assert all(not g["frtAssigned"] for g in d["task"]["gps"] if g["gpCode"] not in frt_org["one"])
    row = next(f for f in d["task"]["frts"] if f["code"] == CODE)
    assert row["gps"] == row["target"] == len(frt_org["one"]) and row["names"] == ["Frt One"] and row["fes"] == ["Test FE One"]
    g = frt_gps[0]["id"]

    # the FRT: only the GPs of their code, may work, notified
    hf = {"X-CSRF-Token": login(client, FRT)}
    mine = client.get(f"/api/v1/tickets/{tid}").json()
    assert mine["task"]["scope"]["kind"] == "FRT" and mine["task"]["scope"]["frtCode"] == CODE and mine["can"]["progress"] is True
    assert {x["gpCode"] for x in mine["task"]["gps"]} == set(frt_org["one"])
    assert not any(r["role"] == "FE" and r["email"] == FE2[0] for r in mine["recipients"])
    assert any(n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    # same evidence rule (Non-Doable by the FRT: tests/test_nd_frt.py)
    assert progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Done"}], hf, photo=False).status_code == 422
    # (the FRT may add GPs found in the field – test_frt_corrects_gp_details_and_adds_a_gp)
    other = next(x["id"] for x in d["task"]["gps"] if x["gpCode"] in frt_org["two"])
    assert progress(client, tid, [{"taskGpId": other, "category": "A"}], hf).status_code == 403  # not their GP
    r = progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Splicing done by FRT"}], hf)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g)
    assert row["frtStage"] == "PENDING_FE" and row["stage"] == "PENDING_FE" and row["feSubmission"]["submittedByRole"] == "FRT"

    # the FE no longer reports it (only checks it); the Area Manager cannot act before the FE verified it
    h1 = {"X-CSRF-Token": login(client, FE1)}
    fe_view = client.get(f"/api/v1/tickets/{tid}").json()["task"]
    assert any(f["code"] == CODE for f in fe_view["frts"]) and fe_view["totals"]["review"]["pendingFe"] >= 1
    assert progress(client, tid, [{"taskGpId": g, "category": "C", "remark": "FE on behalf"}], h1).status_code == 403
    assert any("verify" in n["title"].lower() for n in client.get("/api/v1/tickets/notifications").json()["items"] if n["ticketId"] == tid)
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    am_fes = client.get(f"/api/v1/tickets/{tid}").json()["task"]["fes"]  # FE-wise table: waiting for the FE's verification
    assert sum(f["pendingFeGps"] for f in am_fes) >= 1 and sum(f["awaitingGps"] for f in am_fes) == 0
    assert progress(client, tid, [{"taskGpId": g, "category": "A"}], hv).status_code == 403
    assert review(client, tid, {"taskGpIds": [g], "action": "AM_APPROVE", "remark": "Approve it", "to": [{"name": "Sme", "email": "frt.sme@pratap-test.in"}]}, hv).status_code == 409

    # FE returns it to the FRT (reason required); FE Two cannot touch FE One's GP
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g], "FE_RETURN", " ", h1).status_code == 422
    assert _check(client, tid, [g], "FE_VERIFY", "x", h1).status_code == 422
    r = _check(client, tid, [g], "FE_RETURN", "Photo is not of this GP", h1)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g)
    assert row["frtStage"] == "RETURNED_FRT" and row["frtCheck"]["action"] == "FE_RETURN" and row["frtCheck"]["remark"] == "Photo is not of this GP"
    assert _check(client, tid, [g], "FE_VERIFY", "Looks fine", h1).status_code == 409  # nothing submitted again yet
    assert _check(client, tid, [g], "FE_VERIFY", "Looks fine", {"X-CSRF-Token": login(client, FE2)}).status_code == 422

    # the FRT corrects it (remark + photo again) and the FE verifies it: now with the Area Manager
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g, "remark": "New photo"}], hf, photo=False).status_code == 422
    assert progress(client, tid, [{"taskGpId": g, "remark": "New photo of the OLT"}], hf, extra_files=[(g, ("olt.jpg", JPG, "image/jpeg"))]).status_code == 200
    assert _gp(client, tid, g)["frtStage"] == "PENDING_FE"
    h1 = {"X-CSRF-Token": login(client, FE1)}
    r = _check(client, tid, [g], "FE_VERIFY", "Checked photo and remark", h1)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g)
    assert row["frtStage"] == "FE_VERIFIED" and row["stage"] == "PENDING_AM"
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g, "category": "C"}], hf).status_code == 409  # with the AM now

    # the Area Manager returns it: FE → FRT → FE → AM again
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert review(client, tid, {"taskGpIds": [g], "action": "AM_RETURN", "remark": "Wrong GP board"}, hv).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g], "FE_VERIFY", "again", h1).status_code == 409  # the FRT corrects it first
    assert _check(client, tid, [g], "FE_RETURN", "AM: wrong GP board", h1).status_code == 200
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Correct board now"}], hf).status_code == 200
    row = _gp(client, tid, g)
    assert row["stage"] == "PENDING_FE" and row["review"] == "RETURNED"
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g], "FE_VERIFY", "Board checked", h1).status_code == 200
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert _gp(client, tid, g)["stage"] == "PENDING_AM"
    r = review(client, tid, {"taskGpIds": [g], "action": "AM_APPROVE", "remark": "Verified", "to": [{"name": "Sme", "email": "frt.sme@pratap-test.in"}]}, hv)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        steps = [x.action for x in db.scalars(select(TicketGpReview).where(TicketGpReview.task_gp_id == g).order_by(TicketGpReview.id))]
    assert steps == ["FE_RETURN", "FE_VERIFY", "AM_RETURN", "FE_RETURN", "FE_VERIFY", "AM_APPROVE"]


def test_gps_without_frt_stay_with_the_fe(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    h2 = {"X-CSRF-Token": login(client, FE2)}
    g2 = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    assert not g2["frtAssigned"] and g2["gpCode"] in frt_org["two"]
    r = progress(client, tid, [{"taskGpId": g2["id"], "category": "A", "remark": "FE Two did it"}], h2)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g2["id"])
    assert row["stage"] == "PENDING_AM" and row["frtStage"] is None
    assert _check(client, tid, [g2["id"]], "FE_VERIFY", "nothing to verify", h2).status_code == 409


def test_fe_reports_an_frt_gp_only_while_the_frt_has_not(client, frt_org, mail):  # noqa: F811
    """A GP with an FRT login: while the FRT has reported nothing the FE may report it itself – straight to the Area
    Manager (no FE check); once the FRT reported it, the FE only verifies / returns it (no category, remark or proof)."""
    tid = _ticket(client, frt_org)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["frtAssigned"])
    # nothing from the FRT – the FE reports it, it waits for the Area Manager (not for an FE check)
    r = progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Done by the FE"}], h1)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g["id"])
    assert row["gpCategory"] == "A" and row["frtStage"] is None and row["stage"] == "PENDING_AM"
    # the FRT reports it after all: from now on the FE only checks it
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "C", "remark": "Revisit needed – FRT"}], hf).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    for items in ([{"taskGpId": g["id"], "category": "D", "remark": "Pole missing on the route"}], [{"taskGpId": g["id"], "remark": "FE note"}]):
        r = progress(client, tid, items, h1)
        assert r.status_code == 403 and "Verify / Return" in r.json()["detail"], r.text
    assert progress(client, tid, [], h1, extra_files=[(g["id"], ("fe.jpg", JPG, "image/jpeg"))]).status_code == 403
    assert _gp(client, tid, g["id"])["frtStage"] == "PENDING_FE"


def test_frt_code_in_user_management_follows_open_tickets(client, frt_org, mail, monkeypatch):  # noqa: F811
    from app.analytics import escalation

    monkeypatch.setattr(escalation, "_active", lambda: None)  # no matrix to check the code against in this test
    tid = _ticket(client, frt_org)
    h = {"X-CSRF-Token": login(client)}
    # an admin is never an FRT account
    r = client.post("/api/v1/users", json={"email": "frt.admin@pratap-test.in", "name": "Frt Admin", "role": "admin", "password": "FrtAdm!Secure-Pass-74", "frtCode": CODE}, headers=h)
    assert r.status_code == 422
    # a new FRT account joins the open ticket with GPs of its code
    r = client.post("/api/v1/users", json={"email": "frt.two@pratap-test.in", "name": "Frt Two", "role": "viewer", "password": "FrtTwo!Secure-Pass-75", "frtCode": " frt-t1 "}, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["frtCode"] == CODE
    with SessionLocal() as db:
        assert db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == tid, TicketRecipient.user_id == uid, TicketRecipient.role == "FRT")).first() is not None
    # removing the code takes it off the open ticket again
    assert client.patch(f"/api/v1/users/{uid}", json={"frtCode": ""}, headers=h).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == tid, TicketRecipient.user_id == uid)).first() is None
    client.post(f"/api/v1/users/{uid}/delete", headers=h)


def test_generate_preview_shows_the_frt_wise_target(client, frt_org):
    login(client)
    p = client.get("/api/v1/tickets/task/preview", params={"am": frt_org["am"], "week": frt_org["week"], "circle": frt_org["circle"]}).json()
    rows = {r["gpCode"]: r for r in p["rows"]}
    assert all(rows[c]["frtCode"] == CODE for c in frt_org["one"] if c in rows)
    frt = next(f for f in p["summary"]["frts"] if f["code"] == CODE)
    assert frt["week"]["gps"] == sum(1 for c in frt_org["one"] if c in rows) and frt["logins"] == ["Frt One"] and frt["fes"] == ["Test FE One"]
    assert p["summary"]["noFrt"]["week"]["gps"] == len(rows) - frt["week"]["gps"]


def test_frt_corrects_gp_details_and_adds_a_gp(client, frt_org, mail):  # noqa: F811
    """The FRT corrects GP Code / GP Name / Block of its GPs and adds a GP found in the field: the added GP gets the
    FRT's code and the FRT's FE, and goes to that FE for verification like any FRT report."""
    tid = _ticket(client, frt_org)
    hf = {"X-CSRF-Token": login(client, FRT)}
    mine = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]
    g, other = mine[0], (mine[1] if len(mine) > 1 else None)
    # invalid / duplicate codes are refused, nothing changes
    assert progress(client, tid, [{"taskGpId": g["id"], "gpCode": "bad code!"}], hf).status_code == 422
    if other:
        r = progress(client, tid, [{"taskGpId": g["id"], "gpCode": other["gpCode"]}], hf)
        assert r.status_code == 422 and "already in this ticket" in r.json()["detail"]
    r = progress(client, tid, [{"taskGpId": g["id"], "gpCode": "FRTFIX-1", "gpName": "Corrected Name", "block": "Corrected Block"}], hf)
    assert r.status_code == 200, r.text
    row = _gp(client, tid, g["id"])
    assert (row["gpCode"], row["gpName"], row["block"]) == ("FRTFIX-1", "Corrected Name", "Corrected Block")
    with SessionLocal() as db:
        assert any("GP Code" in (x.remark or "") for x in db.scalars(select(TicketGpReview).where(TicketGpReview.task_gp_id == g["id"])))

    # a new GP (not in the master data: name required) with Rectification Done + remark + photo
    assert progress(client, tid, new_gps=[{"gpCode": "FRTNEW-1", "category": "A"}], headers=hf).status_code == 422  # no name
    assert progress(client, tid, new_gps=[{"gpCode": "FRTFIX-1", "gpName": "Dup", "category": "A"}], headers=hf).status_code == 422  # renamed code taken
    r = progress(client, tid, new_gps=[{"gpCode": "FRTNEW-1", "gpName": "Field GP", "block": "Field Block", "category": "A", "remark": "Found in the field"}], headers=hf)
    assert r.status_code == 200, r.text
    new = next(x for x in r.json()["task"]["gps"] if x["gpCode"] == "FRTNEW-1")
    assert new["kind"] == "ADDED" and new["frtAssigned"] and new["frtCode"] == CODE and new["feName"] == "Test FE One" and new["frtStage"] == "PENDING_FE"
    # the FRT's FE sees it and verifies it (to the Area Manager); FE Two does not see it
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert any(x["id"] == new["id"] for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"])
    r = _check(client, tid, [new["id"]], "FE_VERIFY", "Checked the new GP", h1)
    assert r.status_code == 200, r.text
    login(client, FE2)
    assert not any(x["id"] == new["id"] for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"])


def test_fe_corrects_details_of_own_gps_only(client, frt_org, mail):  # noqa: F811
    """The FE corrects GP Code / GP Name / Block of its own GPs (no FRT login); an FRT's GP stays with the FRT."""
    tid = _ticket(client, frt_org)
    h2 = {"X-CSRF-Token": login(client, FE2)}  # FE Two's GPs have no FRT
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    r = progress(client, tid, [{"taskGpId": g["id"], "gpCode": "FEFIX-1", "gpName": "FE Name", "block": "FE Block"}], h2)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g["id"])
    assert (row["gpCode"], row["gpName"], row["block"]) == ("FEFIX-1", "FE Name", "FE Block")
    # an FRT's GP the FRT has reported: the FE cannot change it any more
    login(client, FE1)
    f = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["frtAssigned"])
    assert progress(client, tid, [{"taskGpId": f["id"], "category": "A", "remark": "Splicing done by FRT"}], {"X-CSRF-Token": login(client, FRT)}).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert progress(client, tid, [{"taskGpId": f["id"], "gpName": "FE trying"}], h1).status_code == 403
