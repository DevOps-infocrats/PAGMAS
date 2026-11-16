"""User Management areas by BA (business area) and district, and the bulk import with Circle / BA / District / Block /
GP columns: the user sees only the GPs of those areas (same rule as choosing them in User Management)."""

from sqlalchemy import select

from app.analytics.store import area_mask, ba_ids, scoped_store
from app.db import SessionLocal
from app.models import UserScope, User
from app.mail.audience import location_tree, locations

from .conftest import login
from .test_user_import import _cleanup, _post, _xlsx


def _a_ba(g):
    ba = ba_ids(g)
    bid = ba.dropna().value_counts().index[0]
    return ba, bid


def test_ba_area_rule(imported):
    g = imported.gps
    ba, bid = _a_ba(g)
    cid = g.loc[ba == bid, "circle_id"].iloc[0]
    sel = lambda m: set(g.index[m])  # noqa: E731
    in_ba = set(g.index[ba == bid])
    assert in_ba and sel(area_mask(g, [("ba", bid)])[0]) == in_ba
    # circle + one of its BAs = that BA only (the circle is no longer given in full)
    m, full = area_mask(g, [("circle", cid), ("ba", bid)])
    assert sel(m) == in_ba and full == set()
    # BA + a block inside it = that block only
    blk = g.loc[ba == bid, "block_id"].iloc[0]
    assert sel(area_mask(g, [("ba", bid), ("block", blk)])[0]) == set(g.index[g["block_id"] == blk])
    # unknown BA: nothing (never widened)
    assert not area_mask(g, [("ba", f"{cid}~no-such-ba")])[0].any()
    # labels and the picker tree know the BA
    assert bid in locations(imported)["ba"]
    tree = {c["id"]: c for c in location_tree(imported)}
    assert any(b["id"] == bid and blk in b["blocks"] for b in tree[cid]["bas"])
    # the dashboard snapshot of a BA viewer = exactly the BA's GPs
    assert set(scoped_store(imported, (("ba", bid),)).gps.index) == in_ba


def test_viewer_with_a_ba_sees_only_it(client, imported):
    g = imported.gps
    ba, bid = _a_ba(g)
    h = {"x-csrf-token": login(client)}
    email = "ba.viewer@imp-test.in"
    try:
        r = client.post("/api/v1/users", json={"email": email, "name": "Ba Viewer", "password": "BaViewer!Secure-Pass-77", "scopes": [{"level": "ba", "id": bid}]}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["scopes"][0]["valid"] and r.json()["scopes"][0]["label"].endswith(")")
        assert client.post("/api/v1/users", json={"email": "x." + email, "name": "Bad Ba", "password": "BaViewer!Secure-Pass-77", "scopes": [{"level": "ba", "id": "zz~nope"}]}, headers=h).status_code == 422
        r = client.get("/api/v1/users/locations/gps", params={"ba": bid, "limit": 200}).json()
        assert r["total"] == int((ba == bid).sum())
        d = g.loc[ba == bid, "district_id"].iloc[0]
        assert client.get("/api/v1/users/locations/gps", params={"district": d, "limit": 1}).json()["total"] == int((g["district_id"] == d).sum())
    finally:
        _cleanup(email, "x." + email)


def test_import_with_area_columns(client, imported):
    g = imported.gps
    ba, bid = _a_ba(g)
    circle = str(g.loc[ba == bid, "circle"].iloc[0])
    ba_name = str(g.loc[ba == bid, "ba"].iloc[0])
    blk = g.loc[ba == bid].iloc[0]
    other_ba = ba.dropna()[ba.dropna().str.startswith(bid.split("~")[0] + "~") & (ba.dropna() != bid)].iloc[0]
    other_name = str(g.loc[ba == other_ba, "ba"].iloc[0])
    csrf = login(client)
    rows = [
        ["Name", "Email", "Circle", "BA", "Block", "GP"],
        ["Ba One", "ba1@imp-test.in", circle.title(), f"{ba_name.lower()}, {other_name}", None, None],
        ["Block One", "blk1@imp-test.in", circle, ba_name, str(blk["block_name"]), None],
        ["Circle One", "circ1@imp-test.in", circle, None, None, None],
        ["Gp One", "gp1@imp-test.in", None, None, None, str(g.index[0])],
        ["All One", "all1@imp-test.in", None, None, None, None],
        ["Bad Ba", "bad1@imp-test.in", circle, "No Such BA", None, None],
    ]
    emails = [r[1] for r in rows[1:]]
    try:
        p = _post(client, csrf, _xlsx(rows)).json()
        assert p["withAreas"] and (p["new"], p["skipped"]) == (5, 1)
        by = {it["email"]: it for it in p["items"]}
        assert len(by["ba1@imp-test.in"]["areas"]) == 2 and all(a.startswith("BA: ") for a in by["ba1@imp-test.in"]["areas"])
        assert by["blk1@imp-test.in"]["areas"][0].startswith("Block: ")
        assert by["all1@imp-test.in"]["areas"] == []
        assert "not found" in by["bad1@imp-test.in"]["reason"]

        p = _post(client, csrf, _xlsx(rows), dry=False).json()
        assert p["created"] == 5
        with SessionLocal() as db:
            sc = lambda e: sorted((s.level, s.scope_id) for s in db.scalars(select(UserScope).join(User, User.id == UserScope.user_id).where(User.email == e)))  # noqa: E731
            assert sc("ba1@imp-test.in") == sorted([("ba", bid), ("ba", other_ba)])
            assert sc("blk1@imp-test.in") == [("block", blk["block_id"])]
            assert sc("circ1@imp-test.in") == [("circle", g.loc[ba == bid, "circle_id"].iloc[0])]
            assert sc("gp1@imp-test.in") == [("gp", str(g.index[0]))]
            assert sc("all1@imp-test.in") == []
            assert db.scalar(select(User.id).where(User.email == "bad1@imp-test.in")) is None
    finally:
        _cleanup(*emails)
