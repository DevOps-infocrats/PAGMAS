"""KPI drill-down lists: the GPs / blocks behind a Circle Overview KPI card, plus an Excel export.

Every list uses exactly the rule of its card (analytics/metrics.summarize), on the same reporting
week, so the unfiltered total always equals the number on the card:

  gps-above-98    AMC GPs whose month-to-date availability is strictly above the healthy threshold (98%)
  gps-at-zero     AMC GPs whose month-to-date availability is exactly 0% (NA = not reported, never 0)
  penalty-blocks  blocks whose mean AMC GP month-to-date availability is below the penalty threshold (90%)
  hoto-gps        GPs whose HOTO date is on or before the reporting week end
  hoto-blocks     blocks with at least one such GP
  hoto-pending-gps  revised existing GPs (not converted / closed) without a HOTO date by the week end
  removed-gps     GPs converted to NP / permanently closed / deducted ("Converted to NP & Closed" column)
  amc-*           GP-wise AMC conversion plan (analytics/amc_plan.py): month / month-to-date / week target
                  (Planned Date), achieved (Ach Date) and overdue – same masks as the AMC Conversion KPIs

State / district / block / search only narrow the list down; they never change the rule.
Each list has one "value" column used for sorting: MTD availability, HOTO date or HOTO coverage.
"""

from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from ..config import get_settings
from .metrics import r2
from .store import Store

KpiKind = Literal["gps-above-98", "gps-at-zero", "penalty-blocks", "hoto-gps", "hoto-blocks", "existing-gps", "new-gp-blocks", "na-gps", "one-time-up", "hoto-pending-gps", "removed-gps", "amc-plan-month", "amc-plan-mtd", "amc-achieved-mtd", "amc-plan-week", "amc-achieved-week", "amc-overdue"]
SortKey = Literal["value-desc", "value-asc", "name"]
KINDS: tuple[str, ...] = ("gps-above-98", "gps-at-zero", "penalty-blocks", "hoto-gps", "hoto-blocks", "existing-gps", "new-gp-blocks", "na-gps", "one-time-up", "hoto-pending-gps", "removed-gps", "amc-plan-month", "amc-plan-mtd", "amc-achieved-mtd", "amc-plan-week", "amc-achieved-week", "amc-overdue")
DEFAULT_SORT: dict[str, str] = {
    "gps-above-98": "value-desc",
    "gps-at-zero": "name",
    "penalty-blocks": "value-asc",
    "hoto-gps": "name",
    "hoto-blocks": "name",
    "existing-gps": "name",
    "new-gp-blocks": "value-desc",
    "na-gps": "name",
    "one-time-up": "value-desc",
    "hoto-pending-gps": "name",
    "removed-gps": "value-asc",
    "amc-plan-month": "value-asc",
    "amc-plan-mtd": "value-asc",
    "amc-achieved-mtd": "value-desc",
    "amc-plan-week": "value-asc",
    "amc-achieved-week": "value-desc",
    "amc-overdue": "value-asc",
}
# AMC plan list -> (mask key in amc_plan.masks, title, rule, value column)
AMC_LISTS: dict[str, tuple[str, str, str, str]] = {
    "amc-plan-month": ("month-target", "AMC Conversion – Month Target GPs", "GPs whose Planned Date falls in the month of the data date", "plannedDate"),
    "amc-plan-mtd": ("mtd-target", "AMC Conversion – Month-to-date Target GPs", "GPs whose Planned Date falls between the 1st of the month and the data date", "plannedDate"),
    "amc-achieved-mtd": ("mtd-achieved", "AMC Conversion – Achieved (Month-to-date)", "GPs whose Ach Date falls between the 1st of the month and the data date", "achDate"),
    "amc-plan-week": ("week-target", "AMC Conversion – Week Target GPs", "GPs whose Planned Date falls in the reporting week (Fri–Thu)", "plannedDate"),
    "amc-achieved-week": ("week-achieved", "AMC Conversion – Achieved in the Week", "GPs whose Ach Date falls in the reporting week, up to the data date", "achDate"),
    "amc-overdue": ("overdue", "AMC Conversion – Overdue GPs", "GPs whose Planned Date is on or before the data date but with no Ach Date by then", "plannedDate"),
}
LIFECYCLE_LABEL = {"ACTIVE": "In scope", "CONVERTED_NP": "Converted to NP", "PERMANENTLY_CLOSED": "Closed / removed", "DEDUCTED": "Deducted (portal entry)"}


