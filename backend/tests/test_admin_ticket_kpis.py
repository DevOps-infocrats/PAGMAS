"""Admin Tickets: the KPIs and the GP categories follow the list filters (the tickets the list shows).

* no filter: every ticket / every GP of the task tickets (as before);
* a filter (circle, status, …): only the matching tickets – the KPI total equals the list total;
* User Tickets (scope=mine) without filters is unchanged.
"""

from .conftest import VIEWER, login
from .test_ticket_fe import fe_org  # noqa: F401 - shared fixture
from .evidence import progress
from .test_ticket_frt import FRT, _ticket, frt_org  # noqa: F401
from .test_ticket_recipients import mail  # noqa: F401
from .test_ticket_tasks import am_week  # noqa: F401


def test_kpis_and_gp_categories_follow_the_filters(client, frt_org, mail):  # noqa: F811
    tid = _ticket(client, frt_org)
    circle = frt_org["circle"]
    login(client)
    every = client.get("/api/v1/tickets/kpis", params={"scope": "all"}).json()
    assert every["total"] >= 1
    gps_all = client.get("/api/v1/tickets/gp-categories").json()
    assert gps_all["total"] >= 1 and gps_all["total"] == client.get("/api/v1/tickets/gp-monitor/summary", params={"basis": "category"}).json()["total"]

    # the ticket's circle: the KPI total is the list total
    k = client.get("/api/v1/tickets/kpis", params={"scope": "all", "circle": circle}).json()
    lst = client.get("/api/v1/tickets", params={"scope": "all", "circle": circle, "page_size": 100}).json()
    assert k["total"] == lst["total"] >= 1 and tid in [t["id"] for t in lst["items"]]
    assert sum(k["byStatus"].values()) == k["total"]
    assert client.get("/api/v1/tickets/gp-categories", params={"circle": circle}).json()["total"] >= 1

    # a circle without tickets: nothing
    none = client.get("/api/v1/tickets/kpis", params={"scope": "all", "circle": "No Such Circle"}).json()
    assert none["total"] == 0
    assert client.get("/api/v1/tickets/gp-categories", params={"circle": "No Such Circle"}).json()["total"] == 0

    # a status filter: only that status
    st = client.get("/api/v1/tickets/kpis", params={"scope": "all", "status": "OPEN"}).json()
    assert st["total"] == st["byStatus"]["OPEN"] == every["byStatus"]["OPEN"]
    # the same rules as the list; a wrong date range is refused
    assert client.get("/api/v1/tickets/kpis", params={"scope": "all", "date_from": "2026-11-20", "date_to": "2026-11-01"}).status_code == 422
    # User Tickets: unchanged
    assert client.get("/api/v1/tickets/kpis", params={"scope": "mine"}).status_code == 200


def test_kpis_count_the_people_of_the_tickets_and_who_worked(client, frt_org, mail):  # noqa: F811
    """One ticket per AM, shared with its FEs and FRT teams: Total = AM + FE + FRT (per ticket); In Progress = who
    worked on it; each list row shows its GPs filled and who worked."""
    tid = _ticket(client, frt_org)
    circle = frt_org["circle"]
    login(client)
    before = client.get("/api/v1/tickets/kpis", params={"scope": "all", "circle": circle}).json()["work"]
    assert before["total"] == before["am"] + before["fe"] + before["frt"] and before["am"] == before["tickets"] >= 1
    row = next(t for t in client.get("/api/v1/tickets", params={"scope": "all", "circle": circle, "page_size": 100}).json()["items"] if t["id"] == tid)
    assert row["work"]["gps"] >= 1 and row["work"]["frt"] >= 1 and row["work"]["frtWorked"] == 0 and row["work"]["filled"] == 0

    d = client.get(f"/api/v1/tickets/{tid}").json()
    g = next(x["id"] for x in d["task"]["gps"] if x["gpCode"] in frt_org["one"])
    hf = {"X-CSRF-Token": login(client, FRT)}
    assert progress(client, tid, [{"taskGpId": g, "category": "A", "remark": "Splicing done"}], hf).status_code == 200

    login(client)
    after = client.get("/api/v1/tickets/kpis", params={"scope": "all", "circle": circle}).json()["work"]
    assert after["frtWorked"] == before["frtWorked"] + 1 and after["worked"] == before["worked"] + 1
    assert after["filled"] == before["filled"] + 1
    # the Team table: logins per role never exceed the people; the FRT account of the test has a login
    for t in (before, after):
        assert t["amLogin"] <= t["am"] and t["feLogin"] <= t["fe"] and t["frtLogin"] <= t["frt"]
        assert t["frtLogin"] == t["frt"] - t["frtNoLogin"] and t["frtLogin"] >= 1
    row = next(t for t in client.get("/api/v1/tickets", params={"scope": "all", "circle": circle, "page_size": 100}).json()["items"] if t["id"] == tid)
    assert row["work"]["frtWorked"] == 1 and row["work"]["filled"] == 1
    # User Tickets: unchanged (no work totals)
    assert "work" not in client.get("/api/v1/tickets/kpis", params={"scope": "mine"}).json()

    # the GP cards: Not Filled with who has to fill it (adds up), the FRT's Rectification Done waits for the FE
    gc = client.get("/api/v1/tickets/gp-categories", params={"circle": circle}).json()
    assert gc["notFilled"] == sum(gc["notFilledOwners"].values()) and gc["notFilled"] <= gc["total"]
    assert gc["categoryWaiting"]["A"].get("FE to verify", 0) >= 1
    # "Tickets in Progress": the ticket, who worked, what was reported, who acts next
    items = client.get("/api/v1/tickets/working", params={"circle": circle}).json()["items"]
    it = next(x for x in items if x["id"] == tid)
    assert any("(FRT)" in w for w in it["work"]["workers"]) and it["work"]["lastAt"]
    assert it["categories"].get("Rectification Done") == 1 and it["waiting"].get("FE to verify") == 1
    # a ticket nobody worked on is not listed; viewers cannot open the list
    other = _ticket(client, frt_org)
    assert other not in [x["id"] for x in client.get("/api/v1/tickets/working", params={"circle": circle}).json()["items"]]
    login(client, VIEWER)
    assert client.get("/api/v1/tickets/working").status_code == 403
