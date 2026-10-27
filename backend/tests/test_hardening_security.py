import logging
import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Dataset, EscalationImport, User
from app.security.core import hash_password, login_limiter

from .conftest import ADMIN, login

LOCK_USER = ("lockout@pratap-test.in", "L0ckout!Secure-Pass")
URL = "/api/v1/auth/login"


@pytest.fixture
def lock_user():
    """Dedicated account (fresh password / lock state for every test)."""
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == LOCK_USER[0])).first()
        if u is None:
            u = User(email=LOCK_USER[0], name="Lockout", role="viewer", password_hash="")
            db.add(u)
        u.password_hash, u.failed_logins, u.locked_until, u.is_active = hash_password(LOCK_USER[1]), 0, None, True
        db.commit()
    return LOCK_USER


@pytest.fixture
def proxied():
    """Client whose direct peer is the (trusted) Next.js proxy on 127.0.0.1."""
    with TestClient(app, base_url="http://localhost", headers={"origin": "http://localhost:3000"}, client=("127.0.0.1", 50000)) as c:
        yield c


def _post(c, creds, password=None, xff=None, **extra):
    headers = {"x-forwarded-for": xff} if xff else {}
    return c.post(URL, json={"email": creds[0], "password": password or creds[1], **extra}, headers=headers)


# ---------------------------------------------------------------- 1. client IP behind proxies


def test_real_ip_takes_rightmost_untrusted_hop(monkeypatch):
    from app.security.deps import real_ip

    monkeypatch.setattr(get_settings(), "trusted_proxies", ["127.0.0.1", "::1", "10.0.0.0/8"])
    assert real_ip("127.0.0.1", "6.6.6.6, 1.2.3.4") == "1.2.3.4"
    assert real_ip("127.0.0.1", "6.6.6.6, 1.2.3.4, 10.1.2.3") == "1.2.3.4"  # nginx in 10/8 skipped (CIDR)
    assert real_ip("10.9.9.9", "1.2.3.4") == "1.2.3.4"
    assert real_ip("::ffff:127.0.0.1", "1.2.3.4") == "1.2.3.4"  # IPv4-mapped peer
    assert real_ip("127.0.0.1", "1.2.3.4, not-an-ip") == "127.0.0.1"  # malformed rightmost hop: not trusted
    assert real_ip("127.0.0.1", "10.0.0.5, 127.0.0.1") == "10.0.0.5"  # only proxies: the farthest one
    assert real_ip("1.2.3.4", "10.0.0.5") == "1.2.3.4"  # untrusted peer: header ignored
    assert real_ip("testclient", "1.2.3.4") == "testclient"


def test_invalid_trusted_proxy_rejected():
    with pytest.raises(ValidationError, match="TRUSTED_PROXIES"):
        Settings(_env_file=None, trusted_proxies=["nginx"])


def test_forged_leftmost_hop_does_not_reset_the_strict_limit(proxied, lock_user):
    codes = [_post(proxied, lock_user, "bad-password", xff=f"9.9.9.{i}, 1.2.3.4").status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]


def test_multiple_forwarded_headers_are_one_list(proxied, lock_user):
    for _ in range(5):
        proxied.post(URL, json={"email": lock_user[0], "password": "bad-password"}, headers=[("x-forwarded-for", "9.9.9.9"), ("x-forwarded-for", "1.2.3.4")])
    assert _post(proxied, lock_user, "bad-password", xff="1.2.3.4").status_code == 429  # same client: 1.2.3.4


# ---------------------------------------------------------------- 2. login lockout DoS


def test_attacker_cannot_lock_out_the_real_user(proxied, lock_user):
    for _ in range(8):
        _post(proxied, lock_user, "bad-password", xff="6.6.6.6")
    assert _post(proxied, lock_user, xff="6.6.6.6").status_code == 429  # attacker's own pair is limited
    assert _post(proxied, lock_user, xff="1.2.3.4").status_code == 200  # real user, other IP, still gets in


