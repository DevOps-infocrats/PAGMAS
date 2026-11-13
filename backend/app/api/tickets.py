"""Ticket Management endpoints (any signed-in user; admin-only actions are marked).

Permissions are enforced here and in app.tickets.service, never only in the browser: a user sees and changes only
tickets assigned to them (other IDs answer 404), only admins create and review tickets, and attachments are
streamed only after the same check.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.store import Store, get_store
from ..db import get_db
from ..models import TicketAttachment, TicketProgressFile, TicketRecipient, TicketTask, TicketTaskGp
from ..security.deps import CurrentUser, audit, get_current_user, require_admin
from ..tickets import directory, files, mailer, monitor, service
from ..tickets import task as tasks
from ..tickets.service import PRIORITIES, STATUSES, TicketError, Upload

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(get_current_user)])

Scope = Literal["all", "mine"]
INLINE_CSP = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; object-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _fail(exc: TicketError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _scope_user(scope: Scope, user: CurrentUser) -> int | None:
    """`all` (every ticket) is for admins only; `mine` = tickets assigned to the signed-in user."""
    if scope == "all":
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
        return None
    return user.id


class TaskIn(BaseModel):
    """GP-wise weekly task: the reporting week, and – for a ticket without recipients – the Area Manager (Escalation
    Matrix name). With recipients, every selected Area Manager gets their own task ticket."""

    amName: str | None = Field(default=None, min_length=1, max_length=160)
    week: str = Field(pattern=r"^W-\d{1,2}$")


class RecipientIn(BaseModel):
    role: Literal["CBH", "SME", "COH", "AM", "FE", "OTHER"]  # OTHER = name + e-mail typed by the admin
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    # FE only: the Escalation Matrix mapping that decides the FE's GPs (parent Area Manager + FE e-mail of the rows;
    # null = rows without an FE e-mail). `email` is the delivery address (from the matrix or typed by the admin).
    am: str | None = Field(default=None, max_length=160)
    feEmail: str | None = Field(default=None, max_length=200)


class TicketIn(BaseModel):
    assigneeId: int | None = Field(default=None, ge=1)
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10_000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    task: TaskIn | None = None
    # Generate Ticket with Circle → CBH / SME / Area Manager (optional; without it the ticket goes to assigneeId only)
    circle: str | None = Field(default=None, min_length=1, max_length=80)
    recipients: list[RecipientIn] = Field(default_factory=list, max_length=60)
    sendEmail: bool = False


class ProgressItem(BaseModel):
    taskGpId: int = Field(ge=1)
    # DONE / PENDING per GP (Daily Achievement); achievedToday 1 / 0 is the older form of the same choice
    status: Literal["DONE", "PENDING"] | None = None
    achievedToday: int | None = Field(default=None, ge=0, le=1)
    # GP classification A–E (tasks.CATEGORIES) – the Daily Achievement dropdown; replaces the GP's previous category
    category: Literal["A", "B", "C", "D", "E"] | None = None
    remark: str | None = Field(default=None, max_length=tasks.MAX_REMARK)
    # corrections of the GP by the FE / Area Manager (null = unchanged); kept in the GP's history
    gpName: str | None = Field(default=None, max_length=160)
    block: str | None = Field(default=None, max_length=160)


class NewGpIn(BaseModel):
    gpCode: str = Field(min_length=1, max_length=40)
    gpName: str | None = Field(default=None, max_length=160)
    block: str | None = Field(default=None, max_length=160)
    category: Literal["A", "C", "D"] | None = None
    remark: str | None = Field(default=None, max_length=tasks.MAX_REMARK)


class ProgressIn(BaseModel):
    items: list[ProgressItem] = Field(default_factory=list, max_length=2000)
    newGps: list[NewGpIn] = Field(default_factory=list, max_length=tasks.MAX_NEW_GPS)
    note: str | None = Field(default=None, max_length=2000)


class ReviewTo(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    email: str = Field(min_length=3, max_length=254)


class ReviewIn(BaseModel):
    taskGpIds: list[int] = Field(min_length=1, max_length=500)
    # SME_RETURN = SME sends back to the Area Manager · COH_RETURN = COH sends back to the SME (reason = remark)
    action: Literal["AM_APPROVE", "AM_RETURN", "SME_FORWARD", "SME_RETURN", "COH_LETTER", "COH_AMC", "COH_RETURN"]
    remark: str | None = Field(default=None, max_length=1000)
    category: Literal["B", "D"] | None = None
    date: dt.date | None = None
    # AM approve -> the SME, SME forward -> the COH: chosen from the Escalation Matrix or typed (name + e-mail)
    to: list[ReviewTo] = Field(default_factory=list, max_length=10)


def _week_ok(store: Store, week: str) -> None:
    if week not in {w.code for w in store.weeks}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown week {week}")


class CloseIn(BaseModel):
    comment: str | None = Field(default=None, max_length=5_000)
    # GP-wise task with GPs the Area Manager has not approved yet: close anyway (comment = the reason, recorded)
    force: bool = False


class ChangesIn(BaseModel):
    comment: str = Field(min_length=5, max_length=5_000)


@router.get("/kpis")
def kpis(scope: Scope = "mine", user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.kpis(db, _scope_user(scope, user))


@router.get("")
def list_tickets(
    scope: Scope = "mine",
    search: Annotated[str | None, Query(max_length=100)] = None,
    status_: Annotated[Literal[STATUSES] | None, Query(alias="status")] = None,  # type: ignore[valid-type]
    priority: Annotated[Literal[PRIORITIES] | None, Query()] = None,  # type: ignore[valid-type]
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    circle: Annotated[str | None, Query(max_length=80)] = None,
    area_manager: Annotated[str | None, Query(alias="areaManager", max_length=160)] = None,
    week: Annotated[str | None, Query(pattern=r"^W-\d{1,2}$")] = None,
    gp: Annotated[str | None, Query(max_length=100)] = None,
    progress_date: Annotated[dt.date | None, Query(alias="progressDate")] = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The 'from' date is after the 'to' date")
    return service.list_tickets(
        db,
        assignee_id=_scope_user(scope, user),
        search=search,
        status=status_,
        priority=priority,
        date_from=date_from,
        date_to=date_to,
        circle=circle,
        area_manager=area_manager,
        week=week,
        gp=gp,
        progress_date=progress_date,
        page=page,
        page_size=page_size,
    )


@router.get("/filter-options", dependencies=[Depends(require_admin)])
def filter_options(db: Session = Depends(get_db)) -> dict:
    return service.filter_options(db)


@router.get("/directory", dependencies=[Depends(require_admin)])
def ticket_directory(
    circle: Annotated[str | None, Query(max_length=80)] = None,
    week: Annotated[str | None, Query(pattern=r"^W-\d{1,2}$")] = None,
    db: Session = Depends(get_db),
    store: Store = Depends(get_store),
) -> dict:
    """Circles, and for the chosen circle its CBH / SME / Area Managers with e-mails and matching dashboard accounts."""
    wk = week or store.weeks[-1].code
    _week_ok(store, wk)
    return directory.directory(db, store, circle, wk)


@router.get("/assignees", dependencies=[Depends(require_admin)])
def assignees(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Active registered users a ticket can be assigned to (not the admin creating it)."""
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in service.active_users(db) if u.id != user.id]


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: TicketIn, request: Request, background: BackgroundTasks, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if body.circle or body.recipients:
        return _generate(body, request, background, admin, db)
    if body.assigneeId is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select the user or the Circle and recipients of the ticket")
    if body.task is not None and not body.task.amName:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select the Area Manager of the GP-wise task")
    task = None
    if body.task is not None:
        store = get_store()  # the whole dataset (admins are never limited to areas)
        _week_ok(store, body.task.week)
        task = (store, body.task.amName, body.task.week)
    try:
        t = service.create(db, admin, body.assigneeId, body.subject, body.description, body.priority, task)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_create", request, admin.id, f"{t.code} -> user {t.assignee_id} ({t.priority})" + (f" · GP task {body.task.amName} {body.task.week}" if body.task else ""))
    return service.summary_json(t) | {"tickets": [service.summary_json(t)], "emailQueued": 0}


