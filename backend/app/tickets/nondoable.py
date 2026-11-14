"""Non-Doable GP exception and approval workflow (FE → AM → SME → COH → Corporate Team – MGG).

    E1  FE        physical verification of the GP (visit date, visitor, location, reason, findings, evidence / photos)
    E2  FE        justification to the Area Manager (justification, FRT team / visit details, more evidence)
    E3  AM        forward to the SME (recommendation, SME chosen like the GP review) or return to the FE (reason)
    E4  SME       recommend Non-Doable to the COH (recommendation, COH chosen) or return to the AM (reason)
    E5  COH       forward to the Corporate Team – MGG (recommendation) or return to the FE / AM / SME (reason)
    E6  MGG       approve: the GP is closed as Non-Doable (locked; the ticket closes in the same transaction once every
                  GP is achieved or approved Non-Doable) · reject (reason): the GP goes back to Revisit Required and
                  the FE coordinates with the FRT team, records the new FRT site visit and reviews the GP again

A case is created when the FE (or the Area Manager for a GP without a Field Engineer) chooses "Non-Doable – Proposed"
in the daily progress; it belongs to that GP of that ticket – no new ticket or GP. Forms, steps and files are new rows,
never edited (complete history in nd_events). Each step changes the status only from the expected one (a conditional
update – two people cannot act on the same stage twice). Admins see every case but cannot act; only an account an
admin authorised as Corporate Team – MGG (nd_mgg_members) approves or rejects.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    NdCase, NdEvent, NdFile, NdForward, NdMggMember, NdMggPick, NdRecord, Ticket, TicketProgress, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp, User,
)
from ..security.deps import CurrentUser
from . import files

MGG = "Corporate Team – MGG"
STATUS_LABEL = {
    "PROPOSED": "Non-Doable – Proposed",
    "E1_DONE": "E1 Completed – Pending FE Justification",
    "PENDING_AM": "Non-Doable – Pending AM Review",
    "RETURNED_FE": "Returned to FE – Correction Required",
    "PENDING_SME": "Non-Doable – Pending SME Review",
    "RETURNED_AM": "Returned to AM – Correction Required",
    "RETURNED_SME": "Returned to SME – Correction Required",
    "PENDING_COH": "Non-Doable – Pending COH Review",
    "PENDING_MGG": "Non-Doable – Pending MGG Approval",
    "APPROVED": "Non-Doable – Approved",
    "REJECTED": "Rejected – Action Required",
    "WITHDRAWN": "Withdrawn by FE",
}
REVISIT_LABEL = {
    "COORDINATION": "Revisit – FE coordinating with the FRT team",
    "FRT_VISIT": "Revisit – New FRT site visit pending",
    "FRT_UPDATED": "Revisit – FRT updated, FE review pending",
    "REVIEWED": "Revisit – Reviewed by FE",
}
PHYSICAL_LABEL = {"PENDING": "Pending", "SUBMITTED": "Physical verification submitted"}
EVIDENCE_LABEL = {"NONE": "No evidence", "SUBMITTED": "Evidence submitted"}
APPROVAL_LABEL = {"NOT_SUBMITTED": "Not submitted", "IN_REVIEW": "In review", "RETURNED": "Returned for correction", "APPROVED": "Approved", "REJECTED": "Rejected", "WITHDRAWN": "Withdrawn"}
OPEN = ("PROPOSED", "E1_DONE", "PENDING_AM", "RETURNED_FE", "PENDING_SME", "RETURNED_AM", "RETURNED_SME", "PENDING_COH", "PENDING_MGG")
PENDING_WITH = {
    "PROPOSED": "FE", "E1_DONE": "FE", "RETURNED_FE": "FE", "PENDING_AM": "AM", "RETURNED_AM": "AM", "PENDING_SME": "SME", "RETURNED_SME": "SME",
    "PENDING_COH": "COH", "PENDING_MGG": MGG,
}
STAGES = ("E1", "E2", "E3", "E4", "E5", "E6")
STAGE_LABEL = {
    "E1": "FE Physical Verification", "E2": "FE Justification to AM", "E3": "AM Review", "E4": "SME Review", "E5": "COH Review", "E6": "Corporate Team – MGG Decision",
}
ROLE_LABEL = {"FE": "Field Engineer", "AM": "Area Manager", "SME": "SME", "COH": "COH", "MGG": MGG, "ADMIN": "Admin"}
ND_REVIEW = "ND_APPROVED"  # TicketTaskGp.review of a GP closed as Non-Doable (locked, see review.LOCKED)
MAX_TEXT = 2000
MAX_FILES = 10  # per form
PHOTO_TYPES = ("image/jpeg", "image/png")


@dataclass(frozen=True)
class Step:
    role: str  # FE | AM | SME | COH | MGG
    stage: str
    label: str
    frm: tuple[str, ...]
    to: str  # COH_RETURN: chosen target


STEPS: dict[str, Step] = {
    "AM_FORWARD": Step("AM", "E3", "Forwarded by AM to SME", ("PENDING_AM", "RETURNED_AM"), "PENDING_SME"),
    "AM_RETURN": Step("AM", "E3", "Returned by AM to FE", ("PENDING_AM", "RETURNED_AM"), "RETURNED_FE"),
    "SME_RECOMMEND": Step("SME", "E4", "Recommended Non-Doable by SME to COH", ("PENDING_SME", "RETURNED_SME"), "PENDING_COH"),
    "SME_RETURN": Step("SME", "E4", "Returned by SME to AM", ("PENDING_SME", "RETURNED_SME"), "RETURNED_AM"),
    "COH_FORWARD": Step("COH", "E5", f"Forwarded by COH to {MGG}", ("PENDING_COH",), "PENDING_MGG"),
    "COH_RETURN": Step("COH", "E5", "Returned by COH for correction", ("PENDING_COH",), ""),
    "MGG_APPROVE": Step("MGG", "E6", f"Approved Non-Doable by {MGG}", ("PENDING_MGG",), "APPROVED"),
    "MGG_REJECT": Step("MGG", "E6", f"Rejected by {MGG} – action required", ("PENDING_MGG",), "REJECTED"),
    "WITHDRAW": Step("FE", "E2", "Proposal withdrawn by FE", ("PROPOSED", "E1_DONE", "RETURNED_FE"), "WITHDRAWN"),
}
COH_TARGETS = {"FE": "RETURNED_FE", "AM": "RETURNED_AM", "SME": "RETURNED_SME"}
ACTION_LABEL = {
    **{k: s.label for k, s in STEPS.items()},
    "PROPOSED": "Non-Doable proposed in the daily progress",
    "VERIFICATION": "E1 physical verification submitted",
    "JUSTIFICATION": "E2 justification submitted to AM",
    "REVISIT_COORDINATION": "FRT coordination recorded",
    "REVISIT_VISIT": "New FRT site visit recorded",
    "REVISIT_REVIEWED": "GP reviewed by FE after the FRT visit",
}


class NdError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _text(v: Any, limit: int = MAX_TEXT) -> str | None:
    return (str(v).strip()[:limit] or None) if v is not None else None


def _need(v: Any, what: str, minimum: int = 3, limit: int = MAX_TEXT) -> str:
    s = _text(v, limit)
    if s is None or len(s) < minimum:
        raise NdError(422, f"{what} is required" + (f" (at least {minimum} characters)" if minimum > 1 else ""))
    return s


# ---------------------------------------------------------------- who is who


def is_mgg(db: Session, user: CurrentUser) -> bool:
    return db.scalar(select(NdMggMember.id).join(User, User.id == NdMggMember.user_id).where(NdMggMember.user_id == user.id, User.is_active.is_(True))) is not None


def mgg_people(db: Session) -> list[User]:
    return list(db.scalars(select(User).join(NdMggMember, NdMggMember.user_id == User.id).where(User.is_active.is_(True)).order_by(User.name)))


def _mgg_picks(db: Session, c: NdCase) -> list[NdMggPick]:
    """The MGG people the COH chose / typed in the case's LATEST forward (empty = not forwarded yet, or forwarded to
    every authorised MGG account without a choice – as before)."""
    ev = db.scalar(select(NdEvent.id).where(NdEvent.case_id == c.id, NdEvent.action == "COH_FORWARD").order_by(NdEvent.id.desc()).limit(1))
    return [] if ev is None else list(db.scalars(select(NdMggPick).where(NdMggPick.event_id == ev).order_by(NdMggPick.id)))


def _picked(db: Session, c: NdCase, user: CurrentUser) -> bool:
    """The user's e-mail is one the COH forwarded this case to (decides THIS case, like an authorised MGG account)."""
    me = (user.email or "").strip().lower()
    return bool(me) and any(p.email == me for p in _mgg_picks(db, c))


