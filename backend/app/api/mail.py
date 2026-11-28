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

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..analytics.store import NoDataError, Store, get_store
from ..config import get_settings
from ..db import get_db
from ..mail import service
from ..mail import template as tpl
from ..mail.audience import AUDIENCE_LABELS, AUDIENCES, Assignment, _json_list, check_assignments, filter_options, location_tree, matrix_frame, matrix_people, recipients
from ..mail.report import ReportContext
from ..mail.schedule import Schedule, ScheduleError, describe, validate
from ..mail.smtp import MailError, send_test_mail, smtp_status, valid_address
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
        "locations": location_tree(st) if st is not None else [],  # area picker of the extra recipients
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
    from ..mail.layout import LOGO_CID

    html = r.html.replace(f"cid:{LOGO_CID}", "/brand/pratap-wordmark.png")  # the browser preview shows the dashboard's own logo file
    return {"recipient": {"name": people[0].name, "role": people[0].role_label, "emails": people[0].emails}, "subject": r.subject, "html": html, "text": r.text}


# ---------------------------------------------------------------- schedules


class AreaIn(BaseModel):
    level: Literal["circle", "district", "block"]
    id: str = Field(min_length=1, max_length=120)


class ExtraRecipientIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str | None = Field(default=None, max_length=120)
    areas: list[AreaIn] = Field(default_factory=list, max_length=100)  # [] = every circle (within the filters)


class ConfigIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    template_id: int | None = Field(default=None, alias="templateId")
    audiences: list[Audience] = Field(default_factory=list, max_length=4)
    extra_recipients: list[ExtraRecipientIn] = Field(default_factory=list, alias="extraRecipients", max_length=50)
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
        "extraRecipients": _json_list(c.extra_recipients),
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
    if not body.audiences and not body.extra_recipients:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one audience or add an extra recipient")
    extras: dict[str, dict] = {}
    for x in body.extra_recipients:
        addr = valid_address(x.email)
        if not addr:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not a valid e-mail address: {x.email[:80]}")
        if addr in extras:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Extra recipient added twice: {addr}")
        areas = list(dict.fromkeys((a.level, a.id.strip()) for a in x.areas))
        extras[addr] = {"email": addr, "name": " ".join((x.name or "").split()) or None, "areas": [{"level": lv, "id": i} for lv, i in areas]}
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
        areas = [Assignment(a["level"], a["id"]) for x in extras.values() for a in x["areas"]]
        if areas and (problems := check_assignments(st, areas)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Extra recipients: " + "; ".join(problems[:5]))
    c.name = body.name.strip()
    c.template_id = body.template_id
    c.audiences = json.dumps(list(dict.fromkeys(body.audiences)))
    c.filter_circles, c.filter_bas = json.dumps(sorted(set(body.filter_circles))), json.dumps(sorted({b.strip() for b in body.filter_bas}))
    c.filter_blocks, c.filter_people = json.dumps(sorted(set(body.filter_blocks))), json.dumps(sorted(set(body.filter_people)))
    c.user_ids = json.dumps(ids)
    c.extra_recipients = json.dumps(list(extras.values()))
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

#REFRACTOR TEST AMC = TRUE
@router.get("/runs")
def list_runs(config: Annotated[int | None, Query(ge=1)] = None, limit: Annotated[int, Query(ge=1, le=200)] = 50, db: Session = Depends(get_db)) -> list[dict]:
    q = select(MailRun, MailConfig.name).join(MailConfig, MailConfig.id == MailRun.config_id).order_by(MailRun.id.desc()).limit(limit)
    if config:
        q = q.where(MailRun.config_id == config)
    return [
        {"id": r.id, "configId": r.config_id, "configName": name, "scheduledFor": _iso(r.scheduled_for), "startedAt": _iso(r.started_at), "finishedAt": _iso(r.finished_at), "status": r.status, "sent": r.sent, "failed": r.failed, "skipped": r.skipped, "message": r.message}
        for r, name in db.execute(q).all()
    ]



# ---------------------------------------------------------------- O&M Daily Dashboard e-mail (app.mail.om_service)
# One e-mail per circle with that circle's daily dashboard as the HTML body. Saving never sends; "Send test mail"
# goes to the admin's own address only; "Send now" is an explicit admin action; scheduled sending also needs
# OM_DAILY_EMAILS_ENABLED=true.

from ..mail import om_service as om  # noqa: E402
from ..models import OmMailCircle, OmMailDelivery, OmMailRun  # noqa: E402

CircleKey = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]


