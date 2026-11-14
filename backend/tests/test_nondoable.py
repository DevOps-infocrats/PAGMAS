"""Non-Doable GP exception workflow (app.tickets.nondoable): FE → AM → SME → COH → Corporate Team – MGG.

TC1 successful approval · TC2 rejection and revisit · TC3 returns for correction · TC4 permissions · TC5 audit trail,
no duplicate records / notifications. The normal A → B → E review chain is covered in test_ticket_categories."""

import datetime as dt
import json

import pytest
from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import NdCase, NdEvent, NdMggMember, NdRecord, Ticket, TicketNotification, TicketTaskGp, User

from .conftest import VIEWER, login
from .test_ticket_fe import FE1, FE2, PDF, _fe, _gen, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SME = ("nd.sme@pratap-test.in", "NdSme!Secure-Pass-81")
COH = ("nd.coh@pratap-test.in", "NdCoh!Secure-Pass-82")
MGG = ("nd.mgg@pratap-test.in", "NdMgg!Secure-Pass-83")
TODAY = dt.date.today().isoformat()
E1 = {"visitDate": TODAY, "visitorName": "Test FE One", "location": "26.1, 91.7", "reason": "River crossing – no right of way", "findings": "Site flooded, no access road"}
E2 = {"justification": "The GP cannot be reached for the next season – the FRT confirmed it.", "frtTeam": "FRT Guwahati-2 (lead R. Das)", "frtVisit": "Visited on site with the FE"}


@pytest.fixture
def nd(client, fe_org, mail):  # noqa: F811
    """A ticket with the test AM (viewer), FE One and FE Two; SME, COH and MGG accounts (MGG not authorised yet)."""
    h = {"X-CSRF-Token": login(client)}
    for email, pw in (SME, COH, MGG):
        assert client.post("/api/v1/users", json={"email": email, "name": email.split("@")[0].replace(".", " ").title(), "password": pw}, headers=h).status_code in (201, 409)
    with SessionLocal() as db:  # the database is shared by the tests: start without any MGG member
        db.execute(delete(NdMggMember))
        db.commit()
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0]), _fe("Test FE Two", FE2[0])])
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    login(client, FE1)
    gps = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]
    return {"tid": tid, "gps": gps}


def _h(client, creds=None):
    return {"X-CSRF-Token": login(client, creds) if creds else login(client)}


def _propose(client, tid, gid, remark="Not doable – flooded"):
    return client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": gid, "category": "D", "remark": remark}]}, headers=_h(client, FE1))


def _case_of(client, gid):
    items = client.get("/api/v1/nondoable/cases").json()["items"]
    return next(c for c in items if c["gpId"] == gid)


def _form(client, h, cid, kind, data, evidence=(), photos=(), extra=None):
    files = [("evidence", (n, b, t)) for n, b, t in evidence] + [("photos", (n, b, t)) for n, b, t in photos]
    return client.post(f"/api/v1/nondoable/cases/{cid}/{kind}", data={"payload": json.dumps(data), **(extra or {})}, files=files or None, headers=h)


def _act(client, h, cid, action, **body):
    return client.post(f"/api/v1/nondoable/cases/{cid}/action", json={"action": action, **body}, headers=h)


