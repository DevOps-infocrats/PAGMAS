"""Ticket Management rules: who may do what, status transitions, KPIs, lists and notifications.

Status flow (no other move is possible – every transition is a conditional UPDATE on the expected status, so two
clicks or two admins can never apply the same step twice):

    admin creates            -> OPEN
    assignee starts work     OPEN -> IN_PROGRESS
    assignee submits work    IN_PROGRESS | CHANGES_REQUESTED -> PENDING_REVIEW
    admin requests changes   PENDING_REVIEW -> CHANGES_REQUESTED   (comment required)
    admin closes (approves)  PENDING_REVIEW -> CLOSED

Only the assigned user starts and submits; only an admin (not the assignee of that ticket) reviews. Users never
close a ticket. A generated ticket (Circle → CBH / SME / Area Manager) can have several recipients (ticket_recipients):
every recipient with a dashboard account sees it in User Tickets; on a normal ticket each of them may work on it, on a
GP-wise task only the Area Manager and the Field Engineers report progress (an FE only on the GPs mapped to them)
and the CBH / SME follow it read-only. Recipients without an
account (or a typed address) only receive the optional e-mail. KPIs are counted from the database on every request:
    admin: Open = OPEN + IN_PROGRESS, Pending = PENDING_REVIEW, Closed = CLOSED
    user:  Total = all assigned to them, Working = IN_PROGRESS, Closed = CLOSED
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Ticket, TicketAttachment, TicketEvent, TicketGpForward, TicketNotification, TicketProgress, TicketRecipient, TicketSubmission, TicketTask, TicketTaskGp, User
from ..security.deps import CurrentUser
from . import files, review

STATUSES = ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CHANGES_REQUESTED", "CLOSED")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
STATUS_LABEL = {"OPEN": "Open", "IN_PROGRESS": "In Progress", "PENDING_REVIEW": "Pending Review", "CHANGES_REQUESTED": "Changes Requested", "CLOSED": "Closed"}
PRIORITY_LABEL = {"LOW": "Low", "MEDIUM": "Medium", "HIGH": "High", "CRITICAL": "Critical"}
MIN_WORK_TEXT = 10


class TicketError(Exception):
    """A refused action. `status` is the HTTP status the API answers with; `message` is shown to the user."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Upload:
    file_name: str | None
    content_type: str | None
    stream: BinaryIO


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(v: dt.datetime | None) -> str | None:
    """ISO time with offset (SQLite returns naive UTC values)."""
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).isoformat()


def code_of(ticket_id: int) -> str:
    return f"TKT-{ticket_id:06d}"


# ---------------------------------------------------------------- reading


def _recipient(db: Session, t: Ticket, user_id: int) -> TicketRecipient | None:
    return db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user_id).limit(1)).first()


def link_recipients(db: Session, user_id: int, email: str) -> int:
    """Recipients added before their dashboard account existed (e.g. the SME the Area Manager chose, the COH the SME
    chose): link them to the account with that e-mail, so the tickets show in User Tickets, and notify the user once.
    Returns the number of tickets linked."""
    addr = (email or "").strip().lower()
    if not addr:
        return 0
    rows = list(db.scalars(select(TicketRecipient).where(TicketRecipient.user_id.is_(None), func.lower(TicketRecipient.email) == addr, TicketRecipient.ticket_id.not_in(deleted_ids()))))
    if not rows:
        return 0
    for r in rows:
        r.user_id = user_id
    db.flush()
    for tid in sorted({r.ticket_id for r in rows}):
        t = db.get(Ticket, tid)
        if t is None:
            continue
        roles = {r.role for r in rows if r.ticket_id == tid}
        state = "AM_APPROVED" if "SME" in roles else "SME_FORWARDED"
        waiting = 0
        if roles & {"SME", "COH"}:
            # only the GPs forwarded to this person (approvals from before GP-level forwarding: the ticket's count)
            mine = [r.id for r in rows if r.ticket_id == tid]
            q = select(func.count(func.distinct(TicketTaskGp.id))).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid, TicketTaskGp.review == state)
            if db.scalar(select(TicketGpForward.id).where(TicketGpForward.ticket_id == tid).limit(1)) is not None:
                q = q.join(TicketGpForward, TicketGpForward.task_gp_id == TicketTaskGp.id).where(TicketGpForward.recipient_id.in_(mine))
            waiting = db.scalar(q) or 0
        if "SME" in roles:
            title, body = f"{t.code}: GPs approved by the Area Manager – your review", f"{waiting} GP{'s' if waiting != 1 else ''} wait for your review (SME): check and forward them to the COH."
        elif "COH" in roles:
            title, body = f"{t.code}: GPs forwarded by the SME – letter / AMC", f"{waiting} GP{'s' if waiting != 1 else ''} wait for the letter submission / AMC conversion (COH)."
        else:
            title, body = f"Ticket {t.code}: {t.subject}"[:200], "This ticket was sent to your e-mail address – it is now in your User Tickets."
        _notify(db, {user_id}, t, "REVIEW" if roles & {"SME", "COH"} else "ASSIGNED", title, body)
    db.commit()
    return len({r.ticket_id for r in rows})


def is_worker(db: Session, t: Ticket, user: CurrentUser) -> bool:
    """May start / submit / report progress: the assigned user, or a recipient allowed to work on it."""
    if t.assignee_id == user.id:
        return True
    r = _recipient(db, t, user.id)
    return bool(r and r.can_work)


def _workers(db: Session, t: Ticket) -> set[int]:
    ids = {t.assignee_id} if t.assignee_id else set()
    return ids | set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.can_work.is_(True), TicketRecipient.user_id.is_not(None))))


