"""Ticket hierarchy: AM ticket -> FE tickets -> FRT (GP-wise) tickets.

The AM ticket is the existing GP-wise task ticket (tickets row, TKT-000123) and keeps its own status, rules and
history unchanged. Under it:

  FE ticket   TKT-000123-FE-01            one per Field Engineer on the ticket (ticket_recipients role FE)
  FRT ticket  TKT-000123-FE-01-FRT-001    one per GP row with an FRT team (ticket_task_gps.frt_code), under the FE
              TKT-000123-FRT-001          ticket of the GP's FE – or directly under the AM ticket (GP without an FE ticket)

IDs are built on the backend from the parent's ID and a running number per parent, under a lock on the AM ticket
row; the unique constraints (code, ticket + level + key, task_gp_id) make a duplicate impossible. An ID never
changes – a GP reassigned to another FE keeps its FRT ID, only the parent link moves (history: MOVED).

Every unit has its own status and history; NO status is ever copied up or down:

  FRT ticket  follows ITS GP's FE step (decided with the business): the FRT's Daily Achievement waiting for the FE =
              Pending FE Verification; returned by the FE = In Progress (reopened if it was closed); verified by the
              FE = Closed. A GP the FE (or the AM) reported itself and sent on to the AM (FRT without a login) is
              Closed the same way. Nothing else reopens a closed FRT ticket.
  FE ticket   In Progress once the FE works on the ticket (their own Daily Achievement / verification / review
              step). Closed only by the ticket's Area Manager (close_fe) – once the AM has reviewed the FE's GPs, or
              with a written reason. Closing it never closes the AM ticket or the FRT tickets.
  AM ticket   unchanged (Admin closes it, app.tickets.service.close); closing it changes no FE / FRT ticket.

Units are kept in step by a Session hook: every commit that touched a ticket (a GP, a progress line, a review step,
a recipient …) re-checks that ticket's units in the same transaction. A failure in the hook is logged and never
blocks the existing workflow.
"""

from __future__ import annotations

import datetime as dt
import logging
from itertools import chain
from typing import Any

from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session

from ..models import (
    NdEvent,
    Ticket,
    TicketEvent,
    TicketGpReview,
    TicketProgress,
    TicketProgressLine,
    TicketRecipient,
    TicketTask,
    TicketTaskGp,
    TicketUnit,
    TicketUnitEvent,
)

log = logging.getLogger(__name__)

LEVELS = ("AM", "FE", "FRT")
STATUSES = ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CLOSED")
STATUS_LABEL = {"OPEN": "Open", "IN_PROGRESS": "In Progress", "PENDING_REVIEW": "Pending FE Verification", "CLOSED": "Closed"}
MIN_FORCE_REMARK = 10


class UnitError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(v: dt.datetime | None) -> str | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).isoformat()


# ---------------------------------------------------------------- keys and IDs


def fe_unit_key(name: Any, mail: Any) -> str:
    from .task import fe_key

    n, m = fe_key(name, mail)
    return f"fe:{n}|{m}"[:420]


def gp_unit_key(task_gp_id: int) -> str:
    return f"gp:{task_gp_id}"


def fe_code(ticket_code: str, seq: int) -> str:
    return f"{ticket_code}-FE-{seq:02d}"


def frt_code_of(parent_code: str, seq: int) -> str:
    return f"{parent_code}-FRT-{seq:03d}"


# ---------------------------------------------------------------- keeping the units in step


def _actor(db: Session) -> tuple[int | None, str]:
    a = db.info.get("actor")
    return (a[0], a[1]) if a else (None, "System")


def _log(db: Session, u: TicketUnit, action: str, frm: str | None, to: str | None, note: str | None = None, actor: tuple[int | None, str] | None = None, at: dt.datetime | None = None) -> None:
    aid, aname = actor or _actor(db)
    db.add(TicketUnitEvent(unit_id=u.id, at=at or now(), actor_id=aid, actor_name=aname, action=action, from_status=frm, to_status=to, note=note))