def _om_fail(exc: om.OmMailError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _om_rate(admin_id: int) -> None:
    """The same limit as the plain test mail (shared counter): at most TEST_LIMIT mails per admin per window."""
    now = time.monotonic()
    with _test_lock:
        hits = _test_hits[admin_id]
        while hits and now - hits[0] > TEST_WINDOW_S:
            hits.popleft()
        if len(hits) >= TEST_LIMIT:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"At most {TEST_LIMIT} test mails per {TEST_WINDOW_S // 60} minutes - try again later")
        hits.append(now)


def _om_last(db: Session) -> dict[str, tuple[str, dt.datetime | None]]:
    """circle id -> (status, when) of its latest real e-mail (scheduled or Send now – tests not counted)."""
    out: dict[str, tuple[str, dt.datetime | None]] = {}
    q = (select(OmMailDelivery.circle_id, OmMailDelivery.status, OmMailDelivery.sent_at, OmMailDelivery.created_at)
         .join(OmMailRun, OmMailRun.id == OmMailDelivery.run_id).where(OmMailRun.kind != "TEST").order_by(OmMailDelivery.created_at.desc(), OmMailDelivery.id.desc()))
    for cid, st, sent, made in db.execute(q):
        out.setdefault(cid, (st, sent or made))
    return out


def _om_circle_json(c: OmMailCircle, s, last: tuple[str, dt.datetime | None] | None = None) -> dict:
    to, cc = om.recipients(c, s)
    return {
        "lastStatus": last[0] if last else None, "lastAt": _iso(last[1]) if last else None,
        "circleId": c.circle_id, "circleName": c.circle_name, "enabled": c.enabled, "to": om.jlist(c.to_emails), "cc": om.jlist(c.cc_emails),
        "subject": c.subject or "", "includeAms": c.include_ams, "areaManagers": om.jlist(c.area_managers),
        "remarks": c.remarks or "", "remarksUpdatedBy": c.remarks_updated_by, "remarksUpdatedAt": _iso(c.remarks_updated_at),
        "effective": {"to": to, "cc": cc},  # what the next e-mail would really use (central CC and AMs included)
    }


def _om_settings_json(s) -> dict:
    return {
        "enabled": s.enabled, "centralCc": om.jlist(s.central_cc), "schedule": om.jdict(s.schedule), "windowStart": s.window_start, "windowEnd": s.window_end,
        "subjectTemplate": s.subject_template, "nextRunAt": _iso(s.next_run_at) if s.enabled else None, "lastRunAt": _iso(s.last_run_at), "lastStatus": s.last_status,
        "updatedBy": s.updated_by, "updatedAt": _iso(s.updated_at),
    }


@router.get("/om")
def om_config(db: Session = Depends(get_db)) -> dict:
    """Settings, the circles of the active data with their recipients, the status tiles and the SMTP state."""
    s = om.settings_row(db)
    store = _store_or_none()
    if store is not None:
        from ..mail.om_data import Context

        circles = om.ensure_circles(db, Context.build(store).circles())
    else:
        circles = list(db.scalars(select(OmMailCircle).order_by(OmMailCircle.circle_id)))
    st = smtp_status()
    last = _om_last(db)
    circles = [c for c in circles if c.circle_id != om.ALL_CIRCLES]
    return {
        "settings": _om_settings_json(s), "circles": [_om_circle_json(c, s, last.get(c.circle_id)) for c in circles], "tiles": om.tiles(db),
        # the management e-mail with every circle on one page (own To / CC / subject / on-off)
        "allCircles": _om_circle_json(om.all_row(db), s, last.get(om.ALL_CIRCLES)), "allSubjectDefault": om.ALL_SUBJECT,
        "smtpConfigured": st.configured, "smtpProblems": st.problems, "timezone": get_settings().mail_timezone,
        "placeholders": list(om.PLACEHOLDERS), "maxTimesPerDay": om.MAX_TIMES_PER_DAY,
    }


