"""Optional e-mail of a generated ticket ("Send Email Notification" / Retry), through the existing SMTP settings.

* Only the recipients selected for that ticket receive it – one message each; nobody else is copied.
* The Area Manager of a GP-wise task gets their own assignment workbook attached; every Field Engineer gets a workbook
  with only the GPs mapped to them; CBH / SME / other users never get a workbook.
* Sending runs after the ticket is saved (background task): a mail problem never undoes a ticket. The result is kept
  per recipient (SENT / FAILED with a safe reason – never a password or server reply) and can be retried by an admin.
* A recipient without a dashboard account is told so: the e-mail gives them no access to the dashboard.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Ticket, TicketProgress, TicketProgressFile, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp, User
from .directory import ROLE_LABEL

log = logging.getLogger(__name__)
XLSX = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def _see_gps():
    from ..mail import layout as L

    return L.Section("Target GPs", lines=["The GP list is not included in this e-mail. To see which GPs are your target GPs, sign in with VIEW DASHBOARD below and open the ticket on the dashboard."])


def _ticket_email(db, t: Ticket, r: TicketRecipient, task, tj, scope, shared: tuple[str, str] | None):
    """The content of a ticket e-mail for this recipient (role-specific: an FE sees only their GPs – `tj` is already
    scoped – the Area Manager / CBH / SME the whole task with the FE-wise split)."""
    from ..mail import layout as L
    from .service import PRIORITY_LABEL, STATUS_LABEL

    role = ROLE_LABEL.get(r.role, r.role)
    works = bool(r.can_work)
    if shared:
        title, badge, tone = "Ticket status shared with you", "For Information", "info"
        intro = [f"Area Manager {shared[0]} has shared the latest status of this ticket with you ({role})."]
    elif works:
        title, badge, tone = ("New GP-wise task assigned" if tj is not None else "New ticket assigned"), "Action Required", "warning"
        intro = [f"A ticket has been assigned to you on PAGMAS ({role})."]
    else:
        title, badge, tone = "Ticket shared with you", "For Information", "info"
        intro = [f"A ticket has been {'shared with' if r.user_id else 'sent to'} you on PAGMAS ({role})."]
    summary = [
        ("Ticket ID", t.code or "—"), ("Subject", t.subject), ("Priority", PRIORITY_LABEL.get(t.priority, t.priority)), ("Status", STATUS_LABEL.get(t.status, t.status)),
        ("Circle", t.circle or "—"), ("Assigned by", t.created_by_name), ("Your role", role),
    ]
    kpis: list[L.Kpi] = []
    sections: list[L.Section] = []
    action = None
    if tj is not None:
        T = tj["totals"]
        who = f"Field Engineer {r.name} (Area Manager {task.am_name})" if scope is not None else f"Area Manager {task.am_name}"
        summary += [("Area Manager", task.am_name), ("Week", f"Week {task.week_code[2:]} ({task.week_start:%d %b} – {task.week_end:%d %b %Y})")]
        if scope is not None:
            summary.append(("Field Engineer", r.name))
        intro.append(f"GP-wise weekly task – {who}, Week {task.week_code[2:]}. The figures below are {'your GPs only' if scope is not None else 'all GPs of the task'}.")
        kpis = [
            L.Kpi("Assigned GPs", f"{T['gps']:,}", "info", f"{T['weekGps']} this week · {T['pendingGps']} pending"),
            L.Kpi("Weekly target", f"{T['target']:,}", "neutral"),
            L.Kpi("Achieved", f"{T['achieved']:,}", "good", f"{T['pct']}%" if T["pct"] is not None else None),
            L.Kpi("Remaining gap", f"{T['gap']:,}", "critical" if T["gap"] else "good"),
        ]
        if tj["fes"]:
            sections.append(L.Section("Field Engineer-wise", L.Table(
                ["Field Engineer", "GPs", "Weekly Target", "Achieved", "Remaining Gap", "Done", "Pending"],
                [[f["name"] or "FE not mapped", f["gps"], f["target"], f["achieved"], f["gap"], f["doneGps"], f["pendingGps"]] for f in tj["fes"]],
                {1, 2, 3, 4, 5, 6},
            )))
        sections.append(_see_gps())
        if works and not shared:
            action = L.Action(
                "Update every GP in the daily progress: choose its status, add remarks and attach the proof documents.",
                who=f"{role} {r.name}", stage=STATUS_LABEL.get(t.status, t.status), due=f"{task.week_end:%d %b %Y} (end of Week {task.week_code[2:]})",
                steps=["Sign in with the button below and open the ticket in Ticket Management → User Tickets.", "Statuses: Rectification Done · Ready for Letter Submitted · Revisit Required · Non-Doable – Proposed · Letter Submission Done."],
            )
    elif works and not shared:
        action = L.Action("Do the work described below and submit it with your documents for review.", who=f"{role} {r.name}", stage=STATUS_LABEL.get(t.status, t.status))
    sections.append(L.Section("Description", lines=[x for x in (t.description or "").splitlines() if x.strip()] or ["—"]))
    notes = []
    if shared:
        notes.append("The latest GP-wise sheet (status, remarks and proof documents of every GP) is attached.")
    elif tj is not None and r.attach_workbook:
        notes.append("Your GP-wise assignment workbook is attached.")
    notes.append(f"Open ticket {t.code} in Ticket Management → User Tickets after signing in." if r.user_id else "This address has no dashboard account – this e-mail is for information only.")
    return L.Email(
        title=title, badge=badge, badge_tone=tone, greeting=r.name, intro=intro, reference=t.code, date=f"{(t.created_at or now_utc()):%d %b %Y}", kpis=kpis, summary=summary,
        highlight=(f"Remark from {shared[0]}", shared[1]) if shared else None, sections=sections, action=action, notes=notes,
    )


def now_utc():
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC)


def _message(db, t: Ticket, r: TicketRecipient, shared: tuple[str, str] | None = None):
    from ..mail import layout as L
    from . import task as tasks

    task = db.get(TicketTask, t.id)
    scope = tasks.FeScope(r.name, r.fe_mail) if r.role == "FE" else None
    tj = tasks.task_json(db, t, scope) if task is not None else None  # the same figures the dashboard shows this person
    subject = f"[{t.code}] {'Shared by ' + shared[0] + ': ' if shared else ''}{t.subject}"[:250]
    msg = L.message(r.email, subject, _ticket_email(db, t, r, task, tj, scope, shared))
    if task is not None and shared is not None:  # the latest GP sheet of the whole task (progress, remarks, proof names)
        msg.add_attachment(tasks.workbook(db, t, task, original=False), maintype=XLSX[0], subtype=XLSX[1], filename=tasks.file_name(task, False))
    elif task is not None and r.attach_workbook:
        if scope is not None:  # only the FE's own GPs
            data = tasks.workbook(db, t, task, original=True, scope=scope)
        else:
            path = tasks.assignment_path(t, task)
            data = path.read_bytes() if path is not None and path.is_file() else tasks.workbook(db, t, task, original=True)
        msg.add_attachment(data, maintype=XLSX[0], subtype=XLSX[1], filename=tasks.file_name(task, True, scope))
    return msg


def deliver(recipient_ids: list[int], session_factory=SessionLocal, shared: tuple[str, str] | None = None) -> dict[str, int]:
    """Send the queued e-mails (status PENDING) of these recipients over one SMTP connection. `shared` = (Area Manager,
    remark): the Area Manager shared the ticket – the latest GP sheet and the remark go to them."""
    from ..mail import smtp
    from .service import now

    sent = failed = 0
    if not recipient_ids:
        return {"sent": 0, "failed": 0}
    with session_factory() as db:
        rows = list(db.scalars(select(TicketRecipient).where(TicketRecipient.id.in_(recipient_ids), TicketRecipient.email_status == "PENDING").order_by(TicketRecipient.id)))
        if not rows:
            return {"sent": 0, "failed": 0}

        def fail(r: TicketRecipient, reason: str) -> None:
            nonlocal failed
            r.email_status, r.email_error, r.emailed_at = "FAILED", reason[:300], now()
            failed += 1

        try:
            session = smtp.SmtpSession()
            session.__enter__()
        except smtp.MailError as exc:
            for r in rows:
                fail(r, str(exc))
            db.commit()
            log.warning("Ticket e-mails not sent: %s", exc)
            return {"sent": 0, "failed": failed}
        try:
            for r in rows:
                t = db.get(Ticket, r.ticket_id)
                if t is None or t.deleted_at is not None:
                    continue
                try:
                    session.send(_message(db, t, r, shared))
                except smtp.MailError as exc:
                    fail(r, str(exc))
                except Exception as exc:  # noqa: BLE001 - one bad message must not stop the others
                    fail(r, f"The e-mail could not be built ({type(exc).__name__})")
                else:
                    r.email_status, r.email_error, r.emailed_at = "SENT", None, now()
                    sent += 1
                db.commit()
        finally:
            session.__exit__(None, None, None)
    log.info("Ticket e-mails: %s sent, %s failed", sent, failed)
    return {"sent": sent, "failed": failed}


def queue(db, ticket_ids: list[int], recipient_id: int | None = None) -> list[int]:
    """Mark recipients' e-mails as waiting (PENDING) and return their ids for `deliver`."""
    from .service import now

    q = select(TicketRecipient).where(TicketRecipient.ticket_id.in_(ticket_ids))
    if recipient_id is not None:
        q = q.where(TicketRecipient.id == recipient_id)
    rows = list(db.scalars(q))
    for r in rows:
        r.email_status, r.email_error, r.emailed_at = "PENDING", None, now()
    db.commit()
    return [r.id for r in rows]


