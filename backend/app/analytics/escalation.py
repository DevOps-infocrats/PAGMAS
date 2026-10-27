"""Field Team & Escalation – built from the active Escalation Matrix upload, joined to the master data by GP code.

Escalation chain per GP: FRT → Splicer → FE → AM → SHQ SPOC → COH → CBH (name + phone).
  Field team complete      FRT code, splicer (name + valid phone) and FE (name + valid phone) present
  Escalation complete      AM, SHQ SPOC, COH and CBH names present
  Valid phone              every number is 10 digits starting 6–9
  Down GP                  AMC GP whose month-to-date availability (selected week, same rule as everywhere) is 0%
Phone numbers are shown in full to admins only; everyone else sees them masked (98XXXXX144).
Location filters use the master data's circle / district / block ids, so they match the other pages.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Literal

import numpy as np
import pandas as pd
from sqlalchemy import select, text

from ..config import get_settings
from ..db import SessionLocal, engine
from ..models import EscalationImport
from .metrics import r2
from .store import Store, circle_code, slug

Role = Literal["frt", "splicer", "fe", "am"]
ROLE_FIELDS: dict[str, tuple[str, str | None, str]] = {  # role -> (name column, phone column, label)
    "frt": ("frt_code", None, "FRT team"),
    "splicer": ("splicer_name", "splicer_phone", "Splicer"),
    "fe": ("fe_name", "fe_phone", "Field Engineer (FE)"),
    "am": ("am_name", "am_phone", "Area Manager (AM)"),
}
CHAIN = (
    ("frt", "FRT", "frt_code", None),
    ("splicer", "Splicer", "splicer_name", "splicer_phone"),
    ("fe", "FE", "fe_name", "fe_phone"),
    ("am", "AM", "am_name", "am_phone"),
    ("shq", "SHQ SPOC", "shq_name", "shq_phone"),
    ("coh", "COH", "coh_name", "coh_phone"),
    ("cbh", "CBH", "cbh_name", "cbh_phone"),
)
PHONE_RE = re.compile(r"[6-9]\d{9}")
# A person is counted once: same state + same name ignoring case, spaces and punctuation ("OMPRAKASH" = "Om Prakash").
# The same name in two states is two people. "Vacant…" in the AM column is an open post, not a person.
KEY_COLS = {"am": "am_name", "fe": "fe_name", "splicer": "splicer_name", "frt": "frt_code"}


def person_key(name: Any) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    k = re.sub(r"[^a-z0-9]", "", name.lower())
    return k or None


def is_vacant(name: Any) -> bool:
    return isinstance(name, str) and name.strip().lower().startswith("vacant")


class NoEscalationData(Exception):
    pass


# ---------------------------------------------------------------- snapshot of the active import

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def invalidate_escalation() -> None:
    with _lock:
        _cache.clear()


def _active() -> tuple[dict[str, Any], pd.DataFrame] | None:
    with _lock:
        if "frame" in _cache:
            return _cache["meta"], _cache["frame"]
        with SessionLocal() as db:
            imp = db.scalars(select(EscalationImport).where(EscalationImport.is_active.is_(True)).order_by(EscalationImport.id.desc())).first()
            if imp is None:
                return None
            meta = {"id": imp.id, "fileName": imp.file_name, "importedAt": imp.finished_at.isoformat() if imp.finished_at else None}
        with engine.connect() as conn:
            df = pd.read_sql(text("SELECT * FROM escalation_contacts WHERE import_id = :i"), conn, params={"i": meta["id"]})
        df = df.drop(columns=["import_id"]).set_index("gp_code")
        df = df.astype(object).where(df.notna(), None)
        _cache.update(meta=meta, frame=df)
        return meta, df


def _valid_phone(v: Any) -> bool:
    if not isinstance(v, str) or not v:
        return False
    return all(PHONE_RE.fullmatch(p.strip()) for p in v.split("/") if p.strip())


def mask(v: Any, full: bool) -> str | None:
    """Phone number(s) – in full for admins, otherwise first 2 and last 3 digits (98XXXXX144)."""
    if not isinstance(v, str) or not v:
        return None
    if full:
        return v
    return " / ".join((p[:2] + "X" * max(0, len(p) - 5) + p[-3:]) if len(p) > 5 else "XXXXX" for p in (x.strip() for x in v.split("/")) if p)


def _frame(store: Store) -> tuple[dict[str, Any], pd.DataFrame]:
    """Escalation rows with the master data's location ids and names (GPs not in the master list keep their own)."""
    act = _active()
    if act is None:
        raise NoEscalationData("No Escalation Matrix has been uploaded yet – upload it on Data Operations.")
    meta, esc = act
    key = ("joined", meta["id"], store.dataset_id)
    with _lock:
        if _cache.get("joined_key") == key:
            return meta, _cache["joined"]
    g = store.gps.reindex(esc.index)
    df = esc.copy()
    df["in_master"] = g["circle"].notna().to_numpy()
    df["circle_id"] = np.where(df["in_master"], g["circle_id"], [slug(c) for c in df["circle"]])
    df["circle_name"] = [str(c).title() for c in df["circle"]]
    df["district_id"] = g["district_id"].to_numpy()
    df["block_id"] = g["block_id"].to_numpy()
    df["district_name"] = np.where(df["in_master"], g["district"].astype(str).str.title(), df["district"].fillna("").astype(str).str.title())
    df["block_label"] = np.where(df["in_master"], g["block_name"].astype(str).str.title(), df["block_name"].fillna("").astype(str).str.title())
    df["gp_label"] = np.where(df["in_master"], g["name"].astype(str).str.title(), df["gp_name"].fillna("").astype(str).str.title())
    df["master_am"] = g["am_name"].to_numpy()
    for role, _, name_col, phone_col in CHAIN:
        df[f"has_{role}"] = df[name_col].notna().to_numpy()
        if phone_col:
            df[f"phone_ok_{role}"] = df[phone_col].map(_valid_phone).to_numpy()
            df[f"phone_bad_{role}"] = (df[phone_col].notna() & ~df[f"phone_ok_{role}"]).to_numpy()
    for role, col in KEY_COLS.items():
        keys = df[col].map(person_key)
        df[f"key_{role}"] = [f"{c}|{k}" if isinstance(k, str) and k else None for c, k in zip(df["circle_id"], keys)]
    df["am_vacant"] = df["am_name"].map(is_vacant).to_numpy()
    df["field_complete"] = df["has_frt"] & df["has_splicer"] & df["phone_ok_splicer"] & df["has_fe"] & df["phone_ok_fe"]
    df["escalation_complete"] = df["has_am"] & df["has_shq"] & df["has_coh"] & df["has_cbh"]
    with _lock:
        _cache.update(joined_key=key, joined=df)
    return meta, df


