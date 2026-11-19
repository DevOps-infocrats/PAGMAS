"""Non-Doable KPI cards → the cases list and the Excel:

* `kpi=ROLE:card` lists exactly the cases the card counts (for every card the user sees – admin and FE);
* the Excel holds the same cases (same filters), only those the user may see;
* an unknown card is refused.
"""

import io

import pandas as pd

from .conftest import login
from .test_nondoable import _case_of, _propose, nd  # noqa: F401 - shared fixture
from .test_ticket_fe import FE1, FE2, fe_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def _cards_match_lists(client):
    s = client.get("/api/v1/nondoable/summary").json()
    assert s["kpis"], s
    for role, cards in s["kpis"].items():
        for key, n in cards.items():
            r = client.get("/api/v1/nondoable/cases", params={"kpi": f"{role}:{key}", "size": 100})
            assert r.status_code == 200, (role, key, r.text)
            assert r.json()["total"] == n, (role, key, n, r.json()["total"])
    return s


def test_kpi_cards_list_exactly_their_cases_and_export(client, nd, mail):  # noqa: F811
    tid, g = nd["tid"], nd["gps"][0]
    assert _propose(client, tid, g["id"]).status_code == 200
    login(client, FE1)
    ref = _case_of(client, g["id"])["ref"]

    # the FE's cards and the admin's cards: each card's list = its count
    s = _cards_match_lists(client)
    assert s["kpis"]["FE"]["actionNeeded"] >= 1
    login(client)
    _cards_match_lists(client)

    # Excel: the same cases as the list (FE "action needed"), headers, only what the user sees
    login(client, FE1)
    r = client.get("/api/v1/nondoable/cases/export.xlsx", params={"kpi": "FE:actionNeeded"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    df = pd.read_excel(io.BytesIO(r.content), engine="calamine", header=3, dtype=str)
    listed = client.get("/api/v1/nondoable/cases", params={"kpi": "FE:actionNeeded", "size": 100}).json()
    assert sorted(df["Case ID"]) == sorted(x["ref"] for x in listed["items"]) and ref in set(df["Case ID"])
    assert {"GP Code", "Status", "Pending with", "E1 complete", "MGG decision"} <= set(df.columns)

    # another FE sees none of FE One's cases – neither in the list nor in the Excel
    login(client, FE2)
    r = client.get("/api/v1/nondoable/cases/export.xlsx")
    df2 = pd.read_excel(io.BytesIO(r.content), engine="calamine", header=3, dtype=str)
    assert ref not in set(df2["Case ID"].dropna())

    # unknown card / malformed value refused
    assert client.get("/api/v1/nondoable/cases", params={"kpi": "FE:nope"}).status_code == 422
    assert client.get("/api/v1/nondoable/cases", params={"kpi": "drop table"}).status_code == 422
