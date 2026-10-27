"""Mail Configuration: SMTP settings, schedules, audiences (Escalation Matrix AM / SME / COH / CBH and dashboard users),
filters, report figures, templates, scheduler and the admin API.

SMTP is always the in-memory FakeSMTP below; conftest additionally makes any real SMTP connection fail the test.
The Escalation Matrix used here is synthetic (real GP codes of the test data, made-up people and addresses).
"""

from __future__ import annotations

import datetime as dt
import json
import smtplib
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.mail import schedule as sch
from app.mail import service
from app.mail import template as tpl
from app.mail.audience import Assignment, matrix_people, recipients, user_gps
from app.mail.report import ReportContext
from app.mail.smtp import MailError, SmtpSession, build_message, smtp_status
from app.models import EscalationContact, EscalationImport, MailConfig, MailRun, MailTemplate, User, UserScope
from app.security.core import hash_password

from .conftest import VIEWER, login

IST = ZoneInfo("Asia/Kolkata")
UTC = dt.UTC


# ---------------------------------------------------------------- fakes and fixtures


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    refuse: set[str] = set()
    fail_connect = False

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSMTP.fail_connect:
            raise ConnectionRefusedError("refused")
        self.host, self.port, self.ssl, self.tls, self.user = host, port, False, False, None
        self.sent: list = []
        FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if password == "wrong-pw":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 authentication failed")
        self.user = user

    def send_message(self, msg):
        if any(a.strip() in FakeSMTP.refuse for a in msg["To"].split(",")):
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
        self.sent.append(msg)
        return {}

    def quit(self):
        pass


class FakeSMTPSSL(FakeSMTP):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ssl = True


def all_sent() -> list:
    return [m for s in FakeSMTP.instances for m in s.sent]


def sent_to() -> dict:
    return {m["To"]: m for m in all_sent()}


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.refuse, FakeSMTP.fail_connect = [], set(), False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    s = get_settings()
    for k, v in {
        "mail_server": "smtp.example.in",
        "mail_port": "587",
        "mail_use_tls": True,
        "mail_use_ssl": False,
        "mail_username": "sender@example.in",
        "mail_password": SecretStr("pw-secret-123"),
        "mail_default_sender": "Reports <noreply@example.in>",
    }.items():
        monkeypatch.setattr(s, k, v)
    return FakeSMTP


@pytest.fixture
def reports_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "amc_report_emails_enabled", True)


@pytest.fixture
def clean_mail():
    with SessionLocal() as db:
        db.execute(delete(MailRun))
        db.execute(delete(MailConfig))
        db.commit()
    yield


class M:
    """The synthetic Escalation Matrix: who owns which GPs."""

    c1 = c2 = block_a = block_b = block_v = ""
    gps_a: list[str] = []
    gps_b: list[str] = []
    gps_v: list[str] = []
    gps_c1: list[str] = []
    gps_c2: list[str] = []


