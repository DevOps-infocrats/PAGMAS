"""Review chain of the GPs of a task ticket, after the FE's daily progress:

    FE / Area Manager  classifies the GP: A Rectification Done · C Revisit Required · D Non-Doable – Proposed
                       (an A GP waiting for the Area Manager = "Pending AM Verification")
    Area Manager       AM_APPROVE (with a remark, to the SME(s) chosen): A becomes B "Ready for Letter Submission –
                       AM Approved"; the GP is forwarded only to those SMEs (ticket_gp_forwards) – an SME sees only
                       the GPs forwarded to them (task.sme_view)
                       AM_RETURN  (with the reason, back to the FE): the FE corrects it and submits again
    SME                SME_FORWARD an AM-approved GP forwarded to them to the COH, with the SME review remarks and the
                       confirmed category (B) – status "SME Reviewed – Forwarded to COH" (SOP step 7)
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

from ..models import Ticket, TicketGpForward, TicketGpReview, TicketProgress, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp
from ..security.deps import CurrentUser

FE_CATEGORIES = ("A", "C", "D")  # what the FE / Area Manager may choose in the daily progress
RETURNABLE = ("A", "C")  # the Area Manager returns Rectification Done (correction) / Revisit Required (recheck) to the FE
SME_CATEGORIES = ("B",)  # the SME's confirmed category (Non-Doable goes through app.tickets.nondoable)
# in the review chain: the FE / AM can no longer change the GP in the daily progress (the AM returns it to the FE if needed)
LOCKED = ("AM_APPROVED", "SME_RETURNED", "SME_FORWARDED", "COH_RETURNED", "LETTER_SUBMITTED", "AMC_CONVERTED", "ND_APPROVED")
# reviewed and approved by the Area Manager (SOP rule 4 – ticket closure); a GP the SME sent back is not
AM_REVIEWED = ("AM_APPROVED", "SME_FORWARDED", "COH_RETURNED", "LETTER_SUBMITTED", "AMC_CONVERTED", "ND_APPROVED")
MAX_REMARK = 1000
MAX_GPS = 500

# Workflow status wording of the SOP (Non-AMC GP Readiness & AMC Conversion) – the same labels in the API, the
# dashboard and the review history. PENDING_AM is derived (no review yet, FE marked Rectification Done).
PENDING_AM_LABEL = "Pending AM Verification"
REVIEW_LABEL = {
    None: "With FE",
    "RETURNED": "Returned to FE",
    "AM_APPROVED": "Ready for Letter Submission – AM Approved",
    "SME_RETURNED": "Returned to AM by SME",
    "SME_FORWARDED": "SME Reviewed – Forwarded to COH",
    "COH_RETURNED": "Returned to SME by COH",
    "LETTER_SUBMITTED": "Letter Submitted",
    "AMC_CONVERTED": "AMC Converted",
    "ND_APPROVED": "Closed – Non-Doable",
}


def stage_of(g: TicketTaskGp, nd_open: bool = False) -> str:
    """NONE (with the FE) · PENDING_AM (Rectification Done, waiting for the Area Manager) · or the review state."""
    if g.review:
        return g.review
    return "PENDING_AM" if g.gp_category == "A" and not nd_open else "NONE"


def stage_label(stage: str) -> str:
    return PENDING_AM_LABEL if stage == "PENDING_AM" else REVIEW_LABEL.get(None if stage == "NONE" else stage, stage)


@dataclass(frozen=True)
class Step:
    role: str  # AM | SME | COH
    label: str
    frm: tuple[str | None, ...]
    to: str
    remark: bool  # remark required
    date: bool = False  # date required


STEPS: dict[str, Step] = {
    # the AM verifies again a GP the SME sent back (SME_RETURNED) – approve it (again) or return it to the FE
    "AM_APPROVE": Step("AM", "Approved by Area Manager – Ready for Letter Submission", (None, "SME_RETURNED"), "AM_APPROVED", True),
    "AM_RETURN": Step("AM", "Returned to FE for correction / recheck", (None, "SME_RETURNED"), "RETURNED", True),
    # the SME forwards (again, after the COH sent it back) or sends it back to the AM (issue found) – reason required
    "SME_FORWARD": Step("SME", "SME Reviewed – Forwarded to COH", ("AM_APPROVED", "COH_RETURNED"), "SME_FORWARDED", True),
    "SME_RETURN": Step("SME", "Returned to AM by SME", ("AM_APPROVED", "COH_RETURNED"), "SME_RETURNED", True),
    "COH_LETTER": Step("COH", "Letter submitted (COH)", ("SME_FORWARDED",), "LETTER_SUBMITTED", False, True),
    "COH_AMC": Step("COH", "AMC converted (COH)", ("LETTER_SUBMITTED",), "AMC_CONVERTED", False, True),
    "COH_RETURN": Step("COH", "Returned to SME by COH", ("SME_FORWARDED",), "COH_RETURNED", True),
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
        raise ReviewError(422, "Choose the confirmed category (Ready for Letter Submission)")
    if action == "SME_FORWARD" and category not in SME_CATEGORIES:
        raise ReviewError(422, "The SME confirms Ready for Letter Submission – a Non-Doable GP goes through its Non-Doable case")
    ids = list(dict.fromkeys(int(i) for i in gp_ids))
    if not ids or len(ids) > MAX_GPS:
        raise ReviewError(422, f"Select between 1 and {MAX_GPS} GPs")
    # FOR UPDATE (PostgreSQL): two simultaneous requests for the same GP wait for each other, so the state check below
    # sees the first one's result and a GP is never approved / forwarded twice (SQLite ignores it).
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id, TicketTaskGp.id.in_(ids)).with_for_update()))
    if len(gps) != len(ids):
        raise ReviewError(422, "A selected GP is not part of this ticket")
    from .task import sme_view

    view = sme_view(db, t, user)  # an SME acts only on the GPs forwarded to them (the same answer as a GP of another ticket)
    if view is not None and not all(view.owns(g) for g in gps):
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
        if action == "AM_RETURN":
            # the AM sends back what the FE reported: Rectification Done (correction) or Revisit Required (recheck) –
            # an untouched GP has nothing to review; Non-Doable goes through its own case
            if g.gp_category not in RETURNABLE:
                raise ReviewError(422, f"GP {g.gp_code}: only a GP the FE marked Rectification Done or Revisit Required can be returned to the FE")
            last = nd.last_case(db, g.id)
            if g.gp_category == "C" and last is not None and last.status == "REJECTED" and last.revisit_status != "REVIEWED":
                raise ReviewError(409, f"GP {g.gp_code} is in the FRT revisit of Non-Doable case {last.ref} – the FE coordinates it in Non-Doable Cases")
        if action == "COH_LETTER" and g.gp_category != "B":
            raise ReviewError(422, f"GP {g.gp_code} is confirmed Non-Doable – there is no letter to submit")

    nxt = NEXT_ROLE.get(action)
    if to and nxt is None:
        raise ReviewError(422, "This step is not sent to anybody")
    sent_to = _add_to(db, t, user, nxt, to) if to and nxt else []
    if nxt and not sent_to and not _role_users(db, t, nxt) and not db.scalar(select(TicketRecipient.id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == nxt).limit(1)):
        raise ReviewError(422, f"Choose the {nxt} who receives the GPs (name and e-mail)")
    # who the GPs are forwarded to: the people chosen now, else every SME / COH already on the ticket (as before)
    targets: list[TicketRecipient] = []
    if nxt:
        pool = sent_to or list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == nxt).order_by(TicketRecipient.id)))
        targets = list({r.id: r for r in pool}.values())

    role = "ADMIN" if user.is_admin and step.role not in _ticket_roles(db, t, user) else step.role
    at = now()
    sub = TicketProgress(ticket_id=t.id, submitted_by_id=user.id, submitted_by_name=user.name, submitted_at=at, note=f"{step.label}" + (f": {text}" if text else ""))
    db.add(sub)
    db.flush()
    steps: list[tuple[TicketTaskGp, TicketGpReview]] = []
    for g in gps:
        new_cat: str | None = None
        if action == "AM_APPROVE" and g.gp_category == "A":
            new_cat = "B"
        elif action == "SME_FORWARD" and category != g.gp_category:
            new_cat = category
        elif action == "COH_LETTER":
            new_cat = tasks.ACHIEVED_CATEGORY
        elif action == "SME_RETURN" and g.gp_category != "A":
            new_cat = "A"  # back to Rectification Done: the Area Manager verifies it again (approve / return to FE)
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
        row = TicketGpReview(ticket_id=t.id, task_gp_id=g.id, role=role, action=action, category=g.gp_category, on_date=on, remark=text, actor_id=user.id, actor_name=user.name, at=at)
        db.add(row)
        steps.append((g, row))
    if targets:  # GP-level forwarding: exactly which SME / COH received each GP
        db.flush()
        for g, row in steps:
            for r in targets:
                db.add(TicketGpForward(ticket_id=t.id, task_gp_id=g.id, review_id=row.id, recipient_id=r.id, action=action, role=nxt, at=at))
    target_users = {r.user_id for r in targets if r.user_id is not None}
    codes = ", ".join(g.gp_code for g in gps[:10]) + (f" … (+{len(gps) - 10})" if len(gps) > 10 else "")
    n = len(gps)
    gp_word = f"{n} GP{'s' if n != 1 else ''}"
    to_text = f" · sent to {', '.join(f'{nxt} {r.name} <{r.email}>' for r in sent_to)}" if sent_to else ""
    _event(db, t, user, "REVIEW", t.status, t.status, f"{step.label}: {gp_word} ({codes})" + (f" · {text}" if text else "") + (f" · {on:%d-%m-%Y}" if on else "") + to_text)
    body = f"{user.name}: {step.label} – {gp_word} ({codes})" + (f". Remark: {text}" if text else "")
    title = f"{t.code}: {step.label}"
    if action == "AM_APPROVE":
        _notify(db, target_users - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} approved by the Area Manager – your review", body)  # only the SMEs it went to
        _notify(db, _fe_users(db, t, gps) - {user.id}, t, "REVIEW", title, body)
    elif action == "AM_RETURN":
        why = "sent back to recheck (Revisit Required)" if all(g.gp_category == "C" for g in gps) else "returned for correction" if all(g.gp_category == "A" for g in gps) else "returned for correction / recheck"
        _notify(db, _fe_users(db, t, gps) - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} {why}", body)
    elif action == "SME_FORWARD":
        _notify(db, target_users - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} forwarded by the SME – letter / AMC", body)  # only the COHs it went to
        _notify(db, _role_users(db, t, "AM") - {user.id}, t, "REVIEW", title, body)
    elif action == "SME_RETURN":  # back to the Area Manager of the ticket
        _notify(db, _role_users(db, t, "AM") - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} sent back to the Area Manager by the SME – verify again", body)
    elif action == "COH_RETURN":  # back to the SME(s) the AM last forwarded these GPs to, and the SME who forwarded them
        forwarders = set(db.scalars(select(TicketGpReview.actor_id).where(TicketGpReview.ticket_id == t.id, TicketGpReview.action == "SME_FORWARD", TicketGpReview.task_gp_id.in_([g.id for g in gps]), TicketGpReview.actor_id.is_not(None))))
        _notify(db, (_handed_to(db, t, gps, "AM_APPROVE") | forwarders) - {user.id}, t, "REVIEW", f"{t.code}: {gp_word} sent back to the SME by the COH – review again", body)
    else:
        _notify(db, (_role_users(db, t, "AM") | _role_users(db, t, "SME") | _fe_users(db, t, gps) | _reviewers(db, t)) - {user.id}, t, "REVIEW", title, body)
    t.updated_at = at
    db.commit()
    return n, [r.id for r in sent_to]


def _handed_to(db: Session, t: Ticket, gps: list[TicketTaskGp], action: str) -> set[int]:
    """User ids (accounts) the GPs were handed to by their latest `action` step. Steps from before forwards were
    recorded: every account with that role on the ticket."""
    ids = {g.id for g in gps}
    latest: dict[int, int] = {}
    for rid, gp in db.execute(select(TicketGpReview.id, TicketGpReview.task_gp_id).where(TicketGpReview.ticket_id == t.id, TicketGpReview.action == action).order_by(TicketGpReview.id)):
        if gp in ids:
            latest[gp] = rid
    rows = list(db.scalars(select(TicketRecipient.user_id).join(TicketGpForward, TicketGpForward.recipient_id == TicketRecipient.id).where(TicketGpForward.review_id.in_(list(latest.values())), TicketRecipient.user_id.is_not(None)))) if latest else []
    return set(rows) if rows else _role_users(db, t, NEXT_ROLE[action])


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
    cur: dict[int, str | None] = {}  # review state of each GP while walking its history (from → to of every step)
    for r in db.scalars(select(TicketGpReview).where(TicketGpReview.ticket_id == t.id).order_by(TicketGpReview.at, TicketGpReview.id)):
        if r.task_gp_id not in gp_ids:
            continue
        frm, to = _transition(r.action, cur.get(r.task_gp_id))
        if r.action in STEPS:
            cur[r.task_gp_id] = STEPS[r.action].to
        elif r.action == "ND_REOPEN":
            cur[r.task_gp_id] = None
        out.setdefault(r.task_gp_id, []).append(
            {"role": r.role, "action": r.action, "label": ACTION_LABEL.get(r.action, r.action), "category": r.category, "date": r.on_date.isoformat() if r.on_date else None,
             "remark": r.remark, "by": r.actor_name, "at": iso(r.at), "fromStatus": frm, "toStatus": to}
        )
    return out


def _transition(action: str, before: str | None) -> tuple[str | None, str | None]:
    """Workflow status before / after a review step (None for edits / additions). `before` = the GP's review state
    after its previous step; an Area Manager step on a GP without a review (or back from the FE) starts from the FE's
    submission (Pending AM Verification)."""
    step = STEPS.get(action)
    if step is None:
        return None, None
    if before not in step.frm and step.frm:  # e.g. a GP returned to the FE and submitted again (no review row for that)
        before = step.frm[0]
    frm = PENDING_AM_LABEL if before is None else REVIEW_LABEL.get(before, before)
    return frm, REVIEW_LABEL[step.to]


def records(db: Session, t: Ticket, gp_ids: set[int], iso) -> tuple[dict[int, dict[str, Any]], set[tuple[int | None, dt.datetime]]]:
    """Per GP the latest Area Manager approval (`amApproval`) and SME review (`smeReview`) – who, role, remark, when,
    category after the step and who it was forwarded to – read from the stored review rows (never rebuilt). Also the
    (user, time) of every review step of the ticket: the progress lines a step writes have the same, so they are never
    taken for the FE's own submission. `_amAt` = approval time (UTC) for the caller, not for the API."""
    rows = list(db.scalars(select(TicketGpReview).where(TicketGpReview.ticket_id == t.id, TicketGpReview.action.in_(tuple(STEPS))).order_by(TicketGpReview.at, TicketGpReview.id)))
    keys = {(r.actor_id, _utc(r.at)) for r in rows}
    mine = [r for r in rows if r.task_gp_id in gp_ids and r.action in ("AM_APPROVE", "SME_FORWARD", "SME_RETURN", "COH_RETURN")]
    sent: dict[int, list[tuple[str, str, Any]]] = {}
    if mine:
        q = (
            select(TicketGpForward.review_id, TicketRecipient.name, TicketRecipient.email, TicketGpForward.at)
            .join(TicketRecipient, TicketRecipient.id == TicketGpForward.recipient_id)
            .where(TicketGpForward.review_id.in_([r.id for r in mine]))
            .order_by(TicketGpForward.id)
        )
        for rid, name, email, at in db.execute(q):
            sent.setdefault(rid, []).append((name, email, at))
    out: dict[int, dict[str, Any]] = {}
    for r in mine:  # oldest first: the latest step of each kind wins
        to = sent.get(r.id, [])
        rec = {
            "by": r.actor_name, "role": r.role, "remark": r.remark, "at": iso(r.at), "category": r.category,
            "forwardedTo": [{"name": n, "email": e} for n, e, _ in to], "forwardedAt": iso(to[0][2]) if to else None,
        }
        slot = out.setdefault(r.task_gp_id, {})
        if r.action == "AM_APPROVE":
            slot["amApproval"], slot["_amAt"] = rec, _utc(r.at)
            slot.pop("sentBack", None)  # approved again after a send-back
        elif r.action == "SME_FORWARD":
            slot["smeReview"] = rec
            slot.pop("sentBack", None)
        else:  # the latest send-back (SME → AM, COH → SME) while it is still the GP's last step of the chain
            slot["sentBack"] = rec | {"action": r.action}
    return out, keys


def _utc(v: dt.datetime | None) -> dt.datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=dt.UTC))