def _mgg_to(db: Session, user: CurrentUser, to: list[dict[str, str]]) -> list[tuple[str, str]]:
    """(name, e-mail) of the MGG people chosen / typed by the COH – valid, distinct addresses, never the COH."""
    from ..mail.smtp import valid_address

    if len(to) > 10:
        raise NdError(422, f"At most 10 {MGG} e-mails")
    accounts = {u.email.lower(): u.name for u in db.scalars(select(User).where(User.is_active.is_(True)))}
    me = (user.email or "").strip().lower()
    out: dict[str, str] = {}
    for it in to:
        addr = valid_address(it.get("email"))
        if addr is None:
            raise NdError(422, f"'{str(it.get('email') or '')[:80]}' is not a valid e-mail address")
        addr = addr.lower()
        if addr == me:
            raise NdError(422, f"You cannot forward the case to yourself – choose the {MGG} person who decides it")
        name = " ".join(str(it.get("name") or "").split())[:160]
        out.setdefault(addr, name or accounts.get(addr) or addr.split("@")[0])
    return [(n, e) for e, n in out.items()]


def _fe_recipients(db: Session, t: Ticket, g: TicketTaskGp) -> list[TicketRecipient]:
    from .task import FeScope

    return [r for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE")) if FeScope(r.name, r.fe_mail).owns(g)]


def _ams(db: Session, t: Ticket) -> list[tuple[int | None, str, str]]:
    """(user id, name, e-mail) of the Area Manager(s): AM recipients, else the assignee."""
    out = [(r.user_id, r.name, r.email) for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "AM"))]
    if not out and t.assignee_id:
        u = db.get(User, t.assignee_id)
        if u is not None:
            out.append((u.id, u.name, u.email))
    return out


# the step that hands a case to each reviewer role (the people chosen in it are kept in nd_forwards)
HANDED_BY = {"SME": "AM_FORWARD", "COH": "SME_RECOMMEND"}


def _current(db: Session, c: NdCase, role: str) -> set[int] | None:
    """Recipient ids the case is with for SME / COH: the people chosen in its LATEST handing step. Empty set = not
    handed to that role yet; None = handed before the choice was recorded (every SME / COH of the ticket, as before)."""
    ev = db.scalar(select(NdEvent.id).where(NdEvent.case_id == c.id, NdEvent.action == HANDED_BY[role]).order_by(NdEvent.id.desc()).limit(1))
    if ev is None:
        return set()
    return set(db.scalars(select(NdForward.recipient_id).where(NdForward.event_id == ev))) or None


def _holds(db: Session, c: NdCase, t: Ticket, user: CurrentUser, role: str) -> bool:
    """The user is the SME / COH this case was handed to (an old case: any SME / COH of the ticket)."""
    cur = _current(db, c, role)
    if cur == set():
        return False
    rows = db.execute(select(TicketRecipient.id, TicketRecipient.role).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id)).all()
    if cur is None:
        return any(r.role == role for r in rows)
    return any(r.id in cur for r in rows)  # the person explicitly chosen (whatever their other role on the ticket)


def _people(db: Session, t: Ticket, g: TicketTaskGp, role: str, c: NdCase | None = None) -> list[tuple[int | None, str, str]]:
    """(user id, name, e-mail) of the people of a role for this case (FE: the GP's FE, else the Area Manager; SME / COH:
    only the people the case was handed to – for an old case every SME / COH of the ticket)."""
    if role == "FE":
        fes = [(r.user_id, r.name, r.email) for r in _fe_recipients(db, t, g)]
        return fes or _ams(db, t)
    if role == "AM":
        return _ams(db, t)
    if role in ("SME", "COH"):
        cur = _current(db, c, role) if c is not None else None
        rows = db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.id.in_(cur)) if cur else select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == role))
        return [] if cur == set() else [(r.user_id, r.name, r.email) for r in rows]
    if role == "MGG":  # the people the COH chose / typed, else every authorised MGG account (as before)
        picks = _mgg_picks(db, c) if c is not None else []
        if picks:
            users = {u.email.lower(): u.id for u in db.scalars(select(User).where(func.lower(User.email).in_([p.email for p in picks]), User.is_active.is_(True)))}
            return [(users.get(p.email), p.name, p.email) for p in picks]
        return [(u.id, u.name, u.email) for u in mgg_people(db)]
    return []


def _roles_on(db: Session, t: Ticket, user: CurrentUser) -> set[str]:
    """The user's real roles on the ticket (admins get no acting role here)."""
    mine = set(db.scalars(select(TicketRecipient.role).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id)))
    if not mine and t.assignee_id == user.id:
        mine.add("AM")
    return mine & {"FE", "AM", "SME", "COH"}


def is_fe_actor(db: Session, t: Ticket, g: TicketTaskGp, user: CurrentUser) -> bool:
    """The GP's Field Engineer – or the Area Manager when no FE recipient owns the GP (same rule as the daily progress)."""
    fes = _fe_recipients(db, t, g)
    if fes:
        return any(r.user_id == user.id for r in fes)
    return "AM" in _roles_on(db, t, user)


def _reached(db: Session, case_id: int, actions: tuple[str, ...]) -> bool:
    return db.scalar(select(NdEvent.id).where(NdEvent.case_id == case_id, NdEvent.action.in_(actions)).limit(1)) is not None


def roles_for(db: Session, c: NdCase, t: Ticket, g: TicketTaskGp, user: CurrentUser) -> set[str]:
    """Roles of the user on this case: FE / AM / SME (once the AM forwarded it) / COH (once the SME recommended it) /
    MGG (once the COH forwarded it). Empty = no access (admins read every case through `can_view`)."""
    out: set[str] = set()
    on = _roles_on(db, t, user)
    if is_fe_actor(db, t, g, user):
        out.add("FE")
    if "AM" in on:
        out.add("AM")
    # SME / COH: only the person the case was handed to (AM forward / SME recommendation), not every SME / COH of the ticket
    if _holds(db, c, t, user, "SME"):
        out.add("SME")
    if _holds(db, c, t, user, "COH"):
        out.add("COH")
    if _reached(db, c.id, ("COH_FORWARD",)) and (is_mgg(db, user) or _picked(db, c, user)):
        out.add("MGG")
    return out


