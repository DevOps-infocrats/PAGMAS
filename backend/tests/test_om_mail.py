"""O&M Daily Dashboard e-mail (app.mail.om_data / om_html / om_service and /api/v1/mail/om/*).

* one circle's e-mail holds ONLY that circle's figures, the same numbers as the Circle Overview, "done / scope",
  HoTo RKM, One-Time Up & AMC targets (month / week target, ready, achieved) above the uptime trend, GPs < 90% inside
  the penalty blocks, "WTD W-nn" while the week runs; e-mail safe and escaped; the All Circles page (preview only);
* schedule: days x times inside the permitted window, the next run always in the future;
* recipients: To + enabled Area Managers (when included), CC + central CC, de-duplicated;
* sending: test mail to the admin only, "Send now", the scheduler (one e-mail per slot, never twice), a delivery
  stopped while sending is never re-sent, an SMTP failure is logged; admins only.
SMTP is the in-memory FakeSMTP of tests/test_mail.py – nothing reaches a real mail server.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.mail import om_service as om
from app.mail.om_data import Context, circle_view, week_label
from app.mail.om_html import render, render_all
from app.models import OmMailCircle, OmMailDelivery, OmMailRun, OmMailSetting

from .conftest import VIEWER, login
from .test_mail import FakeSMTP, all_sent, smtp  # noqa: F401 - shared fake SMTP fixture

ADMIN_EMAIL = "admin@pratap-test.in"


@pytest.fixture
def active(imported):
    """The imported dataset is the active one while a test of this file runs (other test files switch datasets);
    the previous active dataset is restored afterwards."""
    from sqlalchemy import update

    from app.analytics.store import invalidate_cache
    from app.models import Dataset

    with SessionLocal() as db:
        before = list(db.scalars(select(Dataset.id).where(Dataset.is_active.is_(True))))
        db.execute(update(Dataset).values(is_active=False))
        db.execute(update(Dataset).where(Dataset.id == imported.dataset_id).values(is_active=True))
        db.commit()
    invalidate_cache()
    yield
    with SessionLocal() as db:
        db.execute(update(Dataset).values(is_active=False))
        if before:
            db.execute(update(Dataset).where(Dataset.id.in_(before)).values(is_active=True))
        db.commit()
    invalidate_cache()


@pytest.fixture
def clean_om(active):
    with SessionLocal() as db:
        for m in (OmMailDelivery, OmMailRun, OmMailCircle, OmMailSetting):
            db.execute(delete(m))
        db.commit()
    yield


@pytest.fixture(scope="module")
def ctx(imported):
    return Context.build(imported)


def _names(ctx):
    return [c["name"] for c in ctx.circles()]


# ---------------------------------------------------------------- content


def test_each_circle_mail_has_only_its_own_figures(ctx):
    names = _names(ctx)
    assert len(names) >= 2
    for c in ctx.circles():
        v = circle_view(ctx, c["id"], 3, "Open point one\n<script>alert(1)</script>")
        html, text = render(v)
        assert c["name"] in html and all(o not in html for o in names if o != c["name"])  # never another circle
        assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html  # remarks are text
        assert "<script" not in html.lower() and "http://" not in html and "https://" not in html  # no scripts, no external content
        assert len(html.encode()) < 100_000  # Gmail clips larger mails
        assert v["circle"] in text and "Open point one" in text
        # the All Circles style: portal header, numbered sections, small KPI tiles, auto framing (1040 px page)
        assert html.index("One-Time Up GPs") < html.index("Field Force") and html.index("AMC Status") < html.index("Uptime Trend")
        for label in ("Daily MIS · BN3 O&amp;M", 'src="cid:om-logo"', "HoTo completion", "Total GPs", "HoTo Blocks", "HoTo GPs", "Route km (RKM)",
                      "AMC conversion", "AMC GPs", "Target achievement", "Month-wise one-time-up GPs", "GPs above 98%",
                      "GPs &lt;90% in penalty blocks", "GPs at 0%", "Penalty blocks", "Uptime distribution – AMC GPs (MTD, ", "Tiles &amp; distribution: MTD", "– weekly", "FRT on Portal",
                      "Definitions", 'class="om-frame"', 'content="width=1080"'):
            assert label in html, label
        for gone in ("MTD Ready", "WTD Ready", "AMC target –", f'{c["name"]} Circle'):
            assert gone not in html, gone


def test_figures_match_the_circle_overview(ctx):
    for d in ctx.overview["stateDetails"]:
        v = circle_view(ctx, d["id"])
        h, a, u = v["hoto"], v["amc"], v["uptime"]
        assert (h["blocks"], h["blocksScope"], h["gps"], h["gpsScope"]) == (d["hotoDoneBlocks"], d["blocks"], d["hotoDoneGps"], d["revisedExisting"])
        assert (a["gps"], a["gpsScope"], a["incremental"]) == (d["amcGps"], d["revisedExisting"], d["incrementalGps"])
        assert (u["above98"], u["atZero"], u["penaltyBlocks"]) == (d["gpsAbove98"], d["gpsAtZero"], d["penaltyBlocks"])
        # GPs < 90% counted only inside the penalty blocks (the same blocks as the Circle Overview)
        assert u["penaltyBlocksFound"] == d["penaltyBlocks"] and 0 <= u["below90"] <= u["penaltyGps"] and u["below90"] <= d["gpsBelowPenalty"]
        assert h["rkmScope"] == d["totalRkm"] and 0 <= (h["rkm"] or 0) <= (h["rkmScope"] or 0) + 0.01
        assert a["months"][-1]["value"] == d["amcGps"] and a["months"][-1]["current"]
        # the trend ends with the latest week of the data; the distribution adds up to the reporting GPs
        assert u["trendAbove98"][-1]["label"] == v["week"] and u["trendAbove98"][-1]["current"]
        assert sum(x["value"] for x in u["distribution"]) == u["distributionGps"]


def test_one_time_up_and_amc_targets(ctx, imported):
    """One-time up = GPs with uptime > 0 on any day of the month so far (and the same days of last month); month /
    week target, ready and achieved = the AMC Plan vs Execution rows of the circle."""
    from app.analytics.amc_plan import amc_plan_summary

    plan = {r["id"]: r for r in amc_plan_summary(imported, imported.latest_week.code)["rows"]}
    daily, as_of = imported.daily, imported.data_as_of
    days = [c for c in daily.columns if isinstance(c, dt.date) and c.year == as_of.year and c.month == as_of.month and c <= as_of]
    for c in ctx.circles():
        o = circle_view(ctx, c["id"])["oneTimeUp"]
        idx = imported.gps.index[imported.gps["circle_id"] == c["id"]]
        expect = int((daily.loc[idx, days].fillna(0) > 0).any(axis=1).sum()) if days else None
        assert o["current"] == expect and o["currentLabel"] == f"{as_of:%b} MTD"
        if o["previous"] is not None:
            assert o["delta"] == o["current"] - o["previous"]
        r = plan.get(c["id"], {})
        assert (o["month"]["target"], o["month"]["ready"], o["month"]["achieved"]) == (r.get("monthTarget"), r.get("monthReady"), r.get("monthConverted"))
        assert (o["week"]["target"], o["week"]["ready"], o["week"]["achieved"]) == (r.get("weekTarget"), r.get("weekReady"), r.get("weekConverted"))
        assert o["week"]["label"].startswith("WTD ") != o["week"]["complete"]


def test_all_circles_page_has_every_circle(ctx):
    views = [circle_view(ctx, c["id"]) for c in ctx.circles()]
    html, text = render_all(views)
    assert "All Circles" in html and all(c["name"] in html for c in ctx.circles()) and all(c["name"] in text for c in ctx.circles())
    assert "<script" not in html.lower() and "http://" not in html and "https://" not in html
    for v in views:  # each circle block on the page = the circle's own e-mail figures
        assert f'>{v["circle"]}<' in html and f'{v["hoto"]["gps"]:,}<span' in html and f'{v["uptime"]["above98"]:,}' in html
        assert f'{v["uptime"]["below90"]:,}<span' in html  # GPs < 90% in the penalty blocks, "x / y"
    # the All Circles page: portal design, two columns, no AMC month / week targets, MTD distribution, month-wise table
    for part in ('alt="Pratap – Carving Lives"', 'src="cid:om-logo"', "Daily MIS · BN3 O&amp;M", "DATA AS OF", "HoTo completion (GPs)", "Total GPs", "NP / Closed", "AMC conversion",
                 "Route km (RKM)", "GPs &lt;90% in penalty blocks", "Uptime distribution – AMC GPs (MTD, ", "Tiles &amp; distribution: MTD", "– weekly", "Month-wise one-time-up GPs",
                 'class="om-frame"', "zoom:", 'content="width=1640"'):  # auto framing: one layout, scaled to the screen
        assert part in html, part
    for gone in ("MTD Ready", "WTD Ready", "AMC target –", "Pending", "NETWORK<br>ANALYTICS", *(f'{c["name"]} Circle' for c in ctx.circles())):
        assert gone not in html, gone  # circle cards show just the circle name
    assert html.index("One-Time Up GPs") < html.index("Field Force") and html.index("AMC Status") < html.index("Uptime Trend")
    assert len(html.encode()) < 100_000  # Gmail clips larger mails
    one, _ = render(views[0])  # the circle e-mail: the same style (header, sections, fonts), its own KPI tiles
    assert "Daily MIS · BN3 O&amp;M" in one and "One-Time Up GPs" in one and "HoTo completion (GPs)" not in one and 'content="width=1080"' in one
    assert "Definitions" in html and "🏗" not in html and "🏗" not in one  # numbered badges, no emoji


def test_all_circles_extra_figures(ctx):
    """Total GPs / NP-closed as on the portal, the MTD distribution and the month-wise one-time-up table."""
    for d in ctx.overview["stateDetails"]:
        v = circle_view(ctx, d["id"])
        h, u, o = v["hoto"], v["uptime"], v["oneTimeUp"]
        assert (h["total"], h["npClosed"], h["pending"]) == (d["existingGps"], d["convertedOrClosed"], d["hotoPendingGps"])
        assert sum(x["value"] for x in u["distributionMtd"]) == u["distributionMtdGps"]
        assert u["distributionMtd"][0]["value"] == u["above98"]  # >98% MTD = the GPs above 98% (MTD) tile
        t = o["table"]["values"]
        assert t["cur"] == o["current"] and t["prev"] == o["previous"]  # same days as the one-time-up cards
        if t["cur"] is not None:
            assert t["amc"] + t["nonAmc"] == t["cur"]


def test_running_week_reads_wtd():
    class W:
        number, end = 48, dt.date(2026, 11, 27)

    assert week_label(W, dt.date(2026, 11, 22)) == "WTD W-48"
    assert week_label(W, dt.date(2026, 11, 27)) == "W-48"


# ---------------------------------------------------------------- schedule and recipients


def test_schedule_rules():
    s = om.clean_schedule({"0": ["09:00", "09:00", "17:30"], "6": []}, "08:00", "20:00")
    assert s["0"] == ["09:00", "17:30"] and s["6"] == [] and len(s) == 7
    for bad in ({"1": ["07:30"]}, {"2": ["21:00"]}, {"3": ["09:00", "10:00", "11:00", "12:00", "13:00"]}, {"4": ["9am"]}):
        with pytest.raises(om.OmMailError):
            om.clean_schedule(bad, "08:00", "20:00")
    with pytest.raises(om.OmMailError):
        om.clean_schedule({}, "20:00", "08:00")
    tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
    mon_8 = dt.datetime(2026, 11, 30, 8, 0, tzinfo=tz)  # a Monday
    assert om.next_slot({"0": ["09:00"]}, mon_8).astimezone(tz) == dt.datetime(2026, 11, 30, 9, 0, tzinfo=tz)
    assert om.next_slot({"0": ["09:00"]}, mon_8.replace(hour=9)).astimezone(tz) == dt.datetime(2026, 12, 7, 9, 0, tzinfo=tz)  # strictly after
    assert om.next_slot({}, mon_8) is None


def test_recipients_and_subject():
    s = OmMailSetting(central_cc=json.dumps(["boss@x.in", "head@x.in"]), subject_template="X")
    c = OmMailCircle(to_emails=json.dumps(["head@x.in"]), cc_emails=json.dumps(["mis@x.in", "head@x.in"]), include_ams=False,
                     area_managers=json.dumps([{"name": "A", "email": "am1@x.in", "enabled": True}, {"name": "B", "email": "am2@x.in", "enabled": False}]))
    assert om.recipients(c, s) == (["head@x.in"], ["mis@x.in", "boss@x.in"])  # an address in To is not repeated in CC
    c.include_ams = True
    assert om.recipients(c, s)[0] == ["head@x.in", "am1@x.in"]  # only the enabled AMs
    view = {"circle": "Rajasthan", "dataAsOf": "2026-11-22", "week": "WTD W-48"}
    assert om.render_subject("O&M – {circle} – {date} ({week})\r\nBcc: evil@x.in", view) == "O&M – Rajasthan – 22 Nov 2026 (WTD W-48) Bcc: evil@x.in"  # one line
    assert om.render_subject("", view).startswith("O&M Daily Dashboard – Rajasthan")
    with pytest.raises(om.OmMailError):
        om.clean_emails(["ok@x.in", "not-an-address"], "To")
    merged = om.merge_area_managers(
        [{"name": "Old", "email": "am1@x.in", "source": "matrix", "enabled": False}, {"name": "Typed", "email": "t@x.in", "source": "manual", "enabled": True},
         {"name": "Gone", "email": "gone@x.in", "source": "matrix", "enabled": True}],
        [{"name": "Am One", "email": "am1@x.in", "source": "matrix", "enabled": True}],
    )
    assert [(m["email"], m["enabled"]) for m in merged] == [("am1@x.in", False), ("t@x.in", True)]  # choice kept, manual kept, removed person gone


# ---------------------------------------------------------------- API and sending


def _setup(client, ctx, c1_to=("head1@pratap-test.in",), central=("boss@pratap-test.in",)):
    h = {"X-CSRF-Token": login(client)}
    cfg = client.get("/api/v1/mail/om").json()
    assert [c["circleId"] for c in cfg["circles"]] == [c["id"] for c in ctx.circles()] and not cfg["settings"]["enabled"]
    c1 = ctx.circles()[0]["id"]
    r = client.put(f"/api/v1/mail/om/circles/{c1}", json={"enabled": True, "to": list(c1_to), "cc": ["mis@pratap-test.in"], "subject": "Daily {circle} {date}",
                                                            "includeAms": True, "areaManagers": [{"name": "Typed AM", "email": "typed.am@pratap-test.in", "source": "manual"}],
                                                            "remarks": "Point A\nPoint B"}, headers=h)
    assert r.status_code == 200, r.text
    r = client.put("/api/v1/mail/om/settings", json={"enabled": False, "centralCc": list(central), "schedule": {"0": ["09:00"]}, "windowStart": "08:00", "windowEnd": "20:00",
                                                     "subjectTemplate": "O&M {circle}"}, headers=h)
    assert r.status_code == 200, r.text
    return h, c1


def test_api_validation_preview_and_admin_only(client, ctx, clean_om):
    h, c1 = _setup(client, ctx)
    c2 = ctx.circles()[1]["id"]
    assert client.put(f"/api/v1/mail/om/circles/{c2}", json={"enabled": True, "to": []}, headers=h).status_code == 422  # on without To
    assert client.put(f"/api/v1/mail/om/circles/{c2}", json={"to": ["bad address"]}, headers=h).status_code == 422
    assert client.put("/api/v1/mail/om/settings", json={"enabled": True, "schedule": {}}, headers=h).status_code == 422  # on without a time
    assert client.put("/api/v1/mail/om/settings", json={"schedule": {"1": ["23:00"]}}, headers=h).status_code == 422  # outside the window
    r = client.put("/api/v1/mail/om/settings", json={"enabled": True, "schedule": {str(d): ["09:00"] for d in range(7)}}, headers=h)
    assert r.status_code == 200 and r.json()["settings"]["nextRunAt"]  # saving never sends: the next run is in the future
    assert dt.datetime.fromisoformat(r.json()["settings"]["nextRunAt"]) > dt.datetime.now(dt.UTC)
    p = client.get(f"/api/v1/mail/om/preview/{c1}").json()
    name1 = ctx.circles()[0]["name"]
    assert name1 in p["html"] and "Point A" in p["html"] and p["subject"].startswith(f"Daily {name1}")
    assert client.get("/api/v1/mail/om/preview/no-such-circle").status_code == 404
    allp = client.get("/api/v1/mail/om/preview/all").json()  # All Circles: preview / download only
    assert all(c["name"] in allp["html"] for c in ctx.circles()) and "All Circles" in allp["subject"]
    assert all(c["circleId"] != "all" for c in client.get("/api/v1/mail/om").json()["circles"])  # never listed with the circles
    cfg = client.get("/api/v1/mail/om").json()
    eff = next(c for c in cfg["circles"] if c["circleId"] == c1)["effective"]
    assert eff["to"] == ["head1@pratap-test.in", "typed.am@pratap-test.in"] and eff["cc"] == ["mis@pratap-test.in"]  # central CC cleared by the save above
    login(client, VIEWER)
    assert client.get("/api/v1/mail/om").status_code == 403
    assert client.post("/api/v1/mail/om/send-now", json={}, headers={"X-CSRF-Token": client.cookies.get("pratap_csrf")}).status_code == 403


def test_test_mail_goes_to_the_admin_only(client, ctx, clean_om, smtp):  # noqa: F811
    h, c1 = _setup(client, ctx)
    r = client.post("/api/v1/mail/om/test", json={"circleId": c1}, headers=h)
    assert r.status_code == 200 and r.json()["ok"], r.text
    msgs = all_sent()
    assert len(msgs) == 1 and msgs[0]["To"] == ADMIN_EMAIL and msgs[0]["Cc"] is None and msgs[0]["Subject"].startswith("[TEST]")
    body = msgs[0].get_body(("html",)).get_content()
    assert ctx.circles()[0]["name"] in body and "O&amp;M Daily Dashboard" in body
    log = client.get("/api/v1/mail/om/deliveries", params={"kind": "TEST"}).json()
    assert log["total"] == 1 and log["items"][0]["status"] == "SENT" and log["items"][0]["to"] == [ADMIN_EMAIL]


def test_send_now_one_mail_per_enabled_circle_with_to_and_cc(client, ctx, clean_om, smtp):  # noqa: F811
    h, c1 = _setup(client, ctx)
    client.put("/api/v1/mail/om/settings", json={"centralCc": ["boss@pratap-test.in"], "schedule": {"0": ["09:00"]}}, headers=h)
    r = client.post("/api/v1/mail/om/send-now", json={}, headers=h)
    assert r.status_code == 200 and r.json()["sent"] == 1, r.text  # only the enabled circle
    m = all_sent()[0]
    assert m["To"] == "head1@pratap-test.in, typed.am@pratap-test.in" and m["Cc"] == "mis@pratap-test.in, boss@pratap-test.in"
    name1 = ctx.circles()[0]["name"]
    assert m["Subject"].startswith(f"Daily {name1}")
    html = m.get_body(("html",)).get_content()
    assert name1 in html and all(n not in html for n in _names(ctx) if n != name1)
    item = client.get("/api/v1/mail/om/deliveries").json()["items"][0]
    assert item["status"] == "SENT" and item["kind"] == "MANUAL" and item["cc"] == ["mis@pratap-test.in", "boss@pratap-test.in"] and item["sizeBytes"] > 1000


def test_scheduler_sends_each_slot_once(client, ctx, clean_om, smtp, monkeypatch):  # noqa: F811
    h, c1 = _setup(client, ctx)
    client.put("/api/v1/mail/om/settings", json={"enabled": True, "schedule": {str(d): ["09:00"] for d in range(7)}, "windowStart": "00:00", "windowEnd": "23:59"}, headers=h)
    with SessionLocal() as db:
        assert om.run_due(db) is None  # the switch in .env is off: nothing happens
    monkeypatch.setattr(get_settings(), "om_daily_emails_enabled", True)
    with SessionLocal() as db:
        s = om.settings_row(db)
        due = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        s.next_run_at = due
        db.commit()
        rid = om.run_due(db)
        assert rid is not None and len(all_sent()) == 1
        assert om.run_due(db) is None and len(all_sent()) == 1  # the slot moved on: no second e-mail
        assert om.utc(om.settings_row(db).next_run_at) > dt.datetime.now(dt.UTC)
        # another process trying the same slot is refused by the unique slot key
        db.add(OmMailRun(slot_key=f"sched:{due.isoformat()}", kind="SCHEDULED", status="RUNNING"))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        # a slot seen hours late (server was down) is skipped, not sent late
        s = om.settings_row(db)
        s.next_run_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
        db.commit()
        rid = om.run_due(db)
        assert db.get(OmMailRun, rid).status == "SKIPPED" and len(all_sent()) == 1


def test_stopped_while_sending_is_never_resent_and_smtp_failure_is_logged(client, ctx, clean_om, smtp, monkeypatch):  # noqa: F811
    h, c1 = _setup(client, ctx)
    monkeypatch.setattr(get_settings(), "om_daily_emails_enabled", True)
    with SessionLocal() as db:
        run = OmMailRun(slot_key="manual:old", kind="MANUAL", status="RUNNING")
        db.add(run)
        db.commit()
        db.add(OmMailDelivery(run_id=run.id, circle_id=c1, subject="x", status="SENDING", created_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)))
        db.commit()
        om.run_due(db)  # the tick marks it UNKNOWN (nothing due, nothing sent)
        assert db.scalars(select(OmMailDelivery.status).where(OmMailDelivery.run_id == run.id)).one() == "UNKNOWN" and not all_sent()
    FakeSMTP.fail_connect = True
    r = client.post("/api/v1/mail/om/send-now", json={"circleId": c1}, headers=h)
    assert r.status_code == 200 and not r.json()["ok"] and r.json()["failed"] == 1
    failed = client.get("/api/v1/mail/om/deliveries", params={"status": "FAILED"}).json()["items"]
    assert failed and failed[0]["error"]


# ---------------------------------------------------------------- the All Circles mail (management)


def _setup_all(client, h, to=("mgmt@pratap-test.in",), cc=("copy@pratap-test.in",), enabled=True):
    r = client.put("/api/v1/mail/om/circles/all", json={"enabled": enabled, "to": list(to), "cc": list(cc), "subject": "",
                                                        "includeAms": True, "areaManagers": [{"name": "X", "email": "x@pratap-test.in"}], "remarks": "ignored"}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_all_circles_mail_own_recipients_and_never_with_the_circles(client, ctx, clean_om, smtp):  # noqa: F811
    h, c1 = _setup(client, ctx)  # circle 1 on, central CC boss@
    client.put("/api/v1/mail/om/settings", json={"centralCc": ["boss@pratap-test.in"], "schedule": {"0": ["09:00"]}}, headers=h)
    cfg = client.get("/api/v1/mail/om").json()
    assert cfg["allCircles"]["circleId"] == "all" and not cfg["allCircles"]["enabled"]  # created switched off
    assert client.put("/api/v1/mail/om/circles/all", json={"enabled": True, "to": []}, headers=h).status_code == 422  # on without To
    j = _setup_all(client, h)
    # only its own To / CC: no central CC, no Area Managers, no remarks
    assert j["effective"] == {"to": ["mgmt@pratap-test.in"], "cc": ["copy@pratap-test.in"]} and j["areaManagers"] == [] and not j["includeAms"] and j["remarks"] == ""
    # the circles' "Send now" never sends it
    r = client.post("/api/v1/mail/om/send-now", json={}, headers=h)
    assert r.json()["sent"] == 1 and all("All Circles" not in m["Subject"] for m in all_sent())
    # its own "Send now": one e-mail with every circle, To / CC exactly as typed
    r = client.post("/api/v1/mail/om/send-now", json={"circleId": "all"}, headers=h)
    assert r.status_code == 200 and r.json()["sent"] == 1, r.text
    m = all_sent()[-1]
    assert m["To"] == "mgmt@pratap-test.in" and m["Cc"] == "copy@pratap-test.in" and "All Circles" in m["Subject"]
    html = m.get_body(("html",)).get_content()
    assert all(c["name"] in html for c in ctx.circles()) and len(html.encode()) < 100_000
    assert 'src="cid:' in html and any(p.get_content_type() == "image/png" for p in m.walk())  # the logo travels as an inline image
    item = client.get("/api/v1/mail/om/deliveries", params={"circle": "all"}).json()["items"][0]
    assert item["status"] == "SENT" and item["kind"] == "MANUAL" and item["to"] == ["mgmt@pratap-test.in"]


def test_all_circles_mail_test_schedule_and_off(client, ctx, clean_om, smtp, monkeypatch):  # noqa: F811
    h, c1 = _setup(client, ctx)
    _setup_all(client, h, enabled=False)
    assert client.post("/api/v1/mail/om/send-now", json={"circleId": "all"}, headers=h).status_code == 409  # off: not sent
    assert not all_sent()
    r = client.post("/api/v1/mail/om/test", json={"circleId": "all"}, headers=h)  # test mail: only to the admin
    assert r.status_code == 200 and r.json()["ok"], r.text
    m = all_sent()[-1]
    assert m["To"] == ADMIN_EMAIL and m["Cc"] is None and m["Subject"].startswith("[TEST]") and "All Circles" in m["Subject"]
    # switched on: goes with the schedule, together with the circles
    _setup_all(client, h, enabled=True)
    client.put("/api/v1/mail/om/settings", json={"enabled": True, "schedule": {str(d): ["09:00"] for d in range(7)}, "windowStart": "00:00", "windowEnd": "23:59"}, headers=h)
    monkeypatch.setattr(get_settings(), "om_daily_emails_enabled", True)
    before = len(all_sent())
    with SessionLocal() as db:
        s = om.settings_row(db)
        s.next_run_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        db.commit()
        assert om.run_due(db) is not None
    sent = all_sent()[before:]
    assert len(sent) == 2 and sum("All Circles" in x["Subject"] for x in sent) == 1  # circle 1 + the All Circles mail
