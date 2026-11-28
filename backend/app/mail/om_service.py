"""O&M Daily Dashboard e-mail – settings, schedule, recipients and delivery (one e-mail per circle).

  WHEN   the weekly matrix of the settings ({weekday: ["HH:MM", …]}, MAIL_TIMEZONE), only inside the permitted window.
         next_run_at is always strictly in the future: saving or enabling never sends at once. A slot seen more than
         MISSED_GRACE late (server was down) or outside the window is recorded as SKIPPED – no late flood.
  CLAIM  om_mail_runs.slot_key is unique: the first process to insert a slot sends it, every other attempt is refused,
         and next_run_at moves on in the same transaction – no double e-mails.
  WHAT   one snapshot of the active data per run (all circles from the same dataset); each circle's e-mail is built
         only from that circle's figures (app.mail.om_data) and rendered by app.mail.om_html.
  WHO    To = the circle's To + its enabled Area Managers (when "include Area Managers" is on); CC = the circle's CC +
         the central CC; addresses validated, de-duplicated, an address in To is not repeated in CC.
  SEND   one SMTP session per run; a delivery is SENDING before the server is asked and SENT / FAILED after; one retry
         on a failure. A delivery found SENDING later (process stopped mid-send) becomes UNKNOWN and is never re-sent
         automatically (a missed daily report is better than a duplicate).
  LOG    every circle's e-mail is a delivery row: status, To, CC, subject, error, size – never the content.

ALL CIRCLES  one more e-mail with every circle on one page (app.mail.om_html.render_all) for the management: its own
         row in om_mail_circles (circle_id "all" – never listed with the circles), its own To / CC / subject and
         on / off; it goes with the same schedule when switched on, has its own test mail and "Send now" (the circles'
         "Send now" never sends it). Only the To / CC typed for it – no central CC, no Area Managers.

Scheduled sending needs OM_DAILY_EMAILS_ENABLED=true AND the setting switched on; a test mail (to the admin only) and
"Send now" (an admin's explicit action) need only working SMTP settings.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import OmMailCircle, OmMailDelivery, OmMailRun, OmMailSetting
from .schedule import zone
from .smtp import MailError, SmtpSession, build_message, valid_address

log = logging.getLogger(__name__)

MISSED_GRACE = dt.timedelta(hours=2)
STALE_SENDING = dt.timedelta(minutes=30)  # a delivery still SENDING after this is UNKNOWN (never re-sent)
MAX_RECIPIENTS = 50  # To + CC of one e-mail
MAX_TIMES_PER_DAY = 4
DEFAULT_SUBJECT = "O&M Daily Dashboard – {circle} – {date}"
PLACEHOLDERS = ("{circle}", "{date}", "{week}")
RETRY_PAUSE_S = 3
ALL_CIRCLES = "all"  # every circle on one page: preview / download, and the management e-mail (its own row)
ALL_SUBJECT = "O&M Daily Dashboard – All Circles – {date}"


class OmMailError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def utc(v: dt.datetime | None) -> dt.datetime | None:
    if v is None:
        return None
    return v.replace(tzinfo=dt.UTC) if v.tzinfo is None else v.astimezone(dt.UTC)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def jlist(v: str | None) -> list:
    try:
        x = json.loads(v or "[]")
    except (TypeError, ValueError):
        return []
    return x if isinstance(x, list) else []


def jdict(v: str | None) -> dict:
    try:
        x = json.loads(v or "{}")
    except (TypeError, ValueError):
        return {}
    return x if isinstance(x, dict) else {}


# ---------------------------------------------------------------- addresses and subject


def clean_emails(values: list[Any], what: str) -> list[str]:
    """Validated, lower-case, de-duplicated addresses; raises for an invalid one (the admin sees which)."""
    out: list[str] = []
    for v in values or []:
        raw = str(v or "").strip()
        if not raw:
            continue
        a = valid_address(raw)
        if a is None:
            raise OmMailError(422, f"{what}: '{raw[:80]}' is not a valid e-mail address")
        if a not in out:
            out.append(a)
    return out


def clean_subject(text: str | None) -> str:
    """One line (no header injection), at most 200 characters; blank = the default subject."""
    s = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())[:200]
    return s


def render_subject(template: str | None, view: dict[str, Any]) -> str:
    t = clean_subject(template) or DEFAULT_SUBJECT
    date = dt.date.fromisoformat(view["dataAsOf"]).strftime("%d %b %Y")
    return clean_subject(t.replace("{circle}", view["circle"]).replace("{date}", date).replace("{week}", view["week"]))[:250]


def recipients(c: OmMailCircle, s: OmMailSetting) -> tuple[list[str], list[str]]:
    """(To, CC) of one circle's e-mail – see the module docstring."""
    to: list[str] = []
    for a in jlist(c.to_emails) + ([m.get("email") for m in jlist(c.area_managers) if m.get("enabled", True)] if c.include_ams else []):
        a = valid_address(str(a or ""))
        if a and a not in to:
            to.append(a)
    cc: list[str] = []
    central = [] if c.circle_id == ALL_CIRCLES else jlist(s.central_cc)  # the All Circles mail: only its own CC
    for a in jlist(c.cc_emails) + central:
        a = valid_address(str(a or ""))
        if a and a not in to and a not in cc:
            cc.append(a)
    return to, cc