def _to_mgg(client, cid, authorise=True):
    """E1 + E2 by FE One, AM forward (SME typed), SME recommend (COH typed), COH forward to the MGG."""
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")], photos=[("site.png", PNG, "image/png")]).status_code == 200
    assert _form(client, h1, cid, "justification", E2).status_code == 200
    r = _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="Verified with the FRT report", to=[{"name": "Nd Sme", "email": SME[0]}])
    assert r.status_code == 200, r.text
    r = _act(client, _h(client, SME), cid, "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}])
    assert r.status_code == 200, r.text
    if authorise:
        ha = _h(client)
        with SessionLocal() as db:
            mid = db.scalar(select(User.id).where(User.email == MGG[0]))
        if not any(m["userId"] == mid for m in client.get("/api/v1/nondoable/mgg").json()["members"]):
            assert client.post("/api/v1/nondoable/mgg", json={"userId": mid}, headers=ha).status_code == 200
    r = _act(client, _h(client, COH), cid, "COH_FORWARD", remark="Forward to the Corporate Team")
    assert r.status_code == 200, r.text
    return r.json()


def test_tc1_successful_non_doable_approval(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    mail.sent.clear()
    assert _propose(client, tid, g["id"]).status_code == 200
    # the Area Manager: e-mail with the case reference + dashboard notification + the case in Non-Doable Cases
    am_mail = [m for m in mail.sent if m["To"] == VIEWER[0]]
    assert len(am_mail) == 1 and "Non-Doable proposed" in am_mail[0]["Subject"] and "ND-" in am_mail[0].get_body(("plain",)).get_content()
    login(client, VIEWER)
    assert any(n["kind"] == "NONDOABLE" and n["ticketId"] == tid and n["href"].startswith("/dashboard/tickets/non-doable") for n in client.get("/api/v1/tickets/notifications").json()["items"])
    c = _case_of(client, g["id"])
    assert c["status"] == "PROPOSED" and c["statusLabel"] == "Non-Doable – Proposed" and c["ref"].startswith("ND-") and c["pendingWith"] == "FE"
    assert client.get("/api/v1/nondoable/summary").json()["kpis"]["AM"]["total"] == 1
    gp_row = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["id"] == g["id"])
    assert gp_row["ndCase"]["ref"] == c["ref"] and gp_row["ndCase"]["open"]

    # FE: the GP continues only in the case; E2 needs E1; mandatory fields and evidence
    h1 = _h(client, FE1)
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g["id"], "category": "A"}]}, headers=h1).status_code == 409
    assert _form(client, h1, c["id"], "justification", E2).status_code == 409
    assert _form(client, h1, c["id"], "verification", {**E1, "visitorName": ""}, evidence=[("s.pdf", PDF, "application/pdf")]).status_code == 422
    assert _form(client, h1, c["id"], "verification", E1).status_code == 422  # no evidence / photo
    assert _form(client, h1, c["id"], "verification", E1, photos=[("s.pdf", PDF, "application/pdf")]).status_code == 422  # a photo must be an image
    assert _form(client, h1, c["id"], "verification", {**E1, "visitDate": "2999-01-01"}, evidence=[("s.pdf", PDF, "application/pdf")]).status_code == 422
    d = _form(client, h1, c["id"], "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")], photos=[("site.png", PNG, "image/png")])
    assert d.status_code == 200, d.text
    assert d.json()["case"]["status"] == "E1_DONE" and d.json()["case"]["physical"] == "SUBMITTED" and d.json()["case"]["evidence"] == "SUBMITTED"
    assert _form(client, h1, c["id"], "justification", {**E2, "frtTeam": ""}).status_code == 422
    mail.sent.clear()
    d = _form(client, h1, c["id"], "justification", E2)
    assert d.json()["case"]["status"] == "PENDING_AM" and d.json()["case"]["pendingWith"] == "AM"
    assert [m["To"] for m in mail.sent] == [VIEWER[0]] and "Pending AM Review" in mail.sent[0]["Subject"]
    nd_html = mail.sent[0].get_body(("html",)).get_content()
    assert "VIEW DASHBOARD" in nd_html and 'href="https://pagmas.pramaanu.co.in/login"' in nd_html and "localhost" not in nd_html  # the PAGMAS e-mail layout
    assert "cid:pagmas-logo" in nd_html and "Pending with" in nd_html

    # AM → SME (chosen in the picker) → COH → Corporate Team – MGG
    hv = _h(client, VIEWER)
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="ok").status_code == 422  # recommendation too short… and no SME
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="Verified with the FRT report").status_code == 422  # no SME on the ticket
    assert client.get(f"/api/v1/nondoable/cases/{c['id']}/contacts", params={"role": "SME"}).status_code == 200
    mail.sent.clear()
    d = _act(client, hv, c["id"], "AM_FORWARD", remark="Verified with the FRT report", to=[{"name": "Nd Sme", "email": SME[0]}])
    assert d.status_code == 200 and d.json()["case"]["status"] == "PENDING_SME"
    assert sorted(m["To"] for m in mail.sent) == sorted([SME[0], FE1[0]])
    login(client, SME)
    assert client.get("/api/v1/nondoable/summary").json()["kpis"]["SME"] == {"received": 1, "pending": 1, "recommended": 0, "returnedToAm": 0, "forwardedToCoh": 0}
    assert any(n["kind"] == "NONDOABLE" for n in client.get("/api/v1/tickets/notifications").json()["items"])
    hs = _h(client, SME)
    assert _act(client, hs, c["id"], "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}]).json()["case"]["status"] == "PENDING_COH"
    hc = _h(client, COH)
    r = _act(client, hc, c["id"], "COH_FORWARD", remark="Forward to the Corporate Team")
    assert r.status_code == 422 and "Corporate Team – MGG" in r.json()["detail"]  # nobody authorised yet and nobody typed
    ha = _h(client)
    with SessionLocal() as db:
        mid = db.scalar(select(User.id).where(User.email == MGG[0]))
    assert client.post("/api/v1/nondoable/mgg", json={"userId": mid}, headers=ha).status_code == 200
    hc = _h(client, COH)
    assert _act(client, hc, c["id"], "COH_FORWARD", remark="Forward to the Corporate Team").json()["case"]["status"] == "PENDING_MGG"
    assert _act(client, hc, c["id"], "MGG_APPROVE").status_code == 403  # only the MGG decides
    assert _act(client, _h(client), c["id"], "MGG_APPROVE").status_code == 403  # admins view only

    hm = _h(client, MGG)
    assert client.get("/api/v1/nondoable/summary").json()["kpis"]["MGG"]["pending"] == 1
    mail.sent.clear()
    d = _act(client, hm, c["id"], "MGG_APPROVE", remark="Approved")
    assert d.status_code == 200, d.text
    j = d.json()
    assert j["case"]["status"] == "APPROVED" and j["case"]["statusLabel"] == "Non-Doable – Approved" and j["case"]["decision"] == "APPROVED"
    assert [s["state"] for s in j["tracker"]] == ["done"] * 6
    assert {m["To"] for m in mail.sent} == {FE1[0], VIEWER[0], SME[0], COH[0]}
    assert _act(client, hm, c["id"], "MGG_APPROVE").status_code == 409  # decided once
    with SessionLocal() as db:
        gp = db.get(TicketTaskGp, g["id"])
        assert gp.review == "ND_APPROVED" and gp.gp_category == "D"
        assert db.get(Ticket, tid).status != "CLOSED"  # other GPs are still open
    login(client, FE1)
    row = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["id"] == g["id"])
    assert row["locked"] and row["reviewLabel"] == "Closed – Non-Doable"
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g["id"], "category": "A"}]}, headers=_h(client, FE1)).status_code == 409
    # evidence preview / download for the people of the case
    f = j["records"][0]["files"][0]
    assert client.get(f"/api/v1/nondoable/files/{f['id']}", params={"inline": True}).status_code == 200