@dataclass(frozen=True)
class _Spec:
    unit: Literal["gp", "block"]
    title: str
    rule: str
    # (key, Excel header, width, kind) – kind: text | int | pct | date
    columns: tuple[tuple[str, str, int, str], ...]


def _spec(kind: str) -> _Spec:
    s = get_settings()
    gp_cols = (("name", "GP name", 28, "text"), ("code", "GP code", 14, "text"), ("circle", "State", 14, "text"), ("district", "District", 18, "text"), ("block", "Block", 20, "text"))
    blk_cols = (("name", "Block name", 26, "text"), ("code", "Block code", 13, "text"), ("circle", "State", 14, "text"), ("district", "District", 18, "text"))
    if kind == "gps-above-98":
        return _Spec("gp", f"GPs Above {s.healthy_threshold:g}% Availability (MTD)", f"AMC GPs with month-to-date availability above {s.healthy_threshold:g}% (exactly {s.healthy_threshold:g}% is not counted)",
                     gp_cols + (("amcDate", "AMC date", 13, "date"), ("availability", "MTD availability %", 18, "pct")))
    if kind == "gps-at-zero":
        return _Spec("gp", "GPs at 0% Availability (MTD)", "AMC GPs with exactly 0% month-to-date availability (GPs that did not report are NA, never 0%)",
                     gp_cols + (("amcDate", "AMC date", 13, "date"), ("availability", "MTD availability %", 18, "pct")))
    if kind == "penalty-blocks":
        return _Spec("block", f"Penalty-Prone Blocks <{s.penalty_threshold:g}% (MTD)", f"Blocks whose mean month-to-date availability of their AMC GPs is below {s.penalty_threshold:g}%",
                     blk_cols + (("amcGps", "AMC GPs", 11, "int"), ("reportedGps", "Reporting GPs", 14, "int"), ("availability", "MTD availability %", 18, "pct")))
    if kind == "hoto-gps":
        return _Spec("gp", "HOTO Done GPs", "GPs whose HOTO date is on or before the reporting week end",
                     gp_cols + (("hotoDate", "HOTO date", 13, "date"), ("amcDate", "AMC date", 13, "date")))
    if kind == "existing-gps":
        return _Spec("gp", "Existing GPs", "Every GP row of the GP Wise Data sheet; status from the 'Converted to NP & Closed' column (blank = in scope)",
                     gp_cols + (("status", "Status", 22, "text"), ("hotoDate", "HOTO date", 13, "date"), ("amcDate", "AMC date", 13, "date")))
    if kind == "new-gp-blocks":
        return _Spec("block", "New GPs (block-wise)", "New GPs from the Master Block sheet - the workbook lists them per block only, without GP names or codes",
                     blk_cols + (("existingGps", "Existing GPs", 13, "int"), ("newGps", "New GPs", 11, "int"), ("totalGps", "Total GPs", 11, "int")))
    if kind == "na-gps":
        return _Spec("gp", "AMC GPs Not Reported (NA, MTD)", "AMC GPs without any month-to-date availability value - shown as NA, never counted as 0%",
                     gp_cols + (("amcDate", "AMC date", 13, "date"),))
    if kind == "hoto-pending-gps":
        return _Spec("gp", "HOTO Pending GPs", "Revised existing GPs (not converted to NP / closed / deducted) without a HOTO date on or before the reporting week end",
                     gp_cols + (("amName", "Area manager", 22, "text"),))
    if kind == "removed-gps":
        return _Spec("gp", "GPs Converted to NP / Closed", "Existing GPs removed from scope, from the 'Converted to NP & Closed' column (the source records no date for these changes)",
                     gp_cols + (("status", "Reason", 24, "text"), ("remark", "Source remark", 30, "text"), ("hotoDate", "HOTO date", 13, "date"), ("amcDate", "AMC date", 13, "date")))
    if kind in AMC_LISTS:
        return _Spec("gp", AMC_LISTS[kind][1], AMC_LISTS[kind][2],
                     gp_cols + (("category", "Plan type", 18, "text"), ("plannedDate", "Planned date", 13, "date"), ("achDate", "Ach date", 13, "date"),
                                ("planStatus", "Current status", 15, "text"), ("letterStatus", "Letter status", 13, "text")))
    if kind == "one-time-up":
        return _Spec("gp", "One-Time UP GPs (Sept)", "GPs (all, not only AMC) whose September availability is above 0%",
                     gp_cols + (("availability", "Sept availability %", 18, "pct"),))
    return _Spec("block", "HOTO Done Blocks", "Blocks with at least one GP whose HOTO date is on or before the reporting week end",
                 blk_cols + (("totalGps", "GPs in block", 13, "int"), ("hotoGps", "HOTO done GPs", 15, "int"), ("hotoPct", "HOTO done %", 13, "pct")))


