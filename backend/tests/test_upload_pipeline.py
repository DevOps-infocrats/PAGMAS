"""Data uploads: layered file checks (type, empty, genuine workbook, zip bomb), the chosen file kind, structure,
row rules (blank is never 0, duplicates name both rows, out-of-range values), and the staging flow
"preview -> confirm" (nothing imported before the confirm; a failed check leaves no file; tokens are per admin)."""

import datetime as dt
import io
import zipfile

import pytest
import xlsxwriter
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion import staging
from app.ingestion.parser import parse_workbook
from app.models import Dataset, Gp

from .conftest import ADMIN, VIEWER, login

D = dt.date


def master_xlsx(rows=None, header=None, days=7, extra_days_block=False) -> bytes:
    """A small but complete master data workbook: header in row 3, week dates above W-14, daily dates after it."""
    header = header or ["Circle", "BA", "District", "Block", "Block Code", "GP", "GP Code", "TOTAL RKM", "HOTO Date", "AMC Date"]
    rows = rows if rows is not None else [
        ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One", "910001", 12.5, D(2026, 3, 1), D(2026, 3, 10), 99.0, *[100.0] * days],
        ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp Two", "910002", 8.0, D(2026, 3, 1), D(2026, 3, 11), 97.0, *[95.0] * days],
    ]
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("GP Wise Data")
    datef = wb.add_format({"num_format": "dd-mm-yyyy"})
    first = D(2026, 3, 28)
    dates = [first + dt.timedelta(days=i) for i in range(days)] * (2 if extra_days_block else 1)
    full = [*header, "W-13", *dates]
    ws.write(1, len(header), "28-3 Apr")  # week dates above the W-nn column
    for c, h in enumerate(full):
        ws.write_datetime(2, c, dt.datetime.combine(h, dt.time()), datef) if isinstance(h, D) else ws.write(2, c, h)
    for r, row in enumerate(rows, start=3):
        for c, v in enumerate(row):
            if isinstance(v, D):
                ws.write_datetime(r, c, dt.datetime.combine(v, dt.time()), datef)
            elif v is not None:
                ws.write(r, c, v)
    wb.close()
    return buf.getvalue()


def template_sample() -> bytes:
    """The PAGMAS template's sample with March 2026 data – older than the test dataset, so it is never activated."""
    from app.ingestion.template import build_template

    return build_template(sample=True, today=D(2026, 3, 10))


def escalation_xlsx() -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("All")
    for c, h in enumerate(["Circle", "GP Code", "FRT Code", "FE Name", "AM Name", "FE Email ID"]):
        ws.write(0, c, h)
    for c, v in enumerate(["HARYANA", "910001", "F-1", "Fe A", "", "not-an-email"]):
        ws.write(1, c, v)
    for c, v in enumerate(["HARYANA", "910001", "F-1", "Fe B", "Ravi", "b@x.in"]):  # duplicate GP code
        ws.write(2, c, v)
    wb.close()
    return buf.getvalue()


def _preview(client, csrf, content: bytes, name="m.xlsx", kind="master"):
    return client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": (name, content, "application/octet-stream")}, data={"kind": kind})


def _staged() -> set:
    d = get_settings().staging_dir
    return {p.name for p in d.iterdir()} if d.exists() else set()


