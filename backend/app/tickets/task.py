"""GP-wise weekly task of a ticket: the Area Manager's GPs to convert in a week, the assignment workbook and the
Area Manager's daily progress.

Area Manager      Escalation Matrix (latest upload; the master data's AM Name when there is none) – same mapping as
                  AMC Conversion → Area manager tables (amc_plan._am_names). The ticket goes to the dashboard user whose
                  e-mail is the Area Manager's e-mail in the matrix (no e-mail match = no ticket).
GPs of the task   the AM's GPs of the GP-wise AMC plan with a Planned Date in the selected week (WEEK) – the week's
                  target only. GPs planned before the week and not achieved (no AMC Date before the week starts) are the
                  BACKLOG: counted for information in the preview (never in the target, never in the ticket). Tickets
                  created before this rule may still hold such GPs (kind PENDING) – they are kept unchanged.
Target            1 per GP (one GP to convert) – fixed at creation, never edited
Already achieved  AMC Date filled in the master data at creation (same rule as "GP Achieved" on AMC Conversion)
Daily progress    the Area Manager / FE classifies each GP (CATEGORIES A–E), writes remarks and may attach proof
                  documents per GP; every submission is its own record (ticket_progress / _lines / _files – never
                  overwritten). The GP keeps ONE current category (ticket_task_gps.gp_category): choosing another one
                  replaces it (no duplicate counting), the line keeps the history. Only E "Letter Submission Done" counts
                  as achieved (reported = 1); any other category = not achieved by the user (reported = 0).
                  Cumulative = min(target, already achieved + reported); remaining gap = target − cumulative.
                  (The older Done / Pending form – status / achievedToday – is still accepted by the API.)
GP status         Done = cumulative has reached the target (AMC Date in the master data, or marked Done), else Pending.
                  The status of a history line is the GP's status right after that submission.
Field Engineer    Escalation Matrix "FE Name" + "FE Email ID" of each GP (snapshot on the task GP at creation). An FE
                  recipient of a ticket sees, reports and downloads ONLY the GPs mapped to them (same FE name and the
                  same matrix FE e-mail under that Area Manager); the Area Manager, CBH, SME and admins see every GP of
                  the ticket. A GP without an FE in the matrix is never given to an FE (counted as "FE not mapped").
No Area Manager    GPs whose matrix AM is blank or "Vacant…" form the circle's NO_AM group: their FEs are listed under it
                  (never hidden), and the admin can give the group to an acting Area Manager typed at Generate Ticket
                  (gp_source "NO_AM"), add it to an Area Manager of the matrix ("AM+NO_AM"), or send it FE-wise. Nothing
                  is fixed per circle – a matrix with the AM moves the GPs to that AM for the next tickets.
Zero target       an Area Manager / FE without a GP planned in the week still gets the ticket (0 GPs; the FE can add
                  GPs found in the field) – it is never refused.
FRT team          Escalation Matrix "FRT Code" of each GP (snapshot on the task GP at creation). A dashboard account with
                  that FRT code (User Management) is put on the ticket as FRT: it sees and reports ONLY the GPs with its
                  code – Daily Achievement A Rectification Done / C Revisit Required with the same remark + photo – and
                  that goes to the GP's FE (frt_stage PENDING_FE), not to the Area Manager. The FE checks the FRT's
                  proof and remark: FE_VERIFY sends the GP to the Area Manager (FE_VERIFIED – the review chain starts
                  as before), FE_RETURN sends it back to the FRT (RETURNED_FRT). A GP the Area Manager returns goes to
                  the FE, who sends it back to the FRT. Non-Doable (D) by the FRT opens a case with the FRT (E1 / E2
                  optional) that the FE reviews and completes before the AM (app.tickets.nondoable). The FE reports
                  nothing on such a GP once the FRT reported it – only Verify / Return; while the FRT has reported
                  nothing (no FRT stage) the FE may report it itself, straight to the Area Manager. A GP without an
                  FRT account on the ticket is reported by the FE exactly as before (tickets created earlier too).
Nothing here closes a ticket – only an admin does (service.close).
"""

from __future__ import annotations

import datetime as dt
import io
import re
import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics.amc_plan import NOT_ASSIGNED, VACANT, _am_names
from ..analytics.store import Store
from ..config import get_settings
from ..models import Ticket, TicketProgress, TicketProgressFile, TicketProgressLine, TicketTask, TicketTaskGp, User
from ..security.deps import CurrentUser
from . import files
from .directory import split_emails

MAX_REMARK = 500
MAX_GP_FILES = 5  # proof documents per GP in one daily submission
MAX_PROGRESS_FILES = 50  # proof documents in one daily submission (all GPs)
# Daily Achievement evidence: a GP line that sets / changes the achievement (category, or the older Done / Pending), or
# sends a returned GP back to the Area Manager, needs a remark AND at least one photo (JPG / PNG) in the same submission
MIN_REMARK = 3
PHOTO_EXTS = (".jpg", ".jpeg", ".png")
EVIDENCE_MSG = "Daily Achievement needs a remark (at least 3 characters) and at least one photo (JPG / PNG) of the work in the same submission"

# GP classification of the daily progress (code -> label); only ACHIEVED_CATEGORY counts as achieved
CATEGORIES: dict[str, str] = {
    "A": "Rectification Done",
    "B": "Ready for Letter Submission",
    "C": "Revisit Required",
    "D": "Non-Doable – Proposed",
    "E": "Letter Submission Done",
}
ACHIEVED_CATEGORY = "E"
NO_AM = "No Area Manager"  # the circle's GPs whose matrix AM is blank / "Vacant…" (one group per circle)
# FRT team: what the FRT may choose (Non-Doable – Proposed stays with the FE) and the FRT → FE steps before the AM
FRT_CATEGORIES = ("A", "C", "D")  # D opens a Non-Doable case with the FRT (E1 / E2 optional), then the FE reviews it
FRT_OPEN = ("PENDING_FE", "RETURNED_FRT")  # not yet verified by the FE – the Area Manager cannot act on the GP
FRT_STAGE_LABEL = {"PENDING_FE": "Pending FE Verification (FRT submitted)", "RETURNED_FRT": "Returned to FRT by FE"}
FE_STEPS = {"FE_VERIFY": "Verified by FE – sent to the Area Manager", "FE_RETURN": "Returned to FRT by FE"}


def frt_norm(v: Any) -> str | None:
    """FRT code as compared everywhere: spaces collapsed, upper case; blank / "0" / "Vacant…" = no FRT."""
    from ..analytics.escalation import is_vacant

    t = _text(v)
    return None if t is None or t == "0.0" or is_vacant(t) else t.upper()[:60]


def category_label(code: str | None) -> str | None:
    return CATEGORIES.get(code) if code else None


class TaskError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _d(v: Any) -> dt.date | None:
    return v if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else (v.date() if isinstance(v, dt.datetime) else None)


def _text(v: Any) -> str | None:
    return " ".join(v.split()) if isinstance(v, str) and v.strip() and v.strip() != "0" else None


def _mail(v: Any) -> str | None:
    return v.strip().lower() if isinstance(v, str) and "@" in v else None


def fe_label(v: Any) -> str | None:
    """FE name of the matrix; blank, "0" and "Vacant…" = no FE mapped."""
    from ..analytics.escalation import is_vacant

    t = _text(v)
    return None if t is None or t == "0.0" or is_vacant(t) else t


def _directory(store: Store) -> tuple[pd.DataFrame, str]:
    """Per GP: area manager, AM e-mail, business area, Field Engineer and FE e-mail (Escalation Matrix first, master
    data otherwise – the master data has no FE)."""
    g = store.gps
    names, source, _file, esc = _am_names(store, g.index)

    def col(name: str) -> pd.Series:
        return esc[name] if esc is not None and name in esc.columns else pd.Series(None, index=g.index, dtype=object)

    ba = col("ba")
    ba = ba.where(ba.notna(), g["ba"] if "ba" in g.columns else None)
    return pd.DataFrame(
        {"am": names, "email": col("am_email").map(_mail), "ba": ba, "fe": col("fe_name").map(fe_label), "fe_email": col("fe_email").map(_mail), "frt": col("frt_code").map(frt_norm)},
        index=g.index,
    ), source


def _grouped(d: pd.DataFrame) -> pd.DataFrame:
    """The directory with every GP without an Area Manager (blank / "Vacant…") under NO_AM."""
    return d.assign(am=d["am"].where(~d["am"].isin([NOT_ASSIGNED, VACANT]), NO_AM))


def fe_key(name: Any, mail: Any) -> tuple[str, str]:
    from ..analytics.escalation import person_key

    return (person_key(name) or "", (mail or "").strip().lower() if isinstance(mail, str) else "")


@dataclass(frozen=True)
class FeScope:
    """One Field Engineer's part of a task: the GPs whose matrix FE name (case / spaces ignored) and FE e-mail match."""

    name: str
    mail: str | None

    def key(self) -> tuple[str, str]:
        return fe_key(self.name, self.mail)

    def owns(self, g: Any) -> bool:
        return g.fe_name is not None and fe_key(g.fe_name, g.fe_email) == self.key()


def fe_owner_keys(db: Session, t: Ticket) -> set[tuple[str, str]]:
    """FE keys of the Field Engineers who work on this ticket with a dashboard account: their GPs are reported by them
    only (the Area Manager reviews them). GPs without such an FE stay with the Area Manager."""
    from ..models import TicketRecipient

    rs = db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE", TicketRecipient.user_id.is_not(None), TicketRecipient.can_work.is_(True)))
    return {FeScope(r.name, r.fe_mail).key() for r in rs}


def fe_assigned(g: Any, keys: set[tuple[str, str]]) -> bool:
    return g is not None and g.fe_name is not None and fe_key(g.fe_name, g.fe_email) in keys


@dataclass(frozen=True)
class FrtScope:
    """One FRT team's part of a task: the GPs whose FRT code (Escalation Matrix, at creation) is the account's code."""

    code: str
    name: str

    def owns(self, g: Any) -> bool:
        return g is not None and frt_norm(g.frt_code) == self.code


def frt_owner_codes(db: Session, t: Ticket) -> set[str]:
    """FRT codes with a working FRT account on this ticket: their GPs are reported by the FRT and verified by the FE."""
    from ..models import TicketRecipient

    rs = db.scalars(select(TicketRecipient.frt_code).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FRT", TicketRecipient.user_id.is_not(None), TicketRecipient.can_work.is_(True)))
    return {c for c in (frt_norm(x) for x in rs) if c}


def frt_assigned(g: Any, codes: set[str]) -> bool:
    return g is not None and frt_norm(g.frt_code) in codes if codes else False


def frt_stage_open(g: Any) -> bool:
    """The FRT's Daily Achievement is not verified by the FE yet (the Area Manager waits)."""
    return g is not None and g.frt_stage in FRT_OPEN and g.review in (None, "RETURNED")


def _is_photo(u: Any) -> bool:
    from pathlib import Path

    return Path(files.clean_name(getattr(u, "file_name", None))).suffix.lower() in PHOTO_EXTS


def scope_of(db: Session, t: Ticket, user: CurrentUser) -> FeScope | FrtScope | None:
    """The FE / FRT part a user may see of this ticket: None = the whole ticket (admins, Area Manager, CBH, SME, others)."""
    if user.is_admin:
        return None
    from ..models import TicketRecipient

    r = db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id).limit(1)).first()
    if r is not None and r.role == "FRT":
        code = frt_norm(r.frt_code)
        return FrtScope(code, r.name) if code else FrtScope("\0", r.name)  # no code = no GP (never the whole ticket)
    return FeScope(r.name, r.fe_mail) if r is not None and r.role == "FE" else None


@dataclass(frozen=True)
class ReviewerView:
    """An SME's / COH's part of a task: only the GPs handed to them in the review chain (ticket_gp_forwards) – the SME
    the GPs the Area Manager approved and forwarded to them, the COH the GPs the SME reviewed and forwarded to them.
    Steps made before forwards were recorded (no forward row for that step at all) stay visible to the ticket's
    SMEs / COHs, as before. kind = SME | COH (SME when the user is both)."""

    ids: frozenset[int]
    kind: str = "SME"

    def owns(self, g: Any) -> bool:
        return g is not None and g.id in self.ids


SmeView = ReviewerView  # the SME view came first; same class

# the review step that hands a GP to each reviewer role, and the GP's review states from that step on (a GP moved to
# the Non-Doable workflow afterwards has its review reset – it is then handled on the Non-Doable Cases page, not here)
HANDED_BY = {"SME": "AM_APPROVE", "COH": "SME_FORWARD"}
STAGES_FROM = {
    # SME_RETURNED / COH_RETURNED: sent back (by them / to them) – still shown, read-only resp. to act on again
    "SME": ("AM_APPROVED", "SME_RETURNED", "SME_FORWARDED", "COH_RETURNED", "LETTER_SUBMITTED", "AMC_CONVERTED"),
    "COH": ("SME_FORWARDED", "COH_RETURNED", "LETTER_SUBMITTED", "AMC_CONVERTED"),
}