def _members(db: Session, t: Ticket) -> set[int]:
    """Every dashboard user the ticket was sent to (workers and read-only recipients)."""
    ids = {t.assignee_id} if t.assignee_id else set()
    return ids | set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id.is_not(None))))


def _mine(user_id: int):
    """Tickets of a user: assigned to them, or sent to them as a recipient."""
    return or_(Ticket.assignee_id == user_id, Ticket.id.in_(select(TicketRecipient.ticket_id).where(TicketRecipient.user_id == user_id)))


def live():
    """Not deleted – every list, count, monitor and notification uses only these tickets."""
    return Ticket.deleted_at.is_(None)


def deleted_ids():
    return select(Ticket.id).where(Ticket.deleted_at.is_not(None))


def visible(db: Session, ticket_id: int, user: CurrentUser) -> Ticket:
    """The ticket if this user may open it (admins: every ticket; others: only tickets assigned / sent to them).
    Anything else answers 404, so ticket IDs of other people cannot be probed."""
    t = db.get(Ticket, ticket_id)
    if t is None or t.deleted_at is not None or not (user.is_admin or t.assignee_id == user.id or _recipient(db, t, user.id) is not None):
        raise TicketError(404, "Ticket not found")
    return t


def kpis(db: Session, assignee_id: int | None = None) -> dict[str, int]:
    q = select(Ticket.status, func.count()).where(live()).group_by(Ticket.status)
    if assignee_id is not None:
        q = q.where(_mine(assignee_id))
    c = {s: 0 for s in STATUSES} | dict(db.execute(q).all())
    total = sum(c.values())
    return {
        "total": total,
        "open": c["OPEN"] + c["IN_PROGRESS"],
        "pending": c["PENDING_REVIEW"],
        "closed": c["CLOSED"],
        "working": c["IN_PROGRESS"],
        "byStatus": {s: c[s] for s in STATUSES},
    }


def _local_day_start(d: dt.date) -> dt.datetime:
    """Start of a calendar day in the reporting timezone, as UTC (dates on screen are local dates)."""
    try:
        z = ZoneInfo(get_settings().report_timezone)
    except Exception:  # noqa: BLE001 - unknown zone: fall back to UTC
        z = dt.UTC
    return dt.datetime.combine(d, dt.time(), z).astimezone(dt.UTC)


def list_tickets(
    db: Session,
    *,
    assignee_id: int | None,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    circle: str | None = None,
    area_manager: str | None = None,
    week: str | None = None,
    gp: str | None = None,
    progress_date: dt.date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    q = select(Ticket).where(live())
    if assignee_id is not None:
        q = q.where(_mine(assignee_id))
    if circle and circle.strip():
        c = circle.strip().lower()
        q = q.where(or_(func.lower(Ticket.circle) == c, Ticket.id.in_(select(TicketTaskGp.ticket_id).where(func.lower(TicketTaskGp.circle) == c))))
    if area_manager and area_manager.strip():
        q = q.where(Ticket.id.in_(select(TicketTask.ticket_id).where(TicketTask.am_name == area_manager.strip())))
    if week:
        q = q.where(Ticket.id.in_(select(TicketTask.ticket_id).where(TicketTask.week_code == week)))
    if gp and gp.strip():
        term = f"%{gp.strip().lower()}%"
        q = q.where(Ticket.id.in_(select(TicketTaskGp.ticket_id).where(or_(func.lower(TicketTaskGp.gp_code).like(term), func.lower(TicketTaskGp.gp_name).like(term)))))
    if progress_date:
        q = q.where(
            Ticket.id.in_(
                select(TicketProgress.ticket_id).where(TicketProgress.submitted_at >= _local_day_start(progress_date), TicketProgress.submitted_at < _local_day_start(progress_date + dt.timedelta(days=1)))
            )
        )
    if status:
        q = q.where(Ticket.status == status)
    if priority:
        q = q.where(Ticket.priority == priority)
    if date_from:
        q = q.where(Ticket.created_at >= _local_day_start(date_from))
    if date_to:
        q = q.where(Ticket.created_at < _local_day_start(date_to + dt.timedelta(days=1)))
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        cols = [func.lower(Ticket.code), func.lower(Ticket.subject)]
        if assignee_id is None:  # admin list: also the user's name and e-mail
            cols += [func.lower(Ticket.assignee_name), func.lower(Ticket.assignee_email)]
        q = q.where(or_(*(c.like(term) for c in cols)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    ids = [t.id for t in rows]
    tasks = {k.ticket_id: k for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_(ids)))} if ids else {}
    counts = dict(db.execute(select(TicketRecipient.ticket_id, func.count()).where(TicketRecipient.ticket_id.in_(ids)).group_by(TicketRecipient.ticket_id)).all()) if ids else {}
    items = []
    for t in rows:
        k = tasks.get(t.id)
        items.append(summary_json(t) | {"areaManager": k.am_name if k else None, "week": k.week_code if k else None, "recipientCount": int(counts.get(t.id, 0))})
    return {"items": items, "total": total, "page": page, "pageSize": page_size}


def filter_options(db: Session) -> dict[str, Any]:
    """Circles, Area Managers and weeks that occur in tickets (admin list filters)."""
    gone = deleted_ids()
    circles = {c.strip().title() for c in db.scalars(select(Ticket.circle).where(Ticket.circle.is_not(None), live())) if c and c.strip()}
    circles |= {c.strip().title() for c in db.scalars(select(TicketTaskGp.circle).where(TicketTaskGp.ticket_id.not_in(gone)).distinct()) if c and c.strip()}
    ams = sorted({a for a in db.scalars(select(TicketTask.am_name).where(TicketTask.ticket_id.not_in(gone)).distinct()) if a})
    weeks = sorted({w for w in db.scalars(select(TicketTask.week_code).where(TicketTask.ticket_id.not_in(gone)).distinct()) if w}, key=lambda w: int(w[2:]) if w[2:].isdigit() else 0, reverse=True)
    return {"circles": sorted(circles), "areaManagers": ams, "weeks": weeks}


def summary_json(t: Ticket) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code or code_of(t.id),
        "subject": t.subject,
        "priority": t.priority,
        "status": t.status,
        "assignee": {"id": t.assignee_id, "name": t.assignee_name, "email": t.assignee_email},
        "createdBy": {"id": t.created_by_id, "name": t.created_by_name},
        "createdAt": iso(t.created_at),
        "updatedAt": iso(t.updated_at),
        "submittedAt": iso(t.submitted_at),
        "closedAt": iso(t.closed_at),
        "circle": t.circle,
    }


