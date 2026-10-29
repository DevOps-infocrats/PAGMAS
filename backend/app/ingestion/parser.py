"""Parse the 'Master Data … Daily track' workbook into normalised records.

Columns are located by header text (not position) so new template versions
with moved/added columns keep working. Every value that cannot be trusted is
recorded as a validation issue instead of being silently guessed.
"""

from __future__ import annotations

import calendar
import datetime as dt
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .column_map import GP_HEADER_ANCHORS, GP_REQUIRED, MASTER_BLOCK_HEADER_ANCHORS, MASTER_BLOCK_REQUIRED, ColumnMap, find_header_row, load_column_map, locate, resolve_sheet, suggest
from .workbook import Grid, WorkbookError, as_date, clean_code, code_key, is_blank, norm, open_workbook, read_sheet

# Display names of the sheets in messages; the accepted names (and every column name) live in column_map.py
# and can be extended with data/column_map.json without code changes.
GP_SHEET = "GP Wise Data"
MASTER_BLOCK_SHEET = "Master Block"
OM_SHEET = "O&M"

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({"sept": 9, "june": 6, "july": 7})
WEEK_RE = re.compile(r"^w-?(\d{1,2})$")
AMC_MONTH_RE = re.compile(r"^([a-z]+)'(\d{2}) \(amc\)$")
WEEK_RANGE_RE = re.compile(r"^(\d{1,2})\s*-\s*(\d{1,2})\s+([a-z]+)$")
DATE_TEXT_RE = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")


@dataclass
class Issue:
    sheet: str
    severity: str  # info | warning | critical
    code: str
    message: str
    row_number: int | None = None
    column: str | None = None
    gp_code: str | None = None


@dataclass
class ParsedWorkbook:
    gps: list[dict[str, Any]] = field(default_factory=list)
    availability: list[tuple[str, str, str, float]] = field(default_factory=list)  # (gp, kind, period, value)
    weeks: list[dict[str, Any]] = field(default_factory=list)
    data_as_of: dt.date | None = None
    issues: list[Issue] = field(default_factory=list)
    reported: list[dict[str, Any]] = field(default_factory=list)
    master_blocks: list[dict[str, Any]] = field(default_factory=list)
    circle_sheets: list[dict[str, Any]] = field(default_factory=list)  # One-Time-Up rows of the circle sheets
    amc_plan: list[dict[str, Any]] = field(default_factory=list)  # GP-wise AMC conversion plan (planned / achieved dates)
    # What the file looked like (for the upload report): sheet names, GP-sheet headers, headers nobody reads
    sheet_names: list[str] = field(default_factory=list)
    gp_headers: list[str] = field(default_factory=list)
    unknown_columns: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    rows_total: int = 0
    rows_rejected: int = 0


# ---------------------------------------------------------------- helpers


def _text(v: Any) -> str | None:
    if is_blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v)).strip()


_code = clean_code
BLANK_TEXT = {"", "-", "–", "NA", "N/A"}


def _number(v: Any) -> tuple[float | None, bool]:
    """Returns (value, was_valid). Numeric strings like '4.378', '1,234.5' and '99.5%' are accepted; '-' / 'NA' are blank."""
    if is_blank(v):
        return None, True
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        num = float(v)
    else:
        s = re.sub(r"[\s,]", "", str(v))
        if s.upper() in BLANK_TEXT:
            return None, True
        try:
            num = float(s[:-1] if s.endswith("%") else s)
        except ValueError:
            return None, False
    return (num, True) if math.isfinite(num) else (None, False)


def _availability(v: Any) -> tuple[float | None, bool]:
    """'NA'/blank -> None (valid). Numbers must be within 0..100."""
    if is_blank(v) or (isinstance(v, str) and v.strip().upper() in {"NA", "N/A", "#N/A"}):
        return None, True
    num, ok = _number(v)
    if not ok or num is None or not (0.0 <= num <= 100.0 + 1e-9):
        return None, False
    return min(num, 100.0), True


