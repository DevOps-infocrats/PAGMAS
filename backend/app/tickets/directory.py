"""Circle-wise people a ticket can be sent to (Generate Ticket → Circle → SME / COH / Area Manager).

All names, e-mails and the circle mapping come from the database, nothing is typed in here:
  CBH            Escalation Matrix "CBH Name" / CBH e-mail of the circle's GPs (older tickets, Area Manager sharing)
  SME            Escalation Matrix "SHQ SPOC" (the circle's SME) / its e-mail
  COH            Escalation Matrix "COH Name" / COH e-mail of the circle's GPs
  Area Manager   the same Area Manager list as the GP-wise task (tickets.task: Escalation Matrix, master data AM Name
                 when no matrix is uploaded) with the AM e-mail and the week's GP counts
  Field Engineer Escalation Matrix "FE Name" / "FE Email ID" under each Area Manager (tickets.task.fe_slots): one entry
                 per (Area Manager, FE name, FE e-mail of the rows) with the GPs mapped to it and the week's task GPs
A person is one name within a circle (case, spaces and punctuation ignored); a cell with several addresses
("a@x / b@y") gives several e-mails to choose from. Each e-mail says whether an active dashboard account has it –
only such a recipient sees the ticket in User Tickets; any other address receives the e-mail only.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.escalation import _active, is_vacant, person_key
from ..analytics.store import Store
from ..models import User

ROLE_COLUMNS = {"CBH": ("cbh_name", "cbh_email"), "SME": ("shq_name", "shq_email"), "COH": ("coh_name", "coh_email")}
ROLE_LABEL = {"CBH": "CBH", "SME": "SME", "COH": "COH", "AM": "Area Manager", "FE": "Field Engineer", "USER": "Dashboard user", "OTHER": "Other recipient"}


def _key(circle: str | None) -> str:
    return " ".join(str(circle or "").split()).lower()


def split_emails(v: Any) -> list[str]:
    if not isinstance(v, str):
        return []
    return [p.strip().lower() for p in v.replace(";", "/").replace(",", "/").split("/") if "@" in p]


def _users(db: Session) -> dict[str, User]:
    return {u.email.lower(): u for u in db.scalars(select(User).where(User.is_active.is_(True)))}


def _with_users(emails: list[str], users: dict[str, User]) -> list[dict[str, Any]]:
    out = []
    for e in emails:
        u = users.get(e)
        out.append({"email": e, "user": {"id": u.id, "name": u.name, "role": u.role} if u else None})
    return out


def circles(store: Store) -> list[dict[str, Any]]:
    """Circles of the master data (+ any only in the Escalation Matrix), with their GP counts."""
    counts: dict[str, int] = {}
    for c in store.gps["circle"]:
        if isinstance(c, str) and c.strip():
            counts[str(c).strip().title()] = counts.get(str(c).strip().title(), 0) + 1
    act = _active()
    if act is not None:
        for c in act[1]["circle"].dropna().unique():
            counts.setdefault(str(c).strip().title(), 0)
    return [{"name": k, "gps": v} for k, v in sorted(counts.items())]


def people(db: Session, role: str, circle: str) -> list[dict[str, Any]]:
    """CBH or SME people of a circle (Escalation Matrix) with their e-mails."""
    act = _active()
    if act is None:
        return []
    name_col, email_col = ROLE_COLUMNS[role]
    df = act[1]
    if name_col not in df.columns or email_col not in df.columns:
        return []
    df = df[[_key(c) == _key(circle) for c in df["circle"]]]
    found: dict[str, dict[str, Any]] = {}
    for name, mail in zip(df[name_col], df[email_col]):
        k = person_key(name)
        if not k or is_vacant(name) or str(name).strip() == "0":
            continue
        p = found.setdefault(k, {"name": " ".join(str(name).split()), "emails": {}, "gps": 0})
        p["gps"] += 1
        for e in split_emails(mail):
            p["emails"][e] = None
    users = _users(db)
    return sorted(({"name": p["name"], "gps": p["gps"], "emails": _with_users(list(p["emails"]), users)} for p in found.values()), key=lambda x: x["name"].lower())


def area_managers(db: Session, store: Store, circle: str, week: str, unmapped: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Area Managers of a circle (same names as the GP-wise task) with their e-mails and the week's GP counts
    (`unmappedFeGps` = the week's task GPs of the AM that have no Field Engineer in the Escalation Matrix)."""
    from . import task as tasks

    users = _users(db)
    out = []
    for a in tasks.area_managers(db, store, week)["areaManagers"]:
        if _key(circle) not in {_key(c) for c in a["circles"]}:
            continue
        mine = tasks.circle_counts(store, a["name"], circle, week)
        out.append(
            {
                "name": a["name"], "gps": mine["gps"], "weekGps": mine["weekGps"], "pendingGps": mine["pendingGps"], "businessAreas": a["businessAreas"],
                "emails": _with_users(a["emails"], users), "unmappedFeGps": (unmapped or {}).get(a["name"], 0),
            }
        )
    return out


def field_engineers(db: Session, store: Store, circle: str, week: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Field Engineers of a circle with their Area Manager, e-mails (matching dashboard accounts) and GP counts."""
    from . import task as tasks

    slots, unmapped = tasks.fe_slots(store, circle, week)
    users = _users(db)
    return [s | {"emails": _with_users(s["emails"], users)} for s in slots], unmapped


def directory(db: Session, store: Store, circle: str | None, week: str) -> dict[str, Any]:
    cs = circles(store)
    chosen = next((c["name"] for c in cs if _key(c["name"]) == _key(circle)), None) if circle else None
    has_matrix = _active() is not None
    fe, unmapped = field_engineers(db, store, chosen, week) if chosen else ([], {})
    return {
        "circles": cs,
        "circle": chosen,
        "week": week,
        "source": "escalation" if has_matrix else "master",
        "cbh": people(db, "CBH", chosen) if chosen else [],
        "sme": people(db, "SME", chosen) if chosen else [],
        "coh": people(db, "COH", chosen) if chosen else [],
        "am": area_managers(db, store, chosen, week, unmapped) if chosen else [],
        "fe": fe,
    }


def known_names(db: Session, store: Store, circle: str, week: str) -> dict[str, dict[str, list[str]]]:
    """role -> {name: e-mails} of the circle, to check what the admin selected really comes from the database."""
    d = directory(db, store, circle, week)
    return {role: {p["name"]: [e["email"] for e in p["emails"]] for p in d[key]} for role, key in (("CBH", "cbh"), ("SME", "sme"), ("COH", "coh"), ("AM", "am"))}
