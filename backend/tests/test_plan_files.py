import shutil

from app.analytics.amc_plan import load_month_targets
from app.config import get_settings
from .conftest import VIEWER, login


def _cleanup():
    d = get_settings().data_dir
    (d / "amc_month_targets.json").unlink(missing_ok=True)
    shutil.rmtree(d / "plan_history", ignore_errors=True)


def test_admin_edits_plan_file_with_history(client):
    _cleanup()
    try:
        csrf = login(client)
        h = {"x-csrf-token": csrf}
        files = {f["name"]: f for f in client.get("/api/v1/plan-files").json()}
        assert set(files) == {"review_plan.json", "amc_month_targets.json"}

        body = {"data": {"_help": "keep me", "source": "Test", "targets": {"2026-12": {"assam": "250", "HARYANA": ""}, "2026-11": {"ASSAM": 200}}}}
        r = client.put("/api/v1/plan-files/amc_month_targets.json", json=body, headers=h)
        assert r.status_code == 200, r.text
        saved = r.json()["data"]
        assert saved["_help"] == "keep me"
        assert list(saved["targets"]) == ["2026-11", "2026-12"]
        assert saved["targets"]["2026-12"] == {"ASSAM": 250, "HARYANA": None}

        targets, problem = load_month_targets()
        assert problem is None and targets.targets["2026-12"]["ASSAM"] == 250

        hist = client.get("/api/v1/plan-files/amc_month_targets.json/history").json()
        assert hist[0]["savedBy"] == "admin@pratap-test.in" and hist[0]["content"]["targets"]["2026-11"]["ASSAM"] == 200

        for bad in ({"targets": {"2026-13": {"ASSAM": 1}}}, {"targets": {"2026-11": {"ASSAM": -1}}}, {"targets": {"2026-11": {"ASSAM": 1.5}}}):
            assert client.put("/api/v1/plan-files/amc_month_targets.json", json={"data": bad}, headers=h).status_code == 422
        assert client.put("/api/v1/plan-files/other.json", json={"data": {}}, headers=h).status_code == 422
    finally:
        _cleanup()


def test_viewer_cannot_edit_plan_files(client):
    csrf = login(client, VIEWER)
    assert client.get("/api/v1/plan-files").status_code == 403
    assert client.put("/api/v1/plan-files/review_plan.json", json={"data": {}}, headers={"x-csrf-token": csrf}).status_code == 403