def _parse_week_range(label: Any, last_day: dt.date) -> tuple[dt.date, dt.date] | None:
    """'2-8 Oct' -> (2 Oct, 8 Oct); '25-1 Oct' -> (25 Sep, 1 Oct); '28-3 Sept' -> (28 Aug, 3 Sep). The year is the one of
    the file's last daily date, or the year before when that puts the week end more than 7 days after it ('22-28 Dec'
    in a January file)."""
    m = WEEK_RANGE_RE.match(norm(label))
    if not m:
        return None
    d1, d2, mon = int(m.group(1)), int(m.group(2)), MONTHS.get(m.group(3)[:4]) or MONTHS.get(m.group(3)[:3])
    if not mon:
        return None
    try:
        year = last_day.year
        if dt.date(year, mon, d2) > last_day + dt.timedelta(days=7):
            year -= 1
        end = dt.date(year, mon, d2)
        start_month, start_year = (mon, year) if d1 <= d2 else ((mon - 1) or 12, year if mon > 1 else year - 1)
        start = dt.date(start_year, start_month, d1)
    except ValueError:
        raise WorkbookError(f"Week label '{label}' is not a valid date range") from None
    return start, end


# ---------------------------------------------------------------- GP sheet


def _locate_columns(header: list[Any], issues: list[Issue], cmap: ColumnMap, sheet: str = GP_SHEET) -> dict[str, int]:
    loc = locate(header, cmap.gp)
    found = loc.columns
    missing = [k for k in GP_REQUIRED if k not in found]
    if missing:
        taken = set(found.values())
        parts = []
        for k in missing:
            hint = suggest(header, cmap.gp[k], taken)
            parts.append(f"{k} (accepted names: {', '.join(cmap.gp[k])})" + (f" - similar column in the file: {hint}; if it is the same, add it to data/column_map.json under gpColumns.{k}" if hint else ""))
        raise WorkbookError(f"'{sheet}' is missing required columns: " + "; ".join(parts))
    for k in cmap.gp:
        if k not in found and k not in GP_REQUIRED:
            issues.append(Issue(sheet, "warning", "COLUMN_MISSING", f"Optional column for '{k}' not found (accepted names: {', '.join(cmap.gp[k])})"))
    for k, headers in loc.duplicates.items():
        issues.append(Issue(sheet, "warning", "COLUMN_DUPLICATE", f"{len(headers)} columns match '{k}' ({', '.join(headers)}) - '{headers[0]}' was used"))
    return found


def _locate_periods(grid: Grid, hdr: int) -> dict[str, Any]:
    header = grid[hdr]
    above = grid[hdr - 1] if hdr > 0 else [None] * len(header)
    weekly: list[tuple[int, int]] = []  # (col, week number)
    amc_monthly: list[tuple[int, str]] = []
    for c, h in enumerate(header):
        n = norm(h)
        if m := WEEK_RE.match(n):
            weekly.append((c, int(m.group(1))))
        elif m := AMC_MONTH_RE.match(n):
            mon = MONTHS.get(m.group(1)[:4]) or MONTHS.get(m.group(1)[:3])
            if mon:
                amc_monthly.append((c, f"{2000 + int(m.group(2))}-{mon:02d}"))
    if not weekly:
        raise WorkbookError("No weekly availability columns (W-nn) found")
    first_week_col = min(c for c, _ in weekly)
    last_week_col = max(c for c, _ in weekly)

    monthly: list[tuple[int, str]] = []
    for c in range(first_week_col):
        d = as_date(header[c])
        if d and d.day == 1:
            monthly.append((c, f"{d.year}-{d.month:02d}"))

    daily: list[tuple[int, dt.date]] = []
    c = last_week_col + 1
    while c < len(header) and (d := as_date(header[c])):
        daily.append((c, d))
        c += 1
    if not daily:
        raise WorkbookError("No daily availability columns found after the weekly columns")
    if (stray := next((cc for cc in range(c, len(header)) if as_date(header[cc])), None)) is not None:
        raise WorkbookError(
            f"Daily date columns must be contiguous: column {_col(c)} ('{_text(header[c]) or ''}') interrupts them and date column {_col(stray)} ({as_date(header[stray])}) follows"
        )
    for kind, cols in (("weekly", [(cc, f"W-{n}") for cc, n in weekly]), ("monthly", monthly), ("AMC monthly", amc_monthly), ("daily", [(cc, d.isoformat()) for cc, d in daily])):
        dup = [p for p, n in Counter(p for _, p in cols).items() if n > 1]
        if dup:
            where = "; ".join(f"{p} (columns {', '.join(_col(cc) for cc, q in cols if q == p)})" for p in dup)
            raise WorkbookError(f"Duplicate {kind} availability columns: {where} - each period may appear only once")
    return {"weekly": weekly, "amc_monthly": amc_monthly, "monthly": monthly, "daily": daily, "above": above}