def _set_status(db: Session, u: TicketUnit, to: str, action: str, note: str | None = None, actor: tuple[int | None, str] | None = None) -> None:
    frm = u.status
    if frm == to:
        return
    at = now()
    u.status, u.updated_at = to, at
    if to == "CLOSED":
        aid, aname = actor or _actor(db)
        u.closed_at, u.closed_by_id, u.closed_by_name = at, aid, aname
    elif frm == "CLOSED":
        u.closed_at = u.closed_by_id = u.closed_by_name = None
    if to != "OPEN" and u.started_at is None:
        u.started_at = at
    _log(db, u, action, frm, to, note, actor)


def frt_status(g: TicketTaskGp, current: str, active: bool) -> tuple[str, str, str | None]:
    """(status, history action, note) of the FRT ticket of GP `g` – see the module docstring."""
    from .review import AM_REVIEWED, stage_of

    if g.frt_stage == "FE_VERIFIED":
        return "CLOSED", "CLOSED", "Verified by the FE"
    if g.frt_stage == "PENDING_FE":
        return "PENDING_REVIEW", "SUBMITTED", "Daily Achievement submitted – waiting for the FE to verify"
    if g.frt_stage == "RETURNED_FRT":
        return "IN_PROGRESS", ("REOPENED" if current == "CLOSED" else "RETURNED"), "Returned to the FRT by the FE"
    # no FRT step on the GP: the FE (or the AM) reported it – it passed the FE once it is with the AM or beyond
    if stage_of(g) == "PENDING_AM" or g.review in AM_REVIEWED or g.review == "SME_RETURNED":
        return "CLOSED", "CLOSED", "Reported by the FE / AM and sent to the Area Manager"
    if current == "CLOSED":
        return "CLOSED", "CLOSED", None  # only the FRT step (returned by the FE) reopens a closed FRT ticket
    if active or current == "IN_PROGRESS":
        return "IN_PROGRESS", "STARTED", "Work started on the GP"
    return "OPEN", "CREATED", None


