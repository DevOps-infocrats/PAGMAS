"""AM → SME → COH workflow at GP level (SOP – Non-AMC GP Readiness & AMC Conversion, steps 6–7):

* an SME sees ONLY the GPs the Area Manager approved and forwarded to that SME – in the ticket detail, the proof
  documents, the workbook and the review API (direct requests with other GP ids are refused);
* the FE's original Rectification Done submission stays visible separately after the approval (A → B);
* the AM approval (name, remark, date, forwarded SME) and the SME review (remarks, confirmed category, reviewer,
  date, forwarded COH) are kept per GP, with the SOP status "SME Reviewed – Forwarded to COH";
* a GP cannot be forwarded twice; FE / AM / COH views keep working.
"""

import datetime as dt

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import TicketGpForward, TicketProgressFile, TicketTaskGp, User
from app.security.core import hash_password

from .conftest import VIEWER, login
from .test_ticket_fe import FE1, PDF, _fe, _gen, _sheet, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

SME1 = ("sme.one@pratap-test.in", "SmeOne!Secure-Pass-81")
SME2 = ("sme.two@pratap-test.in", "SmeTwo!Secure-Pass-82")
COH = ("coh.one@pratap-test.in", "CohOne!Secure-Pass-83")


def _accounts():
    with SessionLocal() as db:
        for email, pw in (SME1, SME2, COH):
            if db.scalars(select(User).where(User.email == email)).first() is None:
                db.add(User(email=email, name=email.split("@")[0], role="viewer", password_hash=hash_password(pw)))
        db.commit()


def _setup(client, fe_org):  # noqa: F811
    """One ticket with five GPs: GP-1 Rectification Done by FE One (remark + proof), GP-2 untouched, GP-3 Rectification
    Done (not approved), GP-4 Revisit Required, GP-5 Rectification Done. The AM forwards GP-1 to SME One, GP-5 to SME Two."""
    _accounts()
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0])])
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # GP-1: the FE's own submission (category A, remark, proof)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g1 = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    ok = client.post(
        f"/api/v1/tickets/{tid}/progress-form",
        data={"payload": '{"items": [{"taskGpId": %d, "category": "A", "remark": "Fibre cut rectified with FRT"}]}' % g1["id"], "proofGps": [str(g1["id"])]},
        files=[("proofs", ("after.pdf", PDF, "application/pdf"))],
        headers=h1,
    )
    assert ok.status_code == 200, ok.text

    # the Area Manager adds three GPs (safe test codes) and classifies the others
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.post(
        f"/api/v1/tickets/{tid}/progress",
        json={"newGps": [
            {"gpCode": "ZZSME3", "gpName": "Test GP Three", "category": "A", "remark": "GP-3 rectified"},
            {"gpCode": "ZZSME4", "gpName": "Test GP Four", "category": "C", "remark": "GP-4 revisit"},
            {"gpCode": "ZZSME5", "gpName": "Test GP Five", "category": "A", "remark": "GP-5 rectified"},
        ]},
        headers=hv,
    )
    assert d.status_code == 200, d.text
    gps = {g["gpCode"]: g for g in d.json()["task"]["gps"]}
    g2 = next(g for g in d.json()["task"]["gps"] if g["id"] != g1["id"] and g["kind"] != "ADDED")
    ids = {"g1": g1["id"], "g2": g2["id"], "g3": gps["ZZSME3"]["id"], "g4": gps["ZZSME4"]["id"], "g5": gps["ZZSME5"]["id"]}
    # a proof on GP-3 (not forwarded): an SME must not be able to download it
    pf = client.post(
        f"/api/v1/tickets/{tid}/progress-form",
        data={"payload": '{"items": []}', "proofGps": [str(ids["g3"])]},
        files=[("proofs", ("gp3.pdf", PDF, "application/pdf"))],
        headers=hv,
    )
    assert pf.status_code == 200, pf.text

    def approve(gid, who):
        return client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [gid], "action": "AM_APPROVE", "remark": f"Verified evidence for {who[0]}", "to": [{"name": who[0].split("@")[0], "email": who[0]}]}, headers=hv)

    # an untouched GP (GP-2) has nothing for the AM to review: it cannot be returned
    r = client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [ids["g2"]], "action": "AM_RETURN", "remark": "Not submitted yet"}, headers=hv)
    assert r.status_code == 422 and "Rectification Done or Revisit Required" in r.json()["detail"]
    a = approve(ids["g1"], SME1)
    assert a.status_code == 200, a.text
    assert approve(ids["g5"], SME2).status_code == 200
    return tid, ids


