"""Review chain of the GPs of a task ticket, after the FE's daily progress:

    FE / Area Manager  classifies the GP: A Rectification Done · C Revisit Required · D Non-Doable – Proposed
    Area Manager       AM_APPROVE (with a remark, to the SME): A becomes B "Ready for Letter Submitted"
                       AM_RETURN  (with the reason, back to the FE): the FE corrects it and submits again
    SME                SME_FORWARD an AM-approved GP to the COH with remarks (confirmed B)
    COH                COH_LETTER (date) on a forwarded B GP: category E "Letter Submission Done" – the GP is achieved
                       COH_AMC (date) after the letter: AMC conversion recorded

Who is who comes from the ticket's recipients (the Area Manager of a ticket assigned without recipients is its
assignee); an admin may do any step (recorded as ADMIN). Every step is a TicketGpReview row; a step that changes the
category is also a daily progress line (same history, GP monitor and workbook as the FE's own progress). Once the
Area Manager approved a GP, the FE / Area Manager can no longer change it in the daily progress.

D "Non-Doable – Proposed" does not take this chain: it opens a Non-Doable case (app.tickets.nondoable, FE → AM → SME →
COH → Corporate Team – MGG); a GP with an open case takes no step here, and a GP approved Non-Doable is locked.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ticket, TicketGpReview, TicketProgress, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp
from ..security.deps import CurrentUser

FE_CATEGORIES = ("A", "C", "D")  # what the FE / Area Manager may choose in the daily progress
SME_CATEGORIES = ("B",)  # the SME's confirmed category (Non-Doable goes through app.tickets.nondoable)
LOCKED = ("AM_APPROVED", "SME_FORWARDED", "LETTER_SUBMITTED", "AMC_CONVERTED", "ND_APPROVED")
MAX_REMARK = 1000
MAX_GPS = 500

REVIEW_LABEL = {
    None: "With FE",
    "RETURNED": "Returned to FE",
    "AM_APPROVED": "Approved by AM",
    "SME_FORWARDED": "Forwarded by SME",
    "LETTER_SUBMITTED": "Letter Submitted",
    "AMC_CONVERTED": "AMC Converted",
    "ND_APPROVED": "Closed – Non-Doable",
}


@dataclass(frozen=True)
class Step:
    role: str  # AM | SME | COH
    label: str
    frm: tuple[str | None, ...]
    to: str
    remark: bool  # remark required
    date: bool = False  # date required


STEPS: dict[str, Step] = {
    "AM_APPROVE": Step("AM", "Approved by Area Manager", (None,), "AM_APPROVED", True),
    "AM_RETURN": Step("AM", "Returned to FE for correction", (None,), "RETURNED", True),
    "SME_FORWARD": Step("SME", "Reviewed by SME – forwarded to COH", ("AM_APPROVED",), "SME_FORWARDED", True),
    "COH_LETTER": Step("COH", "Letter submitted (COH)", ("SME_FORWARDED",), "LETTER_SUBMITTED", False, True),
    "COH_AMC": Step("COH", "AMC converted (COH)", ("LETTER_SUBMITTED",), "AMC_CONVERTED", False, True),
}
ACTION_LABEL = {**{k: s.label for k, s in STEPS.items()}, "EDIT": "GP details edited", "ADD": "GP added to the ticket", "ND_REOPEN": "Moved to the Non-Doable workflow"}


class ReviewError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def roles_of(db: Session, t: Ticket, user: CurrentUser) -> set[str]:
    """Review roles of a user on this ticket: AM / SME / COH (admins: all three)."""
    if user.is_admin:
        return {"AM", "SME", "COH"}
    if db.get(TicketTask, t.id) is None:
        return set()
    mine = set(db.scalars(select(TicketRecipient.role).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id)))
    out = mine & {"AM", "SME", "COH"}
    if not mine and t.assignee_id == user.id:  # a task ticket assigned without recipients goes to its Area Manager
        out.add("AM")
    return out


def _fe_users(db: Session, t: Ticket, gps: list[TicketTaskGp]) -> set[int]:
    from .task import FeScope

    out: set[int] = set()
    for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE", TicketRecipient.user_id.is_not(None))):
        if any(FeScope(r.name, r.fe_mail).owns(g) for g in gps):
            out.add(r.user_id)
    return out


def _role_users(db: Session, t: Ticket, role: str) -> set[int]:
    ids = set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == role, TicketRecipient.user_id.is_not(None))))
    if role == "AM" and not ids and t.assignee_id:
        ids.add(t.assignee_id)
    return ids


NEXT_ROLE = {"AM_APPROVE": "SME", "SME_FORWARD": "COH"}  # who receives the GPs of this step
MAX_TO = 10


def contacts(db: Session, t: Ticket, user: CurrentUser, role: str) -> dict[str, Any]:
    """SME (for the Area Manager's approval) or COH (for the SME's forward) of the ticket's circle in the Escalation
    Matrix, with their e-mails – and whether each has a dashboard account / is already on the ticket."""
    from . import directory

    need = {"SME": "AM", "COH": "SME"}.get(role)
    if need is None:
        raise ReviewError(422, "Unknown role")
    if need not in roles_of(db, t, user):
        raise ReviewError(403, f"Only the {'Area Manager' if need == 'AM' else 'SME'} of this ticket chooses the {role}")
    on = {r.email: r for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id))}
    people = directory.people(db, role, t.circle) if t.circle else []
    listed = {e["email"] for p in people for e in p["emails"]}
    return {
        "circle": t.circle,
        "role": role,
        "people": [{"name": p["name"], "emails": [{"email": e["email"], "account": e["user"] is not None, "onTicket": e["email"] in on} for e in p["emails"]]} for p in people if p["emails"]],
        # already on the ticket with this role but not (any more) in the matrix – e.g. typed by the admin / Area Manager
        "onTicket": [{"name": r.name, "email": r.email, "account": r.user_id is not None} for r in on.values() if r.role == role and r.email not in listed],
    }


def _add_to(db: Session, t: Ticket, user: CurrentUser, role: str, to: list[dict[str, str]]) -> list[TicketRecipient]:
    """The SME / COH chosen for the step: put on the ticket (they review it in User Tickets with an account) and queued
    for the e-mail. A name / e-mail typed by the user is accepted (valid address required)."""
    from ..mail.smtp import valid_address
    from .service import active_users, now as snow

    if len(to) > MAX_TO:
        raise ReviewError(422, f"At most {MAX_TO} {role} e-mails")
    users = {u.email.lower(): u for u in active_users(db)}
    existing = {r.email: r for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id))}
    out: list[TicketRecipient] = []
    for it in to:
        addr = valid_address(it.get("email"))
        name = " ".join(str(it.get("name") or "").split())[:160]
        if addr is None:
            raise ReviewError(422, f"'{str(it.get('email') or '')[:80]}' is not a valid e-mail address")
        if any(r.email == addr for r in out):
            continue
        r = existing.get(addr)
        if r is None:
            u = users.get(addr)
            r = TicketRecipient(
                ticket_id=t.id, role=role, name=name or (u.name if u else addr.split("@")[0]), email=addr, user_id=u.id if u is not None and u.id != user.id else None,
                can_work=False, attach_workbook=False, email_status="NONE",
            )
            db.add(r)
            existing[addr] = r
        r.email_status, r.email_error, r.emailed_at = "PENDING", None, snow()
        out.append(r)
    db.flush()
    return out


def apply(
    db: Session, t: Ticket, user: CurrentUser, gp_ids: list[int], action: str, remark: str | None, category: str | None, on: dt.date | None,
    to: list[dict[str, str]] | None = None,
) -> tuple[int, list[int]]:
    """One review step for one or more GPs of the ticket (all or none). `to` = the SME (approval) / COH (forward) who
    receive the GPs. Returns the number of GPs and the recipient ids whose e-mail is queued."""
    from . import task as tasks
    from .service import _event, _notify, _reviewers

    step = STEPS.get(action)
    if step is None:
        raise ReviewError(422, "Unknown review step")
    if t.status == "CLOSED":
        raise ReviewError(409, "This ticket is closed – no more review steps")
    mine = roles_of(db, t, user)
    if step.role not in mine:
        who = {"AM": "the Area Manager", "SME": "the SME", "COH": "the COH"}[step.role]
        raise ReviewError(403, f"Only {who} of this ticket can do this step")
    text = (remark or "").strip()[:MAX_REMARK] or None
    if step.remark and (text is None or len(text) < 3):
        raise ReviewError(422, "Write a remark (at least 3 characters)" if action != "AM_RETURN" else "Write the reason for returning the GP to the FE")
    if step.date:
        if on is None:
            raise ReviewError(422, "Enter the date")
        today = dt.date.today()
        if on > today or on < today - dt.timedelta(days=366):
            raise ReviewError(422, "The date must be within the last year and not in the future")
    if action == "SME_FORWARD" and category is None:
        category = "B"
    if action == "SME_FORWARD" and category not in SME_CATEGORIES:
        raise ReviewError(422, "The SME confirms Ready for Letter Submitted – a Non-Doable GP goes through its Non-Doable case")
    ids = list(dict.fromkeys(int(i) for i in gp_ids))
    if not ids or len(ids) > MAX_GPS:
        raise ReviewError(422, f"Select between 1 and {MAX_GPS} GPs")
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id, TicketTaskGp.id.in_(ids))))
    if len(gps) != len(ids):
        raise ReviewError(422, "A selected GP is not part of this ticket")
    from . import nondoable as nd

    for g in gps:
        c = nd.open_case(db, g.id)
        if c is not None:
            raise ReviewError(409, f"GP {g.gp_code} is in Non-Doable case {c.ref} ({nd.STATUS_LABEL[c.status]}) – it is reviewed in Non-Doable Cases")
        if g.review not in step.frm:
            raise ReviewError(409, f"GP {g.gp_code} is '{REVIEW_LABEL.get(g.review, g.review)}' – this step is not possible now. Reload the ticket.")
        if action == "AM_APPROVE" and g.gp_category != "A":
            raise ReviewError(422, f"GP {g.gp_code}: only a GP marked Rectification Done can be approved (Non-Doable goes through its Non-Doable case)")
        if action == "COH_LETTER" and g.gp_category != "B":
            raise ReviewError(422, f"GP {g.gp_code} is confirmed Non-Doable – there is no letter to submit")

    nxt = NEXT_ROLE.get(action)
    if to and nxt is None:
        raise ReviewError(422, "This step is not sent to anybody")
    sent_to = _add_to(db, t, user, nxt, to) if to and nxt else []
    if nxt and not sent_to and not _role_users(db, t, nxt) and not db.scalar(select(TicketRecipient.id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == nxt).limit(1)):
        raise ReviewError(422, f"Choose the {nxt} who receives the GPs (name and e-mail)")

    role = "ADMIN" if user.is_admin and step.role not in _ticket_roles(db, t, user) else step.role
    at = now()
    sub = TicketProgress(ticket_id=t.id, submitted_by_id=user.id, submitted_by_name=user.name, submitted_at=at, note=f"{step.label}" + (f": {text}" if text else ""))
    db.add(sub)
    db.flush()
    for g in gps:
        new_cat: str | None = None
        if action == "AM_APPROVE" and g.gp_category == "A":
            new_cat = "B"
        elif action == "SME_FORWARD" and category != g.gp_category:
            new_cat = category
        elif action == "COH_LETTER":
            new_cat = tasks.ACHIEVED_CATEGORY
        before = tasks.cumulative(g)
        if new_cat:
            g.gp_category = new_cat
            g.reported = 1 if new_cat == tasks.ACHIEVED_CATEGORY else 0
        if action == "COH_LETTER":
            g.letter_date = on
        if action == "COH_AMC":
            g.amc_on = on
        g.review, g.review_at = step.to, at
        db.add(TicketProgressLine(
            progress_id=sub.id, task_gp_id=g.id, achieved_today=1 if tasks.cumulative(g) > before else 0, cumulative=tasks.cumulative(g), gap=g.target - tasks.cumulative(g),
            remark=f"{step.label}" + (f": {text}" if text else "") + (f" ({on:%d-%m-%Y})" if on else ""), category=new_cat,
        ))
        db.add(TicketGpReview(ticket_id=t.id, task_gp_id=g.id, role=role, action=action, category=g.gp_category, on_date=on, remark=text, actor_id=user.id, actor_name=user.name, at=at))
    codes = ", ".join(g.gp_code for g in gps[:10]) + (f" … (+{len(gps) - 10})" if len(gps) > 10 else "")
    n = len(gps)
    gp_word = f"{n} GP{'s' if n != 1 else ''}"
    to_text = f" · sent to {', '.join(f'{nxt} {r.name} <{r.email}>' for r in sent_to)}" if sent_to else ""
    _event(db, t, user, "REVIEW", t.status, t.status, f"{step.label}: {gp_word} ({codes})" + (f" · {text}" if text else "") + (f" · {on:%d-%m-%Y}" if on else "") + to_text)
    body = f"{user.name}: {step.label} – {gp_word} ({codes})" + (f". Remark: {text}" if text else "")
    title = f"{t.code}: {step.label}"
    if action == "AM_APPROVE":
        _notify(db, _role_users(db, t, "SME") - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} approved by the Area Manager – your review", body)
        _notify(db, _fe_users(db, t, gps) - {user.id}, t, "REVIEW", title, body)
    elif action == "AM_RETURN":
        _notify(db, _fe_users(db, t, gps) - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} returned for correction", body)
    elif action == "SME_FORWARD":
        _notify(db, _role_users(db, t, "COH") - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} forwarded by the SME – letter / AMC", body)
        _notify(db, _role_users(db, t, "AM") - {user.id}, t, "REVIEW", title, body)
    else:
        _notify(db, (_role_users(db, t, "AM") | _role_users(db, t, "SME") | _fe_users(db, t, gps) | _reviewers(db, t)) - {user.id}, t, "REVIEW", title, body)
    t.updated_at = at
    db.commit()
    return n, [r.id for r in sent_to]


def _ticket_roles(db: Session, t: Ticket, user: CurrentUser) -> set[str]:
    """The roles the user really has on the ticket (an admin acting for another role is recorded as ADMIN)."""
    mine = set(db.scalars(select(TicketRecipient.role).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id)))
    if not mine and t.assignee_id == user.id:
        mine.add("AM")
    return mine


def record(db: Session, t: Ticket, g: TicketTaskGp, user: CurrentUser, role: str, action: str, remark: str, at: dt.datetime) -> None:
    """FE / Area Manager edits of a GP (name, block) and added GPs – part of the GP's history (`at` = the time of the
    daily submission they came with)."""
    db.add(TicketGpReview(ticket_id=t.id, task_gp_id=g.id, role=role, action=action, category=g.gp_category, remark=remark[:MAX_REMARK], actor_id=user.id, actor_name=user.name, at=at))


def trails(db: Session, t: Ticket, gp_ids: set[int], iso) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    if not gp_ids:
        return out
    for r in db.scalars(select(TicketGpReview).where(TicketGpReview.ticket_id == t.id).order_by(TicketGpReview.at, TicketGpReview.id)):
        if r.task_gp_id not in gp_ids:
            continue
        out.setdefault(r.task_gp_id, []).append(
            {"role": r.role, "action": r.action, "label": ACTION_LABEL.get(r.action, r.action), "category": r.category, "date": r.on_date.isoformat() if r.on_date else None,
             "remark": r.remark, "by": r.actor_name, "at": iso(r.at)}
        )
    return out
