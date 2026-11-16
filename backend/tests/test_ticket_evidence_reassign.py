"""Daily Achievement evidence, the Area Manager's role in the daily progress and GP reassignment between FEs:

* an FE's Daily Achievement needs a remark AND at least one photo (JPG / PNG) – enforced by the API, not only the page;
* the Area Manager never reports the GP of an FE of the ticket (only reviews it); GPs without such an FE stay theirs;
* the Area Manager (or an admin) gives a GP to another FE of the ticket: only the GP's FE changes – target, category,
  every daily line and proof stay, the step is in the GP's history, no GP or target is duplicated.
"""

import json

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import TicketGpReview, TicketProgressFile, TicketProgressLine, TicketTaskGp

from .conftest import VIEWER, login
from .evidence import JPG, PDF, progress
from .test_ticket_fe import FE1, FE2, _fe, _gen, fe_org  # noqa: F401 - shared fixture
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _ticket(client, fe_org):  # noqa: F811
    h = {"X-CSRF-Token": login(client)}
    r = _gen(client, h, fe_org, [{"role": "AM", "name": fe_org["am"], "email": VIEWER[0]}, _fe("Test FE One", FE1[0]), _fe("Test FE Two", FE2[0])])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _form(client, tid, h, items, files=()):
    data = {"payload": json.dumps({"items": items})}
    if files:
        data["proofGps"] = [str(g) for g, _ in files]
    return client.post(f"/api/v1/tickets/{tid}/progress-form", data=data, files=[("proofs", f) for _, f in files] or None, headers=h)


def test_fe_daily_achievement_needs_remark_and_photo(client, fe_org, mail):  # noqa: F811
    tid = _ticket(client, fe_org)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]["id"]
    jpg = (g, ("site.jpg", JPG, "image/jpeg"))
    cases = [
        ("no remark, no photo", [{"taskGpId": g, "category": "A"}], []),
        ("remark, no photo", [{"taskGpId": g, "category": "A", "remark": "Splicing done"}], []),
        ("photo, no remark", [{"taskGpId": g, "category": "A"}], [jpg]),
        ("whitespace remark + photo", [{"taskGpId": g, "category": "A", "remark": "    "}], [jpg]),
        ("remark + only a PDF", [{"taskGpId": g, "category": "A", "remark": "Letter attached"}], [(g, ("letter.pdf", PDF, "application/pdf"))]),
        ("older Done form, no photo", [{"taskGpId": g, "status": "PENDING", "remark": "Team tomorrow"}], []),
    ]
    for name, items, files in cases:
        r = _form(client, tid, h1, items, files)
        assert r.status_code == 422 and "remark" in r.json()["detail"] and "photo" in r.json()["detail"], (name, r.text)
    # invalid / fake image files are refused by the upload policy
    assert _form(client, tid, h1, [{"taskGpId": g, "category": "A", "remark": "Done"}], [(g, ("virus.exe", b"MZ", "application/octet-stream"))]).status_code == 415
    assert _form(client, tid, h1, [{"taskGpId": g, "category": "A", "remark": "Done"}], [(g, ("fake.jpg", b"MZ-not-an-image", "image/jpeg"))]).status_code == 415
    with SessionLocal() as db:  # nothing was written by any refused submission
        assert db.scalar(select(func.count()).select_from(TicketProgressLine).where(TicketProgressLine.task_gp_id == g)) == 0
        assert db.scalar(select(func.count()).select_from(TicketProgressFile).where(TicketProgressFile.task_gp_id == g)) == 0
    # remark + photo: accepted and stored with the FE as submitter
    r = _form(client, tid, h1, [{"taskGpId": g, "category": "A", "remark": "Splicing done"}], [jpg])
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["task"]["gps"] if x["id"] == g)
    assert row["gpCategory"] == "A" and row["remarks"] == "Splicing done" and [f["fileName"] for f in row["files"]] == ["site.jpg"]
    assert row["feSubmission"]["submittedByRole"] == "FE" and row["feSubmission"]["remark"] == "Splicing done"
    # a remark-only update (no achievement change) needs no photo
    assert _form(client, tid, h1, [{"taskGpId": g, "remark": "FRT confirmed the route"}]).status_code == 200
    # a GP added by the FE with a Daily Achievement: the same evidence (its photo is sent with proofGps = -1)
    add = {"gpCode": "ZZEVI1", "gpName": "Evidence GP", "category": "C", "remark": "Found in the field"}
    r = client.post(f"/api/v1/tickets/{tid}/progress-form", data={"payload": json.dumps({"newGps": [add]})}, headers=h1)
    assert r.status_code == 422 and "photo" in r.json()["detail"]
    r = client.post(f"/api/v1/tickets/{tid}/progress-form", data={"payload": json.dumps({"newGps": [add]}), "proofGps": ["-1"]}, files=[("proofs", ("new.jpg", JPG, "image/jpeg"))], headers=h1)
    assert r.status_code == 200, r.text
    new = next(x for x in r.json()["task"]["gps"] if x["gpCode"] == "ZZEVI1")
    assert new["feName"] == "Test FE One" and [f["fileName"] for f in new["files"]] == ["new.jpg"]