def _review(client, h, tid, gids, **b):
    return client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": gids, **b}, headers=h)


def test_sme_sees_only_the_gps_forwarded_to_them(client, fe_org, mail):  # noqa: F811
    tid, ids = _setup(client, fe_org)

    # SME One: only GP-1
    h_s1 = {"X-CSRF-Token": login(client, SME1)}
    det = client.get(f"/api/v1/tickets/{tid}").json()
    task = det["task"]
    assert [g["id"] for g in task["gps"]] == [ids["g1"]]
    assert task["scope"]["kind"] == "SME" and task["fes"] == [] and det["myRole"] == "SME" and det["can"]["reviewAs"] == ["SME"]
    assert task["totals"]["gps"] == 1 and task["totals"]["review"]["amApproved"] == 1 and task["totals"]["review"]["awaiting"] == 0
    # nothing about the other GPs leaks through the daily history, the activity log or the recipients
    assert all(ln["taskGpId"] == ids["g1"] for s in task["history"] for ln in s["lines"])
    assert not any(e["action"] in ("PROGRESS", "REVIEW") for e in det["events"])
    assert not any(r["email"] == SME2[0] for r in det["recipients"])

    # SME Two: only GP-5
    login(client, SME2)
    assert [g["id"] for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]] == [ids["g5"]]

    # direct API requests with other GP ids are refused (pending, not approved, revisit, another SME's)
    h_s1 = {"X-CSRF-Token": login(client, SME1)}
    for k in ("g2", "g3", "g4", "g5"):
        r = _review(client, h_s1, tid, [ids[k]], action="SME_FORWARD", remark="Trying another GP", category="B", to=[{"name": "COH", "email": COH[0]}])
        assert r.status_code == 422, (k, r.text)
    # proof documents: own GP yes, GP-3 no
    with SessionLocal() as db:
        files = {f.task_gp_id: f.id for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == tid))}
    assert client.get(f"/api/v1/tickets/progress-files/{files[ids['g1']]}").status_code == 200
    assert client.get(f"/api/v1/tickets/progress-files/{files[ids['g3']]}").status_code == 404
    # workbooks: only GP-1
    for kind in ("assignment", "progress"):
        x = client.get(f"/api/v1/tickets/{tid}/task/{kind}.xlsx")
        assert x.status_code == 200
        codes = {str(r[7]) for r in _sheet(x.content)[5:] if r[7] and r[8] != "Total" and str(r[7]) != "GP Code"}
        g1_code = task["gps"][0]["gpCode"]
        assert codes == {g1_code}, (kind, codes)

    # the Area Manager still sees all five, with the SOP stages
    login(client, VIEWER)
    am = {g["id"]: g for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]}
    assert set(ids.values()) <= set(am)
    assert am[ids["g3"]]["stage"] == "PENDING_AM" and am[ids["g3"]]["reviewLabel"] == "Pending AM Verification"
    assert am[ids["g4"]]["stage"] == "NONE" and am[ids["g2"]]["stage"] == "NONE"
    assert am[ids["g1"]]["reviewLabel"] == "Ready for Letter Submission – AM Approved"
    # FE One still sees only their own GPs
    login(client, FE1)
    fe_view = client.get(f"/api/v1/tickets/{tid}").json()["task"]
    assert fe_view["scope"]["kind"] == "FE" and ids["g1"] in {g["id"] for g in fe_view["gps"]} and ids["g5"] not in {g["id"] for g in fe_view["gps"]}

    # GP-level forward records
    with SessionLocal() as db:
        fw = {(f.task_gp_id, f.action, f.role) for f in db.scalars(select(TicketGpForward).where(TicketGpForward.ticket_id == tid))}
    assert fw == {(ids["g1"], "AM_APPROVE", "SME"), (ids["g5"], "AM_APPROVE", "SME")}


