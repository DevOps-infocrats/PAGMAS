"""O&M Daily Dashboard – HTML (and plain text) from the circle views of app.mail.om_data.circle_view.

  render(view)       the e-mail of ONE circle (what a circle head receives) – app.mail.om_html_single: the same
                     style as below, the circle's figures as small KPI tiles, 1040 px, auto framing
  render_all(views)  every circle on one page (preview / download and the All Circles mail for the management) – the
                     portal design below

Both read the same circle views, so the numbers are always the same.

All Circles page – the look of the portal (frontend/src/app/globals.css): light grey page, white cards with a thin
border, Inter font, primary #0a78b0, the page header of the portal (brand line green → blue, hero surface, "pratap"
wordmark, green DATA AS OF pill, week chip), numbered section badges, circle colours from the portal chart palette
(Rajasthan orange, Haryana green, Assam indigo), status colours of the portal.

Layout: two columns at one fixed page width (PAGE_WIDTH) – left HoTo & Network, One-Time Up GPs (cards + the
month-wise table), Field Force, Remarks, Definitions; right AMC Status, Uptime Trend (cards, MTD distribution, weekly
charts). Auto framing (_frame_css): the layout never re-flows; phones / tablets fit the whole page on screen and
narrower browser windows scale it down, so every screen shows the same page. "done / scope" for HoTo blocks / GPs, AMC GPs
and the GPs < 90% inside the penalty blocks; HoTo shows the total GPs with done and converted to NP / closed.

E-mail safe by construction: table layout, inline CSS only, no scripts, no external images or fonts, bars drawn with
table cells; below Gmail's 100 KB clipping. Every value is HTML-escaped – remarks typed by an admin are text.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

# portal tokens (frontend/src/app/globals.css)
INK = "#14202b"
TEXT = "#3b4754"
MUTED = "#4a5866"
LINE = "#dde5eb"
PAGE = "#f2f6f8"
FRAME = "#f2f6f8"
GOOD = "#0b6e2c"  # status text colours
WARN = "#8a5300"
BAD = "#b42318"
PRIMARY = "#0a78b0"
HEADING = "#0c2a3d"
FONT = "font-family:Inter,Arial,sans-serif"  # short: repeated on every cell (Outlook does not inherit fonts)
CIRCLE_COLOURS = {"rajasthan": ("#f6821f", "#fde6d2"), "haryana": ("#1baf7a", "#d3f2e6"), "assam": ("#4a3aa7", "#e2def4")}  # portal chart series
FALLBACK_COLOURS = [("#0a7fc0", "#d6ebf7"), ("#eda100", "#fbefcc"), ("#e87ba4", "#fae3ec"), ("#008300", "#d1ead1")]
DIST_COLOURS = ["#0ca30c", "#7fd17f", "#fab219", "#ec835a", "#d03b3b"]  # >98 · 95–98 · 90–95 · 75–90 · <75
DIST_DARK_TEXT = ("#7fd17f", "#fab219")  # light segments get dark figures

# Gmail hides ("•••", trimmed content) every part of a mail that is identical to an earlier mail of the conversation.
# Each section starts with a hidden token that is different for every rendering (time + random), so no section is
# ever identical to an earlier mail. It is invisible (display:none, 0 size; mso-hide for Outlook) and a few bytes.
UID = "%OMUID%"
MARK = f'<span style="display:none;font-size:0;line-height:0;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">{UID}</span>'


def unique_token() -> str:
    import secrets

    return f"{dt.datetime.now():%d%m%y%H%M%S}{secrets.token_hex(3)}"



def _e(v: Any) -> str:
    return escape("" if v is None else str(v))


def n(v: Any, digits: int = 0) -> str:
    """1,234 / 1,234.5 ; "—" when unknown."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _e(v)
    return f"{f:,.{digits}f}" if digits else f"{round(f):,}"


def pct(v: Any) -> str:
    return "—" if v is None else f"{float(v):.1f}%"


def _ratio(a: Any, b: Any) -> float | None:
    if a is None or not b:
        return None
    return round(100.0 * a / b, 1)


def _colours(v: dict[str, Any], i: int) -> tuple[str, str]:
    key = str(v.get("circleId") or v.get("circle") or "").lower()
    return CIRCLE_COLOURS.get(key) or CIRCLE_COLOURS.get(str(v.get("circle", "")).lower()) or FALLBACK_COLOURS[i % len(FALLBACK_COLOURS)]


# ---------------------------------------------------------------- building blocks


def _bar(p: float | None, colour: str, track: str = LINE, height: int = 6) -> str:
    w = max(0, min(100, round(p or 0)))
    cells = f'<td width="{w}%" style="background:{colour};height:{height}px;line-height:{height}px;font-size:1px">&nbsp;</td>' if w else ""
    cells += f'<td width="{100 - w}%" style="background:{track};height:{height}px;line-height:{height}px;font-size:1px">&nbsp;</td>' if w < 100 else ""
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>{cells}</tr></table>'