def progress_mail(progress_id: int, session_factory=SessionLocal) -> int:
    """An FE submitted daily progress: e-mail it to the Area Manager of the ticket (AM recipients; a ticket without
    them: its assignee). Lists every GP line of the submission with the category, remark, proof count, GP corrections
    and added GPs. Runs after the save (background task); a mail problem only gets logged. Returns the e-mails sent."""
    from ..mail import smtp
    from . import task as tasks

    with session_factory() as db:
        sub = db.get(TicketProgress, progress_id)
        t = db.get(Ticket, sub.ticket_id) if sub is not None else None
        task = db.get(TicketTask, t.id) if t is not None else None
        if sub is None or t is None or t.deleted_at is not None or task is None:
            return 0
        to = {r.email.lower(): r.name for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "AM"))}
        if not to and t.assignee_id:
            u = db.get(User, t.assignee_id)
            if u is not None and u.id != sub.submitted_by_id:
                to[u.email.lower()] = u.name
        submitter = db.get(User, sub.submitted_by_id) if sub.submitted_by_id else None
        to.pop((submitter.email.lower() if submitter else ""), None)
        if not to:
            return 0
        lines = list(db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id == sub.id).order_by(TicketProgressLine.id)))
        proofs: dict[int, int] = {}
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.progress_line_id.in_([ln.id for ln in lines]))) if lines else []:
            proofs[f.progress_line_id] = proofs.get(f.progress_line_id, 0) + 1
        from ..models import NdCase, NdEvent

        nd_refs = dict(db.execute(select(NdEvent.task_gp_id, NdCase.ref).join(NdCase, NdCase.id == NdEvent.case_id).where(NdEvent.ticket_id == t.id, NdEvent.action == "PROPOSED", NdEvent.at == sub.submitted_at)).all())
        from ..mail import layout as L

        intro = f"FE {sub.submitted_by_name} submitted daily progress on ticket {t.code} ({t.subject}) – Week {task.week_code[2:]}, {len(lines)} GP line{'s' if len(lines) != 1 else ''}."
        if nd_refs:
            intro += f" {len(nd_refs)} GP{'s are' if len(nd_refs) != 1 else ' is'} proposed Non-Doable ({', '.join(sorted(nd_refs.values()))})."
        counts: dict[str, int] = {}
        for ln in lines:
            lbl = tasks.category_label(ln.category)
            if lbl:
                counts[lbl] = counts.get(lbl, 0) + 1

        def email_for(name: str) -> L.Email:
            return L.Email(
                title="FE daily progress submitted", badge="Action Required", badge_tone="warning", greeting=name, intro=[intro], reference=t.code,
                date=f"{(sub.submitted_at or now_utc()):%d %b %Y %H:%M} UTC",
                kpis=[L.Kpi("GP lines", f"{len(lines)}", "info"), L.Kpi("Proof documents", f"{sum(proofs.values())}", "neutral"), L.Kpi("Proposed Non-Doable", f"{len(nd_refs)}", "warning" if nd_refs else "neutral")],
                summary=[("Ticket", f"{t.code} – {t.subject}"), ("Area Manager", task.am_name), ("Field Engineer", sub.submitted_by_name), ("Week", f"Week {task.week_code[2:]} ({task.week_start:%d %b} – {task.week_end:%d %b %Y})")]
                + [(f"Status: {k}", str(v)) for k, v in counts.items()],
                highlight=("Note from the FE", sub.note) if sub.note else None,
                sections=[_see_gps()],
                action=L.Action("Review the GPs: approve them for the SME or return them to the FE with the reason.", who=f"Area Manager {task.am_name}", stage="AM review"),
                notes=[f"Open ticket {t.code} in Ticket Management after signing in."],
            )
        subject = (f"[{t.code}] FE daily progress: {sub.submitted_by_name}" + (" · Non-Doable proposed" if nd_refs else ""))[:250]
        sent = 0
        try:
            with smtp.SmtpSession() as session:
                for addr, name in to.items():
                    try:
                        session.send(L.message(addr, subject, email_for(name)))
                        sent += 1
                    except smtp.MailError as exc:
                        log.warning("FE progress e-mail to the Area Manager not sent: %s", exc)
        except smtp.MailError as exc:
            log.warning("FE progress e-mails not sent: %s", exc)
        return sent