# ---------------------------------------------------------------- schedule


def _hhmm(v: str) -> dt.time:
    try:
        return dt.time.fromisoformat(v)
    except (TypeError, ValueError):
        raise OmMailError(422, f"'{v}' is not a time (HH:MM)") from None


def clean_schedule(sched: dict[str, Any], window_start: str, window_end: str) -> dict[str, list[str]]:
    """{"0".."6": sorted unique "HH:MM"} – every time inside the permitted window, at most MAX_TIMES_PER_DAY a day."""
    ws, we = _hhmm(window_start), _hhmm(window_end)
    if ws >= we:
        raise OmMailError(422, "The sending window must start before it ends")
    out: dict[str, list[str]] = {}
    for day in range(7):
        times = sorted({_hhmm(str(t)).strftime("%H:%M") for t in (sched or {}).get(str(day), []) or []})
        if len(times) > MAX_TIMES_PER_DAY:
            raise OmMailError(422, f"At most {MAX_TIMES_PER_DAY} send times per day")
        for t in times:
            if not (ws <= _hhmm(t) <= we):
                raise OmMailError(422, f"{t} is outside the sending window {window_start}–{window_end}")
        out[str(day)] = times
    return out


def next_slot(sched: dict[str, list[str]], after: dt.datetime) -> dt.datetime | None:
    """The first scheduled time strictly after `after` (UTC), or None when no day has a time."""
    tz = zone(get_settings().mail_timezone)
    local = after.astimezone(tz)
    for k in range(8):
        day = local.date() + dt.timedelta(days=k)
        for t in sched.get(str(day.weekday()), []):
            cand = dt.datetime.combine(day, _hhmm(t), tz)
            if cand > local:
                return cand.astimezone(dt.UTC)
    return None


def in_window(s: OmMailSetting, at: dt.datetime) -> bool:
    local = at.astimezone(zone(get_settings().mail_timezone)).time()
    return _hhmm(s.window_start) <= local <= _hhmm(s.window_end)


# ---------------------------------------------------------------- settings rows


def settings_row(db: Session) -> OmMailSetting:
    s = db.scalars(select(OmMailSetting).order_by(OmMailSetting.id).limit(1)).first()
    if s is None:
        s = OmMailSetting(enabled=False, central_cc="[]", schedule=json.dumps({str(d): [] for d in range(7)}), window_start="08:00",
                          window_end="20:00", subject_template=DEFAULT_SUBJECT, updated_at=now_utc())
        db.add(s)
        db.commit()
    return s


def ensure_circles(db: Session, circles: list[dict[str, Any]]) -> list[OmMailCircle]:
    """A (disabled) row for every circle of the data; returns the rows in the given order."""
    have = {c.circle_id: c for c in db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id != ALL_CIRCLES))}
    added = False
    for c in circles:
        if c["id"] not in have:
            row = OmMailCircle(circle_id=c["id"], circle_name=c["name"], enabled=False, to_emails="[]", cc_emails="[]", include_ams=False,
                               area_managers="[]", updated_at=now_utc())
            db.add(row)
            have[c["id"]] = row
            added = True
    if added:
        db.commit()
    order = [c["id"] for c in circles]
    return sorted(have.values(), key=lambda r: (order.index(r.circle_id) if r.circle_id in order else 99, r.circle_id))


def all_row(db: Session) -> OmMailCircle:
    """The All Circles e-mail's row (created switched off, without recipients, on first use)."""
    c = db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == ALL_CIRCLES)).first()
    if c is None:
        c = OmMailCircle(circle_id=ALL_CIRCLES, circle_name="All Circles", enabled=False, to_emails="[]", cc_emails="[]", include_ams=False,
                         area_managers="[]", updated_at=now_utc())
        db.add(c)
        db.commit()
    return c


