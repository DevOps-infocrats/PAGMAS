import jwt

from .conftest import ADMIN, VIEWER, login


def test_health_is_public_and_hardened(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_protected_endpoints_require_session(client):
    for path in ("/api/v1/meta", "/api/v1/overview", "/api/v1/gps", "/api/v1/ingestion/runs", "/api/v1/users"):
        assert client.get(path).status_code == 401, path


def test_wrong_password_gives_generic_error(client):
    r = client.post("/api/v1/auth/login", json={"email": ADMIN[0], "password": "wrong-password"})
    assert r.status_code == 401
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@pratap-test.in", "password": "wrong-password"})
    assert unknown.status_code == 401
    assert r.json()["detail"] == unknown.json()["detail"]  # no user enumeration


def test_login_rate_limited(client):
    codes = [client.post("/api/v1/auth/login", json={"email": VIEWER[0], "password": "bad-password"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5
    assert 429 in codes[5:]


def test_session_cookie_flags(client):
    r = client.post("/api/v1/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("pratap_session=")][0].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"


def test_csrf_required_for_state_changes(client):
    csrf = login(client)
    assert client.post("/api/v1/auth/logout").status_code == 403  # no header
    assert client.post("/api/v1/auth/logout", headers={"x-csrf-token": "forged"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf}).status_code == 200


def test_logout_revokes_token(client):
    csrf = login(client)
    token = client.cookies.get("pratap_session")
    client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    client.cookies.set("pratap_session", token)  # replay the old token
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tampered_or_unsigned_token_rejected(client):
    login(client)
    token = client.cookies.get("pratap_session")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["role"] = "admin"
    forged = jwt.encode(claims, "not-the-secret", algorithm="HS256")
    client.cookies.set("pratap_session", forged)
    assert client.get("/api/v1/auth/me").status_code == 401
    none_alg = jwt.encode(claims, key=None, algorithm="none")
    client.cookies.set("pratap_session", none_alg)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_viewer_cannot_use_admin_endpoints(client):
    csrf = login(client, VIEWER)
    assert client.get("/api/v1/ingestion/runs").status_code == 403
    assert client.get("/api/v1/users").status_code == 403
    r = client.post("/api/v1/users", headers={"x-csrf-token": csrf}, json={"email": "x@pratap-test.in", "name": "X", "password": "Another!Pass123"})
    assert r.status_code == 403


def test_cross_site_post_blocked(client):
    r = client.post("/api/v1/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_weak_password_rejected(client):
    csrf = login(client)
    r = client.post("/api/v1/users", headers={"x-csrf-token": csrf}, json={"email": "weak@pratap-test.in", "name": "Weak", "password": "short"})
    assert r.status_code == 422


def test_upload_rejects_non_excel(client):
    csrf = login(client)
    r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("fake.xlsx", b"not a zip file", "application/vnd.ms-excel")})
    assert r.status_code == 415


def test_input_validation_on_ids(client):
    login(client)
    assert client.get("/api/v1/gps/..%2F..%2Fetc").status_code in (404, 422)
    assert client.get("/api/v1/overview", params={"week": "DROP TABLE"}).status_code in (422, 503)  # 503 when no data loaded yet


# ---------------------------------------------------------------- hardening (review fixes)


def test_forged_forwarded_for_is_ignored():
    """Behind the Next.js proxy the real client is the entry the proxy appended (rightmost), not a forged first one."""
    from app.security.deps import real_ip

    assert real_ip("127.0.0.1", "1.2.3.4") == "1.2.3.4"  # proxy appended the browser address
    assert real_ip("127.0.0.1", "6.6.6.6, 1.2.3.4") == "1.2.3.4"  # "6.6.6.6" was sent by the client
    assert real_ip("127.0.0.1", "6.6.6.6, 1.2.3.4, 127.0.0.1") == "1.2.3.4"  # our own proxies are skipped
    assert real_ip("203.0.113.9", "6.6.6.6") == "203.0.113.9"  # untrusted peer: header ignored
    assert real_ip(None, None) == "unknown"


def test_forged_forwarded_for_cannot_bypass_the_login_limit(client):
    codes = [
        client.post("/api/v1/auth/login", json={"email": f"x{i}@pratap-test.in", "password": "bad-password"}, headers={"x-forwarded-for": f"9.9.9.{i}"}).status_code
        for i in range(25)
    ]
    assert 429 in codes  # rotating the forged address does not reset the per-IP limit


def test_limiter_forgets_expired_keys(monkeypatch):
    from app.security import core

    clock = [1000.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: clock[0])
    lim = core.SlidingWindowLimiter()
    for i in range(500):
        lim.hit(f"ip:{i}", 5, 60)
    assert len(lim) == 500
    clock[0] += 61  # every window has passed and the sweep is due
    lim.hit("ip:new", 5, 60)
    assert len(lim) == 1


def test_disabled_account_gets_the_generic_error(client, monkeypatch):
    from app.api import auth

    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import select

    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == VIEWER[0])).one()
        u.is_active = False
        db.commit()
    try:
        r = client.post("/api/v1/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]})
        assert r.status_code == 401 and r.json()["detail"] == "The email or password is incorrect."
        assert calls and calls[-1] is not None  # the real hash was checked, same work as a wrong password
    finally:
        with SessionLocal() as db:
            u = db.scalars(select(User).where(User.email == VIEWER[0])).one()
            u.is_active = True
            db.commit()


def test_imports_run_one_at_a_time(monkeypatch):
    import threading

    from app.ingestion import service

    running, peak = [0], [0]
    gate = threading.Lock()

    def fake(_id):
        with gate:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        threading.Event().wait(0.05)
        with gate:
            running[0] -= 1

    monkeypatch.setattr(service, "_run_ingestion", fake)
    threads = [threading.Thread(target=service.run_ingestion, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1