# Ticket activity whose notes list GP codes of the whole task (hidden from an SME, who sees only their GPs)
SME_HIDDEN_EVENTS = frozenset({"PROGRESS", "REVIEW", "NONDOABLE"})


def detail_json(db: Session, t: Ticket, user: CurrentUser) -> dict[str, Any]:
    subs = db.scalars(select(TicketSubmission).where(TicketSubmission.ticket_id == t.id).order_by(TicketSubmission.version.desc())).all()
    atts = db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == t.id).order_by(TicketAttachment.id)).all()
    by_sub: dict[int, list[dict[str, Any]]] = {}
    for a in atts:
        by_sub.setdefault(a.submission_id, []).append(
            {"id": a.id, "fileName": a.file_name, "contentType": a.content_type, "size": a.size, "uploadedAt": iso(a.uploaded_at), "previewable": a.content_type in files.INLINE_TYPES}
        )
    events = db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == t.id).order_by(TicketEvent.at, TicketEvent.id)).all()
    assignee = db.get(User, t.assignee_id) if t.assignee_id else None
    latest_change = next((s for s in subs if s.review == "CHANGES_REQUESTED"), None)
    is_assignee = is_worker(db, t, user)
    from .task import ReviewerView, task_json, view_of

    scope = view_of(db, t, user)  # FE: their GPs · SME / COH: the GPs forwarded to them · else the whole task
    task_block = task_json(db, t, scope)
    recs = db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id).order_by(TicketRecipient.id)).all()
    mine = next((r for r in recs if r.user_id == user.id), None)
    if scope is not None:  # a Field Engineer does not see the other FEs of the ticket
        recs = [r for r in recs if r.role != "FE" or r.user_id == user.id]
    if isinstance(scope, ReviewerView):
        # nor does an SME / COH see the other SMEs / COHs, or the ticket activity naming other GPs (daily progress /
        # review steps – each of their own GPs carries its full review history instead)
        recs = [r for r in recs if r.role not in ("SME", "COH") or r.user_id == user.id]
        events = [e for e in events if e.action not in SME_HIDDEN_EVENTS]
    return {
        **summary_json(t),
        "description": t.description,
        "startedAt": iso(t.started_at),
        "closedBy": {"id": t.closed_by_id, "name": t.closed_by_name} if t.closed_by_id or t.closed_by_name else None,
        "assigneeActive": bool(assignee and assignee.is_active),
        "assigneeRole": assignee.role if assignee else None,
        "feedback": (
            {"comment": latest_change.review_comment, "by": latest_change.reviewed_by_name, "at": iso(latest_change.reviewed_at), "version": latest_change.version}
            if latest_change and t.status == "CHANGES_REQUESTED"
            else None
        ),
        "submissions": [
            {
                "id": s.id,
                "version": s.version,
                "description": s.description,
                "submittedAt": iso(s.submitted_at),
                "submittedBy": s.submitted_by_name,
                "review": s.review,
                "reviewedBy": s.reviewed_by_name,
                "reviewedAt": iso(s.reviewed_at),
                "reviewComment": s.review_comment,
                "attachments": by_sub.get(s.id, []),
            }
            for s in subs
        ],
        "events": [{"at": iso(e.at), "actor": e.actor_name, "action": e.action, "from": e.from_status, "to": e.to_status, "note": e.note} for e in events],
        # What this user may do now (the backend checks again on every action)
        "task": task_block,
        "recipients": [recipient_json(r, user.is_admin) for r in recs],
        "myRole": (mine.role if mine else ("ASSIGNEE" if t.assignee_id == user.id else None)),
        "can": {
            "start": is_assignee and t.status == "OPEN",
            "submit": is_assignee and t.status in ("IN_PROGRESS", "CHANGES_REQUESTED"),
            "review": user.is_admin and not is_assignee and t.status == "PENDING_REVIEW",
            # GP-wise task: daily progress by the Area Manager while open; the admin may close it from any open status
            "progress": task_block is not None and is_assignee and t.status != "CLOSED",
            "close": user.is_admin and not is_assignee and (t.status == "PENDING_REVIEW" or (task_block is not None and t.status != "CLOSED")),
            "email": user.is_admin,
            # Area Manager of a GP-wise task: inform the CBH / SME (latest sheet + remark)
            "share": task_block is not None and mine is not None and mine.role == "AM",
            # review chain of the GPs (AM approve / return, SME forward, COH letter / AMC) – admins may do every step
            "reviewAs": sorted(review.roles_of(db, t, user)) if task_block is not None else [],
        },
    }


def recipient_json(r: TicketRecipient, admin: bool) -> dict[str, Any]:
    return {
        "id": r.id,
        "role": r.role,
        "name": r.name,
        "email": r.email,
        "access": "dashboard" if r.user_id else "email",
        "canWork": r.can_work,
        "workbook": r.attach_workbook,
        "emailStatus": r.email_status,
        "emailError": r.email_error if admin else None,
        "emailedAt": iso(r.emailed_at),
        "areaManager": r.am_name,
    }