def test_am_reviews_but_never_reports_an_fes_gp(client, fe_org, mail):  # noqa: F811
    tid = _ticket(client, fe_org)
    hv = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    gps = d["task"]["gps"]
    fe_gp = next(g for g in gps if g["feName"] == "Test FE One")
    free = next(g for g in gps if not g["feName"])  # FE not mapped: the Area Manager reports it
    assert fe_gp["feAssigned"] is True and free["feAssigned"] is False
    assert d["can"]["progress"] is True and d["can"]["reassign"] is True
    # direct API: refused for the FE's GP – with or without evidence, any field (category, remark, proof, GP name)
    for items, files in (
        ([{"taskGpId": fe_gp["id"], "category": "A", "remark": "AM on behalf"}], [(fe_gp["id"], ("am.jpg", JPG, "image/jpeg"))]),
        ([{"taskGpId": fe_gp["id"], "remark": "AM note"}], []),
        ([{"taskGpId": fe_gp["id"], "gpName": "Renamed by AM"}], []),
        ([], [(fe_gp["id"], ("am.jpg", JPG, "image/jpeg"))]),
    ):
        r = _form(client, tid, hv, items, files)
        assert r.status_code == 403 and "only the FE submits" in r.json()["detail"], r.text
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": fe_gp["id"], "status": "PENDING", "remark": "x"}]}, headers=hv).status_code == 403
    # a GP without an FE of the ticket: the Area Manager reports it (with the same evidence)
    assert progress(client, tid, [{"taskGpId": free["id"], "category": "C", "remark": "Revisit planned"}], hv).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TicketProgressLine).where(TicketProgressLine.task_gp_id == fe_gp["id"])) == 0


def test_am_reassigns_a_gp_to_another_fe(client, fe_org, mail):  # noqa: F811
    tid = _ticket(client, fe_org)
    # FE One reports their GP first (history that must stay as it is)
    h1 = {"X-CSRF-Token": login(client, FE1)}
    g = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"][0]
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "C", "remark": "Revisit with FRT"}], h1).status_code == 200
    with SessionLocal() as db:
        before_lines = [(ln.id, ln.remark, ln.category) for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.task_gp_id == g["id"]))]
        before_gps = db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid))
    # an FE cannot reassign
    assert client.post(f"/api/v1/tickets/{tid}/gps/{g['id']}/reassign", json={"recipientId": 1}, headers=h1).status_code == 403

    hv = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    opts = {o["name"]: o for o in d["task"]["feOptions"]}
    assert set(opts) == {"Test FE One", "Test FE Two"}
    total_before = d["task"]["totals"]
    two = opts["Test FE Two"]["recipientId"]
    am_rec = next(r["id"] for r in d["recipients"] if r["role"] == "AM")
    url = f"/api/v1/tickets/{tid}/gps/{g['id']}/reassign"
    assert client.post(url, json={"recipientId": am_rec}, headers=hv).status_code == 422  # not an FE
    assert client.post(url, json={"recipientId": opts["Test FE One"]["recipientId"]}, headers=hv).status_code == 422  # already theirs
    assert client.post(f"/api/v1/tickets/{tid}/gps/999999/reassign", json={"recipientId": two}, headers=hv).status_code == 404
    r = client.post(url, json={"recipientId": two, "remark": "FE One on leave"}, headers=hv)
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    row = next(x for x in task["gps"] if x["id"] == g["id"])
    assert row["feName"] == "Test FE Two" and row["gpCategory"] == "C" and row["remarks"] == "Revisit with FRT" and row["target"] == g["target"]
    step = row["trail"][-1]
    assert step["action"] == "REASSIGN" and step["role"] == "AM" and "Test FE One → Test FE Two" in step["remark"] and "FE One on leave" in step["remark"]
    assert {k: task["totals"][k] for k in ("gps", "target", "achieved", "gap")} == {k: total_before[k] for k in ("gps", "target", "achieved", "gap")}  # nothing duplicated
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TicketTaskGp).where(TicketTaskGp.ticket_id == tid)) == before_gps
        assert [(ln.id, ln.remark, ln.category) for ln in db.scalars(select(TicketProgressLine).where(TicketProgressLine.task_gp_id == g["id"]))] == before_lines
        assert db.scalar(select(func.count()).select_from(TicketGpReview).where(TicketGpReview.task_gp_id == g["id"], TicketGpReview.action == "REASSIGN")) == 1

    # FE Two now sees and reports it (notified); FE One no longer sees it
    h2 = {"X-CSRF-Token": login(client, FE2)}
    assert any(n["kind"] == "REASSIGN" and n["ticketId"] == tid for n in client.get("/api/v1/tickets/notifications").json()["items"])
    mine = client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]
    assert g["id"] in {x["id"] for x in mine}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "A", "remark": "Rectified by FE Two"}], h2).status_code == 200
    login(client, FE1)
    assert g["id"] not in {x["id"] for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"]}
    assert progress(client, tid, [{"taskGpId": g["id"], "category": "C", "remark": "x"}], {"X-CSRF-Token": login(client, FE1)}).status_code == 403

    # once the Area Manager approved it, the GP can no longer be reassigned
    from .evidence import review

    hv = {"X-CSRF-Token": login(client, VIEWER)}
    assert review(client, tid, {"taskGpIds": [g["id"]], "action": "AM_APPROVE", "remark": "Verified", "to": [{"name": "Sme", "email": "evi.sme@pratap-test.in"}]}, hv).status_code == 200
    assert client.post(url, json={"recipientId": opts["Test FE One"]["recipientId"]}, headers=hv).status_code == 409
    # the admin may reassign too (recorded as ADMIN) – on a GP still with the FE
    ha = {"X-CSRF-Token": login(client)}
    other = next(x for x in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if x["feName"] == "Test FE Two" and not x["locked"] and x["id"] != g["id"])
    r = client.post(f"/api/v1/tickets/{tid}/gps/{other['id']}/reassign", json={"recipientId": opts["Test FE One"]["recipientId"]}, headers=ha)
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["task"]["gps"] if x["id"] == other["id"])["trail"][-1]["role"] == "ADMIN"
