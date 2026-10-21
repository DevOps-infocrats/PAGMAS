"""data/column_map.json: new column / sheet names without code changes."""

import json

import pytest

from app.ingestion import column_map as cm
from app.ingestion.parser import Issue, _locate_columns
from app.ingestion.workbook import WorkbookError

HEADER = ["Circle", "BA", "District", "Block", "Block Code", "GP", "GP Code", "TOTAL RKM", "HOTO Date", "AMC Date", "AM Name"]


@pytest.fixture
def map_file(tmp_path, monkeypatch):
    """Point the loader at a temporary column_map.json; write(dict | str) creates it."""
    path = tmp_path / "column_map.json"
    monkeypatch.setattr(cm, "map_path", lambda: path)
    cm._cache.update(mtime=None, map=None)

    def write(content):
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        cm._cache.update(mtime=None, map=None)
        return cm.load_column_map()

    yield write
    cm._cache.update(mtime=None, map=None)


def test_built_in_names_without_a_file(map_file):
    m = cm.load_column_map()
    assert m.problems == []
    cols = _locate_columns(HEADER, [], m)
    assert cols["amc_date"] == HEADER.index("AMC Date") and cols["gp_code"] == HEADER.index("GP Code")


def test_renamed_required_column_fails_with_a_suggestion_until_it_is_added(map_file):
    renamed = [("AMC Dt" if h == "AMC Date" else h) for h in HEADER]
    with pytest.raises(WorkbookError) as err:
        _locate_columns(renamed, [], cm.load_column_map())
    msg = str(err.value)
    assert "amc_date" in msg and '"AMC Dt"' in msg and "column_map.json" in msg  # never applied automatically
    m = map_file({"gpColumns": {"amc_date": ["AMC Dt"]}})
    assert _locate_columns(renamed, [], m)["amc_date"] == renamed.index("AMC Dt")
    assert _locate_columns(HEADER, [], m)["amc_date"] == HEADER.index("AMC Date")  # the old name still works


def test_case_and_spaces_do_not_matter(map_file):
    m = map_file({"gpColumns": {"amc_date": ["AMC Dt"]}})
    messy = [("  amc   DT " if h == "AMC Date" else h) for h in HEADER]
    assert _locate_columns(messy, [], m)["amc_date"] == messy.index("  amc   DT ")


def test_old_and_new_name_together_first_listed_wins_with_a_warning(map_file):
    m = map_file({"gpColumns": {"amc_date": ["AMC Dt"]}})
    both = HEADER + ["AMC Dt"]
    issues: list[Issue] = []
    cols = _locate_columns(both, issues, m)
    assert cols["amc_date"] == both.index("AMC Dt")  # file names come first
    assert any(i.code == "COLUMN_DUPLICATE" and "amc_date" in i.message for i in issues)


def test_built_in_names_cannot_be_removed(map_file):
    m = map_file({"gpColumns": {"amc_date": ["Date of AMC"]}})
    assert _locate_columns(HEADER, [], m)["amc_date"] == HEADER.index("AMC Date")


def test_one_name_for_two_fields_is_rejected(map_file):
    m = map_file({"gpColumns": {"amc_date": ["Date"], "hoto_date": ["Date"]}})
    assert "date" not in m.gp["amc_date"] and "date" not in m.gp["hoto_date"]
    assert any("'date'" in p for p in m.problems)
    m = map_file({"gpColumns": {"amc_date": ["HOTO Date"]}})  # a built-in name of another field stays with that field
    assert "hoto date" in m.gp["hoto_date"] and "hoto date" not in m.gp["amc_date"]


def test_broken_or_unknown_content_never_stops_an_import(map_file):
    m = map_file("{ this is not json")
    assert m.problems and "built-in column names used" in m.problems[0]
    assert _locate_columns(HEADER, [], m)["amc_date"] == HEADER.index("AMC Date")
    m = map_file({"gpColumns": {"amc_dt": ["AMC Dt"]}})
    assert any("unknown field 'amc_dt'" in p for p in m.problems)
    m = map_file({"gpColumns": {"amc_date": ["x" * 500]}})
    assert any("too long" in p for p in m.problems)


def test_renamed_header_anchor_and_sheet(map_file):
    m = map_file({"gpColumns": {"gp_code": ["LGD Code"]}, "sheets": {"gp": ["GP Data"]}})
    grid = [["Title"], [], [("LGD Code" if h == "GP Code" else h) for h in HEADER], ["RAJASTHAN"]]
    assert cm.find_header_row(grid, m.gp, cm.GP_HEADER_ANCHORS) == 2
    assert cm.resolve_sheet(["O&M", "gp data", "Master Block"], "gp", m) == "gp data"
    assert cm.resolve_sheet(["GP Wise Data"], "gp", m) == "GP Wise Data"  # the built-in name still works


def test_project_file_is_valid():
    """The column_map.json shipped in data/ loads without problems and only adds names."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "data" / "column_map.json"
    if not path.exists():
        pytest.skip("no data/column_map.json in this checkout")
    data = cm._File.model_validate(json.loads(path.read_text(encoding="utf-8")))
    problems: list[str] = []
    cm._build(data, problems)
    assert problems == []
