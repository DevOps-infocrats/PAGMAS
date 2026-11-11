"""The fixed PAGMAS master data template – one source of truth for the downloadable template AND the strict upload check.

Reference: the BSNL master data workbook "Master Data V8.2 Daily track 10-11-26.xlsb" (sheets GP Wise Data, Master
Block). Every column below is mandatory. Column ORDER is free (columns are found by their header name); the NAME must be
the template name (letter case and extra spaces are ignored; names an admin added on Data Operations → Column names are
accepted too – nothing is ever guessed or renamed automatically).

Fixed columns       always the same name (Circle, GP Code, TOTAL RKM …).
Period columns      their names change with the data, so they are recognised by PATTERN, never by a fixed name or a
                    fixed week / date list (a new day, week, month or year needs no change here):
                      GP Wise Data   monthly availability (a real date, 1st of a month) · "Mon'YY (AMC)" · W-nn with
                                     its dates ("7-13 Nov") in the row above · one real date per day, right after the
                                     W-nn columns · monthly status (April, May … ) · weekly status (WK-nn)
                      Master Block   "<Month> Avail" · "<Month> Avg Avail[ TD]" (once in the ALL GPs and once in the
                                     AMC GPs group) · "Wnn Avail" · "<Month> 5% Inc. Target" · "<Month> Conversion Target"
Week ↔ date         the file's own week calendar (the 7-day ranges above its W-nn columns) is the reference: weeks must
                    follow each other 7 days apart, every W-nn label must be a 7-day range, the daily dates must be
                    consecutive, and a Master Block "Target Week" must contain its "Target Date" (week numbers continue
                    in 7-day steps from the file's own weeks, across month and year ends – nothing is hard-coded).
Values              identity columns must not be blank; dates, numbers, whole numbers and availability % must be valid
                    where filled (blank is allowed where the business leaves it blank, e.g. AMC Date of a non-AMC GP).
                    Anything wrong = the file is rejected with every problem and its Excel row. Only a few known,
                    harmless conditions are warnings (listed below), so the daily file is not blocked by them.
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

TEMPLATE_MESSAGE = (
    "Your uploaded file does not match the required PAGMAS Excel template. Please download the latest template and update "
    "your file according to the required column names and data formats."
)
MAX_PROBLEMS = 500  # listed per upload (all are counted)

# ---------------------------------------------------------------- column kinds
TEXT, CODE, INT, NUM, DATE, PCT, ENUM, WEEKCODE, SIGNED = "text", "code", "int", "number", "date", "percent", "enum", "weekcode", "signed"
KIND_LABEL = {SIGNED: "Whole number (may be negative)", TEXT: "Text", CODE: "GP code (digits)", INT: "Whole number", NUM: "Number", DATE: "Date (dd-mm-yyyy)", PCT: "Availability % (0–100 or NA)", ENUM: "One of the listed values", WEEKCODE: "Week code (WK-nn)"}


@dataclass(frozen=True)
class Col:
    name: str
    kind: str = TEXT
    required: bool = False  # the cell must not be blank
    lenient: bool = False  # a wrong value is a warning (left empty, as the importer does) – known harmless data issues
    values: tuple[str, ...] = ()  # ENUM: allowed values (case-insensitive)
    field: str | None = None  # importer field (column_map) – its admin-added names are accepted too
    note: str = ""


# GP Wise Data – header row 3 in the template (found in the first 15 rows), fixed columns in the reference order
GP_FIXED: tuple[Col, ...] = (
    Col("Circle", TEXT, True, field="circle"),
    Col("BA", TEXT, True, field="ba"),
    Col("DISTRICT", TEXT, True, field="district"),
    Col("BLOCK", TEXT, True, field="block_name"),
    Col("Block Code", INT, True, field="block_code"),
    Col("New Block Code post BoQ", INT, True),
    Col("New Block Name post BoQ", TEXT, True),
    Col("Block Changed", TEXT, True),
    Col("Block HoTo Status", TEXT, field="block_hoto_status"),
    Col("GP", TEXT, True, field="gp_name"),
    Col("GP Code", CODE, True, field="gp_code"),
    Col("LOCATION CODE", TEXT, True, field="location_code"),
    Col("Converted to NP & Closed", TEXT, field="np_status", note="blank = GP in service"),
    Col("GP Type", TEXT, True, field="gp_type"),
    Col("Phase", TEXT, True, field="phase"),
    Col("OLT Location", TEXT, field="olt_location"),
    Col("BBNL Live KM", NUM, field="bbnl_km", lenient=True, note="a wrong / negative value is left empty (warning)"),
    Col("BSNL Live KM", NUM, field="bsnl_km", lenient=True, note="a wrong / negative value is left empty (warning)"),
    Col("TOTAL RKM", NUM, True, field="total_rkm"),
    Col("LMS /AMC Date", DATE, field="lms_amc_date"),
    Col("HOTO Date", DATE, field="hoto_date", note="blank for a GP without HOTO"),
    Col("Lot wise", TEXT, field="lot"),
    Col("Letter submission date AMC Incremental", DATE, field="letter_date"),
    Col("AMC / Incremental", ENUM, values=("AMC", "Incremental"), field="amc_category", note="blank for a non-AMC GP"),
    Col("AMC Date", DATE, field="amc_date", note="blank for a non-AMC GP"),
    Col("<50 % Availability Last 4 M", NUM),
    Col("FRT Code", TEXT),
    Col("Name of splicer", TEXT),
    Col("Splicer Contact No.", TEXT),
    Col("FE Name", TEXT),
    Col("FE Contact No", TEXT),
    Col("AM Name", TEXT, field="am_name"),
    Col("AM Contact No", TEXT),
    Col("SHQ Spoc", TEXT),
    Col("SHQ Spoc  Contact No", TEXT),
    Col("Block Priority", TEXT),
    Col("5% Contractual Incremental+ Additional AMC", TEXT, field="plan_category"),
    Col("Planned Date", DATE, field="planned_date"),
    Col("Ach Date", DATE, field="ach_date"),
    Col("Letter Status", TEXT, field="plan_letter_status"),
    Col("Approval Status", TEXT, field="plan_approval_status"),
)

# Master Block – header row 4 in the template (row 1: group titles "ALL GPs" / "AMC GPs")
MB_FIXED: tuple[Col, ...] = (
    Col("State", TEXT, True),
    Col("BA", TEXT, True),
    Col("District", TEXT, True),
    Col("Block Name", TEXT, True),
    Col("FRT CODE", TEXT),
    Col("Block Code", INT, True),
    Col("HOTO Done Date", DATE),
    Col("Total GP Count", INT, True),
    Col("Existing GPs", INT, True),
    Col("New GPs", INT, True),
    Col("HOTO Done GPs", INT, True),
    Col("AMC GP GPs", INT, True),
    Col("Non AMC Count", INT, True),
    Col("BSNL Existing RKM", NUM, True),
    Col("BBNL Existing RKM", NUM, True),
    Col("Total RKM", NUM, True),
    Col("Lot Wise", TEXT),
    Col("AMC", INT, True),
    Col("Incremental", INT, True),
    Col("Achieved", INT, True),
    Col("Shortfall / Penalty", SIGNED, note="negative = achieved more than the target"),
    Col("Target Week", WEEKCODE),
    Col("Target Date", DATE),
    Col("Penalty Date", DATE),
)

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_WORD = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
RE_W = re.compile(r"^w-?(\d{1,2})$")
RE_WK = re.compile(r"^wk-?\s*(\d{1,2})$")
RE_AMC_MONTH = re.compile(rf"^{MONTH_WORD}'(\d{{2}}) \(amc\)$")
RE_MONTH_STATUS = re.compile(rf"^{MONTH_WORD}$")
RE_RANGE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})\s+([a-z]+)$")
MB_PATTERNS: tuple[tuple[str, re.Pattern[str], str, int], ...] = (  # (label, pattern, kind, max occurrences of one name)
    ("<Month> Avail", re.compile(rf"^{MONTH_WORD} avail$"), PCT, 1),
    ("<Month> Avg Avail[ TD]", re.compile(rf"^{MONTH_WORD} avg avail(?: td)?$"), PCT, 2),  # ALL GPs + AMC GPs group
    ("Wnn Avail", re.compile(r"^w-?\d{1,2} avail$"), PCT, 1),
    ("<Month> 5% Inc. Target", re.compile(rf"^{MONTH_WORD} 5% inc\.? target$"), NUM, 1),  # 5 % of the GPs – decimals
    ("<Month> Conversion Target", re.compile(rf"^{MONTH_WORD} conversion target$"), NUM, 1),
)
NA = {"na", "n/a", "#n/a"}


@dataclass
class Problem:
    sheet: str
    row: int | None
    column: str | None
    message: str
    severity: str = "error"  # error | warning

    def json(self) -> dict[str, Any]:
        return {"sheet": self.sheet, "row": self.row, "column": self.column, "severity": self.severity, "message": self.message}


@dataclass
class Check:
    errors: list[Problem] = field(default_factory=list)
    warnings: list[Problem] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0

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


# ---------------------------------------------------------------- cell checks


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(\.\d+)?", s):  # a number written as text ('0.22') is a number, not a conversion
            return float(s)
    return None


def _blank(v: Any) -> bool:
    return is_blank(v) or (isinstance(v, float) and v != v) or (isinstance(v, dt.time) and v == dt.time(0, 0))  # Excel date 0 = empty


def _cell_problem(col: Col, v: Any) -> str | None:
    """Why this filled cell does not fit its column, or None."""
    if col.kind == DATE:
        if isinstance(v, (dt.date, dt.datetime)) or (isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 <= v <= 80000):
            return None
        if isinstance(v, str) and as_date(v):
            return None
        return f"'{v}' is not a valid date (dd-mm-yyyy)"
    if col.kind in (NUM, INT, SIGNED):
        n = _num(v)
        if n is None:
            return f"'{v}' is not a valid number"
        if col.kind == SIGNED:
            return None if float(n).is_integer() else f"{v} is not a whole number"
        if n < 0:
            return f"{v} is negative"
        if col.kind == INT and not float(n).is_integer():
            return f"{v} is not a whole number"
        return None
    if col.kind == PCT:
        if isinstance(v, str) and v.strip().lower() in NA:
            return None
        n = _num(v)
        if n is None:
            return f"'{v}' is not an availability % (0–100) or NA"
        if not 0 <= n <= 100 + 1e-9:
            return f"{v} is outside 0–100 %"
        return None
    if col.kind == CODE:
        s = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
        if re.fullmatch(r"\d+", s):
            return None
        if re.fullmatch(r"[Oo]\d+", s):
            return None  # reported as a warning by the caller
        return f"'{v}' is not a GP code (digits only)"
    if col.kind == ENUM:
        if str(v).strip().lower() in {x.lower() for x in col.values}:
            return None
        return f"'{v}' is not one of: {', '.join(col.values)}"
    if col.kind == WEEKCODE:
        return None if RE_WK.match(norm(v)) else f"'{v}' is not a week code like WK-46"
    return None


# ---------------------------------------------------------------- headers


@dataclass
class Header:
    fixed: dict[str, int]  # template name -> column index
    period: dict[int, tuple[str, Any]]  # column index -> (group, parsed key)
    names: list[str]


def _aliases(col: Col, gp: bool) -> set[str]:
    names = {norm(col.name)}
    if gp and col.field:
        from .column_map import load_column_map

        names |= set(load_column_map().gp.get(col.field, ()))
    return names


def _suggest(text: str, missing: list[str]) -> str | None:
    best = difflib.get_close_matches(norm(text), [norm(m) for m in missing], n=1, cutoff=0.6)
    if not best:
        return None
    return next(m for m in missing if norm(m) == best[0])


def _headers(sheet: str, header: list[Any], above: list[Any], fixed: tuple[Col, ...], check: Check, gp: bool, data_cols: set[int]) -> Header | None:
    """Map every header cell to a template column or a period group; missing / unknown / duplicate columns are errors."""
    found: dict[str, int] = {}
    dup: dict[str, list[int]] = {}
    period: dict[int, tuple[str, Any]] = {}
    unknown: list[tuple[int, str]] = []
    lookup: dict[str, str] = {}
    for col in fixed:
        for a in _aliases(col, gp):
            lookup.setdefault(a, col.name)
    seen_pattern: Counter = Counter()
    for c, h in enumerate(header):
        if isinstance(h, (dt.date, dt.datetime)):
            period[c] = ("date", h.date() if isinstance(h, dt.datetime) else h)
            continue
        text = norm(h)
        if not text or (isinstance(h, (int, float)) and not isinstance(h, bool)):
            if c in data_cols:  # data below a column without a header
                unknown.append((c, f"(column {_col(c)} has values but no header)"))
            continue  # empty / numeric summary cells next to the header are not columns
        if text in lookup:
            name = lookup[text]
            if name in found:
                dup.setdefault(name, [found[name]]).append(c)
            else:
                found[name] = c
            continue
        if gp:
            if m := RE_W.match(text):
                period[c] = ("week", int(m.group(1)))
            elif m := RE_WK.match(text):
                period[c] = ("week_status", int(m.group(1)))
            elif RE_AMC_MONTH.match(text):
                period[c] = ("amc_month", text)
            elif RE_MONTH_STATUS.match(text):
                period[c] = ("month_status", text)
            else:
                unknown.append((c, str(h).strip()))
                continue
            seen_pattern[text] += 1
            if seen_pattern[text] > 1:
                dup.setdefault(str(h).strip(), []).append(c)
        else:
            hit = next(((label, kind, most) for label, rx, kind, most in MB_PATTERNS if rx.match(text)), None)
            if hit is None:
                unknown.append((c, str(h).strip()))
                continue
            period[c] = ("mb:" + hit[1], text)
            seen_pattern[text] += 1
            if seen_pattern[text] > hit[2]:
                dup.setdefault(str(h).strip(), []).append(c)
    missing = [col.name for col in fixed if col.name not in found]
    for name in missing:
        check.add(Problem(sheet, None, name, f"Missing column: {name}"))
    for c, text in unknown:
        hint = _suggest(text, missing)
        check.add(Problem(sheet, None, text, f"Incorrect column name: '{text}' (column {_col(c)})" + (f" – the template name is '{hint}'" if hint else " – not a column of the template")))
    for name, cols in dup.items():
        check.add(Problem(sheet, None, name, f"Duplicate column: {name} (columns {', '.join(_col(c) for c in cols)})"))
    return Header(found, period, [str(h) for h in header])


def _col(c: int) -> str:
    s, c = "", c + 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------- week calendar (the file's own)


def _week_range(label: Any, ref_year: int) -> tuple[dt.date, dt.date] | None:
    """'7-13 Nov' -> (7 Nov, 13 Nov); '31-6 Nov' -> (31 Oct, 6 Nov); '28-3 Jan' -> (28 Dec, 3 Jan) – year from the file."""
    m = RE_RANGE.match(norm(label))
    if not m:
        return None
    mon = MONTHS.index(m.group(3)[:3]) + 1 if m.group(3)[:3] in MONTHS else None
    if mon is None:
        return None
    try:
        end = dt.date(ref_year, mon, int(m.group(2)))
        start = end - dt.timedelta(days=6)
    except ValueError:
        return None
    return (start, end) if start.day == int(m.group(1)) else None


def _week_start_of(number: int, anchor: tuple[int, dt.date]) -> dt.date:
    """Start of week `number` continuing the file's own 7-day calendar from an anchor week (wraps at the year end)."""
    n0, s0 = anchor
    if week_number(s0) == n0:  # the file follows the BSNL numbering: find the nearest week with that number (52/53-week years)
        hits = [k for k in range(-30, 31) if week_number(s0 + dt.timedelta(days=7 * k)) == number]
        if hits:
            return s0 + dt.timedelta(days=7 * min(hits, key=abs))
    delta = number - n0
    if delta < -26:
        delta += 52
    elif delta > 26:
        delta -= 52
    return s0 + dt.timedelta(days=7 * delta)


