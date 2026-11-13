"""Field Team & Escalation → Escalation Sheet: every user reads only their GPs (phones masked for non-admins), only
admins edit; edits are validated, all-or-nothing, conflict-safe, recorded, visible everywhere at once (AM names of
AMC Conversion / tickets), find-and-replace works on whole cells, and the export can be uploaded again."""

import io

import pytest
from python_calamine import CalamineWorkbook
from sqlalchemy import delete, select, update

from app.analytics.escalation import invalidate_escalation
from app.db import SessionLocal
from app.models import AuditLog, EscalationContact, EscalationEdit, EscalationImport

from .conftest import VIEWER, login


@pytest.fixture
def matrix(imported):
    """An active Escalation Matrix with three real GPs of the test dataset (the previous active import is restored)."""
    codes = [str(c) for c in imported.gps.index[:3]]
    circle = str(imported.gps.at[imported.gps.index[0], "circle"])
    with SessionLocal() as db:
        prev = list(db.scalars(select(EscalationImport.id).where(EscalationImport.is_active.is_(True))))
        db.execute(update(EscalationImport).values(is_active=False))
        imp = EscalationImport(file_name="sheet-test.xlsx", stored_path="none", sha256="s" * 64, status="SUCCESS", is_active=True)
        db.add(imp)
        db.flush()
        for i, code in enumerate(codes):
            db.add(EscalationContact(import_id=imp.id, gp_code=code, circle=circle, frt_code=f"F-{i}", fe_name=f"Fe {i}", fe_phone="9876543210", am_name="Ravi Kumar" if i < 2 else "Mohan", am_email="ravi@x.in"))
        db.commit()
        imp_id = imp.id
    invalidate_escalation()
    yield {"id": imp_id, "codes": codes}
    with SessionLocal() as db:
        db.execute(delete(EscalationImport).where(EscalationImport.id == imp_id))
        if prev:
            db.execute(update(EscalationImport).where(EscalationImport.id.in_(prev)).values(is_active=True))
        db.commit()
    invalidate_escalation()


def _row(client, code):
    rows = client.get("/api/v1/field-team/sheet", params={"search": code}).json()["rows"]
    return next(r for r in rows if r["gpCode"] == code)


def test_admin_reads_full_and_edits_cells(client, matrix):
    csrf = login(client)
    s = client.get("/api/v1/field-team/sheet").json()
    assert s["source"]["importId"] == matrix["id"] and s["total"] == 3 and s["canEdit"] is True
    assert {c["key"] for c in s["columns"] if not c["editable"]} == {"circle", "gp_code", "block_code"}
    code = matrix["codes"][0]
    assert _row(client, code)["values"]["fe_phone"] == "9876543210"  # admins see the full number
    r = client.patch("/api/v1/field-team/sheet", headers={"x-csrf-token": csrf}, json={"importId": matrix["id"], "changes": [
        {"gpCode": code, "field": "am_name", "old": "Ravi Kumar", "new": "  Ravi   Kumar Sharma "},
        {"gpCode": code, "field": "fe_email", "old": None, "new": "FE.A@X.IN"},
    ]})
    assert r.status_code == 200 and r.json()["saved"] == 2, r.text
    v = _row(client, code)["values"]
    assert v["am_name"] == "Ravi Kumar Sharma" and v["fe_email"] == "fe.a@x.in"  # trimmed, single spaces, lower-case e-mail
    with SessionLocal() as db:
        assert db.scalar(select(EscalationContact.am_name).where(EscalationContact.import_id == matrix["id"], EscalationContact.gp_code == code)) == "Ravi Kumar Sharma"
        e = db.scalars(select(EscalationEdit).where(EscalationEdit.gp_code == code, EscalationEdit.field == "am_name")).one()
        assert (e.old_value, e.new_value) == ("Ravi Kumar", "Ravi Kumar Sharma") and e.edited_by_name
        assert db.scalar(select(AuditLog.id).where(AuditLog.action == "escalation_edit").order_by(AuditLog.id.desc()).limit(1))
    assert client.get("/api/v1/field-team/sheet/edits", params={"gpCode": code}).json()["items"][0]["new"] in ("Ravi Kumar Sharma", "fe.a@x.in")


def test_edits_reach_the_other_pages_at_once(client, matrix, imported):
    from app.analytics.amc_plan import _am_names

    csrf = login(client)
    code = matrix["codes"][2]
    assert client.patch("/api/v1/field-team/sheet", headers={"x-csrf-token": csrf}, json={"importId": matrix["id"], "changes": [{"gpCode": code, "field": "am_name", "old": "Mohan", "new": "Mohan Lal"}]}).status_code == 200
    names = _am_names(imported, imported.gps.index[:3])[0]
    assert names[imported.gps.index[2]] == "Mohan Lal"  # AMC Conversion AM tables / Generate Ticket read the same contacts