@pytest.fixture(scope="module")
def matrix(imported):
    """c1: AM Alpha (block A, BA "Ba One"), AM Beta (block B, BA "Ba Two"), Vacant-1 (another block), SME Sigma
    (whole c1), COH Omega without e-mail. c2: AM Gamma, SME Sigma2 who shares Alpha's address (dedupe test)."""
    from app.analytics.escalation import invalidate_escalation

    g = imported.gps
    circles = sorted(g["circle_id"].unique())
    M.c1, M.c2 = circles[0], circles[-1]
    b1 = list(dict.fromkeys(g.loc[g["circle_id"] == M.c1, "block_id"]))
    M.block_a, M.block_b, M.block_v = b1[0], b1[1], b1[2]
    M.gps_a = list(g.index[g["block_id"] == M.block_a])
    M.gps_b = list(g.index[g["block_id"] == M.block_b])
    M.gps_v = list(g.index[g["block_id"] == M.block_v])
    M.gps_c1 = M.gps_a + M.gps_b + M.gps_v
    M.gps_c2 = list(g.index[g["circle_id"] == M.c2])
    rows = []

    def row(gp, circle, am, am_email, ba, sme, sme_email, coh=None, coh_email=None):
        # every GP also has a CBH with an e-mail: stored as a backup, must never be mailed
        return {"gp_code": gp, "circle": circle, "am_name": am, "am_email": am_email, "ba": ba, "shq_name": sme, "shq_email": sme_email, "coh_name": coh, "coh_email": coh_email, "cbh_name": "Kappa", "cbh_email": "kappa@cbh.in", "fe_name": "FE", "frt_code": "F1"}

    n1 = str(g.loc[M.gps_a[0], "circle"])
    n2 = str(g.loc[M.gps_c2[0], "circle"])
    rows += [row(x, n1, "Alpha", "alpha@am.in", "Ba One", "Sigma", "sigma@sme.in", "Omega", None) for x in M.gps_a]
    rows += [row(x, n1, "Beta", "BETA@am.in", "Ba Two", "Sigma", "sigma@sme.in", "Omega", None) for x in M.gps_b]
    rows += [row(x, n1, "Vacent-1", None, "Ba One", "Sigma", "sigma@sme.in", "Omega", None) for x in M.gps_v]
    rows += [row(x, n2, "Gamma", "gamma@am.in", "Ba Three", "Sigma2", "alpha@am.in") for x in M.gps_c2]
    with SessionLocal() as db:
        db.execute(update(EscalationImport).values(is_active=False))
        imp = EscalationImport(file_name="synthetic.xlsx", stored_path="-", sha256="0" * 64, status="SUCCESS", is_active=True, rows_total=len(rows))
        db.add(imp)
        db.flush()
        db.add_all(EscalationContact(import_id=imp.id, **r) for r in rows)
        db.commit()
        imp_id = imp.id
    invalidate_escalation()
    yield M
    with SessionLocal() as db:
        db.execute(delete(EscalationContact).where(EscalationContact.import_id == imp_id))
        db.execute(delete(EscalationImport).where(EscalationImport.id == imp_id))
        db.commit()
    invalidate_escalation()


_n = [0]


def make_user(role="viewer", scopes=(), active=True, email=None, name=None) -> int:
    _n[0] += 1
    with SessionLocal() as db:
        u = User(email=email or f"u{_n[0]}-{role}@mailtest.in", name=name or f"User {_n[0]}", role=role, password_hash=hash_password("Xx1!long-enough-pw"), is_active=active)
        db.add(u)
        db.flush()
        db.add_all(UserScope(user_id=u.id, level=lv, scope_id=i) for lv, i in scopes)
        db.commit()
        return u.id


def cfg(**kw) -> MailConfig:
    base = {"audiences": ["am"], "filter_circles": [], "filter_bas": [], "filter_blocks": [], "filter_people": [], "user_ids": []}
    base.update(kw)
    return MailConfig(**{k: json.dumps(v) for k, v in base.items()})


def csrf(client) -> dict:
    return {"x-csrf-token": client.cookies.get("pratap_csrf")}


# ---------------------------------------------------------------- schedule calculation


def _next(s: sch.Schedule, after_ist: dt.datetime) -> dt.datetime:
    return sch.next_run(s, after_ist.replace(tzinfo=IST), "Asia/Kolkata").astimezone(IST).replace(tzinfo=None)


def test_daily_today_if_time_not_passed_else_tomorrow():
    s = sch.Schedule("daily", dt.date(2026, 1, 1), "09:30")
    assert _next(s, dt.datetime(2026, 10, 26, 8, 0)) == dt.datetime(2026, 10, 26, 9, 30)
    assert _next(s, dt.datetime(2026, 10, 26, 9, 30)) == dt.datetime(2026, 10, 27, 9, 30)  # strictly after


def test_send_time_is_in_the_configured_timezone():
    s = sch.Schedule("daily", dt.date(2026, 1, 1), "09:30")
    assert sch.next_run(s, dt.datetime(2026, 10, 26, 0, 0, tzinfo=UTC), "Asia/Kolkata") == dt.datetime(2026, 10, 26, 4, 0, tzinfo=UTC)
    with pytest.raises(sch.ScheduleError):
        sch.next_run(s, dt.datetime(2026, 10, 26, tzinfo=UTC), "Mars/Base")
    with pytest.raises(ValueError):
        sch.next_run(s, dt.datetime(2026, 10, 26), "Asia/Kolkata")