# ---------------------------------------------------------------- sheets


def _grid(wb: Any, name: str) -> list[list[Any]]:
    return wb.get_sheet_by_name(name).to_python(skip_empty_area=False)


def _find(grid: list[list[Any]], anchors: tuple[str, ...]) -> int | None:
    want = {norm(a) for a in anchors}
    for i, row in enumerate(grid[:15]):
        if want <= {norm(c) for c in row}:
            return i
    return None


def _rows(grid: list[list[Any]], hdr: int, ncols: int) -> list[tuple[int, list[Any]]]:
    out = []
    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        if all(_blank(v) for v in row[: min(15, ncols)]):
            continue
        if str(row[0]).strip() == "@":  # end-of-data marker of the BSNL sheet
            continue
        out.append((i + 1, row))
    return out


def _check_values(sheet: str, rows: list[tuple[int, list[Any]]], hdr: Header, fixed: tuple[Col, ...], check: Check, key: str | None) -> None:
    cols = [(c, hdr.fixed[c.name]) for c in fixed if c.name in hdr.fixed]
    keys: dict[str, int] = {}
    for excel_row, row in rows:
        for col, i in cols:
            v = row[i] if i < len(row) else None
            if _blank(v):
                if col.required:
                    check.add(Problem(sheet, excel_row, col.name, f"{col.name} is blank – a value is required"))
                continue
            why = _cell_problem(col, v)
            if why:
                check.add(Problem(sheet, excel_row, col.name, why + (" – left empty" if col.lenient else ""), "warning" if col.lenient else "error"))
            elif col.kind == CODE and re.fullmatch(r"[Oo]\d+", str(v).strip()):
                check.add(Problem(sheet, excel_row, col.name, f"GP code '{v}' starts with the letter O – read as {'0' + str(v).strip()[1:]}", "warning"))
            elif col.name == "OLT Location" and _num(v) is not None:
                check.add(Problem(sheet, excel_row, col.name, f"OLT location '{v}' is a number, not a location name – left empty", "warning"))
        if key and key in hdr.fixed:
            v = row[hdr.fixed[key]] if hdr.fixed[key] < len(row) else None
            if not _blank(v):
                k = re.sub(r"\.0$", "", str(v).strip()).upper().lstrip("O0") or "0"
                if k in keys:
                    check.add(Problem(sheet, excel_row, key, f"Duplicate {key} {v} – first on row {keys[k]}"))
                else:
                    keys[k] = excel_row


