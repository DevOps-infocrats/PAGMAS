"""Who receives a schedule's e-mail, and which GPs each person's report covers.

Audiences
  am     Area Managers of the Escalation Matrix – each one gets only the GPs assigned to them (block-wise report)
  sme    SME / SHQ SPOC per circle  – the GPs of their circle(s) in the matrix (area-manager-wise report)
  coh    COH per circle             – same, from the COH column
  (CBH is not an audience: CBH names and e-mails are stored from the matrix as a backup only and never mailed.)
  users  Dashboard users (User Management) – admins: every GP; viewers: only their assigned circles / districts /
         blocks; a viewer without a valid area gets nothing (access is never widened)

A person of the matrix is one name within one circle, ignoring case / spaces / punctuation (same rule as Field Team &
Escalation). "Vacant…" / "Vacent-1" entries are open posts and receive nothing. The e-mail is read from the same rows.

Filters of a schedule (each empty = no restriction; together = AND): states, business areas, blocks, and – for the
matrix audiences – a list of chosen people. Every recipient's GP set is (their own GPs) ∩ (filters); a recipient with
no GP left is skipped. One address receives one e-mail: if the same address appears in several roles, the GP sets
are merged (union) and the roles listed together.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics.store import Store
from ..models import MailConfig, User, UserScope
from .smtp import valid_address

MATRIX_ROLES: dict[str, tuple[str, str, str]] = {  # audience -> (name column, e-mail column, label)
    "am": ("am_name", "am_email", "Area Manager"),
    "sme": ("shq_name", "shq_email", "SME"),
    "coh": ("coh_name", "coh_email", "COH"),
}
AUDIENCES = (*MATRIX_ROLES, "users")
AUDIENCE_LABELS = {**{k: v[2] for k, v in MATRIX_ROLES.items()}, "users": "Dashboard user"}
LEVELS = ("circle", "district", "block")


# ---------------------------------------------------------------- helpers


def is_open_post(name: object) -> bool:
    """An unfilled post, not a person: "Vacant…" and the matrix's own spelling "Vacent-1", "Vacancy" …"""
    return isinstance(name, str) and name.strip().lower().startswith(("vacant", "vacent", "vacancy"))


def _json_list(text: str | None) -> list:
    try:
        v = json.loads(text or "[]")
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def _title(v: object) -> str | None:
    if not isinstance(v, str) or not v.strip() or v.strip() == "0":
        return None
    return " ".join(v.split()).title()


def matrix_frame(store: Store) -> pd.DataFrame | None:
    """Active Escalation Matrix rows of the GPs in the active master data, with the master's location ids."""
    from ..analytics.escalation import _active

    act = _active()
    if act is None:
        return None
    _, esc = act
    esc = esc[esc.index.isin(store.gps.index)]
    g = store.gps.loc[esc.index]
    out = esc.copy()
    out["circle_id"] = g["circle_id"].to_numpy()
    out["circle_name"] = g["circle"].astype(str).str.title().to_numpy()
    out["block_id"] = g["block_id"].to_numpy()
    return out


def gp_business_area(store: Store, matrix: pd.DataFrame | None) -> pd.Series:
    """Business area of every GP: the matrix's BA column, else the master data's BA (title case)."""
    g = store.gps
    master = g["ba"].map(_title) if "ba" in g.columns else pd.Series(None, index=g.index, dtype=object)
    if matrix is None or "ba" not in matrix.columns:
        return master
    esc = matrix["ba"].map(_title).reindex(g.index)
    return esc.where(esc.notna(), master)


def filter_options(store: Store) -> dict:
    """States, business areas and blocks of the active data, for the schedule filters."""
    m = matrix_frame(store)
    ba = gp_business_area(store, m)
    g = store.gps.assign(_ba=ba)
    circles = [{"id": cid, "name": str(n).title()} for cid, n in g.groupby("circle_id")["circle"].first().sort_index().items()]
    bas = [{"name": b, "circleId": c} for (c, b), _ in g.dropna(subset=["_ba"]).groupby(["circle_id", "_ba"])]
    blocks = g.groupby("block_id")[["circle_id", "circle", "block_name", "block_code"]].first().sort_values(["circle", "block_name"])
    return {
        "circles": circles,
        "businessAreas": sorted(bas, key=lambda x: (x["circleId"], x["name"])),
        "blocks": [{"id": bid, "circleId": r.circle_id, "name": f"{str(r.block_name).title()} – {r.block_code}"} for bid, r in blocks.iterrows()],
    }


def filter_mask(store: Store, cfg_circles: list[str], cfg_bas: list[str], cfg_blocks: list[str], matrix: pd.DataFrame | None) -> pd.Series:
    """GPs passing the schedule's state / business area / block filters (each empty = all)."""
    g = store.gps
    m = pd.Series(True, index=g.index)
    if cfg_circles:
        m &= g["circle_id"].isin(set(cfg_circles))
    if cfg_bas:
        wanted = {b.strip().lower() for b in cfg_bas}
        m &= gp_business_area(store, matrix).fillna("").str.lower().isin(wanted)
    if cfg_blocks:
        m &= g["block_id"].isin(set(cfg_blocks))
    return m


