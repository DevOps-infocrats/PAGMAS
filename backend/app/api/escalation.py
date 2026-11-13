"""Field Team & Escalation endpoints (any signed-in user; full phone numbers for admins only)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..analytics import escalation as esc
from ..analytics import escalation_sheet as sheet
from ..analytics.store import Store
from ..db import get_db
from ..security.access import get_user_store
from ..security.deps import CurrentUser, audit, get_current_user, require_admin
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
def summary(week: OptWeekId = None, store: Store = Depends(get_user_store)) -> dict:
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
    store: Store = Depends(get_user_store),
) -> dict:
    return _run(esc.lookup, store, _week(store, week), circle, district, block, search, page, page_size, user.is_admin)


@router.get("/workload")
def workload(
    role: Annotated[Literal["frt", "splicer", "fe", "am"], Query()] = "fe",
    week: OptWeekId = None,
    circle: OptCircle = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_user_store),
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
    store: Store = Depends(get_user_store),
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
    store: Store = Depends(get_user_store),
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
    store: Store = Depends(get_user_store),
) -> dict:
    if issue is not None and issue not in esc.GAP_ISSUES:
        raise HTTPException(422, f"Unknown issue '{issue}'")
    return _run(esc.gaps, store, _week(store, week), issue, circle, district, block, search, page, page_size, user.is_admin)


def _source_id() -> str | None:
    """Active escalation import id + edit version – part of the memo keys, so a new upload and every edit on the
    Escalation Sheet are picked up at once."""
    act = esc._active()
    return f"{act[0]['id']}:{esc._version}" if act else None


# ---------------------------------------------------------------- Escalation Sheet (view / edit / export)


def _sheet_fail(exc: sheet.SheetError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.message, "problems": exc.problems})


@router.get("/sheet")
def escalation_sheet(
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Search = None,
    page: Page = 1,
    page_size: Annotated[int, Query(ge=10, le=500)] = 100,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_user_store),
    db: Session = Depends(get_db),
) -> dict:
    """The active Escalation Matrix as a sheet (only the viewer's GPs; phones in full for admins only)."""
    return _run(sheet.sheet, db, store, circle, district, block, search, page, page_size, user.is_admin)


class CellChange(BaseModel):
    gpCode: str = Field(min_length=1, max_length=40)
    field: str = Field(min_length=1, max_length=40)
    old: str | None = Field(default=None, max_length=500)
    new: str | None = Field(default=None, max_length=500)


class SheetChanges(BaseModel):
    importId: int = Field(ge=1)
    changes: list[CellChange] = Field(min_length=1, max_length=sheet.MAX_CHANGES)


@router.patch("/sheet")
def save_sheet(body: SheetChanges, request: Request, admin: CurrentUser = Depends(require_admin), store: Store = Depends(get_user_store), db: Session = Depends(get_db)) -> Any:
    """Admin: save edited cells (all-or-nothing; validation and conflict problems come back per cell)."""
    try:
        out = _run(sheet.apply_changes, db, store, body.importId, [c.model_dump() for c in body.changes], admin.id, admin.name)
    except sheet.SheetError as exc:
        return _sheet_fail(exc)
    if out["saved"]:
        fields = sorted({c.field for c in body.changes})
        audit(db, "escalation_edit", request, admin.id, f"import {body.importId}: {out['saved']} cell(s) ({', '.join(fields)[:300]})")
    return out


class ReplaceIn(BaseModel):
    importId: int = Field(ge=1)
    field: str = Field(min_length=1, max_length=40)
    find: str = Field(min_length=1, max_length=200)
    replace: str = Field(default="", max_length=500)
    circle: str | None = Field(default=None, max_length=40)
    district: str | None = Field(default=None, max_length=120)
    block: str | None = Field(default=None, max_length=120)
    dryRun: bool = True


@router.post("/sheet/replace")
def replace_in_sheet(body: ReplaceIn, request: Request, admin: CurrentUser = Depends(require_admin), store: Store = Depends(get_user_store), db: Session = Depends(get_db)) -> Any:
    """Admin: whole-cell find and replace in one column within the filters (dryRun = only count the matches)."""
    try:
        out = _run(sheet.replace_all, db, store, body.importId, body.field, body.find, body.replace, body.circle, body.district, body.block, body.dryRun, admin.id, admin.name)
    except sheet.SheetError as exc:
        return _sheet_fail(exc)
    if out["saved"]:
        audit(db, "escalation_replace", request, admin.id, f"import {body.importId}: {body.field} '{body.find[:80]}' -> '{body.replace[:80]}' on {out['saved']} GP(s)")
    return out


@router.get("/sheet/edits", dependencies=[Depends(require_admin)])
def sheet_edits(gpCode: Annotated[str | None, Query(max_length=40)] = None, db: Session = Depends(get_db)) -> dict:
    """Admin: latest edits of the active matrix (optionally of one GP)."""
    import_id = _run(sheet.active_import_id)
    return {"importId": import_id, "items": sheet.edits(db, import_id, gpCode)}


@router.get("/sheet/export.xlsx")
def export_sheet(
    request: Request,
    circle: OptCircle = None,
    district: OptDistrict = None,
    block: OptBlock = None,
    search: Search = None,
    user: CurrentUser = Depends(get_current_user),
    store: Store = Depends(get_user_store),
    db: Session = Depends(get_db),
) -> Response:
    """The filtered sheet as an Escalation Matrix workbook (upload headers – can be uploaded again on Data Operations)."""
    data, n = _run(sheet.export, store, circle, district, block, search, user.is_admin)
    audit(db, "escalation_export", request, user.id, f"{n} rows" + ("" if user.is_admin else " (phones masked)"))
    name = "Escalation_Matrix_export.xlsx" if user.is_admin else "Escalation_Matrix_export_masked.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