def _check_periods_gp(sheet: str, grid: list[list[Any]], hdr_row: int, hdr: Header, rows: list[tuple[int, list[Any]]], check: Check) -> list[tuple[int, dt.date, dt.date]]:
    """GP Wise Data period columns: presence, week labels, 7-day steps, consecutive daily dates, % values."""
    above = grid[hdr_row - 1] if hdr_row > 0 else []
    weeks = sorted((c, n) for c, (g, n) in hdr.period.items() if g == "week")
    dates = sorted((c, d) for c, (g, d) in hdr.period.items() if g == "date")
    if not weeks:
        check.add(Problem(sheet, None, "W-nn", "Missing weekly availability columns (W-nn, e.g. W-46)"))
        return []
    first_w, last_w = weeks[0][0], weeks[-1][0]
    monthly = [(c, d) for c, d in dates if c < first_w]
    daily = [(c, d) for c, d in dates if c > last_w]
    if not monthly:
        check.add(Problem(sheet, None, "Monthly availability", "Missing monthly availability columns (a date on the 1st of each month, before the W-nn columns)"))
    for c, d in monthly:
        if d.day != 1:
            check.add(Problem(sheet, None, _col(c), f"Monthly availability column {_col(c)} is dated {d:%d-%m-%Y} – a monthly column must be the 1st of the month"))
    if not daily:
        check.add(Problem(sheet, None, "Daily dates", "Missing daily availability columns (one date per day, right after the W-nn columns)"))
        return []
    if not any(g == "amc_month" for g, _ in hdr.period.values()):
        check.add(Problem(sheet, None, "Mon'YY (AMC)", "Missing monthly AMC availability columns (e.g. Nov'26 (AMC))"))
    # daily: consecutive days, contiguous columns, no repeats
    seen: set[dt.date] = set()
    for (c1, d1), (c2, d2) in zip(daily, daily[1:]):
        if c2 != c1 + 1:
            check.add(Problem(sheet, None, _col(c1 + 1), f"Daily date columns must be next to each other – column {_col(c1 + 1)} breaks them"))
            break
    for (_, d1), (c2, d2) in zip(daily, daily[1:]):
        if d2 in seen or d2 == d1:
            check.add(Problem(sheet, None, _col(c2), f"Duplicate daily date {d2:%d-%m-%Y} (column {_col(c2)})"))
        elif (d2 - d1).days != 1:
            check.add(Problem(sheet, None, _col(c2), f"Daily dates are not consecutive: {d1:%d-%m-%Y} is followed by {d2:%d-%m-%Y} (column {_col(c2)})"))
        seen.add(d1)
    last_day = daily[-1][1]
    # weeks: each W-nn has a 7-day range above it; weeks are 7 days apart and numbered in order (wrapping at the year end)
    cal: list[tuple[int, dt.date, dt.date]] = []
    for c, n in weeks:
        label = above[c] if c < len(above) else None
        rng = None
        for year in (last_day.year, last_day.year - 1, last_day.year + 1):
            r = _week_range(label, year)
            if r and r[1] <= last_day + dt.timedelta(days=40):
                rng = r
                break
        if rng is None:
            check.add(Problem(sheet, hdr_row, f"W-{n}", f"W-{n}: the week dates above the column ('{label or ''}') are not a 7-day range like '7-13 Nov'"))
            continue
        cal.append((n, *rng))
    cal.sort(key=lambda x: x[1])
    for (n1, s1, _), (n2, s2, _) in zip(cal, cal[1:]):
        if (s2 - s1).days != 7:
            check.add(Problem(sheet, hdr_row, f"W-{n2}", f"Week does not match its dates: W-{n1} starts {s1:%d %b %Y} and W-{n2} starts {s2:%d %b %Y} – weeks must be 7 days apart"))
        elif n2 != n1 + 1 and not (n2 == 1 and n1 >= 52):
            check.add(Problem(sheet, hdr_row, f"W-{n2}", f"Week numbers out of order: W-{n1} ({s1:%d %b}) is followed by W-{n2} ({s2:%d %b}) – expected W-{n1 + 1}"))
    # period values (availability %) and status texts
    pct = Col("availability", PCT)
    for c, (g, key) in sorted(hdr.period.items()):
        if g not in ("week", "date", "amc_month"):
            continue
        label = f"W-{key}" if g == "week" else (key.strftime("%d-%m-%Y") if isinstance(key, dt.date) else str(key))
        for excel_row, row in rows:
            v = row[c] if c < len(row) else None
            if _blank(v):
                continue
            why = _cell_problem(pct, v)
            if why:
                check.add(Problem(sheet, excel_row, label, why))
    return cal