def _grid(cells: list[str], gap: int = 5) -> str:
    """Cells side by side, equal widths (one cell = full width)."""
    w = round(100 / max(1, len(cells)))
    tds = "".join(f'<td valign="top" width="{w}%" style="padding:{gap}px">{c}</td>' for c in cells)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed"><tr>{tds}</tr></table>'


def _card(title: str, colour: str, body: str) -> str:
    """A circle card: coloured header band + body."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:10px;border-collapse:separate;background:#ffffff">'
        f'<tr><td style="background:{colour};border-radius:9px 9px 0 0;padding:9px 12px;{FONT};font-size:13px;font-weight:700;color:#ffffff">{title}</td></tr>'
        f'<tr><td style="padding:10px 12px">{body}</td></tr></table>'
    )


def _label(text: str, extra: str = "") -> str:
    return f'<div style="{FONT};font-size:10px;font-weight:700;color:{MUTED};text-transform:uppercase;letter-spacing:.4px">{text}{extra}</div>'


def _big(label: str, value: Any, colour: str, light: str, badge: str = "") -> str:
    """Big percentage of the card (e.g. HoTo completion) with its bar."""
    return (
        _label(label, badge)
        + f'<div style="{FONT};font-size:24px;font-weight:800;color:{INK};margin:2px 0 6px">{pct(value)}</div>'
        + _bar(value, colour, light, 7)
    )


def _badge(p: float | None) -> str:
    if p is None:
        return ""
    text, fg, bg = ("ON TRACK", GOOD, "#dcfce7") if p >= 95 else ("WATCH", WARN, "#fef3c7") if p >= 80 else ("BEHIND", BAD, "#fee2e2")
    return f' <span style="background:{bg};color:{fg};border-radius:9px;padding:1px 7px;font-size:9px;letter-spacing:.3px">{text}</span>'


def _rows(rows: list[tuple[str, str, str, str]]) -> str:
    """label · value (+ small note under it) rows of a card; (label, value_html, note_html, value_colour)."""
    out = []
    for i, (label, value, note, colour) in enumerate(rows):
        top = f"border-top:1px solid {LINE};" if i else ""
        note_html = f'<div style="{FONT};font-size:10px;color:{MUTED};font-weight:400">{note}</div>' if note else ""
        out.append(
            f'<tr><td valign="middle" style="{top}padding:7px 0;{FONT};font-size:12px;color:{TEXT}">{label}</td>'
            f'<td valign="middle" align="right" style="{top}padding:7px 0;{FONT};font-size:14px;font-weight:700;color:{colour or INK};white-space:nowrap">{value}{note_html}</td></tr>'
        )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px">{"".join(out)}</table>'


def _trio(items: list[tuple[str, Any]]) -> str:
    """Target · Ready · Achieved side by side (one row)."""
    cells = "".join(
        f'<td width="33%" valign="top" style="padding:6px 0 0"><div style="{FONT};font-size:15px;font-weight:700;color:{INK}">{n(v)}</div>'
        f'<div style="{FONT};font-size:10px;color:{MUTED};white-space:nowrap">{cap}</div></td>'
        for cap, v in items
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed"><tr>{cells}</tr></table>'


def _of(done: Any, scope: Any) -> str:
    """"done / scope" – the scope smaller and muted."""
    if scope is None:
        return n(done)
    return f'{n(done)}<span style="font-size:11px;font-weight:600;color:{MUTED}"> / {n(scope)}</span>'


def _delta(d: Any, lower_is_better: bool = False) -> str:
    """▲ 67 (green when good) / ▼ 12 (red when bad) / ■ 0."""
    if d is None:
        return ""
    good = (d <= 0) if lower_is_better else (d >= 0)
    arrow = "▲" if d > 0 else "▼" if d < 0 else "■"
    return f'<span style="color:{GOOD if good else BAD};font-weight:700">{arrow} {n(abs(d))}</span>'


def _sub(text: str) -> str:
    """Small heading inside a card / a section (e.g. AMC GPs – MONTH-WISE)."""
    return f'<div style="{FONT};font-size:10px;font-weight:700;color:{MUTED};text-transform:uppercase;letter-spacing:.4px;margin-top:12px">{text}</div>'


def _heading(title: str, note: str = "") -> str:
    """Heading of a block below the circle cards (distribution, charts, month-wise table)."""
    note_html = f' <span style="font-weight:400;color:{MUTED}">{note}</span>' if note else ""
    return f'<div style="{FONT};font-size:13px;font-weight:700;color:{INK};padding:14px 5px 4px">{title}{note_html}</div>'


def _dot(colour: str) -> str:
    """A coloured dot as a text glyph – shown by every mail client and browser (an empty sized span is not)."""
    return f'<span style="color:{colour};font-size:14px;line-height:1">&#9679;</span>'


def _columns(points: list[dict[str, Any]], colour: str, light: str, height: int = 56) -> str:
    """Vertical bars with the value above and the label below; the running week / month ("current") solid, the
    earlier ones light."""
    if not points:
        return f'<div style="{FONT};font-size:11px;color:{MUTED}">No data</div>'
    top = max((p["value"] or 0) for p in points) or 1
    cols, labels = [], []
    for p in points:
        v = p["value"] or 0
        h = max(2, round(height * v / top))
        cur = bool(p.get("current"))
        cols.append(
            f'<td valign="bottom" align="center" style="padding:0 2px">'
            f'<div style="{FONT};font-size:10px;font-weight:{700 if cur else 400};color:{colour if cur else MUTED};margin-bottom:2px">{n(v)}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:{colour if cur else light};height:{h}px;line-height:{h}px;font-size:1px;border-radius:3px 3px 0 0">&nbsp;</td></tr></table></td>'
        )
        labels.append(f'<td align="center" style="{FONT};font-size:9px;color:{INK if cur else MUTED};font-weight:{700 if cur else 400};padding-top:3px;white-space:nowrap">{_e(p["label"])}</td>')
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed;margin-top:6px">'
        f'<tr style="height:{height + 16}px">{"".join(cols)}</tr><tr>{"".join(labels)}</tr></table>'
    )


def _change(points: list[dict[str, Any]], lower_is_better: bool = False) -> str:
    if len(points) >= 2 and points[-1]["value"] is not None and points[-2]["value"] is not None:
        return _delta(points[-1]["value"] - points[-2]["value"], lower_is_better)
    return ""


def _chart_card(name: str, colour: str, light: str, points: list[dict[str, Any]], lower_is_better: bool = False) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:10px;border-collapse:separate;background:#ffffff">'
        f'<tr><td style="padding:9px 10px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="{FONT};font-size:12px;font-weight:700;color:{INK}">{_dot(colour)} {_e(name)}</td>'
        f'<td align="right" style="{FONT};font-size:11px">{_change(points, lower_is_better)}</td></tr></table>'
        f"{_columns(points, colour, light)}</td></tr></table>"
    )


def _section(key: int | str, title: str, subtitle: str, body: str) -> str:
    num = key if isinstance(key, int) else 6
    subtitle = subtitle[:1].upper() + subtitle[1:]
    return (
        f'<tr><td style="padding:6px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:10px;border-collapse:separate;background:#ffffff;box-shadow:0 1px 3px rgba(16,24,40,.06)">'
        f'<tr><td style="padding:14px 11px 10px">{MARK}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 5px 4px"><tr>'
        f'<td width="30" valign="middle"><div style="{FONT};width:26px;height:26px;line-height:26px;border-radius:6px;background:{PRIMARY};color:#ffffff;font-size:13px;font-weight:700;text-align:center">{num}</div></td>'
        f'<td valign="middle" style="padding-left:9px"><span style="{FONT};font-size:15px;font-weight:700;color:{INK}">{_e(title)}</span>'
        f'<span style="{FONT};font-size:12px;color:{MUTED}">&nbsp;&nbsp;{subtitle}</span></td></tr></table>'
        f"{body}</td></tr></table></td></tr>"
    )


# ---------------------------------------------------------------- sections (the same for one or all circles)

Circle = tuple[dict[str, Any], str, str]  # (view, colour, light colour)


def _s1(cs: list[Circle]) -> str:
    """HoTo per circle: completion, Total GPs with Done / NP-Closed (as on the portal), blocks, GPs (done / active GPs),
    route km."""
    cards = []
    for v, c, lt in cs:
        h = v["hoto"]
        legend = " &nbsp;".join(
            f'<span style="white-space:nowrap">{_dot(dot)} {label} <b style="color:{INK}">{n(val)}</b></span>'
            for label, val, dot in (("Done", h["gps"], "#0ca30c"), ("NP / Closed", h.get("npClosed"), "#d03b3b"))
        )
        total = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px"><tr>'
                 f'<td style="{FONT};font-size:12px;color:{TEXT}">Total GPs</td>'
                 f'<td align="right" style="{FONT};font-size:14px;font-weight:700;color:{INK}">{n(h.get("total"))}</td></tr>'
                 f'<tr><td colspan="2" style="{FONT};font-size:10px;color:{MUTED};padding-top:3px">{legend}</td></tr></table>')
        cards.append(_card(_e(v["circle"]), c, _big("HoTo completion (GPs)", h["gpsPct"], c, lt) + total + _rows([
            ("HoTo Blocks", _of(h["blocks"], h["blocksScope"]), f"{pct(h['blocksPct'])} of blocks", ""),
            ("HoTo GPs", _of(h["gps"], h["gpsScope"]), f"{pct(h['gpsPct'])} of active GPs", ""),
            # only the handed-over route km (no "/ scope"); the share of the scope in the note
            ("Route km (RKM)", f'{n(h["rkm"])}<span style="font-size:11px;font-weight:600;color:{MUTED}"> RKM</span>', f"{pct(h['rkmPct'])} of route km", ""),
        ])))
    return _grid(cards)


def _s2(cs: list[Circle]) -> str:
    cards = []
    for v, c, lt in cs:
        a = v["amc"]
        cards.append(_card(_e(v["circle"]), c, _big("AMC conversion", a["pct"], c, lt) + _rows([
            ("AMC GPs (Total)", _of(a["gps"], a["gpsScope"]), f"{pct(a['pct'])} of revised", ""),
            ("Incremental GPs", n(a["incremental"]), "", ""),
            ("Scope Fibre (RKM)", n(a["rkmScope"]), "", ""),
            ("AMC Fibre (RKM)", n(a["rkm"]), f"{pct(a['rkmPct'])} of scope", ""),
        ]) + _sub("AMC GPs – month-wise") + _columns(a["months"], c, lt)))
    return _grid(cards)


def _s3(cs: list[Circle]) -> str:
    """One-time up per circle (no AMC month / week targets on this page): this month's target achievement, target · gap,
    last month MTD and this month MTD (the same days); then the month-wise table."""
    cards = []
    for v, c, lt in cs:
        o = v["oneTimeUp"]
        mon = (o["currentLabel"] or "").split(" ")[0]
        prev = (o["previousLabel"] or "").split(" ")[0]
        tgt_line = (f'<div style="{FONT};font-size:12px;color:{TEXT};margin-top:7px">Target <b>{n(o["target"])}</b> &nbsp;·&nbsp; Gap '
                    f'<b style="color:{BAD if (o["gap"] or 0) > 0 else GOOD}">{n(o["gap"])}</b></div>') if o["target"] is not None else (
                    f'<div style="{FONT};font-size:12px;color:{MUTED};margin-top:7px">No one-time-up target for {_e(mon)} in the data</div>')
        # the target achievement % and its bar, without the "<month> target achievement · WATCH" label line
        body = (f'<div style="{FONT};font-size:24px;font-weight:800;color:{INK};margin:0 0 6px">{pct(o["pct"])}</div>'
                + _bar(o["pct"], c, lt, 7) + tgt_line + _rows([
            (_e(o["previousLabel"]), n(o["previous"]), "", ""),
            (_e(o["currentLabel"]), n(o["current"]), f"{_delta(o['delta'])} vs {_e(prev)}" if o["delta"] is not None else "", ""),
        ]))
        cards.append(_card(_e(v["circle"]), c, body))
    return _grid(cards) + _month_table(cs)


def _month_table(cs: list[Circle]) -> str:
    """Month-wise one-time-up GPs: base month, full months, last month MTD vs this month MTD (same days), AMC / Non-AMC
    split of this month."""
    t0 = cs[0][0]["oneTimeUp"].get("table") or {}
    cols = t0.get("columns") or []
    if not cols:
        return _heading("Month-wise one-time-up GPs") + f'<div style="{FONT};font-size:11px;color:{MUTED};padding:0 5px">No month-wise data in the current file.</div>'
    th = f"{FONT};font-size:10px;font-weight:700;color:{MUTED};text-transform:uppercase;padding:7px 5px;background:#e6f2f9;border-bottom:1px solid {LINE}"
    td = f"{FONT};font-size:12px;color:{INK};padding:7px 5px;border-bottom:1px solid {LINE}"
    bg = {"amc": "background:#ecf8ef;", "nonAmc": "background:#fdf3ea;"}
    head = f'<td style="{th}">Circle</td>' + "".join(f'<td align="right" style="{th}">{_e(col["label"])}</td>' for col in cols)
    body = ""
    for v, c, _lt in cs:
        vals = (v["oneTimeUp"].get("table") or {}).get("values") or {}
        body += (f'<tr><td style="{td};font-weight:700;white-space:nowrap">{_dot(c)} {_e(v["circle"])}</td>'
                 + "".join(f'<td align="right" style="{td};{bg.get(col["key"], "")}{"font-weight:800;" if col.get("current") else ""}">{n(vals.get(col["key"]))}</td>' for col in cols)
                 + "</tr>")
    return (_heading("Month-wise one-time-up GPs", f"· {_e(t0.get('note', ''))}")
            + f'<div style="padding:0 5px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden">'
            f"<tr>{head}</tr>{body}</table></div>")


def _s4(cs: list[Circle]) -> str:
    cards = []
    for v, c, _lt in cs:
        u = v["uptime"]
        cards.append(_card(_e(v["circle"]), c, _rows([
            ("GPs above 98%", n(u["above98"]), f"{pct(u['above98Pct'])} of AMC", ""),
            ("GPs &lt;90% in penalty blocks", _of(u["below90"], u["penaltyGps"]), f"in {n(u['penaltyBlocks'])} blocks &lt;90%", BAD if u["below90"] else GOOD),
            ("GPs at 0%", n(u["atZero"]), "", BAD if u["atZero"] else GOOD),
            ("Penalty blocks", n(u["penaltyBlocks"]), "", BAD if u["penaltyBlocks"] else GOOD),
        ])))
    out = _grid(cards)

    # uptime distribution (MTD) – one bar per circle
    def dist_of(u: dict[str, Any]) -> list[dict[str, Any]]:
        return u.get("distributionMtd") or u["distribution"]

    u0 = cs[0][0]["uptime"]
    out += _heading(_dist_title(u0, cs[0][0]["oneTimeUp"]))
    legend = "".join(f'<td style="{FONT};font-size:11px;color:{TEXT};padding:0 14px 6px 0;white-space:nowrap">{_dot(col)} {_e(x["label"])}</td>'
                     for x, col in zip(dist_of(u0), DIST_COLOURS))
    rows = ""
    for v, c, _lt in cs:
        u = v["uptime"]
        dist = dist_of(u)
        total = sum(x["value"] for x in dist) or 1
        segs = "".join(
            f'<td width="{max(1, round(100 * x["value"] / total))}%" align="center" style="background:{col};height:20px;{FONT};font-size:10px;font-weight:700;color:{INK if col in DIST_DARK_TEXT else "#ffffff"}">'
            f'{round(100 * x["value"] / total) if 100 * x["value"] / total >= 8 else ""}{"%" if 100 * x["value"] / total >= 8 else ""}</td>'
            for x, col in zip(dist, DIST_COLOURS) if x["value"]
        ) or f'<td style="background:{LINE};height:20px">&nbsp;</td>'
        top = dist[0]["pct"] if dist else None
        fg, bg = (GOOD, "#dcfce7") if (top or 0) >= 80 else (WARN, "#fef3c7") if (top or 0) >= 50 else (BAD, "#fee2e2")
        rows += (
            f'<tr><td width="96" style="{FONT};font-size:12px;font-weight:700;color:{INK};padding:6px 0;white-space:nowrap">{_dot(c)} {_e(v["circle"])}</td>'
            f'<td style="padding:6px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>{segs}</tr></table></td>'
            f'<td width="86" align="right" style="padding:6px 0;white-space:nowrap"><span style="{FONT};font-size:10px;font-weight:700;color:{fg};background:{bg};border-radius:9px;padding:2px 7px">{pct(top)} &gt;98</span>'
            f'<div style="{FONT};font-size:10px;color:{MUTED};margin-top:2px">{n(u.get("distributionMtdGps", u["distributionGps"]))} GPs</div></td></tr>'
        )
    out += (f'<div style="padding:0 5px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>{legend}</tr></table>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></div>')

    # the weekly trends – one mini chart per circle
    out += _heading("AMC GPs with uptime &gt;98% – weekly", "· each week's own uptime, not MTD · higher is better · solid bar = latest week")
    out += _grid([_chart_card(v["circle"], c, lt, v["uptime"]["trendAbove98"]) for v, c, lt in cs])
    out += _heading("Blocks below 90% uptime – weekly", "· each week's own uptime, not MTD · lower is better")
    out += _grid([_chart_card(v["circle"], c, lt, v["uptime"]["trendBlocksBelow90"], lower_is_better=True) for v, c, lt in cs])
    return out


def _dist_title(u: dict[str, Any], o: dict[str, Any]) -> str:
    """Heading of the distribution: MTD with its days (e.g. "MTD, 1–25 Nov"), or the week when no MTD bands exist."""
    if u.get("distributionMtd"):
        return f"Uptime distribution – AMC GPs (MTD, {_e(o.get('range') or '')})"
    return f"Uptime distribution – AMC GPs ({_e(u['distributionWeek'])})"


def uptime_subtitle(v: dict[str, Any]) -> str:
    """The Uptime section says which figures are MTD and which are weekly (the two differ on purpose)."""
    return f"Tiles &amp; distribution: MTD ({_e(v['oneTimeUp'].get('range') or '')}) · charts: weekly, last {len(v['uptime']['trendAbove98'])} weeks"


def _s5(cs: list[Circle]) -> str:
    cards = []
    for v, c, _lt in cs:
        f = v["fieldForce"]
        cards.append(_card(_e(v["circle"]), c, _rows([
            ("FRT Count (O&amp;M)", n(f["frtCount"]), "", ""),
            ("FRT on Portal", n(f["onPortal"]), f"{pct(f['onPortalPct'])} on portal" if f["onPortalPct"] is not None else "", ""),
        ])))
    return _grid(cards)


def _s6(cs: list[Circle]) -> str:
    cards = []
    for v, c, _lt in cs:
        if v["remarks"]:
            items = "".join(f'<tr><td valign="top" style="{FONT};font-size:13px;color:{c};padding:3px 6px 3px 0">›</td>'
                            f'<td style="{FONT};font-size:12px;color:{INK};padding:3px 0">{_e(r)}</td></tr>' for r in v["remarks"])
            body = f'<table role="presentation" cellpadding="0" cellspacing="0">{items}</table>'
        else:
            body = f'<div style="{FONT};font-size:12px;color:{MUTED}">No open points.</div>'
        cards.append(_card(_e(v["circle"]), c, body))
    return _grid(cards)


def _week_note(v: dict[str, Any]) -> str:
    return f"{_e(v['week'])} ({_e(v['weekRange'])})" + ("" if v["weekComplete"] else " – week in progress, updates with every upload")


# ---------------------------------------------------------------- the page


LOGO_CID = "om-logo"
LOGO_FILE = Path(__file__).resolve().parent / "assets" / "om-logo.png"  # frontend/public/brand/pratap-logo.png, white margin cropped (240 x 90)


@lru_cache(maxsize=1)
def logo_bytes() -> bytes | None:
    try:
        return LOGO_FILE.read_bytes()
    except OSError:
        return None


def attach_logo(msg: Any) -> Any:
    """Embed the logo (cid:om-logo) in the e-mail's HTML part – an inline image, nothing loaded from the internet."""
    data = logo_bytes()
    part = msg.get_body(("html",))
    if data and part is not None:
        part.add_related(data, maintype="image", subtype="png", cid=f"<{LOGO_CID}>", disposition="inline")
    return msg


