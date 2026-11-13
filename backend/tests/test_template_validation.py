"""Upload column rules (template.py) and the flexible day / week / month handling (parser.py, history.py).

REQUIRED columns must exist (any order, case / spaces / punctuation ignored) – a missing one rejects the file and the
message names it first. OPTIONAL columns may be absent and unknown columns are ignored (both reported). Day / week /
month columns are recognised by pattern and are NEVER a reason to reject: gaps, duplicates and a file with only the
current week are warnings, and the weeks / months a later file drops stay from earlier uploads."""

import datetime as dt
import io
from pathlib import Path

import pandas as pd
import pytest
import xlsxwriter
from python_calamine import CalamineWorkbook

from app.ingestion import template as T

from .conftest import login

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
GP_HDR, MB_HDR = 2, 3  # header rows (0-based) of the template sheets
TODAY = dt.date(2026, 3, 10)  # template data older than the test dataset – an import of it is never activated


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


def parse(tmp_path, content: bytes):
    from app.ingestion.parser import parse_workbook

    p = tmp_path / "parse.xlsx"
    p.write_bytes(content)
    return parse_workbook(p)


def col(rows, name, hdr=GP_HDR):
    return next(i for i, h in enumerate(rows[hdr]) if str(h).strip().lower() == name.lower())


def drop(rows, i):
    for row in rows:
        if len(row) > i:
            del row[i]


def add_col(rows, header, values, hdr=GP_HDR):
    for r, row in enumerate(rows):
        row.append(header if r == hdr else (values if r > hdr and any(v not in ("", None) for v in row[:5]) else ""))


def errors(c: T.Check) -> str:
    return " | ".join(p.message for p in c.errors)


@pytest.fixture
def sample():
    return grids(T.build_template("master", today=TODAY))


def sheet_report(c: T.Check, name: str) -> dict:
    return next(s.json() for s in c.sheets if s.sheet == name)


# ---------------------------------------------------------------- structure: required / optional / unknown


@pytest.mark.skipif(not (RAW / "Master Data V8.2 Daily track 10-11-26.xlsb").exists(), reason="reference file not available")
@pytest.mark.parametrize("name", ["Master Data V8.2 Daily track 10-11-26.xlsb", "Master Data V8.2 Daily track 04-11-26.xlsb"])
def test_the_reference_files_pass_with_every_column_in_a_bucket(name):
    if not (RAW / name).exists():
        pytest.skip("reference file not available")
    c = T.validate_master(RAW / name)
    assert c.ok, errors(c)
    gp, mb = sheet_report(c, "GP Wise Data"), sheet_report(c, "Master Block")
    assert gp["requiredOk"] and mb["requiredOk"] and gp["headerRow"] == 3 and mb["headerRow"] == 4
    assert gp["unused"] == [] and mb["unused"] == []  # every column of the BSNL sheet is known
    assert gp["periods"]["date"] > 30 and gp["periods"]["week"] >= 6 and mb["periods"]["week"] >= 6


def test_the_template_passes_and_shows_its_two_sections(tmp_path, sample):
    c = check(tmp_path, T.build_template("master", today=TODAY))
    assert c.ok, errors(c)
    gp, mb = sample["GP Wise Data"], sample["Master Block"]
    assert gp[0][0].startswith("SECTION A – REQUIRED") and any(str(v).startswith("SECTION B – Availability columns: EXAMPLES") for v in gp[0])
    assert "NEVER rejected" in next(v for v in gp[0] if str(v).startswith("SECTION B"))
    assert [h for h in gp[GP_HDR][: len(T.GP_REQUIRED)]] == [x.name for x in T.GP_REQUIRED]  # Section A = only the required columns
    assert [h for h in mb[MB_HDR][: len(T.MB_REQUIRED)]] == [x.name for x in T.MB_REQUIRED]
    assert gp[GP_HDR + 1][col(gp, "GP Code")] == 999901 and gp[GP_HDR + 2][col(gp, "GP Code")] == 999902  # two example rows
    w = next(i for i, h in enumerate(gp[GP_HDR]) if str(h).startswith("W-"))
    assert "-" in str(gp[1][w])  # the 7-day range above the week
    assert set(grids(T.build_template("gp", today=TODAY))) == {"Read Me", "GP Wise Data"}
    assert set(grids(T.build_template("block", today=TODAY))) == {"Read Me", "Master Block"}


