"""Read-only analytics endpoints (any signed-in user)."""

from __future__ import annotations

import datetime as dt
import threading
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analytics import views
from ..analytics.amc_conversion import amc_conversion
from ..analytics.amc_plan import amc_plan_area_managers, amc_plan_summary, amc_plan_timeline, targets_stamp
from ..analytics.drilldown import KpiKind, SortKey, kpi_list, kpi_xlsx
from ..analytics.review import management_review
from ..analytics.review_periods import latest_completed_week
from ..analytics.review_targets import PLAN_FILE
from ..analytics.store import Store, get_store
from ..config import get_settings
from ..db import get_db
from ..models import Dataset, ValidationIssue
from ..reports.pdf import render_weekly_report
from ..reports.review_pptx import SECTIONS as DECK_SECTIONS, render_review_deck
from ..security.deps import CurrentUser, audit, get_current_user

router = APIRouter(tags=["analytics"], dependencies=[Depends(get_current_user)])

WeekId = Annotated[str, Query(pattern=r"^W-\d{1,2}$", description="Source week id, e.g. W-41")]
OptWeekId = Annotated[str | None, Query(pattern=r"^W-\d{1,2}$")]
CircleId = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]
BlockId = Annotated[str, Path(pattern=r"^[a-z]{2}-[A-Za-z0-9]{1,20}$")]
GpCode = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,40}$")]
OptCircle = Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}$")]
OptDistrict = Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}~[a-z0-9-]{1,80}$")]
OptDate = Annotated[dt.date | None, Query(description="AMC plan: as of this date (YYYY-MM-DD)")]
OptBlock = Annotated[str | None, Query(pattern=r"^[a-z]{2}-[A-Za-z0-9]{1,20}$")]


def _period(store: Store, week: str | None, compare: str | None) -> tuple[str, str]:
    codes = [w.code for w in store.weeks]
    week = week or codes[-1]
    if week not in codes:
        raise HTTPException(404, f"Week {week} is not available in the imported data ({codes[0]}–{codes[-1]})")
    if compare is None:
        i = codes.index(week)
        compare = codes[max(0, i - 1)]
    if compare not in codes:
        raise HTTPException(404, f"Week {compare} is not available in the imported data")
    return week, compare


@router.get("/meta")
def meta(store: Store = Depends(get_store)) -> dict:
    return views.meta(store)


