"""Roles & Access (app.security.roles, app.api.roles): which pages a role shows; the same for every user of the role.

* built-in roles Viewer / AM / FE / FRT exist; they are edited, never deleted; "Admin" is not a role name;
* a viewer without a role sees every page (as before) – admins always see every page;
* a role's pages are enforced on the server (403 on the data endpoints of a page the role does not show) and take
  effect at once (no new sign-in); /auth/me hands the dashboard the pages and the laptop / phone start pages;
* a role with users cannot be deleted; only admins manage roles; ticket endpoints keep their own rules.
"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User

from .conftest import VIEWER, login


def _h(client, creds=None):
    return {"X-CSRF-Token": login(client, creds) if creds else login(client)}


def _viewer_id():
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == VIEWER[0])).one()


def _set_role(client, role_id):
    r = client.patch(f"/api/v1/users/{_viewer_id()}", json={"roleId": role_id}, headers=_h(client))
    assert r.status_code == 200, r.text
    return r.json()


PAGES_FE = {"gp-insights": {"laptop": True, "phone": False}, "tickets-user": {"laptop": True, "phone": True}, "tickets-nondoable": {"laptop": True, "phone": True}}
# no insights page at all (the overview's KPI drill-down list belongs to the overview and the insights pages)
PAGES_AMC = {"amc-conversion": {"laptop": True, "phone": False}, "tickets-user": {"laptop": True, "phone": True}, "tickets-nondoable": {"laptop": True, "phone": True}}


def test_builtin_roles_and_validation(client):
    h = _h(client)
    d = client.get("/api/v1/roles").json()
    assert {r["key"] for r in d["roles"] if r["system"]} >= {"viewer", "am", "fe", "frt"}
    assert [p["key"] for p in d["pages"]][:2] == ["overview", "circle-insights"] and d["admins"] >= 1
    fe = next(r for r in d["roles"] if r["key"] == "fe")
    assert fe["phoneHome"] == "tickets-user" and fe["pages"]["overview"] == {"laptop": False, "phone": False}
    # a built-in role is not deleted; names are unique; "Admin" is reserved; at least one page; valid start pages
    assert client.delete(f"/api/v1/roles/{fe['id']}", headers=h).status_code == 409
    assert client.post("/api/v1/roles", json={"name": "fe", "pages": PAGES_FE}, headers=h).status_code == 409
    assert client.post("/api/v1/roles", json={"name": "Admin", "pages": PAGES_FE}, headers=h).status_code == 409
    assert client.post("/api/v1/roles", json={"name": "Nothing", "pages": {}}, headers=h).status_code == 422
    assert client.post("/api/v1/roles", json={"name": "Bad page", "pages": {"mail": {"laptop": True}}}, headers=h).status_code == 422
    r = client.post("/api/v1/roles", json={"name": "Bad home", "pages": PAGES_FE, "phoneHome": "gp-insights"}, headers=h)
    assert r.status_code == 422 and "phone" in r.json()["detail"]
    # only admins manage roles
    hv = _h(client, VIEWER)
    assert client.get("/api/v1/roles").status_code == 403
    assert client.post("/api/v1/roles", json={"name": "Mine", "pages": PAGES_FE}, headers=hv).status_code == 403


def test_role_pages_are_enforced_and_follow_edits(client):
    h = _h(client)
    r = client.post("/api/v1/roles", json={"name": "Test Field Role", "description": "tickets + AMC", "pages": PAGES_AMC}, headers=h)
    assert r.status_code == 201, r.text
    role = r.json()
    assert role["laptopHome"] == "amc-conversion" and role["phoneHome"] == "tickets-user" and role["system"] is False
    try:
        # no role: every page (as before)
        login(client, VIEWER)
        me = client.get("/api/v1/auth/me").json()
        assert me["permissions"]["roleName"] == "Viewer" and me["permissions"]["pages"]["overview"]["laptop"] is True
        assert client.get("/api/v1/overview").status_code != 403
        # the role: only its pages – on the server too
        u = _set_role(client, role["id"])
        assert u["roleId"] == role["id"] and u["roleName"] == "Test Field Role"
        login(client, VIEWER)
        p = client.get("/api/v1/auth/me").json()["permissions"]
        assert p["roleName"] == "Test Field Role" and p["phoneHome"] == "tickets-user" and p["pages"]["overview"] == {"laptop": False, "phone": False}
        for url in ("/api/v1/overview", "/api/v1/circles/haryana/insights", "/api/v1/blocks/hr-1/insights", "/api/v1/kpi-lists/gps-at-zero",
                    "/api/v1/gps", "/api/v1/gps/12345", "/api/v1/reviews/management", "/api/v1/reports/weekly", "/api/v1/field-team/summary"):
            r = client.get(url)
            assert r.status_code == 403 and "role" in r.json()["detail"], url
        assert client.get("/api/v1/amc-plan/summary").status_code != 403  # AMC Conversion is in the role
        assert client.get("/api/v1/meta").status_code != 403 and client.get("/api/v1/tickets/notifications").status_code == 200  # shared
        # an admin edit applies at once (no new sign-in): GP Insights on the laptop – its list, and the KPI drill-down
        h = _h(client)
        r = client.patch(f"/api/v1/roles/{role['id']}", json={"pages": {**PAGES_AMC, "gp-insights": {"laptop": True, "phone": False}}, "laptopHome": "gp-insights"}, headers=h)
        assert r.status_code == 200 and r.json()["users"] == 1 and r.json()["laptopHome"] == "gp-insights"
        login(client, VIEWER)
        assert client.get("/api/v1/gps").status_code != 403
        assert client.get("/api/v1/kpi-lists/gps-at-zero").status_code != 403
        assert client.get("/api/v1/field-team/summary").status_code == 403  # still not in the role
        # removing a page moves a start page that is no longer shown
        h = _h(client)
        r = client.patch(f"/api/v1/roles/{role['id']}", json={"pages": PAGES_AMC}, headers=h)
        assert r.json()["laptopHome"] == "amc-conversion"
        # a role with users is not deleted
        assert client.delete(f"/api/v1/roles/{role['id']}", headers=h).status_code == 409
    finally:
        _set_role(client, None)  # the shared viewer account back to the built-in Viewer role
    h = _h(client)
    assert client.delete(f"/api/v1/roles/{role['id']}", headers=h).status_code == 200
    login(client, VIEWER)
    assert client.get("/api/v1/auth/me").json()["permissions"]["roleName"] == "Viewer"


def test_admin_always_sees_everything_and_has_no_role(client):
    h = _h(client)
    fe = next(r for r in client.get("/api/v1/roles").json()["roles"] if r["key"] == "fe")
    me = client.get("/api/v1/auth/me").json()["permissions"]
    assert me["all"] is True and me["roleName"] == "Admin"
    # an admin account keeps no access role (roleId ignored)
    users = client.get("/api/v1/users").json()
    admin = next(u for u in users if u["role"] == "admin")
    r = client.patch(f"/api/v1/users/{admin['id']}", json={"roleId": fe["id"]}, headers=h)
    assert r.status_code == 200 and r.json()["roleId"] is None and r.json()["roleName"] == "Admin"
    assert client.get("/api/v1/overview").status_code != 403
    # an unknown role is refused
    assert client.patch(f"/api/v1/users/{_viewer_id()}", json={"roleId": 999999}, headers=h).status_code == 422
