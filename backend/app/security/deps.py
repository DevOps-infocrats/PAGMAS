"""FastAPI dependencies enforcing authentication, roles and CSRF on every protected route."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, User
from .core import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, csrf_matches, decode_session_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache(maxsize=8)
def _networks(proxies: tuple[str, ...]) -> tuple[IPv4Network | IPv6Network, ...]:
    return tuple(ip_network(p.strip(), strict=False) for p in proxies if p.strip())


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    try:
        addr = ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    return (addr.ipv4_mapped or addr) if isinstance(addr, IPv6Address) else addr


def _trusted(value: str, networks: tuple[IPv4Network | IPv6Network, ...]) -> bool:
    addr = _parse_ip(value)
    return addr is not None and any(addr.version == n.version and addr in n for n in networks)


def real_ip(peer: str | None, forwarded_for: str | None) -> str:
    """Client IP. X-Forwarded-For is only honoured when the direct peer is a trusted proxy (TRUSTED_PROXIES: IPs
    or CIDRs), and then read from the right: each proxy appends the address it received the request from, so the
    rightmost entry that is not one of our own proxies is the real client. Entries further left were sent by the
    client and can be forged, so they are never used."""
    peer = peer or "unknown"
    networks = _networks(tuple(get_settings().trusted_proxies))
    if not forwarded_for or not _trusted(peer, networks):
        return peer
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    nearest = peer
    for hop in reversed(hops):
        if _trusted(hop, networks):
            nearest = hop
            continue
        # A malformed entry cannot have come from our proxies: fall back to the last hop we trust.
        return str(_parse_ip(hop)) if _parse_ip(hop) else nearest[:64]
    return nearest[:64]  # every entry is one of our proxies


def client_ip(request: Request) -> str:
    # Several X-Forwarded-For headers are one list, in order (RFC 7230 §3.2.2).
    xff = ", ".join(request.headers.getlist("x-forwarded-for")) or None
    return real_ip(request.client.host if request.client else None, xff)


def audit(db: Session, action: str, request: Request | None, user_id: int | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(action=action, user_id=user_id, ip=client_ip(request) if request else None, detail=(detail or "")[:1000] or None))
    db.commit()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise unauthorized
    claims = decode_session_token(token)
    if not claims:
        raise unauthorized
    try:
        user_id = int(claims["sub"])
    except (KeyError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    # Token is revoked when the user is disabled or token_version was bumped (logout / password change).
    if user is None or not user.is_active or claims.get("ver") != user.token_version:
        raise unauthorized

    # CSRF: every state-changing request must echo the CSRF cookie in a header.
    if request.method not in SAFE_METHODS and not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")

    return CurrentUser(id=user.id, email=user.email, name=user.name, role=user.role)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