def sync(db: Session, ticket_id: int) -> None:
    """Create the missing FE / FRT tickets of one AM ticket, re-link moved GPs and bring every FRT / FE status in line
    with what happened on the ticket. Idempotent; only units are written."""
    from .task import FeScope, frt_norm

    t = db.get(Ticket, ticket_id)
    if t is None or not t.code or db.get(TicketTask, ticket_id) is None:
        return  # a normal ticket (no GP-wise task) has no hierarchy
    # one writer per AM ticket at a time: the running numbers are taken under this lock (PostgreSQL; SQLite writes
    # one transaction at a time anyway)
    db.execute(select(Ticket.id).where(Ticket.id == ticket_id).with_for_update())
    units = list(db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == ticket_id)))
    by_key = {(u.level, u.unit_key): u for u in units}
    codes = {u.code for u in units}

    def next_id(level: str, parent_id: int | None, prefix: str) -> tuple[int, str]:
        """The next running number under this parent whose ID is still free (a GP moved to another FE keeps its ID,
        so the number after the highest one is taken, skipping any ID that already exists)."""
        seq = max((u.seq for u in units if u.level == level and (level == "FE" or u.parent_id == parent_id)), default=0) + 1
        while (code := (fe_code(prefix, seq) if level == "FE" else frt_code_of(prefix, seq))) in codes:
            seq += 1
        return seq, code

    def add(u: TicketUnit, note: str) -> TicketUnit:
        db.add(u)
        db.flush()
        units.append(u)
        codes.add(u.code)
        by_key[(u.level, u.unit_key)] = u
        _log(db, u, "CREATED", None, u.status, note)
        return u

    # FE tickets: every Field Engineer the AM ticket went to
    fes = list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == ticket_id, TicketRecipient.role == "FE").order_by(TicketRecipient.id)))
    fe_unit_of: dict[str, TicketUnit] = {}
    for r in fes:
        key = fe_unit_key(r.name, r.fe_mail)
        u = by_key.get(("FE", key))
        if u is None:
            seq, code = next_id("FE", None, t.code)
            u = add(TicketUnit(ticket_id=ticket_id, level="FE", parent_id=None, seq=seq, code=code, unit_key=key, recipient_id=r.id,
                               fe_name=r.name, fe_email=r.fe_mail, status="OPEN", created_at=now(), updated_at=now()), f"FE ticket of {r.name} under {t.code}")
        fe_unit_of[key] = u

    # FRT tickets: every GP row with an FRT team, under its FE's ticket
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == ticket_id).order_by(TicketTaskGp.sort, TicketTaskGp.id)))
    worked = set(db.scalars(select(TicketProgressLine.task_gp_id).join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id).where(TicketProgress.ticket_id == ticket_id)))
    for g in gps:
        code = frt_norm(g.frt_code)
        if not code:
            continue
        parent = next((fu for key, fu in fe_unit_of.items() if fu.fe_name is not None and FeScope(fu.fe_name, fu.fe_email).owns(g)), None)
        pid = parent.id if parent is not None else None
        u = by_key.get(("FRT", gp_unit_key(g.id)))
        if u is None:
            seq, uid_code = next_id("FRT", pid, parent.code if parent is not None else t.code)
            u = add(TicketUnit(ticket_id=ticket_id, level="FRT", parent_id=pid, seq=seq, code=uid_code,
                               unit_key=gp_unit_key(g.id), task_gp_id=g.id, frt_code=code, fe_name=g.fe_name, fe_email=g.fe_email, status="OPEN",
                               created_at=now(), updated_at=now()), f"FRT ticket of GP {g.gp_code} (FRT {code})")
        elif u.parent_id != pid:
            old = next((x.code for x in units if x.id == u.parent_id), t.code)
            u.parent_id, u.fe_name, u.fe_email, u.updated_at = pid, g.fe_name, g.fe_email, now()
            _log(db, u, "MOVED", u.status, u.status, f"GP moved from {old} to {parent.code if parent is not None else t.code} (the ticket ID stays {u.code})")
        status, action, note = frt_status(g, u.status, g.id in worked or g.gp_category is not None or g.review is not None)
        if status != u.status:
            _set_status(db, u, status, action, note)

    # FE tickets: In Progress once the FE themselves worked on the ticket (never because of an FRT ticket)
    acted: set[int] = set()
    for q in (
        select(TicketProgress.submitted_by_id).where(TicketProgress.ticket_id == ticket_id),
        select(TicketGpReview.actor_id).where(TicketGpReview.ticket_id == ticket_id),
        select(NdEvent.actor_id).where(NdEvent.ticket_id == ticket_id),
        select(TicketEvent.actor_id).where(TicketEvent.ticket_id == ticket_id, TicketEvent.action == "STARTED"),
    ):
        acted |= {x for x in db.scalars(q) if x is not None}
    by_id = {r.id: r for r in fes}
    for u in units:
        if u.level != "FE" or u.status != "OPEN":
            continue
        r = by_id.get(u.recipient_id) if u.recipient_id else None
        if r is not None and r.user_id is not None and r.user_id in acted:
            _set_status(db, u, "IN_PROGRESS", "STARTED", f"{r.name} started working on the ticket", actor=(r.user_id, r.name))


def backfill(db: Session) -> int:
    """Start-up: the FE / FRT tickets of every live GP-wise task ticket (new rows only). Returns the tickets checked."""
    ids = list(db.scalars(select(TicketTask.ticket_id).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None)).order_by(TicketTask.ticket_id)))
    for tid in ids:
        try:
            sync(db, tid)
            db.commit()
        except Exception:  # never block the start-up of the API
            db.rollback()
            log.exception("ticket hierarchy: backfill of ticket %s failed", tid)
    return len(ids)


@event.listens_for(Session, "after_flush")
def _mark_tickets(session: Session, _ctx: Any) -> None:
    if session.info.get("units_syncing"):
        return
    ids = session.info.setdefault("unit_tickets", set())
    for obj in chain(session.new, session.dirty):
        if isinstance(obj, (TicketUnit, TicketUnitEvent)):
            continue
        tid = obj.id if isinstance(obj, Ticket) else getattr(obj, "ticket_id", None)
        if isinstance(tid, int):
            ids.add(tid)


