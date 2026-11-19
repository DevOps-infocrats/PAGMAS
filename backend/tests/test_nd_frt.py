"""Non-Doable proposed by the FRT: FRT → FE review → Area Manager (app.tickets.nondoable).

* the FRT proposes Non-Doable in its Daily Achievement (remark + photo) – the case starts with the FRT;
* the FRT MAY fill E1 / E2 (every field optional) and submits to the FE with or without them;
* the FE reviews it: completes / corrects E1 / E2 (own rows – the FRT's rows stay), and can forward to the Area Manager
  ONLY when the latest E1 and E2 are complete (backend rule) – or return it to the FRT / withdraw it;
* only the right role acts at each stage; the AM gets the case only after the FE's forward; full history kept.
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import NdEvent, NdRecord, TicketNotification, User

from .conftest import VIEWER, login
from .evidence import progress
from .test_nondoable import COH, E1, E2, MGG, PNG, SME, TODAY, _act, _form
from .test_ticket_fe import FE1, FE2, PDF, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import FRT, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _h(client, creds=None):
    return {"X-CSRF-Token": login(client, creds) if creds else login(client)}


def _frt_case(client, org):
    """A ticket with the FRT; the FRT proposes Non-Doable on one of its GPs. Returns (ticket id, GP id, case id)."""
    tid = _ticket(client, org)
    hf = _h(client, FRT)
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]["id"]
    r = progress(client, tid, [{"taskGpId": g, "category": "D", "remark": "Pole line destroyed – not doable"}], hf)
    assert r.status_code == 200, r.text
    cid = next(c for c in client.get("/api/v1/nondoable/cases").json()["items"] if c["gpId"] == g)["id"]
    return tid, g, cid


def _case(client, cid, creds=None):
    login(client, creds) if creds else login(client)
    return client.get(f"/api/v1/nondoable/cases/{cid}")


def _user_id(email):
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == email)).first()


def test_frt_partial_forms_fe_completes_and_forwards(client, frt_org, mail):  # noqa: F811
    tid, g, cid = _frt_case(client, frt_org)
    d = _case(client, cid, FRT).json()
    assert d["case"]["status"] == "FRT_PROPOSED" and d["case"]["pendingWith"] == "FRT" and d["case"]["mine"] is True
    assert d["can"]["verify"] and d["can"]["justify"] and d["can"]["formMode"] == "optional" and "FRT_SUBMIT" in d["can"]["actions"]
    assert d["frtCase"] is True and d["forms"]["complete"] is False
    hf = _h(client, FRT)
    assert _form(client, hf, cid, "verification", {}).status_code == 422  # nothing at all
    # partial E1 by the FRT: accepted (optional), the case stays with the FRT
    r = _form(client, hf, cid, "verification", {"reason": "Pole line destroyed by landslide"})
    assert r.status_code == 200, r.text
    assert r.json()["case"]["status"] == "FRT_PROPOSED"
    # nobody else acts while it is with the FRT
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "verification", E1, evidence=[("s.pdf", PDF, "application/pdf")]).status_code == 409
    assert _act(client, h1, cid, "FE_FORWARD", remark="Checked").status_code == 409
    assert _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="Skipping", to=[{"name": "S", "email": "s@pratap-test.in"}]).status_code == 409

    # the FRT submits to the FE (E1 partial, no E2) – then can no longer change the forms
    hf = _h(client, FRT)
    r = _act(client, hf, cid, "FRT_SUBMIT", remark="E2 left for the FE")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["status"] == "PENDING_FE"
    assert _form(client, hf, cid, "justification", E2).status_code == 409
    assert _act(client, hf, cid, "FE_FORWARD", remark="FRT trying").status_code == 403

    # the FE: notified, forwarding blocked while E1 / E2 are incomplete (clear message)
    h1 = _h(client, FE1)
    assert any(n["kind"] == "NONDOABLE" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    d = client.get(f"/api/v1/nondoable/cases/{cid}").json()
    assert d["case"]["pendingWith"] == "FE" and d["can"]["formMode"] == "required" and "FE_FORWARD" in d["can"]["actions"] and "FE_RETURN_FRT" in d["can"]["actions"]
    assert set(d["forms"]["e1"]["missing"]) >= {"visit date", "visitor name", "findings", "evidence / site photographs"} and d["forms"]["e1"]["by"] == "FRT"
    assert d["forms"]["e2"]["filled"] is False
    r = _act(client, h1, cid, "FE_FORWARD", remark="Checked on site")
    assert r.status_code == 422 and "E1" in r.json()["detail"] and "E2" in r.json()["detail"]
    # the FE's Daily Achievement waits for the review (Non-Doable forms lock)
    assert any(x["caseId"] == cid for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["ndPending"])
    # the FE completes E1 (mandatory fields) and E2 – the case stays with the FE until the forward
    assert _form(client, h1, cid, "verification", {**E1, "findings": ""}, evidence=[("s.pdf", PDF, "application/pdf")]).status_code == 422
    r = _form(client, h1, cid, "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")], photos=[("site.png", PNG, "image/png")])
    assert r.status_code == 200 and r.json()["case"]["status"] == "PENDING_FE"
    assert r.json()["case"]["physical"] == "SUBMITTED" and r.json()["case"]["evidence"] == "SUBMITTED"  # E1 complete with its first photos
    r = _form(client, h1, cid, "justification", E2)
    assert r.status_code == 200 and r.json()["case"]["status"] == "PENDING_FE"
    d = client.get(f"/api/v1/nondoable/cases/{cid}").json()
    assert d["forms"]["complete"] is True and d["forms"]["e1"]["by"] == "FE" and d["forms"]["e1"]["frtFilled"] is True
    assert _act(client, h1, cid, "FE_FORWARD", remark="").status_code == 422  # the verification remark is required
    r = _act(client, h1, cid, "FE_FORWARD", remark="FRT findings verified on site")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["status"] == "PENDING_AM"

    # the AM has it now, with the FRT's and the FE's forms side by side and the full history
    d = _case(client, cid, VIEWER).json()
    assert "AM_FORWARD" in d["can"]["actions"] and "AM_RETURN" in d["can"]["actions"]
    assert [(r["kind"], r["role"]) for r in d["records"]] == [("VERIFICATION", "FRT"), ("VERIFICATION", "FE"), ("JUSTIFICATION", "FE")]
    assert next(r for r in d["records"] if r["role"] == "FRT")["reason"] == "Pole line destroyed by landslide"  # the FRT's form unchanged
    with SessionLocal() as db:
        evs = [(e.action, e.role, e.actor_id) for e in db.scalars(select(NdEvent).where(NdEvent.case_id == cid).order_by(NdEvent.id))]
        am_note = db.scalars(select(TicketNotification).where(TicketNotification.user_id == _user_id(VIEWER[0]), TicketNotification.kind == "NONDOABLE", TicketNotification.ticket_id == tid)).all()
    frt_id, fe_id = _user_id(FRT[0]), _user_id(FE1[0])
    assert evs == [
        ("PROPOSED_FRT", "FRT", frt_id), ("VERIFICATION", "FRT", frt_id), ("FRT_SUBMIT", "FRT", frt_id),
        ("VERIFICATION", "FE", fe_id), ("JUSTIFICATION", "FE", fe_id), ("FE_FORWARD", "FE", fe_id),
    ]
    assert am_note  # the Area Manager was notified only by the FE's forward (nothing earlier reached the AM)
    assert len(am_note) == 1


def test_frt_complete_forms_fe_only_verifies(client, frt_org, mail):  # noqa: F811
    _tid, _g, cid = _frt_case(client, frt_org)
    hf = _h(client, FRT)
    assert _form(client, hf, cid, "verification", {**E1, "visitorName": "Frt One"}, photos=[("site.png", PNG, "image/png")]).status_code == 200
    assert _form(client, hf, cid, "justification", E2).status_code == 200
    assert _case(client, cid, FRT).json()["forms"]["complete"] is True
    assert _act(client, _h(client, FRT), cid, "FRT_SUBMIT").status_code == 200  # remark optional
    h1 = _h(client, FE1)
    r = _act(client, h1, cid, "FE_FORWARD", remark="FRT's E1 / E2 checked – correct")
    assert r.status_code == 200, r.text
    assert r.json()["case"]["status"] == "PENDING_AM"
    with SessionLocal() as db:
        assert {x.role for x in db.scalars(select(NdRecord).where(NdRecord.case_id == cid))} == {"FRT"}  # the FE only verified


def test_frt_submits_without_forms_return_withdraw_and_permissions(client, frt_org, mail):  # noqa: F811
    tid, g, cid = _frt_case(client, frt_org)
    hf = _h(client, FRT)
    assert _act(client, hf, cid, "FRT_SUBMIT").status_code == 200  # no E1 / E2 at all – allowed for the FRT
    assert _act(client, hf, cid, "FRT_SUBMIT").status_code == 409  # no double submission
    # the Area Manager / another FE cannot do the FE's review
    assert _act(client, _h(client, VIEWER), cid, "FE_FORWARD", remark="AM trying").status_code == 403
    assert _case(client, cid, FE2).status_code == 404
    h1 = _h(client, FE1)
    r = _act(client, h1, cid, "FE_FORWARD", remark="Forward")
    assert r.status_code == 422 and "E1 form not filled" in r.json()["detail"] and "E2 form not filled" in r.json()["detail"]
    # the FE returns it to the FRT (reason required) – the FRT can fill and submit again
    assert _act(client, h1, cid, "FE_RETURN_FRT").status_code == 422
    r = _act(client, h1, cid, "FE_RETURN_FRT", reason="Add the site photographs")
    assert r.status_code == 200 and r.json()["case"]["status"] == "FRT_PROPOSED"
    hf = _h(client, FRT)
    assert _form(client, hf, cid, "verification", {"findings": "Landslide area"}, photos=[("site.png", PNG, "image/png")]).status_code == 200
    # the FRT withdraws its proposal: the GP is no longer Non-Doable – Proposed
    r = _act(client, hf, cid, "FRT_WITHDRAW", remark="Road reopened")
    assert r.status_code == 200 and r.json()["case"]["status"] == "WITHDRAWN"
    row = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["id"] == g)
    assert row["gpCategory"] is None and row["ndCase"]["open"] is False


def test_frt_waits_for_the_fe_revisit_after_mgg_rejection(client, frt_org, mail):  # noqa: F811
    """MGG rejects the FRT's Non-Doable: the GP is Revisit Required; the FRT sends no new status (A / C / D) until the FE
    has recorded the FRT coordination AND the new FRT site visit – then the FRT reports again (to the FE as usual)."""
    ha = _h(client)
    for email, pw in (SME, COH, MGG):
        assert client.post("/api/v1/users", json={"email": email, "name": email.split("@")[0].replace(".", " ").title(), "password": pw}, headers=ha).status_code in (201, 409)
    tid, g, cid = _frt_case(client, frt_org)
    assert _act(client, _h(client, FRT), cid, "FRT_SUBMIT").status_code == 200
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")], photos=[("site.png", PNG, "image/png")]).status_code == 200
    assert _form(client, h1, cid, "justification", E2).status_code == 200
    assert _act(client, h1, cid, "FE_FORWARD", remark="Verified on site").status_code == 200
    assert _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="Verified with the FRT report", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 200
    assert _act(client, _h(client, SME), cid, "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}]).status_code == 200
    ha = _h(client)
    mid = _user_id(MGG[0])
    if not any(m["userId"] == mid for m in client.get("/api/v1/nondoable/mgg").json()["members"]):
        assert client.post("/api/v1/nondoable/mgg", json={"userId": mid}, headers=ha).status_code == 200
    assert _act(client, _h(client, COH), cid, "COH_FORWARD", remark="Forward to the Corporate Team").status_code == 200
    r = _act(client, _h(client, MGG), cid, "MGG_REJECT", reason="Alternate route is feasible")
    assert r.status_code == 200 and r.json()["case"]["revisit"] == "COORDINATION"

    def frt_sends(cat):
        return progress(client, tid, [{"taskGpId": g, "category": cat, "remark": "Checked again"}], _h(client, FRT))

    for cat in ("A", "D"):  # before the FE's coordination: refused (C is the GP's status already – nothing new)
        r = frt_sends(cat)
        assert r.status_code == 422 and "new FRT site visit" in r.json()["detail"], r.text
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "revisit", {"frtTeam": "FRT team", "remarks": "Visit fixed"}, extra={"kind": "COORDINATION"}).json()["case"]["revisit"] == "FRT_VISIT"
    assert frt_sends("A").status_code == 422  # coordination only – the new visit is still missing
    h1 = _h(client, FE1)
    d = _form(client, h1, cid, "revisit", {"visitDate": TODAY, "visitorName": "FRT lead", "findings": "Route reopened", "outcome": "A"}, photos=[("frt.png", PNG, "image/png")], extra={"kind": "VISIT"})
    assert d.json()["case"]["revisit"] == "FRT_UPDATED"
    r = frt_sends("A")  # now the FRT reports – to its FE as usual
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g)
    assert row["gpCategory"] == "A" and row["frtStage"] == "PENDING_FE"