def _logo_src(inline: bool) -> str:
    """The full Pratap logo ("pratap – Carving Lives"): inside the file for the preview / download (works offline),
    "cid:" in the e-mail – attached inline by om_service (attach_logo), so it never counts towards the HTML size."""
    if inline:
        import base64

        data = logo_bytes()
        if data:
            return "data:image/png;base64," + base64.b64encode(data).decode()
    return f"cid:{LOGO_CID}"


def _header(title_line: str, as_of: dt.date, week_line: str, logo_src: str) -> str:
    """The portal page header: white card, brand line on top, hero surface, logo, title, DATA AS OF pill, week chip."""
    wordmark = (f'<td valign="middle" width="150" style="padding-right:18px;border-right:1px solid {LINE}">'
                f'<img src="{logo_src}" width="144" height="54" alt="Pratap – Carving Lives" style="display:block;border:0;outline:none;width:144px;height:54px"></td>')
    title = (f'<td valign="middle" style="padding:0 14px">'
             f'<div style="{FONT};font-size:11px;font-weight:600;color:{MUTED}">Daily MIS · BN3 O&amp;M</div>'
             f'<div style="{FONT};font-size:24px;font-weight:800;color:{PRIMARY};letter-spacing:-.3px;white-space:nowrap">O&amp;M Daily Dashboard</div>'
             f'<div style="{FONT};font-size:13px;font-weight:600;color:{HEADING};margin-top:1px">{title_line}</div></td>')
    pill = f"DATA AS OF {as_of:%d %b %Y}".upper()
    chips = (f'<td valign="middle" align="right" style="white-space:nowrap">'
             f'<div><span style="{FONT};display:inline-block;font-size:11px;font-weight:700;color:#0b6e2c;background:#e8f6ec;border:1px solid #b9e3c4;border-radius:14px;padding:5px 12px;letter-spacing:.4px">'
             f'<span style="display:inline-block;width:7px;height:7px;border-radius:4px;background:#0ca30c"></span>&nbsp; {pill}</span></div>'
             f'<div style="margin-top:6px"><span style="{FONT};display:inline-block;font-size:11px;font-weight:600;color:{HEADING};background:#ffffff;border:1px solid {LINE};border-radius:8px;padding:5px 10px">{week_line}</span></div></td>')
    return (
        f'<tr><td style="padding:0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate">'
        f'<tr><td style="height:4px;line-height:4px;font-size:1px;background:#0a8fc4;background-image:linear-gradient(90deg,#0f9a45 0%,#0a8fc4 55%,#0a6fa6 100%);border-radius:10px 10px 0 0">&nbsp;</td></tr>'
        f'<tr><td style="padding:16px 22px;background:#ffffff;background-image:linear-gradient(110deg,#ecf8f0 0%,#ffffff 45%,#e7f3fa 100%);border-bottom:1px solid {LINE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{wordmark}{title}{chips}</tr></table></td></tr></table></td></tr>'
    )


