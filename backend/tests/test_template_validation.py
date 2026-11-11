"""The fixed PAGMAS master data template: every column mandatory by its exact name (any order), no missing / renamed /
duplicate / unknown column, valid values, and dynamic period columns (new day, new week, month and year change) with
the week ↔ date check – nothing hard-coded. An invalid file is refused at the preview: nothing is imported."""

import datetime as dt
import io
from pathlib import Path

import pytest
import xlsxwriter
from python_calamine import CalamineWorkbook

from app.ingestion import template as T

from .conftest import login

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def grids(content: bytes) -> dict[str, list[list]]:
    wb = CalamineWorkbook.from_filelike(io.BytesIO(content))
    return {n: [list(r) for r in wb.get_sheet_by_name(n).to_python(skip_empty_area=False)] for n in wb.sheet_names}


def book(sheets: dict[str, list[list]]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    dfmt = wb.add_format({"num_format": "dd-mm-yyyy"})
    for name, rows in sheets.items():
        ws = wb.add_worksheet(name)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                if isinstance(v, dt.datetime):
                    ws.write_datetime(r, c, v, dfmt)
                elif isinstance(v, dt.date):
                    ws.write_datetime(r, c, dt.datetime.combine(v, dt.time()), dfmt)
                elif v not in ("", None):
                    ws.write(r, c, v)
    wb.close()
    return buf.getvalue()


def check(tmp_path, content: bytes) -> T.Check:
    p = tmp_path / "upload.xlsx"
    p.write_bytes(content)
    return T.validate_master(p)


def col(rows, name, header_row=2):
    return next(i for i, h in enumerate(rows[header_row]) if str(h).strip().lower() == name.lower())


def messages(c: T.Check) -> str:
    return " | ".join(p.message for p in c.errors)


@pytest.fixture
def sample():
    return grids(T.build_template(sample=True))


def test_correct_template_file_passes(tmp_path, sample):
    c = check(tmp_path, book(sample))
    assert c.ok, messages(c)
    blank = check(tmp_path, T.build_template(sample=False))
    assert not blank.ok and "No GP rows" in messages(blank)  # the blank template has to be filled first


def test_reordered_columns_are_accepted(tmp_path, sample):
    gp = sample["GP Wise Data"]
    a, b = col(gp, "Circle"), col(gp, "Approval Status")
    for row in gp:  # swap two fixed columns
        if len(row) > b:
            row[a], row[b] = row[b], row[a]
    mb = sample["Master Block"]
    s, d = col(mb, "State", 3), col(mb, "Penalty Date", 3)
    for row in mb:
        if len(row) > d:
            row[s], row[d] = row[d], row[s]
    c = check(tmp_path, book(sample))
    assert c.ok, messages(c)


def _drop(rows, i):
    for row in rows:
        if len(row) > i:
            del row[i]


def test_missing_renamed_duplicate_and_unknown_columns_are_rejected(tmp_path, sample):
    gp = sample["GP Wise Data"]
    _drop(gp, col(gp, "BA"))  # missing
    gp[2][col(gp, "AMC Date")] = "AMC Dt"  # renamed
    i = col(gp, "GP")
    for row in gp:  # duplicate
        row.append(row[i] if len(row) > i else "")
    for r, row in enumerate(gp):  # unexpected column with values
        row.append("Remarks" if r == 2 else ("x" if r > 2 else ""))
    c = check(tmp_path, book(sample))
    m = messages(c)
    assert not c.ok
    assert "Missing column: BA" in m and "Missing column: AMC Date" in m
    assert "Incorrect column name: 'AMC Dt'" in m and "the template name is 'AMC Date'" in m  # suggested, never applied
    assert "Duplicate column: GP" in m and "Incorrect column name: 'Remarks'" in m


def test_wrong_values_and_blank_required_cells_name_their_row(tmp_path, sample):
    gp = sample["GP Wise Data"]
    gp[3][col(gp, "HOTO Date")] = "31-31-2026"
    gp[3][col(gp, "TOTAL RKM")] = "abc"
    gp[4][col(gp, "GP Code")] = ""
    gp[4][col(gp, "AMC / Incremental")] = "Maybe"
    week = next(i for i, h in enumerate(gp[2]) if str(h).startswith("W-"))
    gp[3][week] = 150
    c = check(tmp_path, book(sample))
    got = {(p.row, p.column) for p in c.errors}
    assert {(4, "HOTO Date"), (4, "TOTAL RKM"), (5, "GP Code"), (5, "AMC / Incremental")} <= got
    assert any(p.row == 4 and "outside 0–100" in p.message for p in c.errors)
    assert "is not a valid date" in messages(c) and "GP Code is blank" in messages(c)


def test_duplicate_gp_code_names_both_rows(tmp_path, sample):
    gp = sample["GP Wise Data"]
    gp[4][col(gp, "GP Code")] = gp[3][col(gp, "GP Code")]
    c = check(tmp_path, book(sample))
    assert any(p.row == 5 and "first on row 4" in p.message for p in c.errors)


def _add_week(gp, n, start: dt.date, days: int = 7):
    """A new W-nn column (with its dates above) right after the last W-nn, and its daily dates after the last day."""
    weeks = [i for i, h in enumerate(gp[2]) if str(h).startswith("W-")]
    for row in gp:
        while len(row) <= max(weeks) + 1:
            row.append("")
    for r, row in enumerate(gp):
        row.insert(weeks[0], {1: f"{start.day}-{(start + dt.timedelta(days=6)).day} {(start + dt.timedelta(days=6)):%b}", 2: f"W-{n}"}.get(r, 99.0 if r == 3 else ""))
    dates = [i for i, h in enumerate(gp[2]) if isinstance(h, dt.date) and i > weeks[-1] + 1]
    last = dates[-1]
    for k in range(days):
        day = gp[2][last] + dt.timedelta(days=1 + k) if isinstance(gp[2][last], dt.date) else None
        for r, row in enumerate(gp):
            row.insert(last + 1 + k, {2: day}.get(r, ""))
    return gp


def test_new_week_and_new_dates_need_no_change(tmp_path):
    sample = grids(T.build_template(sample=True, today=dt.date(2026, 11, 10)))
    gp = sample["GP Wise Data"]
    weeks = [(i, h) for i, h in enumerate(gp[2]) if str(h).startswith("W-")]
    n = max(int(h[2:]) for _, h in weeks)
    days = [h for h in gp[2] if isinstance(h, dt.date)]
    start = max(days) + dt.timedelta(days=1)
    _add_week(gp, n + 1, start)
    c = check(tmp_path, book(sample))
    assert c.ok, messages(c)


@pytest.mark.parametrize("today", [dt.date(2026, 12, 2), dt.date(2027, 1, 4), dt.date(2027, 12, 29)], ids=["month-change", "year-change", "53-week-year"])
def test_month_and_year_transitions(tmp_path, today):
    c = check(tmp_path, T.build_template(sample=True, today=today))
    assert c.ok, messages(c)
    heads = grids(T.build_template(sample=True, today=today))["GP Wise Data"][2]
    days = sorted(h for h in heads if isinstance(h, dt.date))
    assert len({(d.year, d.month) for d in days}) >= 1


def test_week_must_match_its_dates(tmp_path, sample):
    gp = sample["GP Wise Data"]
    w = next(i for i, h in enumerate(gp[2]) if str(h).startswith("W-"))
    gp[1][w] = "1-6 Nov"  # not a 7-day range
    c = check(tmp_path, book(sample))
    assert "not a 7-day range" in messages(c)
    sample = grids(T.build_template(sample=True))
    mb = sample["Master Block"]
    t = col(mb, "Target Date", 3)
    mb[4][t] = mb[4][t] + dt.timedelta(days=14)  # outside its Target Week
    c = check(tmp_path, book(sample))
    assert any(p.sheet == "Master Block" and p.row == 5 and "Week does not match the date" in p.message for p in c.errors)


def test_week_labels_must_follow_their_dates(tmp_path, sample):
    gp = sample["GP Wise Data"]
    weeks = [i for i, h in enumerate(gp[2]) if str(h).startswith("W-")]
    assert len(weeks) >= 2
    a, b = weeks[0], weeks[1]
    gp[1][a], gp[1][b] = gp[1][b], gp[1][a]  # W-nn kept, its dates swapped with the next week's
    c = check(tmp_path, book(sample))
    assert not c.ok and "Week numbers out of order" in messages(c)
    sample = grids(T.build_template(sample=True))
    gp = sample["GP Wise Data"]
    w = next(i for i, h in enumerate(gp[2]) if str(h).startswith("W-"))
    gp[1][w] = "1-7 Jan"  # a real 7-day range, but not 7 days from the neighbouring week
    c = check(tmp_path, book(sample))
    assert not c.ok and "weeks must be 7 days apart" in messages(c)


def test_master_block_columns_are_all_required(tmp_path, sample):
    mb = sample["Master Block"]
    _drop(mb, col(mb, "Total GP Count", 3))
    i = next(i for i, h in enumerate(mb[3]) if "avg avail" in str(h).lower())
    _drop(mb, i)  # one month's availability of the ALL GPs group – the AMC GPs one stays
    c = check(tmp_path, book(sample))
    assert "Missing column: Total GP Count" in messages(c)


@pytest.mark.skipif(not (RAW / "Master Data V8.2 Daily track 10-11-26.xlsb").exists(), reason="reference file not available")
def test_the_reference_file_passes():
    c = T.validate_master(RAW / "Master Data V8.2 Daily track 10-11-26.xlsb")
    assert c.ok, messages(c)
    assert c.warning_count  # known harmless issues (OLT location 0, GP codes with a letter O) are warnings only


def test_preview_refuses_a_file_that_is_not_the_template(client, tmp_path):
    csrf = login(client)
    sample = grids(T.build_template(sample=True))
    gp = sample["GP Wise Data"]
    _drop(gp, col(gp, "LOCATION CODE"))
    r = client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": ("bad.xlsx", book(sample))}, data={"kind": "master"}).json()
    assert r["canImport"] is False and r["stage"] == "template" and r["token"] is None
    assert r["error"].startswith("Your uploaded file does not match the required PAGMAS Excel template")
    assert any(e["message"] == "Missing column: LOCATION CODE" for e in r["templateErrors"])
    t = client.get("/api/v1/ingestion/template/master.xlsx", params={"sample": True})
    assert t.status_code == 200 and "PAGMAS Master Data Sample.xlsx" in t.headers["content-disposition"]
