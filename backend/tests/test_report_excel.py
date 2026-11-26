"""Ticket Report Excel (app.tickets.report.xlsx + excel_details): readable without the page.

* the days run from the ticket's generation to today: a ticket generated after its week ended still shows its work
  (the page keeps the 7 week days – unchanged);
* every GP once: a GP on two tickets of the week is one row of GP Status (both tickets named);
* who has to act: one person per GP; the sheets are Summary, GP Status, Team Activity, AM Achievement, Returns, Completed.
"""

import datetime as dt
import io

from python_calamine import CalamineWorkbook
from sqlalchemy import update

from app.db import SessionLocal
from app.models import TicketTask
from app.tickets.monitor import _local_date

from .conftest import login
from .evidence import progress
from .test_ticket_fe import FE1, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import FRT, _check, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

WEEK = "W-91"  # test database only: a week that ended before the tickets were generated

SHEETS = ["Summary", "GP Status", "Team Activity", "AM Achievement", "Returns", "Completed"]


def _past_week(*tids, week=WEEK):
    """Move the tickets to a week that ended a week ago (generated after the week, as happens in the field)."""
    today = _local_date(dt.datetime.now(dt.UTC))
    start = today - dt.timedelta(days=13)
    with SessionLocal() as db:
        db.execute(update(TicketTask).where(TicketTask.ticket_id.in_(tids)).values(week_code=week, week_start=start, week_end=start + dt.timedelta(days=6)))
        db.commit()
    return today


def _sheets(content: bytes) -> dict[str, list[list]]:
    wb = CalamineWorkbook.from_filelike(io.BytesIO(content))
    return {n: wb.get_sheet_by_name(n).to_python() for n in wb.sheet_names}


def test_excel_counts_work_after_the_week_and_every_gp_once(client, frt_org, mail):  # noqa: F811
    t1 = _ticket(client, frt_org)
    t2 = _ticket(client, frt_org)  # the same Area Manager's GPs again: every GP on two tickets
    today = _past_week(t1, t2)
    d = client.get(f"/api/v1/tickets/{t2}").json()
    g = next(x["id"] for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"])
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, t2, [{"taskGpId": g, "category": "A", "remark": "Splicing done"}], hf).status_code == 200
    # work today on a ticket of ANOTHER week: never counted in this week's Excel
    t3 = _ticket(client, frt_org)
    g3 = next(x["id"] for x in client.get(f"/api/v1/tickets/{t3}").json()["task"]["gps"] if x["gpCode"] in frt_org["one"])
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, t3, [{"taskGpId": g3, "category": "A", "remark": "Other week work"}], hf).status_code == 200

    login(client)
    page = client.get("/api/v1/tickets/report", params={"week": WEEK}).json()
    # the page: the 7 week days only – today's submission is after the week: a separate total (Option B)
    assert len(page["days"]) == 7 and page["cards"]["submissions"] == 0
    assert page["cards"]["submissionsAfterWeek"] == 1  # t2's – not t3's (another week's ticket)
    assert sum(p["afterWeek"]["subs"] for p in page["people"]) == 1
    assert next(r for r in page["roles"] if r["role"] == "FRT")["submissionsAfterWeek"] == 1
    # every GP once on the page: the KPI, the pending boxes and rows; the GP's tickets named
    unique_page = len({x["gpCode"] for x in client.get(f"/api/v1/tickets/{t2}").json()["task"]["gps"]})
    assert page["cards"]["gpsUnique"] == unique_page and page["cards"]["gpsOnTwoTickets"] == unique_page
    pend = page["pending"]
    prim = [it for it in pend["items"] if it["primary"]]
    assert len(prim) == unique_page == sum(b["gps"] for b in pend["buckets"])
    assert all(len(it["tickets"]) == 2 and it["why"] for it in prim)
    # one person per GP: the GPs to fill add up to the not-filled GPs (never counted for the FE and the AM as well)
    not_filled = next(b["gps"] for b in pend["buckets"] if b["key"] == "not_filled")
    assert sum(p.get("toFill", 0) for p in page["people"]) == not_filled
    assert sum(r.get("toFill", 0) for r in page["roles"]) == not_filled
    x = client.get("/api/v1/tickets/report.xlsx", params={"week": WEEK})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    sh = _sheets(x.content)
    assert list(sh) == SHEETS

    # Summary: the submission after the week counts; the GPs once; the warnings say why
    summary = {r[0]: r[1] for r in sh["Summary"] if r and r[0]}
    assert summary["Daily submissions (whole period)"] == 1  # t2's – not t3's (another week's ticket)
    unique = len({x["gpCode"] for x in d["task"]["gps"]})
    assert summary["GPs (each GP once)"] == unique
    text = " ".join(str(c) for r in sh["Summary"] for c in r)
    assert "generated after the week ended" in text and "on two tickets" in text

    # GP Status: one row per GP code, both tickets named, who acts and why
    gs = sh["GP Status"]
    head = gs[1]  # row 0: the column groups (GP / team / status / pending with)
    rows = [r for r in gs[2:] if r and r[0]]
    codes = [r[head.index("GP code")] for r in rows]
    assert len(codes) == len(set(codes)) == unique
    t_codes = {r[head.index("Ticket(s)")] for r in rows}
    assert any("," in c for c in t_codes)
    assert all(r[head.index("Why with them")] for r in rows)
    # the team's logins and one plain status per GP; a not-filled GP names the person it is pending with
    assert {r[head.index("AM login")] for r in rows} <= {"Yes", "No"}
    for r in rows:
        st = r[head.index("Status now")]
        assert st
        if st.startswith("NOT FILLED"):
            assert r[head.index("Pending with (name)")] and r[head.index("Role")] in ("AM", "FE", "FRT")

    # Team Activity: a column for today (after the week)
    ta = sh["Team Activity"][0]
    assert today.strftime("%d-%b")[:6] in [str(c) for c in ta]
    # the page JSON is unchanged by the Excel
    assert client.get("/api/v1/tickets/report", params={"week": WEEK}).json()["cards"] == page["cards"]


def test_gp_status_shows_who_did_what_when(client, frt_org, mail):  # noqa: F811
    """GP Status: Circle / BA, the day of every step; a step done twice shows it (2×), the return says who, to whom, why."""
    week = "W-92"
    tid = _ticket(client, frt_org)
    today = _past_week(tid, week=week)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    g = next(x for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"])
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Splicing done"}], hf).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g["id"]], "FE_RETURN", "Photo not clear", h1).status_code == 200
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Splicing done again"}], hf).status_code == 200

    login(client)
    sh = _sheets(client.get("/api/v1/tickets/report.xlsx", params={"week": week}).content)
    gs = sh["GP Status"]
    head = gs[1]
    row = next(r for r in gs[2:] if r and r[0] == g["gpCode"])
    col = lambda name: row[head.index(name)]  # noqa: E731
    day = today.strftime("%d-%b")
    assert col("Circle") == frt_org["circle"] and "BA" in head
    assert col("Ticket generated on") == day
    assert col("FRT filled on") == f"{day} (2×)"  # filled, returned, filled again – the same day
    assert "FE → FRT" in col("Returned (when: who → whom, why)") and "Photo not clear" in col("Returned (when: who → whom, why)")
    assert col("FE filled on") == "" and col("AM approved (sent on) on") == ""  # not done – empty