PAGE_WIDTH = 1600  # the All Circles page is designed at one width – it is scaled, never re-flowed
PAGE_MARGIN = 40  # body padding + frame border around it


def _frame_css(width: int) -> str:
    """Auto framing: the page keeps its layout on every screen and is scaled to fit.
      * phones / tablets: the viewport is the page width (<meta viewport>), so the device fits the whole page on screen;
      * narrower browser windows (laptops): CSS zoom steps shrink the whole frame so it fits the window width.
    Mail clients without <style> / zoom show the page at its full width (side scroll) – the layout itself is unchanged."""
    full = width + PAGE_MARGIN
    scrollbar = 20  # a vertical scrollbar takes this much of the window
    # steps only below the page width (never zoom in); each zoom fits the narrowest window of its step
    floors = [f for f in (1440, 1280, 1100, 960, 800, 640) if f < full] + [0]
    rules, top = [], full + scrollbar - 1
    for floor in floors:
        z = round((max(floor, 400) - scrollbar) / full - 0.005, 2)
        rules.append(f"@media screen and (max-width:{top}px){{.om-frame{{zoom:{z}}}}}")
        top = floor - 1
    return "<style>" + "".join(rules) + "</style>"


def _block(section_tr: str) -> str:
    """A section (<tr>…) as a block of a column."""
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{section_tr}</table>'