def test_future_start_date_weekly_and_monthly():
    assert _next(sch.Schedule("daily", dt.date(2026, 11, 5), "07:00"), dt.datetime(2026, 10, 26, 12)) == dt.datetime(2026, 11, 5, 7, 0)
    fri = sch.Schedule("weekly", dt.date(2026, 1, 1), "18:00", weekday=4)
    assert _next(fri, dt.datetime(2026, 10, 26, 10)) == dt.datetime(2026, 10, 30, 18, 0)
    assert _next(fri, dt.datetime(2026, 10, 30, 18)) == dt.datetime(2026, 11, 6, 18, 0)
    m31 = sch.Schedule("monthly", dt.date(2026, 1, 1), "10:00", month_day=31)
    assert _next(m31, dt.datetime(2026, 2, 1)) == dt.datetime(2026, 2, 28, 10, 0)
    assert _next(m31, dt.datetime(2026, 4, 1)) == dt.datetime(2026, 4, 30, 10, 0)
    assert _next(sch.Schedule("monthly", dt.date(2028, 1, 1), "10:00", month_day=30), dt.datetime(2028, 2, 1)) == dt.datetime(2028, 2, 29, 10, 0)


@pytest.mark.parametrize(
    "bad",
    [
        sch.Schedule("hourly", dt.date(2026, 1, 1), "09:00"),
        sch.Schedule("daily", dt.date(2026, 1, 1), "25:00"),
        sch.Schedule("daily", dt.date(2026, 1, 1), "9:00"),
        sch.Schedule("weekly", dt.date(2026, 1, 1), "09:00"),
        sch.Schedule("weekly", dt.date(2026, 1, 1), "09:00", weekday=7),
        sch.Schedule("monthly", dt.date(2026, 1, 1), "09:00", month_day=32),
        sch.Schedule("daily", dt.date(1999, 1, 1), "09:00"),
    ],
)
def test_invalid_schedules_are_rejected(bad):
    with pytest.raises(sch.ScheduleError):
        sch.validate(bad)


# ---------------------------------------------------------------- SMTP settings


def _settings(**kw) -> Settings:
    return Settings(secret_key="k" * 8 + "abcdefghijklmnopqrstuvwxyz0123456789", _env_file=None, **kw)


def test_smtp_settings_load_from_env_strings(monkeypatch):
    for k, v in {"MAIL_SERVER": "mail.example.in", "MAIL_PORT": "587", "MAIL_USE_SSL": "False", "MAIL_USE_TLS": "True", "MAIL_USERNAME": "a@example.in", "MAIL_PASSWORD": "p&ss", "MAIL_DEFAULT_SENDER": "b@example.in", "SMTP_APPROVAL_EMAILS_ENABLED": "True"}.items():
        monkeypatch.setenv(k, v)
    s = _settings()
    st = smtp_status(s)
    assert st.configured and st.port == 587 and st.security == "STARTTLS"
    assert s.mail_use_ssl is False and s.mail_use_tls is True and s.smtp_approval_emails_enabled is True
    assert s.amc_report_emails_enabled is False
    assert "p&ss" not in repr(s)


@pytest.mark.parametrize(
    ("kw", "problem"),
    [
        ({}, "MAIL_SERVER is not set"),
        ({"mail_server": "m", "mail_port": "abc", "mail_default_sender": "a@b.in"}, "MAIL_PORT must be a number"),
        ({"mail_server": "m", "mail_port": "465", "mail_use_ssl": True, "mail_use_tls": True, "mail_default_sender": "a@b.in"}, "cannot both be true"),
        ({"mail_server": "m", "mail_port": "587", "mail_username": "u@b.in", "mail_default_sender": "a@b.in"}, "must be set together"),
        ({"mail_server": "m", "mail_port": "587", "mail_default_sender": "not-an-address"}, "not a valid e-mail"),
    ],
)
def test_invalid_smtp_settings_are_reported_not_fatal(kw, problem):
    st = smtp_status(_settings(**kw))
    assert not st.configured and any(problem in p for p in st.problems)


def test_starttls_ssl_and_safe_errors(smtp, monkeypatch):
    with SmtpSession() as s:
        s.send(build_message("x@test.in", "S", "T"))
    assert smtp.instances[-1].tls and smtp.instances[-1].user == "sender@example.in"
    monkeypatch.setattr(get_settings(), "mail_use_tls", False)
    monkeypatch.setattr(get_settings(), "mail_use_ssl", True)
    with SmtpSession():
        pass
    assert smtp.instances[-1].ssl
    monkeypatch.setattr(get_settings(), "mail_password", SecretStr("wrong-pw"))
    with pytest.raises(MailError) as e:
        with SmtpSession():
            pass
    assert "wrong-pw" not in str(e.value)
    smtp.fail_connect = True
    with pytest.raises(MailError, match="Could not connect"):
        with SmtpSession():
            pass
    with pytest.raises(MailError, match="not configured"):
        with SmtpSession(_settings()):
            pass