def _check_master_block(wb: Any, check: Check, cal: list[tuple[int, dt.date, dt.date]]) -> None:
    sheet = "Master Block"
    if sheet not in wb.sheet_names:
        check.add(Problem(sheet, None, None, "Missing sheet: Master Block"))
        return
    grid = _grid(wb, sheet)
    hdr_row = _find(grid, ("State", "Block Code"))
    if hdr_row is None:
        check.add(Problem(sheet, None, None, "Header row not found in the first 15 rows (it must contain State and Block Code)"))
        return
    ncols = len(grid[hdr_row])
    rows = _rows(grid, hdr_row, ncols)
    data_cols = {c for _, r in rows for c, v in enumerate(r) if not _blank(v)}
    hdr = _headers(sheet, grid[hdr_row], [], MB_FIXED, check, False, data_cols)
    if hdr is None:
        return
    for label, rx, _kind, _most in MB_PATTERNS:
        if not any(rx.match(norm(h)) for h in grid[hdr_row]):
            check.add(Problem(sheet, None, label, f"Missing columns: {label}"))
    _check_values(sheet, rows, hdr, MB_FIXED, check, "Block Code")
    for c, (g, text) in sorted(hdr.period.items()):
        if not g.startswith("mb:"):
            check.add(Problem(sheet, None, str(grid[hdr_row][c]), f"Incorrect column name: '{grid[hdr_row][c]}' (column {_col(c)}) – not a column of the template"))
            continue
        kind = g.split(":", 1)[1]
        col = Col(text, kind)
        for excel_row, row in rows:
            v = row[c] if c < len(row) else None
            if _blank(v):
                continue
            why = _cell_problem(col, v)
            if why:
                check.add(Problem(sheet, excel_row, grid[hdr_row][c], why))
    # Target Week must contain Target Date (the GP sheet's week calendar continued in 7-day steps)
    if cal and "Target Week" in hdr.fixed and "Target Date" in hdr.fixed:
        anchor = (cal[-1][0], cal[-1][1])
        for excel_row, row in rows:
            wk, d = row[hdr.fixed["Target Week"]], as_date(row[hdr.fixed["Target Date"]])
            m = RE_WK.match(norm(wk))
            if not m or d is None:
                continue
            start = _week_start_of(int(m.group(1)), anchor)
            if not start <= d <= start + dt.timedelta(days=6):
                check.add(Problem(sheet, excel_row, "Target Week", f"Week does not match the date: {wk} is {start:%d %b} – {start + dt.timedelta(days=6):%d %b %Y}, Target Date is {d:%d-%m-%Y}"))
        if "Penalty Date" in hdr.fixed:
            for excel_row, row in rows:
                t, p = as_date(row[hdr.fixed["Target Date"]]), as_date(row[hdr.fixed["Penalty Date"]])
                if t and p and p < t:
                    check.add(Problem(sheet, excel_row, "Penalty Date", f"Penalty Date {p:%d-%m-%Y} is before the Target Date {t:%d-%m-%Y}", "warning"))


