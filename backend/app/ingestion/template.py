"""PAGMAS master data upload: which columns an upload needs, the structure check that runs BEFORE the file is read,
and the downloadable templates – one source of truth for all three, so they can never disagree.

An upload is ONE workbook ("Master Data … Daily track") with two data sheets: "GP Wise Data" and "Master Block".

Three column buckets per sheet. Columns are found by their header NAME, never by position, so any order works:

  REQUIRED      must exist; a missing one rejects the file and the message names it. Why: the dashboard, the tickets
                and the e-mails are built from them (location, AMC status, plan, Area Manager, block GP counts).
  OPTIONAL      known columns that may be in the sheet: read when present, blank when absent – never a reason to
                reject (the dashboard shows NA where it would use one).
  TIME-VARYING  day / week / month availability, recognised by PATTERN – a real date, "W-46" with its 7-day range in
                the row above, "Nov'26 (AMC)", "W46 Avail", "Nov Avg Avail TD" … A new day, week, month or year needs
                no change here, and a file with only the current week or month is fine (earlier periods are kept from
                earlier uploads, see history.py). Never a reason to reject.
  anything else ignored and reported as "not used".

Header names are compared ignoring case, spaces and punctuation ("AMC/Incremental" = "AMC / Incremental"); names an
admin added under Data Operations → Column names are accepted too. Nothing is renamed automatically: a missing
required column only gets a "similar column in the file" hint, so a wrong column can never feed a field.

What is checked here (structure only, fail fast, nothing is written): sheet found → header row found → every REQUIRED
column present (and not twice) → at least one availability period in GP Wise Data. Row values (blank is never 0,
dates, 0–100 %, duplicate GP / Block codes …) are checked by the importer itself (parser.py) – each problem with its
Excel row – because only the importer knows how a value is read.
"""

from __future__ import annotations

import datetime as dt
import difflib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .workbook import as_date, is_blank, norm

TEMPLATE_HINT = (
    "Download the PAGMAS template: Section A lists the required columns (exact names, they must be present); Section B "
    "shows example day / week / month columns – add as many as you have, they are never the reason a file is rejected."
)
MAX_PROBLEMS = 500  # problems listed per upload (all are counted)
D = dt.date


# ---------------------------------------------------------------- the columns


@dataclass(frozen=True)
class Col:
    name: str  # the name in the BSNL workbook (shown in the template and in messages)
    field: str | None = None  # importer field (column_map.py) – its built-in and admin-added names are accepted too
    fmt: str = "text"  # text | int | num | date – only for the template's cell format
    example: tuple[Any, Any] = (None, None)  # the template's two example rows
    why: str = ""  # what the dashboard uses it for (Read Me)


# GP Wise Data – REQUIRED: what the dashboard, the tickets and the e-mails cannot work without.
GP_REQUIRED: tuple[Col, ...] = (
    Col("Circle", "circle", example=("RAJASTHAN", "HARYANA"), why="circle of the GP – every view and user area"),
    Col("BA", "ba", example=("Jodhpur", "Ambala"), why="BA-wise views and AMC e-mails"),
    Col("DISTRICT", "district", example=("JODHPUR", "AMBALA"), why="district drill-down"),
    Col("BLOCK", "block_name", example=("BAP", "BARARA"), why="block drill-down"),
    Col("Block Code", "block_code", "int", (722, 501), "block of the GP"),
    Col("GP", "gp_name", example=("EXAMPLE GP One", "EXAMPLE GP Two"), why="GP name"),
    Col("GP Code", "gp_code", "int", (999901, 999902), "the GP's key – one row per GP code"),
    Col("GP Type", "gp_type", example=("Existing", "New"), why="existing / new GP"),
    Col("TOTAL RKM", "total_rkm", "num", (11.38, 4.2), "route km KPIs (blank = not reported, never 0)"),
    Col("HOTO Date", "hoto_date", "date", (D(2026, 5, 18), D(2026, 8, 1)), "HOTO status and dates (blank = no HOTO yet)"),
    Col("Letter submission date AMC Incremental", "letter_date", "date", (D(2026, 9, 10), None), "letter submission of the AMC / incremental GP"),
    Col("AMC / Incremental", "amc_category", example=("Incremental", None), why="AMC or Incremental (blank = not under AMC)"),
    Col("AMC Date", "amc_date", "date", (D(2026, 9, 19), None), "AMC start – AMC availability counts from this date"),
    Col("AM Name", "am_name", example=("Example AM", "Example AM 2"), why="Area Manager – tickets, AM e-mails and reports"),
    Col("5% Contractual Incremental+ Additional AMC", "plan_category", example=("Additional Plan", None), why="AMC conversion plan category"),
    Col("Planned Date", "planned_date", "date", why="AMC conversion plan – planned date"),
    Col("Ach Date", "ach_date", "date", why="AMC conversion plan – achieved date"),
)