def reviewer_view(db: Session, t: Ticket, user: CurrentUser) -> ReviewerView | None:
    """The GP filter of a user who is on this ticket ONLY as SME and / or COH (None = not such a user: admins, the
    assigned Area Manager and anybody with another role on the ticket keep their existing view)."""
    if user.is_admin or t.assignee_id == user.id:
        return None
    from ..models import TicketGpForward, TicketGpReview, TicketRecipient

    recs = db.execute(select(TicketRecipient.id, TicketRecipient.role).where(TicketRecipient.ticket_id == t.id, TicketRecipient.user_id == user.id)).all()
    roles = {r.role for r in recs}
    if not recs or not roles <= set(HANDED_BY):
        return None
    mine = {r.id for r in recs}
    state = dict(db.execute(select(TicketTaskGp.id, TicketTaskGp.review).where(TicketTaskGp.ticket_id == t.id)).all())
    ids: set[int] = set()
    for role in roles:
        # only the LATEST handing step of each GP counts: a GP the AM approves again for another SME (after the SME
        # sent it back) is that SME's, no longer the first one's
        latest: dict[int, int] = {}
        for rid, gp in db.execute(select(TicketGpReview.id, TicketGpReview.task_gp_id).where(TicketGpReview.ticket_id == t.id, TicketGpReview.action == HANDED_BY[role]).order_by(TicketGpReview.id)):
            latest[gp] = rid
        to: dict[int, set[int]] = {}  # handing step -> recipient ids
        for rid, rec in db.execute(select(TicketGpForward.review_id, TicketGpForward.recipient_id).where(TicketGpForward.ticket_id == t.id, TicketGpForward.role == role)):
            to.setdefault(rid, set()).add(rec)
        for gp, rid in latest.items():
            sent = to.get(rid)
            mine_now = (sent is None) or bool(sent & mine)  # no forward row = handed on before forwards were recorded
            if mine_now and state.get(gp) in STAGES_FROM[role]:  # only while the GP is (still) at / past that stage
                ids.add(gp)
    return ReviewerView(frozenset(ids), "SME" if "SME" in roles else "COH")


sme_view = reviewer_view  # used by review.apply: an SME / COH acts only on the GPs handed to them


def view_of(db: Session, t: Ticket, user: CurrentUser) -> FeScope | FrtScope | ReviewerView | None:
    """What a user may SEE of a task (detail, proof documents, workbooks): a Field Engineer their GPs, an SME / COH the
    GPs forwarded to them, everyone else the whole task. (Daily progress keeps using scope_of – FE or Area Manager.)"""
    return scope_of(db, t, user) or reviewer_view(db, t, user)


def area_managers(db: Session, store: Store, week_code: str) -> dict[str, Any]:
    """Area Managers a task can be built for, with their GP counts for the week and the matching dashboard user."""
    w = store.week(week_code)
    d, source = _directory(store)
    users = {u.email.lower(): u for u in db.scalars(select(User).where(User.is_active.is_(True)))}
    rows = _task_rows(store, d, None, w.start, w.end)
    out = []
    for am, part in d.groupby("am"):
        if am in (NOT_ASSIGNED, VACANT):
            continue
        emails = sorted({e for v in part["email"] for e in split_emails(v)})
        user = next((users[e] for e in emails if e in users), None)
        mine = rows[rows["am"] == am]
        out.append(
            {
                "name": am,
                "emails": emails,
                "circles": sorted({str(c).title() for c in store.gps.loc[part.index, "circle"]}),
                "businessAreas": sorted({str(b).title() for b in part["ba"] if _text(b)}),
                "gps": len(part),
                "weekGps": int((mine["kind"] == "WEEK").sum()),
                "pendingGps": int((mine["kind"] == "PENDING").sum()),
                "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
            }
        )
    out.sort(key=lambda x: x["name"].lower())
    return {"week": {"id": w.code, "label": f"Week {w.number}", "start": w.start.isoformat(), "end": w.end.isoformat()}, "source": source, "areaManagers": out}


def _task_rows(store: Store, d: pd.DataFrame, am: str | None, start: dt.date, end: dt.date) -> pd.DataFrame:
    """GP rows of the plan that belong to a task of the week (all AMs when am is None)."""
    p = store.amc_plan
    cols = ["am", "kind", "planned", "ready", "amc", "category", "fe", "fe_email", "frt"]
    if p.empty:
        return pd.DataFrame(columns=cols)
    amc = store.gps["amc_date"].reindex(p.index)
    none = pd.Series(None, index=p.index, dtype=object)
    frame = pd.DataFrame(
        {
            "am": d["am"].reindex(p.index), "planned": p["planned_date"].map(_d), "ready": p["ach_date"].map(_d), "amc": amc.map(_d), "category": p["category"],
            "fe": d["fe"].reindex(p.index) if "fe" in d.columns else none, "fe_email": d["fe_email"].reindex(p.index) if "fe_email" in d.columns else none,
            "frt": d["frt"].reindex(p.index) if "frt" in d.columns else none,
        },
        index=p.index,
    )
    if am is not None:
        frame = frame[frame["am"] == am]
    week = frame["planned"].map(lambda v: v is not None and start <= v <= end)
    pending = frame.apply(lambda r: r["planned"] is not None and r["planned"] < start and (r["amc"] is None or r["amc"] >= start), axis=1) if len(frame) else week
    frame = frame[week | pending].copy()
    frame["kind"] = ["WEEK" if w_ else "PENDING" for w_ in week[week | pending]]
    return frame[cols]


def _in_circle(store: Store, idx: pd.Index, circle: str | None) -> pd.Index:
    if not circle:
        return idx
    key = " ".join(circle.split()).lower()
    return idx[[" ".join(str(c).split()).lower() == key for c in store.gps.loc[idx, "circle"]]]


def circle_counts(store: Store, am: str, circle: str, week_code: str) -> dict[str, int]:
    """GPs of an Area Manager in one circle, and how many of them are this week's / pending task GPs."""
    w = store.week(week_code)
    d = _grouped(_directory(store)[0])
    mine = _in_circle(store, d.index[d["am"] == am], circle)
    rows = _task_rows(store, d, am, w.start, w.end)
    rows = rows.loc[rows.index.isin(mine)]
    return {"gps": len(mine), "weekGps": int((rows["kind"] == "WEEK").sum()), "pendingGps": int((rows["kind"] == "PENDING").sum())}


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) else None


def fe_slots(store: Store, circle: str | None, week_code: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Field Engineers of a circle, one per (Area Manager, FE name, matrix FE e-mail) – the GPs mapped to each, with
    the week's task GP counts – and per Area Manager the week's task GPs that have no FE in the matrix. FEs of GPs
    without an Area Manager are listed under NO_AM (never left out)."""
    w = store.week(week_code)
    d = _grouped(_directory(store)[0])
    if "fe" not in d.columns:
        return [], {}
    d = d.loc[_in_circle(store, d.index, circle)]
    rows = _task_rows(store, d, None, w.start, w.end)
    rows = rows.loc[rows.index.isin(d.index)]
    slots: dict[tuple[str, str, str], dict[str, Any]] = {}
    for am, fe, mail in zip(d["am"], d["fe"], d["fe_email"]):
        if not isinstance(fe, str):
            continue
        s = slots.setdefault((am, *fe_key(fe, mail)), {"name": fe, "am": am, "mappedEmail": _str(mail), "emails": split_emails(mail), "gps": 0, "weekGps": 0, "pendingGps": 0})
        s["gps"] += 1
    unmapped: dict[str, int] = {}
    for am, fe, mail, kind in zip(rows["am"], rows["fe"], rows["fe_email"], rows["kind"]):
        if not isinstance(fe, str):
            if kind == "WEEK":  # the week's target GPs without an FE
                unmapped[am] = unmapped.get(am, 0) + 1
            continue
        s = slots.get((am, *fe_key(fe, mail)))
        if s is not None:
            s["weekGps" if kind == "WEEK" else "pendingGps"] += 1
    return sorted(slots.values(), key=lambda s: (s["am"].lower(), s["name"].lower(), s["mappedEmail"] or "")), unmapped


def preview(
    store: Store, am: str, week_code: str, circle: str | None = None, fes: list[FeScope] | None = None, backlog: bool = False, with_no_am: bool = False
) -> list[dict[str, Any]]:
    """The task GPs of an Area Manager: Planned Date in the week (only that AM's GPs; only the selected circle's when
    one is given; only the GPs of these Field Engineers when `fes` is given). backlog=True: the backlog GPs instead
    (planned before the week, not achieved) – information only, never part of a ticket.
    am = NO_AM: the circle's GPs without an Area Manager (circle required). with_no_am: the AM's GPs plus those."""
    w = store.week(week_code)
    d = _grouped(_directory(store)[0])
    if (am == NO_AM or with_no_am) and not circle:
        raise TaskError(422, "Select the circle – the GPs without an Area Manager are taken per circle")
    if (am == NO_AM or with_no_am) and not len(_in_circle(store, d.index[d["am"] == NO_AM], circle)):
        raise TaskError(422, f"Every GP of {circle} has an Area Manager in the Escalation Matrix – select the Area Manager from the list")
    if am not in set(d["am"]) or am in (NOT_ASSIGNED, VACANT):
        raise TaskError(422, "Unknown Area Manager")
    if with_no_am and am != NO_AM:
        d = d.assign(am=d["am"].replace(NO_AM, am))  # the circle's GPs without an AM join this AM (cut to the circle below)
    rows = _task_rows(store, d, am, w.start, w.end)
    rows = rows[rows["kind"] == ("PENDING" if backlog else "WEEK")]
    rows = rows.loc[rows.index.isin(_in_circle(store, rows.index, circle))]
    if fes is not None:
        keys = {f.key() for f in fes}
        mask = [isinstance(fe, str) and fe_key(fe, mail) in keys for fe, mail in zip(rows["fe"], rows["fe_email"])]
        rows = rows.loc[pd.Series(mask, index=rows.index, dtype=bool)]  # a boolean mask, also when empty ([] would pick columns)
    g = store.gps.loc[rows.index]
    out = []
    for i, (code, r) in enumerate(rows.sort_values(["kind", "planned"], ascending=[False, True]).iterrows(), start=1):
        gp = g.loc[code]
        base = 1 if r["amc"] is not None and r["amc"] <= store.data_as_of else 0
        out.append(
            {
                "sort": i,
                "gpCode": str(code),
                "gpName": str(gp["name"]).title(),
                "circle": str(gp["circle"]).title(),
                "businessArea": (_text(d.at[code, "ba"]) or "").title() or None,
                "district": str(gp["district"]).title() if _text(gp["district"]) else None,
                "block": str(gp["block_name"]).title() if _text(gp["block_name"]) else None,
                "kind": r["kind"],
                "category": _text(r["category"]),
                "plannedDate": r["planned"].isoformat() if r["planned"] else None,
                "readyDate": r["ready"].isoformat() if r["ready"] else None,
                "amcDate": r["amc"].isoformat() if r["amc"] else None,
                "target": 1,
                "achieved": base,
                "gap": 1 - base,
                "feName": _str(r["fe"]),
                "feEmail": _str(r["fe_email"]),
                "frtCode": frt_norm(r["frt"]),
            }
        )
    return out


def _figures(rows: list[dict[str, Any]], ready_by: dt.date, amc_by: dt.date, backlog: list[dict[str, Any]] | None = None) -> dict[str, dict[str, int]]:
    """Counts of task GPs (preview rows): this week's target (Planned Date in the week – the ticket's GPs) with how many
    are Ready (Ach Date filled by the plan data date) and AMC converted (AMC Date by the data date), and the backlog
    (planned earlier, not achieved – information only, not in the ticket). toReady = GPs − Ready, toConvert = GPs − AMC."""
    r_by, a_by = ready_by.isoformat(), amc_by.isoformat()

    def part(rs: list[dict[str, Any]]) -> dict[str, int]:
        n = len(rs)
        ready = sum(1 for x in rs if x["readyDate"] and x["readyDate"] <= r_by)
        amc = sum(1 for x in rs if x["amcDate"] and x["amcDate"] <= a_by)
        return {"gps": n, "ready": ready, "amc": amc, "toReady": n - ready, "toConvert": n - amc}

    week = [x for x in rows if x["kind"] == "WEEK"]
    return {"week": part(week), "backlog": part(backlog or []), "total": part(week)}


def breakdown(store: Store, am: str, week_code: str, circle: str | None, rows: list[dict[str, Any]], with_no_am: bool = False) -> dict[str, Any]:
    """Target and achievement of an Area Manager's task for the week, and of every FE mapped under them (only the GPs
    mapped to that FE; GPs without an FE in the matrix are a separate "not mapped" line – never given to anyone).
    `page` = the same AM's figures of AMC Conversion → area manager-wise table (Ach / AMC Date IN the week), to check."""
    from ..analytics.amc_plan import amc_plan_area_managers, plan_data_date, windows

    w = store.week(week_code)
    win = windows(store, week_code, month_of_week=True)
    ready_by, amc_by = plan_data_date(store), store.data_as_of
    groups = {am, NO_AM} if with_no_am else {am}
    slots = [s for s in fe_slots(store, circle, week_code)[0] if s["am"] in groups] if circle else []
    back = preview(store, am, week_code, circle, backlog=True, with_no_am=with_no_am)
    fes = []
    for s in slots:
        key = fe_key(s["name"], s["mappedEmail"])
        owns = lambda x: bool(x["feName"]) and fe_key(x["feName"], x["feEmail"]) == key  # noqa: E731
        fes.append({"name": s["name"], "email": s["mappedEmail"], "emails": s["emails"], **_figures([x for x in rows if owns(x)], ready_by, amc_by, [x for x in back if owns(x)])})
    unmapped = [x for x in rows if not x["feName"]]
    unmapped_back = [x for x in back if not x["feName"]]
    # FRT-wise: the GPs of each FRT code (Escalation Matrix) – an FRT account with that code joins the ticket and reports
    # them (the API adds who has a login); GPs without an FRT code stay with their FE
    frts = []
    for code in sorted({x.get("frtCode") for x in rows + back if x.get("frtCode")}):
        mine, mine_back = [x for x in rows if x.get("frtCode") == code], [x for x in back if x.get("frtCode") == code]
        frts.append({"code": code, "fes": sorted({x["feName"] for x in mine + mine_back if x["feName"]}), **_figures(mine, ready_by, amc_by, mine_back)})
    no_frt, no_frt_back = [x for x in rows if not x.get("frtCode")], [x for x in back if not x.get("frtCode")]
    page = None
    if circle and am != NO_AM and not with_no_am:  # the AMC Conversion table knows only the matrix AMs' own GPs
        ckey = " ".join(circle.split()).lower()
        cid = next((i for i, c in zip(store.gps["circle_id"], store.gps["circle"]) if " ".join(str(c).split()).lower() == ckey), None)
        if cid is not None:
            t = next((r for r in amc_plan_area_managers(store, week_code, cid)["rows"] if r["name"] == am), None)
            if t is not None:
                page = {"weekTarget": t["weekTarget"], "weekReady": t["weekAchieved"], "weekConverted": t["weekConverted"]}
    return {
        "week": {"id": w.code, "number": w.number, "start": w.start.isoformat(), "end": w.end.isoformat(), "asOf": min(w.end, win.as_of).isoformat()},
        "readyAsOf": ready_by.isoformat(),
        "amcAsOf": amc_by.isoformat(),
        "am": {"name": am, **_figures(rows, ready_by, amc_by, back)},
        "fes": fes,
        "unmapped": _figures(unmapped, ready_by, amc_by, unmapped_back) if unmapped or unmapped_back else None,
        "frts": frts,
        "noFrt": _figures(no_frt, ready_by, amc_by, no_frt_back) if frts and (no_frt or no_frt_back) else None,
        "page": page,
        "definitions": [
            f"Weekly Target = GPs whose Planned Date falls in Week {w.number} ({w.start:%d %b} – {w.end:%d %b %Y}) – only these GPs are in the ticket; Backlog = Planned Date before the week, no AMC Date before it (information only, not in the target).",
            f"Ready = Ach Date filled (up to {ready_by:%d %b %Y}); AMC Converted = AMC Date filled (up to {amc_by:%d %b %Y}).",
            "Remaining to be ready = GPs − Ready; Remaining to convert = GPs − AMC Converted.",
            "Each FE: only the GPs mapped to that FE (FE name + FE e-mail) in the Escalation Matrix. GPs without an FE are shown as not mapped.",
        ],
    }


