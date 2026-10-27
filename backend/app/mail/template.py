"""E-mail templates: plain text with {{placeholders}}, rendered to a plain-text and an HTML part.

Safe by construction: the template is never executed (no Jinja / format strings). Literal text and every value are
HTML-escaped; only the table placeholders produce HTML, and that HTML is built here. Unknown placeholders are refused
when a template is saved, so a typo cannot reach a recipient. Table placeholders must stand on a line of their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Any

PH = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

TEXT_PLACEHOLDERS: dict[str, str] = {
    "recipient_name": "Name of the recipient",
    "recipient_role": "Area Manager / SME / COH / Dashboard user",
    "area": "Area the e-mail covers (state, business areas …)",
    "gps": "Number of GPs in the recipient's area",
    "data_date": "Date of the data (e.g. 23 Oct 2026)",
    "month": "Current month (e.g. Oct 2026)",
    "week": "Latest week (e.g. WK-44)",
    "week_range": "Dates of the latest week",
    "month_target": "GPs planned in the month",
    "mtd_target": "GPs due so far this month",
    "mtd_achieved": "GPs achieved so far this month",
    "mtd_pct": "Month-to-date achievement %",
    "overdue": "Planned GPs not yet achieved",
    "week_target": "GPs planned in the week",
    "week_achieved": "GPs achieved in the week",
    "week_pct": "Week achievement %",
    "breakdown_title": "“By block” for Area Managers, “By area manager” for SME / COH",
    "source_file": "Name of the data file",
}
TABLE_PLACEHOLDERS: dict[str, str] = {
    "summary_table": "Month and week figures in one table",
    "breakdown_table": "Block-wise table for Area Managers, area-manager-wise for everyone else",
    "block_table": "Block-wise table (blocks with a target, achievement or overdue GP)",
    "am_table": "Area-manager-wise table",
    "ba_table": "Business-area-wise table",
}
ALL_PLACEHOLDERS = {**TEXT_PLACEHOLDERS, **TABLE_PLACEHOLDERS}

FOOTER = "Target = GPs with a Planned Date in the period · Achieved = GPs with an Ach Date in the period, up to the data date · Overdue = planned on or before the data date and not yet achieved."

DEFAULT_TEMPLATES: list[dict[str, str]] = [
    {
        "key": "detailed",
        "name": "Detailed AMC Conversion report",
        "description": "Full report: month and week summary plus the block-wise / area-manager-wise table.",
        "subject": "AMC Conversion – {{area}} – {{month}} / {{week}} (data as of {{data_date}})",
        "body": (
            "Dear {{recipient_name}},\n\n"
            "Please find below the AMC Conversion status for {{area}} ({{gps}} GPs), based on data as of {{data_date}}.\n\n"
            "{{summary_table}}\n\n"
            "{{breakdown_title}}\n"
            "{{breakdown_table}}\n\n"
            "Kindly review the figures and ensure the planned conversions are completed on time.\n\n"
            "Regards,\nPratap Network Analytics"
        ),
    },
    {
        "key": "summary",
        "name": "Short summary",
        "description": "A few lines with the key numbers – suited to a daily e-mail.",
        "subject": "AMC Conversion summary – {{area}} – {{data_date}}",
        "body": (
            "Dear {{recipient_name}},\n\n"
            "AMC Conversion for {{area}} as of {{data_date}}:\n\n"
            "• {{month}}: {{mtd_achieved}} of {{mtd_target}} due GPs achieved ({{mtd_pct}}); month target {{month_target}} GPs.\n"
            "• {{week}} ({{week_range}}): {{week_achieved}} of {{week_target}} GPs achieved ({{week_pct}}).\n"
            "• Overdue: {{overdue}} GPs.\n\n"
            "Regards,\nPratap Network Analytics"
        ),
    },
    {
        "key": "action",
        "name": "Overdue – action required",
        "description": "Focus on overdue GPs, with the table to follow up – suited to a weekly reminder.",
        "subject": "Action required: {{overdue}} overdue AMC conversions – {{area}}",
        "body": (
            "Dear {{recipient_name}},\n\n"
            "As of {{data_date}}, {{overdue}} GPs in {{area}} were planned for AMC conversion on or before this date "
            "but are not yet achieved. Month-to-date achievement is {{mtd_pct}} ({{mtd_achieved}} of {{mtd_target}} due GPs).\n\n"
            "{{breakdown_title}}\n"
            "{{breakdown_table}}\n\n"
            "Please review the overdue GPs and share the revised completion dates.\n\n"
            "Regards,\nPratap Network Analytics"
        ),
    },
]


class TemplateError(ValueError):
    pass


def placeholders_in(text: str) -> list[str]:
    return [m.group(1) for m in PH.finditer(text or "")]


def validate(subject: str, body: str) -> None:
    if not subject.strip() or not body.strip():
        raise TemplateError("Subject and body are required")
    unknown = sorted({p for p in placeholders_in(subject) + placeholders_in(body) if p not in ALL_PLACEHOLDERS})
    if unknown:
        raise TemplateError(f"Unknown placeholder(s): {', '.join('{{' + u + '}}' for u in unknown)}")
    tables = sorted({p for p in placeholders_in(subject) if p in TABLE_PLACEHOLDERS})
    if tables:
        raise TemplateError(f"Tables cannot be used in the subject: {', '.join(tables)}")
    for line in body.splitlines():
        found = [p for p in placeholders_in(line) if p in TABLE_PLACEHOLDERS]
        if found and PH.sub("", line).strip():
            raise TemplateError(f"{{{{{found[0]}}}}} must stand on a line of its own")


# ---------------------------------------------------------------- values of one recipient


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _n(v: int) -> str:
    return f"{v:,}"


@dataclass
class Rendered:
    subject: str
    text: str
    html: str


SUMMARY_COLS = [("period", "Period", "l"), ("target", "Target", "r"), ("achieved", "Achieved", "r"), ("pct", "Achieved %", "r"), ("overdue", "Overdue", "r")]
TABLE_COLS = [
    ("name", "", "l"),
    ("circle", "State", "l"),
    ("gps", "GPs", "r"),
    ("monthTarget", "Month target", "r"),
    ("mtdTarget", "Due so far", "r"),
    ("mtdAchieved", "Achieved (MTD)", "r"),
    ("mtdPct", "MTD %", "r"),
    ("overdue", "Overdue", "r"),
    ("weekTarget", "Week target", "r"),
    ("weekAchieved", "Week achieved", "r"),
    ("weekPct", "Week %", "r"),
]
FIRST_COL = {"block_table": "Block", "am_table": "Area manager", "ba_table": "Business area"}


def values(figures: dict[str, Any], periods: dict[str, str], name: str, role: str, area: str, breakdown: str) -> dict[str, Any]:
    t = figures["total"]
    v: dict[str, Any] = {
        **periods,
        "recipient_name": name,
        "recipient_role": role,
        "area": area,
        "gps": _n(figures["gps"]),
        "month_target": _n(t["monthTarget"]),
        "mtd_target": _n(t["mtdTarget"]),
        "mtd_achieved": _n(t["mtdAchieved"]),
        "mtd_pct": _pct(t["mtdPct"]),
        "overdue": _n(t["overdue"]),
        "week_target": _n(t["weekTarget"]),
        "week_achieved": _n(t["weekAchieved"]),
        "week_pct": _pct(t["weekPct"]),
        "breakdown_title": "By block" if breakdown == "block" else "By area manager",
    }
    summary = [
        {"period": f"{periods['month']} (so far)", "target": _n(t["mtdTarget"]), "achieved": _n(t["mtdAchieved"]), "pct": _pct(t["mtdPct"]), "overdue": _n(t["overdue"])},
        {"period": f"{periods['month']} (whole month)", "target": _n(t["monthTarget"]), "achieved": _n(t["mtdAchieved"]), "pct": _pct(_ratio(t["mtdAchieved"], t["monthTarget"])), "overdue": ""},
        {"period": f"{periods['week']} ({periods['week_range']})", "target": _n(t["weekTarget"]), "achieved": _n(t["weekAchieved"]), "pct": _pct(t["weekPct"]), "overdue": ""},
    ]
    tables = {
        "summary_table": ("Period", SUMMARY_COLS, summary),
        "block_table": ("Block", TABLE_COLS, figures["block"]),
        "am_table": ("Area manager", TABLE_COLS, figures["am"]),
        "ba_table": ("Business area", TABLE_COLS, figures["ba"]),
    }
    tables["breakdown_table"] = tables["block_table"] if breakdown == "block" else tables["am_table"]
    v["_tables"] = tables
    v["_has_plan"] = figures["hasPlan"]
    return v


def _ratio(a: int, b: int) -> float | None:
    return round(a / b * 100, 2) if b else None


def _cell(row: dict[str, Any], key: str) -> str:
    v = row.get(key, "")
    if key in ("mtdPct", "weekPct"):
        return _pct(v)
    if isinstance(v, int):
        return _n(v)
    return str(v)


_TH = "padding:6px 9px;border:1px solid #d5dde7;background:#eef3f8;font-size:12px;text-align:{a};white-space:nowrap"
_TD = "padding:6px 9px;border:1px solid #e3e8ef;font-size:13px;text-align:{a};white-space:nowrap"


def _html_table(first: str, cols: list[tuple[str, str, str]], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p style="color:#5b6675;font-size:13px">No GP with a target, achievement or overdue in this period.</p>'
    align = {"l": "left", "r": "right"}
    head = "".join(f'<th style="{_TH.format(a=align[a])}">{escape(label or first)}</th>' for _, label, a in cols)
    body = "".join("<tr>" + "".join(f'<td style="{_TD.format(a=align[a])}">{escape(_cell(r, k))}</td>' for k, _, a in cols) + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;margin:6px 0 14px">{"<tr>" + head + "</tr>"}{body}</table>'


def _text_table(first: str, cols: list[tuple[str, str, str]], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No GP with a target, achievement or overdue in this period."
    heads = [label or first for _, label, _ in cols]
    data = [[_cell(r, k) for k, _, _ in cols] for r in rows]
    w = [max(len(h), *(len(d[i]) for d in data)) for i, h in enumerate(heads)]

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(w[i]) if cols[i][2] == "l" else c.rjust(w[i]) for i, c in enumerate(cells))

    return "\n".join([line(heads), line(["-" * x for x in w]), *(line(d) for d in data)])


def render(subject: str, body: str, v: dict[str, Any]) -> Rendered:
    tables = v["_tables"]

    def text_value(name: str) -> str:
        return str(v.get(name, ""))

    subj = PH.sub(lambda m: text_value(m.group(1)), subject)
    text_lines: list[str] = []
    html_parts: list[str] = []
    for line in body.splitlines():
        table = next((p for p in placeholders_in(line) if p in TABLE_PLACEHOLDERS), None)
        if table:
            first, cols, rows = tables[table]
            text_lines.append(_text_table(first, cols, rows))
            html_parts.append(_html_table(first, cols, rows))
            continue
        text_lines.append(PH.sub(lambda m: text_value(m.group(1)), line))
        pos, out = 0, []
        for m in PH.finditer(line):
            out.append(escape(line[pos : m.start()]))
            out.append(f"<b>{escape(text_value(m.group(1)))}</b>" if m.group(1) not in ("recipient_name", "breakdown_title") else escape(text_value(m.group(1))))
            pos = m.end()
        out.append(escape(line[pos:]))
        content = "".join(out)
        if line.strip() == "{{breakdown_title}}":
            html_parts.append(f'<h3 style="margin:14px 0 4px;font-size:15px">{content}</h3>')
        else:
            html_parts.append(f"{content}<br>" if content.strip() else "<br>")
    if not v.get("_has_plan", True):
        note = "Note: the active data file has no GP-wise AMC plan (Planned Date / Ach Date), so all figures are 0."
        text_lines.insert(0, note + "\n")
        html_parts.insert(0, f'<p style="color:#9a5b00">{escape(note)}</p>')
    text = "\n".join(text_lines) + f"\n\n{FOOTER}\nThis is an automatic e-mail from Pratap Network Analytics."
    html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;color:#1f2a37;font-size:14px;line-height:1.5">'
        + "".join(html_parts)
        + f'<p style="margin-top:18px;color:#5b6675;font-size:12px">{escape(FOOTER)}<br>This is an automatic e-mail from Pratap Network Analytics.</p></div>'
    )
    return Rendered(subj, text, html)
