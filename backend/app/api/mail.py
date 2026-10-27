"""Mail Configuration (admins only): templates, schedules, recipient preview, run history, test mail.

Nothing here sends a report. Saving / enabling a schedule only stores it and sets its next run time (always in the
future); the scheduler (app.mail.service) sends when that time comes and AMC_REPORT_EMAILS_ENABLED=true. Template and
recipient previews render in the browser only. The one endpoint that sends is POST /mail/test: a plain test message
to one address, rate limited.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analytics.store import NoDataError, Store, get_store
from ..config import get_settings
from ..db import get_db
from ..mail import service
from ..mail import template as tpl
from ..mail.audience import AUDIENCE_LABELS, AUDIENCES, _json_list, filter_options, matrix_frame, matrix_people, recipients
from ..mail.report import ReportContext
from ..mail.schedule import Schedule, ScheduleError, describe, validate
from ..mail.smtp import MailError, send_test_mail, smtp_status
from ..models import MailConfig, MailRun, MailTemplate, User
from ..security.deps import CurrentUser, audit, require_admin

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(require_admin)])

TEST_LIMIT, TEST_WINDOW_S = 5, 600  # test mails per admin per 10 minutes
_test_hits: dict[int, deque[float]] = defaultdict(deque)
_test_lock = Lock()
Audience = Literal["am", "sme", "coh", "users"]  # CBH is stored as a backup only, never mailed


def _store_or_none() -> Store | None:
    try:
        return get_store()
    except NoDataError:
        return None


def _iso(v: dt.datetime | None) -> str | None:
    v = service.utc(v)
    return v.isoformat() if v else None


# ---------------------------------------------------------------- status and test mail


@router.get("/status")
def mail_status() -> dict:
    """SMTP settings as far as they are safe to show (never the password) and the switches."""
    s = get_settings()
    st = smtp_status(s)
    return {
        "smtp": {"configured": st.configured, "problems": st.problems, "server": st.server, "port": st.port, "security": st.security, "usernameSet": st.username_set, "sender": st.sender},
        "reportEmailsEnabled": s.amc_report_emails_enabled,
        "approvalEmailsEnabled": s.smtp_approval_emails_enabled,
        "schedulerRunning": service.scheduler_running(),
        "timezone": s.mail_timezone,
    }


class TestMailIn(BaseModel):
    to: EmailStr


@router.post("/test")
def test_mail(body: TestMailIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Send one plain test message (explicit admin action only). No report is generated."""
    now = time.monotonic()
    with _test_lock:
        hits = _test_hits[admin.id]
        while hits and now - hits[0] > TEST_WINDOW_S:
            hits.popleft()
        if len(hits) >= TEST_LIMIT:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"At most {TEST_LIMIT} test mails per {TEST_WINDOW_S // 60} minutes – try again later")
        hits.append(now)
    to = str(body.to).lower()
    try:
        send_test_mail(to, admin.name, admin.id)
    except MailError as exc:
        audit(db, "mail_test_failed", request, admin.id, str(exc)[:300])
        return {"ok": False, "message": str(exc)}
    audit(db, "mail_test_sent", request, admin.id, f"to {to}")
    return {"ok": True, "message": f"Test mail sent to {to}."}


# ---------------------------------------------------------------- choices for the forms


@router.get("/options")
def options(db: Session = Depends(get_db)) -> dict:
    """Everything the schedule / template forms need: filters, matrix people, users, placeholders."""
    st = _store_or_none()
    people = []
    if st is not None:
        for p in matrix_people(st):
            people.append({"id": p.id, "role": p.role, "roleLabel": AUDIENCE_LABELS[p.role], "name": p.name, "circleId": p.circle_id, "circle": p.circle, "emails": p.emails, "gps": len(p.gps), "businessAreas": p.business_areas})
    return {
        "hasData": st is not None,
        "hasMatrix": st is not None and matrix_frame(st) is not None,
        "audiences": [{"id": a, "label": AUDIENCE_LABELS[a]} for a in AUDIENCES],
        "filters": filter_options(st) if st is not None else {"circles": [], "businessAreas": [], "blocks": []},
        "people": people,
        "users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in db.scalars(select(User).where(User.is_active.is_(True)).order_by(func.lower(User.name)))],
        "placeholders": [{"name": k, "description": v, "table": k in tpl.TABLE_PLACEHOLDERS} for k, v in tpl.ALL_PLACEHOLDERS.items()],
    }