def _load(db: Session, case_id: int, user: CurrentUser) -> tuple[NdCase, Ticket, TicketTaskGp, set[str]]:
    c = db.get(NdCase, case_id)
    t = db.get(Ticket, c.ticket_id) if c is not None else None
    g = db.get(TicketTaskGp, c.task_gp_id) if c is not None else None
    if c is None or t is None or g is None or t.deleted_at is not None:
        raise NdError(404, "Non-Doable case not found")
    roles = roles_for(db, c, t, g, user)
    if not roles and not user.is_admin:
        raise NdError(404, "Non-Doable case not found")
    return c, t, g, roles


def open_case(db: Session, task_gp_id: int) -> NdCase | None:
    return db.scalars(select(NdCase).where(NdCase.task_gp_id == task_gp_id, NdCase.status.in_(OPEN)).limit(1)).first()


def last_case(db: Session, task_gp_id: int) -> NdCase | None:
    return db.scalars(select(NdCase).where(NdCase.task_gp_id == task_gp_id).order_by(NdCase.id.desc()).limit(1)).first()


# ---------------------------------------------------------------- hooks of the daily progress (app.tickets.task)


def check_progress(db: Session, g: TicketTaskGp, new_cat: str | None) -> None:
    """Before a daily progress line: a GP with an open case continues only in this workflow; after a rejection the GP
    can be proposed Non-Doable again only after the new FRT site visit is recorded."""
    c = open_case(db, g.id)
    if c is not None:
        raise NdError(409, f"GP {g.gp_code} is in Non-Doable case {c.ref} ({STATUS_LABEL[c.status]}) – continue it in Non-Doable Cases")
    if new_cat == "D":
        last = last_case(db, g.id)
        if last is not None and last.status == "REJECTED" and last.revisit_status not in ("FRT_UPDATED", "REVIEWED"):
            raise NdError(422, f"GP {g.gp_code}: Non-Doable was rejected ({last.ref}) – record the FRT coordination and the new FRT site visit before proposing it again")


def on_progress(db: Session, t: Ticket, g: TicketTaskGp, user: CurrentUser, new_cat: str | None, remark: str | None, at: dt.datetime) -> NdCase | None:
    """After a daily progress line (same transaction): "Non-Doable – Proposed" opens a case; a GP reviewed after the
    FRT update closes the revisit of the rejected case."""
    last = last_case(db, g.id)
    if new_cat and last is not None and last.status == "REJECTED" and last.revisit_status == "FRT_UPDATED":
        last.revisit_status, last.updated_at = "REVIEWED", at
        _event(db, last, user, "RV", "REVISIT_REVIEWED", "FE", last.status, last.status, remark=f"Category chosen: {new_cat}" + (f" – {remark}" if remark else ""), at=at)
    if new_cat != "D":
        return None
    fe = _fe_recipients(db, t, g)
    c = NdCase(
        ticket_id=t.id, task_gp_id=g.id, gp_code=g.gp_code, round=(last.round + 1) if last is not None else 1, status="PROPOSED",
        fe_name=fe[0].name if fe else g.fe_name, fe_email=fe[0].email if fe else g.fe_email, created_by_id=user.id, created_by_name=user.name, created_at=at, updated_at=at,
    )
    db.add(c)
    db.flush()
    c.ref = f"ND-{c.id:06d}"
    _event(db, c, user, "E1", "PROPOSED", "FE", None, "PROPOSED", remark=remark, at=at)
    return c


# ---------------------------------------------------------------- writing


def _event(
    db: Session, c: NdCase, user: CurrentUser, stage: str, action: str, role: str, frm: str | None, to: str, *, remark: str | None = None,
    recommendation: str | None = None, reason: str | None = None, decision: str | None = None, record_id: int | None = None, at: dt.datetime | None = None,
) -> NdEvent:
    ev = NdEvent(
        case_id=c.id, ticket_id=c.ticket_id, task_gp_id=c.task_gp_id, stage=stage, action=action, role=role, from_status=frm, to_status=to, remark=remark,
        recommendation=recommendation, reason=reason, decision=decision, record_id=record_id, actor_id=user.id, actor_name=user.name, at=at or now(),
    )
    db.add(ev)
    return ev