# GP Wise Data – OPTIONAL: read when present (NA on the dashboard when absent), or only reference columns.
GP_OPTIONAL: tuple[Col, ...] = (
    Col("New Block Code post BoQ"),
    Col("New Block Name post BoQ"),
    Col("Block Changed"),
    Col("Block HoTo Status", "block_hoto_status", why="reconciliation with the O&M key numbers"),
    Col("LOCATION CODE", "location_code", why="GP details"),
    Col("Converted to NP & Closed", "np_status", why="GP converted to NP / closed (blank = in service)"),
    Col("Phase", "phase", why="GP details"),
    Col("OLT Location", "olt_location", why="GP details"),
    Col("BBNL Live KM", "bbnl_km", "num", why="BBNL route km (NA when the column is absent)"),
    Col("BSNL Live KM", "bsnl_km", "num", why="BSNL route km (NA when the column is absent)"),
    Col("LMS /AMC Date", "lms_amc_date", "date", why="GP details"),
    Col("Lot wise", "lot", why="GP details"),
    Col("<50 % Availability Last 4 M"),
    Col("Current Status", "plan_status", why="AMC conversion plan"),
    Col("Letter Status", "plan_letter_status", why="AMC conversion plan"),
    Col("Letter submission Date", "plan_letter_date", "date", why="AMC conversion plan"),
    Col("Approval Status", "plan_approval_status", why="AMC conversion plan"),
    Col("FRT Code"),
    Col("Name of splicer"),
    Col("Splicer Contact No."),
    Col("FE Name"),
    Col("FE Contact No"),
    Col("AM Contact No"),
    Col("SHQ Spoc"),
    Col("SHQ Spoc  Contact No"),
    Col("Block Priority"),
)

# Master Block – REQUIRED: the block identity and the GP counts the dashboard shows per block.
MB_REQUIRED: tuple[Col, ...] = (
    Col("State", "state", example=("Rajasthan", "Haryana"), why="state of the block"),
    Col("BA", example=("Jodhpur", "Ambala"), why="BA of the block"),
    Col("District", example=("JODHPUR", "AMBALA"), why="district of the block"),
    Col("Block Name", "block_name", example=("BAP", "BARARA"), why="block name"),
    Col("Block Code", "block_code", "int", (722, 501), "the block's key – one row per block code"),
    Col("HOTO Done Date", fmt="date", example=(D(2026, 5, 1), D(2026, 6, 15)), why="HOTO date of the block"),
    Col("Total GP Count", "total_gp_count", "int", (41, 35), "GPs of the block"),
    Col("Existing GPs", "existing_gps", "int", (33, 35), "existing GPs of the block"),
    Col("New GPs", "new_gps", "int", (8, 0), "new GPs of the block"),
)
MB_OPTIONAL: tuple[Col, ...] = (
    Col("FRT CODE"),
    Col("HOTO Done GPs"),
    Col("AMC GP GPs"),
    Col("Non AMC Count"),
    Col("BSNL Existing RKM"),
    Col("BBNL Existing RKM"),
    Col("Total RKM"),
    Col("Lot Wise"),
    Col("AMC"),
    Col("Incremental"),
    Col("Achieved"),
    Col("Shortfall / Penalty"),
    Col("Target Week"),
    Col("Target Date"),
    Col("Penalty Date"),
    Col("Block Status", "block_status"),
)

# ---------------------------------------------------------------- time-varying columns (patterns, never fixed names)