# ---------------------------------------------------------------- templates


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class PreviewIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    config_id: int | None = Field(default=None, alias="configId")
    person_id: str | None = Field(default=None, alias="personId", max_length=200)


def _template_json(t: MailTemplate, used_by: int = 0) -> dict:
    return {"id": t.id, "key": t.key, "builtIn": t.key is not None, "name": t.name, "description": t.description, "subject": t.subject, "body": t.body, "usedBy": used_by, "updatedAt": _iso(t.updated_at)}


def _check_template(subject: str, body: str) -> None:
    try:
        tpl.validate(subject, body)
    except tpl.TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)) -> list[dict]:
    service.ensure_default_templates(db)
    used = dict(db.execute(select(MailConfig.template_id, func.count()).group_by(MailConfig.template_id)).all())
    return [_template_json(t, used.get(t.id, 0)) for t in db.scalars(select(MailTemplate).order_by(MailTemplate.key.is_(None), MailTemplate.id))]


@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(body: TemplateIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _check_template(body.subject, body.body)
    t = MailTemplate(name=body.name.strip(), description=body.description, subject=body.subject.strip(), body=body.body)
    db.add(t)
    db.commit()
    audit(db, "mail_template_created", request, admin.id, f"#{t.id} {t.name}")
    return _template_json(t)


def _get_template(db: Session, tid: int) -> MailTemplate:
    t = db.get(MailTemplate, tid)
    if t is None:
        raise HTTPException(404, "Template not found")
    return t


@router.patch("/templates/{tid}")
def update_template(tid: int, body: TemplateIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    t = _get_template(db, tid)
    _check_template(body.subject, body.body)
    t.name, t.description, t.subject, t.body = body.name.strip(), body.description, body.subject.strip(), body.body
    db.commit()
    audit(db, "mail_template_updated", request, admin.id, f"#{t.id} {t.name}")
    return _template_json(t)


@router.post("/templates/{tid}/reset")
def reset_template(tid: int, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    t = _get_template(db, tid)
    default = next((d for d in tpl.DEFAULT_TEMPLATES if d["key"] == t.key), None)
    if default is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only built-in templates can be reset")
    t.name, t.description, t.subject, t.body = default["name"], default["description"], default["subject"], default["body"]
    db.commit()
    audit(db, "mail_template_reset", request, admin.id, f"#{t.id} {t.name}")
    return _template_json(t)


@router.post("/templates/{tid}/delete")
def delete_template(tid: int, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    t = _get_template(db, tid)
    if t.key is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in templates cannot be deleted – edit or reset them instead")
    used = db.scalar(select(func.count()).select_from(MailConfig).where(MailConfig.template_id == tid))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The template is used by {used} schedule(s) – choose another template there first")
    db.delete(t)
    db.commit()
    audit(db, "mail_template_deleted", request, admin.id, f"#{tid}")
    return {"deleted": tid}


@router.post("/templates/preview")
def preview_template(body: PreviewIn, db: Session = Depends(get_db)) -> dict:
    """Render a template for one real recipient (a schedule's first recipient, or a chosen person). Sends nothing."""
    _check_template(body.subject, body.body)
    st = _store_or_none()
    if st is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No active data yet")
    cfg = db.get(MailConfig, body.config_id) if body.config_id else None
    if cfg is None:  # a single person, or every Area Manager / SME / COH / CBH when none is chosen
        cfg = MailConfig(audiences=json.dumps(["am", "sme", "coh", "users"]), filter_circles="[]", filter_bas="[]", filter_blocks="[]", filter_people=json.dumps([body.person_id] if body.person_id else []), user_ids="[]")
    people, _ = recipients(db, st, cfg)
    if body.person_id:
        people = [p for p in people if body.person_id in p.person_ids] or people
    if not people:
        raise HTTPException(status.HTTP_409_CONFLICT, "No recipient to preview – check the Escalation Matrix e-mails or the schedule's filters")
    r = service.compose(ReportContext(st), body.subject, body.body, people[0])
    return {"recipient": {"name": people[0].name, "role": people[0].role_label, "emails": people[0].emails}, "subject": r.subject, "html": r.html, "text": r.text}


# ---------------------------------------------------------------- schedules


class ConfigIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    template_id: int | None = Field(default=None, alias="templateId")
    audiences: list[Audience] = Field(min_length=1, max_length=4)
    filter_circles: list[str] = Field(default_factory=list, alias="filterCircles", max_length=50)
    filter_bas: list[str] = Field(default_factory=list, alias="filterBusinessAreas", max_length=200)
    filter_blocks: list[str] = Field(default_factory=list, alias="filterBlocks", max_length=2000)
    filter_people: list[str] = Field(default_factory=list, alias="filterPeople", max_length=500)
    user_ids: list[int] = Field(default_factory=list, alias="userIds", max_length=1000)
    frequency: Literal["daily", "weekly", "monthly"]
    start_date: dt.date = Field(alias="startDate")
    send_time: str = Field(alias="sendTime", pattern=r"^\d{2}:\d{2}$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    month_day: int | None = Field(default=None, alias="monthDay", ge=1, le=31)
    enabled: bool = False


class EnabledIn(BaseModel):
    enabled: bool


def _config_json(c: MailConfig, templates: dict[int, str]) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "templateId": c.template_id,
        "templateName": templates.get(c.template_id or 0, "Detailed AMC Conversion report (default)"),
        "audiences": _json_list(c.audiences),
        "filterCircles": _json_list(c.filter_circles),
        "filterBusinessAreas": _json_list(c.filter_bas),
        "filterBlocks": _json_list(c.filter_blocks),
        "filterPeople": _json_list(c.filter_people),
        "userIds": _json_list(c.user_ids),
        "frequency": c.frequency,
        "startDate": c.start_date.isoformat(),
        "sendTime": c.send_time,
        "weekday": c.weekday,
        "monthDay": c.month_day,
        "enabled": c.enabled,
        "summary": describe(Schedule(c.frequency, c.start_date, c.send_time, c.weekday, c.month_day)),
        "timezone": get_settings().mail_timezone,
        "nextRunAt": _iso(c.next_run_at),
        "lastRunAt": _iso(c.last_run_at),
        "lastStatus": c.last_status,
        "createdAt": _iso(c.created_at),
        "updatedAt": _iso(c.updated_at),
    }


def _template_names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(MailTemplate.id, MailTemplate.name)).all())


def _apply(c: MailConfig, body: ConfigIn, db: Session) -> None:
    try:
        s = validate(Schedule(body.frequency, body.start_date, body.send_time, body.weekday, body.month_day))
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if body.template_id is not None and db.get(MailTemplate, body.template_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown template")
    ids = sorted(set(body.user_ids)) if "users" in body.audiences else []
    if ids:
        known = set(db.scalars(select(User.id).where(User.id.in_(ids))))
        if missing := [i for i in ids if i not in known]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown user id(s): {missing[:5]}")
    st = _store_or_none()
    if st is not None:  # filters must exist in the active data (a typo would silently match nothing)
        opts = filter_options(st)
        bad = [x for x in body.filter_circles if x not in {o["id"] for o in opts["circles"]}]
        bad += [x for x in body.filter_bas if x.strip().lower() not in {o["name"].lower() for o in opts["businessAreas"]}]
        bad += [x for x in body.filter_blocks if x not in {o["id"] for o in opts["blocks"]}]
        if body.filter_people:
            bad += [x for x in body.filter_people if x not in {p.id for p in matrix_people(st)}]
        if bad:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown filter value(s): {', '.join(map(str, bad[:5]))}")
    c.name = body.name.strip()
    c.template_id = body.template_id
    c.audiences = json.dumps(list(dict.fromkeys(body.audiences)))
    c.filter_circles, c.filter_bas = json.dumps(sorted(set(body.filter_circles))), json.dumps(sorted({b.strip() for b in body.filter_bas}))
    c.filter_blocks, c.filter_people = json.dumps(sorted(set(body.filter_blocks))), json.dumps(sorted(set(body.filter_people)))
    c.user_ids = json.dumps(ids)
    c.frequency, c.start_date, c.send_time, c.weekday, c.month_day = s.frequency, s.start_date, s.send_time, s.weekday, s.month_day
    c.enabled = body.enabled
    try:
        service.plan_next(c)  # strictly in the future -> saving never sends
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


def _get(db: Session, cid: int) -> MailConfig:
    c = db.get(MailConfig, cid)
    if c is None:
        raise HTTPException(404, "Schedule not found")
    return c


@router.get("/configs")
def list_configs(db: Session = Depends(get_db)) -> list[dict]:
    names = _template_names(db)
    return [_config_json(c, names) for c in db.scalars(select(MailConfig).order_by(MailConfig.id))]


@router.post("/configs", status_code=status.HTTP_201_CREATED)
def create_config(body: ConfigIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    c = MailConfig(created_by=admin.id)
    _apply(c, body, db)
    db.add(c)
    db.commit()
    audit(db, "mail_config_created", request, admin.id, f"#{c.id} {c.name} ({c.frequency}, {'enabled' if c.enabled else 'disabled'})")
    return _config_json(c, _template_names(db))


@router.patch("/configs/{cid}")
def update_config(cid: int, body: ConfigIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    c = _get(db, cid)
    _apply(c, body, db)
    db.commit()
    audit(db, "mail_config_updated", request, admin.id, f"#{c.id} {c.name} ({c.frequency}, {'enabled' if c.enabled else 'disabled'})")
    return _config_json(c, _template_names(db))


@router.post("/configs/{cid}/enabled")
def set_enabled(cid: int, body: EnabledIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    c = _get(db, cid)
    c.enabled = body.enabled
    service.plan_next(c)
    db.commit()
    audit(db, "mail_config_enabled" if body.enabled else "mail_config_disabled", request, admin.id, f"#{c.id} {c.name}")
    return _config_json(c, _template_names(db))


@router.post("/configs/{cid}/delete")
def delete_config(cid: int, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    c = _get(db, cid)
    name = c.name
    db.execute(delete(MailRun).where(MailRun.config_id == cid))
    db.delete(c)
    db.commit()
    audit(db, "mail_config_deleted", request, admin.id, f"#{cid} {name}")
    return {"deleted": cid}


@router.get("/configs/{cid}/recipients")
def preview_recipients(cid: int, db: Session = Depends(get_db)) -> dict:
    """Who would receive the schedule's next e-mail and what each one's report covers. Sends nothing."""
    c = _get(db, cid)
    st = _store_or_none()
    if st is None:
        return {"hasData": False, "recipients": [], "skipped": []}
    people, skipped = recipients(db, st, c)
    return {
        "hasData": True,
        "recipients": [{"name": p.name, "roles": p.role_label, "emails": p.emails, "areas": p.areas, "gps": len(p.gps), "breakdown": p.breakdown} for p in people],
        "skipped": [{"name": s.name, "role": s.role, "reason": s.reason} for s in skipped],
    }


@router.get("/runs")
def list_runs(config: Annotated[int | None, Query(ge=1)] = None, limit: Annotated[int, Query(ge=1, le=200)] = 50, db: Session = Depends(get_db)) -> list[dict]:
    q = select(MailRun, MailConfig.name).join(MailConfig, MailConfig.id == MailRun.config_id).order_by(MailRun.id.desc()).limit(limit)
    if config:
        q = q.where(MailRun.config_id == config)
    return [
        {"id": r.id, "configId": r.config_id, "configName": name, "scheduledFor": _iso(r.scheduled_for), "startedAt": _iso(r.started_at), "finishedAt": _iso(r.finished_at), "status": r.status, "sent": r.sent, "failed": r.failed, "skipped": r.skipped, "message": r.message}
        for r, name in db.execute(q).all()
    ]