class OmSettingsIn(BaseModel):
    enabled: bool = False
    centralCc: list[str] = Field(default_factory=list, max_length=30)
    schedule: dict[str, list[str]] = Field(default_factory=dict)
    windowStart: str = Field("08:00", pattern=r"^\d{2}:\d{2}$")
    windowEnd: str = Field("20:00", pattern=r"^\d{2}:\d{2}$")
    subjectTemplate: str = Field(om.DEFAULT_SUBJECT, max_length=200)


@router.put("/om/settings")
def om_save_settings(body: OmSettingsIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Save the settings; the next run time is always in the future (saving never sends)."""
    s = om.settings_row(db)
    try:
        sched = om.clean_schedule(body.schedule, body.windowStart, body.windowEnd)
        central = om.clean_emails(body.centralCc, "Central CC")
    except om.OmMailError as exc:
        raise _om_fail(exc) from None
    nxt = om.next_slot(sched, om.now_utc()) if body.enabled else None
    if body.enabled and nxt is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one day and time before switching the daily mail on")
    s.central_cc, s.schedule, s.window_start, s.window_end = json.dumps(central), json.dumps(sched), body.windowStart, body.windowEnd
    s.subject_template = om.clean_subject(body.subjectTemplate) or om.DEFAULT_SUBJECT
    s.enabled, s.next_run_at = body.enabled, nxt
    s.updated_by, s.updated_at = admin.name, om.now_utc()
    db.commit()
    audit(db, "om_mail_settings", request, admin.id, f"enabled={body.enabled} times={sum(len(v) for v in sched.values())} central_cc={len(central)}")
    return om_config(db)


class OmAreaManagerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    source: Literal["matrix", "manual"] = "manual"
    enabled: bool = True


class OmCircleIn(BaseModel):
    enabled: bool = False
    to: list[str] = Field(default_factory=list, max_length=30)
    cc: list[str] = Field(default_factory=list, max_length=30)
    subject: str = Field("", max_length=200)
    includeAms: bool = False
    areaManagers: list[OmAreaManagerIn] = Field(default_factory=list, max_length=60)
    remarks: str = Field("", max_length=4000)


@router.put("/om/circles/{circle_id}")
def om_save_circle(circle_id: CircleKey, body: OmCircleIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Save one circle's recipients, subject, Area Managers and remarks (nothing is sent)."""
    c = om.all_row(db) if circle_id == om.ALL_CIRCLES else db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == circle_id)).first()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Circle not found")
    if circle_id == om.ALL_CIRCLES:  # the All Circles mail: only To / CC / subject / on-off (remarks come from each circle)
        body = body.model_copy(update={"includeAms": False, "areaManagers": [], "remarks": ""})
    try:
        to, cc = om.clean_emails(body.to, "To"), om.clean_emails(body.cc, "CC")
        ams = om.clean_area_managers([m.model_dump() for m in body.areaManagers])
    except om.OmMailError as exc:
        raise _om_fail(exc) from None
    if body.enabled and not to and not (body.includeAms and any(m["enabled"] for m in ams)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Add at least one To address for {c.circle_name} before switching it on")
    remarks = "\n".join(ln.rstrip() for ln in body.remarks.replace("\r", "").split("\n")).strip() or None
    if remarks != c.remarks:
        c.remarks, c.remarks_updated_by, c.remarks_updated_at = remarks, admin.name, om.now_utc()
    c.enabled, c.to_emails, c.cc_emails = body.enabled, json.dumps(to), json.dumps(cc)
    c.subject = om.clean_subject(body.subject) or None
    c.include_ams, c.area_managers, c.updated_at = body.includeAms, json.dumps(ams), om.now_utc()
    db.commit()
    audit(db, "om_mail_circle", request, admin.id, f"{circle_id} enabled={body.enabled} to={len(to)} cc={len(cc)} ams={len(ams)} include_ams={body.includeAms}")
    return _om_circle_json(c, om.settings_row(db), _om_last(db).get(circle_id))


@router.post("/om/circles/{circle_id}/area-managers/refresh")
def om_refresh_ams(circle_id: CircleKey, db: Session = Depends(get_db)) -> dict:
    """The circle's Area Managers from the Escalation Matrix (manual entries and on / off choices kept). Not saved
    until the circle is saved."""
    c = db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == circle_id)).first()
    store = _store_or_none()
    if c is None or store is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Circle or active data not found")
    return {"areaManagers": om.merge_area_managers(om.jlist(c.area_managers), om.matrix_area_managers(store, circle_id))}


