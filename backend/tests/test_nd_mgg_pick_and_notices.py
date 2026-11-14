"""The COH forwards a Non-Doable case to the Corporate Team – MGG person it chooses or types (nd_mgg_picks), and the
review steps that hand the GPs to nobody chosen are e-mailed: Area Manager return → the GP's FE, COH letter / AMC →
the Area Manager."""

import datetime as dt

from sqlalchemy import select

from app.db import SessionLocal
from app.models import NdMggPick, User

from .conftest import VIEWER, login
from .test_nondoable import COH, E1, E2, MGG, PNG, SME, _act, _case_of, _form, _h, _propose, nd  # noqa: F401 - shared fixture
from .test_ticket_fe import FE1, FE2, PDF, fe_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _to_coh(client, cid):
    h1 = _h(client, FE1)
    assert _form(client, h1, cid, "verification", E1, evidence=[("survey.pdf", PDF, "application/pdf")], photos=[("site.png", PNG, "image/png")]).status_code == 200
    assert _form(client, h1, cid, "justification", E2).status_code == 200
    assert _act(client, _h(client, VIEWER), cid, "AM_FORWARD", remark="Verified with the FRT report", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 200
    r = _act(client, _h(client, SME), cid, "SME_RECOMMEND", remark="Recommend Non-Doable", to=[{"name": "Nd Coh", "email": COH[0]}])
    assert r.status_code == 200 and r.json()["case"]["status"] == "PENDING_COH"


def test_coh_types_the_mgg_when_none_is_authorised(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    assert _propose(client, tid, g["id"]).status_code == 200
    login(client, FE1)
    cid = _case_of(client, g["id"])["id"]
    _to_coh(client, cid)

    hc = _h(client, COH)
    # the MGG picker: only the COH of the case; no authorised account yet = empty list (the COH types the e-mail)
    r = client.get(f"/api/v1/nondoable/cases/{cid}/contacts", params={"role": "MGG"})
    assert r.status_code == 200 and r.json()["role"] == "MGG" and r.json()["people"] == []
    assert _act(client, hc, cid, "COH_FORWARD", remark="Forward to the Corporate Team").status_code == 422  # nobody authorised, nobody typed
    assert _act(client, hc, cid, "COH_FORWARD", remark="Forward", to=[{"email": "not-an-email"}]).status_code == 422
    assert _act(client, hc, cid, "COH_FORWARD", remark="Forward", to=[{"email": COH[0]}]).status_code == 422  # not to themselves
    login(client, SME)
    assert client.get(f"/api/v1/nondoable/cases/{cid}/contacts", params={"role": "MGG"}).status_code == 403  # only the COH chooses

    mail.sent.clear()
    hc = _h(client, COH)
    d = _act(client, hc, cid, "COH_FORWARD", remark="Forward to the Corporate Team", to=[{"name": "Nd Mgg", "email": MGG[0].upper()}])
    assert d.status_code == 200, d.text
    j = d.json()
    assert j["case"]["status"] == "PENDING_MGG" and j["mggPicked"] == [{"name": "Nd Mgg", "email": MGG[0], "account": True}]
    assert MGG[0] in {m["To"] for m in mail.sent}  # the typed MGG gets the e-mail
    assert "Sent to MGG Nd Mgg" in j["history"][-1]["remark"]

    # the typed MGG (an account, not authorised by the admin) sees and decides THIS case
    hm = _h(client, MGG)
    rows = client.get("/api/v1/nondoable/cases").json()["items"]
    assert [x["id"] for x in rows] == [cid] and rows[0]["mine"] and rows[0]["roles"] == ["MGG"]
    assert client.get("/api/v1/nondoable/summary").json()["kpis"]["MGG"]["pending"] == 1
    assert "MGG_APPROVE" in client.get(f"/api/v1/nondoable/cases/{cid}").json()["can"]["actions"]
    assert _act(client, _h(client, FE2), cid, "MGG_APPROVE").status_code == 404  # anybody else: no access
    d = _act(client, _h(client, MGG), cid, "MGG_APPROVE", remark="Approved")
    assert d.status_code == 200 and d.json()["case"]["status"] == "APPROVED"


def test_typed_mgg_without_an_account_decides_once_the_account_exists(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    assert _propose(client, tid, g["id"]).status_code == 200
    login(client, FE1)
    cid = _case_of(client, g["id"])["id"]
    _to_coh(client, cid)
    late = ("late.mgg@pratap-test.in", "LateMgg!Secure-Pass-91")
    with SessionLocal() as db:
        assert db.scalar(select(User.id).where(User.email == late[0])) is None
    mail.sent.clear()
    d = _act(client, _h(client, COH), cid, "COH_FORWARD", remark="Forward to the Corporate Team", to=[{"name": "Late Mgg", "email": late[0]}])
    assert d.status_code == 200, d.text
    assert d.json()["mggPicked"] == [{"name": "Late Mgg", "email": late[0], "account": False}]
    assert late[0] in {m["To"] for m in mail.sent}
    # the admin creates the account later: it decides the case (matched by its e-mail)
    h = _h(client)
    assert client.post("/api/v1/users", json={"email": late[0], "name": "Late Mgg", "password": late[1]}, headers=h).status_code in (201, 409)
    hl = _h(client, late)
    assert [x["id"] for x in client.get("/api/v1/nondoable/cases").json()["items"]] == [cid]
    r = _act(client, hl, cid, "MGG_REJECT", reason="Revisit with a new FRT team")
    assert r.status_code == 200 and r.json()["case"]["status"] == "REJECTED"
    with SessionLocal() as db:
        assert db.scalar(select(NdMggPick.email).where(NdMggPick.case_id == cid)) == late[0]


def test_return_to_fe_and_letter_amc_are_emailed(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    today = dt.date.today().isoformat()

    def rev(hh, **b):
        return client.post(f"/api/v1/tickets/{tid}/review", json={"taskGpIds": [g["id"]], **b}, headers=hh)

    h1 = _h(client, FE1)
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g["id"], "category": "A"}]}, headers=h1).status_code == 200
    mail.sent.clear()
    hv = _h(client, VIEWER)
    assert rev(hv, action="AM_RETURN", remark="Photo missing").status_code == 200
    fe_mail = [m for m in mail.sent if m["To"] == FE1[0]]
    assert len(fe_mail) == 1 and "returned for correction" in fe_mail[0]["Subject"]
    assert "Photo missing" in fe_mail[0].get_body(("plain",)).get_content()
    assert FE2[0] not in {m["To"] for m in mail.sent}  # only the FE of the returned GP

    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g["id"], "category": "A", "remark": "Photo added"}]}, headers=_h(client, FE1)).status_code == 200
    assert rev(_h(client, VIEWER), action="AM_APPROVE", remark="Verified", to=[{"name": "Nd Sme", "email": SME[0]}]).status_code == 200
    assert rev(_h(client, SME), action="SME_FORWARD", remark="Confirmed", category="B", to=[{"name": "Nd Coh", "email": COH[0]}]).status_code == 200
    hc = _h(client, COH)
    mail.sent.clear()
    assert rev(hc, action="COH_LETTER", date=today).status_code == 200
    assert [m["To"] for m in mail.sent] == [VIEWER[0]] and "Letter submission recorded" in mail.sent[0]["Subject"]
    mail.sent.clear()
    assert rev(_h(client, COH), action="COH_AMC", date=today).status_code == 200
    assert [m["To"] for m in mail.sent] == [VIEWER[0]] and "AMC conversion recorded" in mail.sent[0]["Subject"]
