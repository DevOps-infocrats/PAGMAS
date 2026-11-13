"""Non-Doable Cases endpoints (app.tickets.nondoable): FE → AM → SME → COH → Corporate Team – MGG.

Every permission is checked in the service from the ticket's recipients and the admin-managed Corporate Team – MGG
list – a case of somebody else answers 404, a step of another role 403 – and files are streamed only after the same
check. Admins see every case (read only) and manage the Corporate Team – MGG members.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..security.deps import CurrentUser, audit, get_current_user, require_admin
from ..tickets import files, mailer
from ..tickets import nondoable as nd
from .tickets import INLINE_CSP

router = APIRouter(prefix="/nondoable", tags=["nondoable"], dependencies=[Depends(get_current_user)])


def _fail(exc: nd.NdError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


class ToIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    email: str = Field(max_length=254)


class ActionIn(BaseModel):
    action: Literal["AM_FORWARD", "AM_RETURN", "SME_RECOMMEND", "SME_RETURN", "COH_FORWARD", "COH_RETURN", "MGG_APPROVE", "MGG_REJECT", "WITHDRAW"]
    remark: str | None = Field(default=None, max_length=nd.MAX_TEXT)
    reason: str | None = Field(default=None, max_length=nd.MAX_TEXT)
    target: Literal["FE", "AM", "SME"] | None = None  # COH_RETURN
    to: list[ToIn] = Field(default_factory=list, max_length=10)  # AM_FORWARD: SME · SME_RECOMMEND: COH


class MemberIn(BaseModel):
    userId: int


@router.get("/summary")
def summary(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Role-wise KPI cards of the signed-in user."""
    return nd.summary(db, user)


@router.get("/cases")
def cases(
    status_: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    mine: bool = False,
    ticket: int | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Cases the user may see; `mine` = waiting for the user's action."""
    return nd.list_cases(db, user, status_, q, mine, ticket, page, size)


@router.get("/cases/{case_id}")
def case(case_id: int, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        return nd.detail(db, case_id, user)
    except nd.NdError as exc:
        raise _fail(exc) from None


@router.get("/cases/{case_id}/contacts")
def contacts(case_id: int, role: Literal["SME", "COH"], user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """SME (AM forward) / COH (SME recommendation) of the ticket's circle in the Escalation Matrix."""
    try:
        return nd.contacts(db, case_id, user, role)
    except nd.NdError as exc:
        raise _fail(exc) from None


def _form(
    case_id: int, kind: str, payload: str, evidence: list[UploadFile] | None, photos: list[UploadFile] | None, request: Request, background: BackgroundTasks,
    user: CurrentUser, db: Session,
) -> dict:
    try:
        data = json.loads(payload or "{}")
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The form could not be read") from None
    uploads = [nd.Upload("EVIDENCE", f.filename, f.content_type, f.file) for f in (evidence or []) if f.filename]
    uploads += [nd.Upload("PHOTO", f.filename, f.content_type, f.file) for f in (photos or []) if f.filename]
    try:
        c, mail, event_id = nd.submit_form(db, case_id, user, kind, data, uploads)
    except nd.NdError as exc:
        raise _fail(exc) from None
    background.add_task(mailer.nd_mail, c.id, event_id, mail)
    audit(db, "nondoable_form", request, user.id, f"{c.ref} {kind} ({len(uploads)} files)")
    return nd.detail(db, c.id, user)


@router.post("/cases/{case_id}/verification")
def verification(
    case_id: int, request: Request, background: BackgroundTasks, payload: Annotated[str, Form(max_length=50_000)],
    evidence: Annotated[list[UploadFile] | None, File()] = None, photos: Annotated[list[UploadFile] | None, File()] = None,
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    """E1 – physical verification (visitDate, visitorName, location, reason, findings, remarks + evidence / photos)."""
    return _form(case_id, "VERIFICATION", payload, evidence, photos, request, background, user, db)


@router.post("/cases/{case_id}/justification")
def justification(
    case_id: int, request: Request, background: BackgroundTasks, payload: Annotated[str, Form(max_length=50_000)],
    evidence: Annotated[list[UploadFile] | None, File()] = None, photos: Annotated[list[UploadFile] | None, File()] = None,
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    """E2 – justification to the Area Manager (justification, frtTeam, frtVisit, remarks + additional evidence)."""
    return _form(case_id, "JUSTIFICATION", payload, evidence, photos, request, background, user, db)


@router.post("/cases/{case_id}/revisit")
def revisit(
    case_id: int, request: Request, background: BackgroundTasks, payload: Annotated[str, Form(max_length=50_000)], kind: Annotated[Literal["COORDINATION", "VISIT"], Form()],
    evidence: Annotated[list[UploadFile] | None, File()] = None, photos: Annotated[list[UploadFile] | None, File()] = None,
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    """After a rejection: FE coordination with the FRT team, then the new FRT site visit."""
    return _form(case_id, f"REVISIT_{kind}", payload, evidence, photos, request, background, user, db)


@router.post("/cases/{case_id}/action")
def action(case_id: int, body: ActionIn, request: Request, background: BackgroundTasks, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """AM forward / return, SME recommend / return, COH forward / return, Corporate Team – MGG approve / reject, FE withdraw."""
    try:
        c, mail, event_id, sent = nd.act(db, case_id, user, body.action, body.remark, body.reason, body.target, [x.model_dump() for x in body.to])
    except nd.NdError as exc:
        raise _fail(exc) from None
    background.add_task(mailer.nd_mail, c.id, event_id, mail, sent)
    audit(db, "nondoable_action", request, user.id, f"{c.ref} {body.action}" + (f" · sent to {len(sent)}" if sent else ""))
    return nd.detail(db, c.id, user)


@router.get("/files/{file_id}")
def file(file_id: int, inline: bool = False, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    """Evidence / site photograph of a case – same permission rule as the case."""
    try:
        f = nd.file_for(db, file_id, user)
        path = files.path_of(f.ticket_id, f.stored_name)
    except (nd.NdError, files.AttachmentError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file is missing")
    show = inline and f.content_type in files.INLINE_TYPES
    headers = {"Cache-Control": "private, no-store"}
    if show:
        headers["Content-Security-Policy"] = INLINE_CSP
    return FileResponse(path, media_type=f.content_type, filename=f.file_name, content_disposition_type="inline" if show else "attachment", headers=headers)


@router.get("/mgg")
def mgg_members(_: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return {"members": nd.members(db)}


@router.post("/mgg")
def mgg_add(body: MemberIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Authorise an existing active account as Corporate Team – MGG (no account is created here)."""
    try:
        nd.add_member(db, admin, body.userId)
    except nd.NdError as exc:
        raise _fail(exc) from None
    audit(db, "nondoable_mgg_add", request, admin.id, str(body.userId))
    return {"members": nd.members(db)}


@router.post("/mgg/{user_id}/remove")
def mgg_remove(user_id: int, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        nd.remove_member(db, user_id)
    except nd.NdError as exc:
        raise _fail(exc) from None
    audit(db, "nondoable_mgg_remove", request, admin.id, str(user_id))
    return {"members": nd.members(db)}
