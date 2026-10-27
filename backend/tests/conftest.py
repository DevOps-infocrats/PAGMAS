import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="pratap-test-"))
os.environ.update(
    {
        "APP_ENV": "test",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATA_DIR": str(_TMP / "data"),  # empty -> no automatic import on startup
        "CORS_ORIGINS": '["http://localhost:3000"]',
        # Never reach the real mail server from tests: blank SMTP settings override backend/.env, the scheduler stays off.
        "MAIL_SERVER": "",
        "MAIL_PORT": "",
        "MAIL_USERNAME": "",
        "MAIL_PASSWORD": "",
        "MAIL_DEFAULT_SENDER": "",
        "AMC_REPORT_EMAILS_ENABLED": "false",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security.core import hash_password, login_limiter  # noqa: E402

ADMIN = ("admin@pratap-test.in", "Adm1n!Secure-Pass")
VIEWER = ("viewer@pratap-test.in", "V1ewer!Secure-Pass")
REAL_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "Master Data V8.2 Daily track 09-10-26.xlsb"


@pytest.fixture(scope="session", autouse=True)
def _users():
    init_db()
    with SessionLocal() as db:
        for (email, pw), role in ((ADMIN, "admin"), (VIEWER, "viewer")):
            db.add(User(email=email, name=role.title(), role=role, password_hash=hash_password(pw)))
        db.commit()


@pytest.fixture(autouse=True)
def _reset_limits():
    login_limiter._hits.clear()


class _NoRealSmtp:
    def __init__(self, *a, **k):
        raise AssertionError("A test tried to open a real SMTP connection")


@pytest.fixture(autouse=True)
def _no_real_smtp(monkeypatch):
    """Guard for every test: opening a real SMTP connection fails the test. Mail tests replace this with a fake."""
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _NoRealSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _NoRealSmtp)


@pytest.fixture
def client():
    with TestClient(app, base_url="http://localhost", headers={"origin": "http://localhost:3000"}) as c:
        yield c


def login(client: TestClient, creds=ADMIN) -> str:
    r = client.post("/api/v1/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return client.cookies.get("pratap_csrf")


@pytest.fixture(scope="session")
def imported():
    if not REAL_FILE.exists():
        pytest.skip("Real master data file not available")
    from app.analytics.store import get_store, invalidate_cache
    from app.ingestion.service import import_file

    ds = import_file(REAL_FILE)
    assert ds.status in {"SUCCESS", "PARTIAL"}, ds.message
    invalidate_cache()
    return get_store()
