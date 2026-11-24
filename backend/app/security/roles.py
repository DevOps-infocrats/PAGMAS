"""Roles & Access – WHICH pages a dashboard user sees (WHICH data is their areas: app.security.access).

  admin (users.role = "admin")   every page, always (an admin can never lock itself out)
  viewer with role_id NULL       the built-in Viewer role (every page below – as before roles existed)
  viewer with a role             that role's pages; the same for every user of the role

A role lists, per page key, whether it shows on a laptop and on a phone, and the page each opens after sign-in.
Enforced on the server: the data endpoints of a page (analytics / field team) answer 403 to a role without that page
(require_page) – laptop or phone counts, the server cannot tell the device. The phone / laptop split and the hidden
menu entries are the dashboard's (frontend). Ticket and Non-Doable endpoints keep their own rules (only the tickets
a user is on), the role only shows / hides those pages. Admin Tickets, Ticket Report and User Management can be given
to a role (ADMIN_PAGES, off by default); Data Operations, Mail, Roles and Settings stay admin-only.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Role, User
from .deps import CurrentUser, get_current_user

# key, label, menu group – the dashboard pages a role can show (frontend: components/navigation/nav-config.ts pageKey)
PAGES: tuple[tuple[str, str, str], ...] = (
    ("overview", "Circle Overview", "Overview"),
    ("circle-insights", "Circle Insights", "Network Insights"),
    ("block-insights", "Block Insights", "Network Insights"),
    ("gp-insights", "GP Insights", "Network Insights"),
    ("amc-conversion", "AMC Conversion", "Field Operations"),
    ("field-team", "Field Team & Escalation", "Field Operations"),
    ("reports", "Management Review", "Reporting"),
    ("tickets-admin", "Admin Tickets", "Ticket Management"),
    ("tickets-report", "Ticket Report", "Ticket Management"),
    ("tickets-user", "User Tickets", "Ticket Management"),
    ("tickets-nondoable", "Non-Doable Cases", "Ticket Management"),
    ("users-admin", "User Management", "Administration"),
)
PAGE_KEYS = tuple(k for k, _l, _g in PAGES)
LABEL = {k: lbl for k, lbl, _g in PAGES}
# Admin pages a role may be given (off unless the admin switches them on – never part of "every page" of the Viewer):
#   Admin Tickets   = the user acts as an admin on tickets (every ticket, create / close / delete / review / e-mail)
#   Ticket Report   = the weekly ticket report (read-only + Excel)
#   User Management = add / edit / delete / import users – never an admin account, never their own role (no self-promotion)
# Data Operations, Roles & Access, Mail Configuration and Settings stay admin-only.
ADMIN_PAGES = ("tickets-admin", "tickets-report", "users-admin")

# The Circle Overview KPI drill-down list (/kpi-list) is opened from the overview and the insights pages
INSIGHTS = ("overview", "circle-insights", "block-insights", "gp-insights")


def _all(on: bool = True, admin_pages: bool = False) -> dict[str, dict[str, bool]]:
    """Every dashboard page; the admin pages only with admin_pages=True (an admin account)."""
    return {k: {"laptop": on and (admin_pages or k not in ADMIN_PAGES), "phone": on and (admin_pages or k not in ADMIN_PAGES)} for k in PAGE_KEYS}


def _only(laptop: tuple[str, ...], phone: tuple[str, ...]) -> dict[str, dict[str, bool]]:
    return {k: {"laptop": k in laptop, "phone": k in phone} for k in PAGE_KEYS}


TICKETS = ("tickets-user", "tickets-nondoable")
# Built-in roles: created once, then edited freely by the admin (never overwritten); not deletable
SYSTEM_ROLES: tuple[dict[str, Any], ...] = (
    {"key": "viewer", "name": "Viewer", "description": "Every dashboard page (the default of accounts without a role)", "pages": _all(), "laptop_home": "overview", "phone_home": "overview"},
    {
        "key": "am", "name": "AM", "description": "Area Manager – the data of their own areas",
        "pages": _only(("overview", "circle-insights", "block-insights", "gp-insights", "amc-conversion", "field-team", *TICKETS), TICKETS),
        "laptop_home": "overview", "phone_home": "tickets-user",
    },
    {"key": "fe", "name": "FE", "description": "Field Engineer – their tickets and GPs", "pages": _only(("gp-insights", *TICKETS), TICKETS), "laptop_home": "tickets-user", "phone_home": "tickets-user"},
    {"key": "frt", "name": "FRT", "description": "FRT team – the Daily Achievement of their GPs", "pages": _only(TICKETS, TICKETS), "laptop_home": "tickets-user", "phone_home": "tickets-user"},
)


def ensure_system_roles(db: Session) -> None:
    """Create the built-in roles that do not exist yet (start-up; an edited role is never changed)."""
    have = set(db.scalars(select(Role.key).where(Role.key.is_not(None))))
    taken = {n.lower() for n in db.scalars(select(Role.name))}
    added = False
    for r in SYSTEM_ROLES:
        if r["key"] in have:
            continue
        name = r["name"] if r["name"].lower() not in taken else f"{r['name']} (built-in)"
        db.add(Role(key=r["key"], name=name, description=r["description"], pages=json.dumps(r["pages"]), laptop_home=r["laptop_home"], phone_home=r["phone_home"], updated_by="System"))
        added = True
    if added:
        db.commit()


def parse_pages(raw: str | None) -> dict[str, dict[str, bool]]:
    """A role's pages (unknown keys dropped, missing pages = not shown)."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    out = {}
    for k in PAGE_KEYS:
        v = data.get(k) if isinstance(data, dict) else None
        out[k] = {"laptop": bool(isinstance(v, dict) and v.get("laptop")), "phone": bool(isinstance(v, dict) and v.get("phone"))}
    return out


