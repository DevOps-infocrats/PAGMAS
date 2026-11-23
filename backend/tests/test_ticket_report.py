"""Ticket Report (app.tickets.report): tickets generated in a ticket week per role, daily submissions per person and
day, completed work – read only, admin only.

* the week's ticket counts per role match the recipients; the FRT's / FE's GPs are theirs only;
* a daily submission counts on its local day for the submitter's role (FRT > FE > AM on that ticket);
* review steps (FE verify, AM approve …) also write a progress row – they are NOT daily submissions;
* viewers get 403; the Excel workbook downloads.
"""

import datetime as dt

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import TicketTask
from app.tickets.monitor import _local_date

from .conftest import VIEWER, login
from .evidence import progress, review
from .test_ticket_fe import FE1, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import CODE, FRT, _check, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

WEEK = "W-90"  # the test ticket is moved to a week around today (test database only)


def _this_week(tid):
    today = _local_date(dt.datetime.now(dt.UTC))
    start = today - dt.timedelta(days=(today.weekday() - 5) % 7)  # Saturday – Friday
    with SessionLocal() as db:
        db.execute(update(TicketTask).where(TicketTask.ticket_id == tid).values(week_code=WEEK, week_start=start, week_end=start + dt.timedelta(days=6)))
        db.commit()
    return today.isoformat()


def test_report_counts_generated_tickets_and_daily_submissions(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    today = _this_week(tid)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    frt_ids = [x["id"] for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"]]
    g = frt_ids[0]

    # FRT reports (a daily submission); the FE verifies and the AM approves (review steps – not daily submissions)
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Splicing done by FRT"}], hf).status_code == 200
    # a Non-Doable proposed in the Daily Achievement is part of that submission – it counts too
    nd_gp = frt_ids[1] if len(frt_ids) > 1 else None
    if nd_gp is not None:
        assert progress(client, tid, [{"taskGpId": nd_gp, "category": "D", "remark": "Pole line destroyed"}], hf).status_code == 200
    frt_subs = 2 if nd_gp is not None else 1
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g], "FE_VERIFY", "Checked photo and remark", h1).status_code == 200
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert review(client, tid, {"taskGpIds": [g], "action": "AM_APPROVE", "remark": "Approved", "to": [{"name": "Rep Sme", "email": "report.sme@pratap-test.in"}]}, hv).status_code == 200

    # viewers cannot open the report
    assert client.get("/api/v1/tickets/report").status_code == 403
    assert client.get("/api/v1/tickets/report.xlsx").status_code == 403

    login(client)
    r = client.get("/api/v1/tickets/report", params={"week": WEEK})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["week"]["code"] == WEEK and len(rep["days"]) == 7 and any(x["date"] == today for x in rep["days"])
    assert rep["cards"]["tickets"] == 1 and rep["cards"]["gps"] == len(d["task"]["gps"])
    roles = {x["role"]: x for x in rep["roles"]}
    assert roles["AM"]["tickets"] == 1 and roles["FE"]["tickets"] == 1 and roles["FRT"]["tickets"] == 1
    assert roles["FRT"]["gps"] == len(frt_org["one"])  # only the GPs of the FRT code
    assert roles["FRT"]["submissions"] == frt_subs and roles["FRT"]["activePeople"] == 1
    assert roles["FE"]["submissions"] == 0 and roles["AM"]["submissions"] == 0  # FE verify / AM approve are review steps
    assert rep["cards"]["submissions"] == frt_subs and rep["cards"]["submittedToday"] == 1
    frt = next(p for p in rep["people"] if p["role"] == "FRT")
    assert frt["days"][today] == {"subs": frt_subs, "gps": frt_subs, "done": 0, "reviews": 0, "acts": {}} and frt["activeDays"] == 1 and frt["tickets"] == 1
    # FRT = one row per FRT code on the week's GPs, with its login (since when) and the FE it works under
    assert frt["frtCodes"] == [CODE] and frt["account"] is True and frt["loginSince"] and frt["fes"] == ["Test FE One"]
    assert roles["FRT"]["people"] == 1 and roles["FRT"]["withAccount"] == 1 and roles["FRT"]["withoutAccount"] == 0
    # status breakdown = the GP's CURRENT category: Rectification Done (A) became Ready for Letter Submission (B) with the
    # AM approval; a Non-Doable proposed in the Daily Achievement is D. Returns, last sign-in / daily submission.
    assert frt["status"]["B"] == 1 and frt["status"]["D"] == frt_subs - 1 and sum(frt["status"].values()) == frt["gps"]
    assert roles["FRT"]["status"]["B"] == 1 and roles["FRT"]["returns"] == frt["returns"] == 0
    assert frt["lastSubmission"] and frt["lastLogin"]
    # pending with: the approved GP waits with the SME (named on the ticket); a Non-Doable GP in its case with the FE
    items = {it["gpCode"]: it for it in rep["pending"]["items"]}
    gcode = next(x["gpCode"] for x in d["task"]["gps"] if x["id"] == g)
    assert items[gcode]["bucket"] == "sme" and items[gcode]["whoRole"] == "SME" and "Rep Sme" in items[gcode]["who"] and items[gcode]["days"] == 0
    if nd_gp is not None:
        ncode = next(x["gpCode"] for x in d["task"]["gps"] if x["id"] == nd_gp)
        assert items[ncode]["bucket"] == "nd" and items[ncode]["whoRole"] == "FE"
    counts = {b["key"]: b["count"] for b in rep["pending"]["buckets"]}
    assert sum(counts.values()) == rep["cards"]["gps"] and counts["sme"] == 1
    am = next(p for p in rep["people"] if p["role"] == "AM")
    assert am["lastSubmission"] is None  # the AM approval is a review step, not a Daily Achievement submission …
    # … but it IS the AM's daily work: a review on that day (and the FE's verification of the FRT's report likewise)
    assert am["submissions"] == 0 and am["days"][today]["reviews"] == 1 and am["days"][today]["acts"] == {"approved": 1} and am["activeDays"] == 1
    fe = next(p for p in rep["people"] if p["role"] == "FE" and p["name"] == "Test FE One")
    assert fe["days"][today]["acts"] == {"verified": 1} and fe["reviews"] == 1 and fe["lastActive"]
    assert roles["SME"]["reviewed"] == len(roles["SME"]["steps"]) == 0 and roles["COH"]["steps"] == []  # nothing forwarded yet
    assert roles["AM"]["reviews"] == 1 and roles["FE"]["reviews"] == 1 and rep["cards"]["submittedToday"] == 1  # Daily Achievement only
    assert WEEK in [w["code"] for w in rep["weeks"]] and rep["trend"][-1]["week"] in [w["code"] for w in rep["weeks"]]
    # a circle that is not the ticket's: nothing
    other = client.get("/api/v1/tickets/report", params={"week": WEEK, "circle": "No Such Circle"}).json()
    assert other["cards"]["tickets"] == 0 and other["cards"]["submissions"] == 0
    # the workbook and refused inputs
    x = client.get("/api/v1/tickets/report.xlsx", params={"week": WEEK})
    assert x.status_code == 200 and x.content[:2] == b"PK" and f"Ticket_Report_{WEEK}" in x.headers["content-disposition"]
    assert client.get("/api/v1/tickets/report", params={"week": "1; drop"}).status_code == 422
    with SessionLocal() as db:  # read only: the ticket week is unchanged by the report
        assert db.scalars(select(TicketTask.week_code).where(TicketTask.ticket_id == tid)).one() == WEEK