def _move(db: Session, c: NdCase, frm: tuple[str, ...], to: str, **values: Any) -> str:
    """Conditional status change: only while the case is still in one of `frm` (a second click / another person
    acting at the same time gets 409)."""
    before = c.status
    res = db.execute(update(NdCase).where(NdCase.id == c.id, NdCase.status.in_(frm)).values(status=to, updated_at=now(), **values).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        db.rollback()
        raise NdError(409, "This case was changed meanwhile – the action is no longer possible. Reload the case.")
    db.refresh(c)
    return before


@dataclass
class Upload:
    kind: str  # EVIDENCE | PHOTO
    file_name: str | None
    content_type: str | None
    stream: Any


def _check_files(uploads: list[Upload]) -> None:
    if len(uploads) > MAX_FILES:
        raise NdError(422, f"At most {MAX_FILES} files per form")
    for u in uploads:
        try:
            files.check_meta(u.file_name, u.content_type)
        except files.AttachmentError as exc:
            raise NdError(exc.status, str(exc)) from None
        if u.kind == "PHOTO" and (u.content_type or "").split(";")[0].strip().lower() not in PHOTO_TYPES:
            raise NdError(422, f"{u.file_name}: a site photograph must be a JPEG or PNG image")


def _store(db: Session, c: NdCase, rec: NdRecord, user: CurrentUser, uploads: list[Upload], stored: list[str]) -> None:
    budget = get_settings().ticket_upload_max_mb * 1024 * 1024
    for u in uploads:
        try:
            f = files.save(c.ticket_id, u.file_name, u.content_type, u.stream, budget)
        except files.AttachmentError as exc:
            raise NdError(exc.status, str(exc)) from None
        stored.append(f.stored_name)
        budget -= f.size
        db.add(NdFile(
            case_id=c.id, ticket_id=c.ticket_id, record_id=rec.id, kind=u.kind, file_name=f.file_name, stored_name=f.stored_name, content_type=f.content_type,
            size=f.size, sha256=f.sha256, uploaded_by_name=user.name, uploaded_at=now(),
        ))


Mail = list[tuple[str, str]]  # (name, e-mail) – one e-mail per address


def _announce(db: Session, c: NdCase, t: Ticket, g: TicketTaskGp, user: CurrentUser, roles: tuple[str, ...], title: str, body: str) -> Mail:
    """Dashboard notification (kind NONDOABLE, one per person) and the e-mail list of the people of these roles."""
    from .service import _notify

    ids: set[int] = set()
    mail: dict[str, str] = {}
    for role in roles:
        for uid, name, email in _people(db, t, g, role, c):
            if uid is not None and uid != user.id:
                ids.add(uid)
            if email and uid != user.id and email.lower() != (user.email or "").lower():
                mail.setdefault(email.lower(), name)
    _notify(db, ids, t, "NONDOABLE", f"{t.code} · {c.ref}: {title}", body)
    return list(mail.items())


def _closed(t: Ticket) -> None:
    if t.status == "CLOSED":
        raise NdError(409, "This ticket is closed – the Non-Doable case cannot change any more")


def submit_form(db: Session, case_id: int, user: CurrentUser, kind: str, data: dict[str, Any], uploads: list[Upload]) -> tuple[NdCase, Mail, int]:
    """FE forms: VERIFICATION (E1), JUSTIFICATION (E2), REVISIT_COORDINATION / REVISIT_VISIT (after a rejection).
    Returns the case, the e-mail list and the audit event id."""
    c, t, g, roles = _load(db, case_id, user)
    _closed(t)
    if "FE" not in roles:
        raise NdError(403, "Only the Field Engineer of this GP can submit this form")
    _check_files(uploads)
    at = now()
    rec = NdRecord(case_id=c.id, kind=kind, created_by_id=user.id, created_by_name=user.name, created_at=at)
    if kind == "VERIFICATION":
        if c.status not in ("PROPOSED", "E1_DONE", "RETURNED_FE"):
            raise NdError(409, f"The case is '{STATUS_LABEL[c.status]}' – the physical verification cannot be submitted now")
        rec.visit_date = _visit_date(data.get("visitDate"))
        rec.visitor_name = _need(data.get("visitorName"), "Visitor name", 2, 160)
        rec.location = _text(data.get("location"), 300)
        rec.reason = _need(data.get("reason"), "Non-Doable reason")
        rec.findings = _need(data.get("findings"), "Findings")
        rec.remarks = _text(data.get("remarks"))
        has_files = bool(uploads) or db.scalar(select(NdFile.id).where(NdFile.case_id == c.id).limit(1)) is not None
        if not has_files:
            raise NdError(422, "Attach the evidence / site photographs of the physical verification")
        to, stage, frm = "E1_DONE", "E1", c.status
        values: dict[str, Any] = {"physical_status": "SUBMITTED"}
    elif kind == "JUSTIFICATION":
        if c.status not in ("E1_DONE", "RETURNED_FE") or c.physical_status != "SUBMITTED":
            raise NdError(409, "Submit the E1 physical verification first" if c.physical_status != "SUBMITTED" else f"The case is '{STATUS_LABEL[c.status]}' – the justification cannot be submitted now")
        rec.justification = _need(data.get("justification"), "Justification", 10)
        rec.frt_team = _need(data.get("frtTeam"), "FRT team details")
        rec.frt_visit = _need(data.get("frtVisit"), "FRT visit details")
        rec.remarks = _text(data.get("remarks"))
        to, stage, frm = "PENDING_AM", "E2", c.status
        values = {"approval_status": "IN_REVIEW"}
    elif kind == "REVISIT_COORDINATION":
        if c.status != "REJECTED" or c.revisit_status != "COORDINATION":
            raise NdError(409, "The FRT coordination is recorded after a rejection by the Corporate Team – MGG")
        rec.frt_team = _need(data.get("frtTeam"), "FRT team details")
        rec.remarks = _need(data.get("remarks"), "Coordination details")
        to, stage, frm = c.status, "RV", c.status
        values = {"revisit_status": "FRT_VISIT"}
    elif kind == "REVISIT_VISIT":
        if c.status != "REJECTED" or c.revisit_status != "FRT_VISIT":
            raise NdError(409, "Record the FRT coordination first")
        rec.visit_date = _visit_date(data.get("visitDate"))
        rec.visitor_name = _need(data.get("visitorName"), "FRT visitor name", 2, 160)
        rec.location = _text(data.get("location"), 300)
        rec.findings = _need(data.get("findings"), "Findings of the FRT visit")
        rec.outcome = data.get("outcome") if data.get("outcome") in ("A", "C", "D") else None
        if rec.outcome is None:
            raise NdError(422, "Choose the outcome of the FRT visit: Rectification Done, Revisit Required or Non-Doable")
        rec.remarks = _text(data.get("remarks"))
        to, stage, frm = c.status, "RV", c.status
        values = {"revisit_status": "FRT_UPDATED"}
    else:
        raise NdError(422, "Unknown form")
    if uploads:
        values["evidence_status"] = "SUBMITTED"
    stored: list[str] = []
    try:
        if to != frm:
            _move(db, c, (frm,), to, **values)
        else:
            res = db.execute(update(NdCase).where(NdCase.id == c.id, NdCase.revisit_status == c.revisit_status).values(updated_at=at, **values).execution_options(synchronize_session=False))
            if res.rowcount != 1:
                raise NdError(409, "This case was changed meanwhile – reload the case.")
            db.refresh(c)
        db.add(rec)
        db.flush()
        _store(db, c, rec, user, uploads, stored)
        ev = _event(db, c, user, stage, kind, "FE", frm, c.status, remark=rec.remarks, reason=rec.reason, record_id=rec.id, at=at)
        what = {
            "VERIFICATION": ("E1 physical verification submitted", f"{user.name} submitted the physical verification of GP {g.gp_code} ({g.gp_name}). The justification (E2) follows."),
            "JUSTIFICATION": ("Non-Doable – Pending AM Review", f"{user.name} submitted the Non-Doable justification of GP {g.gp_code} ({g.gp_name}) – your review: forward to the SME or return to the FE."),
            "REVISIT_COORDINATION": ("FRT coordination recorded", f"{user.name} recorded the coordination with the FRT team for GP {g.gp_code} after the rejection."),
            "REVISIT_VISIT": ("New FRT site visit recorded", f"{user.name} recorded the new FRT site visit of GP {g.gp_code} – the FE reviews the GP in the daily progress."),
        }[kind]
        mail = _announce(db, c, t, g, user, ("AM",), *what)
        t.updated_at = at
        db.commit()
    except BaseException:
        db.rollback()
        files.remove(c.ticket_id, stored)
        raise
    return c, mail, ev.id


def _visit_date(v: Any) -> dt.date:
    try:
        d = v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v or ""))
    except ValueError:
        raise NdError(422, "Enter the visit date") from None
    today = dt.date.today()
    if d > today or d < today - dt.timedelta(days=366):
        raise NdError(422, "The visit date must be within the last year and not in the future")
    return d