def _iso(values: pd.Series) -> list[str | None]:
    return [d.isoformat() if isinstance(d, dt.date) else None for d in values]


def _gp_frame(sub: pd.DataFrame) -> dict[str, Any]:
    return {
        "id": sub.index,
        "name": sub["name"].astype(str).str.title().to_numpy(),
        "code": sub.index,
        "circleId": sub["circle_id"].to_numpy(),
        "circle": sub["circle"].str.title().to_numpy(),
        "districtId": sub["district_id"].to_numpy(),
        "district": sub["district"].str.title().to_numpy(),
        "blockId": sub["block_id"].to_numpy(),
        "block": sub["block_name"].str.title().to_numpy(),
    }


def _block_frame(g: pd.DataFrame, ids: pd.Index) -> dict[str, Any]:
    first = g.drop_duplicates("block_id").set_index("block_id").loc[ids]
    return {
        "id": ids,
        "name": first["block_name"].str.title().to_numpy(),
        "code": first["block_code"].astype(str).to_numpy(),
        "circleId": first["circle_id"].to_numpy(),
        "circle": first["circle"].str.title().to_numpy(),
        "districtId": first["district_id"].to_numpy(),
        "district": first["district"].str.title().to_numpy(),
        "blockId": ids,
        "block": first["block_name"].str.title().to_numpy(),
    }