def _dashboard(views: list[dict[str, Any]], gen: str, width: int, logo_src: str) -> str:
    cs: list[Circle] = [(v, *_colours(v, i)) for i, v in enumerate(views)]
    first = views[0]
    as_of = dt.date.fromisoformat(first["dataAsOf"])
    o0 = first["oneTimeUp"]
    week_line = f"{_e(first['week'])} · {_e(first['weekRange'])}" + ("" if first["weekComplete"] else " · in progress")
    dots = " &nbsp;".join(f"{_dot(c)} {_e(v['circle'])}" for v, c, _lt in cs)
    pre = " · ".join(
        f"{v['circle']}: AMC {pct(v['amc']['pct'])}, one-time up {n(v['oneTimeUp']['current'])}, {n(v['uptime']['penaltyBlocks'])} blocks below 90%" for v in views
    )
    s1 = _section(1, "HoTo & Network Status", "Done / scope", _s1(cs))
    s2 = _section(2, "AMC Status", "GPs and fibre under AMC", _s2(cs))
    s3 = _section(3, "One-Time Up GPs", "Month to date vs last month", _s3(cs))
    s4 = _section(4, "Uptime Trend", uptime_subtitle(first), _s4(cs))
    s5 = _section(5, "Field Force", "FRT deployment", _s5(cs))
    s6 = _section("r", "Remarks & Open Points", "As updated by the circle teams", _s6(cs))
    defs = [
        f"<b>One-time up</b> – GPs with uptime &gt; 0 on at least one day ({_e(o0['range'])} vs {_e(o0['previousRange'])}).",
        "<b>Penalty blocks</b> – blocks whose mean AMC uptime is below 90%; GPs &lt;90% are counted inside these blocks.",
        "<b>WTD</b> – week to date: the week is still running and the figures update with every upload.",
    ]
    defs_html = (f'<div style="padding:6px"><div style="background:#ffffff;border:1px solid {LINE};border-radius:12px;padding:11px 14px">{MARK}{_label("Definitions")}'
                 + "".join(f'<div style="{FONT};font-size:11px;color:{TEXT};margin-top:4px;line-height:15px">{d}</div>' for d in defs) + "</div></div>")
    # two columns at a FIXED page width: the layout never squeezes; smaller screens scale the whole page (_frame_css)
    c1 = _block(s1) + _block(s3) + _block(s5) + _block(s6) + defs_html
    c2 = _block(s2) + _block(s4)
    rows = (
        '<tr><td style="padding:0 10px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="table-layout:fixed"><tr>'
        f'<td width="50%" valign="top">{c1}</td><td width="50%" valign="top">{c2}</td>'
        "</tr></table></td></tr>"
    )
    foot = (f'<tr><td style="padding:6px 22px 16px">{MARK}<div style="{FONT};font-size:11px;color:{MUTED}">Generated on {gen} from {_e(first["sourceFile"]) or "the active master data"}'
            f" · data as of {as_of:%d %b %Y} · system-generated – for data corrections contact the O&amp;M MIS team.</div></td></tr>")
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width={width + PAGE_MARGIN}">'
        f"<title>O&amp;M Daily Dashboard – All Circles</title>{_frame_css(width)}</head>"
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{_e(pre)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE}"><tr><td align="center" style="padding:16px 8px">'
        f'<table class="om-frame" role="presentation" width="{width}" cellpadding="0" cellspacing="0" style="width:{width}px;background:{FRAME};border-radius:12px;border:1px solid {LINE};border-collapse:separate">'
        f'{_header(f"All Circles &nbsp;·&nbsp; {dots}", as_of, week_line, logo_src)}<tr><td style="height:8px;font-size:1px">&nbsp;</td></tr>{rows}{foot}</table></td></tr></table></body></html>'
    ).replace(UID, unique_token())