def am_emails(store: Store, am: str) -> list[str]:
    if am == NO_AM:
        return []
    d, _ = _directory(store)
    return sorted({e for v in d.loc[d["am"] == am, "email"] for e in split_emails(v)})


def _cbh_of(codes: list[str]) -> str | None:
    """CBH name(s) of the GPs in the Escalation Matrix (None without a matrix)."""
    from ..analytics.escalation import _active

    act = _active()
    if act is None or not codes:
        return None
    names = {" ".join(str(n).split()): None for n in act[1].reindex(codes)["cbh_name"] if isinstance(n, str) and n.strip() and n.strip() != "0"}
    return ", ".join(names)[:160] or None


def attach(
    db: Session, store: Store, t: Ticket, am: str, week_code: str, circle: str | None = None, am_email: str | None = None, fes: list[FeScope] | None = None,
    *, with_no_am: bool = False, acting: str | None = None, typed_fe: FeScope | None = None,
) -> TicketTask:
    """Create the task rows of a ticket being created (same transaction) and its assignment workbook. `fes`: a ticket
    without the Area Manager – only the GPs of these Field Engineers. am = NO_AM + `acting`: the circle's GPs without an
    Area Manager for the acting AM typed by the admin; with_no_am: an AM's GPs plus those. `typed_fe`: an FE typed by
    the admin gets the task GPs that have no FE in the matrix. No GP in the week = a ticket with 0 GPs (never refused)."""
    rows = preview(store, am, week_code, circle, fes, with_no_am=with_no_am)
    if typed_fe is not None:
        for r in rows:
            if not r["feName"]:
                r["feName"], r["feEmail"] = typed_fe.name, typed_fe.mail
    w = store.week(week_code)
    emails = am_emails(store, am)
    circles = sorted({r["circle"] for r in rows})
    source = "NO_AM" if am == NO_AM and acting else "AM+NO_AM" if with_no_am else None
    task = TicketTask(
        ticket_id=t.id, am_name=(acting or am)[:160], am_email=am_email or (emails[0] if emails else None), week_code=w.code, week_start=w.start, week_end=w.end,
        data_as_of=store.data_as_of, source_file=store.file_name, circle=circle or ", ".join(circles)[:80], cbh_name=_cbh_of([r["gpCode"] for r in rows]), gp_source=source,
    )
    db.add(task)
    for r in rows:
        db.add(
            TicketTaskGp(
                ticket_id=t.id, sort=r["sort"], gp_code=r["gpCode"], gp_name=r["gpName"], circle=r["circle"], business_area=r["businessArea"], district=r["district"], block=r["block"],
                kind=r["kind"], category=r["category"], planned_date=_iso(r["plannedDate"]), ready_date=_iso(r["readyDate"]), amc_date=_iso(r["amcDate"]), target=1, base_achieved=r["achieved"], reported=0,
                fe_name=r["feName"], fe_email=r["feEmail"], frt_code=r.get("frtCode"),
            )
        )
    db.flush()
    # the original assignment workbook (reference document, never rewritten)
    data = workbook(db, t, task, original=True)
    name = f"{uuid.uuid4().hex}.xlsx"
    folder = get_settings().ticket_dir / str(t.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    task.assignment_file = name
    return task


def week_range(start: dt.date, end: dt.date) -> str:
    """07–13 Nov / 28 Oct – 03 Nov."""
    return f"{start:%d}–{end:%d %b}" if (start.year, start.month) == (end.year, end.month) else f"{start:%d %b} – {end:%d %b}"


def task_subject(task: TicketTask, fes: list[str] | None = None) -> str:
    """The subject of a GP-wise task ticket, built from ITS OWN task – the Area Manager (or the Field Engineers of a
    ticket without the AM), the week with its dates and the circle – so every ticket of a batch names the right AM."""
    am = f"{task.am_name} (acting AM)" if task.gp_source == "NO_AM" else task.am_name
    who = f"FE {', '.join(fes)} ({am})" if fes else am
    where = f" · {task.circle}" if task.circle else ""
    return f"Weekly GP task – {who} – Week {task.week_code[2:]} ({week_range(task.week_start, task.week_end)}){where}"[:200]


def _iso(v: str | None) -> dt.date | None:
    return dt.date.fromisoformat(v) if v else None


def _gps(db: Session, ticket_id: int) -> list[TicketTaskGp]:
    return list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == ticket_id).order_by(TicketTaskGp.sort)))


def cumulative(g: TicketTaskGp) -> int:
    return min(g.target, g.base_achieved + g.reported)


def gp_status(g: TicketTaskGp) -> str:
    """DONE once the GP's cumulative achievement reached its target, else PENDING."""
    return "DONE" if cumulative(g) >= g.target else "PENDING"


def line_status(ln: TicketProgressLine, g: TicketTaskGp | None) -> str:
    """The GP's status right after that daily submission."""
    return "DONE" if g is not None and ln.cumulative >= g.target else "PENDING"


def file_json(f: TicketProgressFile, iso) -> dict[str, Any]:
    out = {"id": f.id, "fileName": f.file_name, "contentType": f.content_type, "size": f.size, "uploadedAt": iso(f.uploaded_at), "previewable": f.content_type in files.INLINE_TYPES}
    if f.latitude is not None and f.longitude is not None:  # a live camera photo: where and when it was taken
        out |= {"latitude": f.latitude, "longitude": f.longitude, "accuracy": f.geo_accuracy, "capturedAt": iso(f.captured_at), "source": f.capture_source}
    return out


# The FRT's photo: on a phone the screen takes it with the Camera (with its location – validated below and saved);
# on a laptop the FRT uploads a photo file (no location). Both need the usual remark + JPG / PNG photo.
MAX_CAPTURE_AGE = dt.timedelta(hours=24)  # a camera photo is used the same day it was taken


