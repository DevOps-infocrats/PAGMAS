"""SMTP settings check and delivery (MAIL_* variables in backend/.env).

Nothing here runs on its own: `send` is called only by the admin's "Send Test Mail" action and by the scheduler for a
due, enabled schedule. Passwords never reach a log line or an error message.
"""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from email_validator import EmailNotValidError, validate_email

from ..config import Settings, get_settings

log = logging.getLogger(__name__)


class MailError(Exception):
    """A delivery problem, with a message that is safe to show to an admin (no secrets, no addresses)."""


@dataclass(frozen=True)
class SmtpStatus:
    configured: bool
    problems: list[str]
    server: str | None
    port: int | None
    security: str  # "SSL" | "STARTTLS" | "none"
    username_set: bool
    sender: str | None


def valid_address(value: str | None) -> str | None:
    """The address in normalised lower-case form, or None (syntax check only – no DNS lookup)."""
    if not value or not isinstance(value, str):
        return None
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def _port(s: Settings) -> int | None:
    try:
        p = int(str(s.mail_port).strip())
    except (TypeError, ValueError):
        return None
    return p if 1 <= p <= 65535 else None


def smtp_status(s: Settings | None = None) -> SmtpStatus:
    """What is missing or contradictory in the MAIL_* settings. configured = nothing blocks sending."""
    s = s or get_settings()
    problems: list[str] = []
    if not s.mail_server:
        problems.append("MAIL_SERVER is not set")
    port = _port(s)
    if s.mail_port is None:
        problems.append("MAIL_PORT is not set")
    elif port is None:
        problems.append("MAIL_PORT must be a number between 1 and 65535")
    if s.mail_use_ssl and s.mail_use_tls:
        problems.append("MAIL_USE_SSL and MAIL_USE_TLS cannot both be true – use SSL (port 465) or TLS/STARTTLS (port 587)")
    if bool(s.mail_username) != bool(s.mail_password and s.mail_password.get_secret_value()):
        problems.append("MAIL_USERNAME and MAIL_PASSWORD must be set together")
    if not s.mail_default_sender:
        problems.append("MAIL_DEFAULT_SENDER is not set")
    elif not valid_address(parseaddr(s.mail_default_sender)[1]):
        problems.append("MAIL_DEFAULT_SENDER is not a valid e-mail address")
    security = "SSL" if s.mail_use_ssl else "STARTTLS" if s.mail_use_tls else "none"
    return SmtpStatus(not problems, problems, s.mail_server, port, security, bool(s.mail_username), s.mail_default_sender)


def build_message(to: list[str] | str, subject: str, text: str, html: str | None = None, s: Settings | None = None) -> EmailMessage:
    s = s or get_settings()
    name, addr = parseaddr(s.mail_default_sender or "")
    msg = EmailMessage()
    msg["From"] = formataddr((name, addr)) if name else addr
    msg["To"] = ", ".join(to) if isinstance(to, list) else to
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")
    msg["Message-ID"] = make_msgid(domain=addr.split("@")[-1] if "@" in addr else None)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


class SmtpSession:
    """One SMTP connection for several messages (a scheduled run): `with SmtpSession() as smtp: smtp.send(msg)`."""

    def __init__(self, s: Settings | None = None):
        self.s = s or get_settings()
        self.conn: smtplib.SMTP | None = None

    def __enter__(self) -> "SmtpSession":
        st = smtp_status(self.s)
        if not st.configured:
            raise MailError("SMTP is not configured: " + "; ".join(st.problems))
        ctx = ssl.create_default_context()
        try:
            if self.s.mail_use_ssl:
                self.conn = smtplib.SMTP_SSL(st.server, st.port, timeout=self.s.mail_timeout_seconds, context=ctx)
            else:
                self.conn = smtplib.SMTP(st.server, st.port, timeout=self.s.mail_timeout_seconds)
                if self.s.mail_use_tls:
                    self.conn.starttls(context=ctx)
            if self.s.mail_username and self.s.mail_password:
                self.conn.login(self.s.mail_username, self.s.mail_password.get_secret_value())
        except smtplib.SMTPAuthenticationError:
            self._close()
            raise MailError("The mail server rejected MAIL_USERNAME / MAIL_PASSWORD") from None
        except (smtplib.SMTPException, OSError, socket.timeout, ssl.SSLError) as exc:
            self._close()
            raise MailError(f"Could not connect to the mail server {st.server}:{st.port} ({type(exc).__name__})") from None
        return self

    def send(self, msg: EmailMessage) -> None:
        assert self.conn is not None
        try:
            refused = self.conn.send_message(msg)
        except smtplib.SMTPRecipientsRefused:
            raise MailError("The mail server refused the recipient address") from None
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Sending failed ({type(exc).__name__})") from None
        if refused:
            raise MailError("The mail server refused the recipient address")

    def _close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:  # noqa: BLE001 - closing a broken connection
                pass
            self.conn = None

    def __exit__(self, *exc: object) -> None:
        self._close()


def send_test_mail(to: str, requested_by: str, user_id: int | None = None) -> None:
    """A short plain message proving the SMTP settings work. No report data is generated."""
    msg = build_message(
        to,
        "Test mail – Pratap Network Analytics",
        f"This is a test message from Pratap Network Analytics.\n\nRequested by {requested_by}. "
        "If you received it, the SMTP settings work.\n\nNo reply is needed.",
    )
    with SmtpSession() as smtp:
        smtp.send(msg)
    log.info("Test mail sent (requested by user id %s)", user_id)
