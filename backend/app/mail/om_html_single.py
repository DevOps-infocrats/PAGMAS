"""O&M Daily Dashboard – the e-mail of ONE circle (what a circle head receives), in the All Circles style.

Same building blocks as the All Circles page (app.mail.om_html): the portal header (full Pratap logo, "Daily MIS · BN3
O&M", DATA AS OF pill, week chip), numbered section frames, portal fonts / colours, glyph dots, auto framing (one fixed
page width, scaled to the screen) and the hidden per-mail tokens against Gmail's trimming. The figures of the circle
are shown as small KPI tiles (3 per row) so the page stays compact:

  header      AMC conversion · one-time up (this month MTD vs last month) · penalty blocks
  1 HoTo      completion · total GPs (incl. NP / closed) · blocks · GPs · route km
  2 AMC       conversion · AMC GPs · scope fibre · AMC fibre · month-wise chart
  3 One-Time  target achievement (target · gap) · last month MTD · this month MTD · month-wise table
  4 Uptime    GPs >98% · GPs <90% in penalty blocks · GPs at 0% · penalty blocks · MTD distribution · weekly charts
  5 Field     FRT count · FRT on portal
  6 Remarks   as typed for the circle · definitions

Only that circle's figures are on the page (the e-mail of a circle never shows another circle).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import om_html as oa

FONT = oa.FONT
WIDTH = 1040  # page width (one circle): scaled, never re-flowed – see om_html._frame_css
# compact cards on this page: smaller paddings, row spacing and big figures than the All Circles page
COMPACT = [
    ('<tr><td style="padding:10px 12px">', '<tr><td style="padding:7px 11px">'),  # card body
    ("padding:9px 12px;", "padding:6px 11px;"),  # card header band
    ("padding:7px 0;", "padding:4px 0;"),  # label / value rows
    ("font-size:24px;font-weight:800;color:", "font-size:20px;font-weight:800;color:"),  # big % figures
    ("margin:2px 0 6px", "margin:0 0 4px"),
    ('<tr><td style="padding:14px 11px 10px">', '<tr><td style="padding:10px 9px 7px">'),  # section frame
    ('margin-top:12px">', 'margin-top:8px">'),
]


def _kpi(label: str, value: str, sub: str, tone: str) -> str:
    """Highlight tile under the header (portal MiniKpi): white, coloured top line, label, value, caption."""
    return (f'<td valign="middle" style="padding:0 8px 0 0"><table role="presentation" cellpadding="0" cellspacing="0" style="border:1px solid {oa.LINE};border-top:3px solid {tone};'
            f'border-radius:7px;border-collapse:separate;background:#ffffff;min-width:104px"><tr><td style="padding:4px 9px 5px">'
            f'<div style="{FONT};font-size:9px;font-weight:700;color:{oa.MUTED};text-transform:uppercase;letter-spacing:.3px;white-space:nowrap">{label}</div>'
            f'<div style="{FONT};font-size:15px;font-weight:800;color:{oa.INK};white-space:nowrap;line-height:19px">{value}</div>'
            f'<div style="{FONT};font-size:10px;color:{oa.MUTED};white-space:nowrap">{sub}</div></td></tr></table></td>')


def _tile(label: str, value: str, sub: str = "", colour: str = oa.PRIMARY, bar: float | None = None, light: str = "#e5eaf1", value_colour: str = "") -> str:
    """A small KPI tile: coloured top line (circle colour), label, figure, one-line caption, optional bar."""
    bar_html = f'<div style="margin-top:5px">{oa._bar(bar, colour, light, 4)}</div>' if bar is not None else ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {oa.LINE};border-top:3px solid {colour};border-radius:8px;border-collapse:separate;background:#ffffff">'
        f'<tr><td style="padding:6px 9px 7px">'
        f'<div style="{FONT};font-size:9px;font-weight:700;color:{oa.MUTED};text-transform:uppercase;letter-spacing:.3px;white-space:nowrap;overflow:hidden">{label}</div>'
        f'<div style="{FONT};font-size:16px;font-weight:800;color:{value_colour or oa.INK};white-space:nowrap;margin-top:2px">{value}</div>'
        f'<div style="{FONT};font-size:10px;color:{oa.MUTED};white-space:nowrap;overflow:hidden">{sub or "&nbsp;"}</div>{bar_html}'
        f"</td></tr></table>"
    )


def _tiles(tiles: list[str], per_row: int = 3) -> str:
    """Tiles in rows of `per_row` (equal widths; the last row is filled with empty cells)."""
    w = round(100 / per_row)
    out = ""
    for i in range(0, len(tiles), per_row):
        row = tiles[i:i + per_row] + [""] * (per_row - len(tiles[i:i + per_row]))
        out += "<tr>" + "".join(f'<td valign="top" width="{w}%" style="padding:3px">{t}</td>' for t in row) + "</tr>"
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed">{out}</table>'


def _of(done: Any, scope: Any) -> str:
    return f'{oa.n(done)}<span style="font-size:11px;font-weight:600;color:{oa.MUTED}"> / {oa.n(scope)}</span>'


def _s1(v: dict[str, Any], c: str, lt: str) -> str:
    h = v["hoto"]
    legend = f'incl. {oa._dot("#d03b3b")} {oa.n(h.get("npClosed"))} NP / closed'  # the done GPs are in the HoTo GPs tile
    return _tiles([
        _tile("HoTo completion", oa.pct(h["gpsPct"]), "of active GPs", c, h["gpsPct"], lt),
        _tile("Total GPs", oa.n(h.get("total")), legend, c),
        _tile("HoTo Blocks", _of(h["blocks"], h["blocksScope"]), f"{oa.pct(h['blocksPct'])} of blocks", c),
        _tile("HoTo GPs", _of(h["gps"], h["gpsScope"]), f"{oa.pct(h['gpsPct'])} of active GPs", c),
        _tile("Route km (RKM)", f'{oa.n(h["rkm"])}<span style="font-size:11px;font-weight:600;color:{oa.MUTED}"> RKM</span>', f"{oa.pct(h['rkmPct'])} of route km", c),
    ])


def _s2(v: dict[str, Any], c: str, lt: str) -> str:
    a = v["amc"]
    return _tiles([
        _tile("AMC conversion", oa.pct(a["pct"]), "of active GPs", c, a["pct"], lt),
        _tile("AMC GPs", _of(a["gps"], a["gpsScope"]), f"{oa.pct(a['pct'])} of revised", c),
        _tile("Scope Fibre (RKM)", oa.n(a["rkmScope"]), "route km in scope", c),
        _tile("AMC Fibre (RKM)", oa.n(a["rkm"]), f"{oa.pct(a['rkmPct'])} of scope", c),
    ]) + oa._sub("AMC GPs – month-wise") + oa._columns(a["months"], c, lt, height=44)


def _s3(v: dict[str, Any], c: str, lt: str, cs: list) -> str:
    o = v["oneTimeUp"]
    prev = (o["previousLabel"] or "").split(" ")[0]
    gap = (f'Target {oa.n(o["target"])} · Gap <b style="color:{oa.BAD if (o["gap"] or 0) > 0 else oa.GOOD}">{oa.n(o["gap"])}</b>'
           if o["target"] is not None else "no target in the data")
    return _tiles([
        _tile("Target achievement", oa.pct(o["pct"]), gap, c, o["pct"], lt),
        _tile(oa._e(o["previousLabel"]), oa.n(o["previous"]), oa._e(o["previousRange"]), c),
        _tile(oa._e(o["currentLabel"]), oa.n(o["current"]), f"{oa._delta(o['delta'])} vs {oa._e(prev)}" if o["delta"] is not None else oa._e(o["range"]), c),
    ]) + oa._month_table(cs)


def _s4(v: dict[str, Any], c: str, lt: str, cs: list) -> str:
    u = v["uptime"]
    full = oa._s4(cs)  # the MTD distribution and the weekly charts of the All Circles page, below the tiles
    head = oa._heading(oa._dist_title(u, v["oneTimeUp"]))
    return _tiles([
        _tile("GPs above 98%", _of(u["above98"], u["reporting"]), f"{oa.pct(u['above98Pct'])} of reporting", c, u["above98Pct"], lt),
        _tile("GPs &lt;90% in penalty blocks", _of(u["below90"], u["penaltyGps"]), f"in {oa.n(u['penaltyBlocks'])} blocks &lt;90%", c, value_colour=oa.BAD if u["below90"] else ""),
        _tile("GPs at 0%", oa.n(u["atZero"]), "no uptime this month", c, value_colour=oa.BAD if u["atZero"] else ""),
        _tile("Penalty blocks", oa.n(u["penaltyBlocks"]), "block mean uptime &lt;90%", c, value_colour=oa.BAD if u["penaltyBlocks"] else ""),
    ], per_row=2) + full[full.index(head):]


def _s5(v: dict[str, Any], c: str) -> str:
    f = v["fieldForce"]
    return _tiles([
        _tile("FRT Count (O&amp;M)", oa.n(f["frtCount"]), "as per O&amp;M sheet", c),
        _tile("FRT on Portal", oa.n(f["onPortal"]), f"{oa.pct(f['onPortalPct'])} with a portal login" if f["onPortalPct"] is not None else "&nbsp;", c),
    ], per_row=2)


def _s6(v: dict[str, Any], c: str) -> str:
    if v["remarks"]:
        items = "".join(f'<tr><td valign="top" style="{FONT};font-size:13px;color:{c};padding:2px 6px 2px 0">›</td>'
                        f'<td style="{FONT};font-size:12px;color:{oa.INK};padding:2px 0">{oa._e(r)}</td></tr>' for r in v["remarks"])
        body = f'<table role="presentation" cellpadding="0" cellspacing="0">{items}</table>'
    else:
        body = f'<div style="{FONT};font-size:12px;color:{oa.MUTED}">No open points.</div>'
    return f'<div style="padding:3px"><div style="border:1px solid {oa.LINE};border-radius:8px;background:#ffffff;padding:8px 10px">{body}</div></div>'


def render_html(v: dict[str, Any], gen: str, inline_logo: bool = False) -> str:
    """The HTML of one circle's e-mail. inline_logo: the logo inside the file (preview / download); otherwise "cid:"
    (the e-mail attaches it – om_html.attach_logo)."""
    cs = [(v, *oa._colours(v, 0))]
    c, lt = cs[0][1], cs[0][2]
    a, o, u = v["amc"], v["oneTimeUp"], v["uptime"]
    as_of = dt.date.fromisoformat(v["dataAsOf"])
    week_line = f"{oa._e(v['week'])} · {oa._e(v['weekRange'])}" + ("" if v["weekComplete"] else " · in progress")
    prev = (o["previousLabel"] or "").split(" ")[0]
    pre = f"{v['circle']}: AMC {oa.pct(a['pct'])}, one-time up {oa.n(o['current'])}, {oa.n(u['penaltyBlocks'])} blocks below 90%"
    s1 = oa._section(1, "HoTo & Network Status", "Done / scope", _s1(v, c, lt))
    s2 = oa._section(2, "AMC Status", "GPs and fibre under AMC", _s2(v, c, lt))
    s3 = oa._section(3, "One-Time Up GPs", "Month to date vs last month", _s3(v, c, lt, cs))
    s4 = oa._section(4, "Uptime Trend", oa.uptime_subtitle(v), _s4(v, c, lt, cs))
    s5 = oa._section(5, "Field Force", "FRT deployment", _s5(v, c))
    s6 = oa._section("r", "Remarks & Open Points", f"As updated for {oa._e(v['circle'])}", _s6(v, c))
    defs = [
        f"<b>One-time up</b> – GPs with uptime &gt; 0 on at least one day ({oa._e(o['range'])} vs {oa._e(o['previousRange'])}).",
        "<b>Penalty blocks</b> – blocks whose mean AMC uptime is below 90%; GPs &lt;90% are counted inside these blocks.",
        "<b>WTD</b> – week to date: the week is still running and the figures update with every upload.",
    ]
    defs_html = (f'<div style="padding:6px"><div style="background:#ffffff;border:1px solid {oa.LINE};border-radius:12px;padding:11px 14px">{oa.MARK}{oa._label("Definitions")}'
                 + "".join(f'<div style="{FONT};font-size:11px;color:{oa.TEXT};margin-top:4px;line-height:15px">{d}</div>' for d in defs) + "</div></div>")
    c1 = oa._block(s1) + oa._block(s3) + oa._block(s5) + oa._block(s6) + defs_html
    c2 = oa._block(s2) + oa._block(s4)
    rows = ('<tr><td style="padding:0 10px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed"><tr>'
            f'<td width="50%" valign="top">{c1}</td><td width="50%" valign="top">{c2}</td></tr></table></td></tr>')
    head = oa._header(f"{oa._dot(c)} {oa._e(v['circle'])}", as_of, week_line, oa._logo_src(inline_logo))
    # the three highlight tiles in their own row under the header (keeps the header inside the page width)
    tiles = ('<tr><td style="padding:12px 16px 2px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>'
             + _kpi("AMC conversion", oa.pct(a["pct"]), f"{oa.n(a['gps'])} of {oa.n(a['gpsScope'])} GPs", oa.PRIMARY)
             + _kpi(f"One-time up · {oa._e(o['currentLabel'])}", oa.n(o["current"]), f"{oa._delta(o['delta'])} vs {oa._e(prev)}" if o["delta"] is not None else "&nbsp;", "#0ca30c")
             + _kpi("Penalty blocks &lt;90%", f'<span style="color:{oa.BAD if u["penaltyBlocks"] else oa.INK}">{oa.n(u["penaltyBlocks"])}</span>', f"{oa.n(u['below90'])} GPs &lt;90% inside", "#d03b3b")
             + "</tr></table></td></tr>")
    foot = (f'<tr><td style="padding:6px 22px 16px">{oa.MARK}<div style="{FONT};font-size:11px;color:{oa.MUTED}">Generated on {gen} from {oa._e(v["sourceFile"]) or "the active master data"}'
            f" · data as of {as_of:%d %b %Y} · system-generated mail – for data corrections contact the O&amp;M MIS team.</div></td></tr>")
    html = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width={WIDTH + oa.PAGE_MARGIN}">'
        f"<title>O&amp;M Daily Dashboard – {oa._e(v['circle'])}</title>{oa._frame_css(WIDTH)}</head>"
        f'<body style="margin:0;padding:0;background:{oa.PAGE}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{oa._e(pre)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{oa.PAGE}"><tr><td align="center" style="padding:16px 8px">'
        f'<table class="om-frame" role="presentation" width="{WIDTH}" cellpadding="0" cellspacing="0" style="width:{WIDTH}px;background:{oa.FRAME};border-radius:12px;border:1px solid {oa.LINE};border-collapse:separate">'
        f'{head}{tiles}<tr><td style="height:4px;font-size:1px">&nbsp;</td></tr>{rows}{foot}</table></td></tr></table></body></html>'
    )
    for old, new in COMPACT:
        html = html.replace(old, new)
    return html.replace(oa.UID, oa.unique_token())