def test_tc2_rejection_and_revisit(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    _propose(client, tid, g["id"])
    login(client, FE1)
    c = _case_of(client, g["id"])
    _to_mgg(client, c["id"])
    hm = _h(client, MGG)
    assert _act(client, hm, c["id"], "MGG_REJECT").status_code == 422  # the reason is mandatory
    mail.sent.clear()
    d = _act(client, hm, c["id"], "MGG_REJECT", reason="Alternate route via the block road is feasible")
    assert d.status_code == 200
    j = d.json()["case"]
    assert j["status"] == "REJECTED" and j["statusLabel"] == "Rejected – Action Required" and j["revisit"] == "COORDINATION" and j["pendingWith"] == "FE"
    assert FE1[0] in {m["To"] for m in mail.sent}
    with SessionLocal() as db:
        assert db.get(TicketTaskGp, g["id"]).gp_category == "C"  # back to Revisit Required, not locked
    login(client, FE1)
    assert any(n["kind"] == "NONDOABLE" and "Rejected" in n["title"] for n in client.get("/api/v1/tickets/notifications").json()["items"])
    # proposing again needs the FRT coordination and the new FRT site visit
    assert _propose(client, tid, g["id"]).status_code == 422
    h1 = _h(client, FE1)
    assert _form(client, h1, c["id"], "revisit", {"visitDate": TODAY, "visitorName": "FRT lead", "findings": "x" * 5, "outcome": "D"}, extra={"kind": "VISIT"}).status_code == 409
    assert _form(client, h1, c["id"], "revisit", {"frtTeam": "FRT Guwahati-2", "remarks": "Visit fixed for tomorrow"}, extra={"kind": "COORDINATION"}).json()["case"]["revisit"] == "FRT_VISIT"
    d = _form(client, h1, c["id"], "revisit", {"visitDate": TODAY, "visitorName": "FRT lead", "findings": "Route still blocked", "outcome": "D"}, photos=[("frt.png", PNG, "image/png")], extra={"kind": "VISIT"})
    assert d.json()["case"]["revisit"] == "FRT_UPDATED"
    # the FE reviews the GP: proposed again -> round 2, the rejected case's revisit is reviewed
    assert _propose(client, tid, g["id"], "Still not doable after the FRT visit").status_code == 200
    with SessionLocal() as db:
        rounds = list(db.scalars(select(NdCase).where(NdCase.task_gp_id == g["id"]).order_by(NdCase.id)))
        assert [(x.round, x.status, x.revisit_status) for x in rounds] == [(1, "REJECTED", "REVIEWED"), (2, "PROPOSED", None)]
        assert db.scalar(select(func.count()).select_from(NdRecord).where(NdRecord.case_id == c["id"], NdRecord.kind.like("REVISIT_%"))) == 2


def test_tc3_returns_for_correction(client, nd):
    tid, g = nd["tid"], nd["gps"][0]
    _propose(client, tid, g["id"])
    login(client, FE1)
    c = _case_of(client, g["id"])
    h1 = _h(client, FE1)
    _form(client, h1, c["id"], "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")])
    _form(client, h1, c["id"], "justification", E2)
    hv = _h(client, VIEWER)
    assert _act(client, hv, c["id"], "AM_RETURN").status_code == 422  # reason mandatory
    d = _act(client, hv, c["id"], "AM_RETURN", reason="Attach the FRT visit photographs")
    assert d.json()["case"]["status"] == "RETURNED_FE" and d.json()["case"]["statusLabel"] == "Returned to FE – Correction Required"
    h1 = _h(client, FE1)
    assert _form(client, h1, c["id"], "justification", E2, photos=[("frt.png", PNG, "image/png")]).json()["case"]["status"] == "PENDING_AM"
    hv = _h(client, VIEWER)
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="Photos attached now", to=[{"name": "Nd Sme", "email": SME[0]}]).json()["case"]["status"] == "PENDING_SME"
    hs = _h(client, SME)
    assert _act(client, hs, c["id"], "SME_RETURN", reason="Confirm the alternate route").json()["case"]["status"] == "RETURNED_AM"
    hv = _h(client, VIEWER)
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="No alternate route – confirmed").json()["case"]["status"] == "PENDING_SME"
    hs = _h(client, SME)
    assert _act(client, hs, c["id"], "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}]).json()["case"]["status"] == "PENDING_COH"
    hc = _h(client, COH)
    assert _act(client, hc, c["id"], "COH_RETURN", reason="Add the block office letter").status_code == 422  # target required
    d = _act(client, hc, c["id"], "COH_RETURN", reason="Add the block office letter", target="SME")
    assert d.json()["case"]["status"] == "RETURNED_SME" and d.json()["case"]["pendingWith"] == "SME"
    hs = _h(client, SME)
    assert _act(client, hs, c["id"], "SME_RECOMMEND", remark="Letter added – recommend").json()["case"]["status"] == "PENDING_COH"
    login(client, SME)
    k = client.get("/api/v1/nondoable/summary").json()["kpis"]
    assert k["SME"]["returnedToAm"] == 1 and k["SME"]["recommended"] == 1
    login(client, COH)
    assert client.get("/api/v1/nondoable/summary").json()["kpis"]["COH"]["returned"] == 1


def test_tc4_permissions(client, nd):
    tid, g = nd["tid"], nd["gps"][0]
    _propose(client, tid, g["id"])
    login(client, FE1)
    c = _case_of(client, g["id"])
    h1 = _h(client, FE1)
    d = _form(client, h1, c["id"], "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")])
    fid = d.json()["records"][0]["files"][0]["id"]
    # another FE: no case, no form, no file
    h2 = _h(client, FE2)
    assert all(x["id"] != c["id"] for x in client.get("/api/v1/nondoable/cases").json()["items"])
    assert client.get(f"/api/v1/nondoable/cases/{c['id']}").status_code == 404
    assert _form(client, h2, c["id"], "justification", E2).status_code == 404
    assert client.get(f"/api/v1/nondoable/files/{fid}").status_code == 404
    # the SME does not see the case before the AM forwards it
    login(client, SME)
    assert client.get(f"/api/v1/nondoable/cases/{c['id']}").status_code == 404
    # the AM cannot fill the FE's forms; the FE cannot review; nobody skips a stage
    hv = _h(client, VIEWER)
    assert _form(client, hv, c["id"], "justification", E2).status_code == 403
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="Skipping E2", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 409
    assert _act(client, hv, c["id"], "MGG_APPROVE").status_code == 403
    h1 = _h(client, FE1)
    _form(client, h1, c["id"], "justification", E2)
    assert _act(client, h1, c["id"], "AM_FORWARD", remark="FE trying").status_code == 403
    # only admins manage the Corporate Team – MGG; no account is created
    hv = _h(client, VIEWER)
    assert client.post("/api/v1/nondoable/mgg", json={"userId": 1}, headers=hv).status_code == 403
    ha = _h(client)
    assert client.post("/api/v1/nondoable/mgg", json={"userId": 999999}, headers=ha).status_code == 422
    # the admin reads every case but cannot act
    assert client.get(f"/api/v1/nondoable/cases/{c['id']}").json()["can"]["actions"] == []
    # the GP review chain cannot bypass the case
    assert client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], "action": "AM_RETURN", "remark": "Bypass the case"}, headers=_h(client, VIEWER)).status_code == 409