def test_account_lock_only_applies_to_failing_sources(proxied, lock_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "account_lockout_threshold", 3)
    for _ in range(3):
        assert _post(proxied, lock_user, "bad-password", xff="6.6.6.6").status_code == 401
    with SessionLocal() as db:
        assert db.scalars(select(User).where(User.email == lock_user[0])).one().locked_until is not None
    assert _post(proxied, lock_user, xff="6.6.6.6").status_code == 401  # locked for the failing source, even with the right password
    assert _post(proxied, lock_user, xff="1.2.3.4").status_code == 200  # clean source can sign in (and clears the lock)
    with SessionLocal() as db:
        assert db.scalars(select(User).where(User.email == lock_user[0])).one().locked_until is None


def test_per_account_backstop(proxied, lock_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_account_max_attempts", 3)
    codes = [_post(proxied, lock_user, "bad-password", xff=f"7.7.7.{i}").status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]


def test_successful_logins_do_not_use_up_the_ip_bucket(client):
    for _ in range(get_settings().login_max_attempts * 4 + 2):
        assert client.post(URL, json={"email": ADMIN[0], "password": ADMIN[1]}).status_code == 200


def test_rate_limited_attempts_are_logged_not_audited(client, lock_user, caplog):
    for _ in range(5):
        _post(client, lock_user, "bad-password")
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(AuditLog))
    with caplog.at_level(logging.WARNING, logger="pratap.auth"):
        assert all(_post(client, lock_user, "bad-password").status_code == 429 for _ in range(3))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == before
    assert "rate-limited" in caplog.text


# ---------------------------------------------------------------- 3. production configuration

KEY = "Prod-Secret-0123456789-abcdefghijklmnopqrstuvwxyz-ABCDEFGH"
PROD = {"_env_file": None, "app_env": "production", "secret_key": KEY, "cors_origins": ["https://dashboard.example.in"]}


def test_production_settings_accepted_and_hosts_default():
    s = Settings(**PROD)
    assert "testserver" not in s.trusted_hosts and s.secure_cookies
    assert "testserver" in Settings(_env_file=None, app_env="test", secret_key=KEY).trusted_hosts


@pytest.mark.parametrize(
    ("override", "env_var"),
    [
        ({"cors_origins": ["http://localhost:3000", "http://127.0.0.1:3000"]}, "CORS_ORIGINS"),
        ({"trusted_hosts": ["dashboard.example.in", "testserver"]}, "TRUSTED_HOSTS"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"ADMIN_PASSWORD": "Adm1n!Secure-Pass"}, "ADMIN_PASSWORD_HASH"),
    ],
)
def test_production_refuses_unsafe_settings(override, env_var):
    with pytest.raises(ValidationError, match=env_var):
        Settings(**{**PROD, **override})


# ---------------------------------------------------------------- 4. body size limits


def test_small_body_limit_outside_upload(client):
    r = client.post(URL, content=b"{" + b" " * (70 * 1024) + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.headers["x-content-type-options"] == "nosniff"


def test_chunked_oversized_body_gives_413(client):
    def chunks():
        for _ in range(10):
            yield b" " * 10_000

    r = client.post(URL, content=chunks(), headers={"content-type": "application/json"})
    assert "content-length" not in r.request.headers
    assert r.status_code == 413, r.text


def test_upload_path_keeps_the_large_limit(client):
    csrf = login(client)
    body = b"PK" + os.urandom(200 * 1024)  # > 64 KB, rejected for its content, not its size
    r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("big.xlsx", body, "application/vnd.ms-excel")})
    assert r.status_code == 415


# ---------------------------------------------------------------- 5. health / readiness


def test_ready_reports_database(client):
    r = client.get("/api/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and isinstance(r.json()["snapshotLoaded"], bool)


def test_ready_503_when_database_down(client, monkeypatch):
    from app import main

    class Down:
        def connect(self):
            raise ConnectionError("db down")

    monkeypatch.setattr(main, "engine", Down())
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}
    assert client.get("/api/health").status_code == 200  # liveness does not touch the database


def test_probes_skip_rate_limit_and_access_log(client, monkeypatch, caplog):
    from app.security import middleware

    monkeypatch.setattr(middleware.api_limiter, "hit", lambda *a: False)
    with caplog.at_level(logging.INFO, logger="pratap.access"):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 429
    logged = [r.getMessage() for r in caplog.records if r.name == "pratap.access"]
    assert not any("/api/health" in m or "/api/ready" in m for m in logged)