def test_report_lists_returns_with_reason_and_am_achievement(client, frt_org, mail):  # noqa: F811
    """A return shows who sent which GP back, to whom and why; the AM table adds up (achieved + waiting = GPs)."""
    tid = _ticket(client, frt_org)
    _this_week(tid)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    g = next(x["id"] for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"])
    gcode = next(x["gpCode"] for x in d["task"]["gps"] if x["id"] == g)
    assert progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Splicing done"}], {"X-CSRF-Token": login(client, FRT)}).status_code == 200
    assert _check(client, tid, [g], "FE_RETURN", "Photo is blurred", {"X-CSRF-Token": login(client, FE1)}).status_code == 200

    login(client)
    rep = client.get("/api/v1/tickets/report", params={"week": WEEK}).json()
    items = rep["returns"]["items"]
    assert len(items) == 1
    x = items[0]
    assert x["gpCode"] == gcode and x["byRole"] == "FE" and x["toRole"] == "FRT" and x["remark"] == "Photo is blurred" and x["ticketId"] == tid
    assert rep["returns"]["top"] == [{"role": "FRT", "name": x["to"], "count": 1}]
    frt = next(p for p in rep["people"] if p["role"] == "FRT")
    assert frt["returns"] == 1  # the same return as in the count
    am = rep["amAchievement"]
    assert len(am) == 1 and am[0]["gps"] == len(d["task"]["gps"]) and am[0]["ticketIds"] == [tid]
    assert am[0]["done"] + sum(am[0]["waiting"].values()) == am[0]["gps"] and am[0]["waiting"].get("field") == 1  # the returned GP waits with the FRT
    assert am[0]["pct"] == round(am[0]["done"] * 100 / am[0]["gps"], 1)
    x = client.get("/api/v1/tickets/report.xlsx", params={"week": WEEK})
    assert x.status_code == 200 and x.content[:2] == b"PK"
