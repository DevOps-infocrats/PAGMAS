"""COH (Circle Operations Head) on User Tickets: the Letter Submitted / AMC Converted GP lists and Excel, and closing a
GP-wise task ticket.

Lists      the GPs of the signed-in user's tickets on which they are COH (live tickets only), limited to the GPs the
           SME forwarded to them (task.reviewer_view – the same GPs they see in the ticket): Letter Submitted = a letter
           date was recorded (also when the AMC conversion followed), AMC Converted = an AMC date was recorded. Target
           Date = the GP's Planned Date of the AMC plan (snapshot at ticket creation); a GP without one (added later)
           shows the ticket week's last day, flagged.
Closing    a COH of the ticket may close it only when EVERY GP of the ticket is finished: letter submitted / AMC
           converted, closed Non-Doable, or already achieved in the master data. Anything still with the FE / Area
           Manager / SME keeps the ticket open (the admin's own closing rules are unchanged – service.close).
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ticket, TicketRecipient, TicketTask, TicketTaskGp
from ..security.deps import CurrentUser

FINISHED_REVIEWS = ("LETTER_SUBMITTED", "AMC_CONVERTED", "ND_APPROVED")
KINDS = {"letter": "Letter Submitted", "amc": "AMC Converted"}


class CohError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def is_coh(db: Session, t: Ticket, user: CurrentUser) -> bool:
    """A COH recipient of this ticket with this account (admins act through the admin page)."""
    return db.scalar(select(TicketRecipient.id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id, TicketRecipient.role == "COH").limit(1)) is not None


def close_block(db: Session, t: Ticket) -> str | None:
    """Why the COH cannot close this task ticket yet (None = every GP is finished)."""
    from . import review as rv
    from .task import cumulative

    if t.status == "CLOSED":
        return "The ticket is already closed"
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id)))
    open_ = [g for g in gps if g.review not in FINISHED_REVIEWS and cumulative(g) < g.target]
    if not open_:
        return None
    where: dict[str, int] = {}
    for g in open_:
        label = rv.stage_label(rv.stage_of(g))
        where[label] = where.get(label, 0) + 1
    detail = ", ".join(f"{n} {label}" for label, n in sorted(where.items(), key=lambda x: -x[1]))
    return f"{len(open_)} of {len(gps)} GP{'s' if len(gps) != 1 else ''} not finished yet ({detail}) – the ticket can be closed once every GP is Letter Submitted / AMC Converted / closed Non-Doable"


def can_close(db: Session, t: Ticket, user: CurrentUser) -> tuple[bool, str | None]:
    """(may close now, reason shown to a COH when not) – (False, None) for anybody who is not a COH of a task ticket."""
    if user.is_admin or db.get(TicketTask, t.id) is None or not is_coh(db, t, user):
        return False, None
    why = close_block(db, t)
    return why is None, why


def close(db: Session, t: Ticket, user: CurrentUser, comment: str | None) -> Ticket:
    """The COH closes a finished GP-wise task ticket (same effects as the admin's closing: status, history, notices)."""
    from ..models import TicketSubmission
    from .service import _event, _members, _move, _notify, now

    if db.get(TicketTask, t.id) is None:
        raise CohError(422, "Only a GP-wise task ticket is closed by the COH")
    if not is_coh(db, t, user) or user.is_admin:
        raise CohError(403, "Only the COH of this ticket can close it here")
    why = close_block(db, t)
    if why is not None:
        raise CohError(409, why)
    note = (comment or "").strip()[:5000] or None
    last = db.scalars(select(TicketSubmission).where(TicketSubmission.ticket_id == t.id).order_by(TicketSubmission.version.desc()).limit(1)).first()
    frm = _move(db, t, ("OPEN", "IN_PROGRESS", "PENDING_REVIEW", "CHANGES_REQUESTED"), "CLOSED", closed_at=now(), closed_by_id=user.id, closed_by_name=user.name)
    if last is not None and last.review == "PENDING":
        last.review, last.reviewed_by_id, last.reviewed_by_name, last.reviewed_at, last.review_comment = "ACCEPTED", user.id, user.name, now(), note
    _event(db, t, user, "CLOSED", frm, "CLOSED", "Closed by the COH – every GP finished" +(f" · {note}" if note else ""))
    _notify(db, _members(db, t) - {user.id}, t, "CLOSED", f"{t.code} closed", f"{user.name} (COH) closed the ticket – every GP is finished: {t.subject}")
    db.commit()
    db.refresh(t)
    return t


def gp_lists(db: Session, user: CurrentUser) -> dict[str, Any]:
    """Letter Submitted and AMC Converted GPs of the user's COH tickets (each GP row once per ticket)."""
    from .service import live
    from .task import reviewer_view

    tickets = list(
        db.scalars(
            select(Ticket)
            .join(TicketRecipient, TicketRecipient.ticket_id == Ticket.id)
            .where(TicketRecipient.user_id == user.id, TicketRecipient.role == "COH", live())
            .distinct()
            .order_by(Ticket.id.desc())
        )
    )
    letter: list[dict[str, Any]] = []
    amc: list[dict[str, Any]] = []
    for t in tickets:
        task = db.get(TicketTask, t.id)
        if task is None:
            continue
        view = reviewer_view(db, t, user)
        for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id).order_by(TicketTaskGp.sort)):
            if view is not None and not view.owns(g):
                continue
            if g.letter_date is None and g.amc_on is None:
                continue
            row = {
                "ticketId": t.id, "ticket": t.code or f"TKT-{t.id:06d}", "ticketStatus": t.status, "week": task.week_code,
                "gpCode": g.gp_code, "gpName": g.gp_name, "circle": g.circle, "district": g.district, "block": g.block,
                "areaManager": task.am_name, "fieldEngineer": g.fe_name,
                "targetDate": (g.planned_date or task.week_end).isoformat(), "targetFromWeek": g.planned_date is None,
                "letterDate": g.letter_date.isoformat() if g.letter_date else None, "amcDate": g.amc_on.isoformat() if g.amc_on else None,
                "status": g.review,
            }
            if g.letter_date is not None:
                letter.append(row)
            if g.amc_on is not None:
                amc.append(row)
    letter.sort(key=lambda r: (r["letterDate"] or "", r["ticket"], r["gpCode"]), reverse=True)
    amc.sort(key=lambda r: (r["amcDate"] or "", r["ticket"], r["gpCode"]), reverse=True)
    return {"isCoh": bool(tickets), "tickets": len(tickets), "letterSubmitted": len(letter), "amcConverted": len(amc), "letter": letter, "amc": amc}