def review_mail(recipient_ids: list[int], gp_ids: list[int], action: str, by: str, remark: str | None, session_factory=SessionLocal) -> dict[str, int]:
    """The Area Manager approved GPs for the SME (or the SME forwarded them to the COH): the chosen people get the GP
    list with the FE's status / remark, proof count and the reviewer's remark. Result kept per recipient like the
    ticket e-mail (SENT / FAILED, retry by an admin); runs after the save (background task)."""
    from ..mail import smtp
    from . import review, task as tasks
    from .service import now

    sent = failed = 0
    if not recipient_ids:
        return {"sent": 0, "failed": 0}
    with session_factory() as db:
        rows = list(db.scalars(select(TicketRecipient).where(TicketRecipient.id.in_(recipient_ids), TicketRecipient.email_status == "PENDING").order_by(TicketRecipient.id)))
        if not rows:
            return {"sent": 0, "failed": 0}
        t = db.get(Ticket, rows[0].ticket_id)
        task = db.get(TicketTask, t.id) if t is not None else None
        gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == rows[0].ticket_id, TicketTaskGp.id.in_(gp_ids)).order_by(TicketTaskGp.sort)))
        proofs: dict[int, int] = {}
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.task_gp_id.in_(gp_ids))) if gp_ids else []:
            proofs[f.task_gp_id] = proofs.get(f.task_gp_id, 0) + 1
        step = review.STEPS[action].label
        what = "approved these GPs for your review (SME)" if action == "AM_APPROVE" else "forwarded these GPs to you for the letter submission / AMC conversion (COH)"
        intro = f"{by} {what} – ticket {t.code} ({t.subject})" + (f", Area Manager {task.am_name}, Week {task.week_code[2:]}" if task else "") + "."

        def fail(r: TicketRecipient, reason: str) -> None:
            nonlocal failed
            r.email_status, r.email_error, r.emailed_at = "FAILED", reason[:300], now()
            failed += 1

        try:
            session = smtp.SmtpSession()
            session.__enter__()
        except smtp.MailError as exc:
            for r in rows:
                fail(r, str(exc))
            db.commit()
            log.warning("Review e-mails not sent: %s", exc)
            return {"sent": 0, "failed": failed}
        try:
            from ..mail import layout as L

            nxt = {"AM_APPROVE": "SME", "SME_FORWARD": "COH"}.get(action)
            todo = {
                "SME": "Review these GPs (photos, remarks, history) and forward them to the COH, or return them to the Area Manager.",
                "COH": "Arrange the letter submission and the AMC conversion of these GPs, and record each step in the ticket.",
            }
            cats: dict[str, int] = {}
            for g in gps:
                lbl = tasks.category_label(g.gp_category) or "—"
                cats[lbl] = cats.get(lbl, 0) + 1
            for r in rows:
                email = L.Email(
                    title=step, badge="Action Required" if nxt else "For Information", badge_tone="warning" if nxt else "info", greeting=r.name, intro=[intro], reference=t.code, date=f"{now():%d %b %Y}",
                    kpis=[L.Kpi("GPs", f"{len(gps)}", "info"), L.Kpi("Proof documents", f"{sum(proofs.values())}", "neutral")],
                    summary=[("Ticket", f"{t.code} – {t.subject}"), ("Circle", t.circle or "—")] + ([("Area Manager", task.am_name), ("Week", f"Week {task.week_code[2:]}")] if task else [])
                    + [("Reviewed by", by), ("Your role", ROLE_LABEL.get(r.role, r.role))] + [(f"Status: {k}", str(v)) for k, v in cats.items()],
                    highlight=(f"Remark – {step}", remark) if remark else None,
                    sections=[_see_gps()],
                    action=L.Action(todo[nxt], who=f"{nxt} {r.name}", stage=step) if nxt in todo else None,
                    notes=[f"Open ticket {t.code} in Ticket Management after signing in." if r.user_id else "This address has no dashboard account – this e-mail is for information only."],
                )
                try:
                    session.send(L.message(r.email, f"[{t.code}] {step}: {len(gps)} GP{'s' if len(gps) != 1 else ''}"[:250], email))
                except smtp.MailError as exc:
                    fail(r, str(exc))
                except Exception as exc:  # noqa: BLE001 - one bad message must not stop the others
                    fail(r, f"The e-mail could not be built ({type(exc).__name__})")
                else:
                    r.email_status, r.email_error, r.emailed_at = "SENT", None, now()
                    sent += 1
                db.commit()
        finally:
            session.__exit__(None, None, None)
    return {"sent": sent, "failed": failed}

