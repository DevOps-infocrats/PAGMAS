"""Ingestion hardening: number / date / code helpers, period columns, activation, pruning, upload and retry rules."""

import datetime as dt
import hashlib
import uuid
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, SessionLocal
from app.ingestion import service
from app.ingestion.parser import ParsedWorkbook, _availability, _circle_column_key, _derive_missing_weeks, _number, _parse_gp_sheet, _parse_week_range
from app.ingestion.workbook import WorkbookError, as_date, clean_code, code_key
from app.models import Dataset, DatasetWeek, EscalationImport, Gp

from .conftest import login

HEADER = ["Circle", "BA", "District", "Block", "Block Code", "GP", "GP Code", "TOTAL RKM", "HOTO Date", "AMC Date", "AM Name"]
OCT = [dt.date(2026, 10, 1) + dt.timedelta(days=i) for i in range(9)]


def gp_grid(weeks=(("W-40", "25-1 Oct"), ("W-41", "2-8 Oct")), days=OCT, daily=95.0, extra=(), rows=None):
    """A minimal GP sheet: label row, header row (fields, W-nn, daily dates, extra headers) and GP rows."""
    above = [None] * len(HEADER) + [label for _, label in weeks] + [None] * (len(days) + len(extra))
    header = HEADER + [w for w, _ in weeks] + list(days) + list(extra)
    rows = rows or [("566", "262368")]
    body = [["RAJASTHAN", "AJMER", "AJMER", "ARAIN", block, "GP", code, 4.5, dt.date(2025, 1, 1), None, "Ram"] + [90.0] * len(weeks) + [daily] * len(days) + [None] * len(extra) for block, code in rows]
    return [above, header, *body]


def parse(grid, sheet="GP Data X"):
    out = ParsedWorkbook()
    _parse_gp_sheet(grid, out, sheet=sheet)
    return out


# ---------------------------------------------------------------- helpers (10, 11, 12)


def test_number_coercion():
    assert _number("1,234.5") == (1234.5, True) and _number(" 4 378 ") == (4378.0, True) and _number("99.5%") == (99.5, True)
    for blank in ("-", "–", "NA", "n/a", "", "  "):
        assert _number(blank) == (None, True), blank
    for bad in ("abc", "nan", "inf", float("nan"), float("inf"), True):
        assert _number(bad) == (None, False), bad
    assert _availability("99.5%") == (99.5, True) and _availability("100.5") == (None, False)


def test_dates_accept_day_first_text_and_excel_serials():
    for text in ("15-10-2026", "15.10.2026", "15/10/2026", "15-10-26", " 15/10/2026 "):
        assert as_date(text) == dt.date(2026, 10, 15), text
    assert as_date(46310) == dt.date(1899, 12, 30) + dt.timedelta(days=46310) and as_date(46310.0) == as_date(46310)
    for garbage in ("31-02-2026", "Till 8 Oct", "W-41", "2026", 19999, 80001, True, None, "10/15/2026"):
        assert as_date(garbage) is None, garbage


def test_one_code_helper_for_master_and_escalation():
    assert clean_code(262368.0) == "262368" and clean_code(" 262368.0 ") == "262368" and clean_code("O033977") == "0033977"
    assert clean_code(None) is None and clean_code("  ") is None and clean_code("BLK-7") == "BLK-7"
    assert code_key("0033977") == code_key("33977") == code_key(clean_code("O033977")) and code_key("BLK-7") != code_key("BLK-8")


def test_escalation_rows_rejected_with_reasons(tmp_path):
    import xlsxwriter

    from app.ingestion.escalation import parse_escalation

    path = tmp_path / "esc.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet("Matrix")
    rows = [["Circle", "GP Code", "FRT Code", "FE Name"], ["Rajasthan", "O033977", "F1", "A"], ["Rajasthan", 33977, "F2", "B"], ["Rajasthan", None, "F3", "C"], [None, "4455", "F4", "D"]]
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            if v is not None:
                ws.write(r, c, v)
    wb.close()
    p = parse_escalation(path)
    assert [r["gp_code"] for r in p.rows] == ["0033977"] and (p.rows_total, p.rows_rejected) == (4, 3)
    assert p.rejected == ["row 3: duplicate GP code 33977 (first on row 2)", "row 4: no GP code", "row 5: no circle"]
    assert p.summary().startswith("3 row(s) of 'Matrix' rejected: row 3: duplicate GP code 33977")


