"""Roles & Access – the admin pages a role may be given (app.security.roles.ADMIN_PAGES):

* Ticket Report (tickets-report): the weekly report and its Excel;
* Admin Tickets (tickets-admin): the user acts as an admin on the ticket endpoints (every ticket, filters, …);
* User Management (users-admin): users and the role list – never an admin account, never their own role; roles stay
  admin-only to change.
Off by default: a viewer without a role (the built-in Viewer) and every existing role get none of them.
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User

from .conftest import ADMIN, VIEWER, login

ON = {"laptop": True, "phone": False}
BASE = {"tickets-user": ON}


def _h(client, creds=ADMIN):
    return {"X-CSRF-Token": login(client, creds)}


def _id(email):
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == email)).one()


def _with_role(client, name, pages):
    """Create a role, give it to the test viewer; returns the role id."""
    h = _h(client)
    r = client.post("/api/v1/roles", json={"name": name, "pages": {**BASE, **pages}}, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.patch(f"/api/v1/users/{_id(VIEWER[0])}", json={"roleId": rid}, headers=h).status_code == 200
    return rid


def _cleanup(client, rid):
    h = _h(client)
    assert client.patch(f"/api/v1/users/{_id(VIEWER[0])}", json={"roleId": None}, headers=h).status_code == 200
    assert client.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 200


def test_admin_pages_are_listed_and_off_by_default(client):
    _h(client)
    keys = [p["key"] for p in client.get("/api/v1/roles").json()["pages"]]
    assert {"tickets-admin", "tickets-report", "users-admin"} <= set(keys)
    assert not {"operations", "roles", "mail", "settings"} & set(keys)
    # a viewer without a role: none of the admin pages (as before)
    login(client, VIEWER)
    p = client.get("/api/v1/auth/me").json()["permissions"]
    assert p["pages"]["overview"]["laptop"] is True
    assert all(p["pages"][k] == {"laptop": False, "phone": False} for k in ("tickets-admin", "tickets-report", "users-admin"))
    for url in ("/api/v1/tickets/report", "/api/v1/tickets/filter-options", "/api/v1/tickets?scope=all", "/api/v1/users", "/api/v1/roles"):
        assert client.get(url).status_code == 403, url
    # the admin still has every page
    login(client)
    assert client.get("/api/v1/auth/me").json()["permissions"]["pages"]["users-admin"]["laptop"] is True
    assert client.get("/api/v1/tickets/report").status_code == 200


def test_ticket_report_page(client):
    rid = _with_role(client, "Test Report Role", {"tickets-report": ON})
    try:
        login(client, VIEWER)
        assert client.get("/api/v1/tickets/report").status_code == 200
        assert client.get("/api/v1/tickets/report.xlsx").status_code == 200
        # nothing else of the admin pages
        assert client.get("/api/v1/tickets?scope=all").status_code == 403
        assert client.get("/api/v1/users").status_code == 403
    finally:
        _cleanup(client, rid)


def test_admin_tickets_page(client):
    rid = _with_role(client, "Test Ticket Admin Role", {"tickets-admin": ON})
    try:
        login(client, VIEWER)
        assert client.get("/api/v1/tickets?scope=all").status_code == 200
        assert client.get("/api/v1/tickets/filter-options").status_code == 200
        assert client.get("/api/v1/tickets/kpis?scope=all").status_code == 200
        # the other admin pages stay closed
        assert client.get("/api/v1/tickets/report").status_code == 403
        assert client.get("/api/v1/users").status_code == 403
    finally:
        _cleanup(client, rid)


def test_user_management_page(client):
    rid = _with_role(client, "Test User Manager Role", {"users-admin": ON})
    new_id = None
    try:
        h = _h(client, VIEWER)
        assert client.get("/api/v1/users").status_code == 200
        assert client.get("/api/v1/roles").status_code == 200  # the role picker
        # roles stay admin-only to change; other admin pages stay closed
        assert client.post("/api/v1/roles", json={"name": "Mine", "pages": BASE}, headers=h).status_code == 403
        assert client.get("/api/v1/ingestion/runs").status_code == 403
        # never an admin account: not created, not changed, not deleted, nobody promoted
        admin_id = _id(ADMIN[0])
        r = client.post("/api/v1/users", json={"email": "x-admin@pratap-test.in", "name": "X Admin", "role": "admin", "password": "Str0ng!Passw0rd-x"}, headers=h)
        assert r.status_code == 403, r.text
        assert client.patch(f"/api/v1/users/{admin_id}", json={"name": "Hacked"}, headers=h).status_code == 403
        assert client.post(f"/api/v1/users/{admin_id}/delete", headers=h).status_code == 403
        # not their own role (no self-promotion)
        assert client.patch(f"/api/v1/users/{_id(VIEWER[0])}", json={"roleId": None}, headers=h).status_code == 403
        # viewers: created, edited, never promoted, deleted
        r = client.post("/api/v1/users", json={"email": "managed-user@pratap-test.in", "name": "Managed", "role": "viewer", "password": "Str0ng!Passw0rd-m"}, headers=h)
        assert r.status_code == 201, r.text
        new_id = r.json()["id"]
        assert client.patch(f"/api/v1/users/{new_id}", json={"name": "Managed 2"}, headers=h).status_code == 200
        assert client.patch(f"/api/v1/users/{new_id}", json={"role": "admin"}, headers=h).status_code == 403
        assert client.post(f"/api/v1/users/{new_id}/delete", headers=h).status_code == 200
        new_id = None
    finally:
        if new_id is not None:
            client.post(f"/api/v1/users/{new_id}/delete", headers=_h(client))
        _cleanup(client, rid)


# ---------------------------------------------------------------- circle limits (the areas of the user)
from app.security.core import hash_password  # noqa: E402

from .test_ticket_fe import fe_org  # noqa: E402, F401 - shared fixture
from .test_ticket_frt import _ticket, frt_org  # noqa: E402, F401
from .test_ticket_recipients import mail  # noqa: E402, F401
from .test_ticket_tasks import am_week  # noqa: E402, F401

MGR = ("circle-manager@pratap-test.in", "C1rcle!Secure-Pass")


def _manager(client, pages):
    """A viewer account with a role of these pages (removed by _drop_manager)."""
    h = _h(client)
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.email == MGR[0])).first() is None:
            db.add(User(email=MGR[0], name="Circle Manager", role="viewer", password_hash=hash_password(MGR[1])))
            db.commit()
    r = client.post("/api/v1/roles", json={"name": "Test Circle Manager Role", "pages": {**BASE, **pages}}, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.patch(f"/api/v1/users/{_id(MGR[0])}", json={"roleId": rid}, headers=h).status_code == 200
    return rid


def _areas(client, circle_ids):
    r = client.patch(f"/api/v1/users/{_id(MGR[0])}", json={"scopes": [{"level": "circle", "id": c} for c in circle_ids]}, headers=_h(client))
    assert r.status_code == 200, r.text


def _drop_manager(client, rid):
    h = _h(client)
    client.post(f"/api/v1/users/{_id(MGR[0])}/delete", headers=h)
    assert client.delete(f"/api/v1/roles/{rid}", headers=h).status_code == 200


def test_ticket_pages_follow_the_circles_of_the_areas(client, imported, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    circle, week = frt_org["circle"], frt_org["week"]
    g = imported.gps
    own_id = next(i for i, c in zip(g["circle_id"], g["circle"]) if str(c).title() == circle)
    other = next(((i, str(c).title()) for i, c in zip(g["circle_id"], g["circle"]) if str(c).title() != circle), None)
    rid = _manager(client, {"tickets-admin": ON, "tickets-report": ON})
    try:
        # the ticket's circle in the areas: the ticket, its report, filters and GPs
        _areas(client, [own_id])
        h = _h(client, MGR)
        assert tid in [t["id"] for t in client.get("/api/v1/tickets", params={"scope": "all", "page_size": 100}).json()["items"]]
        assert client.get(f"/api/v1/tickets/{tid}").status_code == 200
        assert client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()["total"] >= 1
        assert set(client.get("/api/v1/tickets/filter-options").json()["circles"]) == {circle}
        rep = client.get("/api/v1/tickets/report", params={"week": week}).json()
        assert rep["circles"] == [circle] and rep["cards"]["tickets"] >= 1
        assert client.get("/api/v1/tickets/report.xlsx", params={"week": week}).status_code == 200
        mon = client.get("/api/v1/tickets/gp-monitor/summary").json()
        assert mon["options"]["circles"] == [circle]
        assert [c["name"] for c in client.get("/api/v1/tickets/directory", params={"week": week}).json()["circles"]] == [circle]
        if other is None:
            return
        other_id, other_name = other
        assert client.get("/api/v1/tickets/directory", params={"circle": other_name, "week": week}).status_code == 403
        body = {"circle": other_name, "recipients": [], "subject": "Other circle", "description": "Not my circle at all.", "priority": "LOW", "assigneeId": _id(ADMIN[0])}
        assert client.post("/api/v1/tickets", json=body, headers=h).status_code == 403
        # another circle in the areas: nothing of this ticket – not listed, not opened, not closed / deleted
        _areas(client, [other_id])
        h = _h(client, MGR)
        assert tid not in [t["id"] for t in client.get("/api/v1/tickets", params={"scope": "all", "page_size": 100}).json()["items"]]
        assert client.get(f"/api/v1/tickets/{tid}").status_code == 404
        assert client.post(f"/api/v1/tickets/{tid}/close", json={"comment": "x"}, headers=h).status_code == 403
        assert client.request("DELETE", f"/api/v1/tickets/{tid}", json={"reason": "x"}, headers=h).status_code == 403
        assert circle not in client.get("/api/v1/tickets/filter-options").json()["circles"]
        rep = client.get("/api/v1/tickets/report", params={"week": week}).json()
        assert circle not in rep["circles"] and ((rep["cards"] or {}).get("tickets") or 0) == 0
        assert circle not in client.get("/api/v1/tickets/gp-monitor/summary").json()["options"]["circles"]
        # the admin: every circle, as before
        login(client)
        assert client.get(f"/api/v1/tickets/{tid}").status_code == 200
        assert circle in client.get("/api/v1/tickets/report", params={"week": week}).json()["circles"]
    finally:
        _drop_manager(client, rid)
