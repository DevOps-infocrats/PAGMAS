"""Authentication primitives: password hashing, session tokens, CSRF, rate limiting."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import get_settings

SESSION_COOKIE = "pratap_session"
CSRF_COOKIE = "pratap_csrf"
CSRF_HEADER = "x-csrf-token"
# JWT algorithm, issuer, audience and keys come from backend/.env (config.Settings).

_hasher = PasswordHasher()  # Argon2id with library defaults (memory-hard)
# Pre-computed hash so unknown e-mails take the same time as wrong passwords.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, email: str = "") -> list[str]:
    """Simple strength policy (length beats complexity rules)."""
    problems = []
    if len(password) < 12:
        problems.append("at least 12 characters")
    if len(password) > 128:
        problems.append("at most 128 characters")
    if password.lower() in {"password1234", "123456789012", "qwertyuiop12"}:
        problems.append("not a common password")
    if email and email.split("@")[0].lower() in password.lower():
        problems.append("must not contain your e-mail name")
    classes = sum(bool(any(f(c) for c in password)) for f in (str.islower, str.isupper, str.isdigit, lambda c: not c.isalnum()))
    if classes < 3:
        problems.append("a mix of at least 3 of: lower-case, upper-case, digits, symbols")
    return problems


# ---------------------------------------------------------------- session tokens


def create_session_token(user_id: int, role: str, token_version: int) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.session_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "ver": token_version,
        "iat": now,
        "nbf": now,
        "exp": exp,
        "aud": s.jwt_audience,
        "iss": s.jwt_issuer,
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm), exp


def decode_session_token(token: str) -> dict | None:
    """Verify signature, expiry, issuer and audience. The previous key (SECRET_KEY_PREVIOUS)
    is accepted too, so rotating SECRET_KEY does not sign everybody out at once."""
    s = get_settings()
    if not token or len(token) > 4096:
        return None
    for key in (s.secret_key, s.secret_key_previous):
        if not key:
            continue
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[s.jwt_algorithm],  # pinned: rejects "none"/alg-confusion
                audience=s.jwt_audience,
                issuer=s.jwt_issuer,
                leeway=10,
                options={"require": ["exp", "iat", "nbf", "sub", "aud", "iss", "jti"]},
            )
        except jwt.InvalidSignatureError:
            continue  # maybe signed with the previous key
        except jwt.PyJWTError:
            return None
    return None


# ---------------------------------------------------------------- CSRF (double-submit cookie)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    return bool(cookie_value and header_value) and hmac.compare_digest(cookie_value, header_value)  # type: ignore[arg-type]


# ---------------------------------------------------------------- rate limiting


class SlidingWindowLimiter:
    """In-process sliding-window limiter (use Redis when running several workers).
    Keys whose window has passed are swept out once a minute, so random IPs / e-mails cannot grow memory."""

    SWEEP_EVERY = 60.0

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._windows: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - self._windows.get(k, 0)]:
            self._hits.pop(k, None)
            self._windows.pop(k, None)
        self._last_sweep = now

    def __len__(self) -> int:
        return len(self._hits)

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit; returns False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep >= self.SWEEP_EVERY:
                self._sweep(now)
            self._windows[key] = max(window_seconds, self._windows.get(key, 0))
            q = self._hits[key]
            while q and q[0] <= now - window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._windows.pop(key, None)


login_limiter = SlidingWindowLimiter()
api_limiter = SlidingWindowLimiter()