def act(db: Session, case_id: int, user: CurrentUser, action: str, remark: str | None, reason: str | None, target: str | None, to: list[dict[str, str]] | None) -> tuple[NdCase, Mail, int, list[int]]:
    """AM / SME / COH / MGG steps and the FE's withdrawal. Returns the case, the e-mail list, the audit event id and
    the SME / COH recipient ids chosen in `to` (put on the ticket like the GP review)."""
    from . import review
    from . import task as tasks
    from .service import _event as ticket_event
    from .service import _move as ticket_move

    step = STEPS.get(action)
    if step is None:
        raise NdError(422, "Unknown action")
    c, t, g, roles = _load(db, case_id, user)
    _closed(t)
    if step.role not in roles:
        if step.role == "MGG":
            raise NdError(403, f"Only the {MGG} can approve or reject a Non-Doable case")
        raise NdError(403, f"Only the {ROLE_LABEL[step.role]} of this case can do this step")
    if c.status not in step.frm:
        raise NdError(409, f"The case is '{STATUS_LABEL[c.status]}' – this step is not possible now. Reload the case.")
    returning = action.endswith("_RETURN") or action == "MGG_REJECT"
    text = _text(remark)
    why = _need(reason, "The rejection reason" if action == "MGG_REJECT" else "The reason for returning the case") if returning else None
    recommendation = None
    if action in ("AM_FORWARD", "SME_RECOMMEND", "COH_FORWARD"):
        recommendation = _need(remark, "Your recommendation / remarks")
        text = None
    dest = step.to
    if action == "COH_RETURN":
        dest = COH_TARGETS.get(target or "", "")
        if not dest:
            raise NdError(422, "Choose to whom the case is returned: FE, AM or SME")
    nxt = {"AM_FORWARD": "SME", "SME_RECOMMEND": "COH"}.get(action)
    sent: list[TicketRecipient] = []
    if nxt:
        try:
            sent = review._add_to(db, t, user, nxt, to or []) if to else []
        except review.ReviewError as exc:
            raise NdError(exc.status, exc.message) from None
        if not sent and not db.scalar(select(TicketRecipient.id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == nxt).limit(1)):
            db.rollback()
            raise NdError(422, f"Choose the {nxt} who receives the case (name and e-mail)")
    mgg_to: list[tuple[str, str]] = []
    if action == "COH_FORWARD":  # to the MGG people chosen / typed by the COH, else every authorised MGG account
        mgg_to = _mgg_to(db, user, to or [])
        if not mgg_to and not mgg_people(db):
            raise NdError(422, f"No {MGG} account is authorised yet – type the name and e-mail of the {MGG} person who decides the case")
    at = now()
    values: dict[str, Any] = {}
    if returning and action != "MGG_REJECT":
        values["approval_status"] = "RETURNED"
    elif action in ("AM_FORWARD", "SME_RECOMMEND", "COH_FORWARD"):
        values["approval_status"] = "IN_REVIEW"
    elif action == "WITHDRAW":
        values["approval_status"] = "WITHDRAWN"
    elif action in ("MGG_APPROVE", "MGG_REJECT"):
        values.update(
            approval_status="APPROVED" if action == "MGG_APPROVE" else "REJECTED", decision="APPROVED" if action == "MGG_APPROVE" else "REJECTED",
            decided_by_id=user.id, decided_by_name=user.name, decided_at=at, decision_remark=why or text,
        )
        if action == "MGG_REJECT":
            values["revisit_status"] = "COORDINATION"
    try:
        frm = _move(db, c, step.frm, dest, **values)
        t = db.get(Ticket, c.ticket_id)
        g = db.get(TicketTaskGp, c.task_gp_id)
        closed_ticket = False
        if action in ("MGG_APPROVE", "MGG_REJECT", "WITHDRAW"):
            # the GP itself: closed as Non-Doable (locked) / back to Revisit Required / proposal withdrawn – a daily
            # progress line keeps the GP history, monitor and workbook in line
            new_cat = {"MGG_APPROVE": None, "MGG_REJECT": "C", "WITHDRAW": None}[action]
            label = {"MGG_APPROVE": f"Closed – Non-Doable ({c.ref}, approved by {MGG})", "MGG_REJECT": f"Non-Doable rejected ({c.ref}) – revisit required: {why}",
                     "WITHDRAW": f"Non-Doable proposal withdrawn ({c.ref})" + (f": {text}" if text else "")}[action]
            sub = TicketProgress(ticket_id=t.id, submitted_by_id=user.id, submitted_by_name=user.name, submitted_at=at, note=label[:2000])
            db.add(sub)
            db.flush()
            if action == "MGG_APPROVE":
                g.review, g.review_at = ND_REVIEW, at
            elif action == "MGG_REJECT":
                g.gp_category, g.reported = "C", 0
            else:
                g.gp_category = None
            db.add(TicketProgressLine(progress_id=sub.id, task_gp_id=g.id, achieved_today=0, cumulative=tasks.cumulative(g), gap=g.target - tasks.cumulative(g), remark=label[:500], category=new_cat))
            ticket_event(db, t, user, "NONDOABLE", t.status, t.status, f"{c.ref} · GP {g.gp_code}: {ACTION_LABEL[action]}" + (f" · {why or text}" if (why or text) else ""))
            if action == "MGG_APPROVE" and t.status != "CLOSED":
                gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id)))
                if gps and all(x.review == ND_REVIEW or tasks.cumulative(x) >= x.target for x in gps):
                    before = ticket_move(db, t, ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CHANGES_REQUESTED"), "CLOSED", closed_at=at, closed_by_id=user.id, closed_by_name=user.name)
                    ticket_event(db, t, user, "CLOSED", before, "CLOSED", f"Every GP is achieved or approved Non-Doable – closed with {c.ref}")
                    closed_ticket = True
        else:
            ticket_event(db, t, user, "NONDOABLE", t.status, t.status, f"{c.ref} · GP {g.gp_code}: {ACTION_LABEL[action]}" + (f" · {why or recommendation or text}" if (why or recommendation or text) else ""))
        ev = _event(db, c, user, step.stage, action, step.role, frm, c.status, remark=text, recommendation=recommendation, reason=why,
                    decision={"MGG_APPROVE": "APPROVED", "MGG_REJECT": "REJECTED"}.get(action), at=at)
        if nxt:  # who the case now goes to: the people chosen now, else every SME / COH already on the ticket (as before)
            pool = sent or list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == nxt).order_by(TicketRecipient.id)))
            db.flush()
            for r in {r.id: r for r in pool}.values():
                db.add(NdForward(case_id=c.id, event_id=ev.id, recipient_id=r.id, role=nxt, at=at))
            db.flush()  # the e-mail / notification list below reads them
        if sent:
            ev.remark = ((ev.remark + " · ") if ev.remark else "") + "Sent to " + ", ".join(f"{nxt} {r.name} <{r.email}>" for r in sent)
        if mgg_to:  # who decides the case now (the e-mail / notification list below reads them)
            db.flush()
            for name, email in mgg_to:
                db.add(NdMggPick(case_id=c.id, event_id=ev.id, name=name, email=email, at=at))
            db.flush()
            ev.remark = ((ev.remark + " · ") if ev.remark else "") + "Sent to " + ", ".join(f"MGG {n} <{e}>" for n, e in mgg_to)
        detail = why or recommendation or text
        body = f"{user.name}: {ACTION_LABEL[action]} – GP {g.gp_code} ({g.gp_name})" + (f". {'Reason' if why else 'Remarks'}: {detail}" if detail else "")
        who: tuple[str, ...] = {
            "AM_FORWARD": ("SME", "FE"), "AM_RETURN": ("FE",), "SME_RECOMMEND": ("COH", "AM"), "SME_RETURN": ("AM",), "COH_FORWARD": ("MGG", "SME", "AM"),
            "COH_RETURN": {"RETURNED_FE": ("FE", "AM"), "RETURNED_AM": ("AM",), "RETURNED_SME": ("SME", "AM")}.get(dest, ()), "MGG_APPROVE": ("FE", "AM", "SME", "COH"),
            "MGG_REJECT": ("FE", "AM", "SME", "COH"), "WITHDRAW": ("AM",),
        }[action]
        title = STATUS_LABEL[c.status] + (" · ticket closed" if closed_ticket else "")
        mail = _announce(db, c, t, g, user, who, title, body)
        t.updated_at = at
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return c, mail, ev.id, [r.id for r in sent]


