"""Ticket Report (admin, read only): what was generated for whom in a ticket week, and who did the daily work.

A ticket is generated once a week (TicketTask.week_code, BSNL week Saturday – Friday); the Daily Achievement is
submitted on any day. So the report has two lenses on the chosen week:

  generated   the tickets of that week (not deleted) – per role (AM / FE / FRT / SME / COH): how many tickets have
              that role, how many people, how many GPs are theirs, how many of those are achieved (Done)
  daily       every DAILY submission made on the days of that week (any live ticket – pending work goes on), per
              person and day. A daily submission is a TicketProgress row that is NOT written by a review step
              (TicketGpReview, app.tickets.review.STEPS) or a Non-Doable step that changes the GP (MGG approve /
              reject, withdraw): those write a progress row with the same user and the same time (the same rule
              app.tickets.task uses for the FE's own submission). A Non-Doable proposed in the Daily Achievement is part
              of that submission and counts. The submitter's role on the
              ticket: FRT > FE > AM (recipients with that account), else the ticket's assignee = AM.
  completed   what was finished in the week: GPs that became Done in a daily submission, letters submitted and AMC
              conversions recorded by the COH, Non-Doable cases approved by the Corporate Team – MGG; who and when.

Nothing is written. Dates are local (REPORT_TIMEZONE, as the rest of the ticket pages).
"""

from __future__ import annotations

import datetime as dt
import io
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NdCase, NdEvent, Ticket, TicketGpReview, TicketProgress, TicketProgressLine, TicketRecipient, TicketTask, TicketTaskGp, User
from .monitor import _local_date
from .task import cumulative, fe_key, frt_norm

ROLES = ("AM", "FE", "FRT", "SME", "COH")
WORKERS = ("AM", "FE", "FRT")  # roles that submit the Daily Achievement
TREND_WEEKS = 6
# review steps counted as the reviewer's daily activity: label per action (app.tickets.review / task FE_STEPS / nondoable)
REVIEW_ACT = {"FE_VERIFY": "verified", "FE_RETURN": "returned", "AM_APPROVE": "approved", "AM_RETURN": "returned"}
ND_ACT = {
    "VERIFICATION": "Non-Doable E1", "JUSTIFICATION": "Non-Doable E2", "FE_FORWARD": "Non-Doable forwarded", "FE_RETURN_FRT": "Non-Doable returned",
    "AM_FORWARD": "Non-Doable forwarded", "AM_RETURN": "Non-Doable returned", "REVISIT_COORDINATION": "revisit recorded", "REVISIT_VISIT": "revisit recorded",
}
# Non-Doable steps that write their own progress row (app.tickets.nondoable.act)
ND_PROGRESS_STEPS = ("MGG_APPROVE", "MGG_REJECT", "WITHDRAW", "FRT_WITHDRAW")
MAX_COMPLETED = 500
# GP returns: the action and whom the GP goes back to (FE → FRT, AM → FE, SME / COH → AM)
RETURN_TO = {"FE_RETURN": "FRT", "AM_RETURN": "FE", "SME_RETURN": "AM", "COH_RETURN": "AM"}


def _utc(v: dt.datetime | None) -> dt.datetime | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).replace(microsecond=0)


def _weeks(db: Session, allowed: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """Ticket weeks that have live tickets (of the allowed circles), newest first: code, start, end, number of tickets."""
    rows = db.execute(
        select(TicketTask.week_code, TicketTask.week_start, TicketTask.week_end, Ticket.id, TicketTask.circle).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None))
    ).all()
    by: dict[tuple[str, dt.date, dt.date], int] = defaultdict(int)
    for code, start, end, _tid, circle in rows:
        if _circle_ok(circle, allowed):
            by[(code, start, end)] += 1
    return [{"code": c, "start": s.isoformat(), "end": e.isoformat(), "tickets": n} for (c, s, e), n in sorted(by.items(), key=lambda kv: kv[0][1], reverse=True)]


def _pick_week(weeks: list[dict[str, Any]], code: str | None) -> dict[str, Any] | None:
    if code:
        return next((w for w in weeks if w["code"] == code), None)
    today = _local_date(dt.datetime.now(dt.UTC))
    current = next((w for w in weeks if w["start"] <= today.isoformat() <= w["end"]), None)
    return current or (weeks[0] if weeks else None)


def _circle_ok(value: str | None, allowed: frozenset[str] | None) -> bool:
    """A ticket circle ("Haryana", or "Haryana, Rajasthan") in the allowed circles (None = every circle)."""
    if allowed is None:
        return True
    key = lambda v: " ".join(str(v or "").split()).lower()  # noqa: E731
    return key(value) in allowed or any(key(p) in allowed for p in str(value or "").split(","))


EXTEND_MAX_DAYS = 28  # the Excel: the days after the week end it covers at most


