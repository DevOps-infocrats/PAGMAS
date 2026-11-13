"""Area Manager -> CBH / SME: only the AM of a GP-wise task, only the CBH / SME of the ticket's circle (Escalation
Matrix), a remark is required; each gets the latest GP sheet + remark by e-mail (fake SMTP – nothing is really sent),
people with an account get the ticket read-only; recorded in the history."""

import io

from python_calamine import CalamineWorkbook

from .conftest import ADMIN, VIEWER, login
from .test_ticket_recipients import AM, CBH, CBH_MAIL, SME, SME_R, _gen, mail, org  # noqa: F401 - shared fixtures
from .test_ticket_tasks import am_week  # noqa: F401


def test_area_manager_shares_with_cbh_and_sme(client, org, mail):  # noqa: F811
    h = {"X-CSRF-Token": login(client, ADMIN)}
    r = _gen(client, h, org, [AM(org)], task=True)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.get(f"/api/v1/tickets/{tid}/share-contacts").status_code == 403  # the admin is not the AM

    ha = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["share"] is True
    c = client.get(f"/api/v1/tickets/{tid}/share-contacts").json()
    assert [p["name"] for p in c["cbh"]] == ["Test CBH"] and c["cbh"][0]["emails"][0] == {"email": CBH_MAIL, "account": False, "onTicket": False}
    assert c["sme"][0]["emails"][0]["account"] is True
    url = f"/api/v1/tickets/{tid}/share"
    # only matrix people, a remark is required
    assert client.post(url, json={"recipients": [{"role": "CBH", "name": "Made Up", "email": "x@example.com"}], "remark": "Please check"}, headers=ha).status_code == 422
    assert client.post(url, json={"recipients": [CBH], "remark": ""}, headers=ha).status_code == 422
    assert client.post(url, json={"recipients": [], "remark": "Please check"}, headers=ha).status_code == 422
    mail.sent.clear()
    ok = client.post(url, json={"recipients": [CBH, SME_R], "remark": "10 GPs ready for letter – please follow up"}, headers=ha)
    assert ok.status_code == 200, ok.text
    assert ok.json()["emailQueued"] == 2 and sorted(m["To"] for m in mail.sent) == sorted([CBH_MAIL, SME[0]])
    for m in mail.sent:
        html = m.get_body(("html",)).get_content()
        assert "10 GPs ready for letter – please follow up" in html and "shared the latest status" in html and m["Subject"].startswith(f"[{d['code']}] Shared by")
        att = [p for p in m.walk() if p.get_filename()]
        assert len(att) == 1 and att[0].get_filename().endswith(".xlsx")
        rows = CalamineWorkbook.from_filelike(io.BytesIO(att[0].get_payload(decode=True))).get_sheet_by_name("GP Task").to_python()
        assert sorted(str(x[7]) for x in rows[5:] if x[7]) == sorted(g["gpCode"] for g in d["task"]["gps"])
    d = ok.json()
    roles = {x["email"]: x for x in d["recipients"]}
    assert roles[CBH_MAIL]["role"] == "CBH" and roles[CBH_MAIL]["access"] == "email" and roles[SME[0]]["access"] == "dashboard" and not roles[SME[0]]["canWork"]
    ev = next(e for e in d["events"] if e["action"] == "SHARED")
    assert "CBH Test CBH" in ev["note"] and "please follow up" in ev["note"]
    # the SME sees it read-only and cannot share
    login(client, SME)
    mine = client.get("/api/v1/tickets", params={"scope": "mine"}).json()
    assert tid in [t["id"] for t in mine["items"]]
    ds = client.get(f"/api/v1/tickets/{tid}").json()
    assert ds["can"]["share"] is False and ds["can"]["progress"] is False
    assert client.post(url, json={"recipients": [CBH], "remark": "x" * 5}, headers={"X-CSRF-Token": client.cookies.get("pratap_csrf")}).status_code == 403