def _rows(store: Store, kind: str, week: str, as_of: dt.date | None = None) -> pd.DataFrame:
    """All rows of the KPI (no filters), one per GP or per block, with the list columns and "value"."""
    s = get_settings()
    g = store.gps
    wf = store.week_frame(week)
    amc = wf["amc"]
    hoto = wf["hoto_done"]
    mtd = wf["mtd"].where(amc)
    if kind in ("gps-above-98", "gps-at-zero"):
        sel = (mtd > s.healthy_threshold) if kind == "gps-above-98" else (mtd == 0)
        sub = g[sel.to_numpy()]
        vals = mtd[sel].round(2).to_numpy()
        return pd.DataFrame({**_gp_frame(sub), "amcDate": _iso(sub["amc_date"]), "availability": vals, "value": vals})
    if kind == "hoto-gps":
        sub = g[hoto.to_numpy()]
        dates = _iso(sub["hoto_date"])
        amc_dates = [d if a else None for d, a in zip(_iso(sub["amc_date"]), amc[hoto].to_numpy())]
        return pd.DataFrame({**_gp_frame(sub), "hotoDate": dates, "amcDate": amc_dates, "value": dates})
    if kind == "existing-gps":
        status = g["lifecycle"].map(LIFECYCLE_LABEL).fillna("In scope").to_numpy()
        amc_dates = [d if a else None for d, a in zip(_iso(g["amc_date"]), amc.to_numpy())]
        hoto_dates = [d if h else None for d, h in zip(_iso(g["hoto_date"]), hoto.to_numpy())]
        return pd.DataFrame({**_gp_frame(g), "status": status, "hotoDate": hoto_dates, "amcDate": amc_dates, "value": hoto_dates})
    if kind == "hoto-pending-gps":
        sel = g["revised"] & ~hoto
        sub = g[sel.to_numpy()]
        names = sub["am_name"].where(sub["am_name"].notna(), None).to_numpy()
        return pd.DataFrame({**_gp_frame(sub), "amName": names, "value": sub["name"].astype(str).str.title().to_numpy()})
    if kind == "removed-gps":
        sel = g["lifecycle"] != "ACTIVE"
        sub = g[sel.to_numpy()]
        status = sub["lifecycle"].map(LIFECYCLE_LABEL).to_numpy()
        remark = [str(v).strip() if isinstance(v, str) else None for v in sub["np_status"]]
        amc_dates = [d if a else None for d, a in zip(_iso(sub["amc_date"]), amc[sel].to_numpy())]
        hoto_dates = [d if h else None for d, h in zip(_iso(sub["hoto_date"]), hoto[sel].to_numpy())]
        return pd.DataFrame({**_gp_frame(sub), "status": status, "remark": remark, "hotoDate": hoto_dates, "amcDate": amc_dates, "value": status})
    if kind in AMC_LISTS:
        from .amc_plan import masks, windows

        plan = store.amc_plan
        cols = ["category", "plannedDate", "achDate", "planStatus", "letterStatus"]
        if plan.empty:
            return pd.DataFrame(columns=[*_gp_frame(g.iloc[:0]).keys(), *cols, "value"])
        sel_plan = plan[masks(store, windows(store, week, as_of))[AMC_LISTS[kind][0]]]
        sub = g.loc[sel_plan.index]
        planned, achieved = _iso(sel_plan["planned_date"]), _iso(sel_plan["ach_date"])
        value = achieved if AMC_LISTS[kind][3] == "achDate" else planned
        return pd.DataFrame(
            {
                **_gp_frame(sub),
                "category": sel_plan["category"].where(sel_plan["category"].notna(), None).to_numpy(),
                "plannedDate": planned,
                "achDate": achieved,
                "planStatus": sel_plan["current_status"].where(sel_plan["current_status"].notna(), None).to_numpy(),
                "letterStatus": sel_plan["letter_status"].where(sel_plan["letter_status"].notna(), None).to_numpy(),
                "value": value,
            }
        )
    if kind == "na-gps":
        sel = amc & mtd.isna()
        sub = g[sel.to_numpy()]
        dates = _iso(sub["amc_date"])
        return pd.DataFrame({**_gp_frame(sub), "amcDate": dates, "value": dates})
    if kind == "one-time-up":
        sel = store.one_time_up_sept
        sub = g[sel.to_numpy()]
        col = f"{store.data_as_of.year}-09"
        vals = store.monthly.loc[sub.index, col].round(2).to_numpy() if col in store.monthly.columns else np.full(len(sub), np.nan)
        return pd.DataFrame({**_gp_frame(sub), "availability": vals, "value": vals})
    if kind == "new-gp-blocks":
        return _new_gp_blocks(store)
    if kind == "hoto-blocks":
        by = hoto.groupby(g["block_id"])
        done = by.sum()
        ids = done[by.any()].index
        total = by.size().loc[ids]
        pct = (done.loc[ids] / total * 100).round(2)
        return pd.DataFrame({**_block_frame(g, ids), "totalGps": total.astype(int).to_numpy(), "hotoGps": done.loc[ids].astype(int).to_numpy(), "hotoPct": pct.to_numpy(), "value": pct.to_numpy()})
    # penalty-prone blocks: same block mean as the card (blocks without any AMC value are NaN -> not counted)
    block_avail = mtd.groupby(g["block_id"]).mean()
    pen = block_avail[block_avail < s.penalty_threshold]
    amc_gps = amc.groupby(g["block_id"]).sum().loc[pen.index]
    reported = mtd.notna().groupby(g["block_id"]).sum().loc[pen.index]
    vals = pen.round(2).to_numpy()
    return pd.DataFrame({**_block_frame(g, pen.index), "amcGps": amc_gps.astype(int).to_numpy(), "reportedGps": reported.astype(int).to_numpy(), "availability": vals, "value": vals})