def test_any_order_case_spaces_and_punctuation_are_accepted(tmp_path, sample):
    gp = sample["GP Wise Data"]
    a, b = col(gp, "Circle"), col(gp, "AM Name")
    for row in gp:
        if len(row) > b:
            row[a], row[b] = row[b], row[a]
    gp[GP_HDR][col(gp, "AMC / Incremental")] = "AMC/Incremental"
    gp[GP_HDR][col(gp, "DISTRICT")] = "  district "
    gp[GP_HDR][col(gp, "5% Contractual Incremental+ Additional AMC")] = "5% Contractual Incremental + Additional AMC"
    c = check(tmp_path, book(sample))
    assert c.ok, errors(c)
    p = parse(tmp_path, book(sample))
    assert p.gps[0]["amc_category"] == "INCREMENTAL" and p.gps[0]["district"] == "JODHPUR"  # read under the other spelling


def test_a_missing_required_column_rejects_with_the_reason_first(tmp_path, sample):
    gp = sample["GP Wise Data"]
    drop(gp, col(gp, "AM Name"))
    gp[GP_HDR][col(gp, "AMC Date")] = "AMC Dt"
    mb = sample["Master Block"]
    drop(mb, col(mb, "HOTO Done Date", MB_HDR))
    c = check(tmp_path, book(sample))
    assert not c.ok
    msg = c.message()
    assert msg.startswith("Missing required column(s) – GP Wise Data: AMC Date, AM Name; Master Block: HOTO Done Date.")
    assert "day, week and month columns are never a reason to reject" in msg
    assert "the file has 'AMC Dt' (similar)" in errors(c)  # suggested, never applied
    rep = sheet_report(c, "GP Wise Data")
    assert not rep["requiredOk"] and {r["name"] for r in rep["required"] if r["header"] is None} == {"AMC Date", "AM Name"}


def test_a_duplicate_required_column_or_a_missing_sheet_rejects(tmp_path, sample):
    gp = sample["GP Wise Data"]
    add_col(gp, "GP Code", 5)
    c = check(tmp_path, book(sample))
    assert not c.ok and "Duplicate required column: GP Code" in errors(c)
    sample = grids(T.build_template("master", today=TODAY))
    del sample["Master Block"]
    c = check(tmp_path, book(sample))
    assert not c.ok and "Missing sheet: Master Block" in errors(c)


def test_no_availability_column_at_all_rejects(tmp_path, sample):
    gp = sample["GP Wise Data"]
    for i in sorted((i for i, h in enumerate(gp[GP_HDR]) if i >= len(T.GP_REQUIRED)), reverse=True):
        drop(gp, i)
    c = check(tmp_path, book(sample))
    assert not c.ok and "No availability columns found" in errors(c)


def test_optional_absent_and_unknown_columns_never_reject(client, tmp_path, sample):
    gp = sample["GP Wise Data"]
    add_col(gp, "Remarks", "checked")  # a column of the user's own, with values
    add_col(gp, "Phse", "Phase-1")  # a misspelt OPTIONAL column: ignored, never a reason to reject
    c = check(tmp_path, book(sample))
    assert c.ok, errors(c)
    rep = sheet_report(c, "GP Wise Data")
    assert {"Remarks", "Phse"} <= set(rep["unused"]) and "Phase" in rep["optionalAbsent"] and "BBNL Live KM" in rep["optionalAbsent"]
    csrf = login(client)
    r = client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": ("opt.xlsx", book(sample))}, data={"kind": "master"}).json()
    assert r["canImport"] is True and r["stage"] == "ok", r.get("error")
    sheets = {s["sheet"]: s for s in r["columnCheck"]["sheets"]}
    assert sheets["GP Wise Data"]["requiredOk"] and "Remarks" in sheets["GP Wise Data"]["unused"]
    assert r["periods"]["weeks"] and r["periods"]["days"]["count"] > 0
    client.delete(f"/api/v1/ingestion/preview/{r['token']}", headers={"x-csrf-token": csrf})


def test_preview_refuses_a_file_without_a_required_column(client, sample):
    csrf = login(client)
    gp = sample["GP Wise Data"]
    drop(gp, col(gp, "GP Type"))
    r = client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": ("bad.xlsx", book(sample))}, data={"kind": "master"}).json()
    assert r["canImport"] is False and r["stage"] == "template" and r["token"] is None
    assert r["error"].startswith("Missing required column(s) – GP Wise Data: GP Type.")
    assert any(e["message"] == "Missing required column: GP Type" for e in r["templateErrors"])
    assert r["columnCheck"]["templateHint"].startswith("Download the PAGMAS template")