def build(db: Session, week: str | None = None, circle: str | None = None, allowed: frozenset[str] | None = None, extend: bool = False, with_ids: bool = False) -> dict[str, Any]:
    """The report of a ticket week; `circle`: one circle; `allowed`: only these circles (a non-admin's areas).
    `extend` (the Excel): the days run from the first ticket's generation (or the week start) to today (at most
    EXTEND_MAX_DAYS after the week end) – work done after the week on its tickets counts too. The page: the 7 week days."""

    def keep(c: str | None) -> bool:
        return (not circle or (c or "") == circle) and _circle_ok(c, allowed)

    limited = bool(circle) or allowed is not None
    weeks = _weeks(db, allowed)
    w = _pick_week(weeks, week)
    if w is None:
        return {"week": None, "weeks": weeks, "circles": [], "cards": None, "roles": [], "days": [], "people": [], "completed": [], "trend": [], "returns": {"items": [], "top": []}, "amAchievement": []}
    start, end = dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    today = _local_date(dt.datetime.now(dt.UTC))

    # ---------------------------------------------------------------- the week's tickets (generated)
    week_tasks = [(k, t) for k, t in db.execute(select(TicketTask, Ticket).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None), TicketTask.week_code == w["code"]))]
    circles = sorted({k.circle for k, _t in week_tasks if k.circle and _circle_ok(k.circle, allowed)})
    if limited:
        week_tasks = [(k, t) for k, t in week_tasks if keep(k.circle)]
    tids = [t.id for _k, t in week_tasks]
    task_of = {t.id: k for k, t in week_tasks}
    # the day each ticket was generated – nobody can submit on a ticket before it exists
    made_on = {t.id: _local_date(t.created_at) for _k, t in week_tasks}
    week_end = end  # the extended days (after it) count only the work on THIS week's tickets
    if extend:
        first = min((d for d in made_on.values() if d), default=start)
        start = min(start, first)
        end = max(end, min(today, end + dt.timedelta(days=EXTEND_MAX_DAYS)))
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]

    def since(ticket_ids) -> str | None:
        d = min((made_on[i] for i in ticket_ids if made_on.get(i)), default=None)
        return d.isoformat() if d else None
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id.in_(tids)))) if tids else []
    recs = list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(tids), TicketRecipient.role.in_(ROLES)))) if tids else []
    gps_of_ticket: dict[int, list[TicketTaskGp]] = defaultdict(list)
    for g in gps:
        gps_of_ticket[g.ticket_id].append(g)

    def norm(name: str | None) -> str:
        return " ".join((name or "").split()).lower()

    def person_key(r: TicketRecipient) -> str:
        """A person = a name on the tickets (with its login, if any): two names given one login stay two people."""
        return f"u{r.user_id}|{norm(r.name)}" if r.user_id is not None else f"{r.role}:{(r.email or '').strip().lower()}|{norm(r.name)}"

    def login_of(key: str) -> str | None:
        return key.split("|", 1)[0] if key.startswith("u") else None

    def gps_of(r: TicketRecipient) -> list[TicketTaskGp]:
        """The GPs this recipient is responsible for on its ticket."""
        rows = gps_of_ticket.get(r.ticket_id, [])
        if r.role == "FE":
            key = fe_key(r.name, r.fe_mail)
            return [g for g in rows if g.fe_name is not None and fe_key(g.fe_name, g.fe_email) == key]
        if r.role == "FRT":
            code = frt_norm(r.frt_code)
            return [g for g in rows if code and frt_norm(g.frt_code) == code]
        return rows  # AM / SME / COH: every GP of the ticket

    # people of the week, per role
    people: dict[tuple[str, str], dict[str, Any]] = {}
    for r in recs:
        p = people.setdefault((r.role, person_key(r)), {"role": r.role, "name": r.name, "email": r.email, "userId": r.user_id, "account": r.user_id is not None, "tickets": set(), "gps": {}, "circles": set(), "codes": set()})
        p["tickets"].add(r.ticket_id)
        if r.role == "FRT" and frt_norm(r.frt_code):
            p["codes"].add(frt_norm(r.frt_code))
        p["account"] = p["account"] or r.user_id is not None
        k = task_of.get(r.ticket_id)
        if k is not None and k.circle:
            p["circles"].add(k.circle)
        for g in gps_of(r):
            p["gps"][g.id] = g

    # ---------------------------------------------------------------- daily submissions on the week's days (any live ticket)
    lo = dt.datetime.combine(start - dt.timedelta(days=1), dt.time(), dt.UTC)  # local days ±1 day margin, cut by the local date below
    hi = dt.datetime.combine(end + dt.timedelta(days=2), dt.time(), dt.UTC)
    subs = list(db.execute(
        select(TicketProgress, Ticket).join(Ticket, Ticket.id == TicketProgress.ticket_id).where(Ticket.deleted_at.is_(None), TicketProgress.submitted_at >= lo, TicketProgress.submitted_at < hi)
    ))
    subs = [(s, t) for s, t in subs if start <= (_local_date(s.submitted_at) or start) <= end]
    own = set(tids)
    if extend:  # after the week: only this week's tickets (other weeks' tickets have their own report)
        subs = [(s, t) for s, t in subs if (_local_date(s.submitted_at) or start) <= week_end or t.id in own]
    sub_tids = {t.id for _s, t in subs}
    if limited and sub_tids:
        circle_of = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_(sub_tids)))}
        subs = [(s, t) for s, t in subs if keep(circle_of.get(t.id))]
        sub_tids = {t.id for _s, t in subs}
    # the steps that WRITE their own progress row (same user and time) are not daily submissions: the review steps
    # (app.tickets.review.STEPS – the same rule app.tickets.task uses) and the Non-Doable steps that change the GP.
    # A Non-Doable proposed IN a daily submission (PROPOSED / PROPOSED_FRT …) is part of that submission – it counts.
    from .review import STEPS as REVIEW_STEPS  # also used for the last submission below

    step_keys = set()
    if sub_tids:
        step_keys |= {(a, _utc(at)) for a, at in db.execute(select(TicketGpReview.actor_id, TicketGpReview.at).where(TicketGpReview.ticket_id.in_(sub_tids), TicketGpReview.action.in_(tuple(REVIEW_STEPS))))}
        step_keys |= {(a, _utc(at)) for a, at in db.execute(select(NdEvent.actor_id, NdEvent.at).where(NdEvent.ticket_id.in_(sub_tids), NdEvent.action.in_(ND_PROGRESS_STEPS)))}
    daily = [(s, t) for s, t in subs if (s.submitted_by_id, _utc(s.submitted_at)) not in step_keys]
    lines_of: dict[int, list[TicketProgressLine]] = defaultdict(list)
    if daily:
        for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id.in_([s.id for s, _t in daily]))):
            lines_of[ln.progress_id].append(ln)
    # the submitter's role on each ticket
    sub_recs: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    if sub_tids:
        for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(sub_tids), TicketRecipient.user_id.is_not(None), TicketRecipient.role.in_(WORKERS))):
            sub_recs[r.ticket_id][r.user_id].add(r.role)
    names = {u.id: (u.name, u.email) for u in db.scalars(select(User).where(User.id.in_({s.submitted_by_id for s, _t in daily if s.submitted_by_id})))} if daily else {}

    def role_of(s: TicketProgress, t: Ticket) -> str | None:
        have = sub_recs.get(t.id, {}).get(s.submitted_by_id or -1, set())
        for role in ("FRT", "FE", "AM"):
            if role in have:
                return role
        return "AM" if s.submitted_by_id is not None and s.submitted_by_id == t.assignee_id else None

    activity: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)  # person -> local day -> {subs, gps}
    done_by: list[dict[str, Any]] = []
    for s, t in daily:
        role = role_of(s, t)
        if role is None:
            continue  # e.g. an admin correction – not a field submission
        key = (role, f"u{s.submitted_by_id}")  # daily work is per login (one row per submission – never twice)
        if not any(k[0] == role and login_of(k[1]) == key[1] for k in people):
            nm, em = names.get(s.submitted_by_id or -1, (s.submitted_by_name, None))
            people[(role, f"{key[1]}|{norm(nm)}")] = {"role": role, "name": nm, "email": em, "userId": s.submitted_by_id, "account": True, "tickets": set(), "gps": {}, "circles": set(), "codes": set()}
        day = (_local_date(s.submitted_at) or start).isoformat()
        cell = activity[key].setdefault(day, {"subs": 0, "gps": set(), "done": 0, "reviews": 0, "acts": {}})
        cell["subs"] += 1
        for ln in lines_of.get(s.id, []):
            cell["gps"].add(ln.task_gp_id)
            if ln.achieved_today:
                cell["done"] += 1
                done_by.append({"gpId": ln.task_gp_id, "ticketId": t.id, "ticket": t.code, "what": "DONE", "by": s.submitted_by_name, "byRole": role, "at": s.submitted_at})

    # review steps = the daily work of the FE / AM on GPs others report (FE verify / return the FRT's Daily
    # Achievement, AM approve / return, their Non-Doable steps): per login and local day as "reviews" (one per GP or
    # case) – never counted as a Daily Achievement submission
    rev_rows = [
        (x.actor_id, x.actor_name, x.role, REVIEW_ACT[x.action], x.at, x.ticket_id)
        for x in db.scalars(select(TicketGpReview).join(Ticket, Ticket.id == TicketGpReview.ticket_id).where(Ticket.deleted_at.is_(None), TicketGpReview.action.in_(tuple(REVIEW_ACT)), TicketGpReview.at >= lo, TicketGpReview.at < hi))
    ]
    rev_rows += [
        (e.actor_id, e.actor_name, e.role, ND_ACT[e.action], e.at, e.ticket_id)
        for e in db.scalars(select(NdEvent).join(Ticket, Ticket.id == NdEvent.ticket_id).where(Ticket.deleted_at.is_(None), NdEvent.action.in_(tuple(ND_ACT)), NdEvent.at >= lo, NdEvent.at < hi))
    ]
    if limited and rev_rows:
        circ_of = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_({r[5] for r in rev_rows})))}
        rev_rows = [r for r in rev_rows if keep(circ_of.get(r[5]))]
    for uid, uname, role, act, at, _tid in rev_rows:
        if uid is None or role not in ("FE", "AM") or not (start <= (_local_date(at) or start) <= end):
            continue
        if extend and (_local_date(at) or start) > week_end and _tid not in own:
            continue
        key = (role, f"u{uid}")
        if not any(k[0] == role and login_of(k[1]) == key[1] for k in people):
            people[(role, f"{key[1]}|{norm(uname)}")] = {"role": role, "name": uname, "email": None, "userId": uid, "account": True, "tickets": set(), "gps": {}, "circles": set(), "codes": set()}
        cell = activity[key].setdefault((_local_date(at) or start).isoformat(), {"subs": 0, "gps": set(), "done": 0, "reviews": 0, "acts": {}})
        cell["reviews"] += 1
        cell["acts"][act] = cell["acts"].get(act, 0) + 1

    # ---------------------------------------------------------------- completed in the week (any live ticket)
    completed: list[dict[str, Any]] = list(done_by)
    for x, t in db.execute(
        select(TicketGpReview, Ticket).join(Ticket, Ticket.id == TicketGpReview.ticket_id).where(Ticket.deleted_at.is_(None), TicketGpReview.action.in_(("COH_AMC", "COH_LETTER")), TicketGpReview.at >= lo, TicketGpReview.at < hi)
    ):
        if start <= (_local_date(x.at) or start) <= end:
            # COH: AMC converted, or the letter submitted (category E – the GP is achieved with it)
            completed.append({"gpId": x.task_gp_id, "ticketId": t.id, "ticket": t.code, "what": "AMC_CONVERTED" if x.action == "COH_AMC" else "LETTER_SUBMITTED", "by": x.actor_name, "byRole": x.role, "at": x.at})
    for e, t in db.execute(
        select(NdEvent, Ticket).join(Ticket, Ticket.id == NdEvent.ticket_id).where(Ticket.deleted_at.is_(None), NdEvent.action == "MGG_APPROVE", NdEvent.at >= lo, NdEvent.at < hi)
    ):
        if start <= (_local_date(e.at) or start) <= end:
            completed.append({"gpId": e.task_gp_id, "ticketId": t.id, "ticket": t.code, "what": "ND_APPROVED", "by": e.actor_name, "byRole": "MGG", "at": e.at})
    if extend:
        completed = [c for c in completed if c["ticketId"] in own or (_local_date(c["at"]) or start) <= week_end]
    if limited and completed:
        circ = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_({c["ticketId"] for c in completed})))}
        completed = [c for c in completed if keep(circ.get(c["ticketId"]))]
    gp_rows = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_({c["gpId"] for c in completed})))} if completed else {}
    completed.sort(key=lambda c: c["at"], reverse=True)
    completed_out = [
        {"gpId": c["gpId"], "gpCode": gp_rows[c["gpId"]].gp_code if c["gpId"] in gp_rows else None, "gpName": gp_rows[c["gpId"]].gp_name if c["gpId"] in gp_rows else None,
         "block": gp_rows[c["gpId"]].block if c["gpId"] in gp_rows else None, "ticketId": c["ticketId"], "ticket": c["ticket"], "what": c["what"], "by": c["by"], "byRole": c["byRole"],
         "at": _utc(c["at"]).isoformat() if c["at"] else None}
        for c in completed[:MAX_COMPLETED]
    ]

    # ---------------------------------------------------------------- FRT teams = every FRT code on the week's GPs
    # (Escalation Matrix, saved on the GP at generation) – a team is on the ticket's GPs whether or not it has a login;
    # only a team with a login (a user with that FRT code) can submit. A login's submissions belong to its FRT code.
    frt_users = {u.id: u for u in db.scalars(select(User).where(User.frt_code.is_not(None)))}
    logins: dict[str, list[User]] = defaultdict(list)
    for u in frt_users.values():
        if u.is_active and frt_norm(u.frt_code):
            logins[frt_norm(u.frt_code)].append(u)
    teams: dict[str, dict[str, Any]] = {}

    def team(code: str) -> dict[str, Any]:
        return teams.setdefault(code, {"tickets": set(), "gps": {}, "circles": set(), "fes": set(), "act": {}})

    for g in gps:
        code = frt_norm(g.frt_code)
        if not code:
            continue
        tm = team(code)
        tm["tickets"].add(g.ticket_id)
        tm["gps"][g.id] = g
        k = task_of.get(g.ticket_id)
        if k is not None and k.circle:
            tm["circles"].add(k.circle)
        if g.fe_name:
            tm["fes"].add(" ".join(g.fe_name.split()))
    for (role, key), days_of in activity.items():
        if role != "FRT":
            continue
        u = frt_users.get(int(key[1:])) if key[1:].isdigit() else None
        tm = team((frt_norm(u.frt_code) if u is not None else None) or key)
        for d, cell in days_of.items():
            agg = tm["act"].setdefault(d, {"subs": 0, "gps": set(), "done": 0, "reviews": 0, "acts": {}})
            agg["subs"] += cell["subs"]
            agg["reviews"] += cell.get("reviews", 0)
            agg["gps"] |= cell["gps"]
            agg["done"] += cell["done"]
    # when each login was created (days before it: "no login yet", never "nothing submitted")
    since_of = {uid: _local_date(u.created_at) for uid, u in frt_users.items()}
    other_ids = {p["userId"] for p in people.values() if p.get("userId") and p["userId"] not in since_of}
    if other_ids:
        since_of |= {u.id: _local_date(u.created_at) for u in db.scalars(select(User).where(User.id.in_(other_ids)))}

    # ---------------------------------------------------------------- status, returns, last sign-in, last submission
    def status_of(rows) -> dict[str, int]:
        """GP status counts: the category chosen in the Daily Achievement (A–E), none = not filled yet."""
        out = dict.fromkeys(("A", "B", "C", "D", "E", "none"), 0)
        for g in rows:
            out[g.gp_category if g.gp_category in out else "none"] += 1
        return out

    # returns on the week's GPs: FE → FRT (FE_RETURN), AM → FE (AM_RETURN), SME / COH → AM (SME_RETURN / COH_RETURN)
    returns_of: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    return_rows: list[TicketGpReview] = []
    if tids:
        for x in db.scalars(select(TicketGpReview).where(TicketGpReview.ticket_id.in_(tids), TicketGpReview.action.in_(tuple(RETURN_TO)))):
            returns_of[x.task_gp_id][x.action] += 1
            return_rows.append(x)
    RETURNED_TO = {"FRT": ("FE_RETURN",), "FE": ("AM_RETURN",), "AM": ("SME_RETURN", "COH_RETURN")}

    def returns(role: str, rows) -> int:
        return sum(returns_of.get(g.id, {}).get(a, 0) for g in rows for a in RETURNED_TO.get(role, ()))

    # last sign-in and last DAILY submission (any ticket, any time) of every login in the report
    uids = {p["userId"] for p in people.values() if p.get("userId")} | {u.id for us in logins.values() for u in us}
    last_login = {u.id: u.last_login_at for u in db.scalars(select(User).where(User.id.in_(uids)))} if uids else {}
    last_sub: dict[int, dt.datetime] = {}
    if uids:
        own_steps = {(a, _utc(at)) for a, at in db.execute(select(TicketGpReview.actor_id, TicketGpReview.at).where(TicketGpReview.actor_id.in_(uids), TicketGpReview.action.in_(tuple(REVIEW_STEPS))))}
        own_steps |= {(a, _utc(at)) for a, at in db.execute(select(NdEvent.actor_id, NdEvent.at).where(NdEvent.actor_id.in_(uids), NdEvent.action.in_(ND_PROGRESS_STEPS)))}
        for uid, at in db.execute(select(TicketProgress.submitted_by_id, TicketProgress.submitted_at).join(Ticket, Ticket.id == TicketProgress.ticket_id).where(Ticket.deleted_at.is_(None), TicketProgress.submitted_by_id.in_(uids))):
            if (uid, _utc(at)) in own_steps:
                continue
            if uid not in last_sub or _utc(at) > last_sub[uid]:
                last_sub[uid] = _utc(at)

    last_rev: dict[int, dt.datetime] = {}
    if uids:
        for uid, at in list(db.execute(select(TicketGpReview.actor_id, TicketGpReview.at).join(Ticket, Ticket.id == TicketGpReview.ticket_id).where(Ticket.deleted_at.is_(None), TicketGpReview.actor_id.in_(uids), TicketGpReview.action.in_(tuple(REVIEW_ACT))))) + list(
            db.execute(select(NdEvent.actor_id, NdEvent.at).join(Ticket, Ticket.id == NdEvent.ticket_id).where(Ticket.deleted_at.is_(None), NdEvent.actor_id.in_(uids), NdEvent.action.in_(tuple(ND_ACT))))
        ):
            if uid not in last_rev or _utc(at) > last_rev[uid]:
                last_rev[uid] = _utc(at)

    def iso_max(values) -> str | None:
        vals = [_utc(v) for v in values if v is not None]
        return max(vals).isoformat() if vals else None

    # ---------------------------------------------------------------- per role (generated in the week + daily work)
    day_keys = [d.isoformat() for d in days]
    role_rows = []
    for role in ROLES:
        if role == "FRT":
            on = {c: t for c, t in teams.items() if t["tickets"]}
            f_gps = {gid: g for t in on.values() for gid, g in t["gps"].items()}
            f_done = sum(1 for g in f_gps.values() if cumulative(g) >= g.target)
            role_rows.append({
                "role": "FRT", "people": len(on), "withoutAccount": sum(1 for c in on if not logins.get(c)), "withAccount": sum(1 for c in on if logins.get(c)),
                "tickets": len({tid for t in on.values() for tid in t["tickets"]}), "gps": len(f_gps), "done": f_done, "pending": len(f_gps) - f_done,
                "submissions": sum(c["subs"] for t in teams.values() for c in t["act"].values()),
                "activePeople": sum(1 for t in on.values() if t["act"]),
            })
            continue
        ps = [(k, p) for k, p in people.items() if k[0] == role and p["tickets"]]
        tickets = {tid for _k, p in ps for tid in p["tickets"]}
        role_gps = {gid: g for _k, p in ps for gid, g in p["gps"].items()}
        done = sum(1 for g in role_gps.values() if cumulative(g) >= g.target)
        acts = [a for k, a in activity.items() if k[0] == role]  # per login: each submission once
        row = {
            "role": role, "people": len(ps), "withoutAccount": sum(1 for _k, p in ps if not p["account"]), "tickets": len(tickets), "gps": len(role_gps),
            "done": done, "pending": len(role_gps) - done,
            "submissions": sum(c["subs"] for a in acts for c in a.values()),
            "activePeople": sum(1 for k, _p in ps if activity.get((role, login_of(k[1]) or "")) ),
            "reviews": sum(c.get("reviews", 0) for a in acts for c in a.values()),
        }
        if role in REVIEWER_STEPS:
            row["steps"] = _review_steps(db, tids, tuple(REVIEWER_STEPS[role]), lo, hi, start, end)
            row["reviewed"] = len(row["steps"])
        role_rows.append(row)

    # ---------------------------------------------------------------- people of the daily tracker (AM / FE / FRT)
    people_out = []
    for (role, key), p in people.items():
        if role not in WORKERS or role == "FRT":  # FRT: one row per FRT code below
            continue
        act = activity.get((role, login_of(key) or ""), {})  # the login's daily work (shared by names on one login)
        mine = list(p["gps"].values())
        people_out.append({
            "role": role, "name": p["name"], "email": p["email"], "account": p["account"], "circles": sorted(p["circles"]),
            "tickets": len(p["tickets"]), "gps": len(mine), "done": sum(1 for g in mine if cumulative(g) >= g.target),
            "days": {d: {"subs": act[d]["subs"], "gps": len(act[d]["gps"]), "done": act[d]["done"], "reviews": act[d].get("reviews", 0), "acts": act[d].get("acts", {})} for d in day_keys if d in act},
            "activeDays": sum(1 for d in day_keys if d in act),
            # FRT: its FRT code(s) and the Field Engineer(s) of its GPs (the FE it works under)
            "frtCodes": [],
            "fes": [],
            "loginSince": since_of[p["userId"]].isoformat() if p.get("userId") in since_of and since_of[p["userId"]] else None,
            "ticketSince": since(p["tickets"]),
            "status": status_of(mine), "returns": returns(role, mine),
            "lastLogin": iso_max([last_login.get(p["userId"])]) if p.get("userId") else None,
            "lastSubmission": iso_max([last_sub.get(p["userId"])]) if p.get("userId") else None,
            "submissions": sum(c["subs"] for c in act.values()),
            "reviews": sum(c.get("reviews", 0) for c in act.values()),
            "lastActive": iso_max([last_sub.get(p["userId"]), last_rev.get(p["userId"])]) if p.get("userId") else None,
            **({"ticketIds": sorted(p["tickets"]), "gpIds": list(p["gps"])} if with_ids else {}),
        })
    for code, tm in teams.items():
        users = logins.get(code, [])
        mine = list(tm["gps"].values())
        act = tm["act"]
        first = min((since_of.get(u.id) for u in users if since_of.get(u.id)), default=None)
        people_out.append({
            "role": "FRT", "name": ", ".join(u.name for u in users) if users else code, "email": None, "account": bool(users), "circles": sorted(tm["circles"]),
            "tickets": len(tm["tickets"]), "gps": len(mine), "done": sum(1 for g in mine if cumulative(g) >= g.target),
            "days": {d: {"subs": act[d]["subs"], "gps": len(act[d]["gps"]), "done": act[d]["done"], "reviews": act[d].get("reviews", 0), "acts": act[d].get("acts", {})} for d in day_keys if d in act},
            "activeDays": sum(1 for d in day_keys if d in act), "frtCodes": [] if (code.startswith("u") and code[1:].isdigit()) else [code],
            "fes": sorted(tm["fes"]), "loginSince": first.isoformat() if first else None, "ticketSince": since(tm["tickets"]),
            "status": status_of(mine), "returns": returns("FRT", mine),
            "lastLogin": iso_max([last_login.get(u.id) for u in users]), "lastSubmission": iso_max([last_sub.get(u.id) for u in users]),
            "submissions": sum(c["subs"] for c in act.values()),
            "reviews": 0,
            "lastActive": iso_max([last_sub.get(u.id) for u in users]),
            **({"ticketIds": sorted(tm["tickets"]), "gpIds": list(tm["gps"])} if with_ids else {}),
        })
    people_out.sort(key=lambda x: (WORKERS.index(x["role"]), x["name"].lower()))
    for row in role_rows:
        mine_rows = [x for x in people_out if x["role"] == row["role"] and x["tickets"] > 0]
        if row["role"] in WORKERS:
            row["status"] = {k: sum(x["status"][k] for x in mine_rows) for k in ("A", "B", "C", "D", "E", "none")}
            row["returns"] = sum(x["returns"] for x in mine_rows)
            row["neverSignedIn"] = sum(1 for x in mine_rows if x["account"] and not x["lastLogin"])

    # ---------------------------------------------------------------- cards
    nd = list(db.scalars(select(NdCase).where(NdCase.ticket_id.in_(tids)))) if tids else []
    cards = {
        "tickets": len(tids), "closed": sum(1 for _k, t in week_tasks if t.status == "CLOSED"), "gps": len(gps),
        "done": sum(1 for g in gps if cumulative(g) >= g.target), "amcConverted": sum(1 for g in gps if g.review == "AMC_CONVERTED"),
        "nonDoable": len(nd), "nonDoableApproved": sum(1 for c in nd if c.status == "APPROVED"),
        "submissions": sum(c["subs"] for a in activity.values() for c in a.values()),
        "submittedToday": sum(1 for a in activity.values() if a.get(today.isoformat(), {}).get("subs")),
    }
    gp_by_id = {g.id: g for g in gps}
    tickets_by_id = {t.id: t for _k, t in week_tasks}
    ret_items = []
    for x in return_rows:
        g, k, t = gp_by_id.get(x.task_gp_id), task_of.get(x.ticket_id), tickets_by_id.get(x.ticket_id)
        if g is None or t is None:
            continue
        to_role = RETURN_TO[x.action]
        if to_role == "FRT":
            code = frt_norm(g.frt_code)
            to = ", ".join(u.name for u in logins.get(code or "", [])) or g.frt_code or "FRT"
        elif to_role == "FE" and g.fe_name:
            to = g.fe_name
        else:  # SME / COH → AM, or an AM return on a GP without a Field Engineer
            to, to_role = (k.am_name if k is not None else None) or "AM", "AM"
        ret_items.append({
            "at": _utc(x.at).isoformat(), "gpId": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "block": g.block, "ticketId": t.id, "ticket": t.code,
            "by": x.actor_name, "byRole": x.role, "to": to, "toRole": to_role, "frtCode": g.frt_code if to_role == "FRT" else None, "remark": x.remark,
        })
    ret_items.sort(key=lambda r: r["at"], reverse=True)
    ret_top: dict[tuple[str, str], int] = defaultdict(int)
    for r in ret_items:
        ret_top[(r["toRole"], r["to"])] += 1
    pending = _pending(db, week_tasks, gps, today)
    bucket_of = {it["gpId"]: it["bucket"] for it in pending["items"]}
    # one person per GP: the GPs this person has to fill (not filled) / work on again (revisit, returned) – the GP's
    # reporter only (FRT team with a login, else the FE, else the AM), each GP code once. "status.none" stays every
    # not-filled GP on their tickets.
    item_of = {it["gpId"]: it for it in pending["items"]}
    code_of_gp = {g.id: g.gp_code for g in gps}

    def owned(role: str, gids, bucket: str) -> int:
        return len({code_of_gp.get(gid) for gid in gids if (it := item_of.get(gid)) and it.get("primary") and it["bucket"] == bucket and it["whoRole"] == role})

    by_key = {}
    for (role, key), p in people.items():
        if role in WORKERS and role != "FRT":
            by_key[(role, p["name"], p["email"])] = list(p["gps"])
    for x in people_out:
        gids = by_key.get((x["role"], x["name"], x["email"]), []) if x["role"] != "FRT" else list(teams.get((x["frtCodes"] or [x["name"]])[0], {}).get("gps", {}))
        x["toFill"] = owned(x["role"], gids, "not_filled")
        x["toRework"] = owned(x["role"], gids, "field")
    for row in role_rows:
        if row["role"] in WORKERS:
            row["toFill"] = sum(x.get("toFill", 0) for x in people_out if x["role"] == row["role"])
    am_rows = []
    for (role, _key), pp in people.items():
        if role != "AM" or not pp["tickets"]:
            continue
        mine = list(pp["gps"].values())
        done_n = sum(1 for g in mine if cumulative(g) >= g.target)
        waiting: dict[str, int] = defaultdict(int)
        for g in mine:  # where the GPs not achieved yet wait now (achieved + waiting = GPs)
            b = bucket_of.get(g.id)
            if b and b != "closed" and cumulative(g) < g.target:
                waiting[b] += 1
        am_rows.append({
            "name": pp["name"], "account": pp["account"], "circles": sorted(pp["circles"]), "tickets": len(pp["tickets"]), "ticketIds": sorted(pp["tickets"]), "gps": len(mine), "done": done_n,
            "pct": round(done_n * 100 / len(mine), 1) if mine else 0.0, "waiting": dict(waiting),
        })
    am_rows.sort(key=lambda a: (a["gps"] == 0, -a["pct"], -a["done"], -a["gps"], a["name"].lower()))  # top achiever first; no GPs last
    # every GP once (a GP on two tickets of the week counts once): GPs, achieved, how many are on two tickets
    by_code: dict[str, list[TicketTaskGp]] = defaultdict(list)
    for g in gps:
        by_code[g.gp_code or f"#{g.id}"].append(g)
    cards["gpsUnique"] = len(by_code)
    cards["doneUnique"] = sum(1 for rows_ in by_code.values() if any(cumulative(g) >= g.target for g in rows_))
    cards["gpsOnTwoTickets"] = sum(1 for rows_ in by_code.values() if len({g.ticket_id for g in rows_}) > 1)
    # after the week (the page shows the 7 week days): the daily work done AFTER the week on this week's tickets
    if not extend and tids and today > week_end:
        _after_week(db, week, circle, allowed, week_end, people_out, role_rows, cards)
    return {
        "week": w, "weeks": weeks, "circles": circles, "circle": circle, "today": today.isoformat(), "cards": cards, "roles": role_rows,
        "returns": {"items": ret_items, "top": [{"role": r, "name": n, "count": c} for (r, n), c in sorted(ret_top.items(), key=lambda kv: (-kv[1], kv[0][1].lower()))]},
        "amAchievement": am_rows,
        "days": [{"date": d.isoformat(), "future": d > today} for d in days], "people": people_out, "completed": completed_out,
        "completedTotal": len(completed), "trend": _trend(db, weeks, circle, allowed),
        "pending": pending,
    }