# ---------------------------------------------------------------- reading


def _visible_cases(db: Session, user: CurrentUser) -> list[tuple[NdCase, set[str]]]:
    """(case, the user's roles on it) of every case the user may see (admins: all, with no role)."""
    from .service import _mine, deleted_ids

    q = select(NdCase).where(NdCase.ticket_id.not_in(deleted_ids())).order_by(NdCase.updated_at.desc(), NdCase.id.desc())
    mgg = is_mgg(db, user)
    me = (user.email or "").strip().lower()
    if not user.is_admin:
        mine = select(Ticket.id).where(_mine(user.id))
        conds = [NdCase.ticket_id.in_(mine)]
        if mgg:
            conds.append(NdCase.id.in_(select(NdEvent.case_id).where(NdEvent.action == "COH_FORWARD")))
        if me:  # cases the COH forwarded to this e-mail
            conds.append(NdCase.id.in_(select(NdMggPick.case_id).where(NdMggPick.email == me)))
        q = q.where(or_(*conds))
    cases = list(db.scalars(q))
    if not cases:
        return []
    tickets = {t.id: t for t in db.scalars(select(Ticket).where(Ticket.id.in_({c.ticket_id for c in cases})))}
    gps = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_({c.task_gp_id for c in cases})))}
    reached: dict[int, set[str]] = {}
    latest: dict[tuple[int, str], int] = {}  # (case, SME / COH) -> its latest handing step (the same rule as _current)
    latest_coh: dict[int, int] = {}  # case -> its latest COH forward
    role_of = {a: r for r, a in HANDED_BY.items()}
    for eid, cid, a in db.execute(
        select(NdEvent.id, NdEvent.case_id, NdEvent.action).where(NdEvent.case_id.in_([c.id for c in cases]), NdEvent.action.in_(("AM_FORWARD", "SME_RECOMMEND", "COH_FORWARD"))).order_by(NdEvent.id)
    ):
        reached.setdefault(cid, set()).add(a)
        if a in role_of:
            latest[(cid, role_of[a])] = eid
        if a == "COH_FORWARD":
            latest_coh[cid] = eid
    # the cases whose latest COH forward went to this user's e-mail (the same rule as _mgg_picks / _picked)
    picked_events = set(db.scalars(select(NdMggPick.event_id).where(NdMggPick.event_id.in_(list(latest_coh.values())), NdMggPick.email == me))) if latest_coh and me else set()
    handed: dict[int, set[int]] = {}  # handing step -> recipient ids
    for eid, rid in db.execute(select(NdForward.event_id, NdForward.recipient_id).where(NdForward.event_id.in_(list(latest.values())))) if latest else []:
        handed.setdefault(eid, set()).add(rid)
    my_rows: dict[int, dict[int, str]] = {}  # ticket -> the user's recipient rows (id -> role)
    for rid, tid, role in db.execute(select(TicketRecipient.id, TicketRecipient.ticket_id, TicketRecipient.role).where(TicketRecipient.ticket_id.in_({c.ticket_id for c in cases}), TicketRecipient.user_id == user.id)):
        my_rows.setdefault(tid, {})[rid] = role

    def holds(c: NdCase, role: str) -> bool:
        eid = latest.get((c.id, role))
        if eid is None:
            return False
        rows = my_rows.get(c.ticket_id, {})
        sent = handed.get(eid)
        return any(r == role for r in rows.values()) if sent is None else bool(sent & rows.keys())

    on_cache: dict[int, set[str]] = {}
    fe_cache: dict[int, list[TicketRecipient]] = {}
    from .task import FeScope

    out: list[tuple[NdCase, set[str]]] = []
    for c in cases:
        t, g = tickets.get(c.ticket_id), gps.get(c.task_gp_id)
        if t is None or g is None:
            continue
        if t.id not in on_cache:
            on_cache[t.id] = _roles_on(db, t, user)
            fe_cache[t.id] = list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE")))
        on = on_cache[t.id]
        owners = [r for r in fe_cache[t.id] if FeScope(r.name, r.fe_mail).owns(g)]
        roles: set[str] = set()
        if (owners and any(r.user_id == user.id for r in owners)) or (not owners and "AM" in on):
            roles.add("FE")
        if "AM" in on:
            roles.add("AM")
        got = reached.get(c.id, set())
        if holds(c, "SME"):  # only the SME / COH the case was handed to
            roles.add("SME")
        if holds(c, "COH"):
            roles.add("COH")
        if "COH_FORWARD" in got and (mgg or latest_coh.get(c.id) in picked_events):
            roles.add("MGG")
        if roles or user.is_admin:
            out.append((c, roles))
    return out