def _new_gp_blocks(store: Store) -> pd.DataFrame:
    """Master Block rows with new GPs (the same rows the 'New GPs' total of the overview adds up)."""
    from .store import circle_code, slug

    mb = store.master_blocks
    cols = ["id", "name", "code", "circleId", "circle", "districtId", "district", "blockId", "block", "existingGps", "newGps", "totalGps", "value"]
    if mb.empty:
        return pd.DataFrame(columns=cols)
    mb = mb[mb["new_gps"].fillna(0) > 0]
    g = store.gps.drop_duplicates("block_id").set_index("block_id")
    rows = []
    for r in mb.itertuples():
        bid = f"{circle_code(r.state).lower()}-{r.block_code}"
        known = bid in g.index
        new = int(r.new_gps)
        rows.append(
            {
                "id": bid,
                "name": str(r.block_name or r.block_code).title(),
                "code": str(r.block_code),
                "circleId": slug(r.state),
                "circle": str(r.state).title(),
                "districtId": g.at[bid, "district_id"] if known else "",
                "district": str(g.at[bid, "district"]).title() if known else "-",
                "blockId": bid,
                "block": str(r.block_name or r.block_code).title(),
                "existingGps": int(r.existing_gps) if r.existing_gps == r.existing_gps and r.existing_gps is not None else None,
                "newGps": new,
                "totalGps": int(r.total_gp_count) if r.total_gp_count == r.total_gp_count and r.total_gp_count is not None else None,
                "value": new,
            }
        )
    return pd.DataFrame(rows, columns=cols)


def _filtered(rows: pd.DataFrame, circle: str | None, district: str | None, block: str | None, search: str | None, sort: str) -> pd.DataFrame:
    m = np.ones(len(rows), dtype=bool)
    if circle:
        m &= (rows["circleId"] == circle).to_numpy()
    if district:
        m &= (rows["districtId"] == district).to_numpy()
    if block:
        m &= (rows["blockId"] == block).to_numpy()
    if search and search.strip():
        q = search.strip().lower()
        m &= (rows["name"].str.lower().str.contains(q, regex=False) | rows["code"].astype(str).str.lower().str.contains(q, regex=False)).to_numpy()
    out = rows[m]
    if sort == "name":
        return out.sort_values(["name", "code"], kind="stable")
    return out.sort_values(["value", "name"], ascending=[sort == "value-asc", True], kind="stable", na_position="last")


INT_KEYS = ("amcGps", "reportedGps", "totalGps", "hotoGps", "existingGps", "newGps")
PCT_KEYS = ("availability", "hotoPct")