def test_unhandled_error_is_generic_and_hardened(client):
    def boom():
        raise RuntimeError("secret internals")

    if not any(getattr(r, "path", None) == "/api/__boom_test" for r in app.routes):
        app.add_api_route("/api/__boom_test", boom)
    r = client.get("/api/__boom_test")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers.get("x-request-id")


# ---------------------------------------------------------------- 6. start-up


def test_interrupted_imports_marked_failed():
    from app.main import INTERRUPTED, _fail_interrupted

    with SessionLocal() as db:
        ds = Dataset(file_name="x.xlsb", stored_path="/nonexistent/x.xlsb", sha256="0" * 64, status="PROCESSING")
        esc = EscalationImport(file_name="e.xlsx", stored_path="/nonexistent/e.xlsx", sha256="0" * 64, status="PROCESSING")
        db.add_all([ds, esc])
        db.commit()
        try:
            _fail_interrupted(db)
            db.expire_all()
            for row in (db.get(Dataset, ds.id), db.get(EscalationImport, esc.id)):
                assert row.status == "FAILED" and row.message == INTERRUPTED and row.finished_at is not None
        finally:
            db.execute(delete(Dataset).where(Dataset.id == ds.id))
            db.execute(delete(EscalationImport).where(EscalationImport.id == esc.id))
            db.commit()


def test_startup_import_picks_newest_master_file_by_mtime(tmp_path):
    from app.main import _newest_master_file

    files = {
        "Master Data V8.2 Daily track 14-10-26.xlsb": 1_000,
        "Master Data V8.2 Daily track 09-10-26.xlsb": 3_000,  # newest master by mtime, not by name
        "Escalation Matrix 20-10-26.xlsx": 5_000,
        "notes.txt": 9_000,
    }
    for name, mtime in files.items():
        (tmp_path / name).write_bytes(b"x")
        os.utime(tmp_path / name, (mtime, mtime))
    assert _newest_master_file(tmp_path).name == "Master Data V8.2 Daily track 09-10-26.xlsb"
    assert _newest_master_file(tmp_path / "missing") is None


def test_startup_import_skips_non_master_workbooks(tmp_path, monkeypatch):
    from app import main
    from app.ingestion import escalation, service

    imported = []
    monkeypatch.setattr(service, "import_file", lambda p: imported.append(p))
    monkeypatch.setattr(escalation, "detect_kind", lambda p: "escalation")
    main._auto_import(tmp_path / "a.xlsx")
    monkeypatch.setattr(escalation, "detect_kind", lambda p: "master")
    main._auto_import(tmp_path / "b.xlsx")
    assert [p.name for p in imported] == ["b.xlsx"]


# ---------------------------------------------------------------- 7 / 8. admin e-mail, change-password


def test_invalid_admin_email_is_not_created(monkeypatch, caplog):
    from app import main

    s = get_settings()
    monkeypatch.setattr(s, "admin_email", "admin@localhost")
    monkeypatch.setattr(s, "admin_password", "Adm1n!Secure-Pass")
    with SessionLocal() as db, caplog.at_level(logging.ERROR, logger="pratap"):
        main._ensure_env_admin(db)
        assert db.scalars(select(User).where(User.email == "admin@localhost")).first() is None
    assert "not a valid e-mail" in caplog.text


def test_cli_rejects_invalid_email():
    from app.cli import main as cli

    assert cli(["create-user", "--email", "not-an-email", "--name", "X", "--password", "Another!Pass1234"]) != 0


def test_change_password_rate_limited_and_keeps_remember_me(client, lock_user):
    assert _post(client, lock_user, remember=True).status_code == 200
    csrf = client.cookies.get("pratap_csrf")
    url = "/api/v1/auth/change-password"
    codes = [client.post(url, headers={"x-csrf-token": csrf}, json={"currentPassword": "wrong", "newPassword": "N3w!Secure-Passw0rd"}).status_code for _ in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429
    login_limiter._hits.clear()
    r = client.post(url, headers={"x-csrf-token": csrf}, json={"currentPassword": lock_user[1], "newPassword": "N3w!Secure-Passw0rd"})
    assert r.status_code == 200
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("pratap_session=")][0].lower()
    assert "max-age=" in cookie  # still a persistent cookie
    assert client.get("/api/v1/auth/me").status_code == 200