def _all_views(db: Session, ctx: Any, store: Any) -> list[dict[str, Any]]:
    """The views of every circle of the data (with each circle's remarks) – the All Circles page."""
    from .om_data import circle_view, frt_on_portal

    ids = [c["id"] for c in ctx.circles()]
    if not ids:
        raise OmMailError(404, "No circles in the active data")
    rows = {c.circle_id: c for c in db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id.in_(ids)))}
    return [circle_view(ctx, cid, frt_on_portal(store, cid, db), rows[cid].remarks if cid in rows else None) for cid in ids]


def with_time(subject: str, at: dt.datetime | None = None) -> str:
    """The subject with the send time ("… – 09:00", MAIL_TIMEZONE): every e-mail has its own subject, so Gmail does not
    join the daily mails into one conversation (and does not trim them as repeated content)."""
    local = (at or now_utc()).astimezone(zone(get_settings().mail_timezone))
    return clean_subject(f"{subject} – {local:%H:%M}")[:250]


def _all_subject(template: str | None, views: list[dict[str, Any]]) -> str:
    first = views[0]
    return render_subject(template or ALL_SUBJECT, {"circle": "All Circles", "dataAsOf": first["dataAsOf"], "week": first["week"]})


def matrix_area_managers(store: Any, circle_id: str) -> list[dict[str, Any]]:
    """Area Managers of the circle in the Escalation Matrix, with their first valid e-mail."""
    from .audience import matrix_people

    out = []
    for p in matrix_people(store, ("am",)):
        if p.circle_id == circle_id and p.emails:
            out.append({"name": p.name, "email": p.emails[0], "source": "matrix", "enabled": True})
    return sorted(out, key=lambda x: x["name"].lower())