def _col(c: int) -> str:
    """0-based column index -> Excel letters (0 -> A, 27 -> AB)."""
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_gp_sheet(grid: Grid, out: ParsedWorkbook, cmap: ColumnMap | None = None, sheet: str = GP_SHEET) -> None:
    cmap = cmap or load_column_map()
    hdr = find_header_row(grid, cmap.gp, GP_HEADER_ANCHORS)
    if hdr is None:
        need = "; ".join(f"{a}: {' / '.join(cmap.gp[a])}" for a in GP_HEADER_ANCHORS)
        raise WorkbookError(f"'{sheet}': header row not found in the first 15 rows (it must contain {need})")
    header = grid[hdr]
    cols = _locate_columns(header, out.issues, cmap, sheet)
    periods = _locate_periods(grid, hdr)
    # Record the file's layout for the upload report: every non-period header, and the ones no field uses.
    period_cols = {c for c, _ in periods["weekly"]} | {c for c, _ in periods["amc_monthly"]} | {c for c, _ in periods["monthly"]} | {c for c, _ in periods["daily"]}
    used = set(cols.values())
    for c, h in enumerate(header):
        label = _text(h)
        if not label or c in period_cols or as_date(h):
            continue
        out.gp_headers.append(label)
        if c not in used:
            out.unknown_columns.append(label)
    out.missing_optional = [k for k in cmap.gp if k not in cols]
    daily = periods["daily"]
    last_day = max(d for _, d in daily)

    # Weeks from the label row above the W-nn headers (e.g. "2-8 Oct").
    for c, number in sorted(periods["weekly"], key=lambda x: x[1]):
        rng = _parse_week_range(periods["above"][c], last_day)
        if not rng or (rng[1] - rng[0]).days != 6:
            raise WorkbookError(f"Week W-{number}: date range label '{periods['above'][c]}' could not be parsed as a 7-day range")
        out.weeks.append({"code": f"W-{number}", "number": number, "start_date": rng[0], "end_date": rng[1]})

    seen: set[str] = set()
    last_day_with_data: dt.date | None = None
    col_label = {v: k for k, v in cols.items()}

    def cell(row: list[Any], key: str) -> Any:
        idx = cols.get(key)
        return row[idx] if idx is not None and idx < len(row) else None

    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        excel_row = i + 1
        if all(is_blank(v) for v in row[:15]):
            continue
        circle_raw = _text(cell(row, "circle"))
        if circle_raw == "@":  # end-of-data sentinel used in the template
            continue
        out.rows_total += 1
        gp_code = _code(cell(row, "gp_code"))
        if not gp_code or not circle_raw:
            out.rows_rejected += 1
            out.issues.append(Issue(sheet, "critical", "ROW_REJECTED", "Row has no GP code or circle", excel_row))
            continue
        if code_key(gp_code) in seen:
            out.rows_rejected += 1
            out.issues.append(Issue(sheet, "critical", "DUPLICATE_GP", f"Duplicate GP code {gp_code}; later row ignored", excel_row, "GP Code", gp_code))
            continue
        seen.add(code_key(gp_code))

        def warn(code: str, msg: str, column: str | None = None, severity: str = "warning") -> None:
            out.issues.append(Issue(sheet, severity, code, msg, excel_row, column, gp_code))

        location = {"district": _text(cell(row, "district")), "block_name": _text(cell(row, "block_name")), "block_code": _code(cell(row, "block_code"))}
        if missing_loc := [k.replace("_", " ") for k, v in location.items() if not v]:
            warn("BLOCK_MISSING", f"{', '.join(missing_loc).capitalize()} missing - shown as UNKNOWN", "Block Code" if not location["block_code"] else None)

        nums: dict[str, float | None] = {}
        for key, label in (("bbnl_km", "BBNL Live KM"), ("bsnl_km", "BSNL Live KM"), ("total_rkm", "TOTAL RKM")):
            val, ok = _number(cell(row, key))
            if not ok:
                warn("INVALID_NUMBER", f"{label} '{cell(row, key)}' is not a number", label)
            elif val is not None and val < 0:
                warn("INVALID_NUMBER", f"{label} is negative ({val})", label)
                val = None
            nums[key] = val
        if nums["total_rkm"] is None:
            warn("RKM_MISSING", "TOTAL RKM missing - counted as 0 RKM", "TOTAL RKM")
        if None not in (nums["bbnl_km"], nums["bsnl_km"], nums["total_rkm"]) and abs(nums["bbnl_km"] + nums["bsnl_km"] - nums["total_rkm"]) > 0.01:  # type: ignore[operator]
            warn("RKM_MISMATCH", f"BBNL ({nums['bbnl_km']}) + BSNL ({nums['bsnl_km']}) ≠ TOTAL RKM ({nums['total_rkm']}); TOTAL RKM used", "TOTAL RKM")

        dates: dict[str, dt.date | None] = {}
        for key, label in (("hoto_date", "HOTO Date"), ("amc_date", "AMC Date"), ("lms_amc_date", "LMS /AMC Date"), ("letter_date", "Letter submission date")):
            raw = cell(row, key)
            d = as_date(raw)
            if d is None and not is_blank(raw):
                warn("INVALID_DATE", f"{label} '{raw}' is not a date", label)
            dates[key] = d

        olt = _text(cell(row, "olt_location"))
        if olt and (DATE_TEXT_RE.match(olt) or re.fullmatch(r"[\d.]+", olt)):
            warn("OLT_INVALID", f"OLT location '{olt}' is not a location name", "OLT Location")
            olt = None
        elif olt is None:
            warn("OLT_MISSING", "OLT location missing", "OLT Location", "info")

        am = _text(cell(row, "am_name"))
        if am and re.fullmatch(r"[\d.]+", am):
            warn("AM_MISSING", f"AM name '{am}' is not a name", "AM Name", "info")
            am = None

        category_raw = _text(cell(row, "amc_category"))
        category = category_raw.upper() if category_raw else None
        if category and category not in {"AMC", "INCREMENTAL"}:
            warn("INVALID_CATEGORY", f"AMC / Incremental value '{category_raw}' not recognised", "AMC / Incremental")
            category = None
        if bool(category) != bool(dates["amc_date"]):
            warn("AMC_INCONSISTENT", "AMC / Incremental and AMC Date do not agree", "AMC Date")
        np_status = _text(cell(row, "np_status"))
        if dates["amc_date"] and not dates["hoto_date"]:
            warn("AMC_WITHOUT_HOTO", "AMC date present but HOTO date missing", "AMC Date")
        if dates["amc_date"] and dates["hoto_date"] and dates["amc_date"] < dates["hoto_date"]:
            warn("AMC_BEFORE_HOTO", f"AMC date {dates['amc_date']} is before HOTO date {dates['hoto_date']}", "AMC Date")
        if np_status and dates["hoto_date"]:
            warn("NP_WITH_HOTO", f"GP marked '{np_status}' but has a HOTO date", "Converted to NP & Closed", "info")

        out.gps.append(
            {
                "gp_code": gp_code,
                "source_row": excel_row,
                "location_code": _text(cell(row, "location_code")),
                "name": _text(cell(row, "gp_name")) or gp_code,
                "circle": circle_raw.upper(),
                "ba": _text(cell(row, "ba")),
                "district": (location["district"] or "UNKNOWN").upper(),
                "block_name": (location["block_name"] or "UNKNOWN").upper(),
                "block_code": location["block_code"] or "UNKNOWN",
                "block_hoto_status": _text(cell(row, "block_hoto_status")),
                "np_status": np_status,
                "gp_type": _text(cell(row, "gp_type")),
                "phase": _text(cell(row, "phase")),
                "lot": _text(cell(row, "lot")),
                "olt_location": olt.upper() if olt else None,
                "bbnl_km": nums["bbnl_km"],
                "bsnl_km": nums["bsnl_km"],
                "total_rkm": nums["total_rkm"] or 0.0,
                "hoto_date": dates["hoto_date"],
                "lms_amc_date": dates["lms_amc_date"],
                "letter_date": dates["letter_date"],
                "amc_category": category,
                "amc_date": dates["amc_date"],
                "am_name": am,
            }
        )

        # GP-wise AMC conversion plan: kept only for GPs that are in the plan (a category or a planned / achieved date).
        plan_dates: dict[str, dt.date | None] = {}
        for key, label in (("planned_date", "Planned Date"), ("ach_date", "Ach Date"), ("plan_letter_date", "Letter submission Date")):
            raw = cell(row, key)
            d = as_date(raw)
            if d is None and not is_blank(raw):
                warn("INVALID_DATE", f"{label} '{raw}' is not a date", label)
            plan_dates[key] = d
        plan_category = _text(cell(row, "plan_category"))
        if plan_category or plan_dates["planned_date"] or plan_dates["ach_date"]:
            status = _text(cell(row, "plan_status"))
            out.amc_plan.append(
                {
                    "gp_code": gp_code,
                    "category": plan_category,
                    "planned_date": plan_dates["planned_date"],
                    "ach_date": plan_dates["ach_date"],
                    "current_status": status.upper() if status and status != "0" else None,
                    "letter_status": _text(cell(row, "plan_letter_status")),
                    "letter_date": plan_dates["plan_letter_date"],
                    "approval_status": _text(cell(row, "plan_approval_status")),
                }
            )

        # Availability values (only non-NA values are stored; absent = NA).
        def take(kind: str, period: str, c: int, label: str) -> float | None:
            raw = row[c] if c < len(row) else None
            val, ok = _availability(raw)
            if not ok:
                warn("INVALID_AVAILABILITY", f"{label}: '{raw}' is not a percentage between 0 and 100", label)
            elif val is not None:
                out.availability.append((gp_code, kind, period, val))
            return val

        for c, period in periods["monthly"]:
            take("M", period, c, f"Availability {period}")
        for c, period in periods["amc_monthly"]:
            take("MA", period, c, f"AMC availability {period}")
        for c, number in periods["weekly"]:
            take("W", f"W-{number}", c, f"W-{number}")
        for c, day in daily:
            if take("D", day.isoformat(), c, f"Daily {day.isoformat()}") is not None:
                if last_day_with_data is None or day > last_day_with_data:
                    last_day_with_data = day

    if not out.gps:
        raise WorkbookError(f"'{sheet}' contains no GP rows")
    if last_day_with_data is None:
        raise WorkbookError(f"No daily availability values found in '{sheet}'")
    if last_day_with_data > dt.date.today() + dt.timedelta(days=1):
        col = next(c for c, d in daily if d == last_day_with_data)
        raise WorkbookError(f"'{sheet}' column {_col(col)}: daily date {last_day_with_data} is in the future - check the date headers")
    out.data_as_of = last_day_with_data
    _derive_missing_weeks(out, sheet)


