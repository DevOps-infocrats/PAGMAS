"""User Management areas: circle / block / GP, the picker's GP search, and the access rule – areas add up, and a more
specific area chosen inside another one narrows it (the same rule for the dashboard and the AMC Conversion e-mail)."""

from app.analytics.store import area_mask, scoped_store
from app.mail.audience import Assignment, locations, user_gps

from .conftest import login


def _two_circles(g):
    cs = list(g["circle_id"].unique())
    return cs[0], cs[1]


def test_area_rule(imported):
    g = imported.gps
    c1, c2 = _two_circles(g)
    b1 = g.loc[g["circle_id"] == c1, "block_id"].iloc[0]
    b2 = g.loc[g["circle_id"] == c2, "block_id"].iloc[0]
    gps_b1 = list(g.index[g["block_id"] == b1])
    sel = lambda m: set(g.index[m])  # noqa: E731
    # one circle: all its GPs; two circles: both
    assert sel(area_mask(g, [("circle", c1)])[0]) == set(g.index[g["circle_id"] == c1])
    assert sel(area_mask(g, [("circle", c1), ("circle", c2)])[0]) == set(g.index[g["circle_id"].isin([c1, c2])])
    # Rajasthan + one Rajasthan block = that block only; the circle is no longer "given in full"
    m, full = area_mask(g, [("circle", c1), ("block", b1)])
    assert sel(m) == set(gps_b1) and full == set()
    # Rajasthan + a block of another circle = all of Rajasthan + that block
    m, full = area_mask(g, [("circle", c1), ("block", b2)])
    assert sel(m) == set(g.index[(g["circle_id"] == c1) | (g["block_id"] == b2)]) and full == {c1}
    # block + one of its GPs = that GP; a GP alone = that GP
    assert sel(area_mask(g, [("block", b1), ("gp", gps_b1[0])])[0]) == {gps_b1[0]}
    assert sel(area_mask(g, [("gp", gps_b1[0])])[0]) == {gps_b1[0]}
    # unknown ids match nothing (never widened)
    assert not area_mask(g, [("gp", "ZZZ-NOT-A-GP"), ("block", "zz-0")])[0].any()


def test_dashboard_and_mail_follow_the_same_rule(imported):
    g = imported.gps
    c1, _ = _two_circles(g)
    b1 = g.loc[g["circle_id"] == c1, "block_id"].iloc[0]
    areas = (("block", b1), ("circle", c1))
    s = scoped_store(imported, tuple(sorted(areas)))
    assert set(s.gps.index) == set(g.index[g["block_id"] == b1])
    gps, labels = user_gps(imported, "viewer", [Assignment(lvl, i) for lvl, i in areas])
    assert set(gps) == set(s.gps.index) and any(lab.startswith("Block: ") for lab in labels)
    code = str(g.index[g["block_id"] == b1][0])
    assert code in locations(imported)["gp"]
    gps, labels = user_gps(imported, "viewer", [Assignment("gp", code)])
    assert list(gps) == [code] and labels[0].startswith("GP: ")


def test_gp_search_follows_the_chosen_circles_and_blocks(client, imported):
    g = imported.gps
    c1, c2 = _two_circles(g)
    b1 = g.loc[g["circle_id"] == c1, "block_id"].iloc[0]
    login(client)
    url = "/api/v1/users/locations/gps"
    r = client.get(url, params={"block": b1, "limit": 200}).json()
    assert r["total"] == int((g["block_id"] == b1).sum()) and {x["blockId"] for x in r["items"]} == {b1}
    r = client.get(url, params=[("circle", c1), ("circle", c2), ("limit", 200)]).json()
    assert r["total"] == int(g["circle_id"].isin([c1, c2]).sum()) and {x["circleId"] for x in r["items"]} <= {c1, c2}
    code = str(g.index[g["block_id"] == b1][0])
    r = client.get(url, params={"circle": c1, "q": code}).json()
    assert any(x["id"] == code for x in r["items"])


def test_viewer_with_a_gp_area(client, imported):
    g = imported.gps
    code = str(g.index[0])
    login(client)
    h = {"x-csrf-token": client.cookies.get("pratap_csrf")}
    r = client.post("/api/v1/users", json={"email": "gp.viewer@areas-test.in", "name": "GP Viewer", "password": "Gp!Viewer-Pass-77", "scopes": [{"level": "gp", "id": code}]}, headers=h)
    assert r.status_code == 201, r.text
    sc = r.json()["scopes"]
    assert sc[0]["level"] == "gp" and sc[0]["valid"] and code in sc[0]["label"]
    assert client.post("/api/v1/users", json={"email": "gp.bad@areas-test.in", "name": "GP Bad", "password": "Gp!Viewer-Pass-77", "scopes": [{"level": "gp", "id": "ZZZ-NOT-A-GP"}]}, headers=h).status_code == 422
    login(client, ("gp.viewer@areas-test.in", "Gp!Viewer-Pass-77"))
    ov = client.get("/api/v1/overview").json()
    assert ov["summary"]["existingGps"] == 1  # only that GP on every page
