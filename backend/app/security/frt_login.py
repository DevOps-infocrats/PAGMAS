"""FRT accounts created with their FRT code only (no e-mail): User Management / user import.

Such an account still needs a unique `users.email` (the login key everywhere), so it gets a fixed, non-deliverable
address built from the code – <code>@frt.invalid (".invalid" is reserved, RFC 2606: it never reaches a mail server;
app.mail.smtp refuses it and every mail list skips it). The user signs in with the FRT code itself (app.api.auth): a
login name without "@" is the FRT code and maps to that address. One code-only login per FRT code.
"""

from __future__ import annotations

import re

FRT_LOGIN_DOMAIN = "frt.invalid"


def frt_code_norm(code: str | None) -> str | None:
    """The FRT code as stored (users.frt_code): spaces collapsed, upper case – the same rule as app.tickets.task.frt_norm."""
    if not isinstance(code, str):
        return None
    t = " ".join(code.split()).upper()
    return t[:60] or None


def frt_login_email(code: str) -> str:
    """The login address of the code-only account of this FRT code (lower case, letters / digits / - . _ only)."""
    c = frt_code_norm(code) or ""
    local = re.sub(r"[^a-z0-9._-]+", "-", c.lower()).strip("-.") or "frt"
    return f"{local}@{FRT_LOGIN_DOMAIN}"


def is_frt_login(email: str | None) -> bool:
    return isinstance(email, str) and email.lower().endswith("@" + FRT_LOGIN_DOMAIN)