@router.get("/om/preview/{circle_id}")
def om_preview(circle_id: CircleKey, db: Session = Depends(get_db)) -> dict:
    """The circle's e-mail as it would be sent now (HTML + subject). Nothing is sent or stored."""
    try:
        html, subject, view = om.preview(db, circle_id)
    except om.OmMailError as exc:
        raise _om_fail(exc) from None
    return {"html": html, "subject": subject, "dataAsOf": view["dataAsOf"], "week": view["week"], "sizeBytes": len(html.encode())}


class OmTestIn(BaseModel):
    circleId: str = Field(pattern=r"^[a-z0-9-]{1,40}$")


@router.post("/om/test")
def om_test(body: OmTestIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """The circle's e-mail to the signed-in admin's own address only ("[TEST]" subject)."""
    _om_rate(admin.id)
    try:
        run = om.send_test(db, admin.name, admin.email, body.circleId)
    except om.OmMailError as exc:
        raise _om_fail(exc) from None
    audit(db, "om_mail_test", request, admin.id, f"{body.circleId} {run.status}")
    return {"ok": run.status == "SUCCESS", "status": run.status, "message": run.message, "to": admin.email}


class OmSendNowIn(BaseModel):
    circleId: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,40}$")


@router.post("/om/send-now")
def om_send_now(body: OmSendNowIn, request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Send the enabled circles' e-mails (or one circle's) right now - the admin confirmed it on the page."""
    try:
        run = om.send_now(db, admin.name, body.circleId)
    except om.OmMailError as exc:
        raise _om_fail(exc) from None
    audit(db, "om_mail_send_now", request, admin.id, f"{body.circleId or 'all'} {run.status} {run.message}")
    return {"ok": run.status == "SUCCESS", "status": run.status, "message": run.message, "sent": run.sent, "failed": run.failed, "skipped": run.skipped}


@router.post("/om/test-connection")
def om_test_connection(request: Request, admin: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Connect and sign in to the mail server, then close - nothing is sent."""
    from ..mail.smtp import SmtpSession

    try:
        with SmtpSession():
            pass
    except MailError as exc:
        return {"ok": False, "message": str(exc)}
    audit(db, "om_mail_test_connection", request, admin.id, "ok")
    return {"ok": True, "message": "Connected and signed in to the mail server"}


@router.get("/om/deliveries")
def om_deliveries(
    status_: Annotated[Literal["SENT", "FAILED", "SKIPPED", "UNKNOWN", "SENDING", "PENDING"] | None, Query(alias="status")] = None,
    circle: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}$")] = None,
    kind: Annotated[Literal["SCHEDULED", "MANUAL", "TEST"] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    db: Session = Depends(get_db),
) -> dict:
    """The delivery log: one row per circle e-mail - status, kind, To, CC, subject, error, when (never the content)."""
    sel = select(OmMailDelivery, OmMailRun).join(OmMailRun, OmMailRun.id == OmMailDelivery.run_id)
    if status_:
        sel = sel.where(OmMailDelivery.status == status_)
    if circle:
        sel = sel.where(OmMailDelivery.circle_id == circle)
    if kind:
        sel = sel.where(OmMailRun.kind == kind)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        sel = sel.where(func.lower(OmMailDelivery.subject).like(term) | func.lower(OmMailDelivery.to_emails).like(term) | func.lower(OmMailDelivery.cc_emails).like(term))
    total = db.scalar(select(func.count()).select_from(sel.subquery())) or 0
    size = 50
    rows = db.execute(sel.order_by(OmMailDelivery.created_at.desc(), OmMailDelivery.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {
        "total": total, "page": page, "pageSize": size,
        "items": [
            {"id": d.id, "runId": r.id, "kind": r.kind, "triggeredBy": r.triggered_by, "circleId": d.circle_id, "status": d.status, "to": om.jlist(d.to_emails),
             "cc": om.jlist(d.cc_emails), "subject": d.subject, "error": d.error, "attempts": d.attempts, "sizeBytes": d.size_bytes,
             "dataAsOf": r.data_as_of.isoformat() if r.data_as_of else None, "createdAt": _iso(d.created_at), "sentAt": _iso(d.sent_at)}
            for d, r in rows
        ],
    }