def _derive_missing_weeks(out: ParsedWorkbook, sheet: str = GP_SHEET) -> None:
    """Daily data beyond the file's last W-nn week (e.g. data till 18 Oct, last week column W-42 = 9-15 Oct): add the
    next Fri–Thu weeks so the dashboard reaches the data date. Their weekly availability follows the file's own rule
    for its week columns (verified exact on W-39…W-41, and on the in-progress W-42 up to its data date): per GP under
    AMC by the week's end, the mean of its daily values from the later of the week start and its AMC date up to the
    week end or the data date. GPs without any daily value in that range stay NA."""
    if not out.weeks or out.data_as_of is None:
        return
    last = max(out.weeks, key=lambda w: w["end_date"])  # not the highest number: W-52 is followed by W-1
    first_new = last["end_date"] + dt.timedelta(days=1)
    if out.data_as_of < first_new:
        return
    amc = {g["gp_code"]: g["amc_date"] for g in out.gps}
    daily: dict[str, list[tuple[dt.date, float]]] = {}
    for gp, kind, period, val in out.availability:
        if kind == "D":
            day = dt.date.fromisoformat(period)
            if first_new <= day <= out.data_as_of:
                daily.setdefault(gp, []).append((day, val))
    number, start, prev_end = last["number"], first_new, last["end_date"]
    while start <= out.data_as_of:
        end = start + dt.timedelta(days=6)
        number = 1 if end.year > prev_end.year else number + 1  # weeks are numbered by the year of their end date
        prev_end = end
        code = f"W-{number}"
        out.weeks.append({"code": code, "number": number, "start_date": start, "end_date": end})
        for gp, vals in daily.items():
            amc_date = amc.get(gp)
            if amc_date is None or amc_date > end:
                continue
            sel = [v for day, v in vals if start <= day <= end and day >= amc_date]
            if sel:
                out.availability.append((gp, "W", code, sum(sel) / len(sel)))
        upto = min(end, out.data_as_of)
        out.issues.append(
            Issue(
                sheet,
                "info",
                "WEEK_DERIVED",
                f"{code} ({start:%d %b} – {end:%d %b}) is not a column of the file: added because daily data runs to {out.data_as_of:%d %b}; "
                f"its weekly availability is the mean of the daily values up to {upto:%d %b} (AMC GPs, from their AMC date), as in the file's own week columns",
            )
        )
        start = end + dt.timedelta(days=1)