@pytest.mark.parametrize("kind,sheets", [("gp", {"Read Me", "GP Wise Data"}), ("block", {"Read Me", "Master Block"}), ("master", {"Read Me", "GP Wise Data", "Master Block"})])
def test_template_downloads(client, kind, sheets):
    login(client)
    t = client.get(f"/api/v1/ingestion/template/{kind}.xlsx")
    assert t.status_code == 200 and T.TEMPLATE_FILES[kind] in t.headers["content-disposition"]
    assert set(grids(t.content)) == sheets
    assert client.get("/api/v1/ingestion/template/master.xlsx", params={"sample": True}).status_code == 200  # old link


# ---------------------------------------------------------------- values and periods (importer)


def test_day_week_month_problems_are_warnings_never_a_reject(tmp_path, sample):
    gp = sample["GP Wise Data"]
    weeks = [i for i, h in enumerate(gp[GP_HDR]) if str(h).startswith("W-")]
    days = [i for i, h in enumerate(gp[GP_HDR]) if isinstance(h, dt.date) and i > weeks[-1]]
    gp[1][weeks[0]] = "first week"  # not a 7-day range
    drop(gp, days[2])  # a day missing in the middle
    for row in gp:  # the last day twice
        row.append(row[days[-2]] if len(row) > days[-2] else "")
    c = check(tmp_path, book(sample))
    assert c.ok, errors(c)
    p = parse(tmp_path, book(sample))
    codes = {i.code: i.message for i in p.issues}
    assert "WEEK_LABEL" in codes and "PERIOD_GAP" in codes and "PERIOD_DUPLICATE" in codes
    assert "columns" in codes["PERIOD_DUPLICATE"] and " and " in codes["PERIOD_DUPLICATE"]  # both column letters named
    assert p.data_as_of and p.weeks


def test_only_the_current_week_is_imported_as_it_is(tmp_path, sample):
    gp = sample["GP Wise Data"]
    weeks = [i for i, h in enumerate(gp[GP_HDR]) if str(h).startswith("W-")]
    months = [i for i, h in enumerate(gp[GP_HDR]) if isinstance(h, dt.date) and i < weeks[0]]
    current = gp[GP_HDR][weeks[-1]]
    for i in sorted([weeks[0], *months], reverse=True):  # only the current W-nn, no monthly columns
        drop(gp, i)
    c = check(tmp_path, book(sample))
    assert c.ok, errors(c)
    p = parse(tmp_path, book(sample))
    assert [w["code"] for w in p.weeks] == [current] and p.data_as_of == TODAY


def test_blank_and_na_are_never_zero_and_out_of_range_is_left_blank(tmp_path, sample):
    gp = sample["GP Wise Data"]
    last_week = max(i for i, h in enumerate(gp[GP_HDR]) if str(h).startswith("W-"))
    days = [i for i, h in enumerate(gp[GP_HDR]) if isinstance(h, dt.date) and h <= TODAY and i > last_week]
    gp[3][days[0]], gp[4][days[0]] = "NA", 0
    gp[3][days[1]] = 150
    p = parse(tmp_path, book(sample))
    d0, d1 = gp[GP_HDR][days[0]].isoformat(), gp[GP_HDR][days[1]].isoformat()
    vals = {(g, per): v for g, k, per, v in p.availability if k == "D"}
    assert ("999901", d0) not in vals and vals[("999902", d0)] == 0  # NA = not reported, a written 0 is 0
    assert ("999901", d1) not in vals and any(i.code == "INVALID_AVAILABILITY" and i.row_number == 4 for i in p.issues)
    assert {g["gp_code"] for g in p.gps} == {"999901", "999902"}  # the row itself is kept


def test_a_duplicate_gp_row_is_skipped_and_both_rows_are_named(tmp_path, sample):
    gp = sample["GP Wise Data"]
    gp[4][col(gp, "GP Code")] = gp[3][col(gp, "GP Code")]
    mb = sample["Master Block"]
    mb[5][col(mb, "Block Code", MB_HDR)] = mb[4][col(mb, "Block Code", MB_HDR)]
    p = parse(tmp_path, book(sample))
    dup = next(i for i in p.issues if i.code == "DUPLICATE_GP")
    assert dup.row_number == 5 and "first on row 4" in dup.message and len(p.gps) == 1
    blk = next(i for i in p.issues if i.code == "DUPLICATE_BLOCK")
    assert "first on row 5" in blk.message and "row 6" in blk.message and len(p.master_blocks) == 1


