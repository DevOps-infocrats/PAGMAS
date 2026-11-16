"""COH on User Tickets: Letter Submitted / AMC Converted KPIs and GP lists (only the GPs forwarded to them, with the
Area Manager, FE, Target Date = Planned Date and the letter / AMC date) and their Excel; the COH closes a ticket only
when every GP of it is finished."""

import datetime as dt
import io

from python_calamine import CalamineWorkbook
from sqlalchemy import select

from app.db import SessionLocal
from app.models import TicketTaskGp

from .conftest import VIEWER, login
from .evidence import review
from .test_ticket_fe import FE1, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_sme_scope import COH, SME1, SME2, _setup
from .test_ticket_tasks import am_week  # noqa: F401


def test_coh_kpis_lists_excel_and_closing(client, fe_org, mail):  # noqa: F811
    tid, ids = _setup(client, fe_org)
    to = [{"name": "COH One", "email": COH[0]}]
    hs = {"X-CSRF-Token": login(client, SME1)}
    assert review(client, tid, {"taskGpIds": [ids["g1"]], "action": "SME_FORWARD", "remark": "Reviewed and confirmed", "category": "B", "to": to}, hs).status_code == 200
    hs2 = {"X-CSRF-Token": login(client, SME2)}
    assert review(client, tid, {"taskGpIds": [ids["g5"]], "action": "SME_FORWARD", "remark": "Reviewed and confirmed", "category": "B", "to": to}, hs2).status_code == 200

    hc = {"X-CSRF-Token": login(client, COH)}
    k = client.get("/api/v1/tickets/coh-gps").json()
    assert k["isCoh"] is True and k["letterSubmitted"] == 0 and k["amcConverted"] == 0
    today = dt.date.today().isoformat()
    assert review(client, tid, {"taskGpIds": [ids["g1"], ids["g5"]], "action": "COH_LETTER", "date": today}, hc).status_code == 200
    assert review(client, tid, {"taskGpIds": [ids["g1"]], "action": "COH_AMC", "date": today}, hc).status_code == 200
    k = client.get("/api/v1/tickets/coh-gps").json()
    assert k["letterSubmitted"] == 2 and k["amcConverted"] == 1  # a converted GP stays in the letter list
    with SessionLocal() as db:
        g1 = db.get(TicketTaskGp, ids["g1"])
        planned = g1.planned_date
    row = next(r for r in k["letter"] if r["gpCode"] == g1.gp_code)
    assert row["areaManager"] == fe_org["am"] and row["fieldEngineer"] == "Test FE One" and row["letterDate"] == today
    assert row["targetDate"] == (planned.isoformat() if planned else row["targetDate"]) and row["targetFromWeek"] == (planned is None)
    assert [r["gpCode"] for r in k["amc"]] == [g1.gp_code] and k["amc"][0]["amcDate"] == today
    # Excel of each list: header + one row per GP
    for kind, n in (("letter", 2), ("amc", 1)):
        x = client.get("/api/v1/tickets/coh-gps.xlsx", params={"kind": kind})
        assert x.status_code == 200 and x.headers["content-type"].startswith("application/vnd.openxmlformats")
        rows = CalamineWorkbook.from_filelike(io.BytesIO(x.content)).get_sheet_by_index(0).to_python()
        assert rows[3][:4] == ["S.No.", "Ticket", "Week", "GP Code"] and len([r for r in rows[4:] if r[3]]) == n
    assert client.get("/api/v1/tickets/coh-gps.xlsx", params={"kind": "other"}).status_code == 422

    # closing: other GPs of the ticket are still with the FE / AM -> not yet
    d = client.get(f"/api/v1/tickets/{tid}").json()
    assert d["can"]["cohClose"] is False and "not finished yet" in d["can"]["cohCloseBlock"] and d["can"]["close"] is False
    r = client.post(f"/api/v1/tickets/{tid}/coh-close", json={}, headers=hc)
    assert r.status_code == 409 and "not finished yet" in r.json()["detail"]
    with SessionLocal() as db:  # every other GP finished (test data only)
        for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == tid)):
            if g.review not in ("LETTER_SUBMITTED", "AMC_CONVERTED"):
                g.review = "ND_APPROVED"
        db.commit()
    assert client.get(f"/api/v1/tickets/{tid}").json()["can"]["cohClose"] is True
    # nobody else closes here: SME / Area Manager / FE
    for creds in (SME1, VIEWER, FE1):
        assert client.post(f"/api/v1/tickets/{tid}/coh-close", json={}, headers={"X-CSRF-Token": login(client, creds)}).status_code == 403
    assert client.get("/api/v1/tickets/coh-gps").json()["isCoh"] is False  # FE: no COH ticket
    hc = {"X-CSRF-Token": login(client, COH)}
    r = client.post(f"/api/v1/tickets/{tid}/coh-close", json={"comment": "All letters and AMC done"}, headers=hc)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "CLOSED" and d["can"]["cohClose"] is False
    ev = next(e for e in d["events"] if e["action"] == "CLOSED")
    assert ev["actor"] == COH[0].split("@")[0] and "Closed by the COH" in ev["note"]
    assert client.post(f"/api/v1/tickets/{tid}/coh-close", json={}, headers=hc).status_code == 409  # already closed
    login(client, VIEWER)
    assert any(n["kind"] == "CLOSED" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
