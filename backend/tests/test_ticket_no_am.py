"""Generate Ticket for a circle without an Area Manager / COH in the Escalation Matrix (e.g. Assam): the FEs of GPs
without an AM are still listed (group "No Area Manager"), the admin can type an acting AM (who gets those GPs and FEs
like a matrix AM), add them to a matrix AM, or send FE-wise; typed SME / COH / FE work in their role; an FE or AM
without a target in the week still gets the ticket. Nothing is fixed per circle – it all follows the matrix."""

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import select

from app.analytics.amc_plan import VACANT
from app.db import SessionLocal
from app.models import TicketEvent, TicketRecipient, TicketTask, TicketTaskGp, User
from app.security.core import hash_password
from app.tickets import directory
from app.tickets import task as tasks

from .conftest import VIEWER, login
from .test_ticket_recipients import mail  # noqa: F401 - shared fixture (fake SMTP session)

ACTING = ("acting.am@pratap-test.in", "Acting!Secure-Pass-71")
SME_MAIL = "assam.sme@pratap-test.in"


@pytest.fixture
def assam(imported, monkeypatch):
    """One circle: GPs 0–1 of 'Real AM' (0 with FE 'Fe Real', 1 without an FE), GPs 2–6 WITHOUT an Area Manager (2–3 FE
    'Fe One', 4 FE 'Fe Two' without an e-mail, 5 without an FE, 6 FE 'Fe Zero' planned before the week = no target);
    GPs 0–5 are this week's target. Every other GP of the circle is Real AM's; every GP of the other circles has an AM."""
    week = imported.weeks[-1].code
    w = imported.week(week)
    g = imported.gps
    circle = g["circle"].value_counts().index[0]
    codes = [c for c in g.index[g["circle"] == circle] if not isinstance(g.at[c, "amc_date"], dt.date)][:7]
    if len(codes) < 7:
        pytest.skip("Need 7 GPs without an AMC Date in one circle")
    plan = pd.DataFrame(
        {
            "category": ["5% Incremental"] * 7,
            "planned_date": [w.start] * 6 + [w.start - dt.timedelta(days=30)],
            "ach_date": [None] * 7, "current_status": [None] * 7, "letter_status": [None] * 7, "letter_date": [None] * 7, "approval_status": [None] * 7,
        },
        index=pd.Index(codes, name=imported.amc_plan.index.name),
    )
    monkeypatch.setattr(imported, "amc_plan", plan)
    real = tasks._directory

    def fake(store):
        d, src = real(store)
        d = d.copy()
        mine = (store.gps["circle"] == circle).reindex(d.index).fillna(False).to_numpy()
        d["am"] = ["Real AM" if m else "Other AM" for m in mine]
        d["email"] = [VIEWER[0] if m else "other.am@pratap-test.in" for m in mine]
        d["fe"], d["fe_email"] = None, None
        for c in codes[2:7]:
            d.at[c, "am"], d.at[c, "email"] = VACANT, None
        for c, fe, mail_ in ((codes[0], "Fe Real", "fe.real@x.in"), (codes[2], "Fe One", "fe.one@x.in"), (codes[3], "Fe One", "fe.one@x.in"), (codes[4], "Fe Two", None), (codes[6], "Fe Zero", "fe.zero@x.in")):
            d.at[c, "fe"], d.at[c, "fe_email"] = fe, mail_
        return d, src

    monkeypatch.setattr(tasks, "_directory", fake)
    esc = pd.DataFrame({"circle": [str(circle).upper()] * 7, "shq_name": ["Assam SME"] * 7, "shq_email": [SME_MAIL] * 7}, index=pd.Index(codes, name="gp_code"))
    monkeypatch.setattr(directory, "_active", lambda: ({"id": 1, "fileName": "test-matrix.xlsx"}, esc))  # an SME, no COH / CBH
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.email == ACTING[0])).first() is None:
            db.add(User(email=ACTING[0], name="Acting AM User", role="viewer", password_hash=hash_password(ACTING[1])))
            db.commit()
    # every request of the test reads THIS snapshot (a background reload must not swap in one without the test plan)
    from app.analytics import store as store_mod
    from app.api import tickets as api_tickets
    from app.main import app

    monkeypatch.setattr(api_tickets, "get_store", lambda: imported)
    app.dependency_overrides[store_mod.get_store] = lambda: imported
    other = next(c for c in g["circle"].unique() if c != circle)
    yield {"circle": str(circle).title(), "other": str(other).title(), "week": week, "codes": codes}
    app.dependency_overrides.pop(store_mod.get_store, None)