def _after_week(db: Session, week: str | None, circle: str | None, allowed: frozenset[str] | None, week_end: dt.date,
                people_out: list[dict[str, Any]], role_rows: list[dict[str, Any]], cards: dict[str, Any]) -> None:
    """The page keeps the 7 week days; the work done after the week on THIS week's tickets is added as totals: per
    person "afterWeek" (submissions, GPs, days), per role and in the cards "submissionsAfterWeek". Same counting rules
    as the days of the week (the Excel's extended build, app.tickets.report.build(extend=True))."""
    ext = build(db, week, circle, allowed, extend=True)
    key = lambda p: (p["role"], p["name"], p.get("email"), tuple(p.get("frtCodes") or ()))  # noqa: E731
    after: dict[tuple, dict[str, int]] = {}
    for p in ext.get("people", []):
        cells = [c for d, c in p["days"].items() if d > week_end.isoformat()]
        after[key(p)] = {"subs": sum(c["subs"] for c in cells), "gps": sum(c["gps"] for c in cells), "days": sum(1 for c in cells if c["subs"] or c.get("reviews"))}
    total = 0
    by_role: dict[str, int] = defaultdict(int)
    for p in people_out:
        a = after.get(key(p), {"subs": 0, "gps": 0, "days": 0})
        p["afterWeek"] = a
        total += a["subs"]
        by_role[p["role"]] += a["subs"]
    cards["submissionsAfterWeek"] = total
    cards["afterWeekUntil"] = (ext.get("days") or [{}])[-1].get("date")
    for row in role_rows:
        if row["role"] in WORKERS:
            row["submissionsAfterWeek"] = by_role.get(row["role"], 0)


