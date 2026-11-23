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


def _weeks(db: Session) -> list[dict[str, Any]]:
    """Ticket weeks that have live tickets, newest first: code, start, end, number of tickets."""
    rows = db.execute(
        select(TicketTask.week_code, TicketTask.week_start, TicketTask.week_end, Ticket.id).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None))
    ).all()
    by: dict[tuple[str, dt.date, dt.date], int] = defaultdict(int)
    for code, start, end, _tid in rows:
        by[(code, start, end)] += 1
    return [{"code": c, "start": s.isoformat(), "end": e.isoformat(), "tickets": n} for (c, s, e), n in sorted(by.items(), key=lambda kv: kv[0][1], reverse=True)]


def _pick_week(weeks: list[dict[str, Any]], code: str | None) -> dict[str, Any] | None:
    if code:
        return next((w for w in weeks if w["code"] == code), None)
    today = _local_date(dt.datetime.now(dt.UTC))
    current = next((w for w in weeks if w["start"] <= today.isoformat() <= w["end"]), None)
    return current or (weeks[0] if weeks else None)


def build(db: Session, week: str | None = None, circle: str | None = None) -> dict[str, Any]:
    weeks = _weeks(db)
    w = _pick_week(weeks, week)
    if w is None:
        return {"week": None, "weeks": weeks, "circles": [], "cards": None, "roles": [], "days": [], "people": [], "completed": [], "trend": [], "returns": {"items": [], "top": []}, "amAchievement": []}
    start, end = dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"])
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    today = _local_date(dt.datetime.now(dt.UTC))

    # ---------------------------------------------------------------- the week's tickets (generated)
    week_tasks = [(k, t) for k, t in db.execute(select(TicketTask, Ticket).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None), TicketTask.week_code == w["code"]))]
    circles = sorted({k.circle for k, _t in week_tasks if k.circle})
    if circle:
        week_tasks = [(k, t) for k, t in week_tasks if (k.circle or "") == circle]
    tids = [t.id for _k, t in week_tasks]
    task_of = {t.id: k for k, t in week_tasks}
    # the day each ticket was generated – nobody can submit on a ticket before it exists
    made_on = {t.id: _local_date(t.created_at) for _k, t in week_tasks}

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
    sub_tids = {t.id for _s, t in subs}
    if circle and sub_tids:
        circle_of = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_(sub_tids)))}
        subs = [(s, t) for s, t in subs if (circle_of.get(t.id) or "") == circle]
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
    if circle and rev_rows:
        circ_of = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_({r[5] for r in rev_rows})))}
        rev_rows = [r for r in rev_rows if (circ_of.get(r[5]) or "") == circle]
    for uid, uname, role, act, at, _tid in rev_rows:
        if uid is None or role not in ("FE", "AM") or not (start <= (_local_date(at) or start) <= end):
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
    if circle and completed:
        circ = {k.ticket_id: k.circle for k in db.scalars(select(TicketTask).where(TicketTask.ticket_id.in_({c["ticketId"] for c in completed})))}
        completed = [c for c in completed if (circ.get(c["ticketId"]) or "") == circle]
    gp_rows = {g.id: g for g in db.scalars(select(TicketTaskGp).where(TicketTaskGp.id.in_({c["gpId"] for c in completed})))} if completed else {}
    completed.sort(key=lambda c: c["at"], reverse=True)
    completed_out = [
        {"gpCode": gp_rows[c["gpId"]].gp_code if c["gpId"] in gp_rows else None, "gpName": gp_rows[c["gpId"]].gp_name if c["gpId"] in gp_rows else None,
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
            "at": _utc(x.at).isoformat(), "gpCode": g.gp_code, "gpName": g.gp_name, "block": g.block, "ticketId": t.id, "ticket": t.code,
            "by": x.actor_name, "byRole": x.role, "to": to, "toRole": to_role, "frtCode": g.frt_code if to_role == "FRT" else None, "remark": x.remark,
        })
    ret_items.sort(key=lambda r: r["at"], reverse=True)
    ret_top: dict[tuple[str, str], int] = defaultdict(int)
    for r in ret_items:
        ret_top[(r["toRole"], r["to"])] += 1
    pending = _pending(db, week_tasks, gps, today)
    bucket_of = {it["gpId"]: it["bucket"] for it in pending["items"]}
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
    return {
        "week": w, "weeks": weeks, "circles": circles, "circle": circle, "today": today.isoformat(), "cards": cards, "roles": role_rows,
        "returns": {"items": ret_items, "top": [{"role": r, "name": n, "count": c} for (r, n), c in sorted(ret_top.items(), key=lambda kv: (-kv[1], kv[0][1].lower()))]},
        "amAchievement": am_rows,
        "days": [{"date": d.isoformat(), "future": d > today} for d in days], "people": people_out, "completed": completed_out,
        "completedTotal": len(completed), "trend": _trend(db, weeks, circle),
        "pending": pending,
    }


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
        })
    counts = defaultdict(int)
    overdue = defaultdict(int)
    for it in items:
        counts[it["bucket"]] += 1
        if it["bucket"] != "closed" and it["days"] > OVERDUE_DAYS:
            overdue[it["bucket"]] += 1
    items.sort(key=lambda it: (it["bucket"] == "closed", -it["days"], it["gpCode"] or ""))
    return {"buckets": [{"key": k, "label": lbl, "count": counts[k], "overdue": overdue[k]} for k, lbl in PENDING_BUCKETS], "items": items, "overdueDays": OVERDUE_DAYS}


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