def _generate(body: TicketIn, request: Request, background: BackgroundTasks, admin: CurrentUser, db: Session) -> dict:
    """Generate Ticket with Circle + CBH / SME / Area Manager recipients (several tickets for several AMs' tasks)."""
    if not body.circle:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Select the Circle / State")
    store = get_store()  # the whole dataset (admins are never limited to areas)
    week = body.task.week if body.task else store.weeks[-1].code
    _week_ok(store, week)
    try:
        made = service.generate(
            db, admin, store, subject=body.subject, description=body.description, priority=body.priority, circle=body.circle,
            items=[r.model_dump() for r in body.recipients], assignee_id=body.assigneeId, week=week, task=body.task is not None, send_email=body.sendEmail,
        )
    except TicketError as exc:
        raise _fail(exc) from None
    queued: list[int] = []
    if body.sendEmail:
        queued = list(db.scalars(select(TicketRecipient.id).where(TicketRecipient.ticket_id.in_([t.id for t in made]), TicketRecipient.email_status == "PENDING")))
        background.add_task(mailer.deliver, queued)
    for t in made:
        n = db.scalar(select(func.count()).where(TicketRecipient.ticket_id == t.id)) or 0
        audit(db, "ticket_create", request, admin.id, f"{t.code} -> {n} recipients, {t.circle} ({t.priority})" + (f" · GP task {week}" if body.task else "") + (" · e-mail" if body.sendEmail else ""))
    first = made[0]
    return service.summary_json(first) | {"tickets": [service.summary_json(t) for t in made], "emailQueued": len(queued)}