def test_fe_submission_and_am_approval_are_kept_separately(client, fe_org, mail):  # noqa: F811
    tid, ids = _setup(client, fe_org)
    login(client, SME1)
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    assert g["gpCategory"] == "B"  # current category after the AM approval
    fe = g["feSubmission"]
    assert fe["category"] == "A" and fe["remark"] == "Fibre cut rectified with FRT" and fe["submittedByRole"] == "FE" and fe["feName"] == "Test FE One"
    assert fe["submittedAt"] and [f["fileName"] for f in fe["files"]] == ["after.pdf"]
    am = g["amApproval"]
    assert am["by"].lower() == VIEWER[0].split("@")[0] and am["role"] == "AM" and am["remark"] == f"Verified evidence for {SME1[0]}" and am["at"]
    assert am["category"] == "B" and am["forwardedTo"] == [{"name": SME1[0].split("@")[0], "email": SME1[0]}] and am["forwardedAt"]
    assert g["smeReview"] is None and g["stage"] == "AM_APPROVED"
    step = g["trail"][-1]
    assert step["action"] == "AM_APPROVE" and step["fromStatus"] == "Pending AM Verification" and step["toStatus"] == "Ready for Letter Submission – AM Approved"
    # the remark of the GP row is still the FE's (never overwritten by the review)
    assert g["remarks"] == "Fibre cut rectified with FRT"


def test_sme_review_forwards_to_coh_with_sop_status(client, fe_org, mail):  # noqa: F811
    tid, ids = _setup(client, fe_org)
    h = {"X-CSRF-Token": login(client, SME1)}
    to = [{"name": "COH One", "email": COH[0]}]
    assert _review(client, h, tid, [ids["g1"]], action="SME_FORWARD", remark="ok", category="B", to=to).status_code == 422  # remark too short
    assert _review(client, h, tid, [ids["g1"]], action="SME_FORWARD", remark="Reviewed AM remarks", to=to).status_code == 422  # no confirmed category
    assert _review(client, h, tid, [ids["g1"]], action="SME_FORWARD", remark="Reviewed AM remarks", category="D", to=to).status_code == 422  # Non-Doable: own workflow
    mail.sent.clear()
    r = _review(client, h, tid, [ids["g1"]], action="SME_FORWARD", remark="Reviewed AM remarks and evidence", category="B", to=to)
    assert r.status_code == 200, r.text
    g = r.json()["task"]["gps"][0]
    assert g["review"] == "SME_FORWARDED" and g["stage"] == "SME_FORWARDED" and g["reviewLabel"] == "SME Reviewed – Forwarded to COH"
    s = g["smeReview"]
    assert s["by"] == SME1[0].split("@")[0] and s["role"] == "SME" and s["remark"] == "Reviewed AM remarks and evidence" and s["category"] == "B" and s["at"]
    assert s["forwardedTo"] == [{"name": "COH One", "email": COH[0]}]
    assert g["trail"][-1]["fromStatus"] == "Ready for Letter Submission – AM Approved" and g["trail"][-1]["toStatus"] == "SME Reviewed – Forwarded to COH"
    assert g["feSubmission"]["category"] == "A" and g["amApproval"]["remark"]  # earlier records unchanged
    assert [m["To"] for m in mail.sent] == [COH[0]]
    # the same GP cannot be forwarded twice
    assert _review(client, h, tid, [ids["g1"]], action="SME_FORWARD", remark="Again please", category="B", to=to).status_code == 409

    # the COH: notified, sees the ticket and records the letter
    hc = {"X-CSRF-Token": login(client, COH)}
    assert any(n["kind"] == "REVIEW" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    det = client.get(f"/api/v1/tickets/{tid}").json()
    assert det["myRole"] == "COH" and det["can"]["reviewAs"] == ["COH"]
    # the COH sees ONLY the GPs the SME reviewed and forwarded to them (not GP-5 approved for SME Two, nor the others)
    assert det["task"]["scope"]["kind"] == "COH" and [g["id"] for g in det["task"]["gps"]] == [ids["g1"]]
    assert not any(e["action"] in ("PROGRESS", "REVIEW") for e in det["events"])
    today = dt.date.today().isoformat()
    for k in ("g2", "g3", "g5"):  # direct requests for other GPs are refused
        assert _review(client, hc, tid, [ids[k]], action="COH_LETTER", date=today).status_code == 422, k
    d = _review(client, hc, tid, [ids["g1"]], action="COH_LETTER", date=today)
    assert d.status_code == 200, d.text
    assert next(x for x in d.json()["task"]["gps"] if x["id"] == ids["g1"])["review"] == "LETTER_SUBMITTED"
    # SME Two was not notified about GP-1
    login(client, SME2)
    notes = [n for n in client.get("/api/v1/tickets/notifications").json()["items"] if n["ticketId"] == tid]
    assert all("forwarded by the SME" not in n["title"] for n in notes)


def test_am_approval_needs_no_photographs(client, fe_org, mail):  # noqa: F811
    """No minimum number of photos for the Area Manager's approval (the remark and the SME remain required)."""
    tid, ids = _setup(client, fe_org)
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    # GP-5 had no proof at all and was approved in the setup; GP-3 (only a PDF) is approved the same way
    body = {"taskGpIds": [ids["g3"]], "action": "AM_APPROVE", "remark": "Verified", "to": [{"name": "sme", "email": SME1[0]}]}
    d = client.post(f"/api/v1/tickets/{tid}/review", json=body, headers=hv)
    assert d.status_code == 200, d.text
    assert next(g for g in d.json()["task"]["gps"] if g["id"] == ids["g3"])["review"] == "AM_APPROVED"
    assert "evidence" not in d.json()["task"]["gps"][0]


def test_am_returns_revisit_required_gp_to_fe_for_recheck(client, fe_org, mail):  # noqa: F811
    """Revisit Required (GP-4): the AM can send it back to the FE to recheck (never approve it); after the FE's next
    update it comes back to the AM. Non-Doable (own case) and untouched GPs cannot be returned."""
    tid, ids = _setup(client, fe_org)
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    rev = lambda gid, action, **b: client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [gid], "action": action, **b}, headers=hv)  # noqa: E731
    g4 = ids["g4"]
    assert rev(g4, "AM_APPROVE", remark="Looks fine", to=[{"name": "sme", "email": SME1[0]}]).status_code == 422  # approve = Rectification Done only
    d = rev(g4, "AM_RETURN", remark="Recheck the fibre route with the FRT team")
    assert d.status_code == 200, d.text
    row = next(g for g in d.json()["task"]["gps"] if g["id"] == g4)
    assert row["review"] == "RETURNED" and row["stage"] == "RETURNED" and row["gpCategory"] == "C"
    step = row["trail"][-1]
    assert step["action"] == "AM_RETURN" and step["remark"] == "Recheck the fibre route with the FRT team" and step["toStatus"] == "Returned to FE"
    assert rev(g4, "AM_RETURN", remark="Again").status_code == 409  # already returned
    # the FE / AM updates the GP again (still Revisit Required, new remark) -> back with the Area Manager
    d = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g4, "category": "C", "remark": "FRT revisit planned for Monday"}]}, headers=hv)
    assert d.status_code == 200, d.text
    assert next(g for g in d.json()["task"]["gps"] if g["id"] == g4)["review"] is None
    # Non-Doable: its own case workflow, not returned here
    d = client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": ids["g2"], "category": "D", "remark": "Site not reachable"}]}, headers=hv)
    assert d.status_code == 200, d.text
    assert rev(ids["g2"], "AM_RETURN", remark="Recheck please").status_code == 409