def test_tc5_audit_trail_and_no_duplicates(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    with SessionLocal() as db:
        gp_count = db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid))
        tickets = db.scalar(select(func.count()).select_from(Ticket))
    _propose(client, tid, g["id"])
    login(client, FE1)
    c = _case_of(client, g["id"])
    j = _to_mgg(client, c["id"])
    hv = _h(client, VIEWER)
    assert _act(client, hv, c["id"], "AM_FORWARD", remark="Second click", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 409  # no double step
    d = _act(client, _h(client, MGG), c["id"], "MGG_APPROVE", remark="Approved").json()
    actions = [(e["stage"], e["action"], e["role"]) for e in d["history"]]
    assert actions == [
        ("E1", "PROPOSED", "FE"), ("E1", "VERIFICATION", "FE"), ("E2", "JUSTIFICATION", "FE"), ("E3", "AM_FORWARD", "AM"),
        ("E4", "SME_RECOMMEND", "SME"), ("E5", "COH_FORWARD", "COH"), ("E6", "MGG_APPROVE", "MGG"),
    ]
    assert all(e["by"] and e["at"] and e["to"] for e in d["history"])
    assert d["history"][3]["recommendation"] == "Verified with the FRT report" and "Sent to SME" in d["history"][3]["remark"]
    assert [r["kind"] for r in d["records"]] == ["VERIFICATION", "JUSTIFICATION"] and j["case"]["ref"] == c["ref"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid)) == gp_count  # no duplicate GP
        assert db.scalar(select(func.count()).select_from(Ticket)) == tickets  # no new ticket
        assert db.scalar(select(func.count()).select_from(NdCase).where(NdCase.task_gp_id == g["id"])) == 1
        assert db.scalar(select(func.count()).select_from(NdEvent).where(NdEvent.case_id == c["id"])) == 7
        am = db.scalar(select(User.id).where(User.email == VIEWER[0]))
        # one notification per person and action: proposed, E1, E2, SME recommend, COH forward, MGG decision
        n = db.scalar(select(func.count()).select_from(TicketNotification).where(TicketNotification.user_id == am, TicketNotification.ticket_id == tid, TicketNotification.kind == "NONDOABLE"))
        assert n == 6


