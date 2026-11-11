"""Per-GP Done / Pending with proof documents (user side) and the admin Done / Pending GP monitoring: each GP code
counted once across tickets, overall status, remarks / proof exactly as submitted, filters, GP history, no auto-close."""

import datetime as dt
import json

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import TicketProgressFile, TicketProgressLine, User
from app.security.core import hash_password

from .conftest import ADMIN, VIEWER, login
from .test_ticket_tasks import _create, am_week  # noqa: F401 - shared fixture

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
OTHER = ("other.viewer@pratap-test.in", "0ther!Secure-Pass-55")


def _form(client, h, tid, items, files=(), note=None):
    data = {"payload": json.dumps({"items": items, "note": note}), "proofGps": [str(g) for g, _, _, _ in files]}
    up = [("proofs", (name, body, mime)) for _, name, body, mime in files]
    return client.post(f"/api/v1/tickets/{tid}/progress-form", data=data, files=up or None, headers=h)


def _lines(tid):
    with SessionLocal() as db:
        from app.models import TicketProgress

        return db.scalar(select(func.count()).select_from(TicketProgressLine).join(TicketProgress, TicketProgress.id == TicketProgressLine.progress_id).where(TicketProgress.ticket_id == tid))


def test_user_done_pending_with_proof_and_admin_monitoring(imported, client, am_week):  # noqa: F811
    am, week = am_week
    ha = {"X-CSRF-Token": login(client, ADMIN)}
    r = _create(client, ha, am, week)
    assert r.status_code == 201, r.text
    tid, code = r.json()["id"], r.json()["code"]
    before = client.get("/api/v1/tickets/gp-monitor/summary").json()

    hu = {"X-CSRF-Token": login(client, VIEWER)}
    d = client.get(f"/api/v1/tickets/{tid}").json()
    open_gps = [g for g in d["task"]["gps"] if g["status"] == "PENDING"]
    assert len(open_gps) >= 2, "test needs two pending GPs"
    g1, g2 = open_gps[0], open_gps[1]
    assert all(g["files"] == [] for g in d["task"]["gps"])

    # refused before anything is written: a file type not allowed / a file without its GP / Pending on a done GP
    bad = _form(client, hu, tid, [{"taskGpId": g1["id"], "status": "DONE"}], [(g1["id"], "virus.exe", b"MZ..", "application/octet-stream")])
    assert bad.status_code == 415, bad.text
    r = client.post(f"/api/v1/tickets/{tid}/progress-form", data={"payload": json.dumps({"items": [{"taskGpId": g1["id"], "status": "DONE"}]})}, files=[("proofs", ("a.pdf", PDF, "application/pdf"))], headers=hu)
    assert r.status_code == 422
    assert _lines(tid) == 0 and client.get(f"/api/v1/tickets/{tid}").json()["task"]["totals"]["achieved"] == d["task"]["totals"]["achieved"]

    # day 1: GP1 Done with a PDF letter, GP2 Pending with a reason and a photo
    r = _form(
        client, hu, tid,
        [{"taskGpId": g1["id"], "status": "DONE", "remark": "Letter accepted"}, {"taskGpId": g2["id"], "status": "PENDING", "remark": "OTDR test pending"}],
        [(g1["id"], "letter.pdf", PDF, "application/pdf"), (g2["id"], "site.png", PNG, "image/png")],
        note="Day 1",
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "IN_PROGRESS"
    gp = {g["id"]: g for g in d["task"]["gps"]}
    assert gp[g1["id"]]["status"] == "DONE" and gp[g1["id"]]["remarks"] == "Letter accepted" and [f["fileName"] for f in gp[g1["id"]]["files"]] == ["letter.pdf"]
    assert gp[g2["id"]]["status"] == "PENDING" and gp[g2["id"]]["remarks"] == "OTDR test pending" and gp[g2["id"]]["lastUpdated"]
    line = {ln["taskGpId"]: ln for ln in d["task"]["history"][0]["lines"]}
    assert line[g1["id"]]["status"] == "DONE" and line[g1["id"]]["files"][0]["fileName"] == "letter.pdf"
    assert line[g2["id"]]["status"] == "PENDING" and line[g2["id"]]["achievedToday"] == 0
    # a done GP can be neither Done again nor Pending; the older JSON form still works
    assert _form(client, hu, tid, [{"taskGpId": g1["id"], "status": "DONE"}]).status_code == 422
    assert _form(client, hu, tid, [{"taskGpId": g1["id"], "status": "PENDING"}]).status_code == 422
    assert client.post(f"/api/v1/tickets/{tid}/progress", json={"items": [{"taskGpId": g2["id"], "achievedToday": 0, "remark": "Team on site tomorrow"}]}, headers=hu).status_code == 200

    # proof download: the assignee and the admin; nobody else (404)
    pdf = gp[g1["id"]]["files"][0]
    x = client.get(f"/api/v1/tickets/progress-files/{pdf['id']}?inline=true")
    assert x.status_code == 200 and x.content == PDF and x.headers["content-disposition"].startswith("inline")
    with SessionLocal() as db:
        if db.scalars(select(User).where(User.email == OTHER[0])).first() is None:
            db.add(User(email=OTHER[0], name="Other", role="viewer", password_hash=hash_password(OTHER[1])))
            db.commit()
    login(client, OTHER)
    assert client.get(f"/api/v1/tickets/progress-files/{pdf['id']}").status_code == 404
    assert client.get("/api/v1/tickets/gp-monitor/summary").status_code == 403

    # admin monitoring
    ha = {"X-CSRF-Token": login(client, ADMIN)}
    s = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code}).json()
    total = len(d["task"]["gps"])
    assert s["total"] == total and s["done"] == sum(1 for g in d["task"]["gps"] if g["status"] == "DONE") and s["done"] + s["pending"] == total
    done = client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "ticket": code, "page_size": 200}).json()
    row = next(x for x in done["items"] if x["gpCode"] == g1["gpCode"])
    assert row["areaManager"] == am and row["remarks"] == "Letter accepted" and row["files"][0]["fileName"] == "letter.pdf" and row["completedAt"] and row["ticket"] == code
    assert row["achieved"] == 1 and row["gap"] == 0 and done["kpis"]["done"] == s["done"]
    pend = client.get("/api/v1/tickets/gp-monitor", params={"status": "PENDING", "ticket": code, "page_size": 200}).json()
    p2 = next(x for x in pend["items"] if x["gpCode"] == g2["gpCode"])
    assert p2["remarks"] == "Team on site tomorrow" and p2["files"][0]["fileName"] == "site.png" and p2["lastUpdated"] and p2["gap"] == 1
    assert all(x["files"] == [] for x in pend["items"] if x["gpCode"] not in (g2["gpCode"],))
    # filters: GP code, block, week, date range of today / tomorrow
    assert [x["gpCode"] for x in client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "gpCode": g1["gpCode"]}).json()["items"]] == [g1["gpCode"]]
    assert g1["gpCode"] in [x["gpCode"] for x in client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "week": week, "block": g1["block"] or "", "page_size": 200}).json()["items"]]
    today = dt.date.today()
    assert g1["gpCode"] in [x["gpCode"] for x in client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "dateFrom": (today - dt.timedelta(days=1)).isoformat(), "page_size": 200}).json()["items"]]
    assert client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "dateFrom": (today + dt.timedelta(days=2)).isoformat(), "gpCode": g1["gpCode"]}).json()["items"] == []

    # the same GPs in a second ticket of the AM: counted once, GP1 stays Done (done in the first ticket)
    r2 = _create(client, ha, am, week)
    code2 = r2.json()["code"]
    s_all = client.get("/api/v1/tickets/gp-monitor/summary").json()
    assert s_all["total"] == before["total"] + (s["total"] if before["total"] == 0 else 0) or s_all["total"] >= s["total"]
    s2 = client.get("/api/v1/tickets/gp-monitor/summary", params={"ticket": code2}).json()
    assert s2["total"] == s["total"] and s2["done"] == s["done"]
    both = client.get("/api/v1/tickets/gp-monitor/summary", params={"areaManager": am}).json()
    assert both["total"] == s["total"]  # two tickets, every GP once
    row2 = next(x for x in client.get("/api/v1/tickets/gp-monitor", params={"status": "DONE", "gpCode": g1["gpCode"]}).json()["items"])
    assert row2["ticket"] == code and sorted(row2["tickets"]) == sorted([code, code2])

    # GP detail: every ticket and the date-wise history with status, remark and proof
    det = client.get(f"/api/v1/tickets/gp-monitor/gps/{g2['gpCode']}").json()
    assert det["status"] == "PENDING" and {t["ticket"] for t in det["ticketRows"]} == {code, code2}
    hist = [h for h in det["history"] if h["source"] == "progress"]
    assert [h["remark"] for h in hist] == ["Team on site tomorrow", "OTDR test pending"] and hist[1]["files"][0]["fileName"] == "site.png"
    assert all(h["status"] == "PENDING" for h in hist)
    assert client.get("/api/v1/tickets/gp-monitor/gps/NOPE-123").status_code == 404

    # all GPs done -> the ticket still is not closed (only the admin closes)
    hu = {"X-CSRF-Token": login(client, VIEWER)}
    rest = [g for g in client.get(f"/api/v1/tickets/{tid}").json()["task"]["gps"] if g["status"] == "PENDING"]
    r = _form(client, hu, tid, [{"taskGpId": g["id"], "status": "DONE"} for g in rest])
    assert r.status_code == 200 and r.json()["status"] == "IN_PROGRESS" and r.json()["task"]["totals"]["openGps"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).where(TicketProgressFile.ticket_id == tid)) == 2
