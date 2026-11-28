"""Ticket hierarchy (app.tickets.units): AM ticket -> FE tickets -> FRT (GP-wise) tickets.

* generating an AM ticket gives every FE on it an FE ticket and every GP with an FRT team an FRT ticket, each ID
  starting with the AM ticket's ID, linked by keys (not by the text of the ID), no duplicates on a second sync;
* every ticket has its own status and history: the FRT ticket follows its GP's FE step (FRT submitted -> Pending FE
  Verification, FE returned -> In Progress, FE verified -> Closed); closing one never closes a parent or a sibling;
* only the ticket's Area Manager closes an FE ticket (same SOP rule as the Admin's close; forced = written reason);
  the Admin closing the AM ticket leaves the FE / FRT tickets as they are;
* Admin: every level in one list (search by any ID, filters, counts per level); others: only their own part.
"""

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Ticket, TicketUnit, TicketUnitEvent
from app.tickets import task as tasks
from app.tickets import units

from .conftest import VIEWER, login
from .evidence import progress
from .test_ticket_fe import FE1, FE2, fe_org  # noqa: F401 - shared fixture
from .test_ticket_frt import CODE, FRT, _check, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401

CODE2 = "FRT-T2"  # an FRT team on the GP without an FE (its FRT ticket hangs directly under the AM ticket)


@pytest.fixture
def unit_org(frt_org, monkeypatch):  # noqa: F811
    base = tasks._directory

    def with_frt2(store):
        d, src = base(store)
        d = d.copy()
        d.loc[d.index.isin(frt_org["unmapped"]), "frt"] = CODE2
        return d, src

    monkeypatch.setattr(tasks, "_directory", with_frt2)
    return frt_org


def _tree(client, tid):
    r = client.get(f"/api/v1/tickets/{tid}/hierarchy")
    assert r.status_code == 200, r.text
    return r.json()


def _status(tid, gp_id=None, code=None):
    with SessionLocal() as db:
        q = select(TicketUnit.status).where(TicketUnit.ticket_id == tid)
        q = q.where(TicketUnit.task_gp_id == gp_id) if gp_id else q.where(TicketUnit.code == code)
        return db.scalars(q).one()


def test_hierarchy_ids_links_and_no_duplicates(client, unit_org, mail):  # noqa: F811
    tid = _ticket(client, unit_org)
    login(client)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    am_code = d["code"]
    tree = _tree(client, tid)
    assert tree["ticket"]["code"] == am_code and tree["ticket"]["level"] == "AM"
    fe = {f["fe"]: f for f in tree["fe"]}
    assert set(fe) == {"Test FE One", "Test FE Two"}
    assert sorted(f["code"] for f in tree["fe"]) == [f"{am_code}-FE-01", f"{am_code}-FE-02"]
    one = fe["Test FE One"]
    # FE One's GPs have FRT-T1: one FRT ticket per GP, under FE One's ticket; FE Two's GPs have no FRT team
    assert sorted(x["gpCode"] for x in one["frt"]) == sorted(unit_org["one"])
    assert [x["code"] for x in sorted(one["frt"], key=lambda x: x["code"])] == [f"{one['code']}-FRT-{i:03d}" for i in range(1, len(unit_org["one"]) + 1)]
    assert all(x["frt"] == CODE and x["parentCode"] == one["code"] and x["amCode"] == am_code and x["status"] == "OPEN" for x in one["frt"])
    assert fe["Test FE Two"]["frt"] == []
    # the GP without an FE but with an FRT team: directly under the AM ticket
    assert [(x["code"], x["frt"], x["gpCode"]) for x in tree["frtDirect"]] == [(f"{am_code}-FRT-001", CODE2, unit_org["unmapped"][0])]
    # every ID unique and starting with the AM ticket's ID; links by keys
    with SessionLocal() as db:
        rows = list(db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == tid)))
        assert len({u.code for u in rows}) == len(rows) and all(u.code.startswith(am_code + "-") for u in rows)
        fe_ids = {u.id for u in rows if u.level == "FE" and u.fe_name == "Test FE One"}
        assert all(u.parent_id in fe_ids for u in rows if u.level == "FRT" and u.frt_code == CODE)
        assert all(u.task_gp_id for u in rows if u.level == "FRT")
        n = len(rows)
        units.sync(db, tid)  # a second sync (and every later commit) adds nothing
        db.commit()
        assert db.scalar(select(func.count()).select_from(TicketUnit).where(TicketUnit.ticket_id == tid)) == n
        assert db.scalar(select(func.count()).select_from(TicketUnitEvent).join(TicketUnit).where(TicketUnit.ticket_id == tid, TicketUnitEvent.action == "CREATED")) == n