@router.get("/overview")
def overview(week: OptWeekId = None, compare: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    w, c = _period(store, week, compare)
    return store.memo(("overview", w, c), lambda: views.overview(store, w, c))


@router.get("/circles/{circle_id}/insights")
def circle_insights(circle_id: CircleId, week: OptWeekId = None, compare: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    w, c = _period(store, week, compare)
    return store.memo(("circle", circle_id, w, c), lambda: views.circle_insights(store, circle_id, w, c))


@router.get("/blocks/{block_id}/insights")
def block_insights(block_id: BlockId, week: OptWeekId = None, compare: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    w, c = _period(store, week, compare)
    return store.memo(("block", block_id, w, c), lambda: views.block_insights(store, block_id, w, c))


@router.get("/gps")
def list_gps(
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 50,
    store: Store = Depends(get_store),
) -> dict:
    w, _ = _period(store, week, None)
    return views.list_gps(store, w, circle, district, block, search, page, page_size)


XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KpiSearch = Annotated[str | None, Query(max_length=80)]


@router.get("/kpi-lists/{kind}.xlsx")
def kpi_drilldown_xlsx(
    request: Request,
    kind: Annotated[KpiKind, Path()],
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: KpiSearch = None,
    sort: SortKey | None = None,
    date: OptDate = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
    db: Session = Depends(get_db),
) -> Response:
    """The whole (filtered) KPI list as an Excel workbook. Declared before /kpi-lists/{kind} so ".xlsx" is not read as a kind."""
    w, _ = _period(store, week, None)
    data, name = kpi_xlsx(store, kind, w, circle, district, block, search, sort, date)
    audit(db, "kpi_list_xlsx_download", request, user.id, f"{kind} · {w} · dataset {store.dataset_id} · circle={circle or 'all'} district={district or 'all'} block={block or 'all'}")
    return Response(data, media_type=XLSX_MEDIA, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/kpi-lists/{kind}")
def kpi_drilldown(
    kind: Annotated[KpiKind, Path()],
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: KpiSearch = None,
    sort: SortKey | None = None,
    date: OptDate = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    store: Store = Depends(get_store),
) -> dict:
    """The GPs / blocks behind a Circle Overview KPI card (same rule and week as the card)."""
    w, _ = _period(store, week, None)
    return kpi_list(store, kind, w, circle, district, block, search, sort, page, page_size, date)


@router.get("/gps/{gp_code}")
def gp_detail(gp_code: GpCode, week: OptWeekId = None, store: Store = Depends(get_store), db: Session = Depends(get_db)) -> dict:
    w, _ = _period(store, week, None)
    issues = [
        {"code": i.code, "message": i.message, "severity": i.severity}
        for i in db.scalars(
            select(ValidationIssue).where(ValidationIssue.dataset_id == store.dataset_id, ValidationIssue.gp_code == gp_code).limit(50)
        )
    ]
    return views.gp_detail(store, gp_code, w, issues)


@router.get("/search")
def search(q: Annotated[str, Query(min_length=1, max_length=80)], store: Store = Depends(get_store)) -> list[dict]:
    return views.search(store, q)


def _data_quality(db: Session, store: Store) -> list[dict]:
    counts = dict(
        db.execute(
            select(ValidationIssue.code, func.count()).where(ValidationIssue.dataset_id == store.dataset_id).group_by(ValidationIssue.code)
        ).all()
    )
    labels = {
        "OLT_INVALID": ("GPs with an invalid OLT location (date/number)", "warning"),
        "OLT_MISSING": ("GPs with OLT location missing", "warning"),
        "RKM_MISMATCH": ("GPs where BSNL + BBNL ≠ TOTAL RKM", "warning"),
        "AMC_WITHOUT_HOTO": ("AMC GPs without a HOTO date", "critical"),
        "INVALID_NUMBER": ("Non-numeric or negative fibre values", "warning"),
        "INVALID_AVAILABILITY": ("Availability values outside 0–100%", "critical"),
        "DUPLICATE_GP": ("Duplicate GP codes (ignored rows)", "critical"),
        "ROW_REJECTED": ("Rows rejected (no GP code / circle)", "critical"),
    }
    out = [{"label": label, "count": int(counts.get(code, 0)), "severity": sev} for code, (label, sev) in labels.items()]
    na = int((store.week_frame(store.latest_week.code)["amc"] & store.week_frame(store.latest_week.code)["mtd"].isna()).sum())
    out.insert(0, {"label": "AMC GPs with no availability reported (NA)", "count": na, "severity": "warning"})
    return out


@router.get("/reports/weekly")
def weekly_report(
    week: OptWeekId = None,
    compare: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    store: Store = Depends(get_store),
    db: Session = Depends(get_db),
) -> dict:
    w, c = _period(store, week, compare)
    return store.memo(("weekly", w, c, circle, district, block), lambda: views.weekly_report(store, w, c, circle, district, block, _data_quality(db, store)))


@router.get("/reports/weekly.pdf")
def weekly_report_pdf(
    week: OptWeekId = None,
    compare: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
    db: Session = Depends(get_db),
) -> Response:
    w, c = _period(store, week, compare)
    report = views.weekly_report(store, w, c, circle, district, block, _data_quality(db, store))
    pdf = render_weekly_report(report, generated_by=user.name)
    name = f"weekly_report_{w}_vs_{c}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- management review

_review_cache: OrderedDict[tuple[int, str, str], dict[str, Any]] = OrderedDict()
_review_lock = threading.Lock()
PPTX_MEDIA = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _review(store: Store, db: Session, week: str, compare: str) -> dict[str, Any]:
    """Review payload, memoised per dataset + period + plan-file version (the web page and the deck share it).
    A new master data file (new dataset) or a saved change to review_plan.json is picked up without a restart."""
    plan = get_settings().data_dir / PLAN_FILE
    key = (store.dataset_id, week, compare, plan.stat().st_mtime if plan.exists() else None)
    with _review_lock:
        if key in _review_cache:
            _review_cache.move_to_end(key)
            return _review_cache[key]
    payload = management_review(store, week, compare, _data_quality(db, store))
    with _review_lock:
        _review_cache[key] = payload
        while len(_review_cache) > 12:
            _review_cache.popitem(last=False)
    return payload


def _review_period(store: Store, week: str | None, compare: str | None) -> tuple[str, str]:
    """Default reporting week = the latest *completed* week of the file (never a partial week)."""
    if week is None:
        done = latest_completed_week(store)
        if done is not None:
            week = done.code
    w, c = _period(store, week, compare)
    if store.week(c).number >= store.week(w).number:
        raise HTTPException(422, "The comparison week must be earlier than the reporting week")
    return w, c


def _fresh(payload: dict[str, Any]) -> dict[str, Any]:
    """Cached figures (same dataset + period) with this request's generation time."""
    return {**payload, "generatedAt": dt.datetime.now(dt.UTC).isoformat()}


def _csv(value: str | None, allowed: set[str], what: str) -> list[str] | None:
    """Comma list -> validated, de-duplicated list (None = everything)."""
    if value is None:
        return None
    items = list(dict.fromkeys(v for v in value.split(",") if v))
    unknown = [v for v in items if v not in allowed]
    if unknown:
        raise HTTPException(422, f"Unknown {what}: {', '.join(unknown)}")
    return items


@router.get("/reviews/management")
def management_review_json(week: OptWeekId = None, compare: OptWeekId = None, store: Store = Depends(get_store), db: Session = Depends(get_db)) -> dict:
    w, c = _review_period(store, week, compare)
    return _fresh(_review(store, db, w, c))


@router.get("/reviews/management.pptx")
def management_review_pptx(
    request: Request,
    week: OptWeekId = None,
    compare: OptWeekId = None,
    sections: Annotated[str | None, Query(pattern=r"^[a-z-]{1,20}(,[a-z-]{1,20}){0,15}$", description="Comma-separated deck sections; default all")] = None,
    circles: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}(,[a-z0-9-]{1,40}){0,15}$", description="Comma-separated circle ids; default all")] = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
    db: Session = Depends(get_db),
) -> Response:
    w, c = _review_period(store, week, compare)
    payload = _fresh(_review(store, db, w, c))
    if not payload["summary"]["valid"]:
        failed = ", ".join(x["name"] for x in payload["summary"]["checks"] if not x["ok"] and not x.get("warningOnly"))
        raise HTTPException(409, f"Report not generated – validation failed: {failed}")
    chosen = _csv(sections, set(DECK_SECTIONS), "section")
    circle_ids = _csv(circles, {x["id"] for x in payload["circles"]}, "circle")
    try:
        deck = render_review_deck(payload, generated_by=user.name, sections=chosen, circle_ids=circle_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    audit(db, "review_pptx_download", request, user.id, f"{w} vs {c} · dataset {store.dataset_id} · sections={sections or 'all'} · circles={circles or 'all'}")
    name = f"Pratap_Management_Review_{w}_vs_{c}.pptx"
    return Response(deck, media_type=PPTX_MEDIA, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/amc-conversion")
def amc_conversion_plan(week: OptWeekId = None, compare: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    """AMC conversion plan (management plan file) vs execution (GPs by AMC date), counted up to the selected
    week's end or the last date with data. Default = the file's latest week, i.e. execution up to the latest data."""
    w, c = _period(store, week, compare)
    plan = get_settings().data_dir / PLAN_FILE
    stamp = plan.stat().st_mtime if plan.exists() else None  # a changed plan file is picked up without a restart
    return store.memo(("amc-conversion", w, c, stamp), lambda: amc_conversion(store, w, c))


@router.get("/amc-plan/summary")
def amc_plan(week: OptWeekId = None, date: OptDate = None, store: Store = Depends(get_store)) -> dict:
    """GP-wise AMC conversion plan vs achievement (Planned Date / Ach Date of the GP sheet). Default = the file's latest
    week; `date` = as of a picked day (its month and Fri–Thu week, capped at the data date)."""
    w, _ = _period(store, week, None)
    return store.memo(("amc-plan", w, date), lambda: amc_plan_summary(store, w, date))


@router.get("/amc-plan/area-managers")
def amc_plan_by_area_manager(circle: Annotated[str, Query(pattern=r"^[a-z0-9-]{1,40}$")], week: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    """One state's AMC plan vs achievement per area manager (Escalation Matrix AM names): current month and the
    selected week. Not memoised: a new Escalation Matrix upload must show at once (the join is cached there)."""
    w, _ = _period(store, week, None)
    try:
        return amc_plan_area_managers(store, w, circle)
    except KeyError:
        raise HTTPException(404, "Unknown state") from None


@router.get("/amc-plan/timeline")
def amc_plan_months_weeks(week: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    """Month-wise and week-wise GP-wise AMC plan vs achievement, per state (counts of Planned Date / Ach Date)."""
    w, _ = _period(store, week, None)
    return store.memo(("amc-plan-timeline", w, targets_stamp()), lambda: amc_plan_timeline(store, w))


@router.get("/notifications")
def notifications(week: OptWeekId = None, store: Store = Depends(get_store), db: Session = Depends(get_db)) -> list[dict]:
    w, _ = _period(store, week, None)
    from ..analytics.metrics import summarize

    s = store.memo(("summary", w), lambda: summarize(store, None, w))
    ds = db.get(Dataset, store.dataset_id)
    return [
        {"id": "penalty", "severity": "critical", "title": f"{s['penaltyBlocks']} penalty-prone blocks", "body": f"Blocks below the penalty threshold (MTD) in Week {w[2:]}.", "href": "/dashboard/reports"},
        {"id": "zero", "severity": "warning", "title": f"{s['gpsAtZero']} AMC GPs at 0% MTD", "body": "GPs that reported zero availability this month.", "href": "/dashboard"},
        {"id": "na", "severity": "info", "title": f"{s['naGps']} AMC GPs not reported", "body": "Shown as NA – never counted as 0%."},
        {
            "id": "import",
            "severity": "info" if ds and ds.status == "SUCCESS" else "warning",
            "title": f"Data as of {store.data_as_of:%d %b %Y}",
            "body": f"Source: {store.file_name}",
            "href": "/dashboard/operations",
        },
    ]