# ---------------------------------------------------------------- pending with
# where a GP of the week waits now (the stage of app.tickets.review.stage_of, as on the ticket page; an open
# Non-Doable case: its own stage, app.tickets.nondoable._pending_with)
PENDING_BUCKETS = (
    ("not_filled", "Not filled"),
    ("field", "Revisit / returned"),
    ("fe_verify", "FE verify"),
    ("am", "AM approval"),
    ("sme", "SME"),
    ("coh", "COH"),
    ("nd", "Non-Doable case"),
    ("closed", "Completed"),
)
OVERDUE_DAYS = 2  # waiting longer than this: shown as overdue
# how far a GP got (a GP on two tickets: the further row tells its real state)
PROGRESS_RANK = {"not_filled": 0, "field": 1, "nd": 2, "fe_verify": 3, "am": 4, "sme": 5, "coh": 6, "closed": 7}


def _pending(db: Session, week_tasks: list[tuple[TicketTask, Ticket]], gps: list[TicketTaskGp], today: dt.date) -> dict[str, Any]:
    """Every GP of the week's tickets: the step it waits at, with whom (name and role) and since when (the last thing
    that happened to it: a daily progress line, a review step, the Non-Doable case, else the ticket's generation)."""
    from . import nondoable as nd
    from .review import stage_label, stage_of
    from .task import fe_owner_keys, frt_owner_codes

    empty = {"buckets": [{"key": k, "label": lbl, "count": 0, "overdue": 0} for k, lbl in PENDING_BUCKETS], "items": [], "overdueDays": OVERDUE_DAYS}
    if not gps:
        return empty
    tickets = {t.id: (k, t) for k, t in week_tasks}
    gids = [g.id for g in gps]
    cases: dict[int, NdCase] = {}
    for c in db.scalars(select(NdCase).where(NdCase.task_gp_id.in_(gids)).order_by(NdCase.id)):
        cases[c.task_gp_id] = c  # the latest case of the GP
    last: dict[int, dt.datetime] = {}

    def bump(gid: int, at: dt.datetime | None) -> None:
        if at is not None and (gid not in last or _utc(at) > last[gid]):
            last[gid] = _utc(at)

    for gid, at in db.execute(select(TicketProgressLine.task_gp_id, TicketProgress.submitted_at).join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id).where(TicketProgressLine.task_gp_id.in_(gids))):
        bump(gid, at)
    for gid, at in db.execute(select(TicketGpReview.task_gp_id, TicketGpReview.at).where(TicketGpReview.task_gp_id.in_(gids))):
        bump(gid, at)
    for g in gps:
        bump(g.id, g.review_at)
    for c in cases.values():
        bump(c.task_gp_id, c.updated_at)
    # the people of each ticket: names per role; FRT accounts per code; FEs with a working account
    names: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    frt_who: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(list(tickets)), TicketRecipient.role.in_(ROLES))):
        if r.name not in names[r.ticket_id][r.role]:
            names[r.ticket_id][r.role].append(r.name)
        if r.role == "FRT" and r.user_id is not None and r.can_work and frt_norm(r.frt_code):
            frt_who[r.ticket_id][frt_norm(r.frt_code)].append(r.name)
    fe_keys = {tid: fe_owner_keys(db, t) for tid, (_k, t) in tickets.items()}
    frt_codes = {tid: frt_owner_codes(db, t) for tid, (_k, t) in tickets.items()}

    items = []
    for g in gps:
        k, t = tickets[g.ticket_id]
        am = k.am_name
        code = frt_norm(g.frt_code)
        fe_ok = g.fe_name is not None and fe_key(g.fe_name, g.fe_email) in fe_keys[g.ticket_id]

        def reporter() -> tuple[str, str]:
            """Who reports the GP in the Daily Achievement: its FRT team (with a login), else its FE, else the AM."""
            if code and code in frt_codes[g.ticket_id]:
                return ", ".join(frt_who[g.ticket_id][code]) or code, "FRT"
            if fe_ok:
                return g.fe_name, "FE"
            return am, "AM"

        def by_role(role: str) -> tuple[str, str]:
            if role == "FRT":
                return ", ".join(frt_who[g.ticket_id].get(code or "", [])) or (code or "FRT"), "FRT"
            if role == "FE":
                return (g.fe_name, "FE") if g.fe_name else (am, "AM")
            if role == "AM":
                return am, "AM"
            if role in ("SME", "COH"):
                return ", ".join(names[g.ticket_id].get(role, [])) or role, role
            return role, role  # Corporate Team – MGG

        c = cases.get(g.id)
        nd_role = nd._pending_with(c) if c is not None else None
        nd_open = c is not None and c.status in nd.OPEN
        stage = stage_of(g, nd_open)
        if nd_role:
            bucket, (who, who_role), label = "nd", by_role(nd_role), f"{c.ref} · {nd.STATUS_LABEL.get(c.status, c.status)}"
        elif stage == "PENDING_FE":
            bucket, (who, who_role), label = "fe_verify", by_role("FE"), stage_label(stage)
        elif stage == "RETURNED_FRT":
            bucket, (who, who_role), label = "field", by_role("FRT"), stage_label(stage)
        elif stage == "RETURNED":
            bucket, (who, who_role), label = "field", reporter() if not code or code not in frt_codes[g.ticket_id] else by_role("FE"), stage_label(stage)
        elif stage in ("PENDING_AM", "SME_RETURNED"):
            bucket, (who, who_role), label = "am", by_role("AM"), stage_label(stage)
        elif stage in ("AM_APPROVED", "COH_RETURNED"):
            bucket, (who, who_role), label = "sme", by_role("SME"), stage_label(stage)
        elif stage in ("SME_FORWARDED", "LETTER_SUBMITTED"):
            bucket, (who, who_role), label = "coh", by_role("COH"), stage_label(stage)
        elif stage in ("AMC_CONVERTED", "ND_APPROVED") or cumulative(g) >= g.target:
            bucket, (who, who_role), label = "closed", ("—", "—"), stage_label(stage) if stage != "NONE" else "Achieved"
        elif g.gp_category is None:
            bucket, (who, who_role), label = "not_filled", reporter(), "Not filled yet"
        else:  # Revisit Required (C) or another category without a review yet
            from .task import CATEGORIES

            bucket, (who, who_role), label = "field", reporter(), CATEGORIES.get(g.gp_category, g.gp_category)
        since = last.get(g.id) or _utc(t.created_at)
        days = max(0, (today - (_local_date(since) or today)).days)
        items.append({
            "gpId": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "block": g.block, "ticketId": t.id, "ticket": t.code, "bucket": bucket, "stage": label,
            "who": who, "whoRole": who_role, "since": since.isoformat() if since else None, "days": days,
            "why": _why(bucket, who_role, code, code in frt_codes[g.ticket_id] if code else False, g.fe_name),
        })
    counts = defaultdict(int)
    overdue = defaultdict(int)
    for it in items:
        counts[it["bucket"]] += 1
        if it["bucket"] != "closed" and it["days"] > OVERDUE_DAYS:
            overdue[it["bucket"]] += 1
    items.sort(key=lambda it: (it["bucket"] == "closed", -it["days"], it["gpCode"] or ""))
    # every GP once: a GP on two tickets of the week – its row that got FURTHEST is the "primary" one (equal: the newest
    # ticket's); the others stay for the per-ticket views (e.g. the Area Manager's GPs); "tickets" names all of them
    of_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        of_code[it["gpCode"] or f"#{it['gpId']}"].append(it)
    gps_n, gps_late = defaultdict(int), defaultdict(int)
    for rows_ in of_code.values():
        top = max(rows_, key=lambda x: (PROGRESS_RANK.get(x["bucket"], 0), x["ticketId"]))
        codes = [x["ticket"] for x in sorted(rows_, key=lambda x: x["ticketId"])]
        for it in rows_:
            it["primary"] = it is top
            it["tickets"] = codes
        gps_n[top["bucket"]] += 1
        if top["bucket"] != "closed" and top["days"] > OVERDUE_DAYS:
            gps_late[top["bucket"]] += 1
    return {
        "buckets": [{"key": k, "label": lbl, "count": counts[k], "overdue": overdue[k], "gps": gps_n[k], "gpsOverdue": gps_late[k]} for k, lbl in PENDING_BUCKETS],
        "items": items, "overdueDays": OVERDUE_DAYS,
    }