def check_geo(geo: Any) -> dict | None:
    """A camera photo's location / time as sent by the screen: {"lat", "lng", "accuracy"?, "capturedAt"} – validated
    (ranges, not in the future, at most a day old); None = no (valid) location. Raises TaskError on a malformed value."""
    if not geo:
        return None
    if not isinstance(geo, dict):
        raise TaskError(422, "The photo location could not be read")
    try:
        lat, lng = float(geo.get("lat")), float(geo.get("lng"))
        acc = float(geo["accuracy"]) if geo.get("accuracy") is not None else None
        at = dt.datetime.fromisoformat(str(geo.get("capturedAt")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise TaskError(422, "The photo location / time could not be read – take the photo again") from None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0) or (acc is not None and acc < 0):
        raise TaskError(422, "The photo location is not valid – take the photo again with location on")
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    now = dt.datetime.now(dt.UTC)
    if at > now + dt.timedelta(minutes=10) or now - at > MAX_CAPTURE_AGE:
        raise TaskError(422, "The photo was not taken now (its time is in the future or more than a day old) – take it again")
    return {"lat": round(lat, 7), "lng": round(lng, 7), "accuracy": round(acc, 1) if acc is not None else None, "capturedAt": at}


def _fe_summary(gps: list[TicketTaskGp], files_of_gp: dict[int, list[Any]], last_update: dict[int, Any], fe_recipients: set[tuple[str, str]], iso) -> list[dict[str, Any]]:
    """FE-wise allocation and progress of a task (GPs without an FE in the matrix = one "not mapped" row, name None)."""
    out: dict[tuple[str, str] | None, dict[str, Any]] = {}
    for g in gps:
        k = fe_key(g.fe_name, g.fe_email) if g.fe_name else None
        r = out.setdefault(
            k,
            {"name": g.fe_name, "email": g.fe_email, "gps": 0, "target": 0, "achieved": 0, "doneGps": 0, "pendingGps": 0, "proofFiles": 0, "lastUpdated": None, "recipient": k in fe_recipients,
             "categories": dict.fromkeys(CATEGORIES, 0), "notClassified": 0, "approvedGps": 0, "returnedGps": 0, "awaitingGps": 0, "addedGps": 0, "pendingFeGps": 0},
        )
        r["gps"] += 1
        if g.review == "RETURNED":
            r["returnedGps"] += 1
        elif g.review is not None:
            r["approvedGps"] += 1
        elif g.gp_category == "A" and not frt_stage_open(g):
            r["awaitingGps"] += 1
        r["pendingFeGps"] += frt_stage_open(g) and g.frt_stage == "PENDING_FE"  # the FRT submitted, the FE has to verify
        r["addedGps"] += g.kind == "ADDED"
        if g.gp_category in CATEGORIES:
            r["categories"][g.gp_category] += 1
        else:
            r["notClassified"] += 1
        r["target"] += g.target
        r["achieved"] += cumulative(g)
        r["doneGps" if gp_status(g) == "DONE" else "pendingGps"] += 1
        r["proofFiles"] += len(files_of_gp.get(g.id, []))
        when = last_update.get(g.id)
        if when is not None and (r["lastUpdated"] is None or when > r["lastUpdated"]):
            r["lastUpdated"] = when
    rows = sorted(out.values(), key=lambda r: (r["name"] is None, (r["name"] or "").lower(), r["email"] or ""))
    return [r | {"gap": r["target"] - r["achieved"], "lastUpdated": iso(r["lastUpdated"])} for r in rows]


def _frt_summary(gps: list[TicketTaskGp], files_of_gp: dict[int, list[Any]], last_update: dict[int, Any], frt_people: dict[str, list[str]], iso) -> list[dict[str, Any]]:
    """FRT-wise target and progress of a task: one row per FRT code of the GPs (GPs without an FRT are not listed –
    their FE reports them). `frt_people` = FRT code -> names of the FRT accounts on the ticket (empty = no account)."""
    out: dict[str, dict[str, Any]] = {}
    for g in gps:
        code = frt_norm(g.frt_code)
        if code is None:
            continue
        r = out.setdefault(
            code,
            {"code": code, "names": frt_people.get(code, []), "recipient": code in frt_people, "fes": set(), "gps": 0, "target": 0, "achieved": 0, "doneGps": 0, "pendingGps": 0,
             "proofFiles": 0, "lastUpdated": None, "categories": dict.fromkeys(CATEGORIES, 0), "notClassified": 0, "pendingFe": 0, "returnedFrt": 0, "verified": 0},
        )
        r["gps"] += 1
        if g.fe_name:
            r["fes"].add(g.fe_name)
        r["target"] += g.target
        r["achieved"] += cumulative(g)
        r["doneGps" if gp_status(g) == "DONE" else "pendingGps"] += 1
        r["proofFiles"] += len(files_of_gp.get(g.id, []))
        if g.gp_category in CATEGORIES:
            r["categories"][g.gp_category] += 1
        else:
            r["notClassified"] += 1
        if frt_stage_open(g):
            r["pendingFe" if g.frt_stage == "PENDING_FE" else "returnedFrt"] += 1
        elif g.frt_stage == "FE_VERIFIED":
            r["verified"] += 1
        when = last_update.get(g.id)
        if when is not None and (r["lastUpdated"] is None or when > r["lastUpdated"]):
            r["lastUpdated"] = when
    rows = sorted(out.values(), key=lambda r: r["code"])
    return [r | {"fes": sorted(r["fes"]), "gap": r["target"] - r["achieved"], "lastUpdated": iso(r["lastUpdated"])} for r in rows]


def _utc(v: dt.datetime | None) -> dt.datetime | None:
    return None if v is None else (v if v.tzinfo else v.replace(tzinfo=dt.UTC))  # SQLite: naive UTC


def task_json(db: Session, t: Ticket, scope: FeScope | FrtScope | SmeView | None = None) -> dict[str, Any] | None:
    """The task as one viewer sees it: `scope` = a Field Engineer (only their GPs, proof files and history lines) or an
    SME (only the GPs the Area Manager forwarded to them)."""
    task = db.get(TicketTask, t.id)
    if task is None:
        return None
    gps = [g for g in _gps(db, t.id) if scope is None or scope.owns(g)]
    mine = {g.id for g in gps}
    subs = list(db.scalars(select(TicketProgress).where(TicketProgress.ticket_id == t.id).order_by(TicketProgress.submitted_at.desc(), TicketProgress.id.desc())))
    lines = list(db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id.in_([s.id for s in subs])).order_by(TicketProgressLine.id))) if subs else []
    lines = [ln for ln in lines if ln.task_gp_id in mine]
    if scope is not None:
        with_lines = {ln.progress_id for ln in lines}
        subs = [s for s in subs if s.id in with_lines]
    from ..models import TicketRecipient
    from .service import iso  # local import: service imports this module

    by_gp = {g.id: g for g in gps}
    at = {s.id: (s.submitted_at if s.submitted_at is None or s.submitted_at.tzinfo else s.submitted_at.replace(tzinfo=dt.UTC)) for s in subs}  # SQLite: naive UTC
    from . import review as rv

    # review steps (AM approval, SME forward, …) write progress lines with the same user and time as their review row;
    # proof attached to such a line is that reviewer's proof – never counted or shown as the FE's evidence
    records, review_keys = rv.records(db, t, mine, iso)
    review_subs = {s.id for s in subs if (s.submitted_by_id, _utc(s.submitted_at)) in review_keys}
    sub_of_key = {(s.submitted_by_id, _utc(s.submitted_at)): s.id for s in subs if s.id in review_subs}
    line_sub = {ln.id: ln.progress_id for ln in lines}
    all_files = [f for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)) if f.task_gp_id in mine]
    proofs = [f for f in all_files if line_sub.get(f.progress_line_id) not in review_subs]
    files_of_line: dict[int, list[dict[str, Any]]] = {}
    files_of_gp: dict[int, list[dict[str, Any]]] = {}
    review_files: dict[tuple[int, int], list[dict[str, Any]]] = {}  # (progress id of the review step, GP) -> files
    for f in all_files:
        j = file_json(f, iso)
        files_of_line.setdefault(f.progress_line_id, []).append(j)
        sid = line_sub.get(f.progress_line_id)
        if sid in review_subs:
            review_files.setdefault((sid, f.task_gp_id), []).append(j)
        else:
            files_of_gp.setdefault(f.task_gp_id, []).append(j)
    last_update: dict[int, Any] = {}
    last_by: dict[int, str] = {}  # who submitted the GP's latest line (Area Manager / FE)
    who = {s.id: s.submitted_by_name for s in subs}
    by_sub: dict[int, list[dict[str, Any]]] = {}
    for ln in lines:
        g = by_gp.get(ln.task_gp_id)
        when = at.get(ln.progress_id)
        if when is not None and (ln.task_gp_id not in last_update or when >= last_update[ln.task_gp_id]):
            last_update[ln.task_gp_id] = when
            last_by[ln.task_gp_id] = who.get(ln.progress_id, "")
        by_sub.setdefault(ln.progress_id, []).append(
            {
                "taskGpId": ln.task_gp_id, "gpCode": g.gp_code if g else None, "gpName": g.gp_name if g else None, "block": g.block if g else None,
                "achievedToday": ln.achieved_today, "cumulative": ln.cumulative, "gap": ln.gap, "remark": ln.remark,
                "status": line_status(ln, g), "gpCategory": ln.category, "files": files_of_line.get(ln.id, []),
            }
        )

    target = sum(g.target for g in gps)
    achieved = sum(cumulative(g) for g in gps)
    blocks: dict[str, dict[str, Any]] = {}
    for g in gps:
        b = blocks.setdefault(g.block or "—", {"block": g.block or "—", "gps": 0, "target": 0, "achieved": 0})
        b["gps"] += 1
        b["target"] += g.target
        b["achieved"] += cumulative(g)
    fe_recipients = {fe_key(r.name, r.fe_mail) for r in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE"))}
    owner_keys = fe_owner_keys(db, t)
    frt_recs = list(db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FRT").order_by(TicketRecipient.name)))
    frt_people: dict[str, list[str]] = {}
    for r in frt_recs:
        if frt_norm(r.frt_code) and r.user_id is not None and r.can_work:
            frt_people.setdefault(frt_norm(r.frt_code), []).append(r.name)
    frt_codes = set(frt_people)
    frt_users = {r.user_id for r in frt_recs if r.user_id is not None}
    # the FE's latest check of the FRT's Daily Achievement per GP (FE_VERIFY / FE_RETURN)
    from ..models import TicketGpReview

    frt_check: dict[int, dict[str, Any]] = {}
    if mine:
        for x in db.scalars(select(TicketGpReview).where(TicketGpReview.ticket_id == t.id, TicketGpReview.action.in_(tuple(FE_STEPS))).order_by(TicketGpReview.at, TicketGpReview.id)):
            if x.task_gp_id in mine:
                frt_check[x.task_gp_id] = {"action": x.action, "label": FE_STEPS[x.action], "by": x.actor_name, "role": x.role, "remark": x.remark, "at": iso(x.at)}
    trail = rv.trails(db, t, mine, iso)
    from . import nondoable as nd

    nd_refs = nd.case_refs(db, t.id)
    reviewed = [g.review for g in gps]

    # FE original submission of each GP, from the daily progress lines (never overwritten): the latest line that set
    # an FE category (A / C / D) up to the Area Manager's approval, with the latest remark / submitter after it.
    # Lines written by the review steps themselves (same user and time as a review row) are not the FE's.
    sub_of = {s.id: s for s in subs}
    fe_users = set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE", TicketRecipient.user_id.is_not(None))))
    lines_of_gp: dict[int, list[TicketProgressLine]] = {}
    for ln in lines:
        if ln.progress_id not in review_subs:
            lines_of_gp.setdefault(ln.task_gp_id, []).append(ln)
    epoch = dt.datetime.min.replace(tzinfo=dt.UTC)

    def fe_submission(g: TicketTaskGp) -> dict[str, Any] | None:
        cut = records.get(g.id, {}).get("_amAt")
        own = sorted(
            (ln for ln in lines_of_gp.get(g.id, []) if cut is None or (at.get(ln.progress_id) or epoch) <= cut),
            key=lambda ln: (at.get(ln.progress_id) or epoch, ln.id),
        )
        idx = next((i for i in range(len(own) - 1, -1, -1) if own[i].category in rv.FE_CATEGORIES), None)
        if idx is None:
            return None
        window = own[idx:]
        last = sub_of[window[-1].progress_id]
        return {
            "feName": g.fe_name,
            "submittedBy": last.submitted_by_name,
            "submittedByRole": "FRT" if last.submitted_by_id in frt_users else "FE" if last.submitted_by_id in fe_users else "AM",
            "category": own[idx].category,
            "remark": next((ln.remark for ln in reversed(window) if ln.remark), None),
            "submittedAt": iso(last.submitted_at),
            "files": [f for ln in own for f in files_of_line.get(ln.id, [])],
        }

    def public(r: dict[str, Any] | None, gp_id: int | None = None) -> dict[str, Any] | None:
        """The record for the API, with the proof the reviewer attached to that step (AM / SME evidence)."""
        if not r:
            return None
        out = {k: v for k, v in r.items() if not k.startswith("_")}
        if gp_id is not None:
            sid = sub_of_key.get(r.get("_key"))
            out["files"] = review_files.get((sid, gp_id), []) if sid is not None else []
        return out

    if isinstance(scope, FeScope):
        scope_out: dict[str, Any] | None = {"kind": "FE", "fieldEngineer": scope.name, "email": scope.mail}
    elif isinstance(scope, FrtScope):
        scope_out = {"kind": "FRT", "fieldEngineer": None, "email": None, "frtCode": scope.code if scope.code != "\0" else None, "frtName": scope.name,
                     "fes": sorted({g.fe_name for g in gps if g.fe_name})}
    elif isinstance(scope, ReviewerView):
        # the reviewer's KPIs: the ticket's GP count (a number only – no GP of others) against the GPs handed to them
        ticket_gps = db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id)) or 0
        rs = [g.review for g in gps]
        if scope.kind == "SME":
            kpis = {"pending": rs.count("AM_APPROVED") + rs.count("COH_RETURNED"), "forwarded": sum(r in ("SME_FORWARDED", "LETTER_SUBMITTED", "AMC_CONVERTED") for r in rs),
                    "sentBack": rs.count("SME_RETURNED"), "returnedToYou": rs.count("COH_RETURNED")}
        else:
            kpis = {"pending": rs.count("SME_FORWARDED"), "letterSubmitted": rs.count("LETTER_SUBMITTED"), "amcConverted": rs.count("AMC_CONVERTED"), "sentBack": rs.count("COH_RETURNED")}
        scope_out = {"kind": scope.kind, "fieldEngineer": None, "email": None, "kpis": {"ticketGps": ticket_gps, "assigned": len(gps), **kpis}}
    else:
        scope_out = None
    return {
        "areaManager": task.am_name,
        "gpSource": task.gp_source,
        "amEmail": task.am_email,
        # a Field Engineer's / SME's view: only their GPs; everyone else sees the whole task with the FE-wise split
        "scope": scope_out,
        "fes": [] if scope is not None else _fe_summary(gps, files_of_gp, last_update, fe_recipients, iso),
        # FRT-wise target and progress (whole task, or an FE's own GPs; none in an FRT's / reviewer's view)
        "frts": _frt_summary(gps, files_of_gp, last_update, frt_people, iso) if scope is None or isinstance(scope, FeScope) else [],
        "circle": task.circle,
        "cbhName": task.cbh_name,
        "week": {"id": task.week_code, "start": task.week_start.isoformat(), "end": task.week_end.isoformat()},
        "dataAsOf": task.data_as_of.isoformat(),
        "sourceFile": task.source_file,
        "totals": {
            "gps": len(gps), "target": target, "achieved": achieved, "gap": target - achieved, "pct": round(achieved / target * 100, 1) if target else None,
            "weekGps": sum(g.kind == "WEEK" for g in gps), "pendingGps": sum(g.kind == "PENDING" for g in gps),
            "doneGps": sum(gp_status(g) == "DONE" for g in gps), "openGps": sum(gp_status(g) == "PENDING" for g in gps), "proofFiles": len(proofs),
            "categories": {c: sum(g.gp_category == c for g in gps) for c in CATEGORIES}, "notClassified": sum(g.gp_category is None for g in gps),
            "addedGps": sum(g.kind == "ADDED" for g in gps),
            # review chain: awaiting = Rectification Done by the FE, not yet approved or returned by the Area Manager
            "review": {
                "awaiting": sum(g.review is None and g.gp_category == "A" and not frt_stage_open(g) for g in gps), "returned": reviewed.count("RETURNED"),
                "pendingFe": sum(frt_stage_open(g) and g.frt_stage == "PENDING_FE" for g in gps), "returnedFrt": sum(frt_stage_open(g) and g.frt_stage == "RETURNED_FRT" for g in gps),
                "amApproved": reviewed.count("AM_APPROVED"), "smeForwarded": reviewed.count("SME_FORWARDED"),
                "smeReturned": reviewed.count("SME_RETURNED"), "cohReturned": reviewed.count("COH_RETURNED"),
                "letterSubmitted": reviewed.count("LETTER_SUBMITTED"), "amcConverted": reviewed.count("AMC_CONVERTED"),
                "ndOpen": sum(1 for g in gps if nd_refs.get(g.id, {}).get("open")), "ndApproved": reviewed.count(nd.ND_REVIEW),
            },
        },
        "blocks": [{**b, "gap": b["target"] - b["achieved"]} for b in sorted(blocks.values(), key=lambda x: x["block"])],
        "gps": [
            {
                "id": g.id, "gpCode": g.gp_code, "gpName": g.gp_name, "circle": g.circle, "businessArea": g.business_area, "district": g.district, "block": g.block, "kind": g.kind,
                "category": g.category, "plannedDate": g.planned_date.isoformat() if g.planned_date else None, "readyDate": g.ready_date.isoformat() if g.ready_date else None,
                "amcDate": g.amc_date.isoformat() if g.amc_date else None, "target": g.target, "baseAchieved": g.base_achieved, "reported": g.reported,
                "cumulative": cumulative(g), "gap": g.target - cumulative(g), "remarks": g.remarks,
                "status": gp_status(g), "gpCategory": g.gp_category, "files": files_of_gp.get(g.id, []), "lastUpdated": iso(last_update.get(g.id)), "lastUpdatedBy": last_by.get(g.id), "feName": g.fe_name,
                "review": g.review, "reviewAt": iso(g.review_at), "locked": g.review in rv.LOCKED,
                "stage": rv.stage_of(g, bool((nd_refs.get(g.id) or {}).get("open"))), "reviewLabel": rv.stage_label(rv.stage_of(g, bool((nd_refs.get(g.id) or {}).get("open")))),
                "letterDate": g.letter_date.isoformat() if g.letter_date else None, "amcOn": g.amc_on.isoformat() if g.amc_on else None, "addedBy": g.added_by,
                "trail": trail.get(g.id, []), "ndCase": nd_refs.get(g.id),
                "feSubmission": fe_submission(g), "amApproval": public(records.get(g.id, {}).get("amApproval"), g.id), "smeReview": public(records.get(g.id, {}).get("smeReview"), g.id),
                "sentBack": public(records.get(g.id, {}).get("sentBack")),
                # an FE of this ticket (dashboard account) reports this GP – the Area Manager only reviews / reassigns it
                "feAssigned": fe_assigned(g, owner_keys),
                # FRT team of the GP: an FRT account of the ticket reports it, the FE verifies it (frtStage) before the AM
                "frtCode": g.frt_code, "frtAssigned": frt_assigned(g, frt_codes), "frtStage": g.frt_stage, "frtCheck": frt_check.get(g.id),
            }
            for g in gps
        ],
        # Area Manager / admin: the FEs a GP can be reassigned to (none in an FE's / reviewer's view)
        "feOptions": fe_options(db, t) if scope is None else [],
        # Non-Doable cases of the GPs this viewer reports (FE: theirs; AM: those without an FE of the ticket) that wait
        # for the E1 / E2 forms – the Daily Achievement is locked until they are submitted (submit_progress)
        "ndPending": [
            {"caseId": c.id, "ref": c.ref, "gpId": c.task_gp_id, "gpCode": c.gp_code, "status": c.status, "label": nd.STATUS_LABEL[c.status]}
            for c in nd.forms_pending(db, t.id, {g.id for g in gps if (scope.owns(g) if isinstance(scope, FeScope) else not fe_assigned(g, owner_keys))})
        ] if not isinstance(scope, (ReviewerView, FrtScope)) else [],  # the E1 / E2 forms are the FE's, never the FRT's
        "latestSubmission": iso(subs[0].submitted_at) if subs else None,
        "history": [{"id": s.id, "submittedAt": iso(s.submitted_at), "submittedBy": s.submitted_by_name, "note": s.note, "lines": by_sub.get(s.id, [])} for s in subs],
    }


