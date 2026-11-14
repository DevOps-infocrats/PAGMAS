"""Escalation Matrix upload rules – REQUIRED / OPTIONAL columns like the master data (template.ESC_REQUIRED /
ESC_OPTIONAL): a missing required column rejects the file by name, a missing optional one never does, and the
downloadable template is built from the same lists."""

import io
from pathlib import Path

import pytest
import xlsxwriter

from app.ingestion.column_map import ESCALATION_COLUMNS, ESCALATION_REQUIRED
from app.ingestion.escalation import detect_kind, parse_escalation
from app.ingestion.template import ESC_OPTIONAL, ESC_REQUIRED, build_template, esc_label, validate_escalation
from app.ingestion.workbook import WorkbookError, open_workbook, read_sheet

from .conftest import login

REAL_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "Final Escalation Matrix.xlsx"
REQUIRED = [c.name for c in ESC_REQUIRED]
ROW = {
    "Circle": "HARYANA", "GP Code": "910001", "FE Name": "Fe A", "FE Email ID": "fe@x.in", "AM Name": "Ravi", "AM Email ID": "ravi@x.in",
    "SME Name": "Sme", "SME Email ID": "sme@x.in", "COH": "Coh", "COH Email ID": "coh@x.in", "FRT Code": "F-1", "FE Number": "9876543210",
}  # fmt: skip


def _xlsx(header: list[str], rows: list[dict] | None = None) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("All")
    ws.write_row(0, 0, header)
    for r, row in enumerate(rows if rows is not None else [ROW], start=1):
        for c, h in enumerate(header):
            if row.get(h) is not None:
                ws.write(r, c, row[h])
    wb.close()
    return buf.getvalue()


def _file(tmp_path, header, rows=None) -> Path:
    path = tmp_path / "esc.xlsx"
    path.write_bytes(_xlsx(header, rows))
    return path


def test_lists_are_in_step():
    """Every known Escalation Matrix field is in exactly one bucket, and the required bucket is the importer's."""
    req, opt = [c.field for c in ESC_REQUIRED], [c.field for c in ESC_OPTIONAL]
    assert tuple(req) == ESCALATION_REQUIRED
    assert not set(req) & set(opt) and sorted(req + opt) == sorted(ESCALATION_COLUMNS)
    assert "frt_code" in opt and "cbh_name" in opt and "cbh_email" in opt  # optional by decision (13 Nov 2026)
    assert esc_label("shq_name") == "SME Name" and esc_label("coh_name") == "COH"


def test_template_passes_its_own_check(tmp_path):
    path = tmp_path / "tpl.xlsx"
    path.write_bytes(build_template("escalation"))
    wb = open_workbook(path)
    assert wb.sheet_names == ["Read Me", "All"]
    header = [h for h in read_sheet(wb, "All", nrows=3)[1] if h]
    assert header[: len(REQUIRED)] == REQUIRED and header[len(REQUIRED) :] == [c.name for c in ESC_OPTIONAL]
    assert detect_kind(path) == "escalation" and validate_escalation(path).ok
    p = parse_escalation(path)
    assert len(p.rows) == 2 and p.rows_rejected == 0 and not p.missing
    assert p.rows[0]["fe_email"] == "fe.one@example.in" and p.rows[0]["shq_name"] == "Example SME"


@pytest.mark.parametrize("gone", REQUIRED[3:])  # Circle / GP Code / FE Name find the sheet; every other one is checked by name
def test_missing_required_column_is_refused_by_name(tmp_path, gone):
    path = _file(tmp_path, [h for h in REQUIRED if h != gone])
    assert detect_kind(path) == "escalation"  # still recognised – the message names the column instead
    chk = validate_escalation(path)
    assert not chk.ok and f"Missing required column(s) – All: {gone}." in chk.message()
    with pytest.raises(WorkbookError, match=f"missing required column\\(s\\): {gone}"):
        parse_escalation(path)  # a re-process of such a file is refused too


def test_similar_column_is_suggested_never_used(tmp_path):
    path = _file(tmp_path, [h if h != "AM Email ID" else "AM Mail Address" for h in REQUIRED], [{**ROW, "AM Mail Address": "ravi@x.in"}])
    chk = validate_escalation(path)
    assert not chk.ok and chk.sheets[0].required[REQUIRED.index("AM Email ID")]["hint"] == "AM Mail Address"


def test_optional_columns_may_be_left_out_and_blank_cells_are_fine(tmp_path):
    """No FRT Code, no phones, no CBH: accepted. A blank AM in one row (vacant post) is a warning, never a rejection."""
    path = _file(tmp_path, REQUIRED, [ROW, {**ROW, "GP Code": "910002", "AM Name": None, "AM Email ID": None}])
    chk = validate_escalation(path)
    assert chk.ok and "FRT Code" in chk.sheets[0].optional_absent and "CBH Email ID" in chk.sheets[0].optional_absent
    p = parse_escalation(path)
    assert len(p.rows) == 2 and {"frt_code", "cbh_name", "fe_phone"} <= set(p.missing)
    assert any(i["code"] == "AM_MISSING" for i in p.issues)
    assert "FRT Code" in p.summary() and "frt_code" not in p.summary()


def test_duplicate_required_column_is_refused(tmp_path):
    path = _file(tmp_path, [*REQUIRED, "AM Name"])
    chk = validate_escalation(path)
    assert not chk.ok and any("Duplicate required column: AM Name" in p.message for p in chk.errors)


def test_preview_names_the_missing_column_and_template_download(client):
    csrf = login(client)
    bad = _xlsx([h for h in REQUIRED if h != "COH Email ID"])
    r = client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": ("esc.xlsx", bad, "application/octet-stream")}, data={"kind": "escalation"}).json()
    assert r["canImport"] is False and r["stage"] == "template" and "COH Email ID" in r["error"]
    sheet = r["columnCheck"]["sheets"][0]
    assert not sheet["requiredOk"] and [c["name"] for c in sheet["required"] if c["header"] is None] == ["COH Email ID"]
    assert any(e["column"] == "COH Email ID" for e in r["templateErrors"])
    good = _xlsx(REQUIRED)  # no optional column at all
    r = client.post("/api/v1/ingestion/preview", headers={"x-csrf-token": csrf}, files={"file": ("esc2.xlsx", good, "application/octet-stream")}, data={"kind": "escalation"}).json()
    assert r["canImport"] is True and r["columnCheck"]["sheets"][0]["requiredOk"] and "FRT Code" in r["columns"]["missingOptional"]
    client.delete(f"/api/v1/ingestion/preview/{r['token']}", headers={"x-csrf-token": csrf})
    t = client.get("/api/v1/ingestion/template/escalation.xlsx")
    assert t.status_code == 200 and "PAGMAS Escalation Matrix Template.xlsx" in t.headers["content-disposition"]


@pytest.mark.skipif(not REAL_FILE.exists(), reason="real Escalation Matrix not available")
def test_real_escalation_matrix_passes():
    chk = validate_escalation(REAL_FILE)
    assert chk.ok and chk.sheets[0].json()["requiredOk"] and not chk.sheets[0].optional_absent