def _why(bucket: str, role: str, frt: str | None, frt_login: bool, fe: str | None) -> str:
    """Why the GP waits with this person (plain words – the page and the Excel)."""
    if bucket in ("not_filled", "field"):
        if role == "FRT":
            return f"FRT team {frt} reports this GP"
        if role == "FE":
            return f"FRT team {frt} has no login – the FE reports it" if frt and not frt_login else "No FRT team on this GP – the FE reports it"
        if fe:
            return f"FE {fe} has no login" + (f" and FRT team {frt} has none" if frt and not frt_login else "") + " – the AM reports it"
        return "No FE on this GP" + (f" and FRT team {frt} has no login" if frt and not frt_login else "") + " – the AM reports it"
    return {"fe_verify": "The FRT reported it – the FE checks it", "am": "Reported and verified – the AM approves it", "sme": "Approved by the AM – the SME checks it",
            "coh": "Forwarded by the SME – the COH acts", "nd": "Open Non-Doable case", "closed": "Done"}.get(bucket, "")


# SME / COH review steps: label per action
REVIEWER_STEPS = {
    "SME": {"SME_FORWARD": "Forwarded to COH", "SME_RETURN": "Returned to AM"},
    "COH": {"COH_LETTER": "Letter submitted", "COH_AMC": "AMC converted", "COH_RETURN": "Returned to AM"},
}


def _review_steps(db: Session, tids: list[int], actions: tuple[str, ...], lo: dt.datetime, hi: dt.datetime, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """GP review steps of these actions recorded on the week's days (on the week's tickets), latest first: who did
    it, which GP, when, the remark. Its length is the role's "reviewed" count."""
    if not tids:
        return []
    labels = {a: lbl for m in REVIEWER_STEPS.values() for a, lbl in m.items()}
    q = (
        select(TicketGpReview, Ticket, TicketTaskGp)
        .join(Ticket, Ticket.id == TicketGpReview.ticket_id)
        .join(TicketTaskGp, TicketTaskGp.id == TicketGpReview.task_gp_id)
        .where(TicketGpReview.ticket_id.in_(tids), TicketGpReview.action.in_(actions), TicketGpReview.at >= lo, TicketGpReview.at < hi)
    )
    out = [
        {"at": _utc(x.at).isoformat(), "action": labels.get(x.action, x.action), "by": x.actor_name, "gpCode": g.gp_code, "gpName": g.gp_name,
         "block": g.block, "ticketId": t.id, "ticket": t.code, "remark": x.remark}
        for x, t, g in db.execute(q)
        if start <= (_local_date(x.at) or start) <= end
    ]
    out.sort(key=lambda r: r["at"], reverse=True)
    return out


def _trend(db: Session, weeks: list[dict[str, Any]], circle: str | None, allowed: frozenset[str] | None = None) -> list[dict[str, Any]]:
    """The last ticket weeks (oldest first): tickets generated, their GPs, achieved GPs."""
    out = []
    for w in reversed(weeks[:TREND_WEEKS]):
        q = select(TicketTask.ticket_id, TicketTask.circle).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None), TicketTask.week_code == w["code"])
        if circle:
            q = q.where(TicketTask.circle == circle)
        tids = [tid for tid, c in db.execute(q) if _circle_ok(c, allowed)]
        gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id.in_(tids)))) if tids else []
        out.append({"week": w["code"], "tickets": len(tids), "gps": len(gps), "done": sum(1 for g in gps if cumulative(g) >= g.target)})
    return out