@event.listens_for(Session, "before_commit")
def _sync_tickets(session: Session) -> None:
    if session.info.get("units_syncing"):
        return
    session.flush()  # the last changes of the transaction mark their tickets (after_flush)
    ids = session.info.pop("unit_tickets", None)
    if not ids:
        return
    from ..db import is_postgres

    session.info["units_syncing"] = True
    try:
        for tid in sorted(ids):
            # PostgreSQL: in a savepoint, so a failing sync is undone alone and the transaction (the user's action)
            # still commits; SQLite (tests / local fallback) runs it directly
            sp = session.begin_nested() if is_postgres() else None
            try:
                sync(session, tid)
                session.flush()
                if sp is not None:
                    sp.commit()
            except Exception:  # the hierarchy must never block the existing workflow
                if sp is not None and sp.is_active:
                    sp.rollback()
                log.exception("ticket hierarchy: sync of ticket %s failed", tid)
    finally:
        session.info.pop("units_syncing", None)


@event.listens_for(Session, "after_rollback")
def _forget(session: Session) -> None:
    session.info.pop("unit_tickets", None)


# ---------------------------------------------------------------- who may see / act


def _visible_units(db: Session, t: Ticket, user: Any, units: list[TicketUnit]) -> list[TicketUnit]:
    """The units of this AM ticket the user may see: the whole tree for an admin of the ticket, its Area Manager and
    anybody who sees the whole ticket; an FE their FE ticket and its FRT tickets; an FRT team their FRT tickets; an SME
    / COH the FRT tickets of the GPs handed to them."""
    from .service import admin_of
    from .task import FeScope, FrtScope, ReviewerView, view_of

    if admin_of(db, t, user):
        return units
    scope = view_of(db, t, user)
    if scope is None:
        return units
    gp_ids = {u.task_gp_id for u in units if u.task_gp_id}
    gps = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_(gp_ids)))} if gp_ids else {}
    if isinstance(scope, FeScope):
        mine = {u.id for u in units if u.level == "FE" and u.unit_key == fe_unit_key(scope.name, scope.mail)}
        return [u for u in units if u.id in mine or (u.level == "FRT" and (u.parent_id in mine or scope.owns(gps.get(u.task_gp_id))))]
    if isinstance(scope, (FrtScope, ReviewerView)):
        return [u for u in units if u.level == "FRT" and scope.owns(gps.get(u.task_gp_id))]
    return []


def is_area_manager(db: Session, t: Ticket, user: Any) -> bool:
    """The ticket's Area Manager: the assigned user, or the AM recipient allowed to work on it."""
    if t.assignee_id == user.id:
        return True
    return db.scalar(select(TicketRecipient.id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id, TicketRecipient.role == "AM", TicketRecipient.can_work.is_(True)).limit(1)) is not None


def _fe_gps(db: Session, u: TicketUnit) -> list[TicketTaskGp]:
    from .task import FeScope

    sc = FeScope(u.fe_name or "", u.fe_email)
    return [g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == u.ticket_id)) if sc.owns(g)]