# ---------------------------------------------------------------- reference sheets


def _parse_master_block(grid: Grid, out: ParsedWorkbook, cmap: ColumnMap | None = None, sheet: str = MASTER_BLOCK_SHEET) -> None:
    cmap = cmap or load_column_map()
    hdr = find_header_row(grid, cmap.master_block, MASTER_BLOCK_HEADER_ANCHORS)
    if hdr is None:
        raise WorkbookError("Header row not found (needs " + "; ".join(" / ".join(cmap.master_block[a]) for a in MASTER_BLOCK_HEADER_ANCHORS) + ")")
    loc = locate(grid[hdr], cmap.master_block)
    missing = [k for k in MASTER_BLOCK_REQUIRED if k not in loc.columns]
    if missing:
        raise WorkbookError(f"missing columns: {', '.join(missing)}")
    for k, headers in loc.duplicates.items():
        out.issues.append(Issue(sheet, "warning", "COLUMN_DUPLICATE", f"{len(headers)} columns match '{k}' ({', '.join(headers)}) - '{headers[0]}' was used"))
    idx = loc.columns
    get = lambda row, key: row[idx[key]] if key in idx and idx[key] < len(row) else None  # noqa: E731
    first_row: dict[str, int] = {}
    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        code = _code(get(row, "block_code"))
        state = _text(get(row, "state"))
        if not code or not state:
            continue
        if code in first_row:
            out.issues.append(Issue(sheet, "warning", "DUPLICATE_BLOCK", f"Block code {code} also on row {first_row[code]}; this later row is used", i + 1, "Block Code"))
        first_row.setdefault(code, i + 1)

        def as_int(key: str) -> int | None:
            v, ok = _number(get(row, key))
            return int(v) if ok and v is not None else None

        out.master_blocks.append(
            {
                "block_code": code,
                "state": state.upper(),
                "block_name": (_text(get(row, "block_name")) or "").upper(),
                "total_gp_count": as_int("total_gp_count"),
                "existing_gps": as_int("existing_gps"),
                "new_gps": as_int("new_gps"),
                "block_status": _text(get(row, "block_status")),
            }
        )


