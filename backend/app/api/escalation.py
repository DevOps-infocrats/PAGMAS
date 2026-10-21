"""Field Team & Escalation endpoints (any signed-in user; full phone numbers for admins only)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..analytics import escalation as esc
from ..analytics.store import Store, get_store
from ..security.deps import CurrentUser, get_current_user
from .analytics import OptBlock, OptCircle, OptDistrict, OptWeekId, _period

router = APIRouter(prefix="/field-team", tags=["field-team"], dependencies=[Depends(get_current_user)])

Search = Annotated[str | None, Query(max_length=80)]
Page = Annotated[int, Query(ge=1, le=10_000)]
PageSize = Annotated[int, Query(ge=1, le=200)]


def _week(store: Store, week: str | None) -> str:
    return _period(store, week, None)[0]


def _run(fn, *args):  # noqa: ANN001, ANN202
    try:
        return fn(*args)
    except esc.NoEscalationData as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/summary")
def summary(week: OptWeekId = None, store: Store = Depends(get_store)) -> dict:
    w = _week(store, week)
    return _run(lambda: store.memo(("field-summary", w, _source_id()), lambda: esc.summary(store, w)))


@router.get("/lookup")
def lookup(
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Search = None,
    page: Page = 1,
    page_size: PageSize = 50,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    return _run(esc.lookup, store, _week(store, week), circle, district, block, search, page, page_size, user.is_admin)


@router.get("/workload")
def workload(
    role: Annotated[Literal["frt", "splicer", "fe", "am"], Query()] = "fe",
    week: OptWeekId = None,
    circle: OptCircle = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    w = _week(store, week)
    return _run(lambda: store.memo(("field-workload", w, role, circle, user.is_admin, _source_id()), lambda: esc.workload(store, w, role, circle, user.is_admin)))


@router.get("/people")
def team_directory(
    role: Annotated[Literal["frt", "splicer", "fe", "am"], Query()] = "am",
    week: OptWeekId = None,
    circle: OptCircle = None,
    search: Search = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    """Area managers / FEs / splicers / FRT teams (each counted once) with the districts, blocks and teams they cover."""
    w = _week(store, week)
    return _run(lambda: store.memo(("field-people", w, role, circle, search, user.is_admin, _source_id()), lambda: esc.people(store, w, role, circle, search, user.is_admin)))


@router.get("/down")
def down_gps(
    mode: Annotated[Literal["zero", "below90"], Query()] = "zero",
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Search = None,
    page: Page = 1,
    page_size: PageSize = 50,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    return _run(esc.down, store, _week(store, week), mode, circle, district, block, search, page, page_size, user.is_admin)


@router.get("/gaps")
def data_gaps(
    issue: Annotated[str | None, Query(pattern=r"^[a-z-]{1,40}$")] = None,
    week: OptWeekId = None,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Search = None,
    page: Page = 1,
    page_size: PageSize = 50,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_store),
) -> dict:
    if issue is not None and issue not in esc.GAP_ISSUES:
        raise HTTPException(422, f"Unknown issue '{issue}'")
    return _run(esc.gaps, store, _week(store, week), issue, circle, district, block, search, page, page_size, user.is_admin)


def _source_id() -> int | None:
    """Active escalation import id – part of the memo keys, so a new upload is picked up at once."""
    act = esc._active()
    return act[0]["id"] if act else None