def close_fe(db: Session, t: Ticket, unit_id: int, user: Any, remark: str | None, force: bool = False) -> TicketUnit:
    """The Area Manager closes one FE ticket of their AM ticket. Same SOP rule as the Admin's close of the AM ticket:
    every GP of the FE reviewed by the AM (or achieved at assignment), otherwise only with a written reason. Changes
    nothing else – not the AM ticket, not the FRT tickets, not the GPs."""
    from .review import AM_REVIEWED
    from .task import cumulative

    u = db.get(TicketUnit, unit_id)
    if u is None or u.ticket_id != t.id or u.level != "FE":
        raise UnitError(404, "FE ticket not found on this ticket")
    if not is_area_manager(db, t, user):
        raise UnitError(403, "Only the ticket's Area Manager can close an FE ticket")
    if u.status == "CLOSED":
        raise UnitError(409, f"{u.code} is already closed")
    note = " ".join((remark or "").split()) or None
    open_gps = [g for g in _fe_gps(db, u) if g.review not in AM_REVIEWED and cumulative(g) < g.target]
    if open_gps:
        what = f"{len(open_gps)} GP{'s' if len(open_gps) != 1 else ''} of {u.fe_name} {'are' if len(open_gps) != 1 else 'is'} not yet approved by you (the Area Manager)"
        if not force:
            raise UnitError(409, f"{what}. Close after approving them, or close anyway with a written reason.")
        if note is None or len(note) < MIN_FORCE_REMARK:
            raise UnitError(422, f"Write the reason for closing without approving every GP (at least {MIN_FORCE_REMARK} characters)")
        note = f"Closed with {len(open_gps)} GP{'s' if len(open_gps) != 1 else ''} not approved – reason: {note}"
    frm = u.status
    at = now()
    res = db.execute(
        update(TicketUnit).where(TicketUnit.id == u.id, TicketUnit.status != "CLOSED")
        .values(status="CLOSED", updated_at=at, closed_at=at, closed_by_id=user.id, closed_by_name=user.name, close_remark=note, started_at=func.coalesce(TicketUnit.started_at, at))
    )
    if res.rowcount != 1:
        db.rollback()
        raise UnitError(409, f"{u.code} was closed meanwhile – reload")
    _log(db, u, "CLOSED", frm, "CLOSED", note or "Closed by the Area Manager", actor=(user.id, user.name), at=at)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------- JSON


def unit_json(u: TicketUnit, t: Ticket, task: TicketTask | None, parent: TicketUnit | None, g: TicketTaskGp | None) -> dict[str, Any]:
    return {
        "id": u.id, "level": u.level, "code": u.code, "ticketId": t.id, "amCode": t.code, "parentCode": parent.code if parent is not None else t.code,
        "parentId": u.parent_id, "status": u.status, "statusLabel": STATUS_LABEL.get(u.status, u.status),
        "am": task.am_name if task else t.assignee_name, "fe": u.fe_name, "frt": u.frt_code,
        "gpId": g.id if g is not None else None, "gpCode": g.gp_code if g is not None else None, "gpName": g.gp_name if g is not None else None,
        "block": g.block if g is not None else None, "circle": (g.circle if g is not None else None) or t.circle, "week": task.week_code if task else None,
        "createdAt": iso(u.created_at), "updatedAt": iso(u.updated_at), "startedAt": iso(u.started_at), "closedAt": iso(u.closed_at),
        "closedBy": u.closed_by_name, "closeRemark": u.close_remark,
    }


def am_json(t: Ticket, task: TicketTask | None) -> dict[str, Any]:
    from .service import STATUS_LABEL as TICKET_LABEL

    return {
        "id": t.id, "level": "AM", "code": t.code, "ticketId": t.id, "amCode": t.code, "parentCode": None, "parentId": None,
        "status": t.status, "statusLabel": TICKET_LABEL.get(t.status, t.status), "am": task.am_name if task else t.assignee_name, "fe": None, "frt": None,
        "gpId": None, "gpCode": None, "gpName": None, "block": None, "circle": t.circle, "week": task.week_code if task else None,
        "createdAt": iso(t.created_at), "updatedAt": iso(t.updated_at), "startedAt": iso(t.started_at), "closedAt": iso(t.closed_at),
        "closedBy": t.closed_by_name, "closeRemark": None,
    }