def _gen(client, h, a, recipients, circle=None):
    body = {
        "circle": circle or a["circle"], "recipients": recipients, "subject": "Weekly GP work", "description": "Please complete the GP conversion work of this week.",
        "priority": "MEDIUM", "sendEmail": True, "task": {"week": a["week"]},
    }
    return client.post("/api/v1/tickets", json=body, headers=h)


def _gps(ticket_id: int) -> dict[str, TicketTaskGp]:
    with SessionLocal() as db:
        return {g.gp_code: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == ticket_id))}


TYPED_AM = {"role": "AM", "name": "Rahul Das", "email": ACTING[0], "typed": True}
FE_ONE = {"role": "FE", "name": "Fe One", "email": "fe.one@x.in", "am": tasks.NO_AM, "feEmail": "fe.one@x.in"}
FE_TWO = {"role": "FE", "name": "Fe Two", "email": "fe.two.typed@x.in", "am": tasks.NO_AM, "feEmail": None}  # no e-mail in the matrix – typed
FE_ZERO = {"role": "FE", "name": "Fe Zero", "email": "fe.zero@x.in", "am": tasks.NO_AM, "feEmail": "fe.zero@x.in"}


def test_directory_lists_fes_without_an_area_manager(client, assam):
    login(client)
    d = client.get("/api/v1/tickets/directory", params={"circle": assam["circle"], "week": assam["week"]}).json()
    no_am = d["noAm"]
    assert no_am["label"] == tasks.NO_AM and no_am["gps"] == 5 and no_am["weekGps"] == 4 and no_am["unmappedFeGps"] == 1
    fes = {(f["am"], f["name"]): f for f in d["fe"]}
    assert fes[(tasks.NO_AM, "Fe One")]["weekGps"] == 2 and fes[(tasks.NO_AM, "Fe Two")]["weekGps"] == 1 and fes[(tasks.NO_AM, "Fe Zero")]["weekGps"] == 0
    assert fes[("Real AM", "Fe Real")]["weekGps"] == 1
    assert [p["name"] for p in d["sme"]] == ["Assam SME"] and d["coh"] == []
    assert client.get("/api/v1/tickets/directory", params={"circle": assam["other"], "week": assam["week"]}).json()["noAm"] is None


def test_acting_am_gets_every_gp_without_an_am_and_their_fes(client, assam, mail):
    h = {"x-csrf-token": login(client)}
    coh = {"role": "COH", "name": "Typed Coh", "email": "typed.coh@x.in", "typed": True}
    r = _gen(client, h, assam, [TYPED_AM, FE_ONE, FE_TWO, FE_ZERO, coh])
    assert r.status_code == 201, r.text
    assert len(r.json()["tickets"]) == 1  # one ticket: the acting AM with the FEs of the GPs without an AM
    t = r.json()["tickets"][0]
    c = assam["codes"]
    gps = _gps(t["id"])
    assert set(gps) == set(c[2:6])  # this week's target of the GPs without an AM – nothing of Real AM
    assert t["subject"].startswith("Weekly GP task – Rahul Das (acting AM) – Week")
    with SessionLocal() as db:
        task = db.get(TicketTask, t["id"])
        assert task.am_name == "Rahul Das" and task.gp_source == "NO_AM"
        recs = {x.name: x for x in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t["id"]))}
        assert recs["Rahul Das"].typed and recs["Rahul Das"].role == "AM" and recs["Rahul Das"].user_id is not None
        assert recs["Typed Coh"].typed and recs["Typed Coh"].role == "COH" and not recs["Fe One"].typed
        note = " ".join(e.note or "" for e in db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == t["id"])))
    assert "acting Area Manager" in note and "Fe Zero 0" in note and "COH Typed Coh (typed by admin)" in note
    # each FE: only the GPs mapped to them (Fe Zero: none this week – still on the ticket)
    assert sum(tasks.FeScope("Fe One", "fe.one@x.in").owns(g) for g in gps.values()) == 2
    assert sum(tasks.FeScope("Fe Two", None).owns(g) for g in gps.values()) == 1
    detail = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert detail["task"]["gpSource"] == "NO_AM" and any(x["typed"] for x in detail["recipients"])