# ---------------------------------------------------------------- writing


def _event(db: Session, t: Ticket, actor: CurrentUser, action: str, frm: str | None, to: str | None, note: str | None = None) -> None:
    db.add(TicketEvent(ticket_id=t.id, at=now(), actor_id=actor.id, actor_name=actor.name, action=action, from_status=frm, to_status=to, note=note))


def _notify(db: Session, user_ids: set[int], t: Ticket, kind: str, title: str, body: str) -> None:
    for uid in user_ids:
        db.add(TicketNotification(user_id=uid, ticket_id=t.id, kind=kind, title=title[:200], body=body[:500], created_at=now()))


def _move(db: Session, t: Ticket, allowed: tuple[str, ...], to: str, **values: Any) -> str:
    """Conditional status change: applied only while the ticket is still in one of `allowed`."""
    before = t.status
    res = db.execute(update(Ticket).where(Ticket.id == t.id, Ticket.status.in_(allowed)).values(status=to, updated_at=now(), **values))
    if res.rowcount != 1:
        db.rollback()
        db.refresh(t)
        raise TicketError(409, f"This ticket is now {STATUS_LABEL.get(t.status, t.status)} – the action is no longer possible. Reload the ticket.")
    return before


def active_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)))


def create(db: Session, admin: CurrentUser, assignee_id: int, subject: str, description: str, priority: str, task: tuple[Any, str, str] | None = None) -> Ticket:
    """`task` = (store, Area Manager name, week code): adds the GP-wise weekly task (app.tickets.task) to the ticket.
    The ticket must then go to the dashboard user whose e-mail is the Area Manager's e-mail in the Escalation Matrix."""
    u = db.get(User, assignee_id)
    if u is None or not u.is_active:
        raise TicketError(422, "Select an active user to assign the ticket to")
    if u.id == admin.id:
        raise TicketError(422, "A ticket cannot be assigned to yourself")
    if task is not None:
        from . import task as tasks

        store, am, _week = task
        emails = tasks.am_emails(store, am)
        if u.email.lower() not in emails:
            raise TicketError(422, f"{u.name} ({u.email}) is not {am}'s e-mail in the Escalation Matrix ({', '.join(emails) or 'no e-mail'}) – assign the ticket to the Area Manager's own account")
    t = Ticket(
        subject=subject.strip(),
        description=description.strip(),
        priority=priority,
        status="OPEN",
        assignee_id=u.id,
        assignee_name=u.name,
        assignee_email=u.email,
        created_by_id=admin.id,
        created_by_name=admin.name,
        created_at=now(),
        updated_at=now(),
    )
    db.add(t)
    db.flush()
    t.code = code_of(t.id)
    if task is not None:
        try:
            made = tasks.attach(db, store, t, am, _week)
        except tasks.TaskError as exc:
            db.rollback()
            raise TicketError(exc.status, exc.message) from None
        n = db.scalar(select(func.count()).where(TicketTaskGp.ticket_id == t.id)) or 0
        _event(db, t, admin, "TASK", None, None, f"GP-wise task: {made.am_name} · Week {made.week_code[2:]} · {n} GPs · assignment workbook attached")
    _event(db, t, admin, "CREATED", None, "OPEN", f"Assigned to {u.name} · priority {PRIORITY_LABEL[priority]}")
    _notify(db, {u.id}, t, "ASSIGNED", f"New ticket {t.code}: {t.subject}", f"{admin.name} assigned you a {PRIORITY_LABEL[priority].lower()} priority ticket.")
    db.commit()
    return t


@dataclass
class Rcpt:
    role: str  # CBH | SME | AM | FE | USER
    name: str
    email: str
    user: User | None
    am: str | None = None  # FE: the parent Area Manager in the Escalation Matrix
    fe_mail: str | None = None  # FE: the matrix FE e-mail of their GPs (None = rows without one)

    def scope(self):
        from .task import FeScope

        return FeScope(self.name, self.fe_mail)


ROLE_ORDER = ("USER", "OTHER", "AM", "FE", "SME", "COH", "CBH")  # who is shown as the assigned user of a normal ticket


def resolve_recipients(db: Session, admin: CurrentUser, store: Any, circle: str, items: list[dict[str, str]], assignee_id: int | None, week: str) -> list[Rcpt]:
    """Check what the admin selected: names come from the circle's database records, e-mails are valid, nobody twice.
    The dashboard account of a recipient is the active user with that e-mail (the creating admin never counts)."""
    from ..mail.smtp import valid_address
    from . import directory

    from . import task as tasks

    known = directory.known_names(db, store, circle, week)
    slots = None
    users = {u.email.lower(): u for u in active_users(db)}
    out: list[Rcpt] = []
    seen: dict[str, str] = {}
    for it in items:
        role, name = it["role"], " ".join(str(it["name"]).split())
        label = directory.ROLE_LABEL[role]
        am = fe_mail = None
        if role == "FE":
            # an FE = one Escalation Matrix mapping (Area Manager, FE name, FE e-mail of the GP rows) of this circle
            if slots is None:
                slots = tasks.fe_slots(store, circle, week)[0]
            want = tasks.fe_key(name, it.get("feEmail"))
            slot = next((x for x in slots if x["am"] == " ".join(str(it.get("am") or "").split()) and tasks.fe_key(x["name"], x["mappedEmail"]) == want), None)
            if slot is None:
                under = f" under Area Manager {it.get('am')}" if it.get("am") else ""
                raise TicketError(422, f"Field Engineer '{name}'{under} is not mapped in the Escalation Matrix of {circle}")
            name, am, fe_mail = slot["name"], slot["am"], slot["mappedEmail"]
        elif role == "OTHER":
            pass  # typed by the admin: any name, the e-mail is checked below
        elif name not in known[role]:
            raise TicketError(422, f"{label} '{name}' is not a {label} of {circle} in the database")
        addr = valid_address(it.get("email"))
        if addr is None:
            raise TicketError(422, f"{label} {name}: '{it.get('email') or ''}' is not a valid e-mail address")
        if addr in seen:
            raise TicketError(422, f"{addr} is selected twice ({seen[addr]} and {label} {name})")
        seen[addr] = f"{label} {name}"
        u = users.get(addr)
        out.append(Rcpt(role, name, addr, u if u is not None and u.id != admin.id else None, am, fe_mail))
    if assignee_id is not None:
        u = db.get(User, assignee_id)
        if u is None or not u.is_active:
            raise TicketError(422, "Select an active user to assign the ticket to")
        if u.id == admin.id:
            raise TicketError(422, "A ticket cannot be assigned to yourself")
        if u.email.lower() not in seen:
            out.insert(0, Rcpt("USER", u.name, u.email.lower(), u))
    return out