def _context(db: Session, ticket_ids: list[int]) -> tuple[dict[int, Ticket], dict[int, TicketTask], list[TicketUnit], dict[int, TicketTaskGp]]:
    tickets = {t.id: t for t in db.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids)))} if ticket_ids else {}
    tasks = {k.ticket_id: k for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_(ticket_ids)))} if ticket_ids else {}
    units = list(db.scalars(select(TicketUnit).where(TicketUnit.ticket_id.in_(ticket_ids)).order_by(TicketUnit.ticket_id, TicketUnit.level, TicketUnit.parent_id, TicketUnit.seq))) if ticket_ids else []
    gp_ids = [u.task_gp_id for u in units if u.task_gp_id]
    gps = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_(gp_ids)))} if gp_ids else {}
    return tickets, tasks, units, gps


def tree(db: Session, t: Ticket, user: Any) -> dict[str, Any]:
    """One AM ticket with the FE tickets under it and the FRT tickets under each FE ticket (what this user may see)."""
    tickets, tasks, units, gps = _context(db, [t.id])
    task = tasks.get(t.id)
    seen = _visible_units(db, t, user, units)
    by_id = {u.id: u for u in units}
    out_fe = []
    for u in (x for x in seen if x.level == "FE"):
        kids = [unit_json(c, t, task, u, gps.get(c.task_gp_id)) for c in seen if c.level == "FRT" and c.parent_id == u.id]
        out_fe.append(unit_json(u, t, task, None, None) | {"frt": kids, "counts": _counts(kids)})
    direct = [unit_json(c, t, task, by_id.get(c.parent_id) if c.parent_id else None, gps.get(c.task_gp_id))
              for c in seen if c.level == "FRT" and (c.parent_id is None or c.parent_id not in {f.id for f in seen if f.level == "FE"})]
    return {
        "ticket": am_json(t, task) | {"hasTask": task is not None},
        "fe": out_fe,
        "frtDirect": direct,
        "canCloseFe": task is not None and is_area_manager(db, t, user),
    }


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    c = {s: 0 for s in STATUSES}
    for x in items:
        c[x["status"]] = c.get(x["status"], 0) + 1
    return c | {"total": len(items)}


def history(db: Session, u: TicketUnit) -> list[dict[str, Any]]:
    return [
        {"at": iso(e.at), "by": e.actor_name, "action": e.action, "from": e.from_status, "to": e.to_status, "note": e.note}
        for e in db.scalars(select(TicketUnitEvent).where(TicketUnitEvent.unit_id == u.id).order_by(TicketUnitEvent.at, TicketUnitEvent.id))
    ]


def detail(db: Session, t: Ticket, unit_id: int, user: Any) -> dict[str, Any]:
    tickets, tasks, units, gps = _context(db, [t.id])
    u = next((x for x in _visible_units(db, t, user, units) if x.id == unit_id), None)
    if u is None:
        raise UnitError(404, "Ticket not found")
    parent = next((x for x in units if x.id == u.parent_id), None)
    out = unit_json(u, t, tasks.get(t.id), parent, gps.get(u.task_gp_id)) | {"history": history(db, u)}
    if u.level == "FE":
        out["frtTickets"] = [unit_json(c, t, tasks.get(t.id), u, gps.get(c.task_gp_id)) for c in units if c.level == "FRT" and c.parent_id == u.id]
        out["canClose"] = u.status != "CLOSED" and is_area_manager(db, t, user)
    if u.level == "FRT" and (g := gps.get(u.task_gp_id)) is not None:
        from .review import stage_label, stage_of

        out["gpStage"] = stage_label(stage_of(g))
    return out


def _brief(u: TicketUnit) -> dict[str, Any]:
    return {"id": u.id, "code": u.code, "level": u.level, "status": u.status, "statusLabel": STATUS_LABEL.get(u.status, u.status)}


