"""The reusable PAGMAS HTML e-mail: exact dashboard link (never localhost, no token), escaped values, inline logo (not an
attachment), plain-text twin, and the AMC Conversion report inside the same layout."""

from app.mail import layout as L
from app.mail import template as tpl

URL = "https://pagmas.pramaanu.co.in/login"


def _email(**kw):
    base = dict(
        title="New GP-wise task assigned", badge="Action Required", badge_tone="warning", greeting="<b>Ravi</b>", intro=["Assigned GPs: 3"], reference="TKT-000001",
        kpis=[L.Kpi("Weekly target", "3", "info")], summary=[("Circle", "Rajasthan")], sections=[L.Section("GP-wise list (1 GPs)", L.Table(["GP Code"], [["<script>x</script>"]]))],
        action=L.Action("Update every GP", who="Area Manager Ravi", due="13 Nov 2026"),
    )
    return L.Email(**(base | kw))


def test_dashboard_button_uses_the_exact_url_and_values_are_escaped():
    html, text = L.render(_email())
    assert f'href="{URL}"' in html and "VIEW DASHBOARD" in html and URL in text
    assert "localhost" not in html + text and "token" not in URL
    assert "<script>" not in html and "&lt;script&gt;x&lt;/script&gt;" in html and "&lt;b&gt;Ravi&lt;/b&gt;" in html
    assert "Action required" in html and "Due: 13 Nov 2026" in html and "ACTION REQUIRED: Update every GP" in text


def test_logo_is_inline_not_an_attachment():
    msg = L.message("am@example.com", "Subject", _email())
    parts = list(msg.walk())
    img = [p for p in parts if p.get_content_type() == "image/png"]
    assert len(img) == 1 and img[0]["Content-ID"] == f"<{L.LOGO_CID}>" and not img[0].get_filename()
    assert f"cid:{L.LOGO_CID}" in msg.get_body(("html",)).get_content()
    assert msg.get_body(("plain",)).get_content().startswith("PAGMAS – New GP-wise task assigned")


def test_amc_report_uses_the_same_layout_with_kpis():
    t = tpl.DEFAULT_TEMPLATES[0]
    total = {"monthTarget": 10, "mtdTarget": 6, "mtdAchieved": 4, "mtdPct": 66.67, "overdue": 2, "weekTarget": 3, "weekAchieved": 1, "weekPct": 33.33}
    figures = {"gps": 50, "total": total, "block": [], "am": [], "ba": [], "hasPlan": True}
    periods = {"data_date": "10 Nov 2026", "month": "Nov 2026", "week": "WK-46", "week_range": "07 Nov – 13 Nov 2026", "source_file": "x.xlsb"}
    r = tpl.render(t["subject"], t["body"], tpl.values(figures, periods, "Mohan", "COH", "Rajasthan", "am"))
    assert URL in r.html and "AMC Conversion status" in r.html and "Overdue" in r.html and "Action Required" in r.html
    assert "Dear Mohan" in r.text and URL in r.text and "{{" not in r.html + r.text