def test_corrupt_workbook_is_a_workbook_error(tmp_path):
    from app.ingestion.escalation import detect_kind

    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"PK\x03\x04" + b"\x00garbage" * 100)
    not_excel = tmp_path / "other.xlsx"
    with zipfile.ZipFile(not_excel, "w") as z:
        z.writestr("hello.txt", "not a workbook")
    for path in (junk, not_excel):
        with pytest.raises(WorkbookError):
            detect_kind(path)


# ---------------------------------------------------------------- weeks / periods (5, 6, 8, 9)


def test_week_labels_roll_back_a_year_in_a_january_file():
    jan = dt.date(2027, 1, 10)
    assert _parse_week_range("22-28 Dec", jan) == (dt.date(2026, 12, 22), dt.date(2026, 12, 28))
    assert _parse_week_range("29-4 Jan", jan) == (dt.date(2026, 12, 29), dt.date(2027, 1, 4))
    assert _parse_week_range("2-8 Oct", dt.date(2026, 10, 11)) == (dt.date(2026, 10, 2), dt.date(2026, 10, 8))
    assert _parse_week_range("9-15 Oct", dt.date(2026, 10, 11)) == (dt.date(2026, 10, 9), dt.date(2026, 10, 15))  # week in progress
    with pytest.raises(WorkbookError, match=r"Week label '31-6 Oct' is not a valid date range"):
        _parse_week_range("31-6 Oct", jan)
    assert _circle_column_key("Dec", jan) == "2026-12" and _circle_column_key("Jan", jan) == "2027-01" and _circle_column_key("WK-1", jan) == "W-1"


def test_derived_weeks_follow_dates_across_the_year_end():
    def wk(code, start):
        return {"code": code, "number": int(code[2:]), "start_date": start, "end_date": start + dt.timedelta(days=6)}

    p = ParsedWorkbook(weeks=[wk("W-52", dt.date(2026, 12, 18)), wk("W-1", dt.date(2027, 1, 1))], data_as_of=dt.date(2027, 1, 10))
    _derive_missing_weeks(p)
    assert [(w["code"], w["start_date"]) for w in p.weeks[2:]] == [("W-2", dt.date(2027, 1, 8))]
    q = ParsedWorkbook(weeks=[wk("W-51", dt.date(2026, 12, 11)), wk("W-52", dt.date(2026, 12, 18))], data_as_of=dt.date(2027, 1, 2))
    _derive_missing_weeks(q)
    assert [(w["code"], w["start_date"]) for w in q.weeks[2:]] == [("W-53", dt.date(2026, 12, 25)), ("W-1", dt.date(2027, 1, 1))]


def test_synthetic_sheet_parses_and_issues_use_the_sheet_name():
    p = parse(gp_grid(rows=[("566", "262368"), ("", "0262368"), ("567", "O777")]))
    assert p.data_as_of == OCT[-1] and [w["code"] for w in p.weeks] == ["W-40", "W-41", "W-42"]
    assert p.weeks[0]["start_date"] == dt.date(2026, 9, 25) and [g["gp_code"] for g in p.gps] == ["262368", "0777"]
    codes = {(i.code, i.sheet) for i in p.issues}
    assert ("DUPLICATE_GP", "GP Data X") in codes and ("WEEK_DERIVED", "GP Data X") in codes
    assert all(i.sheet == "GP Data X" for i in p.issues)


def test_blank_block_fields_are_reported():
    grid = gp_grid()
    grid[2][2] = grid[2][3] = grid[2][4] = None  # district, block, block code
    p = parse(grid)
    issue = next(i for i in p.issues if i.code == "BLOCK_MISSING")
    assert issue.severity == "warning" and "District, block name, block code missing" in issue.message
    assert (p.gps[0]["district"], p.gps[0]["block_code"]) == ("UNKNOWN", "UNKNOWN")