def merge_area_managers(current: list[dict[str, Any]], from_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The matrix list refreshed: matrix entries keep their on / off choice, manual entries stay, removed matrix
    people disappear."""
    keep = {str(m.get("email", "")).lower(): m for m in current if m.get("source") == "matrix"}
    out = []
    for m in from_matrix:
        old = keep.get(m["email"].lower())
        out.append(m | {"enabled": bool(old.get("enabled", True)) if old else True})
    have = {m["email"].lower() for m in out}
    out += [m for m in current if m.get("source") == "manual" and str(m.get("email", "")).lower() not in have]
    return out


def clean_area_managers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for m in items or []:
        name = " ".join(str(m.get("name") or "").split())[:120]
        a = valid_address(str(m.get("email") or ""))
        if not name or a is None:
            raise OmMailError(422, f"Area Manager '{name or m.get('email') or ''}': name and a valid e-mail are required")
        if a in seen:
            continue
        seen.add(a)
        out.append({"name": name, "email": a, "source": "matrix" if m.get("source") == "matrix" else "manual", "enabled": bool(m.get("enabled", True))})
    return out


# ---------------------------------------------------------------- building and sending


def _store():
    from ..analytics.store import NoDataError, get_store

    try:
        return get_store()
    except NoDataError:
        raise OmMailError(409, "No active master data – upload the master data first") from None


def preview(db: Session, circle_id: str) -> tuple[str, str, dict[str, Any]]:
    """(html, subject, view) of one circle as it would be sent now – nothing is sent or stored.
    circle_id ALL_CIRCLES = the All Circles page (every circle on one page) – preview / download only, never e-mailed."""
    from .om_data import Context, circle_view, frt_on_portal
    from .om_html import render, render_all

    store = _store()
    ctx = Context.build(store)
    if circle_id == ALL_CIRCLES:
        views = _all_views(db, ctx, store)
        html, _txt = render_all(views, inline_logo=True)  # preview / download: the logo inside the file
        first = views[0]
        row = db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == ALL_CIRCLES)).first()
        summary = {"dataAsOf": first["dataAsOf"], "week": first["week"], "circle": "All Circles"}
        return html, with_time(_all_subject(row.subject if row else None, views)), summary
    if circle_id not in {c["id"] for c in ctx.circles()}:
        raise OmMailError(404, "Circle not found in the active data")
    c = db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == circle_id)).first()
    view = circle_view(ctx, circle_id, frt_on_portal(store, circle_id, db), c.remarks if c else None)
    html, _txt = render(view, inline_logo=True)  # preview / download: the logo inside the file
    s = settings_row(db)
    return html, with_time(render_subject((c.subject if c and c.subject else None) or s.subject_template, view)), view


def _finish(db: Session, run: OmMailRun, message: str | None = None) -> OmMailRun:
    total = run.sent + run.failed
    run.status = "SKIPPED" if total == 0 and run.skipped else "SUCCESS" if run.failed == 0 and run.sent else "FAILED" if run.sent == 0 else "PARTIAL"
    run.finished_at = now_utc()
    run.message = (message or f"{run.sent} sent · {run.failed} failed · {run.skipped} skipped")[:500]
    db.commit()
    return run


def deliver(db: Session, run: OmMailRun, circles: list[OmMailCircle], test_to: str | None = None) -> OmMailRun:
    """Build and send one e-mail per circle of the run (see the module docstring). test_to = the admin's own address:
    the e-mail goes only there, with "[TEST]" in the subject."""
    from .om_data import Context, circle_view, frt_on_portal
    from .om_html import attach_logo, render, render_all

    s = settings_row(db)
    try:
        store = _store()
    except OmMailError as exc:
        return _finish(db, run, exc.message)
    ctx = Context.build(store)
    run.dataset_id, run.data_as_of = ctx.dataset_id, ctx.data_as_of
    db.commit()
    known = {c["id"] for c in ctx.circles()}
    plan: list[tuple[OmMailCircle, OmMailDelivery, Any]] = []
    all_views: list[dict[str, Any]] | None = None
    for c in circles:
        if c.circle_id == ALL_CIRCLES:  # the management e-mail: every circle on one page
            if not known:
                db.add(OmMailDelivery(run_id=run.id, circle_id=c.circle_id, subject="—", status="SKIPPED", error="No circles in the active data", created_at=now_utc()))
                run.skipped += 1
                continue
            all_views = all_views or _all_views(db, ctx, store)
            html, txt = render_all(all_views)  # the logo as cid:, attached below
            subject = _all_subject(c.subject, all_views)
        elif c.circle_id not in known:
            db.add(OmMailDelivery(run_id=run.id, circle_id=c.circle_id, subject="—", status="SKIPPED", error="Circle not in the active data", created_at=now_utc()))
            run.skipped += 1
            continue
        else:
            view = circle_view(ctx, c.circle_id, frt_on_portal(store, c.circle_id, db), c.remarks)
            html, txt = render(view)
            subject = render_subject(c.subject or s.subject_template, view)
        subject = with_time(subject)
        to, cc = ([test_to], []) if test_to else recipients(c, s)
        if test_to:
            subject = f"[TEST] {subject}"[:250]
        d = OmMailDelivery(run_id=run.id, circle_id=c.circle_id, to_emails=json.dumps(to), cc_emails=json.dumps(cc), subject=subject, status="PENDING",
                           size_bytes=len(html.encode()), html_sha256=hashlib.sha256(html.encode()).hexdigest(), created_at=now_utc())
        if not to:
            d.status, d.error = "SKIPPED", "No To address"
            run.skipped += 1
        elif len(to) + len(cc) > MAX_RECIPIENTS:
            d.status, d.error = "SKIPPED", f"More than {MAX_RECIPIENTS} recipients"
            run.skipped += 1
        db.add(d)
        if d.status == "PENDING":
            plan.append((c, d, (to, cc, subject, txt, html)))
    db.commit()
    if not plan:
        return _finish(db, run)
    try:
        with SmtpSession() as smtp:
            for _row, d, (to, cc, subject, txt, html) in plan:
                d.status = "SENDING"
                db.commit()
                msg = build_message(to, subject, txt, html)
                if cc:
                    msg["Cc"] = ", ".join(cc)
                attach_logo(msg)  # every page shows the Pratap logo (inline image, cid:om-logo)
                for attempt in (1, 2):
                    d.attempts = attempt
                    try:
                        smtp.send(msg)
                        d.status, d.sent_at, d.error = "SENT", now_utc(), None
                        run.sent += 1
                        break
                    except MailError as exc:
                        d.error = str(exc)[:300]
                        if attempt == 1:
                            time.sleep(RETRY_PAUSE_S)
                else:
                    d.status = "FAILED"
                    run.failed += 1
                db.commit()
    except MailError as exc:  # no connection at all: every pending delivery fails, nothing half-sent
        for _c, d, _p in plan:
            if d.status in ("PENDING", "SENDING"):
                d.status, d.error = "FAILED", str(exc)[:300]
                run.failed += 1
        db.commit()
        return _finish(db, run, str(exc))
    return _finish(db, run)


def _mark_unknown(db: Session) -> None:
    """Deliveries left SENDING by a stopped process: UNKNOWN (the server may have sent them) – never re-sent."""
    cut = now_utc() - STALE_SENDING
    for d in db.scalars(select(OmMailDelivery).where(OmMailDelivery.status == "SENDING")):
        if (utc(d.created_at) or cut) < cut:
            d.status, d.error = "UNKNOWN", "Stopped while sending – check the mailbox before sending again"
    db.commit()


def run_due(db: Session, now: dt.datetime | None = None) -> int | None:
    """The scheduler tick: send the due slot, if any. Returns the run id (None = nothing due / switched off)."""
    if not get_settings().om_daily_emails_enabled:
        return None
    now = now or now_utc()
    s = settings_row(db)
    _mark_unknown(db)
    due = utc(s.next_run_at)
    if not s.enabled or due is None or due > now:
        return None
    run = OmMailRun(slot_key=f"sched:{due.isoformat()}", kind="SCHEDULED", status="RUNNING", triggered_by="Schedule", started_at=now)
    db.add(run)
    s.next_run_at = next_slot(jdict(s.schedule), now)
    s.last_run_at = now
    try:
        db.commit()
    except IntegrityError:  # another process claimed this slot
        db.rollback()
        return None
    if now - due > MISSED_GRACE or not in_window(s, now):
        run.status, run.finished_at = "SKIPPED", now_utc()
        run.message = "Missed (the server was not running at the planned time)" if now - due > MISSED_GRACE else "Outside the sending window"
        s.last_status = "SKIPPED"
        db.commit()
        return run.id
    circles = list(db.scalars(select(OmMailCircle).where(OmMailCircle.enabled.is_(True))))
    run = deliver(db, run, circles)
    s.last_status = run.status
    db.commit()
    return run.id


def send_now(db: Session, by: str, circle_id: str | None = None) -> OmMailRun:
    """An admin's explicit "Send now": the enabled circles (or one enabled circle) right away. The All Circles e-mail
    only when asked for by its id ("all") – never with the circles."""
    q = select(OmMailCircle).where(OmMailCircle.enabled.is_(True))
    q = q.where(OmMailCircle.circle_id == circle_id) if circle_id else q.where(OmMailCircle.circle_id != ALL_CIRCLES)
    circles = list(db.scalars(q))
    if not circles:
        if circle_id == ALL_CIRCLES:
            raise OmMailError(409, "The All Circles mail is off – switch it on and save first")
        raise OmMailError(409, "No enabled circle to send to – switch a circle on first")
    run = OmMailRun(slot_key=f"manual:{now_utc().isoformat()}:{circle_id or 'all'}", kind="MANUAL", status="RUNNING", triggered_by=by[:120], started_at=now_utc())
    db.add(run)
    db.commit()
    return deliver(db, run, circles)


def send_test(db: Session, by: str, to: str, circle_id: str) -> OmMailRun:
    """One circle's e-mail to the admin's own address only ("[TEST]" subject)."""
    c = all_row(db) if circle_id == ALL_CIRCLES else db.scalars(select(OmMailCircle).where(OmMailCircle.circle_id == circle_id)).first()
    if c is None:
        raise OmMailError(404, "Circle not found")
    addr = valid_address(to)
    if addr is None:
        raise OmMailError(422, "Your account has no valid e-mail address for the test mail")
    run = OmMailRun(slot_key=f"test:{now_utc().isoformat()}:{circle_id}", kind="TEST", status="RUNNING", triggered_by=by[:120], started_at=now_utc())
    db.add(run)
    db.commit()
    return deliver(db, run, [c], test_to=addr)


def tiles(db: Session) -> dict[str, Any]:
    """Next send · sent today · sent / failed in the last 7 days (scheduled and manual e-mails, not tests)."""
    s = settings_row(db)
    tz = zone(get_settings().mail_timezone)
    today = dt.datetime.combine(now_utc().astimezone(tz).date(), dt.time(), tz).astimezone(dt.UTC)
    week = now_utc() - dt.timedelta(days=7)
    real = select(OmMailRun.id).where(OmMailRun.kind != "TEST")

    def count(status: str, since: dt.datetime) -> int:
        return db.scalar(select(func.count()).select_from(OmMailDelivery).where(OmMailDelivery.run_id.in_(real), OmMailDelivery.status == status,
                                                                                 OmMailDelivery.created_at >= since)) or 0

    return {
        "nextRunAt": utc(s.next_run_at).isoformat() if s.enabled and s.next_run_at else None,
        "sentToday": count("SENT", today), "sent7d": count("SENT", week), "failed7d": count("FAILED", week) + count("UNKNOWN", week),
        "switchOn": get_settings().om_daily_emails_enabled,
    }
