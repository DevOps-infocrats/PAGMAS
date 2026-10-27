"""Scheduled AMC Conversion e-mails: claim a due slot, build each recipient's e-mail from the template, send.

One tick (every 60 s in a background thread – only when AMC_REPORT_EMAILS_ENABLED=true, never in tests, first tick one
interval after start-up, so a start-up itself sends nothing):
  1. enabled schedules whose next_run_at has come;
  2. claim the slot: insert mail_runs(config_id, scheduled_for) – unique, so another process / thread trying the same
     slot fails – and move next_run_at to the next future time in the same transaction;
  3. a slot older than MISSED_GRACE is recorded as SKIPPED (no late flood after downtime);
  4. otherwise: recipients (audience.py) → figures of each one's GPs (report.py) → template (template.py) → one SMTP
     connection for all; the run records counts and reasons only (no addresses, passwords or content).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections import Counter

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import MailConfig, MailRun, MailTemplate
from . import template as tpl
from .audience import Recipient, recipients
from .report import ReportContext
from .schedule import MISSED_GRACE, Schedule, next_run
from .smtp import MailError, SmtpSession, build_message

log = logging.getLogger(__name__)
TICK_SECONDS = 60
_stop = threading.Event()
_thread: threading.Thread | None = None
_tick_lock = threading.Lock()


def utc(v: dt.datetime | None) -> dt.datetime | None:
    """SQLite returns naive datetimes; everything stored here is UTC."""
    if v is None:
        return None
    return v.replace(tzinfo=dt.UTC) if v.tzinfo is None else v.astimezone(dt.UTC)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def schedule_of(cfg: MailConfig) -> Schedule:
    return Schedule(cfg.frequency, cfg.start_date, cfg.send_time, cfg.weekday, cfg.month_day)


def plan_next(cfg: MailConfig, after: dt.datetime | None = None) -> None:
    """next_run_at = first run strictly after `after` (default now); cleared when the schedule is disabled."""
    cfg.next_run_at = next_run(schedule_of(cfg), after or now_utc(), get_settings().mail_timezone) if cfg.enabled else None


# ---------------------------------------------------------------- templates


def ensure_default_templates(db: Session) -> None:
    """Create the built-in templates that do not exist yet (never overwrites an edited one)."""
    have = set(db.scalars(select(MailTemplate.key).where(MailTemplate.key.is_not(None))))
    for t in tpl.DEFAULT_TEMPLATES:
        if t["key"] not in have:
            db.add(MailTemplate(**t))
    db.commit()


def template_for(db: Session, cfg: MailConfig) -> MailTemplate:
    t = db.get(MailTemplate, cfg.template_id) if cfg.template_id else None
    if t is None:
        ensure_default_templates(db)
        t = db.scalars(select(MailTemplate).where(MailTemplate.key == "detailed")).one()
    return t


def compose(ctx: ReportContext, subject: str, body: str, r: Recipient) -> tpl.Rendered:
    figures = ctx.figures(r.gps)
    v = tpl.values(figures, ctx.periods(), r.name, r.role_label, "; ".join(r.areas), r.breakdown)
    return tpl.render(subject, body, v)


# ---------------------------------------------------------------- one tick


def run_due(now: dt.datetime | None = None, session_factory=SessionLocal) -> list[int]:
    """Process every due slot. Returns the ids of the mail_runs created. Nothing happens while the switch is off."""
    if not get_settings().amc_report_emails_enabled:
        return []
    now = now or now_utc()
    created: list[int] = []
    with _tick_lock:
        with session_factory() as db:
            due = list(db.scalars(select(MailConfig.id).where(MailConfig.enabled.is_(True), MailConfig.next_run_at.is_not(None), MailConfig.next_run_at <= now)))
        for cid in due:
            try:
                run_id = _claim_and_run(cid, now, session_factory)
            except Exception:  # one broken schedule must not stop the others
                log.exception("Mail schedule %s failed", cid)
                continue
            if run_id:
                created.append(run_id)
    return created


def claim(db: Session, cid: int, now: dt.datetime) -> MailRun | None:
    """Claim the schedule's due slot: the run row and the moved next_run_at commit together, or not at all."""
    cfg = db.get(MailConfig, cid)
    if cfg is None or not cfg.enabled or cfg.next_run_at is None:
        return None
    slot = utc(cfg.next_run_at)
    if slot is None or slot > now:
        return None
    nxt = next_run(schedule_of(cfg), max(now, slot), get_settings().mail_timezone)
    missed = now - slot > MISSED_GRACE
    run = MailRun(config_id=cid, scheduled_for=slot, status="SKIPPED" if missed else "RUNNING", started_at=now)
    if missed:
        run.finished_at = now
        run.message = f"Missed: the server was not running at the planned time (more than {int(MISSED_GRACE.total_seconds() // 3600)} h ago)."
    db.add(run)
    moved = db.execute(update(MailConfig).where(MailConfig.id == cid, MailConfig.next_run_at == cfg.next_run_at).values(next_run_at=nxt, last_run_at=now, last_status=run.status)).rowcount
    if not moved:  # someone else moved it since we read it
        db.rollback()
        return None
    try:
        db.commit()
    except IntegrityError:  # the slot was claimed by another process
        db.rollback()
        return None
    return run