def validate_master(path: Path) -> Check:
    """Strict template check of a master data workbook (nothing is written). Errors = the file must be rejected."""
    from .workbook import open_workbook

    check = Check()
    wb = open_workbook(path)
    sheet = "GP Wise Data"
    from .column_map import load_column_map, resolve_sheet

    name = resolve_sheet(wb.sheet_names, "gp", load_column_map())
    if name is None:
        check.add(Problem(sheet, None, None, "Missing sheet: GP Wise Data"))
        return check
    grid = _grid(wb, name)
    hdr_row = _find(grid, ("Circle", "GP Code"))
    if hdr_row is None:
        check.add(Problem(name, None, None, "Header row not found in the first 15 rows (it must contain Circle and GP Code)"))
        return check
    ncols = len(grid[hdr_row])
    rows = _rows(grid, hdr_row, ncols)
    if not rows:
        check.add(Problem(name, None, None, "No GP rows below the header"))
    data_cols = {c for _, r in rows for c, v in enumerate(r) if not _blank(v)}
    hdr = _headers(name, grid[hdr_row], grid[hdr_row - 1] if hdr_row else [], GP_FIXED, check, True, data_cols)
    cal: list[tuple[int, dt.date, dt.date]] = []
    if hdr is not None:
        _check_values(name, rows, hdr, GP_FIXED, check, "GP Code")
        cal = _check_periods_gp(name, grid, hdr_row, hdr, rows, check)
    _check_master_block(wb, check, cal)
    return check


# ---------------------------------------------------------------- the downloadable template (built from the spec)


