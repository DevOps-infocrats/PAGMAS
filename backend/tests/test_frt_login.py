"""FRT accounts created with their FRT code only – no e-mail (User Management and the user import):

* Add user without an e-mail but with an FRT code of the active Escalation Matrix creates a Viewer that signs in with the
  FRT code (any case) and the password; a code not in the matrix, an admin, no e-mail and no code are refused; one such
  login per FRT code; the login follows a changed code; the code cannot be removed while it is the only login;
* the import template has an FRT Code column: a row without e-mail but with a valid FRT code creates such a login; a
  code not in the matrix / twice in the file / a row with neither is skipped;
* such an address never reaches the mail server (app.mail.smtp).
"""

import io
from email.message import EmailMessage

import pandas as pd
import pytest
from sqlalchemy import delete

from app.db import SessionLocal
from app.models import User

from .conftest import login

PW = "FrtUx!Secure-Pass-92"


@pytest.fixture
def matrix(monkeypatch):
    """An active Escalation Matrix with the FRT codes RJUX-001 / RJUX-002 (what the FRT code is checked against)."""
    from app.analytics import escalation

    monkeypatch.setattr(escalation, "_active", lambda: ({"id": 0}, pd.DataFrame({"frt_code": ["RJUX-001", "RJUX-002", None]})))


def _cleanup():
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email.like("%@frt.invalid")))
        db.commit()


def test_add_user_with_frt_code_and_no_email(client, matrix):
    _cleanup()
    h = {"X-CSRF-Token": login(client)}
    base = {"name": "Frt Ux One", "role": "viewer", "password": PW}
    assert client.post("/api/v1/users", json={**base, "frtCode": "RJUX-999"}, headers=h).status_code == 422  # not in the matrix
    assert client.post("/api/v1/users", json={**base, "role": "admin", "frtCode": "RJUX-001"}, headers=h).status_code == 422
    assert client.post("/api/v1/users", json=base, headers=h).status_code == 422  # neither e-mail nor FRT code
    r = client.post("/api/v1/users", json={**base, "frtCode": " rjux-001 "}, headers=h)
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["loginType"] == "frt" and u["frtCode"] == "RJUX-001"
    assert client.post("/api/v1/users", json={**base, "name": "Again", "frtCode": "RJUX-001"}, headers=h).status_code == 409  # one per code
    # signs in with the FRT code (any case) and the password
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": "rjux-001", "password": PW}).status_code == 200
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": "RJUX-001", "password": "wrong-password-123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "RJUX-002", "password": PW}).status_code == 401
    # a normal e-mail login still works as before
    client.cookies.clear()
    login(client)
    # the code changes: the login follows it; removing the only login (code without e-mail) is refused
    h = {"X-CSRF-Token": login(client)}
    assert client.patch(f"/api/v1/users/{u['id']}", json={"frtCode": ""}, headers=h).status_code == 422
    r = client.patch(f"/api/v1/users/{u['id']}", json={"frtCode": "RJUX-002"}, headers=h)
    assert r.status_code == 200 and r.json()["frtCode"] == "RJUX-002"
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": "RJUX-002", "password": PW}).status_code == 200
    _cleanup()


def test_import_template_with_frt_code(client, matrix):
    _cleanup()
    csrf = login(client)
    tpl = client.get("/api/v1/users/import/template.xlsx")
    assert tpl.status_code == 200 and "FRT Code" in list(pd.read_excel(io.BytesIO(tpl.content), sheet_name="Users", engine="calamine").columns)
    df = pd.DataFrame(
        [
            ["Frt Import One", None, "FrtImp!Secure-Pass-93", "RJUX-001"],  # FRT login (no e-mail)
            ["Frt Bad Code", None, None, "RJUX-404"],  # not in the matrix → skipped
            ["Frt Import Dup", None, None, "rjux-001"],  # the same code twice in the file → skipped
            ["Nobody", None, None, None],  # neither e-mail nor FRT code → skipped
        ],
        columns=["Name", "Email", "Password", "FRT Code"],
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    url = "/api/v1/users/import"
    p = client.post(f"{url}?dryRun=true", headers={"x-csrf-token": csrf}, files={"file": ("users.xlsx", buf.getvalue(), "application/octet-stream")})
    assert p.status_code == 200, p.text
    items = {it["name"]: it for it in p.json()["items"]}
    assert items["Frt Import One"]["status"] == "NEW" and items["Frt Import One"]["frtLogin"] is True and items["Frt Import One"]["email"] is None
    assert items["Frt Bad Code"]["status"] == "SKIPPED" and "not in the active Escalation Matrix" in items["Frt Bad Code"]["reason"]
    assert items["Frt Import Dup"]["status"] == "SKIPPED" and "Duplicate FRT code" in items["Frt Import Dup"]["reason"]
    assert items["Nobody"]["status"] == "SKIPPED"
    p = client.post(f"{url}?dryRun=false", headers={"x-csrf-token": csrf}, files={"file": ("users.xlsx", buf.getvalue(), "application/octet-stream")})
    assert p.json()["created"] == 1
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": "RJUX-001", "password": "FrtImp!Secure-Pass-93"}).status_code == 200
    _cleanup()


def test_frt_login_address_never_reaches_the_mail_server():
    from app.mail import smtp

    class Conn:
        sent = 0

        def send_message(self, msg):
            Conn.sent += 1
            return {}

    s = smtp.SmtpSession.__new__(smtp.SmtpSession)
    s.conn = Conn()
    msg = EmailMessage()
    msg["To"] = "rjux-001@frt.invalid"
    with pytest.raises(smtp.MailError):
        s.send(msg)
    ok = EmailMessage()
    ok["To"] = "person@pratap-test.in"
    s.send(ok)
    assert Conn.sent == 1
