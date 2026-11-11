"""Data access: a viewer with areas sees only the GPs of those areas, on every data endpoint, with the same figures
the whole-dataset pages show for that area; admins and viewers without an area are unchanged."""

import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import User, UserScope

from .conftest import ADMIN, VIEWER, login


def _viewer_id() -> int:
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == VIEWER[0])).one()


def _set_areas(areas) -> None:
    uid = _viewer_id()
    with SessionLocal() as db:
        db.execute(delete(UserScope).where(UserScope.user_id == uid))
        db.add_all(UserScope(user_id=uid, level=lv, scope_id=i) for lv, i in areas)
        db.commit()


@pytest.fixture
def areas():
    """Sets the viewer's areas for one test and always removes them afterwards (other tests see a plain viewer)."""
    yield _set_areas
    _set_areas([])


def _two_circles(store):
    sizes = store.gps.groupby("circle_id").size().sort_values()
    return sizes.index[0], sizes.index[-1]  # smallest, largest


def test_viewer_without_area_sees_everything(imported, client, areas):
    login(client, ADMIN)
    admin_meta = client.get("/api/v1/meta").json()
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    login(client, VIEWER)
    me = client.get("/api/v1/auth/me").json()
    assert me["access"] == {"scope": "all", "areas": []}
    assert client.get("/api/v1/meta").json()["circles"] == admin_meta["circles"]


def test_circle_area_limits_every_endpoint(imported, client, areas):
    mine, other = _two_circles(imported)
    areas([("circle", mine)])
    login(client, VIEWER)
    me = client.get("/api/v1/auth/me").json()
    assert me["access"]["scope"] == "areas" and len(me["access"]["areas"]) == 1

    meta = client.get("/api/v1/meta").json()
    assert [c["id"] for c in meta["circles"]] == [mine]
    assert {d["circleId"] for d in meta["districts"]} == {mine}
    assert {b["circleId"] for b in meta["blocks"]} == {mine}

    # Another state's pages, GPs and blocks are not found; its GPs are not searchable or listed.
    g = imported.gps
    other_gp = g.index[(g["circle_id"] == other).to_numpy()][0]
    other_block = g.loc[g["circle_id"] == other, "block_id"].iloc[0]
    assert client.get(f"/api/v1/circles/{other}/insights").status_code == 404
    assert client.get(f"/api/v1/blocks/{other_block}/insights").status_code == 404
    assert client.get(f"/api/v1/gps/{other_gp}").status_code == 404
    assert all(r.get("circleId", mine) == mine for r in client.get("/api/v1/search", params={"q": g.loc[other_gp, "name"][:6]}).json())
    rows = client.get("/api/v1/gps", params={"page_size": 1000}).json()
    assert rows["total"] == int((g["circle_id"] == mine).sum())
    assert client.get("/api/v1/circles/" + mine + "/insights").status_code == 200

    # The overview of the viewer = the admin's page of that state (same figures).
    ov = client.get("/api/v1/overview").json()
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    login(client, ADMIN)
    ci = client.get(f"/api/v1/circles/{mine}/insights").json()
    common = (set(ov["summary"]) & set(ci["summary"])) - {"states"}
    assert {"existingGps", "newGps", "amcGps", "availability", "penaltyBlocks"} <= common
    for k in common:
        assert ov["summary"][k] == ci["summary"][k], k
    # …and the admin still sees every state (scoped snapshots never leak into the shared one).
    assert len(client.get("/api/v1/meta").json()["circles"]) == imported.gps["circle_id"].nunique()


def test_scoped_figures_equal_masked_figures(imported):
    """Store-level check: every GP-wise frame is cut consistently and the shared metric rules give the same numbers."""
    from app.analytics.metrics import summarize
    from app.analytics.store import scoped_store

    mine, _ = _two_circles(imported)
    s = scoped_store(imported, (("circle", mine),))
    mask = (imported.gps["circle_id"] == mine).to_numpy()
    assert s.gps.index.equals(imported.gps.index[mask])
    for frame in (s.daily, s.weekly, s.monthly, s.monthly_amc):
        assert frame.index.equals(s.gps.index)
    assert set(s.amc_plan.index) <= set(s.gps.index)
    week = imported.latest_week.code
    assert summarize(s, None, week) | {"totalStates": 1} == summarize(imported, mask, week) | {"totalStates": 1}
    assert s.full_circles == {imported.gps.loc[mask, "circle"].iloc[0].upper()}
    # Same areas -> same cached snapshot; the base snapshot is untouched.
    assert scoped_store(imported, (("circle", mine),)) is s
    assert imported.scope_key is None and len(imported.gps) > len(s.gps)


def test_district_area_hides_state_level_values(imported):
    """Part of a state: GP figures for those GPs only; whole-state reference values (O&M numbers) are not applied."""
    from app.analytics.store import scoped_store

    g = imported.gps
    did = g["district_id"].iloc[0]
    s = scoped_store(imported, (("district", did),))
    assert set(s.gps["district_id"]) == {did}
    assert s.full_circles == frozenset()
    circles = {str(c).upper() for c in g["circle"].unique()}
    assert not s.reported["state"].astype(str).str.upper().isin(circles).any()
    blocks = set(zip(s.gps["circle"].str.upper(), s.gps["block_code"].astype(str)))
    assert all((str(st).upper(), str(b)) in blocks for st, b in zip(s.master_blocks["state"], s.master_blocks["block_code"]))