def week_number(start: dt.date) -> int:
    """BSNL week number of a Saturday–Friday week: week 1 is the week that contains 1 January of the year the week
    ends in (W-46 = 7–13 Nov 2026, W-45 = 31 Oct – 6 Nov 2026); used only when no imported data gives the calendar."""
    jan1 = dt.date((start + dt.timedelta(days=6)).year, 1, 1)
    first = jan1 - dt.timedelta(days=(jan1.weekday() - 5) % 7)
    return (start - first).days // 7 + 1


def _period_example(today: dt.date) -> dict[str, Any]:
    """Example period headers around `today` – the template is generated on download, so it is always current."""
    sat = today - dt.timedelta(days=(today.weekday() - 5) % 7)  # weeks run Saturday – Friday like the BSNL sheet
    weeks = [(week_number(sat - dt.timedelta(days=7 * i)), sat - dt.timedelta(days=7 * i)) for i in range(0, 3)]
    first_day = weeks[-1][1]
    days = [first_day + dt.timedelta(days=i) for i in range((sat + dt.timedelta(days=6) - first_day).days + 1)]
    m0 = today.replace(day=1)
    months = [(m0 - dt.timedelta(days=31 * i)).replace(day=1) for i in range(2, -1, -1)]
    return {"weeks": weeks, "days": days, "months": months}