def _parse_key_numbers(grid: Grid, out: ParsedWorkbook) -> None:
    for r, row in enumerate(grid[:10]):
        for c, v in enumerate(row):
            if norm(v) == "key numbers":
                states = [(cc, _text(row[cc])) for cc in range(c + 1, len(row)) if _text(row[cc])]
                for rr in range(r + 1, len(grid)):
                    metric = _text(grid[rr][c]) if c < len(grid[rr]) else None
                    if not metric:
                        break
                    for cc, state in states:
                        raw = grid[rr][cc] if cc < len(grid[rr]) else None
                        num, ok = _number(raw)
                        out.reported.append(
                            {
                                "state": (state or "").upper(),
                                "metric": metric,
                                "value_num": num if ok else None,
                                "value_text": None if ok else _text(raw),
                            }
                        )
                return


# ---------------------------------------------------------------- entry point


# ---------------------------------------------------------------- circle sheets (One-Time Up)

ONE_TIME_UP_ROWS = {"one time up gps": "oneTimeUpGps", "one time up amc": "oneTimeUpAmc", "one time up non-amc": "oneTimeUpNonAmc"}


def _circle_column_key(header: Any, as_of: dt.date) -> str | None:
    """Circle-sheet column header -> period key: "Sept" -> "2026-09" (the latest such month not after `as_of`),
    "WK-40" -> "W-40"; date columns are skipped."""
    if isinstance(header, (dt.date, dt.datetime)):
        return None
    text = norm(header)
    if m := re.fullmatch(r"wk-?\s*(\d{1,2})", text):
        return f"W-{int(m.group(1))}"
    month = MONTHS.get(text[:3])
    if not month:
        return None
    return f"{as_of.year if month <= as_of.month else as_of.year - 1}-{month:02d}"