def nd_mail(case_id: int, event_id: int, to: list[tuple[str, str]], recipient_ids: list[int] | None = None, session_factory=SessionLocal) -> int:
    """A step of a Non-Doable case (app.tickets.nondoable): one e-mail per address (e-mail, name) of the people
    concerned – the case, GP, new status, who did what, the remarks / reason and the link to the case. Runs after the
    save (background task); a mail problem only gets logged. `recipient_ids` = the SME / COH chosen for the step: their
    delivery is kept per recipient (SENT / FAILED) like the GP review e-mail. Returns the e-mails sent."""
    from ..mail import smtp
    from ..models import NdCase, NdEvent
    from . import nondoable as nd
    from .service import now

    if not to:
        return 0
    with session_factory() as db:
        chosen = {r.email.lower(): r for r in db.scalars(select(TicketRecipient).where(TicketRecipient.id.in_(recipient_ids or []), TicketRecipient.email_status == "PENDING"))}

        def mark(addr: str, error: str | None) -> None:
            r = chosen.get(addr.lower())
            if r is not None:
                r.email_status, r.email_error, r.emailed_at = ("FAILED" if error else "SENT"), (error or None) and error[:300], now()

        c, ev = db.get(NdCase, case_id), db.get(NdEvent, event_id)
        t = db.get(Ticket, c.ticket_id) if c is not None else None
        g = db.get(TicketTaskGp, c.task_gp_id) if c is not None else None
        if c is None or ev is None or t is None or g is None or t.deleted_at is not None:
            return 0
        from ..mail import layout as L

        action = nd.ACTION_LABEL.get(ev.action, ev.action)
        status = nd.STATUS_LABEL[c.status]
        waiting = nd._pending_with(c)
        stage = nd.STAGE_LABEL.get(ev.stage, ev.stage) if ev.stage else None
        summary = [
            ("Case", c.ref), ("Ticket", f"{t.code} – {t.subject}"), ("GP", f"{g.gp_code} – {g.gp_name}"), ("Block / District", f"{g.block or '—'} / {g.district or '—'}"),
            ("Field Engineer", c.fe_name or "—"), ("Action", f"{action} ({nd.ROLE_LABEL.get(ev.role, ev.role)} {ev.actor_name})"),
            *([("Stage", stage)] if stage else []), ("Case status", status),
            *([("Revisit", nd.REVISIT_LABEL[c.revisit_status])] if c.revisit_status else []),
            *([("Pending with", nd.ROLE_LABEL.get(waiting, waiting))] if waiting else []),
        ]
        said = [x for x in (("Recommendation", ev.recommendation), ("Reason", ev.reason), ("Remarks", ev.remark)) if x[1]]
        tone = {"APPROVED": "good", "REJECTED": "critical", "WITHDRAWN": "neutral"}.get(c.status, "warning")
        open_case = c.status in nd.OPEN or c.status == "REJECTED"

        def email_for(name: str) -> L.Email:
            return L.Email(
                title=f"Non-Doable case {c.ref}", badge="Action Required" if open_case else "For Information", badge_tone="warning" if open_case else tone,
                greeting=name, intro=[f"Non-Doable case {c.ref} (GP {g.gp_code}): {action}."], reference=c.ref, date=f"{(ev.at or now()):%d %b %Y}",
                summary=summary, highlight=(" · ".join(k for k, _ in said), "\n".join(v for _, v in said)) if said else None,
                notes=["The verification, evidence and complete history are in the case: sign in and open Ticket Management → Non-Doable Cases."],
            )

        subject = f"[{c.ref}] {status} – GP {g.gp_code}"[:250]
        sent = 0
        try:
            with smtp.SmtpSession() as session:
                for addr, name in to:
                    try:
                        session.send(L.message(addr, subject, email_for(name)))
                        sent += 1
                        mark(addr, None)
                    except smtp.MailError as exc:
                        mark(addr, str(exc))
                        log.warning("Non-Doable e-mail not sent: %s", exc)
        except smtp.MailError as exc:
            for addr, _name in to:
                if addr.lower() in chosen and chosen[addr.lower()].email_status == "PENDING":
                    mark(addr, str(exc))
            log.warning("Non-Doable e-mails not sent: %s", exc)
        db.commit()
        return sent