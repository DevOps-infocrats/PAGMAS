"""One reusable, responsive HTML e-mail layout for every PAGMAS notification (ticket, daily progress, GP review, AMC
Conversion report) – the role-specific content is filled in by the caller; nothing here knows about a role.

    ┌ header ─ blue band: PAGMAS logo · product name ···· badge (Action Required / For Information)
    ├ title · reference · date
    ├ greeting · intro
    ├ KPI tiles            (only the figures the business logic supports – passed in by the caller)
    ├ summary              (label / value pairs: notification, ticket, status, priority, circle …)
    ├ sections             (titled tables / free HTML blocks built here or by the AMC report template)
    ├ action box           (what to do, who, stage, due date)
    ├ VIEW DASHBOARD       → https://pagmas.pramaanu.co.in/login (fixed: never localhost, never a token)
    └ footer

Email-safe by construction: table layout, inline CSS only, no scripts, no external fonts / images (the logo is an
inline CID attachment), every value HTML-escaped (only `Section.html` takes pre-built HTML – from code in this
project, never from user input). A plain-text version of the same content is produced for clients without HTML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from functools import lru_cache
from html import escape
from pathlib import Path

DASHBOARD_URL = "https://pagmas.pramaanu.co.in/login"
LOGO_CID = "pagmas-logo"
LOGO_FILE = Path(__file__).resolve().parent / "assets" / "pagmas-logo.png"  # copy of frontend/public/brand/pratap-wordmark.png
PRODUCT = "PAGMAS"
PRODUCT_SUB = "Pratap Network Analytics · GP-wise AMC Operations"

INK, MUTED, LINE, BG, CARD = "#1f2a37", "#5b6675", "#e3e8ef", "#f3f6f9", "#ffffff"
NAVY, BRAND = "#0c2a3d", "#0a78b0"
TONES = {  # text colour, soft background, border
    "info": ("#0a6a9c", "#e6f3fa", "#b9dcef"),
    "good": ("#0b7a2f", "#e8f6ec", "#bfe5ca"),
    "warning": ("#9a5b00", "#fdf4e1", "#f1d79d"),
    "critical": ("#b42323", "#fcebea", "#f1bdbd"),
    "neutral": ("#3c4a5a", "#f1f4f8", "#d8e0ea"),
}
FONT = "Segoe UI,Arial,Helvetica,sans-serif"


@dataclass
class Kpi:
    label: str
    value: str
    tone: str = "neutral"
    hint: str | None = None


@dataclass
class Table:
    head: list[str]
    rows: list[list[object]]
    right: set[int] = field(default_factory=set)  # right-aligned (numeric) columns
    empty: str = "Nothing to show."


@dataclass
class Section:
    title: str
    table: Table | None = None
    lines: list[str] = field(default_factory=list)  # plain paragraphs (escaped)
    html: str | None = None  # pre-built, already escaped HTML from this project's own code
    text: str | None = None  # plain-text version of `html`
    note: str | None = None


@dataclass
class Action:
    what: str
    who: str | None = None
    stage: str | None = None
    due: str | None = None
    steps: list[str] = field(default_factory=list)


@dataclass
class Email:
    title: str
    badge: str = "For Information"
    badge_tone: str = "info"
    greeting: str | None = None  # recipient name
    intro: list[str] = field(default_factory=list)
    reference: str | None = None  # e.g. ticket code
    date: str | None = None
    kpis: list[Kpi] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)
    highlight: tuple[str, str] | None = None  # (label, text) – e.g. a remark from the sender
    sections: list[Section] = field(default_factory=list)
    action: Action | None = None
    notes: list[str] = field(default_factory=list)
    footer: str | None = None


def _e(v: object) -> str:
    return escape("" if v is None else str(v))


# ---------------------------------------------------------------- HTML pieces


def _header(m: Email) -> str:
    fg = TONES.get(m.badge_tone, TONES["info"])[0]
    return (
        f'<tr><td bgcolor="{NAVY}" style="padding:16px 24px;background:{NAVY};background-image:linear-gradient(120deg,{NAVY},{BRAND})">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="vertical-align:middle;width:120px"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td bgcolor="#ffffff" style="background:#ffffff;border-radius:8px;padding:6px 10px">'
        f'<img src="cid:{LOGO_CID}" width="96" height="27" alt="Pratap" style="display:block;border:0;outline:none;height:27px;width:96px"></td></tr></table></td>'
        f'<td style="vertical-align:middle;padding-left:12px"><div style="font:700 15px/1.3 {FONT};color:#ffffff;letter-spacing:.3px">{PRODUCT}</div>'
        f'<div style="font:400 11px/1.4 {FONT};color:#cfe3ef">{_e(PRODUCT_SUB)}</div></td>'
        f'<td align="right" style="vertical-align:middle"><span style="display:inline-block;padding:4px 11px;border-radius:12px;background:#ffffff;'
        f'font:700 11px/1.3 {FONT};color:{fg};white-space:nowrap">{_e(m.badge)}</span></td>'
        "</tr></table></td></tr>"
        f'<tr><td style="height:4px;line-height:4px;font-size:0;background:#19bd4a;background-image:linear-gradient(90deg,#19bd4a,#0a8fc4)">&nbsp;</td></tr>'
    )


def _kpis(kpis: list[Kpi]) -> str:
    if not kpis:
        return ""
    per_row = 4 if len(kpis) == 4 else 3
    cells = []
    for k in kpis[:6]:
        fg, bg, bd = TONES.get(k.tone, TONES["neutral"])
        cells.append(
            f'<td class="kpi" style="padding:4px;vertical-align:top" width="{100 // min(len(kpis), per_row)}%">'
            f'<div style="background:{bg};border:1px solid {bd};border-radius:8px;padding:10px 12px">'
            f'<div style="font:700 10.5px/1.3 {FONT};color:{fg};text-transform:uppercase;letter-spacing:.4px">{_e(k.label)}</div>'
            f'<div style="font:700 22px/1.25 {FONT};color:{INK};margin-top:2px">{_e(k.value)}</div>'
            + (f'<div style="font:400 11px/1.35 {FONT};color:{MUTED};margin-top:1px">{_e(k.hint)}</div>' if k.hint else "")
            + "</div></td>"
        )
    rows = [cells[i : i + per_row] for i in range(0, len(cells), per_row)]
    body = "".join("<tr>" + "".join(r) + "</tr>" for r in rows)
    return f'<tr><td style="padding:6px 20px 4px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{body}</table></td></tr>'


def _summary(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return ""
    cells = "".join(
        f'<tr><td style="padding:6px 10px;font:400 12.5px/1.4 {FONT};color:{MUTED};width:38%;border-bottom:1px solid {LINE};vertical-align:top">{_e(k)}</td>'
        f'<td style="padding:6px 10px;font:600 12.5px/1.4 {FONT};color:{INK};border-bottom:1px solid {LINE};vertical-align:top">{_e(v)}</td></tr>'
        for k, v in pairs
    )
    return (
        f'<tr><td style="padding:10px 24px 4px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden">{cells}</table></td></tr>'
    )


def _table_html(t: Table) -> str:
    if not t.rows:
        return f'<p style="margin:4px 0 0;font:400 12.5px/1.5 {FONT};color:{MUTED}">{_e(t.empty)}</p>'
    th = "".join(
        f'<th align="{"right" if i in t.right else "left"}" style="padding:7px 9px;background:#eef3f8;border-bottom:1px solid #d5dde7;'
        f'font:700 11px/1.3 {FONT};color:#3c4a5a;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap">{_e(h)}</th>'
        for i, h in enumerate(t.head)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td align="{"right" if i in t.right else "left"}" style="padding:6px 9px;border-bottom:1px solid {LINE};font:400 12.5px/1.4 {FONT};color:{INK};'
            f'{"white-space:nowrap;" if i in t.right or len(str(v)) < 24 else ""}">{_e(v)}</td>'
            for i, v in enumerate(row)
        )
        + "</tr>"
        for row in t.rows
    )
    return (
        f'<div style="overflow-x:auto"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden"><tr>{th}</tr>{body}</table></div>'
    )


def _section(s: Section) -> str:
    inner = "".join(f'<p style="margin:0 0 8px;font:400 13.5px/1.55 {FONT};color:{INK}">{_e(x)}</p>' for x in s.lines)
    if s.html:
        inner += f'<div style="font:400 13.5px/1.55 {FONT};color:{INK}">{s.html}</div>'
    if s.table is not None:
        inner += _table_html(s.table)
    if s.note:
        inner += f'<p style="margin:6px 0 0;font:400 11.5px/1.45 {FONT};color:{MUTED}">{_e(s.note)}</p>'
    return f'<tr><td style="padding:14px 24px 2px"><div style="font:700 13px/1.4 {FONT};color:{NAVY};margin:0 0 6px">{_e(s.title)}</div>{inner}</td></tr>'


def _action(a: Action) -> str:
    fg, bg, bd = TONES["warning"]
    meta = " · ".join(x for x in (f"Responsible: {a.who}" if a.who else "", f"Stage: {a.stage}" if a.stage else "", f"Due: {a.due}" if a.due else "") if x)
    steps = "".join(f'<li style="margin:2px 0">{_e(x)}</li>' for x in a.steps)
    return (
        f'<tr><td style="padding:14px 24px 2px"><div style="background:{bg};border:1px solid {bd};border-left:4px solid {fg};border-radius:8px;padding:10px 14px">'
        f'<div style="font:700 12px/1.4 {FONT};color:{fg};text-transform:uppercase;letter-spacing:.4px">Action required</div>'
        f'<div style="font:600 13.5px/1.5 {FONT};color:{INK};margin-top:2px">{_e(a.what)}</div>'
        + (f'<div style="font:400 12px/1.5 {FONT};color:{MUTED};margin-top:2px">{_e(meta)}</div>' if meta else "")
        + (f'<ul style="margin:6px 0 0 18px;padding:0;font:400 12.5px/1.5 {FONT};color:{INK}">{steps}</ul>' if steps else "")
        + "</div></td></tr>"
    )


def _cta() -> str:
    return (
        '<tr><td align="center" style="padding:20px 24px 6px">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td align="center" bgcolor="{BRAND}" style="border-radius:6px;background:{BRAND}">'
        f'<a href="{DASHBOARD_URL}" target="_blank" rel="noopener" style="display:inline-block;padding:10px 26px;font:700 13px/1.2 {FONT};color:#ffffff;'
        'text-decoration:none;letter-spacing:.6px;border-radius:6px">VIEW DASHBOARD</a></td></tr></table>'
        f'<div style="font:400 11px/1.5 {FONT};color:{MUTED};margin-top:6px">or open <a href="{DASHBOARD_URL}" style="color:{BRAND}">{DASHBOARD_URL}</a></div>'
        "</td></tr>"
    )


def render(m: Email) -> tuple[str, str]:
    """(html, plain text) of the e-mail."""
    title = (
        f'<tr><td style="padding:16px 24px 2px"><div style="font:700 19px/1.3 {FONT};color:{NAVY}">{_e(m.title)}</div>'
        + (f'<div style="font:400 12px/1.5 {FONT};color:{MUTED};margin-top:2px">{_e(" · ".join(x for x in (m.reference, m.date) if x))}</div>' if (m.reference or m.date) else "")
        + "</td></tr>"
    )
    intro = "".join(f'<p style="margin:0 0 8px;font:400 13.5px/1.55 {FONT};color:{INK}">{_e(x)}</p>' for x in m.intro)
    greet = f'<p style="margin:0 0 8px;font:400 13.5px/1.55 {FONT};color:{INK}">Dear <b>{_e(m.greeting)}</b>,</p>' if m.greeting else ""
    body_intro = f'<tr><td style="padding:10px 24px 2px">{greet}{intro}</td></tr>' if (greet or intro) else ""
    hl = ""
    if m.highlight:
        fg, bg, bd = TONES["info"]
        hl = (
            f'<tr><td style="padding:8px 24px 2px"><div style="background:{bg};border:1px solid {bd};border-left:4px solid {fg};border-radius:8px;padding:9px 14px">'
            f'<div style="font:700 12px/1.4 {FONT};color:{fg}">{_e(m.highlight[0])}</div>'
            f'<div style="font:400 13px/1.55 {FONT};color:{INK};margin-top:2px;white-space:pre-line">{_e(m.highlight[1])}</div></div></td></tr>'
        )
    notes = "".join(f'<p style="margin:0 0 4px;font:400 11.5px/1.5 {FONT};color:{MUTED}">{_e(x)}</p>' for x in m.notes)
    footer = (
        f'<tr><td style="padding:16px 24px 18px;border-top:1px solid {LINE};background:#fafbfc">{notes}'
        f'<p style="margin:6px 0 0;font:400 11px/1.5 {FONT};color:{MUTED}">{_e(m.footer or "This is an automatic e-mail from PAGMAS – Pratap Network Analytics. Please do not reply.")}</p></td></tr>'
    )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting"><title>' + _e(m.title) + "</title>"
        "<style>@media only screen and (max-width:620px){.wrap{width:100%!important}.kpi{display:block!important;width:100%!important}}</style></head>"
        f'<body style="margin:0;padding:0;background:{BG}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG}"><tr><td align="center" style="padding:18px 10px">'
        f'<table role="presentation" class="wrap" width="680" cellpadding="0" cellspacing="0" border="0" style="width:680px;max-width:680px;background:{CARD};border:1px solid {LINE};border-radius:10px;border-collapse:separate;overflow:hidden">'
        + _header(m)
        + title
        + body_intro
        + _kpis(m.kpis)
        + _summary(m.summary)
        + hl
        + "".join(_section(s) for s in m.sections)
        + (_action(m.action) if m.action else "")
        + _cta()
        + footer
        + "</table></td></tr></table></body></html>"
    )
    return html, text(m)


def _text_table(t: Table) -> str:
    if not t.rows:
        return t.empty
    rows = [[str(c) for c in t.head], *[["" if v is None else str(v) for v in r] for r in t.rows]]
    w = [min(40, max(len(r[i]) for r in rows)) for i in range(len(t.head))]
    out = []
    for n, r in enumerate(rows):
        out.append("  ".join((c[:40].rjust(w[i]) if i in t.right else c[:40].ljust(w[i])) for i, c in enumerate(r)).rstrip())
        if n == 0:
            out.append("  ".join("-" * x for x in w))
    return "\n".join(out)


def text(m: Email) -> str:
    out = [f"{PRODUCT} – {m.title}"]
    if m.reference or m.date:
        out.append(" · ".join(x for x in (m.reference, m.date) if x))
    out.append("")
    if m.greeting:
        out += [f"Dear {m.greeting},", ""]
    out += [*m.intro, ""] if m.intro else []
    if m.kpis:
        out += [" · ".join(f"{k.label}: {k.value}" for k in m.kpis), ""]
    out += [f"{k}: {v}" for k, v in m.summary] + ([""] if m.summary else [])
    if m.highlight:
        out += [f"{m.highlight[0]}:", m.highlight[1], ""]
    for s in m.sections:
        out += [s.title.upper(), *s.lines]
        if s.text:
            out.append(s.text)
        if s.table is not None:
            out.append(_text_table(s.table))
        if s.note:
            out.append(s.note)
        out.append("")
    if m.action:
        a = m.action
        out += ["ACTION REQUIRED: " + a.what] + [x for x in (f"Responsible: {a.who}" if a.who else "", f"Stage: {a.stage}" if a.stage else "", f"Due: {a.due}" if a.due else "") if x]
        out += [f"- {x}" for x in a.steps] + [""]
    out += [f"VIEW DASHBOARD: {DASHBOARD_URL}", "", *m.notes, m.footer or "This is an automatic e-mail from PAGMAS – Pratap Network Analytics. Please do not reply."]
    return "\n".join(out)


@lru_cache(maxsize=1)
def _logo() -> bytes | None:
    try:
        return LOGO_FILE.read_bytes()
    except OSError:
        return None


def attach_logo(msg: EmailMessage) -> EmailMessage:
    """Embed the logo (cid:pagmas-logo) in the HTML part – shown without loading anything from the internet."""
    data = _logo()
    part = msg.get_body(("html",))
    if data and part is not None:
        part.add_related(data, maintype="image", subtype="png", cid=f"<{LOGO_CID}>", disposition="inline")  # inline image, not an attachment
    return msg


def message(to: list[str] | str, subject: str, m: Email) -> EmailMessage:
    """A ready EmailMessage (plain text + HTML + inline logo) – attachments can be added afterwards."""
    from .smtp import build_message

    html, plain = render(m)
    return attach_logo(build_message(to, subject, plain, html))