def test_each_ticket_moves_on_its_own(client, unit_org, mail):  # noqa: F811
    tid = _ticket(client, unit_org)
    login(client)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    am_code = d["code"]
    g1 = next(g["id"] for g in d["task"]["gps"] if g["gpCode"] in unit_org["one"])  # FE One's GP of FRT-T1
    g2 = next(g["id"] for g in d["task"]["gps"] if g["gpCode"] in unit_org["unmapped"])  # a sibling FRT ticket (FRT-T2)
    fe1, fe2 = f"{am_code}-FE-01", f"{am_code}-FE-02"

    # FRT submits GP 1 -> its FRT ticket waits for the FE; nothing else changes
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g1, "category": "A", "remark": "Splicing done"}], hf).status_code == 200
    assert _status(tid, g1) == "PENDING_REVIEW" and _status(tid, g2) == "OPEN"
    assert _status(tid, code=fe1) == "OPEN" and _status(tid, code=fe2) == "OPEN"  # the FRT's work never moves the FE ticket

    # FE One returns it -> In Progress; FE One worked -> FE One's ticket In Progress (FE Two's stays Open)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g1], "FE_RETURN", "Photo not clear", h1).status_code == 200
    assert _status(tid, g1) == "IN_PROGRESS" and _status(tid, code=fe1) == "IN_PROGRESS" and _status(tid, code=fe2) == "OPEN"

    # submitted again and verified -> FRT ticket 1 Closed; its sibling, its FE ticket and the AM ticket stay as they are
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g1, "category": "A", "remark": "Splicing done again"}], hf).status_code == 200
    h1 = {"X-CSRF-Token": login(client, FE1)}
    assert _check(client, tid, [g1], "FE_VERIFY", "Checked the photo", h1).status_code == 200
    assert _status(tid, g1) == "CLOSED" and _status(tid, g2) == "OPEN" and _status(tid, code=fe1) == "IN_PROGRESS"
    login(client)
    # the AM ticket follows only its own (existing) rules: the first Daily Achievement moved it Open -> In Progress
    # (as before); the closed FRT ticket did not close it
    am_status = client.get(f"/api/v1/tickets/{tid}").json()["status"]
    assert am_status == "IN_PROGRESS"
    # "Tickets in Progress": the card's number and the list it opens are the same tickets (AM + FE + FRT)
    k = client.get("/api/v1/tickets/kpis", params={"scope": "all", "search": am_code}).json()
    card = (k["byStatus"]["IN_PROGRESS"] + k["byStatus"]["PENDING_REVIEW"] + k["byStatus"]["CHANGES_REQUESTED"]
            + k["units"]["FE"]["IN_PROGRESS"] + k["units"]["FE"]["PENDING_REVIEW"] + k["units"]["FRT"]["IN_PROGRESS"] + k["units"]["FRT"]["PENDING_REVIEW"])
    wk = client.get("/api/v1/tickets/working", params={"search": am_code}).json()
    assert len(wk["tickets"]) == card == 2  # the AM ticket and FE One's ticket (the FRT ticket is closed)
    assert {(x["level"], x["code"]) for x in wk["tickets"]} == {("AM", am_code), ("FE", fe1)}
    assert [x["id"] for x in wk["items"]] == [tid]  # the existing list (who worked) is unchanged
    # its own history, with who did it
    u1 = next(x for f in _tree(client, tid)["fe"] for x in f["frt"] if x["gpId"] == g1)
    hist = client.get(f"/api/v1/tickets/{tid}/units/{u1['id']}").json()["history"]
    assert [h["to"] for h in hist] == ["OPEN", "PENDING_REVIEW", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED"]
    from app.models import User

    with SessionLocal() as db:
        names = {u.email: u.name for u in db.scalars(select(User).where(User.email.in_((FE1[0], FRT[0]))))}
    assert hist[-1]["by"] == names[FE1[0]] and hist[1]["by"] == names[FRT[0]]  # the accounts that acted

    # the Area Manager closes FE Two's ticket: GPs not approved -> refused, then forced with a reason
    two = next(f for f in _tree(client, tid)["fe"] if f["fe"] == "Test FE Two")
    url = f"/api/v1/tickets/{tid}/units/{two['id']}/close"
    h2 = {"X-CSRF-Token": login(client, FE2)}
    assert client.post(url, json={}, headers=h2).status_code == 403  # the FE cannot close their own FE ticket
    ha = {"X-CSRF-Token": login(client)}
    assert client.post(url, json={"force": True, "remark": "Admin is not the AM"}, headers=ha).status_code == 403  # no new power for the Admin
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert client.post(url, json={}, headers=hv).status_code == 409
    assert client.post(url, json={"force": True, "remark": "short"}, headers=hv).status_code == 422
    r = client.post(url, json={"force": True, "remark": "FE Two moved to another circle"}, headers=hv)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED" and "FE Two moved" in r.json()["closeRemark"] and r.json()["closedBy"]
    assert client.post(url, json={"force": True, "remark": "FE Two moved to another circle"}, headers=hv).status_code == 409  # already closed
    assert _status(tid, code=fe2) == "CLOSED" and _status(tid, code=fe1) == "IN_PROGRESS" and _status(tid, g2) == "OPEN"
    login(client)
    assert client.get(f"/api/v1/tickets/{tid}").json()["status"] == am_status  # the AM ticket is not closed by it

    # the Admin closes the AM ticket (existing rule, forced with a reason): no FE / FRT ticket changes
    with SessionLocal() as db:
        before = {u.code: u.status for u in db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == tid))}
    ha = {"X-CSRF-Token": login(client)}
    r = client.post(f"/api/v1/tickets/{tid}/close", json={"force": True, "comment": "Week over – closing the AM ticket"}, headers=ha)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Ticket, tid).status == "CLOSED"
        assert {u.code: u.status for u in db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == tid))} == before