def generate(
    db: Session,
    admin: CurrentUser,
    store: Any,
    *,
    subject: str,
    description: str,
    priority: str,
    circle: str,
    items: list[dict[str, str]],
    assignee_id: int | None,
    week: str,
    task: bool,
    send_email: bool,
) -> list[Ticket]:
    """Generate Ticket with recipients. Normal ticket: one ticket for everyone selected. GP-wise task: one ticket (and
    one workbook) per selected Area Manager, each with only that AM's GPs; the selected Field Engineers of that AM are on
    the same ticket, each with their own workbook and only the GPs mapped to them. Field Engineers whose Area Manager
    is not selected get one ticket per Area Manager with only their GPs. The CBH / SME / other user selected follow
    every ticket. All tickets are created together or none (a failing one rolls the whole batch back)."""
    from . import directory
    from . import task as tasks

    chosen = next((c["name"] for c in directory.circles(store) if c["name"].lower() == " ".join(circle.split()).lower()), None)
    if chosen is None:
        raise TicketError(422, "Select a Circle / State of the database")
    recs = resolve_recipients(db, admin, store, chosen, items, assignee_id, week)
    if not recs:
        raise TicketError(422, "Select at least one recipient (CBH, SME, Area Manager, Field Engineer or a dashboard user)")
    # (lead, recipients of the ticket, FEs whose GPs make the task when the Area Manager is not on it)
    groups: list[tuple[Rcpt, list[Rcpt], list[Rcpt] | None]] = []
    if task:
        ams = [r for r in recs if r.role == "AM"]
        fes = [r for r in recs if r.role == "FE"]
        if not ams and not fes:
            raise TicketError(422, "GP-wise Task Assignment needs at least one Area Manager or Field Engineer")
        others = [r for r in recs if r.role not in ("AM", "FE")]
        placed: set[str] = set()
        for am in ams:
            mine = [f for f in fes if f.am == am.name and am.name not in placed]
            placed.add(am.name)
            groups.append((am, [am, *mine, *others], None))
        for name in dict.fromkeys(f.am for f in fes if f.am not in placed):
            mine = [f for f in fes if f.am == name]
            groups.append((mine[0], [*mine, *others], mine))
    else:
        primary = next((r for role in ROLE_ORDER for r in recs if r.role == role and r.user), None) or recs[0]
        groups = [(primary, recs, None)]
    for lead, group, _only in groups:
        if send_email:
            continue
        if task and lead.user is None:
            who = "Area Manager" if lead.role == "AM" else "Field Engineer"
            raise TicketError(422, f"{who} {lead.name} has no dashboard account for {lead.email} – turn on 'Send Email Notification' or add the user in User Management")
        if task:
            fe_off = next((r for r in group if r.role == "FE" and r.user is None), None)
            if fe_off is not None:
                raise TicketError(422, f"Field Engineer {fe_off.name} has no dashboard account for {fe_off.email} – turn on 'Send Email Notification' or add the user in User Management")
        if not any(r.user for r in group):
            raise TicketError(422, "None of the selected recipients has a dashboard account – turn on 'Send Email Notification' or select a registered user")

    made: list[Ticket] = []
    folders: list[int] = []  # ticket ids whose workbook folder is removed again if the batch fails
    try:
        for lead, group, only in groups:
            t = Ticket(
                subject=subject.strip(), description=description.strip(), priority=priority, status="OPEN",
                assignee_id=lead.user.id if lead.user else None, assignee_name=lead.user.name if lead.user else lead.name, assignee_email=lead.user.email if lead.user else lead.email,
                created_by_id=admin.id, created_by_name=admin.name, created_at=now(), updated_at=now(), circle=chosen,
            )
            db.add(t)
            db.flush()
            t.code = code_of(t.id)
            made.append(t)
            folders.append(t.id)
            for r in group:
                work = (r.role in ("AM", "FE")) if task else True
                db.add(
                    TicketRecipient(
                        ticket_id=t.id, role=r.role, name=r.name, email=r.email, user_id=r.user.id if r.user else None, can_work=bool(r.user) and work,
                        attach_workbook=task and (r.role == "FE" or (r is lead and r.role == "AM")), email_status="PENDING" if send_email else "NONE",
                        emailed_at=now() if send_email else None, am_name=r.am, fe_mail=r.fe_mail,
                    )
                )
            if task:
                am_name = lead.name if lead.role == "AM" else lead.am
                try:
                    made_task = tasks.attach(db, store, t, am_name, week, chosen, lead.email if lead.role == "AM" else None, [f.scope() for f in only] if only else None)
                except tasks.TaskError as exc:
                    raise TicketError(exc.status, exc.message) from None
                rows = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id)))
                fe_parts = []
                for f in (r for r in group if r.role == "FE"):
                    k = sum(1 for g in rows if f.scope().owns(g))
                    if k == 0:
                        raise TicketError(422, f"Field Engineer {f.name} ({am_name}) has no GP in {chosen} with a Planned Date in Week {made_task.week_code[2:]} – remove this FE")
                    fe_parts.append(f"FE {f.name} {k}")
                fe_note = f" · {', '.join(fe_parts)} GPs" if fe_parts else ""
                _event(db, t, admin, "TASK", None, None, f"GP-wise task: {made_task.am_name} · {chosen} · Week {made_task.week_code[2:]} · {len(rows)} GPs{fe_note} · assignment workbook attached")
            who = ", ".join(f"{directory.ROLE_LABEL[r.role]} {r.name}" for r in group)
            _event(db, t, admin, "CREATED", None, "OPEN", f"{chosen} · sent to {who} · priority {PRIORITY_LABEL[priority]} · e-mail {'on' if send_email else 'off'}")
            for r in group:
                if r.user is None:
                    continue
                works = (r.role in ("AM", "FE")) if task else True
                body = f"{admin.name} assigned you a {PRIORITY_LABEL[priority].lower()} priority ticket." if works else (f"{admin.name} sent you a {PRIORITY_LABEL[priority].lower()} priority ticket – review the GPs the Area Manager approves." if task and r.role == "SME" else f"{admin.name} sent you a {PRIORITY_LABEL[priority].lower()} priority ticket – record the letter submission and AMC conversion of the GPs the SME forwards." if task and r.role == "COH" else f"{admin.name} shared a {PRIORITY_LABEL[priority].lower()} priority ticket with you (view only).")
                _notify(db, {r.user.id}, t, "ASSIGNED", f"New ticket {t.code}: {t.subject}", body)
        db.commit()
    except BaseException:
        db.rollback()
        import shutil

        for tid in folders:
            shutil.rmtree(get_settings().ticket_dir / str(tid), ignore_errors=True)
        raise
    return made