def _claim_and_run(cid: int, now: dt.datetime, session_factory) -> int | None:
    with session_factory() as db:
        run = claim(db, cid, now)
        if run is None:
            return None
        run_id = run.id
        if run.status == "SKIPPED":
            log.warning("Mail schedule %s: slot %s missed – skipped", cid, run.scheduled_for)
            return run_id
        cfg = db.get(MailConfig, cid)
        status, sent, failed, skipped, message = deliver(db, cfg)
        db.execute(update(MailRun).where(MailRun.id == run_id).values(status=status, sent=sent, failed=failed, skipped=skipped, message=message, finished_at=now_utc()))
        db.execute(update(MailConfig).where(MailConfig.id == cid).values(last_status=status))
        db.commit()
        log.info("Mail schedule %s run %s: %s (sent %s, failed %s, skipped %s)", cid, run_id, status, sent, failed, skipped)
        return run_id


def deliver(db: Session, cfg: MailConfig) -> tuple[str, int, int, int, str | None]:
    """Send the schedule's e-mail to every recipient. Returns (status, sent, failed, skipped, message)."""
    from ..analytics.store import NoDataError, get_store

    try:
        store = get_store()
    except NoDataError:
        return "FAILED", 0, 0, 0, "No active data – nothing was sent."
    people, skipped = recipients(db, store, cfg)
    notes = [f"{len(skipped)} skipped: " + ", ".join(f"{n}× {r}" for r, n in Counter(s.reason for s in skipped).items())] if skipped else []
    if not people:
        return "SKIPPED", 0, 0, len(skipped), "; ".join(["No eligible recipients.", *notes])
    t = template_for(db, cfg)
    ctx = ReportContext(store)
    sent, errors = 0, Counter()
    try:
        with SmtpSession() as smtp:
            for p in people:
                r = compose(ctx, t.subject, t.body, p)
                try:
                    smtp.send(build_message(p.emails, r.subject, r.text, r.html))
                    sent += 1
                except MailError as exc:
                    errors[str(exc)] += 1
    except MailError as exc:  # connection / login / settings: nothing more could be sent
        return "FAILED", sent, len(people) - sent, len(skipped), "; ".join([str(exc), *notes])
    failed = sum(errors.values())
    notes = [f"{n}× {e}" for e, n in errors.items()] + notes
    status = "SUCCESS" if not failed else ("PARTIAL" if sent else "FAILED")
    return status, sent, failed, len(skipped), "; ".join(notes) or None


# ---------------------------------------------------------------- background thread


def _loop() -> None:
    while not _stop.wait(TICK_SECONDS):  # first tick one interval after start-up
        try:
            run_due()
        except Exception:
            log.exception("Mail scheduler tick failed")


def start_scheduler() -> bool:
    """Start the background thread when the switch is on (never in tests). Returns whether it runs."""
    global _thread
    s = get_settings()
    if not s.amc_report_emails_enabled or s.app_env == "test":
        log.info("Scheduled AMC e-mails are off (AMC_REPORT_EMAILS_ENABLED=false) – scheduler not started")
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="mail-scheduler", daemon=True)
    _thread.start()
    log.info("Mail scheduler started (every %ss, timezone %s)", TICK_SECONDS, s.mail_timezone)
    return True


def stop_scheduler() -> None:
    _stop.set()


def scheduler_running() -> bool:
    return bool(_thread and _thread.is_alive())
