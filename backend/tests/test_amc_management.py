"""AMC Conversion management view: Target (Planned Date) / GP Ready (Ach Date) / GP Achieved (AMC Date) / Gap and the
letters of the ready GPs – each figure recounted here straight from the plan rows and the GP sheet columns."""

import datetime as dt

import numpy as np

from app.analytics.amc_plan import amc_plan_summary, amc_plan_timeline, windows

from .conftest import login


def _between(values, a, b):
    return np.array([isinstance(v, dt.date) and a <= v <= b for v in values], dtype=bool)


def test_summary_ready_achieved_gap_and_letters(imported):
    s = imported
    week = s.weeks[-1].code
    r = amc_plan_summary(s, week)
    w = windows(s, week, month_of_week=True)
    p = s.amc_plan
    amc = s.gps["amc_date"].reindex(p.index)
    letter = s.gps["letter_date"].reindex(p.index)
    state = s.gps["circle"].reindex(p.index).to_numpy()
    ready_m = _between(p["ach_date"], w.month_start, w.month_as_of)
    ready_w = _between(p["ach_date"], w.week_start, min(w.week_end, w.as_of))
    for row in r["rows"]:
        sel = state == next(c for c in s.gps["circle"].unique() if c.title() == row["name"])
        assert row["monthReady"] == row["mtdAchieved"] == int((sel & ready_m).sum())
        assert row["weekReady"] == row["weekAchieved"] == int((sel & ready_w).sum())
        assert row["monthConverted"] == int((sel & _between(amc, w.month_start, w.month_as_of)).sum())
        assert row["weekConverted"] == int((sel & _between(amc, w.week_start, min(w.week_end, w.as_of))).sum())
        assert row["monthGap"] == row["monthTarget"] - row["monthConverted"]
        assert row["weekGap"] == row["weekTarget"] - row["weekConverted"]
        sent = _between(letter, dt.date.min, w.month_as_of)
        assert row["monthReadyLetterSubmitted"] == int((sel & ready_m & sent).sum())
        assert row["monthReadyLetterSubmitted"] + row["monthReadyLetterNotSubmitted"] == row["monthReady"]  # every ready GP once
        assert row["weekReadyLetterSubmitted"] + row["weekReadyLetterNotSubmitted"] == row["weekReady"]
        assert row["monthReadyLetterAccepted"] == int((sel & ready_m & _between(amc, dt.date.min, w.month_as_of)).sum())
        assert row["incMonthConverted"] <= row["monthConverted"]
        inc = p["category"].fillna("").str.lower().str.contains("incremental").to_numpy()
        assert row["incMonthReadyLetterSubmitted"] == int((sel & ready_m & inc & sent).sum())
        assert row["incMonthReadyLetterSubmitted"] + row["incMonthReadyLetterNotSubmitted"] == row["incMtdAchieved"]  # 5% ready GPs, each once
        assert row["incWeekReadyLetterSubmitted"] + row["incWeekReadyLetterNotSubmitted"] == row["incWeekAchieved"]
    for k in ("monthConverted", "weekConverted", "monthGap", "weekGap", "monthReadyLetterSubmitted", "monthReadyLetterNotSubmitted", "monthReadyLetterAccepted", "weekReadyLetterAccepted"):
        assert r["total"][k] == sum(x[k] for x in r["rows"]), k
    # the existing figures are unchanged by the new ones
    assert r["total"]["mtdAchieved"] == int(ready_m.sum())


def test_timeline_cells_have_ready_achieved_gap(imported):
    t = amc_plan_timeline(imported, imported.weeks[-1].code)
    for part, periods in (("monthly", "months"), ("weekly", "weeks")):
        for row in [*t[part]["rows"], t[part]["total"]]:
            for per, c in zip(t[part][periods], row["cells"]):
                if per["status"] == "not started":
                    assert c["ready"] is None and c["converted"] is None and c["gap"] is None
                    continue
                assert c["ready"] == c["achieved"]
                assert c["gap"] == c["target"] - c["converted"]
        for i, per in enumerate(t[part][periods]):
            if per["status"] != "not started":
                assert t[part]["total"]["cells"][i]["converted"] == sum(r["cells"][i]["converted"] for r in t[part]["rows"])


def test_converted_lists_match_the_cards(imported, client):
    login(client)
    week = imported.weeks[-1].code
    r = amc_plan_summary(imported, week)
    for kind, key in (("amc-converted-mtd", "monthConverted"), ("amc-converted-week", "weekConverted")):
        body = client.get(f"/api/v1/kpi-lists/{kind}", params={"week": week, "page_size": 200}).json()
        assert body["total"] == r["total"][key], kind
        assert all(i["amcDate"] for i in body["items"])
