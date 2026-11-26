"""GP Timeline (app.tickets.timeline, GET /tickets/{id}/gps/{gp}/timeline): one GP's history, oldest first.

* generated → FRT filled → FE returned (with the reason) → FRT filled again → FE verified; proof on the fills;
* where it waits now; the same access as the GP detail: the FE of the GP yes, another FE no.
"""

from .conftest import login
from .evidence import progress
from .test_ticket_fe import FE1, FE2, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import FRT, _check, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def test_gp_timeline_shows_who_did_what_when(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    g = next(x for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"])
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Splicing done"}], hf).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g["id"]], "FE_RETURN", "Photo not clear", h1).status_code == 200
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Splicing done again"}], hf).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g["id"]], "FE_VERIFY", "Checked the photo", h1).status_code == 200

    login(client)
    r = client.get(f"/api/v1/tickets/{tid}/gps/{g['id']}/timeline")
    assert r.status_code == 200, r.text
    tl = r.json()
    kinds = [e["kind"] for e in tl["events"]]
    assert kinds == ["generated", "filled", "return", "filled", "review"]
    ev = tl["events"]
    assert ev[1]["role"] == "FRT" and ev[1]["remark"] == "Splicing done" and ev[1]["files"]  # the FRT's photo
    assert ev[2]["role"] == "FE" and ev[2]["remark"] == "Photo not clear" and "Returned" in ev[2]["label"]
    assert ev[3]["remark"] == "Splicing done again"
    assert ev[4]["role"] == "FE" and "Verified" in ev[4]["label"] and ev[4]["remark"] == "Checked the photo"
    assert [e["at"] for e in ev] == sorted(e["at"] for e in ev)  # oldest first
    assert tl["now"]["label"] and not tl["now"]["done"]

    # the same access as the GP detail: its FE yes, another FE no; a GP of another ticket: not found
    login(client, FE1)
    assert client.get(f"/api/v1/tickets/{tid}/gps/{g['id']}/timeline").status_code == 200
    login(client, FE2)
    assert client.get(f"/api/v1/tickets/{tid}/gps/{g['id']}/timeline").status_code == 404
    login(client)
    other = _ticket(client, frt_org)
    assert client.get(f"/api/v1/tickets/{other}/gps/{g['id']}/timeline").status_code == 404


def test_gp_timeline_from_the_gp_monitor_and_the_ticket_report(client, frt_org, mail):  # noqa: F811
    """The GP Monitor names each ticket row's GP (its timeline); a Ticket Report role (not on the ticket) may open the
    timeline of a report GP; a user without that page may not."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User
    from app.security.core import hash_password

    tid = _ticket(client, frt_org)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    g = d["task"]["gps"][0]
    h = {"X-CSRF-Token": login(client)}
    det = client.get(f"/api/v1/tickets/gp-monitor/gps/{g['gpCode']}").json()
    assert any(r["ticketId"] == tid and r["gpId"] == g["id"] for r in det["ticketRows"])

    who = ("report-reader@pratap-test.in", "R3port!Secure-Pass")
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.email == who[0])).first() is None:
            db.add(User(email=who[0], name="Report Reader", role="viewer", password_hash=hash_password(who[1])))
            db.commit()
        uid = db.scalars(select(User.id).where(User.email == who[0])).one()
    url = f"/api/v1/tickets/{tid}/gps/{g['id']}/timeline"
    r = client.post("/api/v1/roles", json={"name": "Test Report Reader", "pages": {"tickets-report": {"laptop": True, "phone": False}}}, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    try:
        login(client, who)
        assert client.get(url).status_code == 404  # no role page yet: like any outsider
        h = {"X-CSRF-Token": login(client)}
        assert client.patch(f"/api/v1/users/{uid}", json={"roleId": rid}, headers=h).status_code == 200
        login(client, who)
        assert client.get(url).status_code == 200 and client.get(url).json()["events"][0]["kind"] == "generated"
    finally:
        h = {"X-CSRF-Token": login(client)}
        client.post(f"/api/v1/users/{uid}/delete", headers=h)
        client.delete(f"/api/v1/roles/{rid}", headers=h)