def test_invalid_values_and_conflicts_save_nothing(client, matrix):
    csrf = login(client)
    a, b = matrix["codes"][:2]
    send = lambda changes: client.patch("/api/v1/field-team/sheet", headers={"x-csrf-token": csrf}, json={"importId": matrix["id"], "changes": changes})  # noqa: E731
    r = send([{"gpCode": a, "field": "am_name", "old": "Ravi Kumar", "new": "Valid Name"}, {"gpCode": b, "field": "fe_phone", "old": "9876543210", "new": "12345"}])
    assert r.status_code == 422 and r.json()["problems"][0]["field"] == "fe_phone"
    assert _row(client, a)["values"]["am_name"] == "Ravi Kumar"  # all-or-nothing
    assert send([{"gpCode": a, "field": "am_email", "old": "ravi@x.in", "new": "not an email"}]).status_code == 422
    assert send([{"gpCode": a, "field": "gp_code", "old": a, "new": "1"}]).status_code == 422  # identity is never edited
    r = send([{"gpCode": a, "field": "am_name", "old": "Someone Else", "new": "X"}])  # the cell changed meanwhile
    assert r.status_code == 409 and r.json()["problems"][0]["conflict"] is True and r.json()["problems"][0]["current"] == "Ravi Kumar"
    r = client.patch("/api/v1/field-team/sheet", headers={"x-csrf-token": csrf}, json={"importId": matrix["id"] + 999, "changes": [{"gpCode": a, "field": "am_name", "old": "Ravi Kumar", "new": "X"}]})
    assert r.status_code == 409 and "replaced" in r.json()["detail"]
    assert send([{"gpCode": a, "field": "fe_phone", "old": "9876543210", "new": "98765 43210 / 9123456789"}]).json()["saved"] == 1
    assert _row(client, a)["values"]["fe_phone"] == "9876543210 / 9123456789"


def test_find_and_replace_whole_cells(client, matrix):
    csrf = login(client)
    body = {"importId": matrix["id"], "field": "am_name", "find": "ravi  kumar", "replace": "Ravi K. Sharma"}
    dry = client.post("/api/v1/field-team/sheet/replace", headers={"x-csrf-token": csrf}, json=body | {"dryRun": True}).json()
    assert dry["matches"] == 2 and dry["saved"] == 0
    done = client.post("/api/v1/field-team/sheet/replace", headers={"x-csrf-token": csrf}, json=body | {"dryRun": False}).json()
    assert done["saved"] == 2
    assert [_row(client, c)["values"]["am_name"] for c in matrix["codes"]] == ["Ravi K. Sharma", "Ravi K. Sharma", "Mohan"]
    assert client.post("/api/v1/field-team/sheet/replace", headers={"x-csrf-token": csrf}, json=body | {"field": "circle", "dryRun": True}).status_code == 422


def test_viewers_read_masked_and_cannot_edit(client, matrix):
    csrf = login(client, VIEWER)
    s = client.get("/api/v1/field-team/sheet").json()
    assert s["canEdit"] is False and not any(c["editable"] for c in s["columns"])
    for r in s["rows"]:
        assert "X" in (r["values"]["fe_phone"] or "X")
    code = matrix["codes"][0]
    assert client.patch("/api/v1/field-team/sheet", headers={"x-csrf-token": csrf}, json={"importId": matrix["id"], "changes": [{"gpCode": code, "field": "am_name", "old": "Ravi Kumar", "new": "X"}]}).status_code == 403
    assert client.get("/api/v1/field-team/sheet/edits").status_code == 403


def test_export_uses_the_upload_headers(client, matrix):
    login(client)
    r = client.get("/api/v1/field-team/sheet/export.xlsx")
    assert r.status_code == 200 and "Escalation_Matrix_export.xlsx" in r.headers["content-disposition"]
    rows = CalamineWorkbook.from_filelike(io.BytesIO(r.content)).get_sheet_by_name("All").to_python()
    assert rows[0][:8] == ["Circle", "BA", "District", "Block Name", "Block Code", "GP", "GP Code", "FRT Code"] and "AM Name" in rows[0]
    assert sorted(str(x[6]) for x in rows[1:]) == sorted(matrix["codes"])
    from app.ingestion.escalation import _header_row

    assert _header_row(rows) == 0  # the importer recognises the exported file as an Escalation Matrix