@router.get("/task/area-managers", dependencies=[Depends(require_admin)])
def task_area_managers(week: Annotated[str, Query(pattern=r"^W-\d{1,2}$")], db: Session = Depends(get_db), store: Store = Depends(get_store)) -> dict:
    """Area Managers (Escalation Matrix) with their GP counts for the week and the dashboard user matching their e-mail."""
    _week_ok(store, week)
    return tasks.area_managers(db, store, week)


@router.get("/task/preview", dependencies=[Depends(require_admin)])
def task_preview(
    am: Annotated[str, Query(min_length=1, max_length=160)],
    week: Annotated[str, Query(pattern=r"^W-\d{1,2}$")],
    circle: Annotated[str | None, Query(max_length=80)] = None,
    store: Store = Depends(get_store),
) -> dict:
    """The GPs a task ticket for this Area Manager would get (only the selected circle's when one is given)."""
    _week_ok(store, week)
    try:
        rows = tasks.preview(store, am, week, circle)
    except tasks.TaskError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return {"rows": rows, "dataAsOf": store.data_as_of.isoformat(), "emails": tasks.am_emails(store, am), "summary": tasks.breakdown(store, am, week, circle, rows)}


@router.get("/notifications")
def notifications(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return service.notifications(db, user)


@router.post("/notifications/read")
def notifications_read(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"updated": service.mark_read(db, user)}


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, inline: bool = False, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    a = db.get(TicketAttachment, attachment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    try:
        service.visible(db, a.ticket_id, user)  # same rule as the ticket: admin or the assigned user
        path = files.path_of(a.ticket_id, a.stored_name)
    except TicketError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from exc
    except files.AttachmentError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file is missing")
    show = inline and a.content_type in files.INLINE_TYPES
    headers = {"Cache-Control": "private, no-store"}
    if show:
        headers["Content-Security-Policy"] = INLINE_CSP
    return FileResponse(path, media_type=a.content_type, filename=a.file_name, content_disposition_type="inline" if show else "attachment", headers=headers)


def _monitor_filters(
    circle: Annotated[str | None, Query(max_length=80)] = None,
    areaManager: Annotated[str | None, Query(max_length=160)] = None,
    fe: Annotated[str | None, Query(max_length=160)] = None,
    block: Annotated[str | None, Query(max_length=160)] = None,
    week: Annotated[str | None, Query(pattern=r"^W-\d{1,2}$")] = None,
    ticket: Annotated[str | None, Query(max_length=20)] = None,
    gpCode: Annotated[str | None, Query(max_length=40)] = None,
    gpName: Annotated[str | None, Query(max_length=160)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    dateFrom: dt.date | None = None,
    dateTo: dt.date | None = None,
) -> dict:
    if dateFrom and dateTo and dateFrom > dateTo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The 'from' date is after the 'to' date")
    return {"circle": circle, "areaManager": areaManager, "fe": fe, "block": block, "week": week, "ticket": ticket, "gpCode": gpCode, "gpName": gpName, "search": search, "dateFrom": dateFrom, "dateTo": dateTo}


@router.get("/gp-monitor/summary", dependencies=[Depends(require_admin)])
def gp_monitor_summary(f: dict = Depends(_monitor_filters), basis: Literal["status", "category"] = "status", db: Session = Depends(get_db)) -> dict:
    """Done / Pending and category-wise (A–E) GPs of all GP-wise task tickets (each GP code once) for the filters.
    basis "category": the date filter means the day the category was chosen (as in the category tables)."""
    return monitor.summary(db, f, "category" if basis == "category" else None)


@router.get("/gp-monitor", dependencies=[Depends(require_admin)])
def gp_monitor(
    f: dict = Depends(_monitor_filters),
    gp_status: Annotated[Literal["DONE", "PENDING"] | None, Query(alias="status")] = None,
    category: Literal["A", "B", "C", "D", "E"] | None = None,
    sort: Annotated[Literal[monitor.SORTS], Query()] = "date",  # type: ignore[valid-type]
    desc: bool = True,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
    db: Session = Depends(get_db),
) -> dict:
    if (gp_status is None) == (category is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose either a status (Done / Pending) or a category (A–E)")
    return monitor.listing(db, f, gp_status, sort, desc, page, page_size, category)


@router.get("/gp-monitor/gps/{gp_code}", dependencies=[Depends(require_admin)])
def gp_monitor_detail(gp_code: Annotated[str, Path(min_length=1, max_length=40)], db: Session = Depends(get_db)) -> dict:
    d = monitor.gp_detail(db, gp_code)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This GP is not in any GP-wise task ticket")
    return d


@router.get("/progress-files/{file_id}")
def progress_file(file_id: int, inline: bool = False, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    """A proof document of a GP (daily progress) – same permission rule as the ticket (admin or a recipient of it); an
    FE only of their GPs, an SME only of the GPs forwarded to them."""
    f = db.get(TicketProgressFile, file_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    try:
        t = service.visible(db, f.ticket_id, user)
        scope = tasks.view_of(db, t, user)
        if scope is not None and not scope.owns(db.get(TicketTaskGp, f.task_gp_id)):  # another FE's GP / not forwarded to this SME
            raise TicketError(404, "File not found")
        path = files.path_of(f.ticket_id, f.stored_name)
    except TicketError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from exc
    except files.AttachmentError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file is missing")
    show = inline and f.content_type in files.INLINE_TYPES
    headers = {"Cache-Control": "private, no-store"}
    if show:
        headers["Content-Security-Policy"] = INLINE_CSP
    return FileResponse(path, media_type=f.content_type, filename=f.file_name, content_disposition_type="inline" if show else "attachment", headers=headers)


@router.get("/{ticket_id}")
def detail(ticket_id: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        t = service.visible(db, ticket_id, user)
    except TicketError as exc:
        raise _fail(exc) from None
    return service.detail_json(db, t, user)


@router.post("/{ticket_id}/start")
def start(ticket_id: int, request: Request, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        t = service.start(db, service.visible(db, ticket_id, user), user)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_start", request, user.id, t.code)
    return service.detail_json(db, t, user)


@router.post("/{ticket_id}/submit")
def submit(
    ticket_id: int,
    request: Request,
    description: Annotated[str, Form(max_length=10_000)] = "",
    attachments: Annotated[list[UploadFile] | None, File()] = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Sync endpoint (thread pool): files are validated and written without blocking the event loop."""
    try:
        t = service.visible(db, ticket_id, user)
        uploads = [Upload(f.filename, f.content_type, f.file) for f in (attachments or [])]
        t = service.submit(db, t, user, description, uploads)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_submit", request, user.id, f"{t.code} ({len(uploads)} files)")
    return service.detail_json(db, t, user)


def _store_for(body: ProgressIn) -> Store | None:
    """The master data – only needed to fill in the details of added GPs."""
    return get_store() if body.newGps else None


def _mail_am(db: Session, t, user: CurrentUser, progress_id: int, background: BackgroundTasks) -> None:
    """An FE's daily progress is e-mailed to the Area Manager of the ticket (the dashboard notification is already saved)."""
    if tasks.scope_of(db, t, user) is not None:
        background.add_task(mailer.progress_mail, progress_id)


@router.get("/{ticket_id}/review-contacts")
def review_contacts(ticket_id: int, role: Literal["SME", "COH"], user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """SME (Area Manager approval) / COH (SME forward) of the ticket's circle in the Escalation Matrix."""
    from ..tickets import review

    try:
        return review.contacts(db, service.visible(db, ticket_id, user), user, role)
    except TicketError as exc:
        raise _fail(exc) from None
    except review.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/{ticket_id}/review")
def review_gps(ticket_id: int, body: ReviewIn, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Review chain of the GPs: AM approve (to the SME) / return, SME forward to the COH, COH letter submission / AMC
    conversion. The SME / COH chosen in `to` are put on the ticket and e-mailed the GP list."""
    from ..tickets import review

    try:
        t = service.visible(db, ticket_id, user)
        n, ids = review.apply(db, t, user, body.taskGpIds, body.action, body.remark, body.category, body.date, [x.model_dump() for x in body.to])
    except TicketError as exc:
        raise _fail(exc) from None
    except review.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None
    if ids:
        background.add_task(mailer.review_mail, ids, body.taskGpIds, body.action, user.name, (body.remark or "").strip() or None)
    audit(db, "ticket_review", request, user.id, f"{t.code} {body.action} · {n} GPs" + (f" · e-mail to {len(ids)}" if ids else ""))
    db.refresh(t)
    return service.detail_json(db, t, user)


@router.post("/{ticket_id}/progress")
def progress(ticket_id: int, body: ProgressIn, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Daily progress of a GP-wise task (assigned Area Manager / FE); every submission is kept as its own record."""
    try:
        t = service.visible(db, ticket_id, user)
        sub = tasks.submit_progress(db, t, user, [i.model_dump() for i in body.items], body.note, new_gps=[n.model_dump() for n in body.newGps], store=_store_for(body))
    except TicketError as exc:
        raise _fail(exc) from None
    except tasks.TaskError as exc:
        raise HTTPException(exc.status, exc.message) from None
    _mail_am(db, t, user, sub.id, background)
    audit(db, "ticket_progress", request, user.id, f"{t.code} daily progress #{sub.id}")
    db.refresh(t)
    return service.detail_json(db, t, user)


@router.post("/{ticket_id}/progress-form")
def progress_form(
    ticket_id: int,
    request: Request,
    payload: Annotated[str, Form(max_length=500_000)],
    background: BackgroundTasks,
    proofs: Annotated[list[UploadFile] | None, File()] = None,
    proofGps: Annotated[list[int] | None, Form()] = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Daily progress with proof documents: `payload` = the JSON of /progress (items + note); `proofs[i]` belongs to the
    GP `proofGps[i]` (task GP id). Sync endpoint (thread pool): files are validated and written without blocking."""
    try:
        body = ProgressIn.model_validate_json(payload)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The daily progress could not be read") from None
    files_in = [f for f in (proofs or []) if f.filename]
    gps_in = list(proofGps or [])
    if len(files_in) != len(gps_in):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Every proof document must name its GP")
    try:
        t = service.visible(db, ticket_id, user)
        uploads = [(gid, Upload(f.filename, f.content_type, f.file)) for gid, f in zip(gps_in, files_in)]
        sub = tasks.submit_progress(db, t, user, [i.model_dump() for i in body.items], body.note, uploads, [n.model_dump() for n in body.newGps], _store_for(body))
    except TicketError as exc:
        raise _fail(exc) from None
    except tasks.TaskError as exc:
        raise HTTPException(exc.status, exc.message) from None
    _mail_am(db, t, user, sub.id, background)
    audit(db, "ticket_progress", request, user.id, f"{t.code} daily progress #{sub.id} ({len(files_in)} proof files)")
    db.refresh(t)
    return service.detail_json(db, t, user)


@router.get("/{ticket_id}/task/{kind}.xlsx")
def task_workbook(ticket_id: int, kind: Literal["assignment", "progress"], user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    """The original assignment workbook (as generated) or the latest progress report (built from the database now)."""
    try:
        t = service.visible(db, ticket_id, user)
    except TicketError as exc:
        raise _fail(exc) from None
    task = db.get(TicketTask, t.id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This ticket has no GP-wise task")
    original = kind == "assignment"
    scope = tasks.view_of(db, t, user)  # a Field Engineer downloads only their own GPs, an SME only the GPs forwarded to them
    path = tasks.assignment_path(t, task) if original and scope is None else None
    data = path.read_bytes() if path is not None and path.is_file() else tasks.workbook(db, t, task, original=original, scope=scope)
    name = tasks.file_name(task, original, scope)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"},
    )


@router.post("/{ticket_id}/recipients/{recipient_id}/email")
def resend_email(ticket_id: int, recipient_id: int, request: Request, background: BackgroundTasks, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Send (or retry) the e-mail of one recipient. The ticket itself is never changed by this."""
    try:
        t = service.visible(db, ticket_id, admin)
    except TicketError as exc:
        raise _fail(exc) from None
    r = db.get(TicketRecipient, recipient_id)
    if r is None or r.ticket_id != t.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipient not found")
    ids = mailer.queue(db, [t.id], r.id)
    background.add_task(mailer.deliver, ids)
    audit(db, "ticket_email", request, admin.id, f"{t.code} recipient #{r.id} ({r.role})")
    return service.detail_json(db, t, admin)


class ShareTo(BaseModel):
    role: Literal["CBH", "SME"]
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)


class ShareIn(BaseModel):
    recipients: list[ShareTo] = Field(min_length=1, max_length=20)
    remark: str = Field(min_length=3, max_length=2000)


@router.get("/{ticket_id}/share-contacts")
def share_contacts(ticket_id: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """CBH / SME of the ticket's circle (Escalation Matrix) the Area Manager can share the ticket with."""
    try:
        t = service.visible(db, ticket_id, user)
        return service.share_contacts(db, t, user)
    except TicketError as exc:
        raise _fail(exc) from None


@router.post("/{ticket_id}/share")
def share(ticket_id: int, body: ShareIn, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Area Manager -> CBH / SME: the latest GP sheet and a remark by e-mail (read-only access with an account)."""
    try:
        t = service.visible(db, ticket_id, user)
        ids = service.share(db, t, user, [r.model_dump() for r in body.recipients], body.remark)
    except TicketError as exc:
        raise _fail(exc) from None
    background.add_task(mailer.deliver, ids, shared=(user.name, body.remark.strip()))
    audit(db, "ticket_share", request, user.id, f"{t.code} shared with {len(ids)} CBH / SME")
    return service.detail_json(db, t, user) | {"emailQueued": len(ids)}


class DeleteIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: int, request: Request, body: DeleteIn | None = None, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Admin only: soft-delete a ticket (see service.delete). AM / FE / other users get 403."""
    try:
        t = service.delete(db, service.visible(db, ticket_id, admin), admin, body.reason if body else None)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_delete", request, admin.id, f"{t.code} ({t.status}, {t.subject[:60]})")
    return {"deleted": True, "id": t.id, "code": t.code}


@router.post("/{ticket_id}/close")
def close(ticket_id: int, body: CloseIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        t = service.close(db, service.visible(db, ticket_id, admin), admin, body.comment, body.force)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_close", request, admin.id, t.code)
    return service.detail_json(db, t, admin)


@router.post("/{ticket_id}/request-changes")
def request_changes(ticket_id: int, body: ChangesIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        t = service.request_changes(db, service.visible(db, ticket_id, admin), admin, body.comment)
    except TicketError as exc:
        raise _fail(exc) from None
    audit(db, "ticket_request_changes", request, admin.id, t.code)
    return service.detail_json(db, t, admin)