def my_units(db: Session, user_id: int, ticket_ids) -> dict[int, dict[str, Any]]:
    """The signed-in user's OWN ticket under each AM ticket (shown instead of the AM ticket's ID in their lists and
    header): an FE their FE ticket; an FRT team the FRT tickets of their GPs (how many, how many still open, the IDs).
    Tickets where the user is neither FE nor FRT are not in the result (they keep the AM ticket's ID). Read only."""
    from .task import frt_norm

    ids = list(ticket_ids)
    if not ids:
        return {}
    recs = list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(ids), TicketRecipient.user_id == user_id, TicketRecipient.role.in_(("FE", "FRT")))))
    if not recs:
        return {}
    out: dict[int, dict[str, Any]] = {}
    fe_rec = {r.id: r for r in recs if r.role == "FE"}
    if fe_rec:
        for u in db.scalars(select(TicketUnit).where(TicketUnit.level == "FE", TicketUnit.recipient_id.in_(list(fe_rec)))):
            out[u.ticket_id] = _brief(u) | {"count": 1, "open": int(u.status != "CLOSED"), "codes": [u.code]}
    frt_of: dict[int, set[str]] = {}
    for r in recs:
        if r.role == "FRT" and r.ticket_id not in out and (c := frt_norm(r.frt_code)):
            frt_of.setdefault(r.ticket_id, set()).add(c)
    if frt_of:
        rows = db.scalars(select(TicketUnit).where(TicketUnit.level == "FRT", TicketUnit.ticket_id.in_(list(frt_of))).order_by(TicketUnit.code))
        mine: dict[int, list[TicketUnit]] = {}
        for u in rows:
            if u.frt_code in frt_of.get(u.ticket_id, set()):
                mine.setdefault(u.ticket_id, []).append(u)
        for tid, us in mine.items():
            first = next((u for u in us if u.status != "CLOSED"), us[0])
            out[tid] = _brief(first) | {"count": len(us), "open": sum(1 for u in us if u.status != "CLOSED"), "codes": [u.code for u in us]}
    return out


def gp_units(db: Session, t: Ticket, user: Any) -> dict[int, dict[str, Any]]:
    """GP row id -> its FRT ticket (ID and status), only those this user may see (the GP tables of the ticket)."""
    us = list(db.scalars(select(TicketUnit).where(TicketUnit.ticket_id == t.id, TicketUnit.level == "FRT")))
    if not us:
        return {}
    return {u.task_gp_id: _brief(u) for u in _visible_units(db, t, user, us) if u.task_gp_id}


AM_ACTIVE = ("IN_PROGRESS", "PENDING_REVIEW", "CHANGES_REQUESTED")  # AM ticket: work started, not closed
UNIT_ACTIVE = ("IN_PROGRESS", "PENDING_REVIEW")  # FE / FRT ticket: work started, not closed


def in_progress(db: Session, ticket_ids) -> list[dict[str, Any]]:
    """Admin Tickets – "Tickets in Progress": exactly the tickets the KPI card counts – AM tickets In Progress / Pending
    Review / Changes Requested and FE / FRT tickets In Progress / Pending FE Verification – under these AM tickets.
    AM first, then FE, then FRT; latest activity first within a level. Read only."""
    ids = list(ticket_ids)
    if not ids:
        return []
    tickets, tasks, units, gps = _context(db, ids)
    by_id = {u.id: u for u in units}
    rows = [am_json(t, tasks.get(t.id)) for t in tickets.values() if t.status in AM_ACTIVE]
    rows += [unit_json(u, tickets[u.ticket_id], tasks.get(u.ticket_id), by_id.get(u.parent_id) if u.parent_id else None, gps.get(u.task_gp_id))
             for u in units if u.status in UNIT_ACTIVE and u.ticket_id in tickets]
    order = {lv: i for i, lv in enumerate(LEVELS)}
    rows.sort(key=lambda r: r["updatedAt"] or "", reverse=True)
    rows.sort(key=lambda r: order[r["level"]])  # stable: latest first within each level
    return rows


def level_counts(db: Session, ticket_ids) -> dict[str, dict[str, int]]:
    """Admin Tickets KPIs: the FE and FRT tickets under these AM tickets, per status (each ticket once). Read only."""
    ids = list(ticket_ids)
    out = {lv: {s: 0 for s in STATUSES} | {"total": 0} for lv in ("FE", "FRT")}
    if not ids:
        return out
    for level, status, n in db.execute(
        select(TicketUnit.level, TicketUnit.status, func.count()).where(TicketUnit.ticket_id.in_(ids)).group_by(TicketUnit.level, TicketUnit.status)
    ):
        if level in out:
            out[level][status] = out[level].get(status, 0) + n
            out[level]["total"] += n
    return out


