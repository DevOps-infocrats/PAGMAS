"""Weeks missing from the file are derived from the daily values with the file's own rule."""

import copy
from pathlib import Path

import pytest

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def test_derived_week_equals_the_files_own_week_column():
    """Drop W-42 from the 14 Oct file and derive it again: every GP's value equals the file's W-42 column."""
    from app.ingestion.parser import _derive_missing_weeks, parse_workbook

    path = RAW / "Master Data V8.2 Daily track 14-10-26.xlsb"
    if not path.exists():
        pytest.skip("14 Oct workbook not available")
    p = parse_workbook(path)
    assert not [i for i in p.issues if i.code == "WEEK_DERIVED"]  # data ends inside W-42: nothing to add
    truth = {g: v for g, k, per, v in p.availability if k == "W" and per == "W-42"}
    q = copy.copy(p)
    q.weeks = [w for w in p.weeks if w["code"] != "W-42"]
    q.availability = [a for a in p.availability if not (a[1] == "W" and a[2] == "W-42")]
    q.issues = []
    _derive_missing_weeks(q)
    week = next(w for w in q.weeks if w["code"] == "W-42")
    assert (week["start_date"].isoformat(), week["end_date"].isoformat()) == ("2026-10-09", "2026-10-15")
    derived = {g: v for g, k, per, v in q.availability if k == "W" and per == "W-42"}
    assert derived.keys() == truth.keys()
    assert all(abs(derived[g] - truth[g]) < 0.01 for g in truth)
    assert [i.code for i in q.issues] == ["WEEK_DERIVED"]