def _trend(db: Session, weeks: list[dict[str, Any]], circle: str | None) -> list[dict[str, Any]]:
    """The last ticket weeks (oldest first): tickets generated, their GPs, achieved GPs."""
    out = []
    for w in reversed(weeks[:TREND_WEEKS]):
        q = select(TicketTask.ticket_id).join(Ticket, Ticket.id == TicketTask.ticket_id).where(Ticket.deleted_at.is_(None), TicketTask.week_code == w["code"])
        if circle:
            q = q.where(TicketTask.circle == circle)
        tids = list(db.scalars(q))
        gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id.in_(tids)))) if tids else []
        out.append({"week": w["code"], "tickets": len(tids), "gps": len(gps), "done": sum(1 for g in gps if cumulative(g) >= g.target)})
    return out


LABEL = {"DONE": "Done (achieved)", "LETTER_SUBMITTED": "Letter submitted (done)", "AMC_CONVERTED": "AMC converted", "ND_APPROVED": "Non-Doable approved"}


def xlsx(data: dict[str, Any]) -> bytes:
    """The report as an Excel workbook: Summary (per role), Daily tracker, Completed."""
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    head = wb.add_format({"bold": True, "bg_color": "#0F766E", "font_color": "#FFFFFF", "border": 1})
    bold = wb.add_format({"bold": True})
    w = data.get("week") or {}
    ws = wb.add_worksheet("Summary")
    ws.write(0, 0, f"Ticket Report – {w.get('code', '')} ({w.get('start', '')} – {w.get('end', '')})" + (f" · {data['circle']}" if data.get("circle") else ""), bold)
    cards = data.get("cards") or {}
    for i, (k, lbl) in enumerate((("tickets", "Tickets generated"), ("gps", "GPs"), ("done", "GPs achieved"), ("amcConverted", "AMC converted"), ("nonDoable", "Non-Doable cases"), ("submissions", "Daily submissions"))):
        ws.write(2 + i, 0, lbl)
        ws.write(2 + i, 1, cards.get(k, 0))
    r0 = 10
    cols = ["Role", "People", "Tickets", "GPs", "Achieved", "Pending", "Daily submissions", "People who submitted", "Reviews (SME / COH)"]
    ws.write_row(r0, 0, cols, head)
    for i, r in enumerate(data.get("roles", []), start=r0 + 1):
        ws.write_row(i, 0, [r["role"], r["people"], r["tickets"], r["gps"], r["done"], r["pending"], r["submissions"], r["activePeople"], r.get("reviewed", "")])
    ws.set_column(0, 0, 22)
    ws.set_column(1, 8, 16)
    days = [d["date"] for d in data.get("days", [])]
    tr = wb.add_worksheet("Daily tracker")
    st_cols = ["Rectification Done", "Ready for Letter", "Revisit Required", "Non-Doable", "Letter Submitted", "Not filled"]
    tr.write_row(0, 0, ["Role", "FE (FRT)", "Name / FRT code", "Circle", "Login", "Last sign-in", "Last submission", "Tickets", "GPs", "Achieved", *st_cols, "Returns", *days, "Days submitted"], head)
    for i, p in enumerate(data.get("people", []), start=1):
        cells = [(f"{p['days'][d]['gps']} GP" if d in p["days"] else "–") for d in days]
        st = p.get("status") or {}
        name = p["name"] + (f" ({', '.join(p['frtCodes'])})" if p.get("frtCodes") and p["account"] else "")
        tr.write_row(i, 0, [p["role"], ", ".join(p.get("fes") or []), name, ", ".join(p["circles"]), "Yes" if p["account"] else "No",
                            (p.get("lastLogin") or "never")[:16].replace("T", " "), (p.get("lastSubmission") or "never")[:16].replace("T", " "),
                            p["tickets"], p["gps"], p["done"], *[st.get(k, 0) for k in ("A", "B", "C", "D", "E", "none")], p.get("returns", 0), *cells, p["activeDays"]])
    tr.set_column(0, 0, 8)
    tr.set_column(1, 1, 26)
    tr.set_column(2, 5 + len(days) + 1, 12)
    pw = wb.add_worksheet("Pending with")
    pw.write_row(0, 0, ["Waiting at", "Stage", "With", "Role", "Days waiting", "Since", "GP code", "GP name", "Block", "Ticket"], head)
    label_of = {k: lbl for k, lbl in PENDING_BUCKETS}
    for i, it in enumerate((data.get("pending") or {}).get("items", []), start=1):
        pw.write_row(i, 0, [label_of.get(it["bucket"], it["bucket"]), it["stage"] or "", it["who"] or "", it["whoRole"] or "", it["days"], (it["since"] or "")[:10],
                            it["gpCode"] or "", it["gpName"] or "", it["block"] or "", it["ticket"] or ""])
    pw.set_column(0, 9, 18)
    am = wb.add_worksheet("AM achievement")
    am.write_row(0, 0, ["Area Manager", "Circle", "Tickets", "GPs", "Achieved", "Achievement %", *[lbl for k, lbl in PENDING_BUCKETS if k != "closed"]], head)
    for i, a in enumerate(data.get("amAchievement") or [], start=1):
        am.write_row(i, 0, [a["name"], ", ".join(a["circles"]), a["tickets"], a["gps"], a["done"], a["pct"], *[a["waiting"].get(k, 0) for k, _l in PENDING_BUCKETS if k != "closed"]])
    am.set_column(0, 1, 24)
    am.set_column(2, 13, 14)
    rt = wb.add_worksheet("Returns")
    rt.write_row(0, 0, ["When", "GP code", "GP name", "Block", "Ticket", "Returned by", "By role", "Returned to", "To role", "Reason (remark)"], head)
    for i, x in enumerate((data.get("returns") or {}).get("items", []), start=1):
        rt.write_row(i, 0, [x["at"][:16].replace("T", " "), x["gpCode"] or "", x["gpName"] or "", x["block"] or "", x["ticket"] or "", x["by"] or "", x["byRole"] or "",
                            x["to"] or "", x["toRole"] or "", x["remark"] or ""])
    rt.set_column(0, 8, 16)
    rt.set_column(9, 9, 50)
    cp = wb.add_worksheet("Completed")
    cp.write_row(0, 0, ["When", "What", "GP code", "GP name", "Block", "Ticket", "By", "Role"], head)
    for i, c in enumerate(data.get("completed", []), start=1):
        cp.write_row(i, 0, [c["at"] or "", LABEL.get(c["what"], c["what"]), c["gpCode"] or "", c["gpName"] or "", c["block"] or "", c["ticket"] or "", c["by"] or "", c["byRole"] or ""])
    cp.set_column(0, 7, 18)
    wb.close()
    return buf.getvalue()