def test_sme_sends_back_to_am_and_coh_sends_back_to_sme(client, fe_org, mail):  # noqa: F811
    """SME → Back to AM (issue found): the AM verifies again (approve again or return to the FE); COH → Back to SME:
    the SME forwards again or sends it back to the AM. A reason is required; the KPIs and the history follow."""
    tid, ids = _setup(client, fe_org)
    g1 = ids["g1"]
    to_coh = [{"name": "COH One", "email": COH[0]}]

    def rev(creds, action, **b):
        return client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g1], "action": action, **b}, headers={"X-CSRF-Token": login(client, creds)})

    def row(creds):
        login(client, creds)
        task = client.get(f"/api/v1/tickets/{tid}").json()["task"]
        return task, next((g for g in task["gps"] if g["id"] == g1), None)

    # SME KPIs: the ticket's GP count against the GPs handed to them
    task, _ = row(SME1)
    k = task["scope"]["kpis"]
    assert k["ticketGps"] >= 5 and k["assigned"] == 1 and k["pending"] == 1 and k["forwarded"] == 0 and k["sentBack"] == 0
    # the SME sends GP-1 back to the AM (reason required)
    assert rev(SME1, "SME_RETURN", remark="").status_code == 422
    d = rev(SME1, "SME_RETURN", remark="AM remark does not match the photos")
    assert d.status_code == 200, d.text
    g = next(x for x in d.json()["task"]["gps"] if x["id"] == g1)
    assert g["review"] == "SME_RETURNED" and g["reviewLabel"] == "Returned to AM by SME" and g["gpCategory"] == "A" and g["locked"]
    assert g["sentBack"]["action"] == "SME_RETURN" and g["sentBack"]["remark"] == "AM remark does not match the photos"
    assert g["trail"][-1]["fromStatus"] == "Ready for Letter Submission – AM Approved" and g["trail"][-1]["toStatus"] == "Returned to AM by SME"
    assert d.json()["task"]["scope"]["kpis"]["sentBack"] == 1  # still shown to the SME (read-only)
    assert rev(SME1, "SME_FORWARD", remark="Changed my mind", category="B", to=to_coh).status_code == 409  # with the AM now
    # the AM is notified, sees it to verify again; the FE cannot change it meanwhile
    login(client, VIEWER)
    assert any("sent back to the Area Manager by the SME" in n["title"] for n in client.get("/api/v1/tickets/notifications").json()["items"])
    # the AM approves it again – this time for SME Two: SME One no longer sees it
    d = rev(VIEWER, "AM_APPROVE", remark="Photos re-checked with the FE", to=[{"name": "sme two", "email": SME2[0]}])
    assert d.status_code == 200, d.text
    assert row(SME1)[1] is None
    _, g = row(SME2)
    assert g is not None and g["review"] == "AM_APPROVED" and g["gpCategory"] == "B" and g["sentBack"] is None and g["amApproval"]["remark"] == "Photos re-checked with the FE"
    # SME Two forwards to the COH; the COH sends it back to the SME
    assert rev(SME2, "SME_FORWARD", remark="Reviewed again", category="B", to=to_coh).status_code == 200
    task, _ = row(COH)
    assert task["scope"]["kpis"]["assigned"] == 1 and task["scope"]["kpis"]["pending"] == 1
    d = rev(COH, "COH_RETURN", remark="Letter details missing for this GP")
    assert d.status_code == 200, d.text
    g = next(x for x in d.json()["task"]["gps"] if x["id"] == g1)
    assert g["review"] == "COH_RETURNED" and g["reviewLabel"] == "Returned to SME by COH" and g["gpCategory"] == "B"
    assert d.json()["task"]["scope"]["kpis"]["sentBack"] == 1
    assert rev(COH, "COH_LETTER", date=dt.date.today().isoformat()).status_code == 409  # back with the SME
    # SME Two is notified and can forward again (or send it back to the AM)
    task, g = row(SME2)
    assert task["scope"]["kpis"]["returnedToYou"] == 1 and task["scope"]["kpis"]["pending"] == 2  # GP-1 (back from the COH) + GP-5
    assert any("sent back to the SME by the COH" in n["title"] for n in client.get("/api/v1/tickets/notifications").json()["items"])
    assert rev(SME2, "SME_FORWARD", remark="Letter details added", category="B", to=to_coh).status_code == 200
    assert rev(COH, "COH_LETTER", date=dt.date.today().isoformat()).status_code == 200
    _, g = row(VIEWER)
    assert [x["action"] for x in g["trail"] if x["action"] != "EDIT"] == ["AM_APPROVE", "SME_RETURN", "AM_APPROVE", "SME_FORWARD", "COH_RETURN", "SME_FORWARD", "COH_LETTER"]