# ---------------------------------------------------------------- audiences (Escalation Matrix)


def test_matrix_people_one_per_name_and_circle(imported, matrix):
    people = {p.id: p for p in matrix_people(imported)}
    alpha = people[f"am:{M.c1}:alpha"]
    assert set(alpha.gps) == set(M.gps_a) and alpha.emails == ["alpha@am.in"] and alpha.business_areas == ["Ba One"]
    assert people[f"am:{M.c1}:beta"].emails == ["beta@am.in"]  # addresses are normalised
    assert not any("vacent" in pid for pid in people)  # vacant posts are not people
    sigma = people[f"sme:{M.c1}:sigma"]
    assert set(sigma.gps) == set(M.gps_c1)
    assert people[f"coh:{M.c1}:omega"].emails == []


def test_each_area_manager_gets_only_their_own_gps(imported, matrix):
    with SessionLocal() as db:
        people, skipped = recipients(db, imported, cfg(audiences=["am"]))
    by = {p.name: p for p in people}
    assert set(by["Alpha"].gps) == set(M.gps_a) and set(by["Beta"].gps) == set(M.gps_b)
    assert not set(by["Alpha"].gps) & set(by["Beta"].gps)
    assert by["Alpha"].breakdown == "block"
    assert all(s.reason for s in skipped) and not any(s.name == "Alpha" for s in skipped)


def test_sme_coh_get_their_circle_and_missing_email_is_skipped(imported, matrix):
    with SessionLocal() as db:
        people, skipped = recipients(db, imported, cfg(audiences=["sme", "coh"]))
    sigma = next(p for p in people if p.name == "Sigma")
    assert set(sigma.gps) == set(M.gps_c1) and sigma.breakdown == "am"
    assert any(s.name == "Omega" and "no e-mail" in s.reason for s in skipped)


def test_filters_state_business_area_block_and_people(imported, matrix):
    with SessionLocal() as db:
        by_ba = recipients(db, imported, cfg(audiences=["am", "sme"], filter_bas=["ba two"]))[0]
        by_block = recipients(db, imported, cfg(audiences=["am"], filter_blocks=[M.block_a]))[0]
        by_state = recipients(db, imported, cfg(audiences=["am"], filter_circles=[M.c2]))[0]
        one = recipients(db, imported, cfg(audiences=["am"], filter_people=[f"am:{M.c1}:beta"]))[0]
    assert {p.name for p in by_ba} == {"Beta", "Sigma"}
    assert next(p for p in by_ba if p.name == "Sigma").gps.equals(next(p for p in by_ba if p.name == "Beta").gps)  # SME sees only the BA
    assert [p.name for p in by_block] == ["Alpha"] and set(by_block[0].gps) == set(M.gps_a)
    assert [p.name for p in by_state] == ["Gamma"]
    assert [p.name for p in one] == ["Beta"]


def test_same_address_in_two_roles_gets_one_merged_email(imported, matrix):
    with SessionLocal() as db:
        people, _ = recipients(db, imported, cfg(audiences=["am", "sme"]))
    alpha = [p for p in people if p.email == "alpha@am.in"]
    assert len(alpha) == 1
    assert set(alpha[0].roles) == {"am", "sme"} and set(alpha[0].gps) == set(M.gps_a) | set(M.gps_c2)
    assert alpha[0].breakdown == "am"


# ---------------------------------------------------------------- audiences (dashboard users / RBAC)


def test_user_areas_union_and_never_widened(imported, matrix):
    g = imported.gps
    district = g.loc[g["circle_id"] == M.c1, "district_id"].iloc[0]
    assert user_gps(imported, "admin", [])[0].equals(g.index)
    gps, _ = user_gps(imported, "viewer", [Assignment("district", district), Assignment("block", M.block_a)])
    assert set(gps) == set(g.index[(g["district_id"] == district) | (g["block_id"] == M.block_a)])
    assert user_gps(imported, "viewer", [])[0].empty
    assert user_gps(imported, "viewer", [Assignment("circle", "atlantis")])[0].empty
    assert user_gps(imported, "auditor", [Assignment("circle", M.c1)])[0].empty