def test_area_not_in_data_gets_no_data(imported, client, areas):
    areas([("block", "zz-0")])
    login(client, VIEWER)
    assert client.get("/api/v1/meta").status_code == 403
    assert client.get("/api/v1/overview").status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200  # can still sign in and see why


def _ensure_escalation(client) -> None:
    from pathlib import Path

    from app.analytics.escalation import _active

    if _active() is not None:
        return
    raw = Path(__file__).resolve().parents[2] / "data" / "raw"
    esc_file = next((f for f in (raw / "Escalation_Matrix_15.10.xlsx", raw / "Final Escalation Matrix.xlsx") if f.exists()), None)
    if esc_file is None:
        pytest.skip("Escalation Matrix file not available")
    csrf = login(client, ADMIN)
    with esc_file.open("rb") as fh:
        r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("Escalation.xlsx", fh, "application/octet-stream")})
    assert r.status_code in (202, 409), r.text
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    if _active() is None:
        pytest.skip("No active Escalation Matrix")


def test_field_team_is_limited_and_not_mixed(imported, client, areas):
    """Field Team & Escalation for a viewer covers only their GPs; the admin's view is unchanged afterwards."""
    from app.analytics.escalation import _frame
    from app.analytics.store import scoped_store

    _ensure_escalation(client)
    mine, _ = _two_circles(imported)
    _, full = _frame(imported)
    s = scoped_store(imported, (("circle", mine),))
    _, part = _frame(s)
    assert set(part.index) <= set(s.gps.index) and set(part["circle_id"]) <= {mine}
    _, again = _frame(imported)
    assert again is full and len(again) > len(part)

    login(client, ADMIN)
    admin_before = client.get("/api/v1/field-team/summary").json()
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    areas([("circle", mine)])
    login(client, VIEWER)
    rows = client.get("/api/v1/field-team/lookup", params={"page_size": 200}).json()
    assert rows["items"] and {r["circleId"] for r in rows["items"]} == {mine}
    assert client.get("/api/v1/field-team/summary").status_code == 200
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": client.cookies.get("pratap_csrf")})
    login(client, ADMIN)
    assert client.get("/api/v1/field-team/summary").json() == admin_before


@pytest.mark.parametrize("level", ["circle", "district", "block"])
def test_every_page_and_download_works_for_an_area(imported, client, areas, level):
    """Every user-facing data endpoint answers for a viewer limited to a circle / one district / one block
    (a part of a state must never break a page), and lists only that area's GPs."""
    from app.analytics.drilldown import KINDS

    g = imported.gps
    mine, _ = _two_circles(imported)
    sub = g[g["circle_id"] == mine]
    area = {"circle": mine, "district": sub["district_id"].iloc[0], "block": sub["block_id"].iloc[0]}[level]
    in_area = g[{"circle": g["circle_id"], "district": g["district_id"], "block": g["block_id"]}[level] == area]
    try:
        _ensure_escalation(client)
    except pytest.skip.Exception:
        pass
    areas([(level, area)])
    login(client, VIEWER)
    gp, block = in_area.index[0], in_area["block_id"].iloc[0]
    ok = [
        "/api/v1/meta",
        "/api/v1/overview",
        f"/api/v1/circles/{mine}/insights",
        f"/api/v1/blocks/{block}/insights",
        "/api/v1/gps",
        f"/api/v1/gps/{gp}",
        f"/api/v1/search?q={str(in_area['name'].iloc[0])[:4]}",
        "/api/v1/reports/weekly",
        "/api/v1/reports/weekly.pdf",
        "/api/v1/reviews/management",
        "/api/v1/amc-conversion",
        "/api/v1/amc-plan/summary",
        f"/api/v1/amc-plan/area-managers?circle={mine}",
        "/api/v1/amc-plan/timeline",
        "/api/v1/notifications",
        *[f"/api/v1/kpi-lists/{k}" for k in KINDS],
        "/api/v1/kpi-lists/existing-gps.xlsx",
    ]
    for url in ok:
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
    # The deck may be refused by its own validation (409), never fail.
    assert client.get("/api/v1/reviews/management.pptx").status_code in (200, 409)
    for url in ("/api/v1/field-team/summary", "/api/v1/field-team/lookup", "/api/v1/field-team/workload", "/api/v1/field-team/people", "/api/v1/field-team/down", "/api/v1/field-team/gaps"):
        assert client.get(url).status_code in (200, 404), url  # 404 only without an Escalation Matrix
    meta = client.get("/api/v1/meta").json()
    assert {b["id"] for b in meta["blocks"]} == set(in_area["block_id"])
    assert client.get("/api/v1/gps", params={"page_size": 1000}).json()["total"] == len(in_area)
    ex = client.get("/api/v1/kpi-lists/existing-gps", params={"page_size": 200}).json()
    assert ex["total"] == len(in_area)
    review = client.get("/api/v1/reviews/management").json()
    assert [c["id"] for c in review["circles"]] == [mine]