GP_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]{0,39}$")
MAX_NEW_GPS = 50  # GPs added in one daily submission


def _edits(g: TicketTaskGp, it: dict[str, Any]) -> list[tuple[str, str, str | None, str | None]]:
    """GP Code / GP Name / Block corrected in the daily progress: (field, label, old, new). The GP code is checked
    against the ticket and the week by submit_progress (_check_code)."""
    out: list[tuple[str, str, str | None, str | None]] = []
    if it.get("gpCode") is not None:
        c = str(it["gpCode"]).strip()
        if not GP_CODE_RE.match(c):
            raise TaskError(422, f"GP {g.gp_code}: '{c[:40]}' is not a valid GP code (letters and digits, up to 40 characters)")
        if c != g.gp_code:
            out.append(("gp_code", "GP Code", g.gp_code, c))
    if it.get("gpName") is not None:
        v = " ".join(str(it["gpName"]).split())[:160]
        if not v:
            raise TaskError(422, f"GP {g.gp_code}: the GP name cannot be empty")
        if v != g.gp_name:
            out.append(("gp_name", "GP Name", g.gp_name, v))
    if it.get("block") is not None:
        b = " ".join(str(it["block"]).split())[:160] or None
        if b != g.block:
            out.append(("block", "Block", g.block, b))
    return out


def _code_in_week(db: Session, t: Ticket, week_code: str, code: str) -> str | None:
    """Another ticket of the same week that already has this GP code (None = free)."""
    return db.scalar(
        select(Ticket.code)
        .join(TicketTask, TicketTask.ticket_id == Ticket.id)
        .join(TicketTaskGp, TicketTaskGp.ticket_id == Ticket.id)
        .where(TicketTaskGp.gp_code == code, TicketTask.week_code == week_code, Ticket.deleted_at.is_(None), Ticket.id != t.id)
        .limit(1)
    )


def _master_gp(store: Store | None, code: str) -> Any:
    if store is None:
        return None
    idx = store.gps.index
    for key in (code, int(code) if code.isdigit() else None):
        if key is not None and key in idx:
            return store.gps.loc[key]
    return None