def _mtd(store: Store, week: str) -> pd.Series:
    wf = store.week_frame(week)
    return wf["mtd"].where(wf["amc"])


def _filter(df: pd.DataFrame, circle: str | None, district: str | None, block: str | None, search: str | None) -> pd.DataFrame:
    m = np.ones(len(df), dtype=bool)
    if circle:
        m &= (df["circle_id"] == circle).to_numpy()
    if district:
        m &= (df["district_id"] == district).to_numpy()
    if block:
        m &= (df["block_id"] == block).to_numpy()
    if search and search.strip():
        q = search.strip().lower()
        hay = df["gp_label"].str.lower() + " " + df.index.astype(str).str.lower() + " " + df["block_label"].str.lower()
        for col in ("frt_code", "splicer_name", "fe_name", "am_name"):
            hay = hay + " " + df[col].fillna("").astype(str).str.lower()
        m &= hay.str.contains(q, regex=False).to_numpy()
    return df[m]


def _page(df: pd.DataFrame, page: int, page_size: int) -> tuple[pd.DataFrame, dict[str, int]]:
    total = len(df)
    pages = max(1, -(-total // page_size))
    page = min(max(1, page), pages)
    return df.iloc[(page - 1) * page_size : page * page_size], {"total": total, "page": page, "pageSize": page_size, "pages": pages}


def _chain(row: pd.Series, full: bool) -> list[dict[str, Any]]:
    out = []
    for role, label, name_col, phone_col in CHAIN:
        out.append(
            {
                "role": role,
                "label": label,
                "name": row[name_col],
                "phone": mask(row[phone_col], full) if phone_col else None,
                "phoneValid": bool(row[f"phone_ok_{role}"]) if phone_col else None,
            }
        )
    return out


def _gp(row: pd.Series, code: str) -> dict[str, Any]:
    return {
        "id": code,
        "name": row["gp_label"] or code,
        "code": code,
        "circleId": row["circle_id"],
        "circle": row["circle_name"],
        "districtId": row["district_id"],
        "district": row["district_name"],
        "blockId": row["block_id"],
        "block": row["block_label"],
    }


def _states(store: Store, df: pd.DataFrame) -> list[tuple[str, str]]:
    """(circle id, name) in the dashboard's order (by revised scope), then any circle only in the escalation file."""
    g = store.gps
    sizes = g[g["revised"]].groupby("circle").size().reindex(g["circle"].unique(), fill_value=0).sort_values(ascending=False)
    ids = [(slug(c), str(c).title()) for c in sizes.index]
    extra = [(cid, df.loc[df["circle_id"] == cid, "circle_name"].iloc[0]) for cid in df["circle_id"].unique() if cid not in {i for i, _ in ids}]
    return ids + extra


def _meta(meta: dict[str, Any], store: Store, week: str) -> dict[str, Any]:
    wk = store.week(week)
    return {"source": meta, "week": {"id": wk.code, "number": wk.number, "label": f"Week {wk.number}"}, "asOf": min(wk.end, store.data_as_of).isoformat()}


# ---------------------------------------------------------------- 1. summary


def summary(store: Store, week: str) -> dict[str, Any]:
    meta, df = _frame(store)
    mtd = _mtd(store, week).reindex(df.index)
    down = (mtd == 0).to_numpy()

    def block(sub: pd.DataFrame, d: np.ndarray) -> dict[str, Any]:
        n = len(sub)
        people = lambda role: int(sub[f"key_{role}"].dropna().nunique())  # noqa: E731
        bad = sum(int(sub[f"phone_bad_{r}"].sum()) for r, _, _, ph in CHAIN if ph)
        named_am = sub[~sub["am_vacant"]]
        return {
            "gps": n,
            "frtTeams": people("frt"),
            "splicers": people("splicer"),
            "fes": people("fe"),
            "ams": int(named_am["key_am"].dropna().nunique()),
            "amVacantPosts": int(sub.loc[sub["am_vacant"], "key_am"].dropna().nunique()),
            "amVacantGps": int(sub["am_vacant"].sum()),
            "shq": sorted(set(sub["shq_name"].dropna())),
            "coh": sorted(set(sub["coh_name"].dropna())),
            "cbh": sorted(set(sub["cbh_name"].dropna())),
            "fieldComplete": int(sub["field_complete"].sum()),
            "fieldCompletePct": r2(sub["field_complete"].mean() * 100) if n else None,
            "escalationComplete": int(sub["escalation_complete"].sum()),
            "escalationCompletePct": r2(sub["escalation_complete"].mean() * 100) if n else None,
            "missingFrt": int((~sub["has_frt"]).sum()),
            "missingSplicer": int((~sub["has_splicer"]).sum()),
            "missingFe": int((~sub["has_fe"]).sum()),
            "missingAm": int((~sub["has_am"]).sum()),
            "invalidPhones": bad,
            "gpsPerSplicer": r2(n / people("splicer")) if people("splicer") else None,
            "gpsPerFe": r2(n / people("fe")) if people("fe") else None,
            "downGps": int(d.sum()),
            "downWithoutSplicer": int((d & ~sub["has_splicer"].to_numpy()).sum()),
            "amDiffersFromMaster": int(((sub["master_am"].fillna("").astype(str).str.strip().str.lower() != sub["am_name"].fillna("").astype(str).str.strip().str.lower()) & sub["has_am"] & sub["in_master"]).sum()),
        }

    states = []
    for cid, name in _states(store, df):
        m = (df["circle_id"] == cid).to_numpy()
        if m.any():
            states.append({"id": cid, "code": circle_code(name), "name": name, **block(df[m], down[m])})
    return {**_meta(meta, store, week), "total": {"id": "all", "code": "ALL", "name": "Total", **block(df, down)}, "states": states, "notInMaster": int((~df["in_master"]).sum())}


# ---------------------------------------------------------------- 2. lookup


def lookup(store: Store, week: str, circle: str | None, district: str | None, block: str | None, search: str | None, page: int, page_size: int, full: bool) -> dict[str, Any]:
    meta, df = _frame(store)
    sub = _filter(df, circle, district, block, search).sort_values(["circle_name", "district_name", "block_label", "gp_label"], kind="stable")
    part, pg = _page(sub, page, page_size)
    items = [{**_gp(r, code), "chain": _chain(r, full), "fieldComplete": bool(r["field_complete"])} for code, r in part.iterrows()]
    return {**_meta(meta, store, week), **pg, "phonesMasked": not full, "items": items}


# ---------------------------------------------------------------- 3. workload


def workload(store: Store, week: str, role: Role, circle: str | None, full: bool) -> dict[str, Any]:
    meta, df = _frame(store)
    name_col, phone_col, label = ROLE_FIELDS[role]
    sub = _filter(df, circle, None, None, None)
    mtd = _mtd(store, week).reindex(sub.index)
    amc = mtd.notna() | store.week_frame(week)["amc"].reindex(sub.index).fillna(False).astype(bool)
    has = sub[name_col].notna()
    work = pd.DataFrame(
        {
            "circle_id": sub["circle_id"],
            "circle": sub["circle_name"],
            "person": sub[name_col].fillna("").astype(str),
            "key": sub[f"key_{role}"],
            "block": sub["block_id"].fillna(sub["block_label"]),
            "phone": sub[phone_col] if phone_col else None,
            "amc": amc.to_numpy(),
            "mtd": mtd.to_numpy(),
        }
    )[has.to_numpy()]
    rows = []
    for (cid, key), grp in work.groupby(["circle_id", "key"], sort=False, dropna=True):
        vals = grp["mtd"].dropna()
        phones = sorted({p for p in grp["phone"].dropna()}) if phone_col else []
        rows.append(
            {
                "id": key,
                "circleId": cid,
                "circle": grp["circle"].iloc[0],
                "name": grp["person"].mode().iloc[0],
                "phone": " · ".join(mask(p, full) for p in phones) if phones else None,
                "numbers": len(phones),
                "gps": int(len(grp)),
                "blocks": int(grp["block"].nunique()),
                "amcGps": int(grp["amc"].sum()),
                "availability": r2(vals.mean()) if len(vals) else None,
                "gpsAtZero": int((vals == 0).sum()),
                "gpsBelow90": int((vals < get_settings().penalty_threshold).sum()),
            }
        )
    rows.sort(key=lambda x: (-x["gps"], x["name"]))
    loads = [x["gps"] for x in rows]
    return {
        **_meta(meta, store, week),
        "role": role,
        "roleLabel": label,
        "people": len(rows),
        "unassignedGps": int((~has).sum()),
        "avgGps": r2(float(np.mean(loads))) if loads else None,
        "maxGps": max(loads) if loads else None,
        "phonesMasked": not full,
        "items": rows,
    }


# ---------------------------------------------------------------- 4. down GPs – who to call


def down(store: Store, week: str, mode: Literal["zero", "below90"], circle: str | None, district: str | None, block: str | None, search: str | None, page: int, page_size: int, full: bool) -> dict[str, Any]:
    meta, df = _frame(store)
    mtd = _mtd(store, week).reindex(df.index)
    sel = (mtd == 0) if mode == "zero" else (mtd < get_settings().penalty_threshold)
    sub = _filter(df[sel.to_numpy()], circle, district, block, search)
    vals = mtd.reindex(sub.index)
    sub = sub.assign(_mtd=vals).sort_values(["_mtd", "circle_name", "block_label", "gp_label"], kind="stable")
    part, pg = _page(sub, page, page_size)
    items = [{**_gp(r, code), "availability": r2(r["_mtd"]), "chain": _chain(r, full), "noSplicer": not bool(r["has_splicer"])} for code, r in part.iterrows()]
    return {**_meta(meta, store, week), **pg, "mode": mode, "withoutSplicer": int((~sub["has_splicer"]).sum()), "phonesMasked": not full, "items": items}


# ---------------------------------------------------------------- 5. data gaps

GAP_ISSUES: dict[str, str] = {
    "missing-frt": "No FRT code",
    "missing-splicer": "No splicer",
    "missing-splicer-phone": "Splicer phone missing",
    "invalid-splicer-phone": "Splicer phone not a valid 10-digit number",
    "missing-fe-phone": "FE phone missing",
    "invalid-fe-phone": "FE phone not a valid 10-digit number",
    "missing-am": "No area manager",
    "missing-am-phone": "AM phone missing",
    "missing-coh": "No COH",
    "missing-cbh": "No CBH",
    "am-differs": "AM name differs from the master data",
}


def _gap_masks(df: pd.DataFrame) -> dict[str, np.ndarray]:
    def miss_phone(role: str, phone_col: str) -> np.ndarray:
        return (df[f"has_{role}"] & df[phone_col].isna()).to_numpy()

    am_m = df["master_am"].fillna("").astype(str).str.strip().str.lower()
    am_e = df["am_name"].fillna("").astype(str).str.strip().str.lower()
    return {
        "missing-frt": (~df["has_frt"]).to_numpy(),
        "missing-splicer": (~df["has_splicer"]).to_numpy(),
        "missing-splicer-phone": miss_phone("splicer", "splicer_phone"),
        "invalid-splicer-phone": df["phone_bad_splicer"].to_numpy(),
        "missing-fe-phone": miss_phone("fe", "fe_phone"),
        "invalid-fe-phone": df["phone_bad_fe"].to_numpy(),
        "missing-am": (~df["has_am"]).to_numpy(),
        "missing-am-phone": miss_phone("am", "am_phone"),
        "missing-coh": (~df["has_coh"]).to_numpy(),
        "missing-cbh": (~df["has_cbh"]).to_numpy(),
        "am-differs": ((am_m != am_e) & df["has_am"] & df["in_master"]).to_numpy(),
    }


def gaps(store: Store, week: str, issue: str | None, circle: str | None, district: str | None, block: str | None, search: str | None, page: int, page_size: int, full: bool) -> dict[str, Any]:
    meta, df = _frame(store)
    masks = _gap_masks(df)
    states = _states(store, df)
    table = []
    for key, label in GAP_ISSUES.items():
        counts = {cid: int((masks[key] & (df["circle_id"] == cid).to_numpy()).sum()) for cid, _ in states}
        table.append({"id": key, "label": label, "counts": counts, "total": int(masks[key].sum())})
    out: dict[str, Any] = {**_meta(meta, store, week), "states": [{"id": cid, "name": name} for cid, name in states], "issues": table, "issue": issue}
    if issue in masks:
        sub = _filter(df[masks[issue]], circle, district, block, search).sort_values(["circle_name", "block_label", "gp_label"], kind="stable")
        part, pg = _page(sub, page, page_size)
        out.update(pg)
        out["items"] = [{**_gp(r, code), "chain": _chain(r, full), "masterAm": r["master_am"]} for code, r in part.iterrows()]
        out["phonesMasked"] = not full
    return out


# ---------------------------------------------------------------- 6. team directory (KPI card drill-down)


def _names(values: pd.Series) -> list[str]:
    """Distinct names (one spelling per person: the most frequent one), sorted."""
    v = values.dropna().astype(str)
    if v.empty:
        return []
    keys = v.map(person_key)
    best = v.groupby(keys).agg(lambda x: x.value_counts().index[0])
    return sorted(best.tolist(), key=str.lower)


def people(store: Store, week: str, role: Role, circle: str | None, search: str | None, full: bool) -> dict[str, Any]:
    """One row per person / FRT team of a role: the districts and blocks they cover, the teams and people under / above
    them, GP counts and the month-to-date availability of their AMC GPs. Counted with the KPI cards' identity rule."""
    meta, df = _frame(store)
    name_col, phone_col, label = ROLE_FIELDS[role]
    sub = _filter(df, circle, None, None, None)
    sub = sub[sub[f"key_{role}"].notna()]
    wf = store.week_frame(week)
    mtd = wf["mtd"].where(wf["amc"]).reindex(sub.index)
    amc = wf["amc"].reindex(sub.index).fillna(False).astype(bool)
    shared: dict[str, int] = {}
    if phone_col:  # a number used under several names (possible data error)
        ph = df[df[phone_col].notna() & df[f"key_{role}"].notna()]
        shared = ph.groupby(phone_col)[f"key_{role}"].nunique().to_dict()
    rows = []
    for key, grp in sub.groupby(f"key_{role}", sort=False):
        spellings = sorted(set(grp[name_col].dropna().astype(str)))
        name = grp[name_col].dropna().astype(str).value_counts().index[0]
        districts = []
        for dname, dg in grp.groupby("district_name", sort=True):
            districts.append({"name": dname or "—", "blocks": sorted(set(dg["block_label"].dropna()), key=str.lower)})
        vals = mtd.reindex(grp.index).dropna()
        phones = sorted({p for p in grp[phone_col].dropna()}) if phone_col else []
        row = {
            "id": key,
            "circleId": grp["circle_id"].iloc[0],
            "circle": grp["circle_name"].iloc[0],
            "name": name,
            "spellings": spellings if len(spellings) > 1 else [],
            "vacant": role == "am" and is_vacant(name),
            "phone": " · ".join(mask(p, full) for p in phones) if phones else None,
            "phoneShared": any(shared.get(p, 0) > 1 for p in phones),
            "districts": districts,
            "districtCount": len(districts),
            "blockCount": int(grp["block_id"].fillna(grp["block_label"]).nunique()),
            "gps": int(len(grp)),
            "amcGps": int(amc.reindex(grp.index).sum()),
            "availability": r2(vals.mean()) if len(vals) else None,
            "gpsAtZero": int((vals == 0).sum()),
        }
        if role != "frt":
            row["frtTeams"] = _names(grp["frt_code"])
        if role in ("am", "frt"):
            row["fes"] = _names(grp["fe_name"])
        if role in ("am", "fe", "frt"):
            row["splicers"] = _names(grp["splicer_name"])
        if role in ("fe", "splicer", "frt"):
            row["ams"] = _names(grp["am_name"])
        if role == "splicer":
            row["fes"] = _names(grp["fe_name"])
        rows.append(row)
    if search and search.strip():
        q = search.strip().lower()
        rows = [r for r in rows if q in r["name"].lower() or any(q in d["name"].lower() or any(q in b.lower() for b in d["blocks"]) for d in r["districts"])]
    rows.sort(key=lambda r: (r["vacant"], r["circle"], -r["gps"], r["name"].lower()))
    named = [r for r in rows if not r["vacant"]]
    return {
        **_meta(meta, store, week),
        "role": role,
        "roleLabel": label,
        "count": len(named),
        "vacantPosts": len(rows) - len(named),
        "byState": {cid: sum(1 for r in named if r["circleId"] == cid) for cid in dict.fromkeys(r["circleId"] for r in rows)},
        "gpsWithout": int(_filter(df, circle, None, None, None)[f"key_{role}"].isna().sum()),
        "phonesMasked": not full,
        "items": rows,
    }