# ---------------------------------------------------------------- matrix people


@dataclass
class Person:
    id: str  # "am:haryana:hemant"
    role: str
    name: str
    circle_id: str
    circle: str
    emails: list[str]
    gps: pd.Index
    business_areas: list[str]


def matrix_people(store: Store, roles: tuple[str, ...] = tuple(MATRIX_ROLES), matrix: pd.DataFrame | None = None) -> list[Person]:
    from ..analytics.escalation import person_key

    m = matrix if matrix is not None else matrix_frame(store)
    if m is None or m.empty:
        return []
    ba = gp_business_area(store, m)
    out: list[Person] = []
    for role in roles:
        name_col, email_col, _ = MATRIX_ROLES[role]
        if name_col not in m.columns:
            continue
        rows = m[m[name_col].notna() & ~m[name_col].map(is_open_post)]
        keys = rows[name_col].map(person_key)
        rows = rows[keys.notna()]
        for (cid, key), part in rows.groupby([rows["circle_id"], keys[keys.notna()]]):
            names = Counter(" ".join(str(n).split()) for n in part[name_col])
            emails = Counter()
            if email_col in part.columns:
                for v in part[email_col].dropna():
                    for e in str(v).split(" / "):
                        if a := valid_address(e):
                            emails[a] += 1
            out.append(
                Person(
                    id=f"{role}:{cid}:{key}",
                    role=role,
                    name=names.most_common(1)[0][0],
                    circle_id=cid,
                    circle=str(part["circle_name"].iloc[0]),
                    emails=[e for e, _ in emails.most_common()],
                    gps=part.index,
                    business_areas=sorted({b for b in ba.reindex(part.index).dropna()}),
                )
            )
    out.sort(key=lambda p: (list(MATRIX_ROLES).index(p.role), p.circle, p.name.lower()))
    return out


# ---------------------------------------------------------------- dashboard users (User Management RBAC)


@dataclass(frozen=True)
class Assignment:
    level: str
    id: str


def locations(store: Store) -> dict[str, dict[str, str]]:
    """level -> {id: label} for every circle, district and block of the active data."""
    g = store.gps
    circles = {cid: str(name).title() for cid, name in g.groupby("circle_id")["circle"].first().items()}
    d = g.groupby("district_id")[["circle", "district"]].first()
    districts = {did: f"{str(r.district).title()} ({str(r.circle).title()})" for did, r in d.iterrows()}
    b = g.groupby("block_id")[["circle", "block_name", "block_code"]].first()
    blocks = {bid: f"{str(r.block_name).title()} – {r.block_code} ({str(r.circle).title()})" for bid, r in b.iterrows()}
    return {"circle": circles, "district": districts, "block": blocks}


def location_tree(store: Store) -> list[dict]:
    """Circles with their districts and blocks, for the User Management area picker."""
    g = store.gps
    out = []
    for cid, cg in g.groupby("circle_id", sort=True):
        districts = []
        for did, dg in cg.groupby("district_id", sort=True):
            blocks = dg.groupby("block_id")[["block_name", "block_code"]].first().sort_values("block_name")
            districts.append({"id": did, "name": str(dg["district"].iloc[0]).title(), "blocks": [{"id": bid, "name": f"{str(r.block_name).title()} – {r.block_code}"} for bid, r in blocks.iterrows()]})
        districts.sort(key=lambda x: x["name"])
        out.append({"id": cid, "name": str(cg["circle"].iloc[0]).title(), "districts": districts})
    return out


def check_assignments(store: Store | None, items: list[Assignment]) -> list[str]:
    problems = []
    locs = locations(store) if store is not None else None
    for a in items:
        if a.level not in LEVELS:
            problems.append(f"Unknown level {a.level!r}")
        elif locs is not None and a.id not in locs[a.level]:
            problems.append(f"Unknown {a.level} {a.id!r}")
    return problems


def assignments_of(db: Session, user_ids: list[int] | None = None) -> dict[int, list[Assignment]]:
    q = select(UserScope).order_by(UserScope.id)
    if user_ids is not None:
        q = q.where(UserScope.user_id.in_(user_ids))
    out: dict[int, list[Assignment]] = defaultdict(list)
    for r in db.scalars(q):
        out[r.user_id].append(Assignment(r.level, r.scope_id))
    return out


