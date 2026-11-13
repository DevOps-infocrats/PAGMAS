"""Ticket Management: the whole workflow on the real API and database, plus every permission rule.

admin creates -> user sees it (only them) -> starts -> uploads + submits -> admin pending review -> download ->
request changes -> user sees feedback, resubmits -> admin closes -> KPIs on both sides; outsiders get 404.
"""

import io
import zipfile

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Ticket, TicketAttachment, TicketEvent, User
from app.security.core import hash_password

from .conftest import ADMIN, VIEWER, login

OTHER = ("other-viewer@pratap-test.in", "0ther!Secure-Pass")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def _uid(email: str) -> int:
    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == email)).one()


@pytest.fixture(scope="module", autouse=True)
def _other_user():
    with SessionLocal() as db:
        if not db.scalars(select(User).where(User.email == OTHER[0])).first():
            db.add(User(email=OTHER[0], name="Other Viewer", role="viewer", password_hash=hash_password(OTHER[1])))
            db.commit()


def _as(client, creds):
    client.cookies.clear()
    return {"X-CSRF-Token": login(client, creds)}


def _create(client, h, **over):
    body = {"assigneeId": _uid(VIEWER[0]), "subject": "Splice report Hisar", "description": "Upload the splice loss report of block Hisar-1.", "priority": "HIGH"} | over
    r = client.post("/api/v1/tickets", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, h, tid, text="Completed the splice loss report for all 12 GPs.", files=None):
    files = files if files is not None else [("attachments", ("report.pdf", PDF, "application/pdf"))]
    return client.post(f"/api/v1/tickets/{tid}/submit", data={"description": text}, files=files, headers=h)


def test_full_workflow_and_kpis(client):
    h = _as(client, ADMIN)
    before_admin = client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()
    t = _create(client, h)
    assert t["status"] == "OPEN" and t["code"].startswith("TKT-") and t["createdBy"]["name"] == "Admin"
    assert t["assignee"]["email"] == VIEWER[0]
    k = client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()
    assert k["open"] == before_admin["open"] + 1

    # 2–3. assigned user sees it with its priority, and a notification
    h = _as(client, VIEWER)
    mine = client.get("/api/v1/tickets").json()
    assert t["id"] in [i["id"] for i in mine["items"]]
    d = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert d["priority"] == "HIGH" and {k: d["can"][k] for k in ("start", "submit", "review")} == {"start": True, "submit": False, "review": False}
    n = client.get("/api/v1/tickets/notifications").json()
    assert n["unread"] >= 1 and any(i["ticketId"] == t["id"] and i["kind"] == "ASSIGNED" for i in n["items"])

    # submit before starting is refused; 4. start -> In Progress (Working KPI)
    assert _submit(client, h, t["id"]).status_code == 409
    user_before = client.get("/api/v1/tickets/kpis").json()
    assert client.post(f"/api/v1/tickets/{t['id']}/start", headers=h).json()["status"] == "IN_PROGRESS"
    assert client.get("/api/v1/tickets/kpis").json()["working"] == user_before["working"] + 1

    # 5. upload + submit -> Pending Review; the user cannot change it now
    r = _submit(client, h, t["id"], files=[("attachments", ("report.pdf", PDF, "application/pdf")), ("attachments", ("photo.png", PNG, "image/png"))])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "PENDING_REVIEW" and d["submissions"][0]["version"] == 1 and len(d["submissions"][0]["attachments"]) == 2
    assert d["can"]["submit"] is False
    assert _submit(client, h, t["id"]).status_code == 409
    # users never review or close
    assert client.post(f"/api/v1/tickets/{t['id']}/close", json={}, headers=h).status_code == 403

    # 6–7. admin pending review, view + download
    h = _as(client, ADMIN)
    pend = client.get("/api/v1/tickets", params={"scope": "all", "status": "PENDING_REVIEW"}).json()
    assert t["id"] in [i["id"] for i in pend["items"]]
    assert any(i["ticketId"] == t["id"] and i["kind"] == "SUBMITTED" for i in client.get("/api/v1/tickets/notifications").json()["items"])
    d = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert d["can"]["review"] is True
    att = d["submissions"][0]["attachments"][0]
    r = client.get(f"/api/v1/tickets/attachments/{att['id']}")
    assert r.status_code == 200 and r.content == PDF and r.headers["content-disposition"].startswith("attachment")
    r = client.get(f"/api/v1/tickets/attachments/{att['id']}", params={"inline": "true"})
    assert r.headers["content-disposition"].startswith("inline") and r.headers["content-type"] == "application/pdf"

    # 8. request changes (comment required)
    assert client.post(f"/api/v1/tickets/{t['id']}/request-changes", json={"comment": ""}, headers=h).status_code == 422
    r = client.post(f"/api/v1/tickets/{t['id']}/request-changes", json={"comment": "GP Kaithal-3 is missing in the report."}, headers=h)
    assert r.json()["status"] == "CHANGES_REQUESTED"
    # a second admin action on the same submission is refused (conditional status change)
    assert client.post(f"/api/v1/tickets/{t['id']}/close", json={}, headers=h).status_code == 409

    # 9. user sees the feedback and resubmits
    h = _as(client, VIEWER)
    d = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert d["feedback"]["comment"] == "GP Kaithal-3 is missing in the report." and d["can"]["submit"] is True
    r = _submit(client, h, t["id"], text="Added GP Kaithal-3 to the report as requested.", files=[("attachments", ("report-v2.docx", _docx(), "application/octet-stream"))])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PENDING_REVIEW" and [s["version"] for s in r.json()["submissions"]] == [2, 1]

    # 10–12. admin closes; both dashboards show it
    h = _as(client, ADMIN)
    closed_before = client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()["closed"]
    r = client.post(f"/api/v1/tickets/{t['id']}/close", json={"comment": "Looks good."}, headers=h)
    d = r.json()
    assert d["status"] == "CLOSED" and d["closedBy"]["name"] == "Admin" and d["closedAt"]
    assert d["submissions"][0]["review"] == "ACCEPTED" and d["submissions"][1]["review"] == "CHANGES_REQUESTED"
    assert client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()["closed"] == closed_before + 1
    h = _as(client, VIEWER)
    k = client.get("/api/v1/tickets/kpis").json()
    assert k["closed"] >= 1 and k["total"] == sum(k["byStatus"].values())
    # 14. closed = read-only for the user
    d = client.get(f"/api/v1/tickets/{t['id']}").json()
    assert {k: d["can"][k] for k in ("start", "submit", "review", "progress", "close")} == {"start": False, "submit": False, "review": False, "progress": False, "close": False}
    assert _submit(client, h, t["id"]).status_code == 409

    with SessionLocal() as db:
        actions = [e.action for e in db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == t["id"]).order_by(TicketEvent.id))]
        assert actions == ["CREATED", "STARTED", "SUBMITTED", "CHANGES_REQUESTED", "RESUBMITTED", "CLOSED"]
        assert {"ticket_create", "ticket_submit", "ticket_close"} <= set(db.scalars(select(AuditLog.action)))