def _events_by_case(db: Session, ids: list[int]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for cid, a in db.execute(select(NdEvent.case_id, NdEvent.action).where(NdEvent.case_id.in_(ids))) if ids else []:
        out.setdefault(cid, set()).add(a)
    return out


def summary(db: Session, user: CurrentUser) -> dict[str, Any]:
    """Role-wise KPI cards: one block per role the user has on any case (admins: every block over all cases)."""
    rows = _visible_cases(db, user)
    acts = _events_by_case(db, [c.id for c, _ in rows])
    mgg = is_mgg(db, user)

    def of(role: str) -> list[NdCase]:
        return [c for c, roles in rows if user.is_admin or role in roles]

    def n(cases: list[NdCase], cond) -> int:
        return sum(1 for c in cases if cond(c))

    blocks: dict[str, dict[str, int]] = {}
    am = of("AM")
    if am or (not user.is_admin and any("AM" in r for _, r in rows)):
        blocks["AM"] = {
            "proposed": n(am, lambda c: "JUSTIFICATION" in acts.get(c.id, set())), "pending": n(am, lambda c: c.status in ("PENDING_AM", "RETURNED_AM")),
            "approvedForSme": n(am, lambda c: "AM_FORWARD" in acts.get(c.id, set())), "returnedToFe": n(am, lambda c: "AM_RETURN" in acts.get(c.id, set())), "total": len(am),
        }
    sme = of("SME")
    if sme:
        blocks["SME"] = {
            "received": len(sme), "pending": n(sme, lambda c: c.status in ("PENDING_SME", "RETURNED_SME")), "recommended": n(sme, lambda c: "SME_RECOMMEND" in acts.get(c.id, set())),
            "returnedToAm": n(sme, lambda c: "SME_RETURN" in acts.get(c.id, set())), "forwardedToCoh": n(sme, lambda c: c.status in ("PENDING_COH", "PENDING_MGG", "APPROVED", "REJECTED")),
        }
    coh = of("COH")
    if coh:
        blocks["COH"] = {
            "received": len(coh), "pending": n(coh, lambda c: c.status == "PENDING_COH"), "recommendedToMgg": n(coh, lambda c: "COH_FORWARD" in acts.get(c.id, set())),
            "returned": n(coh, lambda c: "COH_RETURN" in acts.get(c.id, set())), "pendingMgg": n(coh, lambda c: c.status == "PENDING_MGG"),
        }
    mg = of("MGG")
    if mg or mgg:
        blocks["MGG"] = {
            "received": len(mg), "pending": n(mg, lambda c: c.status == "PENDING_MGG"), "approved": n(mg, lambda c: c.status == "APPROVED"),
            "rejected": n(mg, lambda c: c.decision == "REJECTED"), "decided": n(mg, lambda c: c.decision is not None),
        }
    fe = [c for c, roles in rows if "FE" in roles]
    if fe:
        blocks["FE"] = {
            "total": len(fe), "actionNeeded": n(fe, lambda c: c.status in ("PROPOSED", "E1_DONE", "RETURNED_FE") or (c.status == "REJECTED" and c.revisit_status in ("COORDINATION", "FRT_VISIT", "FRT_UPDATED"))),
            "inReview": n(fe, lambda c: c.status in ("PENDING_AM", "PENDING_SME", "RETURNED_AM", "RETURNED_SME", "PENDING_COH", "PENDING_MGG")),
            "approved": n(fe, lambda c: c.status == "APPROVED"), "rejected": n(fe, lambda c: c.decision == "REJECTED"),
        }
    return {"roles": sorted({r for _, roles in rows for r in roles} | ({"MGG"} if mgg else set())), "isAdmin": user.is_admin, "isMgg": mgg, "kpis": blocks}


def _pending_with(c: NdCase) -> str | None:
    if c.status in PENDING_WITH:
        return PENDING_WITH[c.status]
    if c.status == "REJECTED" and c.revisit_status in ("COORDINATION", "FRT_VISIT", "FRT_UPDATED"):
        return "FE"
    return None


def _waiting_on(c: NdCase, roles: set[str]) -> bool:
    """The case waits for an action of this user."""
    w = _pending_with(c)
    return (w == MGG and "MGG" in roles) or (w is not None and w in roles)


def case_row(c: NdCase, t: Ticket | None, g: TicketTaskGp | None, roles: set[str], iso) -> dict[str, Any]:
    return {
        "id": c.id, "ref": c.ref, "ticketId": c.ticket_id, "ticketCode": t.code if t else None, "ticketStatus": t.status if t else None,
        "gpId": c.task_gp_id, "gpCode": c.gp_code, "gpName": g.gp_name if g else None, "block": g.block if g else None, "circle": g.circle if g else None, "district": g.district if g else None,
        "fe": c.fe_name, "round": c.round, "status": c.status, "statusLabel": STATUS_LABEL[c.status], "revisit": c.revisit_status, "revisitLabel": REVISIT_LABEL.get(c.revisit_status or ""),
        "physical": c.physical_status, "evidence": c.evidence_status, "approval": c.approval_status, "pendingWith": _pending_with(c),
        "mine": _waiting_on(c, roles), "roles": sorted(roles), "createdAt": iso(c.created_at), "updatedAt": iso(c.updated_at), "decision": c.decision,
    }


FILTERS = {
    "open": lambda c: c.status in OPEN, "pending_am": lambda c: c.status in ("PENDING_AM", "RETURNED_AM"), "pending_sme": lambda c: c.status in ("PENDING_SME", "RETURNED_SME"),
    "pending_coh": lambda c: c.status == "PENDING_COH", "pending_mgg": lambda c: c.status == "PENDING_MGG", "returned": lambda c: c.status.startswith("RETURNED_"),
    "approved": lambda c: c.status == "APPROVED", "rejected": lambda c: c.status == "REJECTED", "with_fe": lambda c: _pending_with(c) == "FE",
}


def list_cases(db: Session, user: CurrentUser, status: str | None, q: str | None, mine: bool, ticket_id: int | None, page: int, size: int) -> dict[str, Any]:
    from .service import iso

    rows = _visible_cases(db, user)
    if status:
        if status in FILTERS:
            rows = [(c, r) for c, r in rows if FILTERS[status](c)]
        elif status in STATUS_LABEL:
            rows = [(c, r) for c, r in rows if c.status == status]
    if mine:
        rows = [(c, r) for c, r in rows if _waiting_on(c, r)]
    if ticket_id:
        rows = [(c, r) for c, r in rows if c.ticket_id == ticket_id]
    tickets = {t.id: t for t in db.scalars(select(Ticket).where(Ticket.id.in_({c.ticket_id for c, _ in rows})))} if rows else {}
    gps = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_({c.task_gp_id for c, _ in rows})))} if rows else {}
    needle = (q or "").strip().lower()
    if needle:
        def hit(c: NdCase) -> bool:
            g, t = gps.get(c.task_gp_id), tickets.get(c.ticket_id)
            hay = " ".join(str(x or "") for x in (c.ref, c.gp_code, g.gp_name if g else "", g.block if g else "", g.district if g else "", c.fe_name, t.code if t else "")).lower()
            return needle in hay
        rows = [(c, r) for c, r in rows if hit(c)]
    total = len(rows)
    start = (page - 1) * size
    return {
        "total": total, "page": page, "size": size,
        "items": [case_row(c, tickets.get(c.ticket_id), gps.get(c.task_gp_id), r, iso) for c, r in rows[start:start + size]],
    }


def _record_json(r: NdRecord, fls: list[NdFile], iso) -> dict[str, Any]:
    return {
        "id": r.id, "kind": r.kind, "visitDate": r.visit_date.isoformat() if r.visit_date else None, "location": r.location, "visitorName": r.visitor_name,
        "findings": r.findings, "reason": r.reason, "remarks": r.remarks, "justification": r.justification, "frtTeam": r.frt_team, "frtVisit": r.frt_visit,
        "outcome": r.outcome, "by": r.created_by_name, "at": iso(r.created_at), "files": [file_json(f, iso) for f in fls],
    }


def file_json(f: NdFile, iso) -> dict[str, Any]:
    return {"id": f.id, "kind": f.kind, "fileName": f.file_name, "contentType": f.content_type, "size": f.size, "uploadedAt": iso(f.uploaded_at), "uploadedBy": f.uploaded_by_name,
            "previewable": f.content_type in files.INLINE_TYPES}


def _tracker(c: NdCase, acts: list[NdEvent]) -> list[dict[str, Any]]:
    """E1–E6 with done / current / returned / pending for the progress tracker (latest round of each stage)."""
    last: dict[str, NdEvent] = {}
    for e in acts:
        if e.stage in STAGES:
            last[e.stage] = e
    current = {
        "PROPOSED": "E1", "E1_DONE": "E2", "RETURNED_FE": "E2", "PENDING_AM": "E3", "RETURNED_AM": "E3", "PENDING_SME": "E4", "RETURNED_SME": "E4",
        "PENDING_COH": "E5", "PENDING_MGG": "E6",
    }.get(c.status)
    order = {s: i for i, s in enumerate(STAGES)}
    out = []
    for s in STAGES:
        e = last.get(s)
        if c.status == "APPROVED":
            state = "done"
        elif c.status == "REJECTED":
            state = "rejected" if s == "E6" else "done"
        elif c.status == "WITHDRAWN":
            state = "done" if e is not None and s in ("E1",) else "skipped"
        elif current is None:
            state = "pending"
        elif s == current:
            state = "returned" if c.status.startswith("RETURNED_") else "current"
        else:
            state = "done" if order[s] < order[current] else "pending"
        out.append({"stage": s, "label": STAGE_LABEL[s], "state": state, "by": e.actor_name if e else None, "at": e.at if e else None})
    return out