SME2 = ("nd.sme2@pratap-test.in", "NdSme2!Secure-Pass-84")
COH2 = ("nd.coh2@pratap-test.in", "NdCoh2!Secure-Pass-85")


def test_tc6_only_the_chosen_sme_and_coh(client, nd, mail):  # noqa: F811
    """A ticket with TWO SMEs and TWO COHs: the case, its actions and its e-mails reach only the SME the Area Manager
    chose (later: the one chosen when it is forwarded again) and only the COH the SME chose. Cases from before the
    choice was recorded stay with every SME / COH of the ticket."""
    from app.models import NdForward, TicketRecipient

    tid, g = nd["tid"], nd["gps"][0]
    ha = _h(client)
    for email, pw in (SME2, COH2):
        assert client.post("/api/v1/users", json={"email": email, "name": email.split("@")[0].replace(".", " ").title(), "password": pw}, headers=ha).status_code in (201, 409)
    with SessionLocal() as db:  # the second SME / COH are already on the ticket (e.g. chosen for other GPs)
        for email, role in ((SME2[0], "SME"), (COH2[0], "COH")):
            uid = db.scalar(select(User.id).where(User.email == email))
            db.add(TicketRecipient(ticket_id=tid, role=role, name=email.split("@")[0], email=email, user_id=uid, can_work=False, attach_workbook=False, email_status="NONE"))
        db.commit()
    _propose(client, tid, g["id"])
    login(client, FE1)
    cid = _case_of(client, g["id"])["id"]
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")]).status_code == 200
    assert _form(client, h1, cid, "justification", E2).status_code == 200

    def sees(creds):
        login(client, creds)
        return any(c["id"] == cid for c in client.get("/api/v1/nondoable/cases").json()["items"])

    # the AM forwards to SME One only
    mail.sent.clear()
    assert _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="Verified", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 200
    assert SME[0] in [m["To"] for m in mail.sent] and SME2[0] not in [m["To"] for m in mail.sent]
    assert sees(SME) and not sees(SME2)
    login(client, SME2)
    assert client.get(f"/api/v1/nondoable/cases/{cid}").status_code == 404
    assert _act(client, _h(client, SME2), cid, "SME_RECOMMEND", remark="Not mine", to=[{"name": "Nd Coh", "email": COH[0]}]).status_code == 404
    login(client, SME2)
    assert not any(n["ticketId"] == tid and "ND-" in n["title"] for n in client.get("/api/v1/tickets/notifications").json()["items"])

    # SME One sends it back; the AM now forwards it to SME Two: SME One no longer has it
    assert _act(client, _h(client, SME), cid, "SME_RETURN", reason="Check with another SME").status_code == 200
    assert _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="For SME Two", to=[{"name": "Nd Sme Two", "email": SME2[0]}]).status_code == 200
    assert sees(SME2) and not sees(SME)
    # SME Two recommends to COH One only
    mail.sent.clear()
    assert _act(client, _h(client, SME2), cid, "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}]).status_code == 200
    assert COH[0] in [m["To"] for m in mail.sent] and COH2[0] not in [m["To"] for m in mail.sent]
    assert sees(COH) and not sees(COH2)
    assert _act(client, _h(client, COH2), cid, "COH_RETURN", reason="Not mine", target="SME").status_code == 404
    # COH One returns it to the SME: the e-mail goes to SME Two only (the SME it is with), not SME One
    mail.sent.clear()
    assert _act(client, _h(client, COH), cid, "COH_RETURN", reason="Add the letter", target="SME").status_code == 200
    to = [m["To"] for m in mail.sent]
    assert SME2[0] in to and SME[0] not in to and COH2[0] not in to
    with SessionLocal() as db:
        assert {(f.role) for f in db.scalars(select(NdForward).where(NdForward.case_id == cid))} == {"SME", "COH"}
        # a case from before the choice was recorded (no forward rows): every SME of the ticket, as before
        db.execute(delete(NdForward).where(NdForward.case_id == cid))
        db.commit()
    assert sees(SME) and sees(SME2)