def build_template(sample: bool = False, today: dt.date | None = None) -> bytes:
    """The master data template (.xlsx): GP Wise Data + Master Block with every mandatory column, the period columns
    for the current weeks / days / months (they move with the data – add the new ones each day), a Read Me sheet and,
    for `sample`, two example rows that pass the upload check."""
    import xlsxwriter

    today = today or dt.date.today()
    ex = _period_example(today)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    base = {"font_name": "Arial", "font_size": 10}
    head = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F6F43", "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"})
    period_head = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#B5651D", "border": 1, "text_wrap": True, "valign": "vcenter", "align": "center"})
    head_date = wb.add_format(base | {"bold": True, "font_color": "#FFFFFF", "bg_color": "#B5651D", "border": 1, "num_format": "dd-mmm-yy", "align": "center"})
    label = wb.add_format(base | {"bold": True, "bg_color": "#FBE5D6", "border": 1, "align": "center"})
    group = wb.add_format(base | {"bold": True, "bg_color": "#E7EEF5", "align": "center"})
    fmt = {
        DATE: wb.add_format(base | {"num_format": "dd-mm-yyyy"}), INT: wb.add_format(base | {"num_format": "0"}), SIGNED: wb.add_format(base | {"num_format": "0"}), NUM: wb.add_format(base | {"num_format": "0.000"}),
        PCT: wb.add_format(base | {"num_format": "0.00"}), TEXT: wb.add_format(base | {"num_format": "@"}), CODE: wb.add_format(base | {"num_format": "0"}),
        ENUM: wb.add_format(base | {"num_format": "@"}), WEEKCODE: wb.add_format(base | {"num_format": "@"}),
    }
    title = wb.add_format(base | {"bold": True, "font_size": 14})
    wrap = wb.add_format(base | {"text_wrap": True, "valign": "top"})
    bold = wb.add_format(base | {"bold": True})

    # ---- Read Me
    rd = wb.add_worksheet("Read Me")
    rd.write(0, 0, "PAGMAS – Master Data upload template", title)
    notes = [
        "Every column of 'GP Wise Data' and 'Master Block' is mandatory. Column names must be exactly these (letter case and extra spaces do not matter); the column ORDER may change.",
        "A missing, renamed, duplicate or unknown column, a wrong date / number / % or a blank required cell rejects the whole file – nothing is imported. The check report lists every problem with its Excel row.",
        "Period columns change with the data – add them, never rename them: one date column per day right after the W-nn columns; W-nn with its 7-day dates (e.g. 7-13 Nov) in the row above; the 1st of each month for monthly availability; Mon'YY (AMC); month status (April …) and WK-nn status.",
        "Master Block: <Month> Avg Avail[ TD] appears once in the ALL GPs group and once in the AMC GPs group; Wnn Avail, <Month> 5% Inc. Target and <Month> Conversion Target follow the current month / week. Target Week (WK-nn) must contain the Target Date.",
        "Dates: real Excel dates (dd-mm-yyyy). Availability: 0–100 or NA. Whole numbers for counts and codes. Blank is allowed only where the business leaves it blank (e.g. AMC Date of a non-AMC GP) – blank is never read as 0.",
    ]
    for i, t in enumerate(notes, start=2):
        rd.merge_range(i, 0, i, 4, t, wrap)
        rd.set_row(i, 42)
    r0 = len(notes) + 3
    for j, h in enumerate(("Sheet", "Column", "Format", "Value required", "Note")):
        rd.write(r0, j, h, head)
    r = r0 + 1
    for sheet, cols in (("GP Wise Data", GP_FIXED), ("Master Block", MB_FIXED)):
        for c in cols:
            rd.write_row(r, 0, [sheet, c.name, KIND_LABEL[c.kind] + (f": {', '.join(c.values)}" if c.values else ""), "Yes" if c.required else "No (blank allowed)", c.note], wrap)
            r += 1
    for sheet, txt, kind in (
        ("GP Wise Data", "Monthly availability – 1st of each month (date)", PCT), ("GP Wise Data", "Mon'YY (AMC)", PCT), ("GP Wise Data", "W-nn (dates in the row above)", PCT),
        ("GP Wise Data", "Daily – one date per day after W-nn", PCT), ("GP Wise Data", "April, May … (month status)", TEXT), ("GP Wise Data", "WK-nn (week status)", TEXT),
        *((("Master Block", lbl, k) for lbl, _rx, k, _m in MB_PATTERNS)),
    ):
        rd.write_row(r, 0, [sheet, txt, KIND_LABEL[kind], "No (blank allowed)", "Period column – recognised by its pattern"], wrap)
        r += 1
    for c, w in zip(range(5), (14, 44, 30, 18, 36)):
        rd.set_column(c, c, w)

    # ---- GP Wise Data (layout of the BSNL sheet: row 1 group titles, row 2 week dates, row 3 header)
    ws = wb.add_worksheet("GP Wise Data")
    order: list[tuple[str, Any, Any]] = []  # (kind, header, value format)
    fixed_head = list(GP_FIXED[:26])  # up to "<50 % Availability Last 4 M" like the reference
    for col in fixed_head[:25]:
        order.append(("fixed", col, None))
    for m in ex["months"]:
        order.append(("month", m, None))
    order.append(("fixed", fixed_head[25], None))
    for m in ex["months"][1:]:
        order.append(("amc_month", f"{m:%b}'{m:%y} (AMC)".replace("Sep'", "Sept'"), None))
    for n, s in ex["weeks"]:
        order.append(("week", f"W-{n}", f"{s.day}-{(s + dt.timedelta(days=6)).day} {(s + dt.timedelta(days=6)):%b}"))
    for d in ex["days"]:
        order.append(("day", d, None))
    for m in ex["months"]:
        order.append(("month_status", m.strftime("%B") if m.month in (6, 7) or m.strftime("%B").lower() in ("april", "may") else ("Sept" if m.month == 9 else m.strftime("%b")), None))
    for n, _s in reversed(ex["weeks"]):
        order.append(("week_status", f"WK-{n}", None))
    for col in GP_FIXED[26:]:
        order.append(("fixed", col, None))
    groups: dict[str, list[int]] = {}
    for c, (kind, h, lab) in enumerate(order):
        if kind == "fixed":
            ws.write(2, c, h.name, head)
            ws.set_column(c, c, 14 if len(h.name) < 14 else 20, fmt[h.kind])
        elif kind in ("month", "day"):
            ws.write_datetime(2, c, dt.datetime.combine(h, dt.time()), head_date)
            ws.set_column(c, c, 10, fmt[PCT])
        else:
            ws.write(2, c, h, period_head)
            ws.set_column(c, c, 11, fmt[PCT] if kind in ("amc_month", "week") else fmt[TEXT])
        if lab:
            ws.write(1, c, lab, label)
        groups.setdefault(kind, []).append(c)
    titles = {"month": "Availability (Monthly)", "amc_month": "AMC GPs (Monthly)", "week": "Weekly – row 2 = week dates", "day": "Daily availability", "month_status": "Status (Monthly)", "week_status": "Status (Weekly)"}
    for kind, cols in groups.items():
        if kind in titles:
            ws.merge_range(0, cols[0], 0, cols[-1], titles[kind], group) if len(cols) > 1 else ws.write(0, cols[0], titles[kind], group)
    ws.set_row(2, 46)
    ws.freeze_panes(3, 11)
    if sample:
        _sample_gp(ws, order, fmt, ex)

    # ---- Master Block (row 1 group titles, header row 4)
    mb = wb.add_worksheet("Master Block")
    m_now = ex["months"][-1]
    month_names = [m.strftime("%B") if m.month in (3, 6, 7) else ("Sep" if m.month == 9 else m.strftime("%b")) for m in ex["months"]]
    mb_order: list[tuple[str, Any]] = [("fixed", c) for c in MB_FIXED[:16]]
    mb_order.append(("p", f"{(ex['months'][0] - dt.timedelta(days=1)).strftime('%B')} Avail"))
    all_start = len(mb_order)
    mb_order += [("p", f"{mn} Avg Avail" + (" TD" if i == len(month_names) - 1 else "")) for i, mn in enumerate(month_names)]
    amc_start = len(mb_order)
    mb_order += [("p", f"{mn} Avg Avail" + (" TD" if i == len(month_names) - 1 else "")) for i, mn in enumerate(month_names)]
    mb_order += [("p", f"W{n} Avail") for n, _ in ex["weeks"]]
    mb_order += [("fixed", MB_FIXED[17]), ("fixed", MB_FIXED[18]), ("p", f"{m_now:%b} 5% Inc. Target"), ("p", f"{m_now:%b} Conversion Target")]
    mb_order += [("fixed", c) for c in MB_FIXED[19:]]
    mb_order.insert(16, ("fixed", MB_FIXED[16]))  # Lot Wise right after Total RKM
    for c, (kind, h) in enumerate(mb_order):
        if kind == "fixed":
            mb.write(3, c, h.name, head)
            mb.set_column(c, c, 14, fmt[h.kind])
        else:
            mb.write(3, c, h, period_head)
            mb.set_column(c, c, 12, fmt[PCT] if "avail" in h.lower() else fmt[INT])
    mb.write(0, all_start + 1, "ALL GPs", group)
    mb.write(0, amc_start + 1, "AMC GPs", group)
    mb.set_row(3, 46)
    mb.freeze_panes(4, 6)
    if sample:
        _sample_mb(mb, mb_order, fmt, ex)

    # ---- O&M and circle sheets (optional reference sheets read by the dashboard)
    om = wb.add_worksheet("O&M")
    om.write(1, 3, "KEY NUMBERS", head)
    for j, st in enumerate(("Rajasthan", "Haryana", "Assam"), start=4):
        om.write(1, j, st, head)
    for i, lbl in enumerate(("Total Blocks", "Total Existing GPs", "Converted to NP/Permanently Closed", "Revised Existing GPs", "HOTO Done - Blocks", "HOTO Done - GPs", "AMC GPs (Total)", "Incremental GPs"), start=2):
        om.write(i, 3, lbl, bold)
    om.set_column(3, 3, 36)
    wb.close()
    return buf.getvalue()