def test_who_sees_what_and_the_admin_list(client, unit_org, mail):  # noqa: F811
    tid = _ticket(client, unit_org)
    login(client)
    am_code = client.get(f"/api/v1/tickets/{tid}").json()["code"]

    # the Area Manager: the whole tree; FE One: their FE ticket and its FRT tickets; FE Two: only theirs; the FRT: only theirs
    login(client, VIEWER)
    t = _tree(client, tid)
    assert len(t["fe"]) == 2 and len(t["frtDirect"]) == 1 and t["canCloseFe"] is True
    login(client, FE1)
    t = _tree(client, tid)
    assert [f["fe"] for f in t["fe"]] == ["Test FE One"] and len(t["fe"][0]["frt"]) == len(unit_org["one"]) and t["frtDirect"] == [] and t["canCloseFe"] is False
    login(client, FE2)
    t = _tree(client, tid)
    assert [f["fe"] for f in t["fe"]] == ["Test FE Two"] and t["fe"][0]["frt"] == [] and t["frtDirect"] == []
    one_id = next(f["id"] for f in _tree_as_admin(client, tid)["fe"] if f["fe"] == "Test FE One")
    login(client, FE2)
    assert client.get(f"/api/v1/tickets/{tid}/units/{one_id}").status_code == 404  # FE Two cannot open FE One's FE ticket
    login(client, FRT)
    t = _tree(client, tid)
    assert t["fe"] == [] and len(t["frtDirect"]) == len(unit_org["one"]) and all(x["frt"] == CODE for x in t["frtDirect"])
    assert client.get(f"/api/v1/tickets/{tid}/units/{one_id}").status_code == 404

    # the Admin list: every level, counts per level (each ticket once), search by any ID, filters; Admin only
    assert client.get("/api/v1/tickets/hierarchy").status_code == 403
    login(client)
    r = client.get("/api/v1/tickets/hierarchy", params={"search": am_code, "pageSize": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    c = body["counts"]
    assert c["AM"]["total"] == 1 and c["FE"]["total"] == 2 and c["FRT"]["total"] == len(unit_org["one"]) + 1
    assert body["total"] == 1 + 2 + len(unit_org["one"]) + 1
    codes = [x["code"] for x in body["items"]]
    assert codes[0] == am_code and codes == sorted(codes)  # AM first, FE and FRT under it
    am_row = body["items"][0]
    assert am_row["children"]["fe"] == 2 and am_row["children"]["frt"] == len(unit_org["one"]) + 1
    one_frt = f"{am_code}-FE-01-FRT-001"
    r = client.get("/api/v1/tickets/hierarchy", params={"search": one_frt}).json()
    assert [x["code"] for x in r["items"]] == [one_frt] and r["items"][0]["am"] and r["items"][0]["fe"] == "Test FE One" and r["items"][0]["gpCode"]
    r = client.get("/api/v1/tickets/hierarchy", params={"search": am_code, "level": "FRT", "frt": CODE2}).json()
    assert [x["code"] for x in r["items"]] == [f"{am_code}-FRT-001"]
    r = client.get("/api/v1/tickets/hierarchy", params={"search": am_code, "level": "FE", "status": "OPEN"}).json()
    assert len(r["items"]) == 2 and r["counts"]["FRT"]["total"] == len(unit_org["one"]) + 1  # counts ignore level / status
    assert client.get("/api/v1/tickets/hierarchy", params={"dateFrom": "2026-11-02", "dateTo": "2026-11-01"}).status_code == 422

    # Admin Tickets KPIs (same filters as the list): the FE / FRT ticket counts are a NEW field next to the old ones
    k = client.get("/api/v1/tickets/kpis", params={"scope": "all", "search": am_code}).json()
    assert {"total", "open", "closed", "byStatus", "work"} <= set(k)  # the existing fields are still there
    assert k["total"] == 1 and k["work"]["fe"] == 2  # the existing numbers are unchanged (people per ticket)
    assert k["units"]["FE"]["total"] == 2 and k["units"]["FRT"]["total"] == len(unit_org["one"]) + 1
    assert k["units"]["FE"]["OPEN"] == 2 and k["units"]["FRT"]["CLOSED"] == 0
    # "Team on these tickets": each person / FRT team once – the same people as the Ticket Report
    p = k["people"]
    assert (p["am"], p["fe"], p["frt"]) == (1, 2, 2) and (p["amTickets"], p["feTickets"], p["frtTickets"]) == (1, 1, 1)
    assert p["frtLogin"] == 1 and p["total"] == 5  # FRT-T1 has an account, FRT-T2 none
    # a second ticket for the same people: still each person once, on 2 tickets (the per-ticket "work" doubles)
    _ticket(client, unit_org)
    login(client)
    from app.db import SessionLocal as _S
    from app.tickets import report, service

    with _S() as db:
        ids = service.filtered_ids(db, None, {"week": unit_org["week"], "area_manager": unit_org["am"]})
        p2 = service.people_totals(db, ids)
        rep = {r["role"]: r for r in report.build(db, unit_org["week"], None, None)["roles"]}
        all_ids = service.filtered_ids(db, None, {"week": unit_org["week"]})
        p_all = service.people_totals(db, all_ids)
    assert p2["am"] == 1 and p2["amTickets"] >= 2 and p2["fe"] == 2
    assert (p_all["am"], p_all["fe"], p_all["frt"]) == (rep["AM"]["people"], rep["FE"]["people"], rep["FRT"]["people"])  # = Ticket Report
    login(client, FE1)
    assert "units" not in client.get("/api/v1/tickets/kpis").json()  # a user's own KPIs (scope mine): unchanged


def test_everyone_sees_their_own_ticket_id(client, unit_org, mail):  # noqa: F811
    """User Tickets list and ticket detail: an FE sees their FE ticket ID, an FRT their GP-wise FRT ticket IDs, each
    GP row its FRT ticket ID (only GPs the user may see); the AM ticket's ID and every existing field stay as before."""
    tid = _ticket(client, unit_org)
    login(client)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    am_code = d["code"]
    assert "myUnit" not in d  # the Admin is nobody's FE / FRT: as before
    frt_gp = next(g["id"] for g in d["task"]["gps"] if g["gpCode"] in unit_org["one"])
    assert d["gpUnits"][str(frt_gp)]["code"].startswith(f"{am_code}-FE-01-FRT-")
    assert len(d["gpUnits"]) == len(unit_org["one"]) + 1  # every FRT GP of the ticket
    adm = next(x for x in client.get("/api/v1/tickets", params={"scope": "all", "search": am_code}).json()["items"] if x["id"] == tid)
    assert adm["code"] == am_code and "myUnit" not in adm  # Admin Tickets list unchanged

    login(client, FE1)
    item = next(x for x in client.get("/api/v1/tickets").json()["items"] if x["id"] == tid)
    assert item["code"] == am_code and item["myUnit"]["code"] == f"{am_code}-FE-01" and item["myUnit"]["level"] == "FE"
    d1 = client.get(f"/api/v1/tickets/{tid}").json()
    assert d1["myUnit"]["code"] == f"{am_code}-FE-01" and set(d1["gpUnits"]) == {str(frt_gp)}  # only their GPs' FRT tickets

    login(client, FE2)
    d2 = client.get(f"/api/v1/tickets/{tid}").json()
    assert d2["myUnit"]["code"] == f"{am_code}-FE-02" and d2["gpUnits"] == {}  # FE Two's GPs have no FRT team

    login(client, FRT)
    item = next(x for x in client.get("/api/v1/tickets").json()["items"] if x["id"] == tid)
    assert item["myUnit"]["level"] == "FRT" and item["myUnit"]["count"] == len(unit_org["one"]) and all(c.startswith(f"{am_code}-FE-01-FRT-") for c in item["myUnit"]["codes"])
    assert client.get(f"/api/v1/tickets/{tid}").json()["myUnit"]["codes"] == item["myUnit"]["codes"]

    login(client, VIEWER)  # the Area Manager: the AM ticket's ID, as before
    item = next(x for x in client.get("/api/v1/tickets").json()["items"] if x["id"] == tid)
    assert item["code"] == am_code and "myUnit" not in item


def _tree_as_admin(client, tid):
    login(client)
    return _tree(client, tid)


def test_existing_tickets_get_their_children_without_changes(client, unit_org, mail):  # noqa: F811
    """A ticket from before the hierarchy (no units yet) gets its FE / FRT tickets from the start-up backfill; the
    ticket itself, its GPs and its history are not touched."""
    tid = _ticket(client, unit_org)
    with SessionLocal() as db:
        for u in db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == tid)):
            db.delete(u)
        db.commit()
        t = db.get(Ticket, tid)
        before = (t.status, t.code, t.subject, t.updated_at)
        assert db.scalar(select(func.count()).select_from(TicketUnit).where(TicketUnit.ticket_id == tid)) == 0
    with SessionLocal() as db:
        units.backfill(db)
    with SessionLocal() as db:
        t = db.get(Ticket, tid)
        assert (t.status, t.code, t.subject, t.updated_at) == before
        n = db.scalar(select(func.count()).select_from(TicketUnit).where(TicketUnit.ticket_id == tid))
        assert n == 2 + len(unit_org["one"]) + 1