def render(v: dict[str, Any], generated_at: dt.datetime | None = None, inline_logo: bool = False) -> tuple[str, str]:
    """(html, plain text) of one circle's O&M Daily Dashboard – the e-mail of the circle (app.mail.om_html_single, the
    All Circles style). inline_logo: the logo inside the HTML (preview / download); otherwise "cid:" (attach_logo)."""
    from .om_html_single import render_html

    gen = (generated_at or dt.datetime.now()).strftime("%d %b %Y %H:%M")
    return render_html(v, gen, inline_logo), text(v, gen)


def render_all(views: list[dict[str, Any]], generated_at: dt.datetime | None = None, inline_logo: bool = False) -> tuple[str, str]:
    """(html, plain text) of the All Circles page (preview / download and the All Circles mail) – the portal design.
    inline_logo: the logo inside the HTML (preview / download); otherwise "cid:" – the e-mail attaches it (attach_logo)."""
    if not views:
        raise ValueError("no circles")
    gen = (generated_at or dt.datetime.now()).strftime("%d %b %Y %H:%M")
    views = sorted(views, key=lambda v: -(v["hoto"]["gpsScope"] or 0))  # largest circle first (Rajasthan · Haryana · Assam)
    return _dashboard(views, gen, PAGE_WIDTH, _logo_src(inline_logo)), "\n\n".join(text(v, gen) for v in views)


