"""GP Timeline (read only): everything that happened to ONE GP of a GP-wise task ticket, oldest first – who (name and
role), when, what (the category reported, the review step, the Non-Doable step), the remark and the proof documents.

  generated      the ticket was generated (by whom, the Area Manager, the week)
  filled         a Daily Achievement line of the GP: FRT / FE / AM (the submitter's role on the ticket)
  review         FE verify / return, AM approve / return, SME forward / return, COH letter / AMC / return, edits
  nd             a Non-Doable step (proposed, E1, E2, forwarded, approved …)
  now            where the GP waits now (app.tickets.review.stage_of) – the last entry

A review step and a Non-Doable step write their own progress line (same user and time): that line's documents are the
step's proof and the line is not shown twice. The caller checks that the user may see the GP (as the GP detail).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NdEvent, Ticket, TicketGpReview, TicketProgress, TicketProgressFile, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp
from .service import iso
from .task import CATEGORIES, file_json

RETURNS = {"FE_RETURN", "AM_RETURN", "SME_RETURN", "COH_RETURN", "RETURNED_FE", "RETURNED_AM", "RETURNED_SME"}
ROLE_NAME = {"FRT": "FRT", "FE": "FE", "AM": "Area Manager", "SME": "SME", "COH": "COH", "ADMIN": "Admin", "MGG": "Corporate Team – MGG"}


def _utc(v: dt.datetime | None) -> dt.datetime | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).replace(microsecond=0)


def build(db: Session, t: Ticket, g: TicketTaskGp) -> dict[str, Any]:
    from . import nondoable as nd
    from .monitor import WAIT_LABEL
    from .review import ACTION_LABEL, stage_label, stage_of

    k = db.get(TicketTask, t.id)
    events: list[dict[str, Any]] = [{
        "at": iso(t.created_at), "kind": "generated", "label": "Ticket generated", "by": t.created_by_name, "role": "ADMIN",
        "remark": None, "detail": f"{t.code}" + (f" · Area Manager {k.am_name}" if k and k.am_name else "") + (f" · {k.week_code.replace('W-', 'Week ')}" if k else ""), "files": [],
    }]

    # the GP's progress lines and their documents
    lines = list(db.execute(
        select(TicketProgressLine, TicketProgress).join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id).where(TicketProgressLine.task_gp_id == g.id)
    ))
    files_of: dict[int, list[dict[str, Any]]] = {}
    for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.task_gp_id == g.id).order_by(TicketProgressFile.id)):
        files_of.setdefault(f.progress_line_id, []).append(file_json(f, iso))
    line_at = {(p.submitted_by_id, _utc(p.submitted_at)): ln for ln, p in lines}

    reviews = list(db.scalars(select(TicketGpReview).where(TicketGpReview.task_gp_id == g.id)))
    nd_events = list(db.scalars(select(NdEvent).where(NdEvent.task_gp_id == g.id)))
    used: set[int] = set()  # progress lines that belong to a review / Non-Doable step

    for x in reviews:
        ln = line_at.get((x.actor_id, _utc(x.at)))
        if ln is not None:
            used.add(ln.id)
        detail = []
        if x.category:
            detail.append(CATEGORIES.get(x.category, x.category))
        if x.on_date:
            detail.append(f"date {x.on_date.strftime('%d %b %Y')}")
        events.append({
            "at": iso(x.at), "kind": "return" if x.action in RETURNS else "review", "label": ACTION_LABEL.get(x.action, x.action.replace("_", " ").title()),
            "by": x.actor_name, "role": x.role, "remark": x.remark, "detail": " · ".join(detail) or None, "files": files_of.get(ln.id, []) if ln is not None else [],
        })
    for e in nd_events:
        ln = line_at.get((e.actor_id, _utc(e.at)))
        if ln is not None and e.action in getattr(nd, "PROGRESS_STEPS", ("MGG_APPROVE", "MGG_REJECT", "WITHDRAW", "FRT_WITHDRAW")):
            used.add(ln.id)
        text = " · ".join(v for v in (e.reason, e.recommendation, e.decision) if v) or None
        events.append({
            "at": iso(e.at), "kind": "return" if e.to_status in RETURNS else "nd",
            "label": f"Non-Doable: {nd.ACTION_LABEL.get(e.action, e.action.replace('_', ' ').lower())}",
            "by": e.actor_name, "role": e.role, "remark": e.remark, "detail": (nd.STATUS_LABEL.get(e.to_status, e.to_status) + (f" · {text}" if text else "")), "files": [],
        })

    # the Daily Achievement lines (not a review / Non-Doable step): who filled it, in which role
    roles: dict[int, set[str]] = {}
    for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id.is_not(None))):
        roles.setdefault(r.user_id, set()).add(r.role)
    for ln, p in lines:
        if ln.id in used:
            continue
        have = roles.get(p.submitted_by_id or -1, set())
        role = next((x for x in ("FRT", "FE", "AM") if x in have), "AM" if p.submitted_by_id is not None and p.submitted_by_id == t.assignee_id else "ADMIN")
        cat = CATEGORIES.get(ln.category, ln.category) if ln.category else None
        events.append({
            "at": iso(p.submitted_at), "kind": "filled", "label": f"Filled by {ROLE_NAME.get(role, role)}" + (f" – {cat}" if cat else ""),
            "by": p.submitted_by_name, "role": role, "remark": ln.remark,
            "detail": (f"achieved {ln.achieved_today} today · {ln.cumulative} of {g.target}" if ln.achieved_today else None), "files": files_of.get(ln.id, []),
        })

    events.sort(key=lambda e: e["at"] or "")
    stage = stage_of(g)
    wait = WAIT_LABEL.get(stage, "")
    return {
        "gpId": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "ticket": t.code,
        "events": events,
        "now": {"label": stage_label(stage), "waiting": "" if wait == "done" else wait, "done": wait == "done"},
    }