def _items(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for rec in df.drop(columns=["value"]).to_dict("records"):
        # pandas turns a missing date into NaN in mixed columns; JSON needs null (NaN is not valid JSON)
        rec = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
        for k in PCT_KEYS:
            if k in rec:
                rec[k] = r2(rec[k])
        for k in INT_KEYS:
            if k in rec:
                rec[k] = int(rec[k])
        out.append(rec)
    return out


def _as_of(store: Store, kind: str, week: str, as_of: dt.date | None) -> dt.date:
    """Date the list is counted up to. AMC plan lists: the same cutoffs as the AMC Conversion cards (month lists up to
    the latest plan data date, week lists up to the week's end); every other list: the week's end capped at the data date."""
    if kind in AMC_LISTS:
        from .amc_plan import windows

        win = windows(store, week, as_of)
        return win.as_of if AMC_LISTS[kind][0].startswith("week") else win.month_as_of
    return min(store.week(week).end, store.data_as_of)


def kpi_list(store: Store, kind: str, week: str, circle: str | None, district: str | None, block: str | None, search: str | None, sort: str | None, page: int, page_size: int, as_of: dt.date | None = None) -> dict[str, Any]:
    """as_of: AMC plan lists only – the date picked on the AMC Conversion summary (see amc_plan.windows)."""
    as_of = as_of if kind in AMC_LISTS else None
    spec = _spec(kind)
    rows = _rows(store, kind, week, as_of)
    sort = sort or DEFAULT_SORT[kind]
    df = _filtered(rows, circle, district, block, search, sort)
    total = len(df)
    pages = max(1, -(-total // page_size))
    page = min(page, pages)
    part = df.iloc[(page - 1) * page_size : page * page_size]
    wk = store.week(week)
    return {
        "kind": kind,
        "unit": spec.unit,
        "title": spec.title,
        "rule": spec.rule,
        "week": {"id": wk.code, "number": wk.number, "endDate": wk.end.isoformat()},
        "asOf": _as_of(store, kind, week, as_of).isoformat(),
        "cardTotal": len(rows),  # = the number on the KPI card
        # new-gp-blocks: rows are blocks, the table's "New" figure is the number of new GPs in them
        "cardValueTotal": int(rows["newGps"].sum()) if kind == "new-gp-blocks" else None,
        "valueTotal": int(df["newGps"].sum()) if kind == "new-gp-blocks" else None,
        "total": total,  # after state / district / block / search
        "page": page,
        "pageSize": page_size,
        "pages": pages,
        "sort": sort,
        "items": _items(part),
    }


def kpi_xlsx(store: Store, kind: str, week: str, circle: str | None, district: str | None, block: str | None, search: str | None, sort: str | None, as_of: dt.date | None = None) -> tuple[bytes, str]:
    """The whole (filtered) list as an .xlsx workbook. Text is always written as text (never as a formula)."""
    import xlsxwriter

    spec = _spec(kind)
    as_of = as_of if kind in AMC_LISTS else None
    rows = _rows(store, kind, week, as_of)
    df = _filtered(rows, circle, district, block, search, sort or DEFAULT_SORT[kind])
    wk = store.week(week)
    as_of = _as_of(store, kind, week, as_of)

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    ws = wb.add_worksheet(spec.title[:31].replace("/", "-").replace(":", " ").replace("<", "lt "))
    title = wb.add_format({"bold": True, "font_size": 14})
    note = wb.add_format({"italic": True, "font_color": "#555555"})
    head = wb.add_format({"bold": True, "bg_color": "#0E7490", "font_color": "#FFFFFF", "border": 1, "text_wrap": True, "valign": "vcenter"})
    fmt = {
        "text": wb.add_format({"border": 1}),
        "date": wb.add_format({"border": 1, "num_format": "dd mmm yyyy"}),
        "int": wb.add_format({"border": 1, "num_format": "#,##0"}),
        "pct": wb.add_format({"border": 1, "num_format": "0.00"}),
    }

    filters = ", ".join(f"{k}: {v}" for k, v in (("State", circle), ("District", district), ("Block", block), ("Search", search)) if v) or "none"
    noun = "GPs" if spec.unit == "gp" else "blocks"
    ws.write_string(0, 0, f"{spec.title} – {len(df):,} {noun}", title)
    ws.write_string(1, 0, f"Week {wk.number} (up to {wk.end:%d %b %Y}) · data as of {as_of:%d %b %Y} · source: {store.file_name}", note)
    ws.write_string(2, 0, f"Rule: {spec.rule}. Filters: {filters}.", note)
    hr = 4
    ws.set_column(0, 0, 6)
    ws.write_string(hr, 0, "#", head)
    for c, (_, label, width, _kind) in enumerate(spec.columns, start=1):
        ws.set_column(c, c, width)
        ws.write_string(hr, c, label, head)
    for r, rec in enumerate(df.to_dict("records"), start=hr + 1):
        ws.write_number(r, 0, r - hr, fmt["int"])
        for c, (key, _, _, ckind) in enumerate(spec.columns, start=1):
            v = rec[key]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                ws.write_blank(r, c, None, fmt["text"])
            elif ckind == "pct":
                ws.write_number(r, c, float(v), fmt["pct"])
            elif ckind == "int":
                ws.write_number(r, c, int(v), fmt["int"])
            elif ckind == "date":
                ws.write_datetime(r, c, dt.datetime.fromisoformat(str(v)), fmt["date"])
            else:
                ws.write_string(r, c, str(v), fmt["text"])
    ws.freeze_panes(hr + 1, 0)
    if len(df):
        ws.autofilter(hr, 0, hr + len(df), len(spec.columns))
    wb.close()
    name = f"Pratap_{kind}_W-{wk.number}_{as_of:%Y%m%d}.xlsx"
    return buf.getvalue(), name