# ---------------------------------------------------------------- Admin: every ticket of every level


def _match(text: str | None, term: str) -> bool:
    return term in (text or "").lower()


def listing(db: Session, circles: frozenset[str] | None, f: dict[str, Any], page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Admin: AM, FE and FRT tickets in one list – filters: level, status, search (any ticket ID, AM / FE / FRT / GP),
    am, fe, frt, gp, circle, week, dateFrom / dateTo (the AM ticket's generation day). Counts per level and status
    are of the filtered tickets (each ticket once; parent and child are never added together)."""
    from .service import _local_day_start, in_circles, live

    q = select(Ticket.id).join(TicketTask, TicketTask.ticket_id == Ticket.id).where(live())
    if circles is not None:
        q = q.where(in_circles(circles))
    if f.get("date_from"):
        q = q.where(Ticket.created_at >= _local_day_start(f["date_from"]))
    if f.get("date_to"):
        q = q.where(Ticket.created_at < _local_day_start(f["date_to"] + dt.timedelta(days=1)))
    if f.get("week"):
        q = q.where(TicketTask.week_code == f["week"])
    ids = list(db.scalars(q))
    tickets, tasks, units, gps = _context(db, ids)
    by_id = {u.id: u for u in units}
    rows: list[dict[str, Any]] = [am_json(tickets[i], tasks.get(i)) for i in ids if i in tickets]
    for u in units:
        t = tickets.get(u.ticket_id)
        if t is not None:
            rows.append(unit_json(u, t, tasks.get(u.ticket_id), by_id.get(u.parent_id) if u.parent_id else None, gps.get(u.task_gp_id)))
    # children per AM / FE ticket (for the drill-down)
    kids: dict[tuple[str, int], dict[str, int]] = {}
    for u in units:
        kids.setdefault(("AM", u.ticket_id), {"fe": 0, "frt": 0, "open": 0})[u.level.lower()] += 1
        if u.level == "FRT" and u.parent_id:
            kids.setdefault(("FE", u.parent_id), {"fe": 0, "frt": 0, "open": 0})["frt"] += 1
        if u.status != "CLOSED":
            kids[("AM", u.ticket_id)]["open"] += 1
            if u.level == "FRT" and u.parent_id:
                kids[("FE", u.parent_id)]["open"] += 1
    for r in rows:
        r["children"] = kids.get((r["level"], r["id"]), {"fe": 0, "frt": 0, "open": 0})

    def keep(r: dict[str, Any]) -> bool:
        if (s := (f.get("search") or "").strip().lower()) and not any(_match(r.get(k), s) for k in ("code", "amCode", "parentCode", "am", "fe", "frt", "gpCode", "gpName")):
            return False
        for key, field in (("am", "am"), ("fe", "fe"), ("frt", "frt"), ("circle", "circle")):
            if (v := (f.get(key) or "").strip().lower()) and not _match(r.get(field), v):
                return False
        if (v := (f.get("gp") or "").strip().lower()) and not (_match(r.get("gpCode"), v) or _match(r.get("gpName"), v)):
            return False
        return True

    rows = [r for r in rows if keep(r)]
    counts = {lv: {s: 0 for s in (*STATUSES, "CHANGES_REQUESTED")} | {"total": 0} for lv in LEVELS}
    for r in rows:
        c = counts[r["level"]]
        c["total"] += 1
        c[r["status"]] = c.get(r["status"], 0) + 1
    if f.get("level") in LEVELS:
        rows = [r for r in rows if r["level"] == f["level"]]
    if f.get("status"):
        rows = [r for r in rows if r["status"] == f["status"]]
    rows.sort(key=lambda r: (-r["ticketId"], r["code"]))  # newest AM ticket first; its ID prefix keeps FE -> FRT under it
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "pageSize": page_size, "counts": counts}