def _role_of(db: Session, user: CurrentUser) -> Role | None:
    """The user's role row: their own, else the built-in Viewer (None = no Viewer row: every page, as before)."""
    rid = user.role_id if user.role_id is not None else db.scalar(select(User.role_id).where(User.id == user.id))
    if rid is not None:
        r = db.get(Role, rid)
        if r is not None:
            return r
    return db.scalars(select(Role).where(Role.key == "viewer")).first()


def permissions(db: Session, user: CurrentUser) -> dict[str, Any]:
    """What the dashboard shows this user: {"all": True} for admins, else the role's pages and home pages."""
    if user.is_admin:
        return {"all": True, "roleId": None, "roleName": "Admin", "pages": _all(admin_pages=True), "laptopHome": "overview", "phoneHome": "overview"}
    r = _role_of(db, user)
    if r is None:
        return {"all": False, "roleId": None, "roleName": "Viewer", "pages": _all(), "laptopHome": "overview", "phoneHome": "overview"}
    pages = parse_pages(r.pages)
    return {"all": False, "roleId": r.id, "roleName": r.name, "pages": pages, "laptopHome": r.laptop_home, "phoneHome": r.phone_home}


def can_open(db: Session, user: CurrentUser, keys: tuple[str, ...]) -> bool:
    if user.is_admin:
        return True
    pages = permissions(db, user)["pages"]
    return any(pages.get(k, {}).get("laptop") or pages.get(k, {}).get("phone") for k in keys)


def require_page(*keys: str):
    """Route dependency: the user's role shows at least one of these pages (laptop or phone) – else 403."""
    unknown = [k for k in keys if k not in PAGE_KEYS]
    if unknown:
        raise ValueError(f"Unknown page key(s): {unknown}")

    def dep(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> CurrentUser:
        if not can_open(db, user, keys):
            names = " / ".join(LABEL[k] for k in keys)
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role does not include this page ({names}). Please ask an administrator.")
        return user

    return dep


def users_per_role(db: Session) -> dict[int | None, int]:
    """Active + inactive viewer accounts per role id (None = no role = Viewer)."""
    rows = db.execute(select(User.role_id, func.count()).where(User.role != "admin").group_by(User.role_id)).all()
    return {rid: int(n) for rid, n in rows}


def circle_key(name: str | None) -> str:
    """A circle name compared case- and space-insensitively."""
    return " ".join(str(name or "").split()).lower()


def area_circles(db: Session, user: CurrentUser) -> frozenset[str] | None:
    """The circles of the user's areas (User Management; a BA / district / block / GP counts as its circle), as
    circle_key()s. None = no limit: an admin, or a user without areas (as on the dashboard). Areas no longer in the
    data give an empty set (nothing) – access is never widened."""
    if user.is_admin:
        return None
    from ..analytics.store import NoDataError, get_store, scoped_store
    from .access import user_areas

    areas = user_areas(db, user)
    if not areas:
        return None
    try:
        part = scoped_store(get_store(), areas)
    except NoDataError:
        return frozenset()
    if part is None:
        return frozenset()
    return frozenset(circle_key(c) for c in part.gps["circle"].unique())


def as_ticket_admin(db: Session, user: CurrentUser) -> CurrentUser:
    """Tickets: a user whose role shows Admin Tickets acts as an admin on tickets – limited to the circles of their
    areas (CurrentUser.circles)."""
    if user.is_admin or not can_open(db, user, ("tickets-admin",)):
        return user
    return replace(user, role="admin", circles=area_circles(db, user))