LABEL = {"DONE": "Done (achieved)", "LETTER_SUBMITTED": "Letter submitted (done)", "AMC_CONVERTED": "AMC converted", "ND_APPROVED": "Non-Doable approved"}

# What the person has to do now, per "pending with" bucket (the Excel)
ACTION = {
    "not_filled": "Fill the Daily Achievement",
    "field": "Work on the GP again (revisit / returned)",
    "fe_verify": "Verify the FRT's entry",
    "am": "Approve or return",
    "sme": "Check and forward to the COH",
    "coh": "Submit the letter / record the AMC",
    "nd": "Next step of the Non-Doable case",
    "closed": "Nothing – done",
}
CAT_LABEL = {"A": "Rectification Done", "B": "Ready for Letter Submission", "C": "Revisit Required", "D": "Non-Doable – Proposed", "E": "Letter Submission Done"}


def _d(v: str | dt.date | dt.datetime | None, time: bool = False) -> str:
    """A date (or date and time) as 19-Nov-2026 (19-Nov-2026 14:05); empty when unknown."""
    if not v:
        return ""
    if isinstance(v, str):
        try:
            v = dt.datetime.fromisoformat(v) if "T" in v or " " in v else dt.date.fromisoformat(v[:10])
        except ValueError:
            return v
    if isinstance(v, dt.datetime):
        loc = _local_date(v)
        if time:
            from .monitor import _zone

            return _utc(v).astimezone(_zone()).strftime("%d-%b-%Y %H:%M")
        return loc.strftime("%d-%b-%Y") if loc else ""
    return v.strftime("%d-%b-%Y")


def excel_details(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    """What the Excel needs beyond the page: every GP ONCE (a GP on two tickets of the week: the newest ticket's row,
    both ticket codes), its AM / FE / FRT team and whether that team has a login, WHO has to act now and WHY, the
    people who have to act (one owner per GP), and the warnings (FRT teams without a login, tickets generated after
    the week, GPs on two tickets, tickets without GPs). Read only."""
    items = (data.get("pending") or {}).get("items", [])
    gids = [it["gpId"] for it in items]
    gp = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_(gids)))} if gids else {}
    tids = sorted({it["ticketId"] for it in items})
    task = {k.ticket_id: k for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_(tids)))} if tids else {}
    made = {t.id: _local_date(t.created_at) for t in db.scalars(select(Ticket).where(Ticket.id.in_(tids)))} if tids else {}
    logins = {frt_norm(u.frt_code) for u in db.scalars(select(User).where(User.frt_code.is_not(None), User.is_active.is_(True)))} - {None}
    active = set(db.scalars(select(User.id).where(User.is_active.is_(True))))
    am_login: set[int] = set()
    fe_login: set[tuple[int, Any]] = set()
    for r in (db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(tids), TicketRecipient.role.in_(("AM", "FE")))) if tids else []):
        if r.user_id is None or r.user_id not in active:
            continue
        if r.role == "AM":
            am_login.add(r.ticket_id)
        else:
            fe_login.add((r.ticket_id, fe_key(r.name, r.fe_mail)))
    # ---- the history of every GP (all its rows – a GP on two tickets: both): fills and review steps, every date
    all_gids = list(gp)
    hist: dict[str, dict[str, list[dt.datetime]]] = defaultdict(lambda: defaultdict(list))
    returns_of: dict[str, list[tuple[dt.datetime, str]]] = defaultdict(list)
    code_of = {gid: (g.gp_code or f"#{gid}") for gid, g in gp.items()}
    if all_gids:
        reviews = list(db.scalars(select(TicketGpReview).where(TicketGpReview.task_gp_id.in_(all_gids))))
        step_keys = {(x.actor_id, _utc(x.at)) for x in reviews}  # review steps write a progress row too – not a fill
        step_keys |= {(a, _utc(at)) for a, at in db.execute(select(NdEvent.actor_id, NdEvent.at).where(NdEvent.task_gp_id.in_(all_gids), NdEvent.action.in_(ND_PROGRESS_STEPS)))}
        roles_on: dict[int, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
        for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id.in_(tids), TicketRecipient.user_id.is_not(None), TicketRecipient.role.in_(WORKERS))):
            roles_on[r.ticket_id][r.user_id].add(r.role)
        assignee = {t.id: t.assignee_id for t in db.scalars(select(Ticket).where(Ticket.id.in_(tids)))} if tids else {}
        for gid, by, at, tid in db.execute(
            select(TicketProgressLine.task_gp_id, TicketProgress.submitted_by_id, TicketProgress.submitted_at, TicketProgress.ticket_id)
            .join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id).where(TicketProgressLine.task_gp_id.in_(all_gids))
        ):
            if (by, _utc(at)) in step_keys:
                continue
            have = roles_on.get(tid, {}).get(by or -1, set())
            role = next((x for x in ("FRT", "FE", "AM") if x in have), "AM" if by is not None and by == assignee.get(tid) else None)
            if role:
                hist[code_of[gid]][f"fill_{role}"].append(_utc(at))
        TO = {"FE_RETURN": "FE → FRT", "AM_RETURN": "AM → FE", "SME_RETURN": "SME → AM", "COH_RETURN": "COH → SME"}
        for x in reviews:
            c = code_of.get(x.task_gp_id)
            if c is None:
                continue
            if x.action in TO:
                why_back = " ".join((x.remark or "").split())
                returns_of[c].append((_utc(x.at), f"{TO[x.action]}" + (f" ({why_back[:80]})" if why_back else "")))
            else:
                hist[c][x.action].append(_utc(x.at))

    def dates(code: str, key: str) -> str:
        """Every date of the step, oldest first: 24-Nov, 26-Nov (×2 = done twice – e.g. after a return)."""
        ev = [v for v in hist.get(code, {}).get(key, []) if v]
        ds = sorted({d for d in (_local_date(v) for v in ev) if d})
        text = ", ".join(d.strftime("%d-%b") for d in ds)
        return f"{text} ({len(ev)}×)" if len(ev) > len(ds) else text  # done twice on one day

    def returned(code: str) -> str:
        return "; ".join(f"{_local_date(at).strftime('%d-%b')}: {what}" for at, what in sorted(returns_of.get(code, [])) if _local_date(at))

    # login and last sign-in of the people of the report (Summary: the person the work is pending with)
    seen = {(p["role"], p["name"]): p.get("lastLogin") for p in data.get("people", [])}
    seen |= {(p["role"], c): p.get("lastLogin") for p in data.get("people", []) for c in (p.get("frtCodes") or [])}
    has_login = {(p["role"], p["name"]): p["account"] for p in data.get("people", [])}
    has_login |= {(p["role"], c): p["account"] for p in data.get("people", []) for c in (p.get("frtCodes") or [])}

    def why(it: dict[str, Any], g: TicketTaskGp | None) -> str:
        b, role = it["bucket"], it["whoRole"]
        code = frt_norm(g.frt_code) if g is not None else None
        if b in ("not_filled", "field"):
            if role == "FRT":
                return f"FRT team {code} reports this GP"
            if role == "FE":
                return f"FRT team {code} has no login – the FE reports this GP" if code else "No FRT team on this GP – the FE reports it"
            if g is not None and g.fe_name:
                return f"FE {g.fe_name} has no login" + (f" and FRT team {code} has none" if code else "") + " – the AM reports this GP"
            return "No FE on this GP" + (f" and FRT team {code} has no login" if code else "") + " – the AM reports it"
        return {"fe_verify": "The FRT reported it – the FE checks it", "am": "Reported and verified – the AM approves it", "sme": "Approved by the AM – the SME checks it",
                "coh": "Forwarded by the SME – the COH acts", "nd": "Open Non-Doable case", "closed": "Done"}.get(b, "")

    def status_now(it: dict[str, Any], cat: str | None) -> str:
        filled = f"Filled as {cat}" if cat else "Filled"
        return {
            "not_filled": "NOT FILLED – no Daily Achievement yet",
            "field": f"{filled} – needs work in the field again",
            "fe_verify": f"{filled} – waiting for the FE to verify",
            "am": f"{filled} – waiting for the AM to approve",
            "sme": "Approved by the AM – waiting for the SME",
            "coh": "Forwarded by the SME – waiting for the COH (letter / AMC)",
            "nd": f"Non-Doable case – {it['stage']}",
            "closed": f"DONE – {it['stage']}",
        }.get(it["bucket"], it["stage"] or "")

    # one row per GP code: the newest ticket's row; the GP's other tickets listed
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        by_code[it["gpCode"] or f"#{it['gpId']}"].append(it)
    rows = []
    for code, its in by_code.items():
        its = sorted(its, key=lambda x: x["ticketId"], reverse=True)
        it = next((x for x in its if x.get("primary")), its[0])  # the GP's row that got furthest (as on the page)
        g = gp.get(it["gpId"])
        k = task.get(it["ticketId"])
        frt = frt_norm(g.frt_code) if g is not None else None
        rows.append({
            **it, "tickets": ", ".join(x["ticket"] for x in sorted(its, key=lambda x: x["ticketId"])), "onTickets": len(its),
            "am": k.am_name if k is not None else "", "fe": (g.fe_name if g is not None else None) or "", "frt": frt or "",
            "frtLogin": ("Yes" if frt in logins else "No") if frt else "", "achieved": g is not None and cumulative(g) >= g.target,
            "amLogin": "Yes" if it["ticketId"] in am_login else "No",
            "circle": (g.circle if g is not None else None) or (k.circle if k is not None else "") or "",
            "ba": (g.business_area if g is not None else None) or "",
            "generated": ", ".join(sorted({made[x["ticketId"]].strftime("%d-%b") for x in its if made.get(x["ticketId"])}, key=lambda v: dt.datetime.strptime(v, "%d-%b"))),
            "dates": {key: dates(code, key) for key in ("fill_FRT", "fill_FE", "fill_AM", "FE_VERIFY", "AM_APPROVE", "SME_FORWARD", "COH_LETTER", "COH_AMC")},
            "returned": returned(code),
            "feLogin": (("Yes" if (it["ticketId"], fe_key(g.fe_name, g.fe_email)) in fe_login else "No") if g is not None and g.fe_name else ""),
            "status": status_now(it, CAT_LABEL.get(g.gp_category) if g is not None and g.gp_category else None),
            "category": CAT_LABEL.get(g.gp_category, "") if g is not None and g.gp_category else "Not filled",
            "action": ACTION.get(it["bucket"], ""), "why": it.get("why") or why(it, g),
        })
    for r in rows:  # with the COH: the letter is already submitted – only the AMC is left
        if r["bucket"] == "coh" and r["dates"]["COH_LETTER"]:
            r["status"] = "Letter submitted – waiting for the COH to record the AMC"
    rows.sort(key=lambda r: (r["bucket"] == "closed", -r["days"], r["gpCode"] or ""))

    # who has to act now: one owner per GP (the GP's row above)
    owners: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if r["bucket"] == "closed":
            continue
        o = owners.setdefault((r["whoRole"], r["who"]), {
            "who": r["who"], "role": r["whoRole"], "total": 0, "oldest": 0, **{b: 0 for b in ACTION if b != "closed"},
            "login": "Yes" if has_login.get((r["whoRole"], r["who"])) or (r["whoRole"] == "FRT" and r["frt"] in logins) else "No",
            "lastLogin": seen.get((r["whoRole"], r["who"])),
        })
        o[r["bucket"]] += 1
        o["total"] += 1
        o["oldest"] = max(o["oldest"], r["days"])
    act = sorted(owners.values(), key=lambda o: (-o["total"], -o["oldest"], str(o["who"]).lower()))

    w = data.get("week") or {}
    week_end = dt.date.fromisoformat(w["end"]) if w.get("end") else None
    frt_role = next((x for x in data.get("roles", []) if x["role"] == "FRT"), {})
    late = sorted({(t, d) for t, d in made.items() if week_end and d and d > week_end}, key=lambda x: x[1])
    code_of = {it["ticketId"]: it["ticket"] for it in items}
    warnings = []
    if frt_role.get("withoutAccount"):
        warnings.append(f"{frt_role['withoutAccount']} of {frt_role.get('people', 0)} FRT teams have no login – their GPs are reported by the FE (or the AM). Create the FRT logins in User Management (FRT code).")
    if late:
        warnings.append(f"{len(late)} ticket(s) were generated after the week ended ({_d(week_end)}): " + ", ".join(f"{code_of.get(t, t)} on {_d(d)}" for t, d in late[:6]) + (" …" if len(late) > 6 else "") + ". The days run until today so their work shows.")
    twice = [r for r in rows if r["onTickets"] > 1]
    if twice:
        pairs = sorted({r["tickets"] for r in twice})
        warnings.append(f"{len(twice)} GP(s) are on two tickets of this week ({'; '.join(pairs[:4])}) – each GP is counted once here.")
    empty = (data.get("cards") or {}).get("tickets", 0) - len(tids)
    if empty > 0:
        warnings.append(f"{empty} ticket(s) of this week have no GPs.")
    from .units import gp_tickets

    people_gps = [gid for p in data.get("people", []) for gid in p.get("gpIds", [])]
    every = people_gps + [it["gpId"] for it in items] + [x.get("gpId") for x in (data.get("returns") or {}).get("items", [])] + [c.get("gpId") for c in data.get("completed", [])]
    hier = gp_tickets(db, every)
    all_t = {tid for p in data.get("people", []) for tid in p.get("ticketIds", [])}
    code_t = dict(db.execute(select(Ticket.id, Ticket.code).where(Ticket.id.in_(all_t))).all()) if all_t else {}
    own: list[list[str]] = []
    for p in data.get("people", []):
        if p["role"] == "AM":
            ids = sorted(code_t[t] for t in p.get("ticketIds", []) if code_t.get(t))
        else:
            key = "feCode" if p["role"] == "FE" else "frtCode"
            ids = sorted({hier[g][key] for g in p.get("gpIds", []) if g in hier and hier[g][key]})
        own.append(ids)
    return {"rows": rows, "act": act, "warnings": warnings, "made": made, "tickets": len(tids), "hier": hier, "own": own}