def text(v: dict[str, Any], gen: str) -> str:
    """The same figures as plain text (mail clients without HTML)."""
    h, a, o, u, f = v["hoto"], v["amc"], v["oneTimeUp"], v["uptime"], v["fieldForce"]
    m, w = o["month"], o["week"]
    lines = [
        f"O&M Daily Dashboard – {v['circle']} Circle",
        f"Data as of {v['dataAsOf']} · {v['week']} ({v['weekRange']})",
        "",
        "1 · HoTo & Network Status",
        f"  HoTo Blocks: {n(h['blocks'])} / {n(h['blocksScope'])} ({pct(h['blocksPct'])})",
        f"  HoTo GPs:    {n(h['gps'])} / {n(h['gpsScope'])} ({pct(h['gpsPct'])})",
        f"  Route km:    {n(h['rkm'])} RKM ({pct(h['rkmPct'])} of route km)",
        "2 · AMC Status",
        f"  AMC GPs:     {n(a['gps'])} / {n(a['gpsScope'])} ({pct(a['pct'])}) · incremental {n(a['incremental'])}",
        f"  Fibre:       scope {n(a['rkmScope'])} RKM · AMC {n(a['rkm'])} RKM ({pct(a['rkmPct'])})",
        "  Month-wise:  " + " · ".join(f"{x['label']} {n(x['value'])}" for x in a["months"]),
        "3 · One-Time Up GPs & Target",
        f"  Target {n(o['target'])} · achievement {pct(o['pct'])} · gap {n(o['gap'])}",
        f"  One-time up GPs: {o['previousLabel']} {n(o['previous'])} → {o['currentLabel']} {n(o['current'])}",
        f"  AMC {m['label'] or 'month'}: target {n(m['target'])} · MTD ready {n(m['ready'])} · MTD achieved {n(m['achieved'])}",
        f"  AMC {w['label'] or 'week'}: target {n(w['target'])} · ready {n(w['ready'])} · achieved {n(w['achieved'])}",
        "4 · Uptime Trend",
        f"  GPs >98% (MTD): {n(u['above98'])} · GPs <90% in penalty blocks: {n(u['below90'])} / {n(u['penaltyGps'])}"
        f" · GPs at 0%: {n(u['atZero'])} · penalty blocks: {n(u['penaltyBlocks'])}",
        "  GPs >98% by week:   " + " · ".join(f"{x['label']} {n(x['value'])}" for x in u["trendAbove98"]),
        "  Blocks <90% by week: " + " · ".join(f"{x['label']} {n(x['value'])}" for x in u["trendBlocksBelow90"]),
        "5 · Field Force",
        f"  FRT count (O&M): {n(f['frtCount'])} · on portal: {n(f['onPortal'])}",
        "Remarks & Open Points",
        *([f"  › {r}" for r in v["remarks"]] or ["  No open points."]),
        "",
        f"Generated {gen} · weeks marked WTD are still in progress. System-generated mail.",
    ]
    return "\n".join(lines)