def _zip(parts: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in parts.items():
            z.writestr(n, b)
    return buf.getvalue()


# ---------------------------------------------------------------- layer 1: the file itself


def test_wrong_type_macro_empty_renamed_and_damaged_files_are_refused(client):
    csrf = login(client)
    before = _staged()
    assert _preview(client, csrf, b"%PDF-1.4", "report.pdf").status_code == 415
    r = _preview(client, csrf, master_xlsx(), "macro.xlsm")
    assert r.status_code == 415 and "Macro" in r.json()["detail"]
    for content, name, text in (
        (b"", "empty.xlsx", "empty"),
        (b"just,some,csv\n1,2,3", "renamed.xlsx", "not a valid Excel workbook"),
        (b"PK\x03\x04garbage-not-a-zip", "damaged.xlsx", "damaged"),
        (_zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"}), "letter.xlsx", "not a genuine .xlsx"),
        (_zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.bin": b"x"}), "binary.xlsx", "looks like a .xlsb"),
    ):
        rep = _preview(client, csrf, content, name).json()
        assert rep["canImport"] is False and rep["stage"] == "file" and text in rep["error"], (name, rep)
        assert rep["token"] is None
    assert _staged() == before  # nothing is left behind


def test_zip_bomb_is_refused(client, monkeypatch):
    csrf = login(client)
    monkeypatch.setattr(get_settings(), "zip_max_ratio", 50)
    bomb = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<w/>", "xl/worksheets/sheet1.xml": b"0" * (8 << 20)})
    rep = _preview(client, csrf, bomb).json()
    assert rep["stage"] == "file" and "unsafe" in rep["error"]


def test_only_admins_can_upload(client):
    csrf = login(client, VIEWER)
    assert _preview(client, csrf, master_xlsx()).status_code == 403


# ---------------------------------------------------------------- layers 2–4: kind, duplicate, structure


def test_chosen_kind_must_match_the_content(client):
    csrf = login(client)
    rep = _preview(client, csrf, master_xlsx(), kind="escalation").json()
    assert rep["stage"] == "kind" and "Master Data workbook" in rep["error"]
    rep = _preview(client, csrf, escalation_xlsx(), "esc.xlsx", kind="master").json()
    assert rep["stage"] == "kind" and "Escalation Matrix" in rep["error"]


def test_missing_required_column_stops_the_preview(client):
    csrf = login(client)
    header = ["Circle", "BA", "District", "Block", "Block Code", "GP", "GP Code", "TOTAL RKM", "HOTO Date"]  # no AMC Date
    rows = [["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One", "910001", 12.5, D(2026, 3, 1), 99.0, *[100.0] * 7]]
    rep = _preview(client, csrf, master_xlsx(rows, header)).json()
    assert rep["canImport"] is False and rep["stage"] == "template"  # the fixed PAGMAS template (test_template_validation.py)
    assert any(e["message"] == "Missing column: AMC Date" for e in rep["templateErrors"])


# ---------------------------------------------------------------- layer 5: row rules (parser)


def test_blank_is_never_zero_duplicates_name_both_rows_and_range_is_checked(tmp_path):
    rows = [
        ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One", "910001", None, D(2026, 3, 1), D(2026, 3, 10), 99.0, None, 100.0, 150.0, 100.0, 100.0, 100.0, 100.0],
        ["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One again", "910001", 3.0, D(2026, 3, 1), D(2026, 3, 10), 99.0, *[100.0] * 7],
    ]
    p = tmp_path / "m.xlsx"
    p.write_bytes(master_xlsx(rows))
    out = parse_workbook(p)
    gp = out.gps[0]
    assert gp["total_rkm"] is None  # blank TOTAL RKM stays blank – not 0 km
    assert any(i.code == "RKM_MISSING" and i.row_number == 4 for i in out.issues)
    daily = {(k, per): v for g, k, per, v in out.availability if g == "910001"}
    assert ("D", "2026-03-28") not in daily  # blank daily value = not reported, nothing stored
    assert ("D", "2026-03-29") in daily and daily[("D", "2026-03-29")] == 100.0
    bad = next(i for i in out.issues if i.code == "INVALID_AVAILABILITY")
    assert bad.row_number == 4 and "150" in bad.message  # out of 0–100: flagged with its row
    dup = next(i for i in out.issues if i.code == "DUPLICATE_GP")
    assert dup.severity == "critical" and dup.row_number == 5 and "first on row 4" in dup.message
    assert out.rows_rejected == 1 and len(out.gps) == 1


def test_a_repeated_block_of_daily_dates_is_ignored_with_a_warning(tmp_path):
    rows = [["HARYANA", "Ambala", "Ambala", "Barara", "501", "Gp One", "910001", 1.0, D(2026, 3, 1), D(2026, 3, 10), 99.0, *[100.0] * 7, *[55.0] * 7]]
    p = tmp_path / "m.xlsx"
    p.write_bytes(master_xlsx(rows, extra_days_block=True))
    out = parse_workbook(p)
    assert any(i.code == "DAILY_REPEATED" for i in out.issues)
    assert {v for g, k, per, v in out.availability if k == "D"} == {100.0}  # only the first (raw) block


def test_escalation_preview_lists_rows_with_numbers(client):
    csrf = login(client)
    rep = _preview(client, csrf, escalation_xlsx(), "esc.xlsx", kind="escalation").json()
    assert rep["canImport"] is True and rep["counts"]["rejected"] == 1
    codes = {(i["code"], i["row"]) for i in rep["issues"]}
    assert ("DUPLICATE_GP", 3) in codes and ("INVALID_EMAIL", 2) in codes and ("AM_MISSING", 2) in codes
    dup = next(i for i in rep["issues"] if i["code"] == "DUPLICATE_GP")
    assert "first on row 2" in dup["message"]
    client.delete(f"/api/v1/ingestion/preview/{rep['token']}", headers={"x-csrf-token": csrf})


# ---------------------------------------------------------------- staging: preview -> confirm


def test_preview_imports_nothing_and_confirm_imports_the_staged_file(client, imported):  # noqa: ARG001 - an active dataset with newer data
    csrf = login(client)
    with SessionLocal() as db:
        runs_before = db.scalar(select(Dataset.id).order_by(Dataset.id.desc()).limit(1)) or 0
    content = template_sample()
    rep = _preview(client, csrf, content, "Master small.xlsx").json()
    assert rep["canImport"] is True and rep["stage"] == "ok" and rep["token"]
    assert rep["counts"]["rows"] == 2 and rep["counts"]["accepted"] == 2
    assert any(f["label"] == "Weeks" and "W-" in f["value"] for f in rep["facts"])
    with SessionLocal() as db:  # preview wrote nothing
        assert (db.scalar(select(Dataset.id).order_by(Dataset.id.desc()).limit(1)) or 0) == runs_before
    assert any(n.startswith(rep["token"]) for n in _staged())
    # another admin's token / a wrong token are not usable
    assert client.post("/api/v1/ingestion/confirm", headers={"x-csrf-token": csrf}, json={"token": "x" * 32}).status_code == 404
    r = client.post("/api/v1/ingestion/confirm", headers={"x-csrf-token": csrf}, json={"token": rep["token"]})
    assert r.status_code == 202, r.text
    run_id = int(r.json()["id"])
    try:
        with SessionLocal() as db:
            ds = db.get(Dataset, run_id)
            assert ds.status in ("SUCCESS", "PARTIAL") and ds.file_name == "Master small.xlsx"
            stored = get_settings().upload_dir / ds.stored_path.replace("\\", "/").split("/")[-1]
            assert stored.name.startswith(dt.datetime.now(dt.UTC).strftime("%Y%m%d")) and rep["sha256"][:16] in stored.name  # timestamp + checksum
            assert not ds.is_active  # older data than the active dataset: imported, never switched to
            assert db.scalar(select(Gp.gp_code).where(Gp.dataset_id == run_id, Gp.gp_code == "999901")) == "999901"
        assert not any(n.startswith(rep["token"]) for n in _staged())  # moved out of staging
        # the same file again: refused before anything is staged for long
        again = _preview(client, csrf, content, "copy.xlsx").json()
        assert again["stage"] == "duplicate" and f"#{run_id}" in again["error"]
    finally:
        with SessionLocal() as db:
            ds = db.get(Dataset, run_id)
            path = ds.stored_path
            for model in __import__("app.ingestion.service", fromlist=["DATA_TABLES"]).DATA_TABLES:
                db.execute(delete(model).where(model.dataset_id == run_id))
            db.delete(ds)
            db.commit()
        __import__("pathlib").Path(path).unlink(missing_ok=True)


def test_cancel_and_expiry_remove_the_staged_file(client, monkeypatch):
    csrf = login(client)
    rep = _preview(client, csrf, template_sample()).json()
    assert client.delete(f"/api/v1/ingestion/preview/{rep['token']}", headers={"x-csrf-token": csrf}).json() == {"discarded": True}
    assert not any(n.startswith(rep["token"]) for n in _staged())
    rep = _preview(client, csrf, template_sample()).json()
    st = staging.load(rep["token"], staging.Staged.__dataclass_fields__ and _admin_id())
    monkeypatch.setattr("time.time", lambda: st.created + get_settings().staging_ttl_minutes * 60 + 1)
    r = client.post("/api/v1/ingestion/confirm", headers={"x-csrf-token": csrf}, json={"token": rep["token"]})
    assert r.status_code == 410 and not any(n.startswith(rep["token"]) for n in _staged())


def _admin_id() -> int:
    from app.models import User

    with SessionLocal() as db:
        return db.scalars(select(User.id).where(User.email == ADMIN[0])).one()


@pytest.fixture(autouse=True)
def _no_stale_staging():
    yield
    staging.cleanup()