def _sample_gp(ws: Any, order: list[tuple[str, Any, Any]], fmt: dict[str, Any], ex: dict[str, Any]) -> None:
    week_start = ex["weeks"][0][1]
    rows = [
        {"Circle": "RAJASTHAN", "BA": "Jodhpur", "DISTRICT": "JODHPUR", "BLOCK": "BAP", "Block Code": 722, "New Block Code post BoQ": 722, "New Block Name post BoQ": "BAP", "Block Changed": "No",
         "Block HoTo Status": "Done", "GP": "EXAMPLE GP One", "GP Code": 999901, "LOCATION CODE": "RJ-JOD-BAP-999901", "GP Type": "Existing", "Phase": "Phase-1", "OLT Location": "BAORI KALAN",
         "BBNL Live KM": 0.455, "BSNL Live KM": 10.925, "TOTAL RKM": 11.38, "LMS /AMC Date": dt.date(2026, 9, 26), "HOTO Date": dt.date(2026, 9, 18), "Lot wise": "LOT-6",
         "AMC / Incremental": "Incremental", "AMC Date": dt.date(2026, 9, 19), "<50 % Availability Last 4 M": 0, "FRT Code": "RJJOJO4-012", "Name of splicer": "Example Splicer",
         "Splicer Contact No.": "9876500001", "FE Name": "Example FE", "FE Contact No": "9876500002", "AM Name": "Example AM", "AM Contact No": "9876500003", "SHQ Spoc": "Example SME",
         "SHQ Spoc  Contact No": "9876500004", "5% Contractual Incremental+ Additional AMC": "Additional Plan", "Planned Date": week_start + dt.timedelta(days=2)},
        {"Circle": "HARYANA", "BA": "Ambala", "DISTRICT": "AMBALA", "BLOCK": "BARARA", "Block Code": 501, "New Block Code post BoQ": 501, "New Block Name post BoQ": "BARARA", "Block Changed": "No",
         "Block HoTo Status": "Done", "GP": "EXAMPLE GP Two", "GP Code": 999902, "LOCATION CODE": "HR-AMB-BAR-999902", "GP Type": "Existing", "Phase": "Phase-1", "OLT Location": "BARARA",
         "BBNL Live KM": 1.2, "BSNL Live KM": 3.0, "TOTAL RKM": 4.2, "HOTO Date": dt.date(2026, 8, 1), "Lot wise": "LOT-2", "<50 % Availability Last 4 M": 0, "FE Name": "Example FE 2", "AM Name": "Example AM 2",
         "SHQ Spoc": "Example SME"},
    ]
    for r, data in enumerate(rows, start=3):
        for c, (kind, h, _lab) in enumerate(order):
            if kind == "fixed":
                v = data.get(h.name)
                if v is None:
                    continue
                if isinstance(v, dt.date):
                    ws.write_datetime(r, c, dt.datetime.combine(v, dt.time()), fmt[DATE])
                else:
                    ws.write(r, c, v, fmt[h.kind])
            elif kind in ("month", "amc_month", "week"):
                ws.write(r, c, 99.5 if r == 3 else "NA")
            elif kind == "day" and h <= dt.date.today():
                ws.write(r, c, 100 if r == 3 else 0)
            elif kind in ("month_status", "week_status"):
                ws.write(r, c, "OPERATIONAL" if r == 3 else "DOWN")


def _sample_mb(ws: Any, order: list[tuple[str, Any]], fmt: dict[str, Any], ex: dict[str, Any]) -> None:
    n, s = ex["weeks"][0]
    target = s + dt.timedelta(days=3)
    rows = [
        {"State": "Rajasthan", "BA": "Jodhpur", "District": "JODHPUR", "Block Name": "BAP", "FRT CODE": "RJJOJO4-012", "Block Code": 722, "HOTO Done Date": dt.date(2026, 5, 1), "Total GP Count": 41,
         "Existing GPs": 33, "New GPs": 8, "HOTO Done GPs": 31, "AMC GP GPs": 31, "Non AMC Count": 0, "BSNL Existing RKM": 182.027, "BBNL Existing RKM": 71.459, "Total RKM": 253.486, "Lot Wise": "LOT-1",
         "AMC": 26, "Incremental": 5, "Achieved": 0, "Shortfall / Penalty": 0, "Target Week": f"WK-{n}", "Target Date": target, "Penalty Date": target + dt.timedelta(days=5)},
        {"State": "Haryana", "BA": "Ambala", "District": "AMBALA", "Block Name": "BARARA", "Block Code": 501, "Total GP Count": 35, "Existing GPs": 35, "New GPs": 0, "HOTO Done GPs": 35, "AMC GP GPs": 34,
         "Non AMC Count": 1, "BSNL Existing RKM": 130.136, "BBNL Existing RKM": 97.998, "Total RKM": 228.134, "Lot Wise": "LOT-1", "AMC": 29, "Incremental": 5, "Achieved": 0},
    ]
    for r, data in enumerate(rows, start=4):
        for c, (kind, h) in enumerate(order):
            if kind == "fixed":
                v = data.get(h.name)
                if v is None:
                    continue
                if isinstance(v, dt.date):
                    ws.write_datetime(r, c, dt.datetime.combine(v, dt.time()), fmt[DATE])
                else:
                    ws.write(r, c, v, fmt[h.kind])
            else:
                ws.write(r, c, 97.5 if "avail" in h.lower() else 3)