def test_ticket_closes_only_after_am_review_or_with_a_reason(client, fe_org, mail):  # noqa: F811
    """SOP rule 4: GPs not approved by the Area Manager block the closure; the admin may close with a written reason."""
    tid, _ids = _setup(client, fe_org)
    ha = {"X-CSRF-Token": login(client)}
    r = client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "done"}, headers=ha)
    assert r.status_code == 409 and "not yet reviewed and approved by the Area Manager" in r.json()["detail"] and "1 Pending AM Verification" in r.json()["detail"]
    assert client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "short", "force": True}, headers=ha).status_code == 422
    d = client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "Week ended – rest carried to next week", "force": True}, headers=ha)
    assert d.status_code == 200 and d.json()["status"] == "CLOSED"
    note = next(e["note"] for e in d.json()["events"] if e["action"] == "CLOSED")
    assert note.startswith("Closed without AM approval of") and "rest carried to next week" in note


def test_approvals_made_before_gp_level_forwarding_stay_visible(client, fe_org, mail):  # noqa: F811
    """GPs approved before forward records existed (no row) stay visible to the ticket's SMEs, as before."""
    tid, ids = _setup(client, fe_org)
    with SessionLocal() as db:
        db.execute(delete(TicketGpForward).where(TicketGpForward.task_gp_id == ids["g5"]))
        db.commit()
    login(client, SME1)
    seen = {g["id"] for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]}
    assert seen == {ids["g1"], ids["g5"]}
    with SessionLocal() as db:
        assert db.get(TicketTaskGp, ids["g3"]).review is None  # never approved = never shown to an SME
        # a GP moved to the Non-Doable workflow after its approval has its review reset: no longer in the SME's list
        db.get(TicketTaskGp, ids["g5"]).review = None
        db.commit()
    assert {g["id"] for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]} == {ids["g1"]}