def test_other_users_cannot_see_or_change_a_ticket(client):
    h = _as(client, ADMIN)
    t = _create(client, h)
    h = _as(client, VIEWER)
    client.post(f"/api/v1/tickets/{t['id']}/start", headers=h)
    _submit(client, h, t["id"])
    att = client.get(f"/api/v1/tickets/{t['id']}").json()["submissions"][0]["attachments"][0]["id"]

    # 13. another viewer: not in their list, every ID answers 404, never another user's data
    h = _as(client, OTHER)
    assert t["id"] not in [i["id"] for i in client.get("/api/v1/tickets").json()["items"]]
    assert client.get(f"/api/v1/tickets/{t['id']}").status_code == 404
    assert client.get(f"/api/v1/tickets/attachments/{att}").status_code == 404
    assert client.post(f"/api/v1/tickets/{t['id']}/start", headers=h).status_code == 404
    assert _submit(client, h, t["id"]).status_code == 404
    # admin-only endpoints
    assert client.get("/api/v1/tickets", params={"scope": "all"}).status_code == 403
    assert client.get("/api/v1/tickets/kpis", params={"scope": "all"}).status_code == 403
    assert client.get("/api/v1/tickets/assignees").status_code == 403
    assert client.post("/api/v1/tickets", json={"assigneeId": _uid(OTHER[0]), "subject": "abc", "description": "0123456789", "priority": "LOW"}, headers=h).status_code == 403
    assert client.post(f"/api/v1/tickets/{t['id']}/request-changes", json={"comment": "nope nope"}, headers=h).status_code == 403
    # signed out
    client.cookies.clear()
    assert client.get("/api/v1/tickets").status_code == 401