def xlsx(data: dict[str, Any], details: dict[str, Any] | None = None) -> bytes:
    """The report as an Excel workbook, written to be read without the page: Summary (the week at a glance, who has to
    act now, warnings, what the words mean), GP Status (every GP once, who acts and why), Team Activity (per person,
    every day from the ticket's generation to today), AM Achievement, Returns, Completed."""
    import xlsxwriter

    from .units import HIER_COLS, HIER_NOTE, hier_values

    det = details or {"rows": [], "act": [], "warnings": [], "made": {}, "tickets": 0}
    hier = det.get("hier") or {}
    hier_heads, hier_widths = [h for h, _w in HIER_COLS], [w for _h, w in HIER_COLS]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    title = wb.add_format({"bold": True, "font_size": 14, "font_color": "#0F766E"})
    sub = wb.add_format({"bold": True, "font_size": 11, "font_color": "#0F172A", "bottom": 1})
    head = wb.add_format({"bold": True, "bg_color": "#0F766E", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter"})
    note = wb.add_format({"italic": True, "font_color": "#475569", "text_wrap": True, "valign": "top"})
    warn = wb.add_format({"bold": True, "font_color": "#B45309", "text_wrap": True, "valign": "top"})
    num = wb.add_format({"align": "right"})
    big = wb.add_format({"bold": True, "align": "right"})
    hot = wb.add_format({"bold": True, "font_color": "#B91C1C", "align": "right"})
    w = data.get("week") or {}
    cards = data.get("cards") or {}
    rows = det["rows"]
    open_rows = [r for r in rows if r["bucket"] != "closed"]
    days = [d["date"] for d in data.get("days", [])]
    first_day, last_day = (days[0], days[-1]) if days else ("", "")
    where = f" · {data['circle']}" if data.get("circle") else ""

    def table(ws, r0: int, cols: list[str], widths: list[int] | None = None) -> None:
        ws.write_row(r0, 0, cols, head)
        for i, wdt in enumerate(widths or []):
            ws.set_column(i, i, wdt)

    # ---------------------------------------------------------------- Summary
    ws = wb.add_worksheet("Summary")
    ws.set_column(0, 0, 34)
    ws.set_column(1, 9, 15)
    ws.write(0, 0, f"Ticket Report – {w.get('code', '')}{where}", title)
    ws.write(1, 0, f"Week {_d(w.get('start'))} – {_d(w.get('end'))} · tickets generated on {', '.join(sorted({_d(d) for d in det['made'].values() if d})) or '—'}", note)
    ws.write(2, 0, f"Work counted from {_d(first_day)} to {_d(last_day)} (report of {_d(data.get('today'))})", note)
    r = 4
    ws.write(r, 0, "The week at a glance", sub)
    r += 1
    unique = len(rows)
    glance = [
        ("Tickets", det["tickets"]),
        ("GPs (each GP once)", unique),
        ("GPs achieved (target met)", sum(1 for x in rows if x["achieved"])),
        ("GPs waiting on a step", len(open_rows)),
        ("GPs with no Daily Achievement yet", sum(1 for x in rows if x["bucket"] == "not_filled")),
        ("Daily submissions (whole period)", cards.get("submissions", 0)),
        ("Non-Doable cases", cards.get("nonDoable", 0)),
        ("AMC converted", cards.get("amcConverted", 0)),
    ]
    for lbl, v in glance:
        ws.write(r, 0, lbl)
        ws.write(r, 1, v, big)
        r += 1
    r += 1
    ws.write(r, 0, "Where the GPs are now (each GP once)", sub)
    r += 1
    flow = [(k, lbl) for k, lbl in PENDING_BUCKETS]
    ws.write_row(r, 0, ["Step", *[lbl for _k, lbl in flow]], head)
    ws.write(r + 1, 0, "GPs")
    for j, (k, _l) in enumerate(flow, start=1):
        ws.write(r + 1, j, sum(1 for x in rows if x["bucket"] == k), num)
    r += 3
    ws.write(r, 0, "Who has to act now (one person per GP – most GPs first)", sub)
    r += 1
    steps = [k for k in ACTION if k != "closed"]
    step_lbl = dict(PENDING_BUCKETS)
    ws.write_row(r, 0, ["Work is pending with", "Role", "Login", "Last signed in", "GPs pending with them", "Waiting longest (days)", *[step_lbl[k] for k in steps]], head)
    for o in det["act"]:
        r += 1
        ws.write_row(r, 0, [o["who"], o["role"], o.get("login", ""), _d(o.get("lastLogin"), True) or ("Never" if o.get("login") == "Yes" else "—")])
        ws.write(r, 4, o["total"], big)
        ws.write(r, 5, o["oldest"], hot if o["oldest"] > OVERDUE_DAYS else num)
        for j, k in enumerate(steps, start=6):
            ws.write(r, j, o[k] or "", num)
    if not det["act"]:
        r += 1
        ws.write(r, 0, "Nobody – every GP is done.", note)
    r += 2
    if det["warnings"]:
        ws.write(r, 0, "Please note", sub)
        for t in det["warnings"]:
            r += 1
            ws.merge_range(r, 0, r, 9, "⚠ " + t, warn)
            ws.set_row(r, 32)
        r += 2
    ws.write(r, 0, "What the words mean", sub)
    for t in (
        f"Ticket IDs (last columns of GP Status, Returns and Completed): {HIER_NOTE}. Example: TKT-000123 → TKT-000123-FE-01 → TKT-000123-FE-01-FRT-001. '—' = the GP has no FE / no FRT team.",
        "Daily Achievement = the daily entry for a GP (category + remark + photo). Who fills it: the FRT team if it has a login, else the FE (if the FE has a login), else the AM.",
        "GP Status sheet: one row per GP – its team with their logins, 'Status now' (what happened to the GP) and 'Pending with' (whose hand the work is in, and why). Filter 'Status now' = NOT FILLED to see who has not filled.",
        "Dates on GP Status: the day of each step. A step done twice shows both days (e.g. FE filled on 24-Nov, 26-Nov) and 'Returned' tells why: 25-Nov: AM → FE (photo not clear). Empty = not done yet.",
        "Not filled = no Daily Achievement for the GP yet. It waits with its reporter only (never counted for the FE and the AM as well).",
        "FE verify → AM approval → SME → COH = the review steps after the entry. Achieved = the GP met its target (Ready for Letter / Letter submitted / AMC).",
        "Rectification Done / Ready for Letter / Revisit Required / Non-Doable / Letter Submission Done = the category chosen in the Daily Achievement.",
        "Waiting (days) = days since the last thing happened to the GP (its ticket's generation when nothing happened yet).",
    ):
        r += 1
        ws.merge_range(r, 0, r, 9, t, note)
        ws.set_row(r, 30)
    ws.freeze_panes(4, 0)

    # ---------------------------------------------------------------- GP Status – every GP once
    gs = wb.add_worksheet("GP Status")
    # read left to right: the GP – its team and who can sign in – where it stands – whose hand it is in, and why
    steps_d = [("fill_FRT", "FRT filled on"), ("fill_FE", "FE filled on"), ("fill_AM", "AM filled on"), ("FE_VERIFY", "FE verified on"),
               ("AM_APPROVE", "AM approved (sent on) on"), ("SME_FORWARD", "SME forwarded on"), ("COH_LETTER", "Letter submitted on"), ("COH_AMC", "AMC converted on")]
    gs.merge_range(0, 0, 0, 4, "GP", head)
    gs.merge_range(0, 5, 0, 10, "Team of the GP (and whether each has a login)", head)
    gs.write(0, 11, "Where the GP stands now", head)
    gs.merge_range(0, 12, 0, 16, "Work is pending with", head)
    gs.merge_range(0, 17, 0, 17 + len(steps_d) + 1, "Who did what, when (every date – a step done twice shows both dates)", head)
    cols = ["GP code", "GP name", "Circle", "BA", "Block", "AM", "AM login", "FE", "FE login", "FRT team", "FRT login", "Status now",
            "Pending with (name)", "Role", "Why with them", "Pending (days)", "Pending since",
            "Ticket generated on", *[lbl for _k, lbl in steps_d], "Returned (when: who → whom, why)"]
    gs_old = len(cols)
    cols += hier_heads  # ticket hierarchy: the AM / FE / FRT ticket IDs and target GPs (after every existing column)
    gs.merge_range(0, gs_old, 0, len(cols) - 1, "Ticket IDs and target GPs: AM → FE → FRT", head)
    table(gs, 1, cols, [10, 20, 12, 16, 14, 20, 9, 20, 9, 14, 9, 52, 24, 7, 52, 9, 12, 12, *[13] * len(steps_d), 46, *hier_widths])
    yes = wb.add_format({"font_color": "#15803D", "align": "center"})
    no = wb.add_format({"font_color": "#B91C1C", "bold": True, "align": "center"})
    nf = wb.add_format({"bold": True, "font_color": "#B91C1C"})
    for i, x in enumerate(rows, start=2):
        gs.write_row(i, 0, [x["gpCode"] or "", x["gpName"] or "", x["circle"], x["ba"], x["block"] or ""])
        for j, (name, login) in enumerate(((x["am"], x["amLogin"]), (x["fe"] or "No FE", x["feLogin"]), (x["frt"] or "No FRT team", x["frtLogin"]))):
            gs.write(i, 5 + 2 * j, name)
            if login:
                gs.write(i, 6 + 2 * j, login, yes if login == "Yes" else no)
        gs.write(i, 11, x["status"], nf if x["bucket"] == "not_filled" else None)
        done = x["bucket"] == "closed"
        gs.write_row(i, 12, ["—" if done else (x["who"] or ""), "" if done else (x["whoRole"] or ""), x["why"]])
        gs.write(i, 15, "" if done else x["days"], hot if not done and x["days"] > OVERDUE_DAYS else num)
        gs.write_row(i, 16, [_d(x["since"]), x["generated"], *[x["dates"][k] for k, _l in steps_d], x["returned"]])
        gs.write_row(i, gs_old, hier_values(hier.get(x["gpId"])))
    gs.freeze_panes(2, 2)
    if rows:
        gs.autofilter(1, 0, len(rows) + 1, len(cols) - 1)

    # ---------------------------------------------------------------- Team Activity – per person, every day
    ta = wb.add_worksheet("Team Activity")
    owner = {(o["role"], o["who"]): o for o in det["act"]}
    st_keys = [("A", "Rectification Done"), ("B", "Ready for Letter"), ("C", "Revisit Required"), ("D", "Non-Doable"), ("E", "Letter Submitted")]
    cols = ["Role", "Name / FRT team", "E-mail", "FE of the FRT team", "Login", "Last sign-in", "Last daily submission", "Tickets", "Ticket ID(s)", "GPs on their tickets",
            "Has to act on (GPs)", *[lbl for _k, lbl in st_keys], "Returned to them", *[_d(d)[:6] for d in days], "Days with work"]
    table(ta, 0, cols, [6, 26, 26, 20, 7, 17, 17, 8, 44, 10, 10, *[11] * len(st_keys), 9, *[7] * len(days), 9])
    own_ids = det.get("own") or []
    for i, p in enumerate(data.get("people", []), start=1):
        st = p.get("status") or {}
        who = p["name"]
        o = owner.get((p["role"], who)) or next((v for (rl, nm), v in owner.items() if rl == p["role"] and p.get("frtCodes") and nm in p["frtCodes"]), None)
        name = p["name"] + (f" ({', '.join(p['frtCodes'])})" if p.get("frtCodes") and p["account"] else "")
        cells = []
        for d in days:
            c = p["days"].get(d)
            cells.append((f"{c['gps']} GP" if c.get("gps") else f"{c.get('reviews', 0)} rev") if c else "")
        ta.write_row(i, 0, [p["role"], name, p.get("email") or "", ", ".join(p.get("fes") or []), "Yes" if p["account"] else "No",
                            _d(p.get("lastLogin"), True) or "Never signed in", _d(p.get("lastSubmission"), True) or "None yet",
                            p["tickets"], ", ".join(own_ids[i - 1]) if i - 1 < len(own_ids) and own_ids[i - 1] else "—", p["gps"], (o or {}).get("total", 0), *[st.get(k, 0) for k, _l in st_keys], p.get("returns", 0), *cells, p["activeDays"]])
    ta.freeze_panes(1, 2)
    if data.get("people"):
        ta.autofilter(0, 0, len(data["people"]), len(cols) - 1)

    # ---------------------------------------------------------------- AM Achievement
    am = wb.add_worksheet("AM Achievement")
    am_cols = ["Area Manager", "Login", "Circle", "Tickets", "GPs", "Achieved", "Achievement %", *[lbl for k, lbl in PENDING_BUCKETS if k != "closed"]]
    table(am, 0, am_cols, [24, 7, 14, 8, 8, 9, 12, *[12] * (len(PENDING_BUCKETS) - 1)])
    for i, a in enumerate(data.get("amAchievement") or [], start=1):
        am.write_row(i, 0, [a["name"], "Yes" if a.get("account") else "No", ", ".join(a["circles"]), a["tickets"], a["gps"], a["done"], a["pct"],
                            *[a["waiting"].get(k, 0) for k, _l in PENDING_BUCKETS if k != "closed"]])
    am.write(len(data.get("amAchievement") or []) + 2, 0, "A GP on two tickets counts on both of its tickets here (one row per ticket owner).", note)
    am.freeze_panes(1, 1)

    # ---------------------------------------------------------------- Returns
    rt = wb.add_worksheet("Returns")
    table(rt, 0, ["When", "GP code", "GP name", "Block", "Returned by", "By role", "Returned to", "To role", "Reason (remark)", *hier_heads], [17, 10, 20, 14, 20, 8, 20, 8, 50, *hier_widths])
    ret = (data.get("returns") or {}).get("items", [])
    for i, x in enumerate(ret, start=1):
        rt.write_row(i, 0, [_d(x["at"], True), x["gpCode"] or "", x["gpName"] or "", x["block"] or "", x["by"] or "", x["byRole"] or "",
                            x["to"] or "", x["toRole"] or "", x["remark"] or "", *hier_values(hier.get(x.get("gpId")))])
    if not ret:
        rt.write(1, 0, "No GP of this week was returned.", note)

    # ---------------------------------------------------------------- Completed
    cp = wb.add_worksheet("Completed")
    table(cp, 0, ["When", "What", "GP code", "GP name", "Block", "By", "Role", *hier_heads], [17, 24, 10, 20, 14, 20, 8, *hier_widths])
    done = data.get("completed", [])
    for i, c in enumerate(done, start=1):
        cp.write_row(i, 0, [_d(c["at"], True), LABEL.get(c["what"], c["what"]), c["gpCode"] or "", c["gpName"] or "", c["block"] or "", c["by"] or "", c["byRole"] or "", *hier_values(hier.get(c.get("gpId")))])
    if not done:
        cp.write(1, 0, f"No GP was completed between {_d(first_day)} and {_d(last_day)}.", note)
    wb.close()
    return buf.getvalue()