def _parse_circle_sheets(wb: Any, out: ParsedWorkbook) -> None:
    """The external one-time-up report rows of the sheets named after each circle (optional sheets)."""
    if out.data_as_of is None:
        return
    names = {n.strip().upper(): n for n in wb.sheet_names}
    for circle in sorted({g["circle"] for g in out.gps}):
        sheet = names.get(str(circle).upper())
        if not sheet:
            out.issues.append(Issue(str(circle), "info", "CIRCLE_SHEET", f"No '{circle}' sheet - One-Time-Up rows not available for this circle"))
            continue
        grid = read_sheet(wb, sheet)
        hdr = next((i for i, r in enumerate(grid[:6]) if r and norm(r[0]) == "parameters"), None)
        if hdr is None:
            out.issues.append(Issue(sheet, "warning", "CIRCLE_SHEET", "Header row 'Parameters' not found - One-Time-Up rows skipped"))
            continue
        keys = [_circle_column_key(h, out.data_as_of) for h in grid[hdr]]
        seen: set[tuple[str, str]] = set()
        for row in grid[hdr + 1 :]:
            metric = ONE_TIME_UP_ROWS.get(norm(row[0]) if row else "")
            if not metric:
                continue
            for k, v in zip(keys, row):
                if k and isinstance(v, (int, float)) and not isinstance(v, bool) and (metric, k) not in seen:
                    seen.add((metric, k))  # first value wins when a period column repeats
                    out.circle_sheets.append({"circle": str(circle), "metric": metric, "period": k, "value": float(v)})


def parse_workbook(path: Path) -> ParsedWorkbook:
    wb = open_workbook(path)
    out = ParsedWorkbook(sheet_names=list(wb.sheet_names))
    cmap = load_column_map()
    for problem in cmap.problems:
        out.issues.append(Issue("column_map.json", "warning", "COLUMN_MAP", problem))
    gp_sheet = resolve_sheet(wb.sheet_names, "gp", cmap)
    if gp_sheet is None:
        raise WorkbookError(f"Required sheet not found: {' / '.join(cmap.sheets['gp'])} (found: {', '.join(wb.sheet_names)}) - a renamed sheet can be added to data/column_map.json under sheets.gp")
    _parse_gp_sheet(read_sheet(wb, gp_sheet), out, cmap, gp_sheet)
    optional = (("masterBlock", MASTER_BLOCK_SHEET, lambda g, n: _parse_master_block(g, out, cmap, n)), ("om", OM_SHEET, lambda g, n: _parse_key_numbers(g, out)))
    for key, label, fn in optional:
        name = resolve_sheet(wb.sheet_names, key, cmap)
        try:
            if name is None:
                raise WorkbookError(f"Sheet {' / '.join(cmap.sheets[key])} not found")
            fn(read_sheet(wb, name), name)
        except WorkbookError as exc:  # reference sheets are optional
            out.issues.append(Issue(name or label, "warning", "REFERENCE_SHEET", f"{exc} - reconciliation for this sheet skipped"))
    try:
        _parse_circle_sheets(wb, out)
    except WorkbookError as exc:
        out.issues.append(Issue("circle sheets", "warning", "CIRCLE_SHEET", f"{exc} - One-Time-Up rows skipped"))
    return out