def test_dashboard_user_recipients(imported, matrix):
    ok = make_user(scopes=[("block", M.block_a)], email="ok@users.in")
    none = make_user(email="none@users.in")
    off = make_user(scopes=[("circle", M.c1)], active=False, email="off@users.in")
    bad = make_user(scopes=[("circle", M.c1)], email="broken-address")
    with SessionLocal() as db:
        people, skipped = recipients(db, imported, cfg(audiences=["users"], user_ids=[ok, none, off, bad]))
    assert [p.email for p in people] == ["ok@users.in"] and set(people[0].gps) == set(M.gps_a)
    reasons = {s.name: s.reason for s in skipped}
    assert any("no circle" in r for r in reasons.values()) and any("no valid e-mail" in r for r in reasons.values())
    assert len(skipped) == 2  # the inactive user is not even considered


# ---------------------------------------------------------------- report figures and templates


def test_report_counts_only_the_recipients_gps(imported, matrix):
    ctx = ReportContext(imported)
    a, b = ctx.figures(pd_index(M.gps_a)), ctx.figures(pd_index(M.gps_b))
    both = ctx.figures(pd_index(M.gps_a + M.gps_b))
    for k in ("monthTarget", "mtdTarget", "mtdAchieved", "overdue", "weekTarget", "weekAchieved"):
        assert a["total"][k] + b["total"][k] == both["total"][k]
    assert a["gps"] == len(M.gps_a)
    assert {r["name"] for r in a["am"]} <= {"Alpha"}
    full = ctx.figures(imported.gps.index)
    assert full["total"]["monthTarget"] == int(ctx.plan["monthTarget"].sum())


def pd_index(codes):
    import pandas as pd

    return pd.Index(codes)


def test_default_templates_are_valid_and_render_every_placeholder(imported, matrix):
    ctx = ReportContext(imported)
    with SessionLocal() as db:
        alpha = next(p for p in recipients(db, imported, cfg(audiences=["am"]))[0] if p.name == "Alpha")
    for t in tpl.DEFAULT_TEMPLATES:
        tpl.validate(t["subject"], t["body"])
        r = service.compose(ctx, t["subject"], t["body"], alpha)
        assert "{{" not in r.subject + r.text + r.html and "Alpha" in r.text
    every = "\n".join(f"{{{{{p}}}}}" for p in tpl.ALL_PLACEHOLDERS)
    r = service.compose(ctx, "S {{area}}", every, alpha)
    assert "{{" not in r.html and "<table" in r.html


def test_template_validation_and_escaping(imported, matrix):
    with pytest.raises(tpl.TemplateError, match="Unknown placeholder"):
        tpl.validate("Hi", "Hello {{recipient_nmae}}")
    with pytest.raises(tpl.TemplateError, match="subject"):
        tpl.validate("{{summary_table}}", "x")
    with pytest.raises(tpl.TemplateError, match="own"):
        tpl.validate("s", "See {{block_table}} below")
    with SessionLocal() as db:
        alpha = next(p for p in recipients(db, imported, cfg(audiences=["am"]))[0] if p.name == "Alpha")
    r = service.compose(ReportContext(imported), "s", "<script>alert(1)</script> {{recipient_name}}", alpha)
    assert "<script>" not in r.html and "&lt;script&gt;" in r.html


# ---------------------------------------------------------------- scheduler


def _due(db, when: dt.datetime, **kw) -> int:
    c = cfg(**kw)
    c.name, c.frequency, c.start_date, c.send_time, c.enabled, c.next_run_at = "t", "daily", dt.date(2026, 1, 1), "09:30", True, when
    db.add(c)
    db.commit()
    return c.id


SLOT = dt.datetime(2026, 10, 26, 4, 0, tzinfo=UTC)


def test_scheduler_sends_each_person_their_own_email_once(imported, matrix, smtp, reports_on, clean_mail):
    with SessionLocal() as db:
        cid = _due(db, SLOT, audiences=["am"], filter_circles=[M.c1])
    runs = service.run_due(now=SLOT + dt.timedelta(minutes=1))
    got = sent_to()
    assert set(got) == {"alpha@am.in", "beta@am.in"}  # Vacent-1 has no address
    beta_text = got["beta@am.in"].get_body(("plain",)).get_content()
    assert "Dear Beta" in beta_text and "Alpha" not in beta_text
    with SessionLocal() as db:
        run = db.get(MailRun, runs[0])
        assert run.status == "SUCCESS" and run.sent == 2 and run.skipped >= 1
        assert service.utc(db.get(MailConfig, cid).next_run_at) > SLOT + dt.timedelta(minutes=1)
    assert service.run_due(now=SLOT + dt.timedelta(minutes=2)) == [] and len(all_sent()) == 2  # no second send