def workbook(rows: list[dict[str, Any]], kind: str, user_name: str) -> bytes:
    """The list as an Excel sheet (same columns as the page)."""
    import xlsxwriter

    title = KINDS[kind]
    date_col = "Letter Submitted Date" if kind == "letter" else "AMC Converted Date"
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet(title[:31])
    bold = wb.add_format({"bold": True, "font_size": 13})
    head = wb.add_format({"bold": True, "bg_color": "#E8F1FB", "border": 1, "text_wrap": True, "valign": "vcenter"})
    cell = wb.add_format({"border": 1})
    day = wb.add_format({"border": 1, "num_format": "dd-mm-yyyy"})
    ws.write(0, 0, f"{title} GPs", bold)
    ws.write(1, 0, f"COH {user_name} · {len(rows)} GP{'s' if len(rows) != 1 else ''} · generated {dt.datetime.now():%d-%m-%Y %H:%M}")
    cols = ["S.No.", "Ticket", "Week", "GP Code", "GP Name", "Circle", "District", "Block", "Area Manager", "FE Name", "Target Date", date_col]
    if kind == "amc":
        cols.insert(11, "Letter Submitted Date")
    widths = [6, 14, 9, 12, 24, 14, 16, 18, 22, 22, 13, 16, 16]
    for j, h in enumerate(cols):
        ws.write(3, j, h, head)
        ws.set_column(j, j, widths[j] if j < len(widths) else 14)
    for i, r in enumerate(rows, start=4):
        vals: list[Any] = [i - 3, r["ticket"], (r["week"] or "").replace("W-", "Week "), r["gpCode"], r["gpName"], r["circle"], r["district"] or "", r["block"] or "",
                           r["areaManager"] or "", r["fieldEngineer"] or "Not mapped", r["targetDate"]]
        if kind == "amc":
            vals.append(r["letterDate"])
        vals.append(r["letterDate"] if kind == "letter" else r["amcDate"])
        for j, v in enumerate(vals):
            if j >= 10 and v:
                ws.write_datetime(i, j, dt.datetime.fromisoformat(v), day)
            else:
                ws.write(i, j, v if v is not None else "", cell)
    ws.freeze_panes(4, 0)
    ws.autofilter(3, 0, max(3, 3 + len(rows)), len(cols) - 1)
    wb.close()
    return buf.getvalue()