def detail(db: Session, case_id: int, user: CurrentUser) -> dict[str, Any]:
    from .service import iso

    c, t, g, roles = _load(db, case_id, user)
    recs = list(db.scalars(select(NdRecord).where(NdRecord.case_id == c.id).order_by(NdRecord.id)))
    fls = list(db.scalars(select(NdFile).where(NdFile.case_id == c.id).order_by(NdFile.id)))
    evs = list(db.scalars(select(NdEvent).where(NdEvent.case_id == c.id).order_by(NdEvent.at, NdEvent.id)))
    by_rec: dict[int, list[NdFile]] = {}
    for f in fls:
        by_rec.setdefault(f.record_id or 0, []).append(f)
    task = db.get(TicketTask, t.id)
    others = list(db.scalars(select(NdCase).where(NdCase.task_gp_id == g.id, NdCase.id != c.id).order_by(NdCase.id)))
    open_ = t.status != "CLOSED"
    fe, w = "FE" in roles and open_, c.status
    can = {
        "verify": fe and w in ("PROPOSED", "E1_DONE", "RETURNED_FE"),
        "justify": fe and w in ("E1_DONE", "RETURNED_FE") and c.physical_status == "SUBMITTED",
        "withdraw": fe and w in STEPS["WITHDRAW"].frm,
        "revisitCoordination": fe and w == "REJECTED" and c.revisit_status == "COORDINATION",
        "revisitVisit": fe and w == "REJECTED" and c.revisit_status == "FRT_VISIT",
        "actions": [a for a, s in STEPS.items() if a != "WITHDRAW" and open_ and s.role in roles and w in s.frm],
    }
    tracker = _tracker(c, evs)
    return {
        "case": case_row(c, t, g, roles, iso) | {
            "physicalLabel": PHYSICAL_LABEL.get(c.physical_status), "evidenceLabel": EVIDENCE_LABEL.get(c.evidence_status), "approvalLabel": APPROVAL_LABEL.get(c.approval_status),
            "feEmail": c.fe_email, "createdBy": c.created_by_name, "decidedBy": c.decided_by_name, "decidedAt": iso(c.decided_at), "decisionRemark": c.decision_remark,
        },
        "ticket": {"id": t.id, "code": t.code, "subject": t.subject, "status": t.status, "circle": t.circle, "areaManager": task.am_name if task else None, "week": task.week_code if task else None},
        "gp": {"id": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "block": g.block, "district": g.district, "circle": g.circle, "category": g.gp_category, "review": g.review,
               "target": g.target, "remarks": g.remarks},
        "tracker": [s | {"at": iso(s["at"])} for s in tracker],
        "records": [_record_json(r, by_rec.get(r.id, []), iso) for r in recs],
        "history": [
            {"id": e.id, "stage": e.stage, "action": e.action, "label": ACTION_LABEL.get(e.action, e.action), "role": e.role, "roleLabel": ROLE_LABEL.get(e.role, e.role),
             "from": e.from_status, "fromLabel": STATUS_LABEL.get(e.from_status or ""), "to": e.to_status, "toLabel": STATUS_LABEL.get(e.to_status),
             "remark": e.remark, "recommendation": e.recommendation, "reason": e.reason, "decision": e.decision, "recordId": e.record_id, "by": e.actor_name, "at": iso(e.at)}
            for e in evs
        ],
        "otherRounds": [{"id": o.id, "ref": o.ref, "round": o.round, "status": o.status, "statusLabel": STATUS_LABEL[o.status]} for o in others],
        "can": can,
        "mggMembers": len(mgg_people(db)),
        "mggPicked": _picked_json(db, c),
    }


def _picked_json(db: Session, c: NdCase) -> list[dict[str, Any]]:
    """The MGG people the COH forwarded the case to, and whether each has an active dashboard account (needed to decide)."""
    picks = _mgg_picks(db, c)
    if not picks:
        return []
    accounts = set(db.scalars(select(func.lower(User.email)).where(func.lower(User.email).in_([p.email for p in picks]), User.is_active.is_(True))))
    return [{"name": p.name, "email": p.email, "account": p.email in accounts} for p in picks]


def file_for(db: Session, file_id: int, user: CurrentUser) -> NdFile:
    f = db.get(NdFile, file_id)
    if f is None:
        raise NdError(404, "File not found")
    _load(db, f.case_id, user)  # the same rule as the case (404 for anybody else)
    return f


def contacts(db: Session, case_id: int, user: CurrentUser, role: str) -> dict[str, Any]:
    """SME (for the AM's forward) / COH (for the SME's recommendation) of the ticket's circle – like the GP review."""
    from . import review

    c, t, _g, roles = _load(db, case_id, user)
    if role == "MGG":  # the COH's forward: the authorised MGG accounts (the COH may also type another name / e-mail)
        if "COH" not in roles:
            raise NdError(403, f"Only the COH of this case chooses the {MGG}")
        me = (user.email or "").lower()
        return {
            "circle": None, "role": "MGG", "onTicket": [],
            "people": [{"name": u.name, "emails": [{"email": u.email, "account": True, "onTicket": False}]} for u in mgg_people(db) if u.email.lower() != me],
        }
    need = {"SME": "AM", "COH": "SME"}.get(role)
    if need is None or need not in roles:
        raise NdError(403, f"Only the {ROLE_LABEL.get(need or '', 'reviewer')} of this case chooses the {role}")
    try:
        return review.contacts(db, t, user, role)
    except review.ReviewError as exc:
        raise NdError(exc.status, exc.message) from None


# ---------------------------------------------------------------- Corporate Team – MGG members (admin)


def members(db: Session) -> list[dict[str, Any]]:
    from .service import iso

    rows = db.execute(select(NdMggMember, User).join(User, User.id == NdMggMember.user_id).order_by(User.name)).all()
    return [{"userId": u.id, "name": u.name, "email": u.email, "active": u.is_active, "addedBy": m.added_by_name, "addedAt": iso(m.added_at)} for m, u in rows]


def add_member(db: Session, admin: CurrentUser, user_id: int) -> None:
    u = db.get(User, user_id)
    if u is None or not u.is_active:
        raise NdError(422, "Choose an active dashboard account")
    if db.scalar(select(NdMggMember.id).where(NdMggMember.user_id == user_id)) is not None:
        raise NdError(409, f"{u.name} is already a {MGG} member")
    db.add(NdMggMember(user_id=user_id, added_by_name=admin.name, added_at=now()))
    db.commit()


def remove_member(db: Session, user_id: int) -> None:
    m = db.scalars(select(NdMggMember).where(NdMggMember.user_id == user_id)).first()
    if m is None:
        raise NdError(404, "Not a member")
    db.delete(m)
    db.commit()


def case_refs(db: Session, ticket_id: int) -> dict[int, dict[str, Any]]:
    """Latest case of each GP of a ticket (for the GP-wise task view): ref, status and label."""
    out: dict[int, dict[str, Any]] = {}
    for c in db.scalars(select(NdCase).where(NdCase.ticket_id == ticket_id).order_by(NdCase.id)):
        out[c.task_gp_id] = {"id": c.id, "ref": c.ref, "status": c.status, "label": STATUS_LABEL[c.status], "revisit": c.revisit_status, "open": c.status in OPEN}
    return out