def user_gps(store: Store, role: str, items: list[Assignment], locs: dict[str, dict[str, str]] | None = None) -> tuple[pd.Index, list[str]]:
    """GPs a dashboard user may receive and readable labels. admin: all; viewer: union of valid areas; else none."""
    g = store.gps
    if role == "admin":
        return g.index, ["All circles"]
    if role != "viewer":
        return g.index[:0], []
    locs = locs or locations(store)
    sets: dict[str, set[str]] = {"circle": set(), "district": set(), "block": set()}
    labels = []
    for a in items:
        label = locs.get(a.level, {}).get(a.id)
        if label is None:  # not in the active data -> ignored, never widened
            continue
        sets[a.level].add(a.id)
        labels.append(f"{a.level.title()}: {label}")
    m = g["circle_id"].isin(sets["circle"]) | g["district_id"].isin(sets["district"]) | g["block_id"].isin(sets["block"])
    return g.index[m.to_numpy()], labels


# ---------------------------------------------------------------- recipients of a schedule


@dataclass
class Recipient:
    email: str  # primary address (dedupe key)
    emails: list[str]
    name: str
    roles: list[str]
    person_ids: list[str]
    gps: pd.Index
    areas: list[str] = field(default_factory=list)

    @property
    def breakdown(self) -> str:
        """Area Managers see their blocks; everyone above them sees the area managers."""
        return "block" if set(self.roles) == {"am"} else "am"

    @property
    def role_label(self) -> str:
        return ", ".join(AUDIENCE_LABELS[r] for r in self.roles)


@dataclass
class Skipped:
    name: str
    role: str
    reason: str


def recipients(db: Session, store: Store, cfg: MailConfig) -> tuple[list[Recipient], list[Skipped]]:
    audiences = [a for a in _json_list(cfg.audiences) if a in AUDIENCES]
    matrix = matrix_frame(store)
    fmask = filter_mask(store, _json_list(cfg.filter_circles), _json_list(cfg.filter_bas), _json_list(cfg.filter_blocks), matrix)
    allowed = store.gps.index[fmask.to_numpy()]
    chosen = set(_json_list(cfg.filter_people))
    by_email: dict[str, Recipient] = {}
    skipped: list[Skipped] = []

    def add(email: str, emails: list[str], name: str, role: str, pid: str, gps: pd.Index, area: str) -> None:
        r = by_email.get(email)
        if r is None:
            by_email[email] = Recipient(email, emails, name, [role], [pid], gps, [area])
            return
        r.gps = r.gps.union(gps)
        if role not in r.roles:
            r.roles.append(role)
        r.person_ids.append(pid)
        if area not in r.areas:
            r.areas.append(area)
        r.emails = list(dict.fromkeys(r.emails + emails))

    matrix_roles = tuple(a for a in audiences if a in MATRIX_ROLES)
    if matrix_roles:
        if matrix is None:
            skipped.append(Skipped("Escalation Matrix", ", ".join(matrix_roles), "no Escalation Matrix uploaded"))
        else:  # open posts are listed so the preview explains why nobody gets those GPs' e-mail
            for role in matrix_roles:
                name_col = MATRIX_ROLES[role][0]
                if name_col in matrix.columns and not chosen:
                    posts = matrix[matrix[name_col].map(is_open_post) & matrix.index.isin(allowed)]
                    for (circle, post), _ in posts.groupby(["circle_name", posts[name_col].map(lambda v: " ".join(str(v).split()))]):
                        skipped.append(Skipped(f"{post} ({circle})", AUDIENCE_LABELS[role], "vacant post – no person to send to"))
        for p in matrix_people(store, matrix_roles, matrix):
            if chosen and p.id not in chosen:
                continue
            label = AUDIENCE_LABELS[p.role]
            if not p.emails:
                skipped.append(Skipped(p.name, label, "no e-mail in the Escalation Matrix"))
                continue
            gps = p.gps.intersection(allowed)
            if gps.empty:
                skipped.append(Skipped(p.name, label, "no GP within the selected filters"))
                continue
            area = f"{p.circle}" + (f" – BA {', '.join(p.business_areas)}" if p.role == "am" and p.business_areas else "")
            add(p.emails[0], p.emails, p.name, p.role, p.id, gps, area)

    if "users" in audiences:
        ids = [int(i) for i in _json_list(cfg.user_ids) if isinstance(i, int)]
        q = select(User).where(User.is_active.is_(True)).order_by(User.id)
        if ids:
            q = q.where(User.id.in_(ids))
        users = list(db.scalars(q))
        scopes = assignments_of(db, [u.id for u in users])
        locs = locations(store)
        for u in users:
            addr = valid_address(u.email)
            if not addr:
                skipped.append(Skipped(u.name, "Dashboard user", "no valid e-mail address"))
                continue
            gps, labels = user_gps(store, u.role, scopes.get(u.id, []), locs)
            if gps.empty:
                skipped.append(Skipped(u.name, "Dashboard user", "no circle / district / block assigned"))
                continue
            gps = gps.intersection(allowed)
            if gps.empty:
                skipped.append(Skipped(u.name, "Dashboard user", "no GP within the selected filters"))
                continue
            add(addr, [addr], u.name, "users", f"user:{u.id}", gps, "; ".join(labels))

    out = sorted(by_email.values(), key=lambda r: (min(AUDIENCES.index(x) for x in r.roles), r.name.lower()))
    return out, skipped