def submit_progress(
    db: Session, t: Ticket, user: CurrentUser, items: list[dict[str, Any]], note: str | None, uploads: list[tuple[int, Any]] | None = None,
    new_gps: list[dict[str, Any]] | None = None, store: Store | None = None,
) -> TicketProgress:
    """Save one daily submission. Only the assigned user, only while the ticket is not closed; nothing is overwritten.
    items: taskGpId, category A / C / D (or the older status DONE | PENDING / achievedToday 1 | 0), remark, and the
    GP Name / Block when the FE / Area Manager corrects them. new_gps: GPs added to the ticket (gpCode, gpName, block,
    category, remark) – target 1 each, details from the master data when the code is in it.
    uploads: (taskGpId, Upload) – proof documents of a GP, validated and stored like the submission attachments.
    A GP the Area Manager approved (review.LOCKED) can no longer be changed here; a returned GP goes back to the
    Area Manager with the next change."""
    from . import nondoable as nd
    from . import review as rv
    from .service import is_worker  # local import: service imports this module

    if not is_worker(db, t, user):
        raise TaskError(403, "Only the assigned Area Manager can submit daily progress")
    if t.status == "CLOSED":
        raise TaskError(409, "This ticket is closed – no more daily progress can be submitted")
    task = db.get(TicketTask, t.id)
    if task is None:
        raise TaskError(404, "This ticket has no GP-wise task")
    gps = {g.id: g for g in _gps(db, t.id)}
    scope = scope_of(db, t, user)
    frt = scope if isinstance(scope, FrtScope) else None
    role = "FRT" if frt is not None else "FE" if scope is not None else "AM"
    fe_keys = fe_owner_keys(db, t) if scope is None else set()
    frt_codes = frt_owner_codes(db, t) if frt is None else set()
    # an FRT may add a GP found in the field: it gets the FRT's code and the FRT's FE (who verifies it, as any FRT GP)
    frt_fe: tuple[str | None, str | None] = (None, None)
    if frt is not None and new_gps:
        mine = [(g.fe_name, g.fe_email) for g in gps.values() if frt.owns(g) and g.fe_name]
        if not mine:
            raise TaskError(422, "Your GPs have no Field Engineer in this ticket – ask your FE to add the GP")
        frt_fe = max(set(mine), key=mine.count)

    # a Non-Doable case of the submitter's own GPs still waiting for their E1 / E2 forms: no Daily Achievement before
    # those are submitted (the case is opened from Non-Doable Cases). The forms are the FE's – an FRT is not blocked.
    mine_ids = {g.id for g in gps.values() if (scope.owns(g) if scope is not None else not fe_assigned(g, fe_keys) and not frt_assigned(g, frt_codes))} if frt is None else set()
    waiting = nd.forms_pending(db, t.id, mine_ids)
    if waiting:
        refs = ", ".join(f"{c.ref} (GP {c.gp_code})" for c in waiting[:5]) + (f" … (+{len(waiting) - 5})" if len(waiting) > 5 else "")
        raise TaskError(409, f"Non-Doable case {refs} is waiting for your E1 Physical Verification / E2 Justification – open it in Non-Doable Cases and submit the forms before the next Daily Achievement")

    def own(g: TicketTaskGp) -> None:
        if scope is not None and not scope.owns(g):
            raise TaskError(403, f"GP {g.gp_code} is not one of your GPs in this ticket")
        if scope is None and fe_assigned(g, fe_keys):  # the Area Manager reviews an FE's GP, never reports it for them
            raise TaskError(
                403, f"GP {g.gp_code} is assigned to FE {g.fe_name} – only the FE submits its Daily Achievement. Review it with Approve / Return, or use Reassign FE."
            )
        if scope is None and frt_assigned(g, frt_codes):  # nor the GP of an FRT of the ticket
            raise TaskError(403, f"GP {g.gp_code} is reported by FRT {g.frt_code} and verified by the FE – only the FRT submits its Daily Achievement")
        # a GP with an FRT login on the ticket: once the FRT has reported it (waiting for / returned by / verified by the
        # FE) the FE only verifies / returns it; while the FRT has reported nothing the FE may report it itself (it then
        # goes to the Area Manager like the FE's own GPs)
        if frt is None and scope is not None and frt_assigned(g, frt_codes) and g.frt_stage is not None:
            raise TaskError(
                403, f"GP {g.gp_code} is reported by FRT {g.frt_code} – check the FRT's Daily Achievement with Verify / Return to FRT"
            )
        if frt is not None and g.frt_stage == "FE_VERIFIED":
            raise TaskError(409, f"GP {g.gp_code} was verified by your FE and sent to the Area Manager – it comes back to you only if the FE returns it")
        if g.review in rv.LOCKED:
            raise TaskError(409, f"GP {g.gp_code} is {rv.REVIEW_LABEL[g.review]} – it can no longer be changed in the daily progress")
        try:
            nd.check_progress(db, g, None)
        except nd.NdError as exc:
            raise TaskError(exc.status, exc.message) from None

    uploads = [(int(gid), u) for gid, u in (uploads or []) if getattr(u, "file_name", None)]
    for _gid, u in uploads:  # camera location / time: validated before anything is written
        if getattr(u, "geo", None):
            u.geo = check_geo(u.geo)
    if len(uploads) > MAX_PROGRESS_FILES:
        raise TaskError(422, f"At most {MAX_PROGRESS_FILES} proof documents per daily submission")
    files_of: dict[int, list[Any]] = {}
    files_new: dict[int, list[Any]] = {}  # proof of an added GP: proofGps = -(index + 1) of the GP in new_gps
    for gid, u in uploads:
        if gid < 0:
            idx = -gid - 1
            if idx >= len(new_gps or []):
                raise TaskError(422, "A proof document belongs to a GP that is not in this ticket")
            files_new.setdefault(idx, []).append(u)
            if len(files_new[idx]) > MAX_GP_FILES:
                raise TaskError(422, f"New GP {str((new_gps or [])[idx].get('gpCode') or '')[:40]}: at most {MAX_GP_FILES} proof documents per submission")
            try:
                files.check_meta(u.file_name, u.content_type)
            except files.AttachmentError as exc:
                raise TaskError(exc.status, f"New GP: {exc}") from None
            continue
        g = gps.get(gid)
        if g is None:
            raise TaskError(422, "A proof document belongs to a GP that is not in this ticket")
        own(g)
        files_of.setdefault(gid, []).append(u)
        if len(files_of[gid]) > MAX_GP_FILES:
            raise TaskError(422, f"GP {g.gp_code}: at most {MAX_GP_FILES} proof documents per submission")
        try:
            files.check_meta(u.file_name, u.content_type)  # names and types first, before anything is written
        except files.AttachmentError as exc:
            raise TaskError(exc.status, f"GP {g.gp_code}: {exc}") from None
    seen: set[int] = set()
    renamed: dict[int, str] = {}  # GP code corrected in this submission: task GP id -> new code
    fe_only = "choose Rectification Done, Revisit Required or Non-Doable – Proposed (Ready for Letter and Letter Submission come from the AM / SME / COH review)"
    # (GP, change of `reported` (+1 / 0 / -1), remark, new category or None = unchanged, GP Name / Block edits)
    changes: list[tuple[TicketTaskGp, int, str | None, str | None, list[tuple[str, str, str | None, str | None]]]] = []

    def evidence(label: str, remark: str | None, proofs: list[Any]) -> None:
        if remark is None or len(remark) < MIN_REMARK or not any(_is_photo(u) for u in proofs):
            raise TaskError(422, f"{label}: {EVIDENCE_MSG}")

    for it in items:
        gid = int(it.get("taskGpId", 0))
        g = gps.get(gid)
        if g is None:
            raise TaskError(422, "A GP of the submission does not belong to this ticket")
        own(g)
        if gid in seen:
            raise TaskError(422, f"GP {g.gp_code} appears twice in the submission")
        seen.add(gid)
        edits = _edits(g, it)
        new_code = next((new for f, _l, _o, new in edits if f == "gp_code"), None)
        if new_code is not None:
            if nd.last_case(db, g.id) is not None:
                raise TaskError(409, f"GP {g.gp_code} has a Non-Doable case – its GP code cannot be changed")
            if any(x.id != g.id and x.gp_code == new_code for x in gps.values()) or new_code in renamed.values():
                raise TaskError(422, f"GP {new_code} is already in this ticket")
            other = _code_in_week(db, t, task.week_code, new_code)
            if other:
                raise TaskError(422, f"GP {new_code} is already in ticket {other} of this week")
            renamed[g.id] = new_code
        cat = it.get("category")
        remark = (it.get("remark") or "").strip()[:MAX_REMARK] or None
        if cat is not None:
            if cat not in CATEGORIES:
                raise TaskError(422, f"GP {g.gp_code}: choose one of the categories A–E")
            if cat not in rv.FE_CATEGORIES:
                raise TaskError(422, f"GP {g.gp_code}: {fe_only}")
            if frt is not None and cat not in FRT_CATEGORIES:
                raise TaskError(422, f"GP {g.gp_code}: choose Rectification Done, Revisit Required or Non-Doable – Proposed")
            if it.get("status") is not None or it.get("achievedToday") is not None:
                raise TaskError(422, f"GP {g.gp_code}: send either a category or Done / Pending, not both")
            new_cat = None if cat == g.gp_category else cat
            if new_cat == "D" or (new_cat and frt is not None):
                try:
                    nd.check_progress(db, g, new_cat, by_frt=frt is not None)
                except nd.NdError as exc:
                    raise TaskError(exc.status, exc.message) from None
            delta = ((1 if cat == ACHIEVED_CATEGORY else 0) - g.reported) if new_cat else 0
            if new_cat or gid in files_of or (remark and remark != (g.remarks or None)) or edits:
                # a Daily Achievement (or a corrected returned GP back to the AM / FE)
                if new_cat or g.review == "RETURNED" or (frt is not None and g.frt_stage == "RETURNED_FRT"):
                    evidence(f"GP {g.gp_code}", remark, files_of.get(gid, []))
                changes.append((g, delta, remark, new_cat, edits))
            continue
        if frt is not None and (it.get("status") is not None or it.get("achievedToday") is not None):
            raise TaskError(422, f"GP {g.gp_code}: choose the Daily Achievement (Rectification Done or Revisit Required)")
        status = it.get("status")
        today = int(it.get("achievedToday") or 0)
        if status is not None:
            if status not in ("DONE", "PENDING"):
                raise TaskError(422, f"GP {g.gp_code}: the status must be Done or Pending")
            want = 1 if status == "DONE" else 0
            if it.get("achievedToday") is not None and today != want:
                raise TaskError(422, f"GP {g.gp_code}: the status and today's achievement do not match")
            today = want
        if today not in (0, 1):
            raise TaskError(422, f"GP {g.gp_code}: today's achievement must be 0 or 1")
        if today and cumulative(g) >= g.target:
            raise TaskError(422, f"GP {g.gp_code} has already reached its target – it cannot be counted again")
        if status == "PENDING" and cumulative(g) >= g.target:
            raise TaskError(422, f"GP {g.gp_code} has already reached its target – it cannot be marked Pending")
        if today or status == "PENDING" or gid in files_of or (remark and remark != (g.remarks or None)) or edits:
            # the older Done / Pending form is a Daily Achievement too
            if today or status is not None or g.review == "RETURNED" or (frt is not None and g.frt_stage == "RETURNED_FRT"):
                evidence(f"GP {g.gp_code}", remark, files_of.get(gid, []))
            changes.append((g, today, remark, None, edits))
    for gid in files_of:  # a proof for a GP without a status / remark change still makes a line of the day
        if gid not in seen:
            changes.append((gps[gid], 0, None, None, []))

    added: list[dict[str, Any]] = []
    if len(new_gps or []) > MAX_NEW_GPS:
        raise TaskError(422, f"At most {MAX_NEW_GPS} new GPs per daily submission")
    for n in new_gps or []:
        code = str(n.get("gpCode") or "").strip()
        if not GP_CODE_RE.match(code):
            raise TaskError(422, f"'{code[:40]}' is not a valid GP code (letters and digits, up to 40 characters)")
        if any(x.gp_code == code for x in gps.values()) or code in renamed.values() or any(a["code"] == code for a in added):
            raise TaskError(422, f"GP {code} is already in this ticket")
        other = _code_in_week(db, t, task.week_code, code)
        if other:
            raise TaskError(422, f"GP {code} is already in ticket {other} of this week – it cannot be added twice")
        cat = n.get("category")
        if cat is not None and cat not in rv.FE_CATEGORIES:
            raise TaskError(422, f"New GP {code}: {fe_only}")
        m = _master_gp(store, code)
        name = " ".join(str(n.get("gpName") or "").split())[:160]
        if m is None and not name:
            raise TaskError(422, f"GP {code} is not in the master data – enter its GP name")
        new_remark = (n.get("remark") or "").strip()[:MAX_REMARK] or None
        idx = len(added)
        if cat is not None:  # a Daily Achievement of the added GP: same evidence as any other GP
            evidence(f"New GP {code}", new_remark, files_new.get(idx, []))
        added.append({"code": code, "name": name, "block": " ".join(str(n.get("block") or "").split())[:160] or None, "cat": cat, "remark": new_remark, "m": m, "files": files_new.get(idx, [])})
    if not changes and not added:
        raise TaskError(422, "Nothing to submit – choose a category for a GP, write a new remark, correct its details, add a GP or attach a proof document")

    from .service import _event, _move, _notify, _reviewers, now  # local import: service imports this module

    if t.status == "OPEN":
        frm = _move(db, t, ("OPEN",), "IN_PROGRESS", started_at=now())
        _event(db, t, user, "STARTED", frm, "IN_PROGRESS", "Started with the first daily progress")
    at = now()
    sub = TicketProgress(ticket_id=t.id, submitted_by_id=user.id, submitted_by_name=user.name, submitted_at=at, note=(note or "").strip()[:2000] or None)
    db.add(sub)
    db.flush()
    done = 0
    stored: list[str] = []
    budget = get_settings().ticket_upload_max_mb * 1024 * 1024
    try:
        sort = max((x.sort for x in gps.values()), default=0)
        for a in added:
            sort += 1
            m = a["m"]
            amc = _d(m["amc_date"]) if m is not None and "amc_date" in m.index else None
            g = TicketTaskGp(
                ticket_id=t.id, sort=sort, gp_code=a["code"], gp_name=a["name"] or str(m["name"]).title(), circle=(str(m["circle"]).title() if m is not None else (task.circle or "—"))[:80],
                business_area=None, district=str(m["district"]).title() if m is not None and _text(m["district"]) else None,
                block=a["block"] or (str(m["block_name"]).title() if m is not None and _text(m["block_name"]) else None), kind="ADDED", category=None, planned_date=None, ready_date=None,
                amc_date=amc, target=1, base_achieved=1 if amc is not None and store is not None and amc <= store.data_as_of else 0, reported=0,
                fe_name=frt_fe[0] if frt is not None else scope.name if scope is not None else None,
                fe_email=frt_fe[1] if frt is not None else scope.mail if scope is not None else None, added_by=user.name,
                frt_code=frt.code if frt is not None else None,
            )
            db.add(g)
            db.flush()
            gps[g.id] = g
            if a["files"]:
                files_of[g.id] = a["files"]  # stored with the GP's line below, like the proof of any other GP
            rv.record(db, t, g, user, role, "ADD", f"Added by {user.name}" + ("" if m is not None else " – not in the master data"), at)
            changes.append((g, 0, a["remark"], a["cat"], []))
        returned = 0
        to_fe: list[TicketTaskGp] = []  # FRT: GPs now waiting for the FE's verification
        cases: list[tuple[TicketTaskGp, Any]] = []
        for g, delta, remark, new_cat, edits in changes:
            before = cumulative(g)
            g.reported += delta
            if new_cat:
                g.gp_category = new_cat
            if remark:
                g.remarks = remark
            if edits:
                for field, _label, _old, new in edits:
                    setattr(g, field, new)
                rv.record(db, t, g, user, role, "EDIT", "; ".join(f"{label}: {old or '—'} → {new or '—'}" for _f, label, old, new in edits), at)
            if frt is not None:
                # the FRT's Daily Achievement (or its correction) goes to the FE first – the FE sends it to the AM
                if new_cat == "D":  # Non-Doable: the case workflow (FRT → FE review → AM), not the FE verification
                    g.frt_stage = None
                elif new_cat or g.frt_stage == "RETURNED_FRT":
                    g.frt_stage = "PENDING_FE"
                    to_fe.append(g)
            elif g.review == "RETURNED":  # corrected by the FE: back to the Area Manager
                g.review, g.review_at = None, at
                returned += 1
            if frt is None and new_cat == "D" and g.frt_stage is not None:  # the FE proposes Non-Doable: out of the FRT step
                g.frt_stage = None
            today = 1 if cumulative(g) > before else 0  # 1 = became achieved with this line
            done += today
            ln = TicketProgressLine(progress_id=sub.id, task_gp_id=g.id, achieved_today=today, cumulative=cumulative(g), gap=g.target - cumulative(g), remark=remark, category=new_cat)
            db.add(ln)
            case = nd.on_progress(db, t, g, user, new_cat, remark, at, by_frt=frt is not None)
            if case is not None:
                cases.append((g, case))
            if g.id in files_of:
                db.flush()
                for u in files_of[g.id]:
                    try:
                        f = files.save(t.id, u.file_name, u.content_type, u.stream, budget)
                    except files.AttachmentError as exc:
                        raise TaskError(exc.status, f"GP {g.gp_code}: {exc}") from None
                    stored.append(f.stored_name)
                    budget -= f.size
                    geo = getattr(u, "geo", None)
                    db.add(TicketProgressFile(
                        ticket_id=t.id, progress_line_id=ln.id, task_gp_id=g.id, file_name=f.file_name, stored_name=f.stored_name, content_type=f.content_type, size=f.size,
                        sha256=f.sha256, uploaded_at=now(),
                        **({"latitude": geo["lat"], "longitude": geo["lng"], "geo_accuracy": geo["accuracy"], "captured_at": geo["capturedAt"], "capture_source": "CAMERA"} if geo else {}),
                    ))
        total = sum(x.target for x in gps.values())
        achieved = sum(cumulative(x) for x in gps.values())
        proof = f" · {len(stored)} proof document{'s' if len(stored) != 1 else ''}" if stored else ""
        cats = [CATEGORIES[c[3]] for c in changes if c[3]]
        what = f"{len(cats)} GP{'s' if len(cats) != 1 else ''} classified ({', '.join(f'{n} {lbl}' for lbl, n in sorted({x: cats.count(x) for x in cats}.items()))})" if cats else f"{done} GP{'s' if done != 1 else ''} marked Done today"
        n_edit = sum(1 for c in changes if c[4])
        extra = (f" · {len(added)} GP{'s' if len(added) != 1 else ''} added" if added else "") + (f" · {n_edit} GP{'s' if n_edit != 1 else ''} corrected" if n_edit else "")
        extra += f" · {returned} returned GP{'s' if returned != 1 else ''} sent back to the Area Manager" if returned else ""
        extra += f" · Non-Doable proposed: {', '.join(f'{c.ref} (GP {g.gp_code})' for g, c in cases)}" if cases else ""
        _event(db, t, user, "PROGRESS", t.status, t.status, f"Daily progress: {what}, {len(changes)} GP line{'s' if len(changes) != 1 else ''}{proof}{extra} · {achieved}/{total} achieved")
        _notify(db, _reviewers(db, t), t, "PROGRESS", f"{t.code}: daily progress", f"{user.name} submitted daily progress – {achieved} of {total} GPs achieved.")
        if frt is not None:  # an FRT reported: their FE verifies it (dashboard notification)
            fe_ids = rv._fe_users(db, t, to_fe or [g for g, *_ in changes]) - {user.id}
            if to_fe:
                codes = ", ".join(g.gp_code for g in to_fe[:10]) + (f" … (+{len(to_fe) - 10})" if len(to_fe) > 10 else "")
                _notify(db, fe_ids, t, "PROGRESS", f"{t.code}: FRT {frt.code} – verify the Daily Achievement",
                        f"FRT {frt.name} ({frt.code}) submitted the Daily Achievement of {len(to_fe)} GP{'s' if len(to_fe) != 1 else ''} ({codes}). Check the proof and remark, then Verify (to the Area Manager) or Return to FRT.")
            else:
                _notify(db, fe_ids, t, "PROGRESS", f"{t.code}: FRT {frt.code} daily progress", f"FRT {frt.name} ({frt.code}) updated {len(changes)} GP line{'s' if len(changes) != 1 else ''}{extra}.")
            if cases:  # Non-Doable by the FRT: the case is with the FE now – E1 / E2 are the FE's to fill / complete
                _notify(
                    db, rv._fe_users(db, t, [g for g, _c in cases]) - {user.id}, t, "NONDOABLE", f"{t.code}: Non-Doable proposed by FRT {frt.code}",
                    "; ".join(f"{c.ref} – GP {g.gp_code} ({g.gp_name})" for g, c in cases) + ". Fill / complete the E1 physical verification and the E2 justification, then forward it to the Area Manager.",
                )
        elif scope is not None:  # an FE reported: their Area Manager follows it too (dashboard + e-mail)
            from ..models import TicketRecipient

            ams = set(db.scalars(select(TicketRecipient.user_id).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "AM", TicketRecipient.user_id.is_not(None))))
            own_gps = [g for g in gps.values() if scope.owns(g)]
            _notify(
                db, ams - {user.id}, t, "PROGRESS", f"{t.code}: FE daily progress",
                f"FE {scope.name} submitted daily progress – {len(changes)} GP line{'s' if len(changes) != 1 else ''}{extra} · {sum(cumulative(g) for g in own_gps)} of their {len(own_gps)} GPs achieved.",
            )
            if cases:
                _notify(
                    db, ams - {user.id}, t, "NONDOABLE", f"{t.code}: Non-Doable proposed by FE {scope.name}",
                    "; ".join(f"{c.ref} – GP {g.gp_code} ({g.gp_name})" for g, c in cases) + ". The FE submits the E1 physical verification and the E2 justification for your review.",
                )
        t.updated_at = now()
        db.commit()
    except BaseException:
        db.rollback()
        files.remove(t.id, stored)
        raise
    return sub