def test_create_validation(client):
    h = _as(client, ADMIN)
    assert client.post("/api/v1/tickets", json={"assigneeId": _uid(VIEWER[0]), "subject": "", "description": "x", "priority": "HIGH"}, headers=h).status_code == 422
    assert client.post("/api/v1/tickets", json={"assigneeId": _uid(VIEWER[0]), "subject": "Valid", "description": "Long enough text", "priority": "URGENT"}, headers=h).status_code == 422
    assert client.post("/api/v1/tickets", json={"assigneeId": _uid(ADMIN[0]), "subject": "Valid", "description": "Long enough text", "priority": "LOW"}, headers=h).status_code == 422
    assert client.post("/api/v1/tickets", json={"assigneeId": 999999, "subject": "Valid", "description": "Long enough text", "priority": "LOW"}, headers=h).status_code == 422
    people = client.get("/api/v1/tickets/assignees").json()
    assert VIEWER[0] in [p["email"] for p in people] and ADMIN[0] not in [p["email"] for p in people]
    # CSRF header required for changes
    assert client.post("/api/v1/tickets", json={"assigneeId": _uid(VIEWER[0]), "subject": "Valid", "description": "Long enough text", "priority": "LOW"}).status_code == 403


def test_file_validation(client):
    h = _as(client, ADMIN)
    t = _create(client, h)
    h = _as(client, VIEWER)
    client.post(f"/api/v1/tickets/{t['id']}/start", headers=h)
    # wrong extension, renamed executable, MIME contradicting the extension, short description
    assert _submit(client, h, t["id"], files=[("attachments", ("tool.exe", b"MZ\x90\x00", "application/octet-stream"))]).status_code == 415
    assert _submit(client, h, t["id"], files=[("attachments", ("report.pdf", b"MZ\x90\x00 not a pdf", "application/pdf"))]).status_code == 415
    assert _submit(client, h, t["id"], files=[("attachments", ("report.pdf", PDF, "text/html"))]).status_code == 415
    assert _submit(client, h, t["id"], files=[("attachments", ("book.xlsx", _docx(), "application/octet-stream"))]).status_code == 415
    assert _submit(client, h, t["id"], text="short").status_code == 422
    # nothing was stored and the ticket is still in progress
    with SessionLocal() as db:
        assert db.scalars(select(TicketAttachment).where(TicketAttachment.ticket_id == t["id"])).first() is None
        assert db.get(Ticket, t["id"]).status == "IN_PROGRESS"
    folder = get_settings().ticket_dir / str(t["id"])
    assert not folder.exists() or not any(folder.iterdir())
    # a description alone is accepted (files are optional)
    assert _submit(client, h, t["id"], files=[]).json()["status"] == "PENDING_REVIEW"


def test_list_search_filters_and_paging(client):
    h = _as(client, ADMIN)
    a = _create(client, h, subject="Unique OLT battery check", priority="CRITICAL")
    _create(client, h, subject="Another routine task", priority="LOW")
    r = client.get("/api/v1/tickets", params={"scope": "all", "search": "olt battery"}).json()
    assert [i["id"] for i in r["items"]] == [a["id"]]
    assert client.get("/api/v1/tickets", params={"scope": "all", "search": a["code"]}).json()["total"] == 1
    assert client.get("/api/v1/tickets", params={"scope": "all", "search": "viewer"}).json()["total"] >= 2  # assigned user's name
    crit = client.get("/api/v1/tickets", params={"scope": "all", "priority": "CRITICAL"}).json()["items"]
    assert crit and all(i["priority"] == "CRITICAL" for i in crit)
    p1 = client.get("/api/v1/tickets", params={"scope": "all", "page_size": 2}).json()
    p2 = client.get("/api/v1/tickets", params={"scope": "all", "page_size": 2, "page": 2}).json()
    assert len(p1["items"]) == 2 and not {i["id"] for i in p1["items"]} & {i["id"] for i in p2["items"]}
    assert client.get("/api/v1/tickets", params={"scope": "all", "date_from": "2001-01-01", "date_to": "2001-01-02"}).json()["total"] == 0
    assert client.get("/api/v1/tickets", params={"scope": "all", "date_from": "2001-01-02", "date_to": "2001-01-01"}).status_code == 422
    assert client.get("/api/v1/tickets", params={"scope": "all", "status": "DONE"}).status_code == 422


def test_notifications_mark_read(client):
    h = _as(client, ADMIN)
    _create(client, h)
    h = _as(client, VIEWER)
    assert client.get("/api/v1/tickets/notifications").json()["unread"] >= 1
    client.post("/api/v1/tickets/notifications/read", headers=h)
    assert client.get("/api/v1/tickets/notifications").json()["unread"] == 0
