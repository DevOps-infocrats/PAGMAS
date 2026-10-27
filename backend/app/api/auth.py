import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security.core import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session_token,
    decode_session_token,
    hash_password,
    login_limiter,
    needs_rehash,
    new_csrf_token,
    password_problems,
    verify_password,
)
from ..security.deps import CurrentUser, audit, client_ip, get_current_user

log = logging.getLogger("pratap.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
GENERIC_LOGIN_ERROR = "The email or password is incorrect."


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128, alias="currentPassword")
    new_password: str = Field(min_length=1, max_length=128, alias="newPassword")


def user_json(u: User | CurrentUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


def _set_session_cookies(response: Response, token: str, max_age: int | None) -> str:
    s = get_settings()
    csrf = new_csrf_token()
    common = {"secure": s.secure_cookies, "samesite": "lax", "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=max_age, **common)
    # Readable by the frontend so it can echo it in the X-CSRF-Token header.
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, max_age=max_age, **common)
    return csrf


def _cookie_max_age(exp: datetime, remember: bool) -> int | None:
    """Browser-session cookie unless "remember me" was chosen at sign-in."""
    return int((exp - datetime.now(UTC)).total_seconds()) if remember else None


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    ip = client_ip(request)
    email = body.email.lower()
    window = s.login_window_seconds
    ip_key, pair_key, acct_key = f"ip:{ip}", f"pair:{email}|{ip}", f"acct:{email}"
    # Failures of this e-mail from this IP still inside the window (successes reset the pair bucket).
    pair_failed = login_limiter.count(pair_key, window) > 0
    # Strict limit per (e-mail, IP), so guessing from one address cannot lock the real user out from theirs;
    # looser limits per IP (many e-mails) and per account (many IPs) as backstops.
    if not (
        login_limiter.hit(ip_key, s.login_max_attempts * 4, window)
        and login_limiter.hit(pair_key, s.login_max_attempts, window)
        and login_limiter.hit(acct_key, s.login_account_max_attempts, window)
    ):
        log.warning("Login rate-limited for %s from %s", email, ip)  # no audit row: an attacker could flood the table
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-in attempts. Please wait 15 minutes and try again.")

    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    now = datetime.now(UTC)
    # A locked account only rejects sources that took part in the failures; a clean (e-mail, IP) pair may still try.
    if user and pair_failed and user.locked_until and user.locked_until.replace(tzinfo=user.locked_until.tzinfo or UTC) > now:
        verify_password(body.password, None)  # keep timing uniform
        audit(db, "login_locked", request, user.id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    # Always verify (also for disabled accounts) so the response time does not reveal which accounts exist.
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not user.is_active or not password_ok:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= s.account_lockout_threshold:
                user.locked_until = now + timedelta(minutes=s.account_lockout_minutes)
                user.failed_logins = 0
            db.commit()
        audit(db, "login_failed", request, user.id if user else None, email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    # A successful sign-in does not count: give back the IP / account hits and forget this pair's failures.
    login_limiter.refund(ip_key)
    login_limiter.refund(acct_key)
    login_limiter.reset(pair_key)

    token, exp = create_session_token(user.id, user.role, user.token_version, remember=body.remember)
    _set_session_cookies(response, token, _cookie_max_age(exp, body.remember))
    audit(db, "login", request, user.id)
    return {"user": user_json(user), "expiresAt": exp.isoformat()}


@router.post("/logout")
def logout(request: Request, response: Response, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    db_user = db.get(User, user.id)
    if db_user:
        db_user.token_version += 1  # revokes every token issued so far
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    audit(db, "logout", request, user.id)
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"user": user_json(user)}


@router.post("/change-password")
def change_password(
    body: PasswordChangeIn, request: Request, response: Response, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    s = get_settings()
    key = f"pwchange:{user.id}"
    # A stolen session must not become an unlimited oracle for the current password.
    if not login_limiter.hit(key, s.login_max_attempts, s.login_window_seconds):
        log.warning("Password change rate-limited for user %s", user.id)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please wait 15 minutes and try again.")
    db_user = db.get(User, user.id)
    if not db_user or not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    login_limiter.reset(key)
    problems = password_problems(body.new_password, db_user.email)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password needs " + "; ".join(problems))
    db_user.password_hash = hash_password(body.new_password)
    db_user.token_version += 1
    db.commit()
    claims = decode_session_token(request.cookies.get(SESSION_COOKIE) or "") or {}
    remember = claims.get("rem") is True
    token, exp = create_session_token(db_user.id, db_user.role, db_user.token_version, remember=remember)
    _set_session_cookies(response, token, _cookie_max_age(exp, remember))
    audit(db, "password_changed", request, user.id)
    return {"ok": True}