MONTH_WORD = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
RE_W = re.compile(r"^w-?\s*(\d{1,2})$")  # GP sheet weekly availability: W-46
RE_AMC_MONTH = re.compile(rf"^{MONTH_WORD}\s*'\s*(\d{{2}})\s*\(amc\)$")  # Nov'26 (AMC)
RE_GP_STATUS = re.compile(rf"^(?:{MONTH_WORD}|wk-?\s*\d{{1,2}})$")  # monthly / weekly status texts (not availability)
RE_MB_MONTH = re.compile(rf"^({MONTH_WORD})\s+(?:avg\s+)?avail(?:\s+td)?$")  # Nov Avail · Nov Avg Avail · Nov Avg Avail TD
RE_MB_WEEK = re.compile(r"^w-?\s*(\d{1,2})\s+avail$")  # W46 Avail
RE_MB_TARGET = re.compile(rf"^(?:{MONTH_WORD}\s+.*target|gap\s+{MONTH_WORD}.*|{MONTH_WORD}\s+gap)$")  # Nov 5% Inc. Target · GAP Nov …


def loose(text: Any) -> str:
    """Header key ignoring case, spaces and punctuation ('AMC/Incremental' = 'AMC / Incremental')."""
    return re.sub(r"[^0-9a-z%<]", "", norm(text))