def test_no_daily_values_is_rejected():
    with pytest.raises(WorkbookError, match=r"No daily availability values found in 'GP Data X'"):
        parse(gp_grid(daily=None))


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        (gp_grid(weeks=(("W-40", "25-1 Oct"), ("W-40", "2-8 Oct"))), r"Duplicate weekly availability columns: W-40 \(columns L, M\)"),
        (gp_grid(days=[*OCT, OCT[-1]]), r"Duplicate daily availability columns: 2026-10-09"),
        (gp_grid(weeks=(("W-40", "31-6 Oct"),)), r"Week label '31-6 Oct' is not a valid date range"),
        (gp_grid(extra=("Remarks", dt.date(2026, 10, 12))), r"Daily date columns must be contiguous: column \w+ \('Remarks'\)"),
        (gp_grid(days=[*OCT, dt.date.today() + dt.timedelta(days=5)]), r"is in the future"),
    ],
    ids=["duplicate-week", "duplicate-day", "invalid-week-label", "non-contiguous-days", "future-day"],
)
def test_bad_period_columns_are_workbook_errors(grid, message):
    with pytest.raises(WorkbookError, match=message):
        parse(grid)


# ---------------------------------------------------------------- activation, failure, pruning (1, 2a, 4, 7)


@pytest.fixture
def temp_db(monkeypatch):
    """Service functions against a private in-memory database (the shared test DB keeps the real import)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", maker)
    reloads = []
    import app.analytics.store as store

    monkeypatch.setattr(store, "reload_store", lambda: reloads.append(1))
    yield maker, reloads
    engine.dispose()


def add_ds(db, status="SUCCESS", active=False, as_of=None, path="x", rows=True):
    ds = Dataset(file_name="f.xlsb", stored_path=str(path), sha256="0" * 64, status=status, is_active=active, data_as_of=as_of)
    db.add(ds)
    db.flush()
    if rows:
        db.add(Gp(dataset_id=ds.id, gp_code="1", source_row=1, name="g", circle="C", district="D", block_name="B", block_code="1"))
        db.add(DatasetWeek(dataset_id=ds.id, code="W-1", number=1, start_date=dt.date(2026, 1, 1), end_date=dt.date(2026, 1, 7)))
        db.flush()
    return ds


def upload_file(tmp=b""):
    d = get_settings().upload_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex}.xlsb"
    p.write_bytes(b"PK\x03\x04" + tmp + uuid.uuid4().bytes)
    return p


def test_prune_keeps_the_active_dataset_and_deletes_unneeded_files(temp_db, tmp_path):
    maker, _ = temp_db
    outside = tmp_path / "raw.xlsb"
    outside.write_bytes(b"PK\x03\x04")
    with maker() as db:
        active = add_ds(db, active=True, path=upload_file())
        raw = add_ds(db, path=outside)  # imported from data/raw: never deleted
        ok = [add_ds(db, path=upload_file()) for _ in range(4)]
        failed = [add_ds(db, status="FAILED", path=upload_file(), rows=False) for _ in range(5)]
        db.commit()
        service._prune(db)
        kept = set(db.scalars(select(DatasetWeek.dataset_id)))
    assert kept == {active.id} | {d.id for d in ok[1:]}  # newest 3 + the active one (older than all of them)
    exists = lambda d: Path(d.stored_path).exists()  # noqa: E731
    assert exists(active) and exists(raw) and not exists(ok[0]) and all(exists(d) for d in ok[1:])
    assert [exists(d) for d in failed] == [False, False, True, True, True]  # the newest failed files stay for a retry


def test_best_dataset_is_the_newest_data_date_with_rows(temp_db):
    maker, _ = temp_db
    with maker() as db:
        newest = add_ds(db, as_of=dt.date(2026, 10, 14))
        add_ds(db, as_of=dt.date(2026, 10, 8))  # uploaded later, older data
        add_ds(db, as_of=dt.date(2026, 10, 20), rows=False)  # pruned: no rows left
        assert service._best_dataset(db) == newest.id
        tie = add_ds(db, as_of=dt.date(2026, 10, 14))
        assert service._best_dataset(db) == tie.id and service._best_dataset(db, exclude=tie.id) == newest.id


def test_older_upload_is_imported_but_not_activated(temp_db, monkeypatch):
    maker, reloads = temp_db
    monkeypatch.setattr(service, "parse_workbook", lambda path: parse(gp_grid(days=OCT[:5] if "old" in str(path) else OCT)))
    with maker() as db:
        new, old = add_ds(db, status="PROCESSING", path="new.xlsb", rows=False), add_ds(db, status="PROCESSING", path="old.xlsb", rows=False)
        db.commit()
    service._run_ingestion(new.id)
    service._run_ingestion(old.id)
    with maker() as db:
        new, old = db.get(Dataset, new.id), db.get(Dataset, old.id)
    assert new.is_active and new.data_as_of == OCT[-1] and reloads == [1]
    assert old.status == "SUCCESS" and not old.is_active and f"run #{new.id} has newer data" in old.message


def test_failed_active_dataset_is_deactivated(temp_db):
    maker, reloads = temp_db
    with maker() as db:
        other, active = add_ds(db, as_of=dt.date(2026, 10, 8)), add_ds(db, active=True, as_of=dt.date(2026, 10, 14))
        db.commit()
    service._fail(active.id, "boom")
    with maker() as db:
        assert (db.get(Dataset, active.id).status, db.get(Dataset, active.id).is_active) == ("FAILED", False)
        assert db.get(Dataset, other.id).is_active and reloads == [1]


# ---------------------------------------------------------------- upload + retry endpoints (2b, 2c, 4)


def uploads():
    d = get_settings().upload_dir
    return set(d.iterdir()) if d.exists() else set()


def test_same_file_twice_returns_the_existing_import(client):
    csrf = login(client)
    for model, kind in ((Dataset, "run"), (EscalationImport, "Escalation Matrix import")):
        stored = upload_file()
        content = stored.read_bytes()
        with SessionLocal() as db:
            rec = model(file_name="first.xlsb", stored_path=str(stored), sha256=hashlib.sha256(content).hexdigest(), status="SUCCESS")
            db.add(rec)
            db.commit()
        try:
            before = uploads()
            r = client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": ("again.xlsb", content, "application/octet-stream")})
            assert r.status_code == 409 and f"already imported as {kind} #{rec.id}" in r.json()["detail"], r.text
            assert uploads() == before  # the new copy was deleted
        finally:
            with SessionLocal() as db:
                db.delete(db.get(model, rec.id))
                db.commit()
            stored.unlink(missing_ok=True)


def test_failed_uploads_leave_no_file(client, monkeypatch):
    csrf = login(client)
    before = uploads()
    post = lambda body, name="x.xlsb": client.post("/api/v1/ingestion/upload", headers={"x-csrf-token": csrf}, files={"file": (name, body, "application/octet-stream")})  # noqa: E731
    monkeypatch.setattr(get_settings(), "upload_max_mb", 1)
    assert post(b"PK\x03\x04" + b"\x00" * (1 << 21)).status_code == 413
    monkeypatch.undo()
    assert post(b"PK\x03\x04" + b"\x00garbage" * 50).status_code == 415  # corrupt workbook: no 500
    from app.api import admin

    monkeypatch.setattr(admin, "detect_kind", lambda path: (_ for _ in ()).throw(RuntimeError("client went away")))
    try:
        assert post(b"PK\x03\x04" + uuid.uuid4().bytes).status_code == 500
    except RuntimeError:
        pass  # the test client re-raises server errors
    assert uploads() == before


def test_retry_only_for_failed_runs_with_a_file(client):
    csrf = login(client)
    retry = lambda i: client.post(f"/api/v1/ingestion/runs/{i}/retry", headers={"x-csrf-token": csrf})  # noqa: E731
    stored = upload_file(b"\x00not-a-workbook")
    old_start = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    with SessionLocal() as db:
        busy = Dataset(file_name="busy.xlsb", stored_path=str(stored), sha256="1" * 64, status="PROCESSING")
        gone = Dataset(file_name="gone.xlsb", stored_path=str(stored.with_name("missing.xlsb")), sha256="2" * 64, status="FAILED")
        failed = Dataset(file_name="failed.xlsb", stored_path=str(stored), sha256="3" * 64, status="FAILED", started_at=old_start)
        db.add_all([busy, gone, failed])
        db.commit()
    try:
        r = retry(busy.id)
        assert r.status_code == 409 and "Only failed imports can be retried" in r.json()["detail"]
        assert retry(gone.id).status_code == 410
        r = retry(failed.id)
        assert r.status_code == 202 and r.json()["accepted"]
        with SessionLocal() as db:
            ds = db.get(Dataset, failed.id)
            assert ds.status == "FAILED" and ds.started_at.year > 2020 and not ds.is_active  # re-processed (still not a workbook)
    finally:
        with SessionLocal() as db:
            for d in (busy, gone, failed):
                db.delete(db.get(Dataset, d.id))
            db.commit()
        stored.unlink(missing_ok=True)
