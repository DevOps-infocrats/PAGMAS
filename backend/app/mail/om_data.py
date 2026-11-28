"""O&M Daily Dashboard e-mail – the figures of ONE circle (no HTML here).

Every number comes from the functions behind the dashboard pages, so the e-mail can never disagree with the screen:

  HoTo & AMC (blocks, GPs, RKM, incremental)   Circle Overview  (analytics.views.overview, latest week of the data)
  HoTo RKM                                      the Management Review rule: TOTAL RKM of the GPs with HoTo by the week end
  AMC GPs month-wise                            Management Review (month columns + current month to date, Jun baseline)
  One-time up GPs (this month MTD vs last)      daily data: availability > 0 on any day, day 1 .. data date, same days
                                                of the previous month
  Month / week target, ready, achieved          AMC Conversion → Plan vs Execution (analytics.amc_plan.amc_plan_summary)
  Uptime (MTD) and the weekly trend             Circle Overview (MTD) · weekly band counts (analytics.views._band_series)
  Field force                                   O&M KEY NUMBERS "FRT Count (O&M)" · FRT codes of the circle's GPs in the
                                                Escalation Matrix that have an active dashboard login (FRT on portal)

Circle isolation: the context is computed once per run for all circles, but `circle_view` only ever reads the rows /
entries of the one circle it is asked for – the renderer never receives another circle's data.

The current week is usually still running: its label is "WTD W-48" (week to date) until the data reaches the week
end, so the reader sees that the week is not complete; it updates with every upload.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..analytics import views
from ..analytics.amc_plan import amc_plan_summary
from ..analytics.metrics import BANDS
from ..analytics.review import _source_circle_kpis, management_review
from ..analytics.review_periods import latest_completed_week, previous_week
from ..analytics.store import Store

TREND_WEEKS = 5  # weeks in the uptime trend bars (ending with the latest week of the data)
DIST_GROUPS: list[tuple[str, list[str]]] = [  # uptime distribution of the AMC GPs (latest week), best first
    (">98%", [">98%"]),
    ("95–98%", ["95–98%"]),
    ("90–95%", ["90–95%"]),
    ("75–90%", ["75–85%", "85–90%"]),
    ("<75%", ["0%", "0–30%", "30–50%", "50–75%"]),
]
BELOW_90 = [lb for lb, lo, hi in BANDS if hi <= 90]  # block bands below the penalty threshold (0% included)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def week_label(week: Any, data_as_of: dt.date) -> str:
    """"W-47" for a finished week, "WTD W-48" while the data has not reached the week end."""
    return f"W-{week.number}" if week.end <= data_as_of else f"WTD W-{week.number}"


@dataclass
class Context:
    """Everything shared by the circles of one run – computed once from ONE snapshot of the active data."""

    store: Store
    dataset_id: int
    data_as_of: dt.date
    source_file: str
    week: Any  # latest week of the data (usually still running)
    week_label: str
    overview: dict[str, Any]
    review: dict[str, Any] | None
    sheets: dict[str, dict[str, dict[str, float]]]
    trend_weeks: list[Any] = field(default_factory=list)
    plan: dict[str, Any] | None = None  # AMC Conversion → Plan vs Execution of the latest week (management view)

    @classmethod
    def build(cls, store: Store) -> Context:
        weeks = store.weeks
        latest = store.latest_week
        prev = previous_week(store, latest) or latest
        ov = views.overview(store, latest.code, prev.code)
        done = latest_completed_week(store)
        rv = None
        if done is not None:
            before = previous_week(store, done)
            if before is not None:
                rv = management_review(store, done.code, before.code, [])
        i = [w.code for w in weeks].index(latest.code)
        try:
            plan = amc_plan_summary(store, latest.code)
        except Exception:  # noqa: BLE001 – a file without a usable plan: the tiles show "–", the mail still goes
            plan = None
        return cls(
            store=store, dataset_id=store.dataset_id, data_as_of=store.data_as_of, source_file=store.file_name or "",
            week=latest, week_label=week_label(latest, store.data_as_of), overview=ov, review=rv,
            sheets=_source_circle_kpis(store), trend_weeks=weeks[max(0, i - TREND_WEEKS + 1): i + 1], plan=plan,
        )

    def circles(self) -> list[dict[str, Any]]:
        """[{id, name}] of the circles in the data (display order of the Circle Overview)."""
        return [{"id": c["id"], "name": c["name"]} for c in self.overview.get("stateDetails", [])]


def _review_row(rows: list[dict[str, Any]] | None, cid: str) -> dict[str, Any]:
    return next((r for r in rows or [] if r.get("id") == cid or r.get("circleId") == cid), {})


def circle_view(ctx: Context, circle_id: str, frt_on_portal: int | None = None, remarks: str | None = None) -> dict[str, Any]:
    """The e-mail content of one circle (plain values – the renderer formats them). Raises KeyError for an unknown
    circle."""
    store = ctx.store
    d = next(c for c in ctx.overview.get("stateDetails", []) if c["id"] == circle_id)
    g = store.gps
    mask = (g["circle_id"] == circle_id).to_numpy()
    rows = g[mask]

    # ---- 1 · HoTo & network status (blocks, GPs, route km – "done / scope")
    hoto = pd.to_datetime(rows["hoto_date"], errors="coerce") <= pd.Timestamp(ctx.week.end)
    hoto_rkm = round(float(pd.to_numeric(rows.loc[hoto, "total_rkm"], errors="coerce").sum()), 2)
    total_rkm = _num(d.get("totalRkm"))
    hoto_s = {
        "blocks": d.get("hotoDoneBlocks"), "blocksScope": d.get("blocks"),
        "gps": d.get("hotoDoneGps"), "gpsScope": d.get("revisedExisting"),
        "rkm": hoto_rkm, "rkmScope": total_rkm,
        # all GPs of the circle as on the portal (Circle Overview): HoTo done + pending + converted to NP / closed
        "total": d.get("existingGps"), "pending": d.get("hotoPendingGps"), "npClosed": d.get("convertedOrClosed"),
        "gpsPct": _pct(d.get("hotoDoneGps"), d.get("revisedExisting")),
        "blocksPct": _pct(d.get("hotoDoneBlocks"), d.get("blocks")),
        "rkmPct": _pct(hoto_rkm, total_rkm),
    }

    # ---- 2 · AMC status
    rv = ctx.review or {}
    sec = (rv.get("sections") or {}).get(circle_id) or {}
    periods = rv.get("periods") or []
    amc_series = next((k["values"] for k in sec.get("kpis", []) if k["key"] == "amcGps"), [])
    months: list[dict[str, Any]] = []
    card = next((c for c in ((rv.get("targetsPage") or {}).get("circleCards") or {}).get("cards", []) if c["id"] == circle_id), None)
    if card and card.get("baseline"):
        months.append({"label": str(card["baseline"]["label"])[:3], "value": card["baseline"]["value"]})
    for p, v in zip(periods, amc_series):
        if p["kind"] == "month":
            months.append({"label": p["label"][:3], "value": v})
    # the current month: the AMC GPs as of the data date (Circle Overview) – the column of the running month
    months.append({"label": f"{ctx.data_as_of:%b} MTD", "value": d.get("amcGps"), "current": True})
    amc_s = {
        "gps": d.get("amcGps"), "gpsScope": d.get("revisedExisting"), "pct": _num(d.get("amcPct")),
        "incremental": d.get("incrementalGps"),
        "rkm": _num(d.get("amcRkm")), "rkmScope": total_rkm, "rkmPct": _pct(_num(d.get("amcRkm")), total_rkm),
        "months": months,
    }

    # ---- 3 · one-time up & AMC targets (shown ABOVE the uptime trend)
    #   one-time up = GPs with availability > 0 on at least one day (the dashboard's one-time-up rule), day 1 .. the
    #   data date of this month vs the same days of the previous month (daily data of the file)
    #   month / week target, ready, achieved = AMC Conversion → Plan vs Execution (management view): Target = Planned
    #   Date in the period, Ready = Ach Date, Achieved = AMC Date – up to the plan's data date
    plan_row = next((r for r in (ctx.plan or {}).get("rows", []) if r.get("id") == circle_id), {})
    week_p = (ctx.plan or {}).get("week") or {}
    otu = one_time_up_mtd(store, mask, ctx.data_as_of)
    #   the month's one-time-up target (O&M KEY NUMBERS, Management Review) – achievement / gap against this month's MTD
    tgt = _review_row((rv.get("targets") or {}).get("rows"), circle_id)
    target = _num(tgt.get("target"))
    #   month-wise one-time-up rows of the circle sheet (4th report) – only when the file has them
    sheet = ctx.sheets.get(str(d["name"])) or ctx.sheets.get(str(d["name"]).upper()) or {}
    gps_by_month = sheet.get("oneTimeUpGps", {})
    month_keys = sorted(k for k in gps_by_month if len(k) == 7)  # "YYYY-MM"
    otu_s = {
        **otu,
        "target": target, "targetLabel": (rv.get("targets") or {}).get("label"), "pct": _pct(otu["current"], target),
        "gap": (target - otu["current"]) if target is not None and otu["current"] is not None else None,
        "monthly": [{"label": dt.date.fromisoformat(k + "-01").strftime("%b-%y"), "value": gps_by_month[k]} for k in month_keys[-8:]],
        "monthlyAmc": (sheet.get("oneTimeUpAmc") or {}).get(month_keys[-1]) if month_keys else None,
        "monthlyNonAmc": (sheet.get("oneTimeUpNonAmc") or {}).get(month_keys[-1]) if month_keys else None,
        "month": {"label": ((ctx.plan or {}).get("month") or {}).get("label"), "target": plan_row.get("monthTarget"),
                  "ready": plan_row.get("monthReady"), "achieved": plan_row.get("monthConverted")},
        "week": {"label": (f"W-{week_p['number']}" if week_p.get("complete") else f"WTD W-{week_p['number']}") if week_p.get("number") else None,
                 "complete": bool(week_p.get("complete")), "target": plan_row.get("weekTarget"), "ready": plan_row.get("weekReady"),
                 "achieved": plan_row.get("weekConverted")},
        "planAsOf": (ctx.plan or {}).get("asOf"), "hasPlan": bool((ctx.plan or {}).get("hasPlan")),
        "table": one_time_up_table(store, mask, ctx.data_as_of, ctx.week.code),
    }

    # ---- 4 · uptime: MTD tiles + the weekly trend ending with the latest week (WTD while it runs)
    _s, gp_table = views._band_series(store, mask, ctx.trend_weeks, per_block=False)
    _s, blk_table = views._band_series(store, mask, ctx.trend_weeks, per_block=True)
    labels = [week_label(w, ctx.data_as_of) for w in ctx.trend_weeks]
    last = gp_table[-1] if gp_table else None
    reported = last["reported"] if last else 0
    dist = [{"label": name, "value": sum(last["counts"][b] for b in bands) if last else 0} for name, bands in DIST_GROUPS]
    for x in dist:
        x["pct"] = _pct(x["value"], reported)
    pen = penalty_block_gps(store, mask, ctx.week.code)
    up_s = {
        "above98": d.get("gpsAbove98"), "amcGps": d.get("amcGps"), "above98Pct": _pct(d.get("gpsAbove98"), d.get("reportingGps")),
        "atZero": d.get("gpsAtZero"), "reporting": d.get("reportingGps"),
        # GPs < 90% INSIDE the penalty blocks (blocks whose mean AMC availability is < 90%), MTD
        "below90": pen["below90"], "penaltyGps": pen["gps"], "below90Pct": _pct(pen["below90"], pen["gps"]), "penaltyBlocksFound": pen["blocks"],
        "penaltyBlocks": d.get("penaltyBlocks"),
        "distribution": dist, "distributionWeek": labels[-1] if labels else None, "distributionGps": reported,
        # the same bands from each AMC GP's MTD uptime (the All Circles page shows the month to date)
        **mtd_distribution(store, mask, ctx.week.code),
        "trendAbove98": [{"label": lb, "value": t["counts"][">98%"], "current": i == len(labels) - 1} for i, (lb, t) in enumerate(zip(labels, gp_table))],
        "trendBlocksBelow90": [{"label": lb, "value": sum(t["counts"][b] for b in BELOW_90), "current": i == len(labels) - 1} for i, (lb, t) in enumerate(zip(labels, blk_table))],
    }

    # ---- 5 · field force
    frt_row = _review_row(((rv.get("targetsPage") or {}).get("weekly") or {}).get("rows"), circle_id)
    frt_count = _num(frt_row.get("frt"))
    ff_s = {"frtCount": int(frt_count) if frt_count is not None else None, "onPortal": frt_on_portal, "onPortalPct": _pct(frt_on_portal, frt_count)}

    return {
        "circleId": circle_id, "circle": d["name"], "dataAsOf": ctx.data_as_of.isoformat(), "week": ctx.week_label,
        "weekComplete": ctx.week.end <= ctx.data_as_of, "weekRange": f"{ctx.week.start:%d %b} – {ctx.week.end:%d %b %Y}",
        "sourceFile": ctx.source_file, "datasetId": ctx.dataset_id,
        "hoto": hoto_s, "amc": amc_s, "oneTimeUp": otu_s, "uptime": up_s, "fieldForce": ff_s,
        "remarks": [ln.strip() for ln in (remarks or "").splitlines() if ln.strip()],
    }


def one_time_up_mtd(store: Store, mask: Any, as_of: dt.date) -> dict[str, Any]:
    """One-time-up GPs month to date: GPs (all GP rows of the scope) with availability > 0 on at least one day from the
    1st up to `as_of`, and the same days of the previous month (daily data). None where the file has no such days."""
    import calendar

    daily = store.daily
    g = store.gps[mask]
    first = as_of.replace(day=1)
    prev_last = first - dt.timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    prev_to = prev_first.replace(day=min(as_of.day, calendar.monthrange(prev_first.year, prev_first.month)[1]))

    def count(lo: dt.date, hi: dt.date) -> int | None:
        cols = [c for c in daily.columns if isinstance(c, dt.date) and lo <= c <= hi]
        if not cols:
            return None
        return int((daily.loc[g.index, cols].fillna(0) > 0).any(axis=1).sum())

    cur, prev = count(first, as_of), count(prev_first, prev_to)
    return {
        "current": cur, "previous": prev, "delta": (cur - prev) if cur is not None and prev is not None else None,
        "currentLabel": f"{as_of:%b} MTD", "previousLabel": f"{prev_first:%b} MTD",
        "range": f"1–{as_of.day} {as_of:%b}", "previousRange": f"1–{prev_to.day} {prev_first:%b}",
    }


def mtd_distribution(store: Store, mask: Any, week_code: str) -> dict[str, Any]:
    """Uptime distribution of the scope's AMC GPs by their MTD uptime (the DIST_GROUPS bands, same band rule as the
    weekly distribution) – {"distributionMtd": [{label, value, pct}], "distributionMtdGps": reporting GPs}."""
    from ..analytics.metrics import band_counts

    g = store.gps[mask]
    wf = store.week_frame(week_code).loc[g.index]
    mtd = wf["mtd"].where(wf["amc"])
    counts = band_counts(mtd)
    reported = int(mtd.notna().sum())
    dist = [{"label": name, "value": sum(counts[b] for b in bands)} for name, bands in DIST_GROUPS]
    for x in dist:
        x["pct"] = _pct(x["value"], reported)
    return {"distributionMtd": dist, "distributionMtdGps": reported}


def one_time_up_table(store: Store, mask: Any, as_of: dt.date, week_code: str) -> dict[str, Any]:
    """Month-wise one-time-up GPs of the scope (the circle report's table):
      base month + the last four full months before last month   monthly uptime > 0 (= up on at least one day)
      last month MTD / this month MTD                             daily data, day 1 .. data date, the same days
      AMC / Non-AMC                                               this month's one-time-up GPs split by the AMC flag
    {"columns": [{key, label, current?}], "values": {key: GPs}, "note": text}."""
    import calendar

    g = store.gps[mask]
    first = as_of.replace(day=1)
    prev_first = (first - dt.timedelta(days=1)).replace(day=1)
    prev_to = prev_first.replace(day=min(as_of.day, calendar.monthrange(prev_first.year, prev_first.month)[1]))
    daily = store.daily

    def up(lo: dt.date, hi: dt.date) -> pd.Series | None:
        cols = [c for c in daily.columns if isinstance(c, dt.date) and lo <= c <= hi]
        return (daily.loc[g.index, cols].fillna(0) > 0).any(axis=1) if cols else None

    months = [m for m in store.monthly.columns if str(m) < f"{prev_first:%Y-%m}"]
    shown = ([months[0]] + [m for m in months[-4:] if m != months[0]]) if months else []
    monthly = store.monthly.reindex(g.index)
    values: dict[str, int | None] = {str(m): int((monthly[m].fillna(0) > 0).sum()) for m in shown}
    now, prev = up(first, as_of), up(prev_first, prev_to)
    amc = store.week_frame(week_code).loc[g.index, "amc"].fillna(False).astype(bool)
    values.update(prev=int(prev.sum()) if prev is not None else None, cur=int(now.sum()) if now is not None else None,
                  amc=int((now & amc).sum()) if now is not None else None, nonAmc=int((now & ~amc).sum()) if now is not None else None)
    cols = [{"key": str(m), "label": dt.date.fromisoformat(f"{m}-01").strftime("%b-%y") + (" base" if i == 0 else "")} for i, m in enumerate(shown)]
    cols += [{"key": "prev", "label": f"{prev_first:%b} MTD"}, {"key": "cur", "label": f"{as_of:%b} MTD", "current": True},
             {"key": "amc", "label": "AMC"}, {"key": "nonAmc", "label": "Non-AMC"}]
    note = f"{prev_first:%b} MTD = 1–{prev_to.day} {prev_first:%b}, {as_of:%b} MTD = 1–{as_of.day} {as_of:%b} (same days) · AMC / Non-AMC = split of {as_of:%b} MTD"
    return {"columns": cols, "values": values, "note": note}


def penalty_block_gps(store: Store, mask: Any, week_code: str) -> dict[str, int]:
    """The penalty blocks of the scope (mean AMC MTD availability < the penalty threshold – the Circle Overview rule)
    and, inside them, the reporting AMC GPs and those with MTD availability < the threshold (same rounding)."""
    from ..config import get_settings

    thr = get_settings().penalty_threshold
    g = store.gps[mask]
    wf = store.week_frame(week_code).loc[g.index]
    mtd = wf["mtd"].where(wf["amc"])
    block_avail = mtd.groupby(g["block_id"]).mean()
    pen_blocks = set(block_avail[block_avail < thr].index)
    inside = g["block_id"].isin(pen_blocks)
    vals = mtd[inside]
    return {"blocks": len(pen_blocks), "gps": int(vals.notna().sum()), "below90": int((vals.round(2) < thr).sum())}


def frt_on_portal(store: Store, circle_id: str, db: Any) -> int | None:
    """FRT teams of the circle (FRT codes of its GPs in the Escalation Matrix) with an active dashboard login."""
    from sqlalchemy import select

    from ..models import User
    from ..tickets.task import frt_norm
    from .audience import matrix_frame

    m = matrix_frame(store)
    if m is None or m.empty or "frt_code" not in m.columns:
        return None
    codes = {c for c in (frt_norm(x) for x in m.loc[m["circle_id"] == circle_id, "frt_code"].dropna()) if c}
    logins = {frt_norm(c) for c in db.scalars(select(User.frt_code).where(User.frt_code.is_not(None), User.is_active.is_(True)))} - {None}
    return len(codes & logins)