def test_two_processes_cannot_claim_the_same_slot(imported, matrix, reports_on, clean_mail):
    with SessionLocal() as db:
        cid = _due(db, SLOT)
    with SessionLocal() as one, SessionLocal() as two:
        assert service.claim(one, cid, SLOT + dt.timedelta(minutes=1)) is not None
        assert service.claim(two, cid, SLOT + dt.timedelta(minutes=1)) is None
    with SessionLocal() as db:
        assert len(list(db.scalars(select(MailRun).where(MailRun.config_id == cid)))) == 1


def test_missed_slot_is_skipped_recent_one_is_sent(imported, matrix, smtp, reports_on, clean_mail):
    with SessionLocal() as db:
        _due(db, SLOT - dt.timedelta(days=3), audiences=["am"], filter_people=[f"am:{M.c1}:alpha"])
    runs = service.run_due(now=SLOT)
    with SessionLocal() as db:
        assert db.get(MailRun, runs[0]).status == "SKIPPED"
    assert all_sent() == []
    with SessionLocal() as db:
        db.execute(delete(MailRun))
        db.execute(delete(MailConfig))
        db.commit()
        _due(db, SLOT, audiences=["am"], filter_people=[f"am:{M.c1}:alpha"])
    service.run_due(now=SLOT + dt.timedelta(hours=2))
    assert list(sent_to()) == ["alpha@am.in"]


def test_smtp_failures_are_recorded_safely(imported, matrix, smtp, reports_on, clean_mail, monkeypatch):
    smtp.refuse = {"beta@am.in"}
    with SessionLocal() as db:
        _due(db, SLOT, audiences=["am"], filter_circles=[M.c1])
    run_id = service.run_due(now=SLOT + dt.timedelta(minutes=1))[0]
    with SessionLocal() as db:
        run = db.get(MailRun, run_id)
    assert run.status == "PARTIAL" and run.sent == 1 and run.failed == 1 and "beta@am.in" not in (run.message or "")
    with SessionLocal() as db:
        db.execute(delete(MailRun))
        db.execute(delete(MailConfig))
        db.commit()
        _due(db, SLOT, audiences=["am"], filter_circles=[M.c1])
    monkeypatch.setattr(get_settings(), "mail_password", SecretStr("wrong-pw"))
    run_id = service.run_due(now=SLOT + dt.timedelta(minutes=1))[0]
    with SessionLocal() as db:
        run = db.get(MailRun, run_id)
    assert run.status == "FAILED" and "wrong-pw" not in (run.message or "")


def test_switch_off_or_disabled_schedule_sends_nothing(imported, matrix, smtp, clean_mail, monkeypatch):
    with SessionLocal() as db:
        _due(db, SLOT, audiences=["am"])
        c = db.get(MailConfig, _due(db, SLOT, audiences=["sme"]))
        c.enabled = False
        db.commit()
    assert service.run_due(now=SLOT + dt.timedelta(minutes=1)) == []  # AMC_REPORT_EMAILS_ENABLED=false
    monkeypatch.setattr(get_settings(), "amc_report_emails_enabled", True)
    assert len(service.run_due(now=SLOT + dt.timedelta(minutes=1))) == 1  # only the enabled one
    assert all("sigma" not in m["To"] for m in all_sent())


def test_startup_does_not_start_the_scheduler_or_send(client, smtp):
    assert service.start_scheduler() is False and not service.scheduler_running()
    login(client)
    assert smtp.instances == []


# ---------------------------------------------------------------- API


def test_mail_api_is_admin_only(client):
    assert client.get("/api/v1/mail/configs").status_code == 401
    login(client, VIEWER)
    for path in ("/api/v1/mail/configs", "/api/v1/mail/templates", "/api/v1/mail/options", "/api/v1/mail/status", "/api/v1/users"):
        assert client.get(path).status_code == 403
    assert client.post("/api/v1/mail/test", json={"to": "a@b.in"}, headers=csrf(client)).status_code == 403