def _header_date(v: Any) -> dt.date | None:
    """A header cell that is a real date (or date text) – never a plain number next to the header."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return None
    return as_date(v)


def gp_period(text: str) -> str | None:
    if RE_W.match(text):
        return "week"
    if RE_AMC_MONTH.match(text):
        return "amcMonth"
    if RE_GP_STATUS.match(text):
        return "status"
    return None


def mb_period(text: str) -> str | None:
    if RE_MB_WEEK.match(text):
        return "week"
    if RE_MB_MONTH.match(text):
        return "month"
    if RE_MB_TARGET.match(text):
        return "target"
    return None


# ---------------------------------------------------------------- check result


@dataclass
class Problem:
    sheet: str
    row: int | None
    column: str | None
    message: str
    severity: str = "error"  # error (rejects the file) | warning | info

    def json(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "row": self.row, "column": self.column, "severity": self.severity, "message": self.message}


@dataclass
class SheetColumns:
    """What the check found in one sheet – shown in the upload report."""

    sheet: str
    found: bool = False
    header_row: int | None = None  # Excel row
    required: list[dict[str, Any]] = field(default_factory=list)  # {name, header (as in the file) or None, hint}
    optional_present: list[str] = field(default_factory=list)
    optional_absent: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    periods: dict[str, int] = field(default_factory=dict)

    @property
    def missing(self) -> list[dict[str, Any]]:
        return [r for r in self.required if r["header"] is None]

    def json(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "found": self.found,
            "headerRow": self.header_row,
            "required": self.required,
            "requiredOk": self.found and not self.missing,
            "optionalPresent": self.optional_present,
            "optionalAbsent": self.optional_absent,
            "unused": self.unused,
            "periods": self.periods,
        }


@dataclass
class Check:
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    sheets: list[SheetColumns] = field(default_factory=list)

    def add(self, p: Problem) -> None:
        if p.severity == "error":
            self.error_count += 1
            if len(self.errors) < MAX_PROBLEMS:
                self.errors.append(p)
        else:
            self.warning_count += 1
            if len(self.warnings) < MAX_PROBLEMS:
                self.warnings.append(p)

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def message(self) -> str:
        """The rejection message: the real reason (the missing required columns) first."""
        missing = [(s.sheet, m["name"]) for s in self.sheets for m in s.missing if s.header_row is not None]
        parts = []
        if missing:
            by: dict[str, list[str]] = {}
            for sheet, name in missing:
                by.setdefault(sheet, []).append(name)
            parts.append("Missing required column(s) – " + "; ".join(f"{sheet}: {', '.join(names)}" for sheet, names in by.items()) + ".")
        other = [p.message for p in self.errors if not p.message.startswith("Missing required column")]
        parts += [m if m.endswith(".") else m + "." for m in other[:3]]
        if len(other) > 3:
            parts.append(f"(+{len(other) - 3} more)")
        parts.append("The file was rejected only because of the required columns / sheets above – day, week and month columns are never a reason to reject.")
        return " ".join(parts)


# ---------------------------------------------------------------- the check


def _col(c: int) -> str:
    s, c = "", c + 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _names(col: Col, aliases: dict[str, tuple[str, ...]]) -> set[str]:
    out = {loose(col.name)}
    if col.field:
        out |= {loose(a) for a in aliases.get(col.field, ())}
    return out


def _find_header(grid: list[list[Any]], anchors: tuple[Col, ...], aliases: dict[str, tuple[str, ...]]) -> int | None:
    want = [_names(a, aliases) for a in anchors]
    for i, row in enumerate(grid[:15]):
        cells = {loose(c) for c in row if not is_blank(c)}
        if all(cells & w for w in want):
            return i
    return None


def _scan(sheet: str, grid: list[list[Any]], required: tuple[Col, ...], optional: tuple[Col, ...], aliases: dict[str, tuple[str, ...]], period_of, check: Check) -> SheetColumns:
    """Header row → every column in a bucket: required / optional / time-varying / not used."""
    rep = SheetColumns(sheet, found=True)
    hdr = _find_header(grid, required[:1] + tuple(c for c in required if c.field in ("gp_code", "block_code")), aliases)
    if hdr is None:
        anchors = [required[0].name] + [c.name for c in required if c.field in ("gp_code", "block_code")]
        rep.required = [{"name": c.name, "header": None, "hint": None} for c in required]
        check.add(Problem(sheet, None, None, f"Header row not found: no row in the first 15 has both '{anchors[0]}' and '{anchors[1]}' (required columns)"))
        return rep
    rep.header_row = hdr + 1
    header = grid[hdr]
    lookup: dict[str, Col] = {}
    for col in (*required, *optional):
        for k in _names(col, aliases):
            lookup.setdefault(k, col)
    hits: dict[str, list[int]] = {}
    unused: list[tuple[int, str]] = []
    periods: Counter = Counter()
    for c, h in enumerate(header):
        if is_blank(h):
            continue
        if _header_date(h):
            periods["date"] += 1
            continue
        if isinstance(h, (int, float)) and not isinstance(h, bool):
            continue  # summary numbers next to the header are not columns
        if (col := lookup.get(loose(h))) is not None:
            hits.setdefault(col.name, []).append(c)
            continue
        if (g := period_of(norm(h))) is not None:
            periods[g] += 1
            continue
        unused.append((c, str(h).strip()))
    texts = [t for _, t in unused]
    for col in required:
        cols = hits.get(col.name)
        hint = None
        if not cols:
            best = difflib.get_close_matches(loose(col.name), [loose(t) for t in texts], n=1, cutoff=0.6)
            hint = next((t for t in texts if loose(t) == best[0]), None) if best else None
            check.add(Problem(sheet, rep.header_row, col.name, f"Missing required column: {col.name}" + (f" – the file has '{hint}' (similar); rename it to '{col.name}' or ask the admin to add it under Column names" if hint else "")))
        elif len(cols) > 1:
            check.add(Problem(sheet, rep.header_row, col.name, f"Duplicate required column: {col.name} (columns {', '.join(_col(x) for x in cols)}) – keep only one"))
        rep.required.append({"name": col.name, "header": str(header[cols[0]]).strip() if cols else None, "hint": hint})
    for col in optional:
        cols = hits.get(col.name)
        (rep.optional_present if cols else rep.optional_absent).append(col.name)
        if cols and len(cols) > 1:
            check.add(Problem(sheet, rep.header_row, col.name, f"Duplicate column: {col.name} (columns {', '.join(_col(x) for x in cols)}) – the first one is read", "warning"))
    rep.unused = texts
    rep.periods = dict(periods)
    return rep


def validate_master(path: Path) -> Check:
    """Structure check of a master data workbook (nothing is written). Errors = the file must be rejected."""
    from .column_map import load_column_map, resolve_sheet
    from .workbook import open_workbook

    check = Check()
    wb = open_workbook(path)
    cmap = load_column_map()
    for key, label, req, opt, aliases, period_of in (
        ("gp", "GP Wise Data", GP_REQUIRED, GP_OPTIONAL, cmap.gp, gp_period),
        ("masterBlock", "Master Block", MB_REQUIRED, MB_OPTIONAL, cmap.master_block, mb_period),
    ):
        name = resolve_sheet(wb.sheet_names, key, cmap)
        if name is None:
            check.add(Problem(label, None, None, f"Missing sheet: {label} (the workbook has: {', '.join(wb.sheet_names)})"))
            check.sheets.append(SheetColumns(label))
            continue
        grid = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        rep = _scan(name, grid, req, opt, aliases, period_of, check)
        check.sheets.append(rep)
        if key == "gp" and rep.header_row is not None and not (rep.periods.get("date") or rep.periods.get("week") or rep.periods.get("amcMonth")):
            check.add(Problem(name, rep.header_row, None, "No availability columns found – add at least the current day(s) (one date per column) or the current week (W-nn)"))
    return check


# ---------------------------------------------------------------- the downloadable templates


def week_number(start: dt.date) -> int:
    """BSNL week number of a Saturday–Friday week: week 1 is the week that contains 1 January of the year the week
    ends in (W-46 = 7–13 Nov 2026, W-45 = 31 Oct – 6 Nov 2026)."""
    jan1 = dt.date((start + dt.timedelta(days=6)).year, 1, 1)
    first = jan1 - dt.timedelta(days=(jan1.weekday() - 5) % 7)
    return (start - first).days // 7 + 1


def _examples(today: dt.date) -> dict[str, Any]:
    """Example period headers around `today` – the template is generated on download, so its examples are current."""
    sat = today - dt.timedelta(days=(today.weekday() - 5) % 7)  # weeks run Saturday – Friday like the BSNL sheet
    weeks = [(week_number(s), s) for s in (sat - dt.timedelta(days=7), sat)]
    m = today.replace(day=1)
    prev = (m - dt.timedelta(days=1)).replace(day=1)
    return {"weeks": weeks, "days": [sat + dt.timedelta(days=i) for i in range(7)], "months": [prev, m]}


def _range(s: dt.date) -> str:
    e = s + dt.timedelta(days=6)
    return f"{s.day}-{e.day} {e:%b}"


SECTION_A = "SECTION A – REQUIRED columns (exact names, must be present – any order)"
SECTION_B = (
    "SECTION B – Availability columns: EXAMPLES, not fixed. Add as many days / weeks / months as you have. "
    "Uploading only the current week / month is fine. Files are NEVER rejected because of these columns."
)


class _Fmt:
    def __init__(self, wb: Any) -> None:
        base = {"font_name": "Arial", "font_size": 10}
        self.req = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F6F43", "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"})
        self.per = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#B5651D", "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"})
        self.per_date = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#B5651D", "border": 1, "num_format": "dd-mmm-yy", "align": "center"})
        self.sec_a = wb.add_format(base | {"bold": True, "font_color": "#1F6F43", "bg_color": "#E2F0E8", "border": 1, "text_wrap": True, "valign": "vcenter"})
        self.sec_b = wb.add_format(base | {"bold": True, "font_color": "#7A3E0A", "bg_color": "#FBE5D6", "border": 1, "text_wrap": True, "valign": "vcenter"})
        self.label = wb.add_format(base | {"italic": True, "font_color": "#7A3E0A", "bg_color": "#FDF2EA", "border": 1, "align": "center"})
        self.cell = {
            "text": wb.add_format(base | {"num_format": "@"}),
            "int": wb.add_format(base | {"num_format": "0"}),
            "num": wb.add_format(base | {"num_format": "0.000"}),
            "date": wb.add_format(base | {"num_format": "dd-mm-yyyy"}),
            "pct": wb.add_format(base | {"num_format": "0.00"}),
        }
        self.title = wb.add_format(base | {"bold": True, "font_size": 14})
        self.bold = wb.add_format(base | {"bold": True})
        self.wrap = wb.add_format(base | {"text_wrap": True, "valign": "top"})


def _sections(ws: Any, f: _Fmt, a_cols: int, b_from: int, b_to: int) -> None:
    ws.merge_range(0, 0, 0, a_cols - 1, SECTION_A, f.sec_a) if a_cols > 1 else ws.write(0, 0, SECTION_A, f.sec_a)
    ws.merge_range(0, b_from, 0, b_to, SECTION_B, f.sec_b) if b_to > b_from else ws.write(0, b_from, SECTION_B, f.sec_b)
    ws.set_row(0, 48)


def _write_required(ws: Any, f: _Fmt, hdr: int, cols: tuple[Col, ...], first_row: int, planned: dt.date) -> None:
    for c, col in enumerate(cols):
        ws.write(hdr, c, col.name, f.req)
        ws.set_column(c, c, 14 if len(col.name) < 14 else 22, f.cell[col.fmt])
        ex = col.example
        if col.field == "planned_date":
            ex = (planned, None)
        for r, v in enumerate(ex):
            if v is None:
                continue
            if isinstance(v, dt.date):
                ws.write_datetime(first_row + r, c, dt.datetime.combine(v, dt.time()), f.cell["date"])
            else:
                ws.write(first_row + r, c, v, f.cell[col.fmt])


def _gp_sheet(wb: Any, f: _Fmt, today: dt.date) -> None:
    """GP Wise Data: row 1 sections, row 2 week dates / weekdays, row 3 header, rows 4–5 examples."""
    ex = _examples(today)
    ws = wb.add_worksheet("GP Wise Data")
    hdr, first = 2, 3
    _write_required(ws, f, hdr, GP_REQUIRED, first, ex["weeks"][-1][1] + dt.timedelta(days=2))
    c = len(GP_REQUIRED)
    b_from = c
    for m in ex["months"]:  # monthly availability: the 1st of the month, before the W-nn columns (as in the BSNL sheet)
        ws.write(1, c, "Month", f.label)
        ws.write_datetime(hdr, c, dt.datetime.combine(m, dt.time()), f.per_date)
        ws.write(first, c, 99.5, f.cell["pct"])
        ws.write(first + 1, c, "NA")
        c += 1
    m = ex["months"][-1]
    ws.write(1, c, "Month – AMC GPs", f.label)
    ws.write(hdr, c, f"{m:%b}'{m:%y} (AMC)", f.per)
    ws.write(first, c, 98.75, f.cell["pct"])
    ws.write(first + 1, c, "NA")
    c += 1
    for n, s in ex["weeks"]:  # W-nn with its 7-day range in the row above
        ws.write(1, c, _range(s), f.label)
        ws.write(hdr, c, f"W-{n}", f.per)
        ws.write(first, c, 99.0, f.cell["pct"])
        ws.write(first + 1, c, "NA")
        c += 1
    for d in ex["days"]:  # one real date per day, weekday in the row above
        ws.write(1, c, f"{d:%a}", f.label)
        ws.write_datetime(hdr, c, dt.datetime.combine(d, dt.time()), f.per_date)
        if d <= today:
            ws.write(first, c, 100, f.cell["pct"])
            ws.write(first + 1, c, 0, f.cell["pct"])  # a literal 0 is 0 % – blank / NA is "not reported"
        c += 1
    ws.set_column(b_from, c - 1, 11, f.cell["pct"])
    _sections(ws, f, len(GP_REQUIRED), b_from, c - 1)
    ws.set_row(hdr, 46)
    ws.freeze_panes(first, 7)


def _mb_sheet(wb: Any, f: _Fmt, today: dt.date) -> None:
    """Master Block: row 1 sections, row 2 groups (ALL GPs / AMC GPs), row 3 weekdays, row 4 header, rows 5–6 examples."""
    ex = _examples(today)
    ws = wb.add_worksheet("Master Block")
    hdr, first = 3, 4
    _write_required(ws, f, hdr, MB_REQUIRED, first, today)
    c = len(MB_REQUIRED)
    b_from = c
    prev, cur = ex["months"]
    for group in ("ALL GPs", "AMC GPs"):  # the same month names twice: first the ALL GPs group, then the AMC GPs group
        ws.write(1, c, group, f.label)
        for head, v in ((f"{prev:%b} Avg Avail", 97.4), (f"{cur:%b} Avg Avail TD", 96.8)):
            ws.write(hdr, c, head, f.per)
            ws.write(first, c, v, f.cell["pct"])
            ws.write(first + 1, c, "NA")
            c += 1
    for n, s in ex["weeks"]:
        ws.write(2, c, _range(s), f.label)
        ws.write(hdr, c, f"W{n} Avail", f.per)
        ws.write(first, c, 98.2, f.cell["pct"])
        ws.write(first + 1, c, "NA")
        c += 1
    for d in ex["days"][:2]:
        ws.write(2, c, f"{d:%a}", f.label)
        ws.write_datetime(hdr, c, dt.datetime.combine(d, dt.time()), f.per_date)
        if d <= today:
            ws.write(first, c, 100, f.cell["pct"])
        c += 1
    ws.set_column(b_from, c - 1, 12, f.cell["pct"])
    _sections(ws, f, len(MB_REQUIRED), b_from, c - 1)
    ws.set_row(hdr, 46)
    ws.freeze_panes(first, 5)


def _read_me(wb: Any, f: _Fmt, kind: str) -> None:
    rd = wb.add_worksheet("Read Me")
    rd.write(0, 0, "PAGMAS – Master Data upload template", f.title)
    notes = [
        "Upload ONE workbook with both sheets: 'GP Wise Data' and 'Master Block'. Columns are found by their header name – any order works; letter case, spaces and punctuation do not matter.",
        "SECTION A (green) = REQUIRED columns. Exact names, must be present. A missing required column is the ONLY column reason a file is rejected – the message names it.",
        "SECTION B (orange) = availability columns (day / week / month). These are EXAMPLES, not fixed: add as many as you have. Uploading only the current week or month is fine – earlier weeks and months stay on the dashboard from earlier uploads. Files are NEVER rejected because of these columns.",
        "Day = a real date in the header (weekday in the row above). Week = W-46 (GP Wise) / W46 Avail (Master Block) with its 7-day range (e.g. 7-13 Nov) in the row above. Month = the 1st of the month as a date, Nov'26 (AMC), Nov Avg Avail [TD].",
        "Any other column (the optional ones below or your own) may be in the sheet: optional columns are read when present, all others are ignored and listed as 'not used' in the check report.",
        "Values: dates as real Excel dates (dd-mm-yyyy); availability 0–100 or NA. Blank / NA = not reported (never counted as 0); only a written 0 is 0 %. One row per GP Code / Block Code – a repeated code is skipped and both rows are named.",
    ]
    for i, t in enumerate(notes, start=2):
        rd.merge_range(i, 0, i, 3, t, f.wrap)
        rd.set_row(i, 44)
    r = len(notes) + 3
    for j, h in enumerate(("Sheet", "Column", "Bucket", "Used for")):
        rd.write(r, j, h, f.req)
    r += 1
    sheets = [("GP Wise Data", GP_REQUIRED, GP_OPTIONAL), ("Master Block", MB_REQUIRED, MB_OPTIONAL)]
    if kind == "gp":
        sheets = sheets[:1]
    elif kind == "block":
        sheets = sheets[1:]
    for sheet, req, opt in sheets:
        for bucket, cols in (("REQUIRED", req), ("optional", opt)):
            for col in cols:
                rd.write_row(r, 0, [sheet, col.name, bucket, col.why or "reference only (not used by the dashboard)"], f.wrap)
                r += 1
        pats = (
            ["Day: a date per column", "Month: 1st of the month (date)", "Month (AMC GPs): Nov'26 (AMC)", "Week: W-46 + 7-day range above", "Status: April … / WK-46 (not used)"]
            if sheet == "GP Wise Data"
            else ["Month: Nov Avail / Nov Avg Avail [TD] (ALL GPs, then AMC GPs)", "Week: W46 Avail", "Day: a date per column", "Targets: Nov 5% Inc. Target, Nov Conversion Target (not used)"]
        )
        for p in pats:
            rd.write_row(r, 0, [sheet, p, "time-varying (pattern)", "availability history – add as many as you have"], f.wrap)
            r += 1
    for c, w in zip(range(4), (14, 52, 22, 52)):
        rd.set_column(c, c, w)


def build_template(kind: str = "master", today: dt.date | None = None, sample: bool = True) -> bytes:
    """Template (.xlsx) with two example rows: kind "gp" (GP Wise Data), "block" (Master Block) or "master" (both sheets
    in one workbook – ready to fill and upload). `sample` is kept for old links (the examples are always included)."""
    import xlsxwriter

    del sample
    today = today or dt.date.today()
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    f = _Fmt(wb)
    _read_me(wb, f, kind)
    if kind in ("gp", "master"):
        _gp_sheet(wb, f, today)
    if kind in ("block", "master"):
        _mb_sheet(wb, f, today)
    wb.close()
    return buf.getvalue()


TEMPLATE_FILES = {"gp": "PAGMAS GP Wise Template.xlsx", "block": "PAGMAS Master Block Template.xlsx", "master": "PAGMAS Master Data Template.xlsx"}