def test_targets_and_ticket_ids_in_the_excel_sheets(client, unit_org, mail):  # noqa: F811
    """Target GPs of every level (AM = all GPs, FE = the FE's GPs, FRT = its GP) on the screens, and the AM / FE / FRT
    ticket IDs with their targets as the LAST columns of the Excel sheets (the existing columns keep their place)."""
    import io

    from python_calamine import CalamineWorkbook

    from app.tickets.units import HIER_COLS

    heads = [h for h, _w in HIER_COLS]
    tid = _ticket(client, unit_org)
    login(client)
    d = client.get(f"/api/v1/tickets/{tid}").json()
    am_code, gps = d["code"], d["task"]["gps"]
    total = sum(g["target"] for g in gps)
    one_target = sum(g["target"] for g in gps if g["gpCode"] in unit_org["one"])
    tree = _tree(client, tid)
    assert tree["ticket"]["targetGps"] == total
    fe1 = next(f for f in tree["fe"] if f["fe"] == "Test FE One")
    assert fe1["targetGps"] == one_target and all(x["targetGps"] == 1 for x in fe1["frt"])
    login(client, FE1)
    assert client.get(f"/api/v1/tickets/{tid}").json()["myUnit"]["targetGps"] == one_target
    login(client, FRT)
    assert client.get(f"/api/v1/tickets/{tid}").json()["myUnit"]["targetGps"] == len(unit_org["one"])

    # the GP assignment workbook: existing columns as before, the six new ones at the end
    login(client)
    rows = CalamineWorkbook.from_filelike(io.BytesIO(client.get(f"/api/v1/tickets/{tid}/task/assignment.xlsx").content)).get_sheet_by_name("GP Task").to_python()
    head = rows[4]
    assert head[7] == "GP Code" and head[-6:] == heads
    g = next(x for x in gps if x["gpCode"] in unit_org["one"])
    row = next(r for r in rows[5:] if str(r[7]) == str(g["gpCode"]))
    assert row[-6] == am_code and row[-5] == total and row[-4] == f"{am_code}-FE-01" and row[-3] == one_target
    assert str(row[-2]).startswith(f"{am_code}-FE-01-FRT-") and row[-1] == 1
    two = next(x for x in gps if x["gpCode"] in unit_org["two"])  # FE Two's GP: no FRT team
    row2 = next(r for r in rows[5:] if str(r[7]) == str(two["gpCode"]))
    assert row2[-4] == f"{am_code}-FE-02" and row2[-2] == "—"

    # the Ticket Report Excel: GP Status ends with the same six columns
    wb = CalamineWorkbook.from_filelike(io.BytesIO(client.get("/api/v1/tickets/report.xlsx", params={"week": unit_org["week"]}).content))
    gs = wb.get_sheet_by_name("GP Status").to_python()
    assert gs[1][0] == "GP code" and gs[1][-6:] == heads
    # each GP is listed once (on its newest ticket of the week – other test files may add tickets with the same GPs):
    # its three IDs belong together – the FRT ID starts with its FE ID, the FE ID with its AM ID
    for r in gs[2:]:
        am_id, fe_id, frt_id = str(r[-6]), str(r[-4]), str(r[-2])
        assert am_id.startswith("TKT-")
        assert fe_id == "—" or fe_id.startswith(f"{am_id}-FE-")  # "—" = the GP's ticket has no FE ticket for it
        assert frt_id == "—" or frt_id.startswith(f"{fe_id if fe_id != '—' else am_id}-FRT-")

    # Team Activity: each person's OWN ticket IDs – AM: AM tickets, FE: FE tickets, FRT: FRT tickets
    ta = wb.get_sheet_by_name("Team Activity").to_python()
    h = [str(x) for x in ta[0]]
    assert h[h.index("Tickets") + 1] == "Ticket ID(s)"
    col = h.index("Ticket ID(s)")
    by = {(str(r[0]), str(r[1])): str(r[col]) for r in ta[1:] if r and r[0]}
    am_cell = next(v for (rl, _n), v in by.items() if rl == "AM" and am_code in v)
    assert all(x.startswith("TKT-") and "-FE-" not in x for x in am_cell.split(", "))
    fe_cell = next(v for (rl, _n), v in by.items() if rl == "FE" and f"{am_code}-FE-01" in v.split(", "))
    assert all("-FE-" in x and "-FRT-" not in x for x in fe_cell.split(", "))
    frt_cell = next(v for (rl, _n), v in by.items() if rl == "FRT" and f"{am_code}-FE-01-FRT-" in v)
    assert all("-FRT-" in x for x in frt_cell.split(", "))