def test_test_mail_success_failure_and_rate_limit(client, smtp, monkeypatch):
    from app.api import mail as mail_api
    from app.mail import report

    monkeypatch.setattr(report.ReportContext, "__init__", lambda *a, **k: pytest.fail("the test mail must not build a report"))
    mail_api._test_hits.clear()
    login(client)
    r = client.post("/api/v1/mail/test", json={"to": "check@test.in"}, headers=csrf(client))
    assert r.json()["ok"] is True and sent_to()["check@test.in"]["Subject"].startswith("Test mail")
    smtp.refuse = {"bounce@test.in"}
    r = client.post("/api/v1/mail/test", json={"to": "bounce@test.in"}, headers=csrf(client))
    assert r.json()["ok"] is False and "refused" in r.json()["message"]
    assert client.post("/api/v1/mail/test", json={"to": "nope"}, headers=csrf(client)).status_code == 422
    codes = [client.post("/api/v1/mail/test", json={"to": "x@test.in"}, headers=csrf(client)).status_code for _ in range(mail_api.TEST_LIMIT)]
    assert codes[-1] == 429
    assert "pw-secret-123" not in client.get("/api/v1/mail/status").text
    mail_api._test_hits.clear()


def test_templates_crud_reset_and_preview_never_send(client, imported, matrix, smtp, clean_mail):
    login(client)
    ts = client.get("/api/v1/mail/templates").json()
    assert {t["key"] for t in ts if t["builtIn"]} == {"detailed", "summary", "action"}
    detailed = next(t for t in ts if t["key"] == "detailed")
    r = client.patch(f"/api/v1/mail/templates/{detailed['id']}", json={**detailed, "subject": "Changed {{area}}"}, headers=csrf(client))
    assert r.status_code == 200 and r.json()["subject"] == "Changed {{area}}"
    assert client.post(f"/api/v1/mail/templates/{detailed['id']}/reset", headers=csrf(client)).json()["subject"] == tpl.DEFAULT_TEMPLATES[0]["subject"]
    assert client.post(f"/api/v1/mail/templates/{detailed['id']}/delete", headers=csrf(client)).status_code == 400
    bad = client.post("/api/v1/mail/templates", json={"name": "Bad", "subject": "x", "body": "{{nope}}"}, headers=csrf(client))
    assert bad.status_code == 422 and "nope" in bad.json()["detail"]
    mine = client.post("/api/v1/mail/templates", json={"name": "Mine", "subject": "Hi {{recipient_name}}", "body": "Hello {{recipient_name}}\n{{summary_table}}\n{{block_table}}"}, headers=csrf(client)).json()
    pv = client.post("/api/v1/mail/templates/preview", json={"subject": mine["subject"], "body": mine["body"], "personId": f"am:{M.c1}:beta"}, headers=csrf(client)).json()
    assert pv["recipient"]["name"] == "Beta" and pv["subject"] == "Hi Beta" and "<table" in pv["html"]
    assert client.post(f"/api/v1/mail/templates/{mine['id']}/delete", headers=csrf(client)).json() == {"deleted": mine["id"]}
    assert smtp.instances == []


def test_schedule_api_create_edit_enable_preview_delete_never_sends(client, imported, matrix, smtp, clean_mail):
    login(client)
    opts = client.get("/api/v1/mail/options").json()
    assert opts["hasMatrix"] and any(p["id"] == f"am:{M.c1}:alpha" for p in opts["people"])
    body = {"name": "AM daily", "audiences": ["am"], "filterCircles": [M.c1], "frequency": "daily", "startDate": "2026-01-01", "sendTime": "09:00", "enabled": False}
    c = client.post("/api/v1/mail/configs", json=body, headers=csrf(client)).json()
    assert c["enabled"] is False and c["nextRunAt"] is None and c["templateName"].startswith("Detailed")
    r = client.post(f"/api/v1/mail/configs/{c['id']}/enabled", json={"enabled": True}, headers=csrf(client)).json()
    assert dt.datetime.fromisoformat(r["nextRunAt"]) > dt.datetime.now(UTC)
    r = client.patch(f"/api/v1/mail/configs/{c['id']}", json={**body, "frequency": "weekly", "weekday": 0, "enabled": True}, headers=csrf(client)).json()
    assert r["summary"] == "Every Monday at 09:00" and dt.datetime.fromisoformat(r["nextRunAt"]).astimezone(IST).weekday() == 0
    pv = client.get(f"/api/v1/mail/configs/{c['id']}/recipients").json()
    assert {x["name"] for x in pv["recipients"]} == {"Alpha", "Beta"} and any(s["name"].startswith("Vacent-1") and "vacant post" in s["reason"] for s in pv["skipped"])
    assert client.post(f"/api/v1/mail/configs/{c['id']}/delete", headers=csrf(client)).json() == {"deleted": c["id"]}
    assert smtp.instances == []