def test_typed_am_refused_where_every_gp_has_an_am(client, assam, mail):
    h = {"x-csrf-token": login(client)}
    r = _gen(client, h, assam, [TYPED_AM], circle=assam["other"])
    assert r.status_code == 422 and "has an Area Manager" in r.json()["detail"]
    r = _gen(client, h, assam, [{**TYPED_AM, "name": "Real AM"}])
    assert r.status_code == 422 and "select them from the list" in r.json()["detail"]


def test_gps_without_an_am_go_to_one_area_manager_only(client, assam, mail):
    h = {"x-csrf-token": login(client)}
    real = {"role": "AM", "name": "Real AM", "email": VIEWER[0], "withNoAm": True}
    r = _gen(client, h, assam, [real, TYPED_AM])
    assert r.status_code == 422 and "Only one Area Manager" in r.json()["detail"]


def test_matrix_am_can_take_the_gps_without_an_am(client, assam, mail):
    h = {"x-csrf-token": login(client)}
    real = {"role": "AM", "name": "Real AM", "email": VIEWER[0], "withNoAm": True}
    r = _gen(client, h, assam, [real, FE_ONE])
    assert r.status_code == 201, r.text
    (t,) = r.json()["tickets"]
    assert set(_gps(t["id"])) == set(assam["codes"][:6])  # own GPs 0–1 + the GPs without an AM 2–5
    with SessionLocal() as db:
        assert db.get(TicketTask, t["id"]).gp_source == "AM+NO_AM"
    p = client.get("/api/v1/tickets/task/preview", params={"am": "Real AM", "week": assam["week"], "circle": assam["circle"], "withNoAm": "true"}).json()
    assert len(p["rows"]) == 6 and {f["name"] for f in p["summary"]["fes"]} >= {"Fe Real", "Fe One"}


def test_fe_wise_ticket_without_an_am_and_zero_target(client, assam, mail):
    """FEs of GPs without an AM, sent without any Area Manager: one ticket with only their GPs; Fe Zero (no target this
    week) alone still gets a ticket with 0 GPs – never refused."""
    h = {"x-csrf-token": login(client)}
    r = _gen(client, h, assam, [FE_ONE])
    assert r.status_code == 201, r.text
    (t,) = r.json()["tickets"]
    assert set(_gps(t["id"])) == set(assam["codes"][2:4]) and t["subject"].startswith(f"Weekly GP task – FE Fe One ({tasks.NO_AM})")
    r = _gen(client, h, assam, [FE_ZERO])
    assert r.status_code == 201, r.text
    (t,) = r.json()["tickets"]
    assert _gps(t["id"]) == {}
    detail = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert detail["task"]["totals"]["gps"] == 0


def test_typed_fe_gets_the_gps_without_an_fe(client, assam, mail):
    h = {"x-csrf-token": login(client)}
    typed_fe = {"role": "FE", "name": "New Fe", "email": "new.fe@x.in", "am": "Real AM", "typed": True}
    r = _gen(client, h, assam, [{"role": "AM", "name": "Real AM", "email": VIEWER[0]}, typed_fe])
    assert r.status_code == 201, r.text
    (t,) = r.json()["tickets"]
    gps = _gps(t["id"])
    c = assam["codes"]
    assert set(gps) == set(c[:2]) and gps[c[1]].fe_name == "New Fe" and gps[c[1]].fe_email == "new.fe@x.in"
    assert gps[c[0]].fe_name == "Fe Real"  # a GP with an FE in the matrix keeps that FE
    r = _gen(client, h, assam, [typed_fe])  # a typed FE needs the Area Manager's ticket
    assert r.status_code == 422 and "add the Area Manager" in r.json()["detail"]
