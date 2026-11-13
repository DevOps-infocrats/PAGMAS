"""Bulk user import on User Management: Excel / CSV with Name + Email -> Viewer accounts with the temporary password."""

import io

import xlsxwriter
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, User
from app.security.core import verify_password
from .conftest import ADMIN, VIEWER, login

URL = "/api/v1/users/import"


def _xlsx(rows: list[list[object]]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet()
    for i, r in enumerate(rows):
        ws.write_row(i, 0, r)
    wb.close()
    return buf.getvalue()


def _post(client, csrf, data: bytes, name="users.xlsx", dry=True):
    return client.post(f"{URL}?dryRun={'true' if dry else 'false'}", headers={"x-csrf-token": csrf}, files={"file": (name, data, "application/octet-stream")})


def _cleanup(*emails: str) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email.in_(emails)))
        db.execute(delete(AuditLog).where(AuditLog.action == "users_imported"))
        db.commit()


def test_preview_then_import_creates_viewers_with_temp_password(client):
    csrf = login(client)
    data = _xlsx(
        [
            ["Pratap user list"],  # title row above the header
            ["S.No.", "Employee Name", "Email ID", "Mobile"],
            [1, "Ravi  Kumar", "Ravi.Kumar@Imp-Test.in", "99999"],
            [2, "Sita Devi", "sita@imp-test.in", None],
            [3, "Existing Admin", ADMIN[0], None],
            [4, "Bad Mail", "not-an-email", None],
            [5, "Ravi Again", "ravi.kumar@imp-test.in", None],
            [6, None, "noname@imp-test.in", None],
            [None, None, None, None],
        ]
    )
    try:
        r = _post(client, csrf, data)
        assert r.status_code == 200, r.text
        p = r.json()
        assert (p["dryRun"], p["total"], p["new"], p["created"], p["exists"], p["skipped"]) == (True, 6, 2, 0, 1, 3)
        by = {(it["row"], it["email"]): it for it in p["items"]}
        assert by[(3, "ravi.kumar@imp-test.in")]["name"] == "Ravi Kumar"
        assert by[(6, "not-an-email")]["reason"] == "Invalid e-mail address"
        assert by[(7, "ravi.kumar@imp-test.in")]["reason"] == "Duplicate e-mail in the file"
        assert by[(8, "noname@imp-test.in")]["reason"] == "Name missing"
        with SessionLocal() as db:  # preview creates nothing
            assert db.scalars(select(User).where(User.email == "sita@imp-test.in")).first() is None

        r = _post(client, csrf, data, dry=False)
        assert r.status_code == 200, r.text
        p = r.json()
        assert (p["created"], p["exists"]) == (2, 1)
        assert sorted(it["email"] for it in p["items"] if it["status"] == "CREATED") == ["ravi.kumar@imp-test.in", "sita@imp-test.in"]
        with SessionLocal() as db:
            u = db.scalars(select(User).where(User.email == "ravi.kumar@imp-test.in")).one()
            assert (u.name, u.role, u.is_active) == ("Ravi Kumar", "viewer", True)
            assert verify_password(get_settings().user_import_password, u.password_hash)
            admin = db.scalars(select(User).where(User.email == ADMIN[0])).one()
            assert admin.role == "admin" and admin.name == "Admin"  # existing account untouched
        # the new user signs in with the temporary password
        login(client, ("sita@imp-test.in", "bsnl@1234567"))

        # importing the same file again changes nothing
        csrf = login(client)
        p = _post(client, csrf, data, dry=False).json()
        assert (p["created"], p["exists"]) == (0, 3)
    finally:
        _cleanup("ravi.kumar@imp-test.in", "sita@imp-test.in")


def test_csv_and_header_variants(client):
    csrf = login(client)
    data = "Name,E-mail\nAsha Rani,asha@imp-test.in\n".encode("utf-8-sig")
    try:
        p = _post(client, csrf, data, name="list.csv", dry=False).json()
        assert p["created"] == 1
    finally:
        _cleanup("asha@imp-test.in")


def test_bad_files_are_refused(client):
    csrf = login(client)
    assert _post(client, csrf, b"MZ\x90\x00", name="evil.exe").status_code == 415
    assert _post(client, csrf, b"not a zip", name="fake.xlsx").status_code == 422
    r = _post(client, csrf, _xlsx([["Circle", "Block"], ["Haryana", "Hisar"]]))
    assert r.status_code == 422 and "Name" in r.json()["detail"]


def test_viewer_cannot_import(client):
    csrf = login(client, VIEWER)
    assert _post(client, csrf, _xlsx([["Name", "Email"], ["X Y", "x@imp-test.in"]])).status_code == 403