def test_master_block_periods_are_read_by_pattern(tmp_path, sample):
    p = parse(tmp_path, book(sample))
    kinds = {k for _c, k, _p, _v in p.block_availability}
    assert {"BM", "BMA", "BW", "BD"} <= kinds  # ALL GPs month, AMC GPs month (same name again), week, day


# ---------------------------------------------------------------- history across uploads


@pytest.fixture
def clean_history():
    """An empty period history for the test; the rows of the session (other tests' imports) are restored after."""
    from sqlalchemy import delete, select

    from app.db import SessionLocal
    from app.models import PeriodHistory

    cols = [c.name for c in PeriodHistory.__table__.columns]
    with SessionLocal() as db:
        saved = [{c: getattr(r, c) for c in cols} for r in db.scalars(select(PeriodHistory))]
        db.execute(delete(PeriodHistory))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(PeriodHistory))
        db.add_all([PeriodHistory(**r) for r in saved])
        db.commit()


def test_a_later_file_with_fewer_weeks_keeps_the_earlier_ones(tmp_path, clean_history):
    """File A has W-23 and W-24 and May + June; file B (two weeks later) has W-25 and W-26 and only June: the
    dashboard keeps W-23, W-24 and May from A. A period in both keeps the newer file's values; re-uploading the older
    file never overwrites them."""
    from app.analytics.store import Week, _with_period_history
    from app.db import SessionLocal
    from app.ingestion.history import earlier_periods, merge_periods

    a = parse(tmp_path, T.build_template("master", today=dt.date(2026, 6, 10)))
    b_grid = grids(T.build_template("master", today=dt.date(2026, 6, 24)))
    gp = b_grid["GP Wise Data"]
    m_cols = [i for i, h in enumerate(gp[GP_HDR]) if isinstance(h, dt.date) and h.day == 1 and h.month == 5]
    for i in reversed(m_cols):  # file B: only June
        drop(gp, i)
    b = parse(tmp_path, book(b_grid))
    a_weeks, b_weeks = [w["code"] for w in a.weeks], [w["code"] for w in b.weeks]
    with SessionLocal() as db:
        merge_periods(db, a, "A.xlsx")
        merge_periods(db, b, "B.xlsx")
        db.commit()
        again = merge_periods(db, a, "A.xlsx")  # the older file once more
        db.commit()
        assert "M 2026-06" in again["kept"] and "W " + b_weeks[-1] not in again["updated"]  # newer values are never overwritten
        first_b = min(w["start_date"] for w in b.weeks)
        hist = earlier_periods(db, "W", set(b_weeks), before=first_b, upto=b.data_as_of)
        months = earlier_periods(db, "M", {"2026-06"}, upto=b.data_as_of)
        # a file on other week days (one day later): the history weeks are not on its calendar – never mixed in
        assert earlier_periods(db, "W", set(b_weeks), before=first_b + dt.timedelta(days=1), upto=b.data_as_of) == []
    earlier = [w for w in a_weeks if w not in b_weeks]
    assert [h[0] for h in hist] == earlier and all(h[5] == "A.xlsx" for h in hist)
    assert [m[0] for m in months] == ["2026-05"]
    # the store puts them in front of the file's own weeks, in date order
    idx = pd.Index(["999901", "999902"], name="gp_code")
    weeks = [Week(w["code"], w["number"], w["start_date"], w["end_date"]) for w in b.weeks]
    weekly = pd.DataFrame({w: [99.0, float("nan")] for w in b_weeks}, index=idx)
    monthly = pd.DataFrame({"2026-06": [99.5, float("nan")]}, index=idx)
    ws, wk, mo, _ma, h_weeks, h_months = _with_period_history(weeks, weekly, monthly, monthly.copy(), idx, b.data_as_of)
    assert [w.code for w in ws] == earlier + b_weeks and list(wk.columns) == earlier + b_weeks
    assert h_weeks == earlier and h_months == ["2026-05"] and list(mo.columns) == ["2026-05", "2026-06"]
    assert wk.loc["999901", earlier[0]] == 99.0 and pd.isna(wk.loc["999902", earlier[0]])  # NA stays NA, never 0