def start(db: Session, t: Ticket, user: CurrentUser) -> Ticket:
    if not is_worker(db, t, user):
        raise TicketError(403, "Only the assigned user can start this ticket")
    frm = _move(db, t, ("OPEN",), "IN_PROGRESS", started_at=now())
    _event(db, t, user, "STARTED", frm, "IN_PROGRESS")
    db.commit()
    db.refresh(t)
    return t


def _reviewers(db: Session, t: Ticket) -> set[int]:
    """Admin(s) told about a submission: the admin who created the ticket, or every active admin if that one is gone."""
    creator = db.get(User, t.created_by_id) if t.created_by_id else None
    workers = _workers(db, t)
    if creator and creator.is_active and creator.role == "admin" and creator.id not in workers:
        return {creator.id}
    return {u.id for u in active_users(db) if u.role == "admin" and u.id not in workers}


def submit(db: Session, t: Ticket, user: CurrentUser, description: str, uploads: list[Upload]) -> Ticket:
    s = get_settings()
    if not is_worker(db, t, user):
        raise TicketError(403, "Only the assigned user can submit work for this ticket")
    if t.status not in ("IN_PROGRESS", "CHANGES_REQUESTED"):
        msg = "Start working on the ticket first" if t.status == "OPEN" else f"This ticket is {STATUS_LABEL.get(t.status, t.status)} – it cannot be changed now"
        raise TicketError(409, msg)
    text = (description or "").strip()
    if len(text) < MIN_WORK_TEXT:
        raise TicketError(422, f"Describe the work you have completed (at least {MIN_WORK_TEXT} characters)")
    uploads = [u for u in uploads if u.file_name]
    if len(uploads) > s.ticket_max_files:
        raise TicketError(422, f"At most {s.ticket_max_files} files per submission")
    for u in uploads:  # names and types first, before anything is written
        try:
            files.check_meta(u.file_name, u.content_type)
        except files.AttachmentError as exc:
            raise TicketError(exc.status, str(exc)) from None

    stored: list[files.StoredFile] = []
    budget = s.ticket_upload_max_mb * 1024 * 1024
    try:
        for u in uploads:
            f = files.save(t.id, u.file_name, u.content_type, u.stream, budget)
            budget -= f.size
            stored.append(f)
        frm = _move(db, t, ("IN_PROGRESS", "CHANGES_REQUESTED"), "PENDING_REVIEW", submitted_at=now())
        version = (db.scalar(select(func.max(TicketSubmission.version)).where(TicketSubmission.ticket_id == t.id)) or 0) + 1
        sub = TicketSubmission(ticket_id=t.id, version=version, submitted_by_id=user.id, submitted_by_name=user.name, description=text, submitted_at=now(), review="PENDING")
        db.add(sub)
        db.flush()
        for f in stored:
            db.add(TicketAttachment(ticket_id=t.id, submission_id=sub.id, file_name=f.file_name, stored_name=f.stored_name, content_type=f.content_type, size=f.size, sha256=f.sha256, uploaded_at=now()))
        what = f"{len(stored)} file{'s' if len(stored) != 1 else ''}"
        _event(db, t, user, "SUBMITTED" if version == 1 else "RESUBMITTED", frm, "PENDING_REVIEW", f"Submission {version} · {what}")
        _notify(db, _reviewers(db, t), t, "SUBMITTED", f"{t.code} submitted for review", f"{user.name} submitted work (submission {version}, {what}) for: {t.subject}")
        db.commit()
    except files.AttachmentError as exc:
        db.rollback()
        files.remove(t.id, [f.stored_name for f in stored])
        raise TicketError(exc.status, str(exc)) from None
    except BaseException:
        db.rollback()
        files.remove(t.id, [f.stored_name for f in stored])
        raise
    db.refresh(t)
    return t