@pytest.mark.parametrize(
    "over",
    [
        {"audiences": []},
        {"audiences": ["fe"]},
        {"audiences": ["cbh"]},
        {"frequency": "weekly"},
        {"frequency": "monthly", "monthDay": 32},
        {"sendTime": "24:10"},
        {"filterCircles": ["atlantis"]},
        {"filterBlocks": ["zz-0"]},
        {"filterPeople": ["am:atlantis:nobody"]},
        {"templateId": 987654},
        {"audiences": ["users"], "userIds": [987654]},
    ],
)
def test_invalid_schedules_are_refused(client, imported, matrix, clean_mail, over):
    login(client)
    body = {"name": "x" * 3, "audiences": ["am"], "frequency": "daily", "startDate": "2026-01-01", "sendTime": "09:00"}
    body.update(over)
    assert client.post("/api/v1/mail/configs", json=body, headers=csrf(client)).status_code == 422


def test_user_management_with_areas(client, imported):
    g = imported.gps
    circle, block = g["circle_id"].iloc[0], g["block_id"].iloc[-1]
    login(client)
    r = client.post("/api/v1/users", json={"email": "Area.User@Mailtest.in", "name": "Area User", "password": "Ar3a!User-Pass", "scopes": [{"level": "circle", "id": circle}, {"level": "block", "id": block}]}, headers=csrf(client))
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["email"] == "area.user@mailtest.in" and {s["id"] for s in u["scopes"]} == {circle, block} and all(s["valid"] for s in u["scopes"])
    assert client.post("/api/v1/users", json={"email": "AREA.user@mailtest.in", "name": "Dup", "password": "Ar3a!User-Pass"}, headers=csrf(client)).status_code == 409
    assert client.post("/api/v1/users", json={"email": "n1@mailtest.in", "name": "N1", "password": "Ar3a!User-Pass", "scopes": [{"level": "block", "id": "zz-0"}]}, headers=csrf(client)).status_code == 422
    r = client.patch(f"/api/v1/users/{u['id']}", json={"name": "Renamed", "scopes": [{"level": "block", "id": block}]}, headers=csrf(client)).json()
    assert r["name"] == "Renamed" and [s["id"] for s in r["scopes"]] == [block]
    assert client.patch(f"/api/v1/users/{u['id']}", json={"role": "admin"}, headers=csrf(client)).json()["scopes"] == []
    assert client.patch(f"/api/v1/users/{u['id']}", json={"isActive": False}, headers=csrf(client)).json()["isActive"] is False
    me = client.get("/api/v1/auth/me").json()["user"]
    assert client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}, headers=csrf(client)).status_code == 400
    assert client.get("/api/v1/users/locations").json()["hasData"]


def test_cbh_is_stored_as_backup_but_never_mailed(imported, matrix, smtp, reports_on, clean_mail):
    from app.analytics.escalation import _active

    _, esc = _active()
    assert (esc["cbh_email"] == "kappa@cbh.in").all()  # stored
    assert not any(p.role == "cbh" for p in matrix_people(imported))
    with SessionLocal() as db:
        people, _ = recipients(db, imported, cfg(audiences=["am", "sme", "coh", "cbh"]))  # an old / forged "cbh" is ignored
        _due(db, SLOT, audiences=["am", "sme", "coh", "cbh"])
    assert all("kappa@cbh.in" not in p.emails for p in people)
    service.run_due(now=SLOT + dt.timedelta(minutes=1))
    assert all_sent() and all("kappa@cbh.in" not in m["To"] for m in all_sent())


def test_escalation_matrix_email_columns_are_parsed(tmp_path):
    from app.ingestion.escalation import email

    assert email("Sisir.Choudhury@telecrats.com") == "sisir.choudhury@telecrats.com"
    assert email("a@x.in / B@y.in") == "a@x.in / b@y.in" and email("0") is None and email("n/a") is None


def test_default_templates_are_seeded_once():
    with SessionLocal() as db:
        service.ensure_default_templates(db)
        service.ensure_default_templates(db)
        keys = list(db.scalars(select(MailTemplate.key).where(MailTemplate.key.is_not(None))))
    assert sorted(keys) == ["action", "detailed", "summary"]
