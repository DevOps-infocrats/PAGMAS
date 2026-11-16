"""Deleting a dashboard account: the account and its areas go, nothing else is touched; an admin cannot delete
their own account."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, User, UserScope

from .conftest import ADMIN, login


def test_admin_deletes_a_user_and_its_areas(client):
    h = {"x-csrf-token": login(client)}
    email = "delete.me@pratap.co.in"
    with SessionLocal() as db:
        old = db.scalars(select(User).where(User.email == email)).first()
        if old:
            db.delete(old)
            db.commit()
    r = client.post("/api/v1/users", json={"email": email, "name": "Delete Me", "password": "Delete!Me-Secure-Pass-88", "scopes": []}, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    with SessionLocal() as db:
        db.add(UserScope(user_id=uid, level="circle", scope_id="haryana"))
        db.commit()
    r = client.post(f"/api/v1/users/{uid}/delete", headers=h)
    assert r.status_code == 200 and r.json() == {"deleted": uid}
    with SessionLocal() as db:
        assert db.get(User, uid) is None
        assert not db.scalars(select(UserScope).where(UserScope.user_id == uid)).first()
        assert db.scalars(select(AuditLog).where(AuditLog.action == "user_deleted", AuditLog.detail.contains(email))).first()
    assert client.post(f"/api/v1/users/{uid}/delete", headers=h).status_code == 404


def test_admin_cannot_delete_own_account(client):
    h = {"x-csrf-token": login(client)}
    with SessionLocal() as db:
        uid = db.scalars(select(User.id).where(User.email == ADMIN[0])).one()
    r = client.post(f"/api/v1/users/{uid}/delete", headers=h)
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.get(User, uid) is not None