def _latest_pending(db: Session, t: Ticket) -> TicketSubmission:
    sub = db.scalars(select(TicketSubmission).where(TicketSubmission.ticket_id == t.id).order_by(TicketSubmission.version.desc()).limit(1)).first()
    if sub is None or sub.review != "PENDING":
        raise TicketError(409, "There is no submission waiting for review")
    return sub


def _check_reviewer(db: Session, t: Ticket, admin: CurrentUser) -> None:
    if not admin.is_admin:
        raise TicketError(403, "Only an admin can review tickets")
    if is_worker(db, t, admin):
        raise TicketError(403, "You cannot review a ticket assigned to yourself")


def close(db: Session, t: Ticket, admin: CurrentUser, comment: str | None, force: bool = False) -> Ticket:
    """Normal ticket: closes an approved submission (Pending Review). Ticket with a GP-wise task: the admin closes it
    from any open status once satisfied with the daily progress (never automatically); a waiting submission is approved."""
    _check_reviewer(db, t, admin)
    has_task = db.get(TicketTask, t.id) is not None
    note = (comment or "").strip() or None
    if has_task:
        # SOP compliance rule 4: no ticket is closed without the Area Manager's review and approval of its GPs. A GP
        # counts as reviewed once approved by the AM (or later steps) or closed Non-Doable; a GP already achieved in the
        # master data at assignment needs no review. The admin may still close with a written reason (kept in history).
        from .task import cumulative

        gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id)))
        unreviewed = [g for g in gps if g.review not in review.AM_REVIEWED and cumulative(g) < g.target]
        if unreviewed:
            pending_am = sum(1 for g in unreviewed if (g.review is None and g.gp_category == "A") or g.review == "SME_RETURNED")
            what = f"{len(unreviewed)} GP{'s' if len(unreviewed) != 1 else ''} of this ticket {'are' if len(unreviewed) != 1 else 'is'} not yet reviewed and approved by the Area Manager"
            detail = f"{pending_am} Pending AM Verification, {len(unreviewed) - pending_am} with the FE / returned / in a Non-Doable case"
            if not force:
                raise TicketError(409, f"{what} ({detail}). Close only after the AM review, or close anyway with a written reason.")
            if note is None or len(note) < 10:
                raise TicketError(422, "Write the reason for closing without the Area Manager's approval (at least 10 characters)")
            note = f"Closed without AM approval of {len(unreviewed)} GP{'s' if len(unreviewed) != 1 else ''} ({detail}) – reason: {note}"
        last = db.scalars(select(TicketSubmission).where(TicketSubmission.ticket_id == t.id).order_by(TicketSubmission.version.desc()).limit(1)).first()
        sub = last if last is not None and last.review == "PENDING" else None
        frm = _move(db, t, ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CHANGES_REQUESTED"), "CLOSED", closed_at=now(), closed_by_id=admin.id, closed_by_name=admin.name)
    else:
        sub = _latest_pending(db, t)
        frm = _move(db, t, ("PENDING_REVIEW",), "CLOSED", closed_at=now(), closed_by_id=admin.id, closed_by_name=admin.name)
    if sub is not None:
        sub.review, sub.reviewed_by_id, sub.reviewed_by_name, sub.reviewed_at, sub.review_comment = "ACCEPTED", admin.id, admin.name, now(), note
    _event(db, t, admin, "CLOSED", frm, "CLOSED", note)
    # every recipient with an account sees the Closed status (one ticket) and is told about it
    _notify(db, _members(db, t) - {admin.id}, t, "CLOSED", f"{t.code} closed", f"{admin.name} approved the work and closed the ticket: {t.subject}")
    db.commit()
    db.refresh(t)
    return t


def request_changes(db: Session, t: Ticket, admin: CurrentUser, comment: str) -> Ticket:
    _check_reviewer(db, t, admin)
    text = (comment or "").strip()
    if len(text) < 5:
        raise TicketError(422, "Explain what needs to be corrected")
    sub = _latest_pending(db, t)
    frm = _move(db, t, ("PENDING_REVIEW",), "CHANGES_REQUESTED")
    sub.review, sub.reviewed_by_id, sub.reviewed_by_name, sub.reviewed_at, sub.review_comment = "CHANGES_REQUESTED", admin.id, admin.name, now(), text
    _event(db, t, admin, "CHANGES_REQUESTED", frm, "CHANGES_REQUESTED", text)
    _notify(db, _workers(db, t), t, "CHANGES_REQUESTED", f"Changes requested on {t.code}", f"{admin.name}: {text}")
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------- delete (admin)


def delete(db: Session, t: Ticket, admin: CurrentUser, reason: str | None = None) -> Ticket:
    """Soft delete: the ticket (any status) leaves every list, KPI, GP monitor and notification for everyone – admin,
    Area Manager, FE, CBH, SME. Its GP rows, daily progress, remarks, proof documents and events stay in the database
    as history (no orphan, no broken reference); its code is never reused. Only an admin may do it (the API checks too)."""
    if not admin.is_admin:
        raise TicketError(403, "Only an admin can delete tickets")
    res = db.execute(update(Ticket).where(Ticket.id == t.id, Ticket.deleted_at.is_(None)).values(deleted_at=now(), deleted_by_name=admin.name, updated_at=now()))
    if res.rowcount != 1:
        db.rollback()
        raise TicketError(404, "Ticket not found")
    note = (reason or "").strip()[:500] or None
    _event(db, t, admin, "DELETED", t.status, t.status, f"Deleted by {admin.name}" + (f": {note}" if note else ""))
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------- notifications


# ---------------------------------------------------------------- Area Manager -> CBH / SME


SHARE_ROLES = ("CBH", "SME")


def can_share(db: Session, t: Ticket, user: CurrentUser) -> bool:
    """The Area Manager of a GP-wise task ticket may inform the CBH / SME of its circle (sheet + remark)."""
    from ..models import TicketTask

    r = _recipient(db, t, user.id)
    return r is not None and r.role == "AM" and db.get(TicketTask, t.id) is not None


def share_contacts(db: Session, t: Ticket, user: CurrentUser) -> dict[str, Any]:
    """CBH / SME of the ticket's circle in the Escalation Matrix – the only people the Area Manager can share with."""
    from . import directory

    if not can_share(db, t, user):
        raise TicketError(403, "Only the Area Manager of this GP-wise task can share it with the CBH / SME")
    on = {r.email for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id))}
    out: dict[str, Any] = {"circle": t.circle}
    for role in SHARE_ROLES:
        people = directory.people(db, role, t.circle) if t.circle else []
        out[role.lower()] = [
            {"name": p["name"], "emails": [{"email": e["email"], "account": e["user"] is not None, "onTicket": e["email"] in on} for e in p["emails"]]} for p in people if p["emails"]
        ]
    return out