def fe_options(db: Session, t: Ticket) -> list[dict[str, Any]]:
    """Field Engineers a GP of this ticket can be given to: the ticket's FE recipients with a dashboard account (they
    are the FEs of this Area Manager's ticket – an FE outside it cannot see the ticket at all)."""
    from ..models import TicketRecipient

    rs = db.scalars(
        select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE", TicketRecipient.user_id.is_not(None), TicketRecipient.can_work.is_(True)).order_by(TicketRecipient.name)
    )
    return [{"recipientId": r.id, "name": r.name, "email": r.email} for r in rs]


def reassign_gp(db: Session, t: Ticket, user: CurrentUser, gp_id: int, recipient_id: int, remark: str | None) -> TicketTaskGp:
    """Area Manager (or admin): give one GP of the ticket to another Field Engineer of the ticket. Only the GP's FE
    changes (ticket_task_gps.fe_name / fe_email = the new FE's mapping) – the target, the category, every daily line,
    proof and review step stay exactly as they are (they keep who submitted them). Recorded in the GP's history
    (REASSIGN) and the ticket events; both FEs are notified. Not possible once the Area Manager approved the GP or while
    it is in a Non-Doable case."""
    from ..models import TicketRecipient
    from . import nondoable as nd
    from . import review as rv
    from .service import _event, _notify, now

    if "AM" not in rv.roles_of(db, t, user):
        raise TaskError(403, "Only the Area Manager of this ticket can reassign a GP")
    if t.status == "CLOSED":
        raise TaskError(409, "This ticket is closed – GPs can no longer be reassigned")
    g = db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id, TicketTaskGp.id == gp_id).with_for_update()).first()
    if g is None:
        raise TaskError(404, "This GP is not part of the ticket")
    if g.review in rv.LOCKED:
        raise TaskError(409, f"GP {g.gp_code} is {rv.REVIEW_LABEL[g.review]} – it can no longer be reassigned")
    c = nd.open_case(db, g.id)
    if c is not None:
        raise TaskError(409, f"GP {g.gp_code} is in Non-Doable case {c.ref} – it cannot be reassigned while the case is open")
    r = db.get(TicketRecipient, recipient_id)
    if r is None or r.ticket_id != t.id or r.role != "FE" or r.user_id is None or not r.can_work:
        raise TaskError(422, "Choose a Field Engineer of this ticket who has a dashboard account")
    if len(r.name) > 120:
        raise TaskError(422, "The Field Engineer's name is too long")
    new = FeScope(r.name, r.fe_mail)
    if new.owns(g):
        raise TaskError(422, f"GP {g.gp_code} is already assigned to FE {r.name}")
    text = (remark or "").strip()[:MAX_REMARK] or None
    keys = {fe_key(x.name, x.fe_mail): x.user_id for x in db.scalars(select(TicketRecipient).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FE", TicketRecipient.user_id.is_not(None)))}
    old_user = keys.get(fe_key(g.fe_name, g.fe_email)) if g.fe_name else None
    old = g.fe_name or "FE not mapped"
    at = now()
    g.fe_name, g.fe_email = r.name, r.fe_mail
    role = "ADMIN" if user.is_admin and "AM" not in rv._ticket_roles(db, t, user) else "AM"
    note = f"FE: {old} → {r.name}" + (f" · {text}" if text else "")
    rv.record(db, t, g, user, role, "REASSIGN", note, at)
    _event(db, t, user, "REASSIGN", t.status, t.status, f"GP {g.gp_code} reassigned – {note}")
    body = f"{user.name} reassigned GP {g.gp_code} ({g.gp_name}) – {note}"
    _notify(db, {r.user_id} - {user.id}, t, "REASSIGN", f"{t.code}: GP {g.gp_code} assigned to you", body)
    if old_user is not None and old_user != r.user_id:
        _notify(db, {old_user} - {user.id}, t, "REASSIGN", f"{t.code}: GP {g.gp_code} given to another FE", body)
    t.updated_at = at
    db.commit()
    return g


MAX_FE_STEP_GPS = 500


def fe_check(db: Session, t: Ticket, user: CurrentUser, gp_ids: list[int], action: str, remark: str | None) -> int:
    """The FE checks the FRT's Daily Achievement (proof + remark) of one or more of their GPs (all or none):
    FE_VERIFY  the GP goes to the Area Manager (frt_stage FE_VERIFIED; a GP the AM had returned is with the AM again)
    FE_RETURN  back to the FRT with the reason (RETURNED_FRT) – also a GP the Area Manager returned to the FE.
    A remark is required. Admins may do it too (recorded as ADMIN). Each step is a TicketGpReview row (GP history)."""
    from ..models import TicketGpReview, TicketRecipient
    from . import nondoable as nd
    from . import review as rv
    from .service import _event, _notify, _reviewers, now

    if action not in FE_STEPS:
        raise TaskError(422, "Unknown step")
    if t.status == "CLOSED":
        raise TaskError(409, "This ticket is closed – no more steps")
    if db.get(TicketTask, t.id) is None:
        raise TaskError(404, "This ticket has no GP-wise task")
    scope = scope_of(db, t, user)
    fe = scope if isinstance(scope, FeScope) else None
    if fe is None and not user.is_admin:
        raise TaskError(403, "Only the Field Engineer of these GPs verifies the FRT's Daily Achievement")
    text = (remark or "").strip()[:MAX_REMARK] or None
    if text is None or len(text) < MIN_REMARK:
        raise TaskError(422, "Write your check remark (at least 3 characters)" if action == "FE_VERIFY" else "Write the reason for returning the GP to the FRT")
    ids = list(dict.fromkeys(int(i) for i in gp_ids))
    if not ids or len(ids) > MAX_FE_STEP_GPS:
        raise TaskError(422, f"Select between 1 and {MAX_FE_STEP_GPS} GPs")
    # FOR UPDATE (PostgreSQL): a GP is never verified / returned twice by two simultaneous requests
    gps = list(db.scalars(select(TicketTaskGp).where(TicketTaskGp.ticket_id == t.id, TicketTaskGp.id.in_(ids)).with_for_update()))
    if len(gps) != len(ids) or (fe is not None and not all(fe.owns(g) for g in gps)):
        raise TaskError(422, "A selected GP is not one of your GPs in this ticket")
    for g in gps:
        c = nd.open_case(db, g.id)
        if c is not None:
            raise TaskError(409, f"GP {g.gp_code} is in Non-Doable case {c.ref} – it is handled in Non-Doable Cases")
        if g.review in rv.LOCKED:
            raise TaskError(409, f"GP {g.gp_code} is {rv.REVIEW_LABEL[g.review]} – it can no longer be changed")
        if action == "FE_VERIFY" and not (g.frt_stage == "PENDING_FE" and g.review in (None, "RETURNED")):
            raise TaskError(409, f"GP {g.gp_code} is not waiting for your verification – the FRT has not submitted it (again). Reload the ticket.")
        if action == "FE_RETURN" and not ((g.frt_stage == "PENDING_FE" and g.review in (None, "RETURNED")) or (g.frt_stage == "FE_VERIFIED" and g.review == "RETURNED")):
            raise TaskError(409, f"GP {g.gp_code} cannot be returned to the FRT now – only a GP the FRT submitted, or one the Area Manager returned. Reload the ticket.")
    at = now()
    role = "FE" if fe is not None else "ADMIN"
    for g in gps:
        if action == "FE_VERIFY":
            g.frt_stage = "FE_VERIFIED"
            if g.review == "RETURNED":  # corrected and checked again: back with the Area Manager
                g.review, g.review_at = None, at
        else:
            g.frt_stage = "RETURNED_FRT"
        db.add(TicketGpReview(ticket_id=t.id, task_gp_id=g.id, role=role, action=action, category=g.gp_category, remark=text, actor_id=user.id, actor_name=user.name, at=at))
    n = len(gps)
    codes = ", ".join(g.gp_code for g in gps[:10]) + (f" … (+{n - 10})" if n > 10 else "")
    word = f"{n} GP{'s' if n != 1 else ''}"
    _event(db, t, user, "REVIEW", t.status, t.status, f"{FE_STEPS[action]}: {word} ({codes}) · {text}")
    body = f"{user.name}: {FE_STEPS[action]} – {word} ({codes}). Remark: {text}"
    if action == "FE_VERIFY":
        _notify(db, rv._role_users(db, t, "AM") - {user.id}, t, "REVIEW", f"{t.code}: {word} verified by the FE – your verification", body)
    else:
        mine = {frt_norm(g.frt_code) for g in gps} - {None}
        q = select(TicketRecipient.user_id, TicketRecipient.frt_code).where(TicketRecipient.ticket_id == t.id, TicketRecipient.role == "FRT", TicketRecipient.user_id.is_not(None))
        frts = {u for u, c in db.execute(q) if frt_norm(c) in mine}
        _notify(db, frts - {user.id}, t, "REVIEW", f"{t.code}: {word} returned to the FRT by the FE", body)
    _notify(db, _reviewers(db, t) - {user.id}, t, "REVIEW", f"{t.code}: {FE_STEPS[action]}", body)
    t.updated_at = at
    db.commit()
    return n


def frt_users_for(db: Session, codes: set[str]) -> list[User]:
    """Active dashboard accounts whose FRT code is one of these."""
    if not codes:
        return []
    return [u for u in db.scalars(select(User).where(User.is_active.is_(True), User.frt_code.is_not(None)).order_by(User.name)) if frt_norm(u.frt_code) in codes]


def add_frt_recipients(db: Session, t: Ticket, users: list[User] | None = None) -> list[Any]:
    """Put the FRT accounts of the ticket's GPs on it (role FRT, may work, dashboard only – no e-mail): every active user
    whose FRT code is the FRT code of a GP of the task. `users` = only these accounts. Somebody already on the ticket
    (same e-mail, any role) is not added again. Returns the new recipients."""
    from ..models import TicketRecipient

    codes = {c for c in (frt_norm(x) for x in db.scalars(select(TicketTaskGp.frt_code).where(TicketTaskGp.ticket_id == t.id, TicketTaskGp.frt_code.is_not(None)).distinct())) if c}
    cands = [u for u in (users if users is not None else frt_users_for(db, codes)) if u.is_active and frt_norm(u.frt_code) in codes]
    if not cands:
        return []
    on = {e.lower() for e in db.scalars(select(TicketRecipient.email).where(TicketRecipient.ticket_id == t.id))}
    out = []
    for u in cands:
        if u.email.lower() in on or u.id == t.created_by_id:
            continue
        r = TicketRecipient(
            ticket_id=t.id, role="FRT", name=u.name[:160], email=u.email.lower(), user_id=u.id, can_work=True, attach_workbook=False, email_status="NONE", frt_code=frt_norm(u.frt_code),
        )
        db.add(r)
        on.add(u.email.lower())
        out.append(r)
    db.flush()
    return out


def sync_frt_user(db: Session, user: User) -> int:
    """After an admin set / changed / removed a user's FRT code (or (re)activated the account): the open task tickets
    follow it – FRT rows of this account for another code are removed from open tickets, and the account is put on the
    open tickets whose GPs have its code (notified once per ticket). Closed and deleted tickets are never changed.
    Returns the number of tickets the user was added to."""
    from ..models import TicketRecipient
    from .service import _notify

    code = frt_norm(user.frt_code) if user.is_active else None
    open_ids = select(Ticket.id).where(Ticket.deleted_at.is_(None), Ticket.status != "CLOSED")
    for r in db.scalars(select(TicketRecipient).where(TicketRecipient.user_id == user.id, TicketRecipient.role == "FRT", TicketRecipient.ticket_id.in_(open_ids))):
        if frt_norm(r.frt_code) != code:
            db.delete(r)
    db.flush()
    added = 0
    if code:
        tids = set(db.scalars(select(TicketTaskGp.ticket_id).where(TicketTaskGp.ticket_id.in_(open_ids), TicketTaskGp.frt_code.is_not(None))))
        for tid in sorted(tids):
            t = db.get(Ticket, tid)
            if t is None or not any(frt_norm(c) == code for c in db.scalars(select(TicketTaskGp.frt_code).where(TicketTaskGp.ticket_id == tid))):
                continue
            if add_frt_recipients(db, t, [user]):
                added += 1
                _notify(db, {user.id}, t, "ASSIGNED", f"Ticket {t.code}: GPs of FRT {code}"[:200], f"You report the Daily Achievement of the GPs of FRT {code} in this ticket – your FE verifies it.")
    db.commit()
    return added


def workbook(db: Session, t: Ticket, task: TicketTask, original: bool, scope: FeScope | FrtScope | SmeView | None = None) -> bytes:
    """GP-wise workbook: the original assignment (achieved as at creation) or the latest progress report (cumulative,
    latest remarks, proof documents, plus the daily history). Identification and target columns are protected; Remarks
    are editable. `scope` = one Field Engineer's workbook (only the GPs mapped to them and only their history lines) or
    an SME's (only the GPs forwarded to them)."""
    import xlsxwriter

    gps = [g for g in _gps(db, t.id) if scope is None or scope.owns(g)]
    proof_of_gp: dict[int, list[str]] = {}
    if not original:
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)):
            proof_of_gp.setdefault(f.task_gp_id, []).append(f.file_name)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet("GP Task")
    title = wb.add_format({"bold": True, "font_size": 14})
    note = wb.add_format({"italic": True, "font_color": "#555555"})
    head = wb.add_format({"bold": True, "bg_color": "#0E7490", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter", "locked": True})
    cell = wb.add_format({"border": 1, "locked": True})
    num = wb.add_format({"border": 1, "num_format": "#,##0", "locked": True})
    edit = wb.add_format({"border": 1, "locked": False, "bg_color": "#FFF8E1", "text_wrap": True})
    total_f = wb.add_format({"bold": True, "border": 1, "bg_color": "#F1F5F9", "locked": True})
    kind = "Assignment (original)" if original else f"Progress report – {dt.datetime.now():%d %b %Y %H:%M}"
    target_total = sum(g.target for g in gps)
    gap_total = sum(g.target - (g.base_achieved if original else cumulative(g)) for g in gps)
    fe = scope if isinstance(scope, FeScope) else None
    who = (
        f"FE {fe.name} ({task.am_name})" if fe is not None
        else f"FRT {scope.code} – {scope.name} ({task.am_name})" if isinstance(scope, FrtScope)
        else f"{scope.kind} – GPs forwarded to you ({task.am_name})" if isinstance(scope, ReviewerView) else task.am_name
    )
    from ..models import TicketUnit
    from .units import HIER_COLS, HIER_NOTE, gp_tickets, hier_values, sync

    if db.scalar(select(TicketUnit.id).where(TicketUnit.ticket_id == t.id).limit(1)) is None:
        # the assignment workbook is written while the ticket is generated – its FE / FRT tickets first (same
        # transaction, the same rows the commit would create), so the workbook carries their IDs
        db.flush()
        sync(db, t.id)
    hier = gp_tickets(db, [g.id for g in gps])  # the AM / FE / FRT ticket IDs and target GPs of each GP row
    own = next((hier[g.id]["feCode"] for g in gps if g.id in hier and hier[g.id]["feCode"]), None) if fe is not None else None
    ws.write_string(0, 0, f"{t.code}{f' → FE ticket {own}' if own else ''} · {who} · Week {task.week_code[2:]} ({task.week_start:%d %b} – {task.week_end:%d %b %Y}) · {kind}", title)
    fe_part = f" · Field Engineer: {fe.name}{f' ({fe.mail})' if fe.mail else ''}" if fe is not None else ""
    ws.write_string(1, 0, f"Circle: {task.circle or '—'} · CBH: {task.cbh_name or '—'} · Area Manager: {task.am_name}{fe_part} · {len(gps)} GPs · total weekly target {target_total} · remaining gap {gap_total}", note)
    ws.write_string(
        2, 0,
        f"Weekly target = 1 GP each (Planned Date in the week). Existing achievement = AMC Date in the master data at assignment (data as of {task.data_as_of:%d %b %Y}, {task.source_file}). "
        + ("Daily Achievement and Remarks can be filled in; " if original else "Daily Achievement = GPs reported in the daily progress of the ticket; ")
        + "the dashboard is the system of record – submit daily progress in the ticket. "
        + f"Last columns – ticket IDs: {HIER_NOTE}.",
        note,
    )
    headers = [
        ("S.No.", 6), ("Circle", 12), ("Area Manager", 18), ("FE Name", 18), ("Business Area", 16), ("District", 16), ("Block Name", 18), ("GP Code", 12), ("GP Name", 24),
        ("Weekly Target", 10), ("Existing Achievement", 12), ("Remaining Gap", 11), ("Daily Achievement", 12), ("Remarks", 40), ("Proof Document", 36),
        ("Type", 9), ("Planned Date", 12), ("Ach Date (Ready)", 13), ("AMC Date", 12),
    ]
    hier_at = len(headers)  # ticket hierarchy columns after every existing column
    headers += HIER_COLS
    hr = 4
    for c, (h, wdt) in enumerate(headers):
        ws.set_column(c, c, wdt)
        ws.write_string(hr, c, h, head)
    for i, g in enumerate(gps, start=1):
        r = hr + i
        ach = g.base_achieved if original else cumulative(g)
        vals = [i, g.circle, task.am_name, g.fe_name or "FE not mapped", g.business_area or "", g.district or "", g.block or "", g.gp_code, g.gp_name]
        for c, v in enumerate(vals):
            (ws.write_number(r, c, v, num) if isinstance(v, int) else ws.write_string(r, c, str(v), cell))
        ws.write_number(r, 9, g.target, num)
        ws.write_number(r, 10, g.base_achieved, num)
        ws.write_number(r, 11, g.target - ach, num)
        if original:
            ws.write_blank(r, 12, None, edit)
        else:
            ws.write_number(r, 12, g.reported, num)
        ws.write_string(r, 13, "" if original else (g.remarks or ""), edit)
        ws.write_string(r, 14, "" if original else (", ".join(proof_of_gp.get(g.id, [])) or "Proof Not Uploaded"), cell)
        ws.write_string(r, 15, {"WEEK": "This week", "ADDED": "Added by FE"}.get(g.kind, "Pending"), cell)
        for c, v in ((16, g.planned_date), (17, g.ready_date), (18, g.amc_date)):
            ws.write_string(r, c, f"{v:%d-%m-%Y}" if v else "", cell)
        for c, v in enumerate(hier_values(hier.get(g.id)), start=hier_at):
            (ws.write_number(r, c, v, num) if isinstance(v, int) else ws.write_string(r, c, str(v), cell))
    tr = hr + len(gps) + 1
    ws.write_string(tr, 8, "Total", total_f)
    for c, v in ((9, target_total), (10, sum(g.base_achieved for g in gps)), (11, gap_total)):
        ws.write_number(tr, c, v, total_f)
    if not original:
        ws.write_number(tr, 12, sum(g.reported for g in gps), total_f)
    ws.freeze_panes(hr + 1, 0)
    ws.protect("", {"autofilter": True, "sort": True, "format_columns": True})
    if not original:
        hs = wb.add_worksheet("Daily History")
        for c, (h, wdt) in enumerate([("Submitted", 18), ("Submitted By", 20), ("GP Code", 12), ("GP Name", 24), ("Block", 18), ("Achieved Today", 12), ("Cumulative", 11), ("Remaining Gap", 12), ("Remark", 40), ("Status", 26), ("Proof", 40)]):
            hs.set_column(c, c, wdt)
            hs.write_string(0, c, h, head)
        subs = list(db.scalars(select(TicketProgress).where(TicketProgress.ticket_id == t.id).order_by(TicketProgress.submitted_at, TicketProgress.id)))
        by_gp = {g.id: g for g in gps}
        proof: dict[int, list[str]] = {}
        for f in db.scalars(select(TicketProgressFile).where(TicketProgressFile.ticket_id == t.id).order_by(TicketProgressFile.id)):
            proof.setdefault(f.progress_line_id, []).append(f.file_name)
        r = 1
        for s in subs:
            for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.progress_id == s.id).order_by(TicketProgressLine.id)):
                g = by_gp.get(ln.task_gp_id)
                if g is None:  # another FE's GP (FE workbook)
                    continue
                at = s.submitted_at if s.submitted_at.tzinfo else s.submitted_at.replace(tzinfo=dt.UTC)
                hs.write_string(r, 0, at.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%d %b %Y %H:%M IST"), cell)
                for c, v in enumerate([s.submitted_by_name, g.gp_code if g else "", g.gp_name if g else "", (g.block or "") if g else ""], start=1):
                    hs.write_string(r, c, v, cell)
                hs.write_number(r, 5, ln.achieved_today, num)
                hs.write_number(r, 6, ln.cumulative, num)
                hs.write_number(r, 7, ln.gap, num)
                hs.write_string(r, 8, ln.remark or "", cell)
                hs.write_string(r, 9, category_label(ln.category) or ("Done" if line_status(ln, g) == "DONE" else "Pending"), cell)
                hs.write_string(r, 10, ", ".join(proof.get(ln.id, [])) or "Proof Not Uploaded", cell)
                r += 1
        hs.freeze_panes(1, 0)
    wb.close()
    return buf.getvalue()


def assignment_path(t: Ticket, task: TicketTask):
    if not task.assignment_file:
        return None
    try:
        return files.path_of(t.id, task.assignment_file)
    except files.AttachmentError:
        return None


def file_name(task: TicketTask, original: bool, scope: FeScope | FrtScope | SmeView | None = None) -> str:
    def safe(v: str, fallback: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in v).strip("_")[:40] or fallback

    if isinstance(scope, FeScope):
        who = f"FE_{safe(scope.name, 'FieldEngineer')}"
    elif isinstance(scope, FrtScope):
        who = f"FRT_{safe(scope.code, 'FRT')}"
    elif isinstance(scope, ReviewerView):
        who = f"{scope.kind}_{safe(task.am_name, 'AreaManager')}"
    else:
        who = safe(task.am_name, "AreaManager")
    return f"{who}_Weekly_GP_Assignment_Week_{task.week_code[2:]}{'' if original else '_Progress'}.xlsx"


def progress_count(db: Session, ticket_id: int) -> int:
    return db.scalar(select(func.count()).where(TicketProgress.ticket_id == ticket_id)) or 0