def share(db: Session, t: Ticket, user: CurrentUser, items: list[dict[str, str]], remark: str) -> list[int]:
    """The Area Manager shares the ticket with CBH / SME of its circle: each gets the latest GP sheet and the remark by
    e-mail (and the ticket read-only in User Tickets when they have a dashboard account). Recorded in the history;
    the admins and the people with an account are notified. Returns the recipient ids whose e-mail is queued."""
    from ..mail.smtp import valid_address
    from . import directory

    if not can_share(db, t, user):
        raise TicketError(403, "Only the Area Manager of this GP-wise task can share it with the CBH / SME")
    text = (remark or "").strip()
    if len(text) < 3:
        raise TicketError(422, "Write a remark for the CBH / SME (at least 3 characters)")
    if not items:
        raise TicketError(422, "Select at least one CBH or SME")
    allowed = {role: {(" ".join(p["name"].split()), e["email"]) for p in directory.people(db, role, t.circle or "") for e in p["emails"]} for role in SHARE_ROLES}
    users = {u.email.lower(): u for u in active_users(db)}
    existing = {r.email: r for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id))}
    picked: list[TicketRecipient] = []
    seen: set[str] = set()
    for it in items:
        role, name = it.get("role"), " ".join(str(it.get("name") or "").split())
        addr = valid_address(it.get("email"))
        if role not in SHARE_ROLES or addr is None or (name, addr) not in allowed[role]:
            raise TicketError(422, f"{name or 'This person'} is not a {role or 'CBH / SME'} of {t.circle} in the Escalation Matrix")
        if addr in seen:
            continue
        seen.add(addr)
        r = existing.get(addr)
        if r is None:
            u = users.get(addr)
            r = TicketRecipient(ticket_id=t.id, role=role, name=name, email=addr, user_id=u.id if u is not None and u.id != user.id else None, can_work=False, attach_workbook=False, email_status="NONE")
            db.add(r)
            existing[addr] = r
        r.email_status, r.email_error, r.emailed_at = "PENDING", None, now()
        picked.append(r)
    db.flush()
    names = ", ".join(f"{r.role} {r.name}" for r in picked)
    _event(db, t, user, "SHARED", t.status, t.status, f"Shared with {names} (latest GP sheet by e-mail) · Remark: {text[:1500]}")
    viewers = {r.user_id for r in picked if r.user_id}
    _notify(db, viewers, t, "SHARED", f"{t.code} shared by Area Manager {user.name}", text)
    _notify(db, _reviewers(db, t) - viewers, t, "SHARED", f"{t.code}: Area Manager shared with {names}"[:200], text)
    t.updated_at = now()
    db.commit()
    return [r.id for r in picked]


def notifications(db: Session, user: CurrentUser, limit: int = 20) -> dict[str, Any]:
    gone = deleted_ids()
    rows = db.scalars(
        select(TicketNotification).where(TicketNotification.user_id == user.id, TicketNotification.ticket_id.not_in(gone)).order_by(TicketNotification.created_at.desc(), TicketNotification.id.desc()).limit(limit)
    ).all()
    unread = db.scalar(select(func.count()).where(TicketNotification.user_id == user.id, TicketNotification.read_at.is_(None), TicketNotification.ticket_id.not_in(gone))) or 0
    path = "/dashboard/tickets/admin" if user.is_admin else "/dashboard/tickets/user"
    out = []
    for n in rows:
        for_admin = n.kind in ("SUBMITTED", "PROGRESS", "REVIEW")
        target = "/dashboard/tickets/admin" if user.is_admin and for_admin else "/dashboard/tickets/user" if not for_admin else path
        if n.kind == "NONDOABLE":
            target = "/dashboard/tickets/non-doable"
        out.append({"id": n.id, "ticketId": n.ticket_id, "kind": n.kind, "title": n.title, "body": n.body, "createdAt": iso(n.created_at), "read": n.read_at is not None, "href": f"{target}?ticket={n.ticket_id}"})
    return {"unread": unread, "items": out}


def mark_read(db: Session, user: CurrentUser) -> int:
    res = db.execute(update(TicketNotification).where(TicketNotification.user_id == user.id, TicketNotification.read_at.is_(None)).values(read_at=now()))
    db.commit()
    return res.rowcount or 0
