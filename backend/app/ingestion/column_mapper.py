"""Column mapper for admins (Data Operations): see which sheet / column names of an uploaded workbook the importer
does not recognise, and add the file's own names to data/column_map.json – without opening the code or the file.

  check(path)      reads only the first rows of the workbook and reports, per sheet the importer uses, every field:
                   found (under which header) or missing, with the most similar unused header as a suggestion, the
                   file's unused headers with sample values, and a warning when the chosen column's values do not
                   look like the field (a date field whose values are not dates …). Nothing is changed.
  add_names(...)   adds names chosen by the admin. Never guesses: only what the admin picked is added. Refused when a
                   name already belongs to another field of the same sheet (one column can never feed two fields) or
                   when column_map.json is broken (it is never overwritten blindly). The previous file is kept as
                   column_map.json.bak; the write is atomic.
  remove_name(...) removes a name an admin added (built-in names cannot be removed – they always work).

Weekly / daily / monthly availability columns are recognised by their pattern (W-41, dates), not by name, so they
are not part of the mapper.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import column_map as cm
from .workbook import WorkbookError, as_date, is_blank, norm, open_workbook, read_sheet

SAMPLE_ROWS = 15 + 200  # header search window + rows used for sample values / type checks
MAX_SHEETS = 40
MAX_NAME = 120
_write_lock = threading.Lock()
_WEEK_RE = re.compile(r"^w-?\d{1,2}$")
_AMC_MONTH_RE = re.compile(r"^[a-z]+'\d{2} \(amc\)$")


@dataclass(frozen=True)
class Section:
    key: str  # API key
    file_key: str  # section of column_map.json
    cmap_attr: str  # attribute of ColumnMap
    sheet_key: str | None  # logical sheet (master data); None = any sheet (Escalation Matrix)
    label: str
    defaults: dict[str, tuple[str, ...]]
    required: tuple[str, ...]
    anchors: tuple[str, ...]


SECTIONS: dict[str, Section] = {
    "gp": Section("gp", "gpColumns", "gp", "gp", "GP Wise Data", cm.GP_COLUMNS, cm.GP_REQUIRED, cm.GP_HEADER_ANCHORS),
    "masterBlock": Section("masterBlock", "masterBlockColumns", "master_block", "masterBlock", "Master Block", cm.MASTER_BLOCK_COLUMNS, cm.MASTER_BLOCK_REQUIRED, cm.MASTER_BLOCK_HEADER_ANCHORS),
    "escalation": Section("escalation", "escalationColumns", "escalation", None, "Escalation Matrix", cm.ESCALATION_COLUMNS, cm.ESCALATION_REQUIRED, cm.ESCALATION_HEADER_ANCHORS),
}
SHEET_LABELS = {"gp": "GP Wise Data (required)", "masterBlock": "Master Block (optional)", "om": "O&M (optional)"}

DATE_FIELDS = {"hoto_date", "amc_date", "lms_amc_date", "letter_date", "planned_date", "ach_date", "plan_letter_date"}
NUMBER_FIELDS = {"bbnl_km", "bsnl_km", "total_rkm", "total_gp_count", "existing_gps", "new_gps"}
PHONE_FIELDS = {"splicer_phone", "fe_phone", "am_phone", "shq_phone", "coh_phone", "cbh_phone"}
EMAIL_FIELDS = {"fe_email", "am_email", "shq_email", "coh_email", "cbh_email"}


class MapperError(ValueError):
    """A change the admin asked for that cannot be made (message is shown as is)."""


# ---------------------------------------------------------------- value checks


def _value_kind(field: str) -> str | None:
    if field in DATE_FIELDS:
        return "date"
    if field in NUMBER_FIELDS:
        return "number"
    if field in PHONE_FIELDS:
        return "phone"
    if field in EMAIL_FIELDS:
        return "email"
    return None


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v == v
    try:
        float(str(v).replace(",", "").strip())
        return True
    except ValueError:
        return False


def _matches(kind: str, v: Any) -> bool:
    if kind == "date":
        return as_date(v) is not None
    if kind == "number":
        return _is_number(v)
    if kind == "phone":
        return len(re.sub(r"\D", "", str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))) >= 10
    if kind == "email":
        return "@" in str(v)
    return True


def _show(v: Any) -> str:
    """A cell as the admin would see it in the file (real date cells as YYYY-MM-DD; text as written)."""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:40] + ("…" if len(s) > 40 else "")


def _column_values(grid: list[list[Any]], hdr: int, col: int) -> list[Any]:
    return [r[col] for r in grid[hdr + 1 :] if col < len(r) and not is_blank(r[col])]


def _fit(field: str, values: list[Any]) -> dict[str, Any] | None:
    """Share of the values that look like the field (None when the field has no expected kind or no values)."""
    kind = _value_kind(field)
    if kind is None or not values:
        return None
    ok = sum(_matches(kind, v) for v in values)
    pct = round(100 * ok / len(values))
    return {"kind": kind, "pct": pct, "warning": pct < 50}


# ---------------------------------------------------------------- reading the workbook


def _header_row(grid: list[list[Any]], s: Section, names: dict[str, tuple[str, ...]]) -> tuple[int | None, bool]:
    """(row, exact): the importer's own rule (all anchor fields present); else the row with most known names (>= 3)
    so a renamed anchor column can still be mapped."""
    hdr = cm.find_header_row(grid, names, s.anchors)
    if hdr is not None:
        return hdr, True
    known = {n for ns in names.values() for n in ns}
    best, best_score = None, 2
    for i, row in enumerate(grid[:15]):
        score = len({norm(c) for c in row} & known)
        if score > best_score:
            best, best_score = i, score
    return best, False


def _section_score(grid: list[list[Any]], s: Section, names: dict[str, tuple[str, ...]]) -> int:
    known = {n for ns in names.values() for n in ns}
    return max((len({norm(c) for c in row} & known) for row in grid[:15]), default=0)


def _is_period(h: Any) -> bool:
    n = norm(h)
    return as_date(h) is not None or bool(_WEEK_RE.match(n) or _AMC_MONTH_RE.match(n))


def _labels(s: Section, cmap: cm.ColumnMap) -> dict[str, list[str]]:
    """Accepted names per field as people write them: the file's names (original spelling) and the built-in ones."""
    custom = _custom_names().get(s.file_key, {})
    out: dict[str, list[str]] = {}
    for f, built in s.defaults.items():
        names: dict[str, str] = {}
        for n in [*custom.get(f, []), *built]:
            names.setdefault(norm(n), n)
        out[f] = [names[n] for n in getattr(cmap, s.cmap_attr)[f] if n in names]
    return out


def _check_section(s: Section, sheet: str | None, sheet_resolved: bool, sheet_hint: str | None, grids: dict[str, list[list[Any]]], cmap: cm.ColumnMap) -> dict[str, Any]:
    names = getattr(cmap, s.cmap_attr)
    out: dict[str, Any] = {"key": s.key, "label": s.label, "sheet": sheet, "sheetResolved": sheet_resolved, "sheetSuggestion": sheet_hint, "headerFound": False, "fields": [], "columns": []}
    if sheet is None:
        return out
    grid = grids[sheet]
    hdr, exact = _header_row(grid, s, names)
    if hdr is None:
        return out
    header = grid[hdr]
    loc = cm.locate(header, names)
    taken = set(loc.columns.values())
    labels = _labels(s, cmap)
    out.update(headerFound=True, headerRow=hdr + 1, headerExact=exact)
    for c, h in enumerate(header):
        if is_blank(h) or c in taken or (s.key == "gp" and _is_period(h)):
            continue
        vals = _column_values(grid, hdr, c)
        out["columns"].append({"header": _show(h) if not isinstance(h, str) else re.sub(r"\s+", " ", h).strip(), "samples": [_show(v) for v in vals[:5]], "fit": {f: _fit(f, vals) for f in s.defaults if _value_kind(f)}})
    for f in s.defaults:
        col = loc.columns.get(f)
        field: dict[str, Any] = {"field": f, "label": s.defaults[f][0], "required": f in s.required, "kind": _value_kind(f), "acceptedNames": labels[f]}
        if col is not None:
            vals = _column_values(grid, hdr, col)
            field.update(status="found", header=str(header[col]).strip(), samples=[_show(v) for v in vals[:3]], fit=_fit(f, vals))
            if f in loc.duplicates:
                field["duplicates"] = loc.duplicates[f]
        else:
            hint = cm.suggest(header, names[f], taken)
            m = re.match(r'^"(.*)" \((\d+)% similar\)$', hint or "")
            field.update(status="missing", suggestion=m.group(1) if m else None, similarity=int(m.group(2)) if m else None)
        out["fields"].append(field)
    return out


def check(path: Path) -> dict[str, Any]:
    """What the importer would recognise in this workbook, and what it would not (reads only the first rows)."""
    cmap = cm.load_column_map()
    try:
        wb = open_workbook(path)
        sheets = list(wb.sheet_names)
        grids = {n: read_sheet(wb, n, nrows=SAMPLE_ROWS) for n in sheets[:MAX_SHEETS]}
    except WorkbookError:
        raise
    except Exception as exc:  # corrupt workbook content
        raise WorkbookError(f"Workbook could not be read: {exc}") from exc
    readable = list(grids)

    gp_sheet = cm.resolve_sheet(sheets, "gp", cmap)
    gp_scores = {n: _section_score(g, SECTIONS["gp"], cmap.gp) for n, g in grids.items()}
    esc_scores = {n: _section_score(g, SECTIONS["escalation"], cmap.escalation) for n, g in grids.items()}
    best_gp = max(gp_scores, key=gp_scores.get) if gp_scores else None
    best_esc = max(esc_scores, key=esc_scores.get) if esc_scores else None
    if gp_sheet is not None:
        kind = "master"
    elif best_esc and esc_scores[best_esc] >= 3 and esc_scores[best_esc] > gp_scores.get(best_esc, 0) and any(norm(h) in {n for n in cmap.escalation["frt_code"]} | {n for n in cmap.escalation["fe_name"]} for row in grids[best_esc][:15] for h in row):
        kind = "escalation"
    elif best_gp and gp_scores[best_gp] >= 3:
        kind = "master"
    elif best_esc and esc_scores[best_esc] >= 3:
        kind = "escalation"
    else:
        kind = None

    sections: list[dict[str, Any]] = []
    sheet_map: list[dict[str, Any]] = []
    if kind == "master":
        gp_hint = None if gp_sheet else best_gp
        sections.append(_check_section(SECTIONS["gp"], gp_sheet or gp_hint, gp_sheet is not None, gp_hint, grids, cmap))
        mb_sheet = cm.resolve_sheet(sheets, "masterBlock", cmap)
        mb_scores = {n: _section_score(g, SECTIONS["masterBlock"], cmap.master_block) for n, g in grids.items() if n != (gp_sheet or gp_hint)}
        mb_hint = None if mb_sheet else next((n for n in sorted(mb_scores, key=mb_scores.get, reverse=True) if mb_scores[n] >= 2), None)
        sections.append(_check_section(SECTIONS["masterBlock"], mb_sheet or mb_hint, mb_sheet is not None, mb_hint, grids, cmap))
        om_sheet = cm.resolve_sheet(sheets, "om", cmap)
        for key, resolved, hint in (("gp", gp_sheet, gp_hint), ("masterBlock", mb_sheet, mb_hint), ("om", om_sheet, None)):
            sheet_map.append({"key": key, "label": SHEET_LABELS[key], "acceptedNames": _sheet_labels(key, cmap), "sheet": resolved, "suggestion": hint})
    elif kind == "escalation":
        s = SECTIONS["escalation"]
        sheet = next((n for n in readable if cm.find_header_row(grids[n], cmap.escalation, s.anchors) is not None), best_esc)
        sections.append(_check_section(s, sheet, True, None, grids, cmap))

    missing_required = [(x["key"], f["field"]) for x in sections for f in x["fields"] if f["required"] and f["status"] == "missing"]
    gp_ok = kind != "master" or sheet_map[0]["sheet"] is not None
    header_ok = all(x["headerFound"] for x in sections if x["key"] != "masterBlock")
    return {
        "kind": kind,
        "sheets": sheets,
        "sheetMap": sheet_map,
        "sections": sections,
        "ready": kind is not None and gp_ok and header_ok and not missing_required,
        "missingRequired": len(missing_required),
        "missingOptional": sum(1 for x in sections for f in x["fields"] if not f["required"] and f["status"] == "missing"),
        "problems": cmap.problems,
    }


def _sheet_labels(key: str, cmap: cm.ColumnMap) -> list[str]:
    custom = _custom_names().get("sheets", {}).get(key, [])
    names: dict[str, str] = {}
    for n in [*custom, *cm.SHEETS[key]]:
        names.setdefault(norm(n), n)
    return [names[n] for n in cmap.sheets[key] if n in names]


# ---------------------------------------------------------------- column_map.json


def _read_file() -> dict[str, Any]:
    """Current column_map.json as a dict ({} when there is none). Raises MapperError when it is broken."""
    path = cm.map_path()
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > cm.MAX_BYTES:
            raise ValueError(f"larger than {cm.MAX_BYTES // 1024} KB")
        raw = json.loads(path.read_text(encoding="utf-8"))
        cm._File.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise MapperError(f"{cm.FILE_NAME} cannot be read ({str(exc).splitlines()[0][:160]}) – fix or remove the file first; it was not changed.") from None
    return raw


def _custom_names() -> dict[str, dict[str, list[str]]]:
    """Names in column_map.json that are not built in: {file section: {field: [names]}} (empty when unreadable)."""
    try:
        raw = _read_file()
    except MapperError:
        return {}
    defaults = {"sheets": cm.SHEETS, **{s.file_key: s.defaults for s in SECTIONS.values()}}
    out: dict[str, dict[str, list[str]]] = {}
    for sec, fields in defaults.items():
        for f, names in (raw.get(sec) or {}).items():
            if f not in fields:
                continue
            built = {norm(n) for n in fields[f]}
            extra = [n for n in names if isinstance(n, str) and norm(n) and norm(n) not in built]
            if extra:
                out.setdefault(sec, {})[f] = extra
    return out


def custom_names() -> list[dict[str, Any]]:
    """Names added to the built-in ones, for the Data Operations list."""
    out = []
    labels = {"sheets": ("Sheet", {k: SHEET_LABELS[k] for k in cm.SHEETS}), **{s.file_key: (s.label, {f: v[0] for f, v in s.defaults.items()}) for s in SECTIONS.values()}}
    keys = {"sheets": "sheets", **{s.file_key: s.key for s in SECTIONS.values()}}
    for sec, fields in _custom_names().items():
        where, flabels = labels[sec]
        for f, names in fields.items():
            for n in names:
                out.append({"section": keys[sec], "sectionLabel": where, "field": f, "fieldLabel": flabels.get(f, f), "name": n})
    return out


def _write(raw: dict[str, Any]) -> None:
    text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > cm.MAX_BYTES:
        raise MapperError(f"{cm.FILE_NAME} would be larger than {cm.MAX_BYTES // 1024} KB – remove names that are no longer used first.")
    cm._File.model_validate(raw)
    path = cm.map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix(".json.bak").write_bytes(path.read_bytes())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    with cm._lock:  # the next import reads the new names at once (also when the file time does not change)
        cm._cache.update(map=None, mtime=None)


def _clean_name(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "")).strip()
    if not n or len(n) > MAX_NAME or any(ord(ch) < 32 for ch in n):
        raise MapperError(f"Not a usable name: {str(name)[:60]!r} (1–{MAX_NAME} characters).")
    return n


def add_names(columns: list[dict[str, str]], sheets: list[dict[str, str]]) -> list[str]:
    """Add the chosen names; returns readable lines of what was added. All or nothing."""
    with _write_lock:
        raw = _read_file()
        cmap = cm.load_column_map()
        added: list[str] = []
        planned: dict[tuple[str, str], str] = {}  # (file section, normalised name) -> field

        def put(sec: str, field: str, name: str, defaults: tuple[str, ...]) -> None:
            lst = raw.setdefault(sec, {}).setdefault(field, [])
            if not lst:
                lst.extend(defaults)  # keep the file readable: the built-in names first
            if norm(name) not in {norm(x) for x in lst}:
                lst.append(name)

        for x in sheets:
            key, name = x.get("key"), _clean_name(x.get("name", ""))
            if key not in cm.SHEETS:
                raise MapperError(f"Unknown sheet {key!r}.")
            owner = next((k for k, ns in cmap.sheets.items() if norm(name) in ns), None)
            if owner == key:
                continue
            if owner is not None or planned.get(("sheets", norm(name))) not in (None, key):
                raise MapperError(f"Sheet name '{name}' is already used for {SHEET_LABELS[owner or planned[('sheets', norm(name))]]}.")
            planned[("sheets", norm(name))] = key
            put("sheets", key, name, cm.SHEETS[key])
            added.append(f"Sheet {SHEET_LABELS[key]}: '{name}'")

        for x in columns:
            s = SECTIONS.get(x.get("section", ""))
            if s is None:
                raise MapperError(f"Unknown section {x.get('section')!r}.")
            field, name = x.get("field", ""), _clean_name(x.get("name", ""))
            if field not in s.defaults:
                raise MapperError(f"Unknown field {field!r} for {s.label}.")
            names = getattr(cmap, s.cmap_attr)
            owner = next((f for f, ns in names.items() if norm(name) in ns), None)
            if owner == field:
                continue  # already accepted
            if owner is not None:
                raise MapperError(f"'{name}' is already the column of {s.defaults[owner][0]} in {s.label} – one column cannot feed two fields.")
            other = planned.get((s.file_key, norm(name)))
            if other is not None and other != field:
                raise MapperError(f"'{name}' was chosen for both {s.defaults[other][0]} and {s.defaults[field][0]} in {s.label}.")
            planned[(s.file_key, norm(name))] = field
            put(s.file_key, field, name, s.defaults[field])
            added.append(f"{s.label} · {s.defaults[field][0]}: '{name}'")
        if added:
            raw.setdefault("_help", _HELP)
            _write(raw)
        return added


def remove_name(section: str, field: str, name: str) -> str:
    """Remove a name an admin added (built-in names stay)."""
    if section == "sheets":
        sec, defaults, where = "sheets", cm.SHEETS.get(field), SHEET_LABELS.get(field, field)
    else:
        s = SECTIONS.get(section)
        sec, defaults, where = (s.file_key, s.defaults.get(field), s.label) if s else ("", None, "")
    if defaults is None:
        raise MapperError("Unknown section or field.")
    if norm(name) in {norm(n) for n in defaults}:
        raise MapperError(f"'{name}' is a built-in name and always stays.")
    with _write_lock:
        raw = _read_file()
        lst = (raw.get(sec) or {}).get(field) or []
        keep = [n for n in lst if norm(n) != norm(name)]
        if len(keep) == len(lst):
            raise MapperError(f"'{name}' is not in the column mapper.")
        raw[sec][field] = keep
        _write(raw)
    return f"{where} · {field}: '{name}' removed"


_HELP = (
    "Accepted sheet and column names of the uploaded workbooks: sheets / gpColumns / masterBlockColumns = master-data "
    "workbook, escalationColumns = Escalation Matrix. Names can be added on Data Operations → Column names, or here. "
    "Upper/lower case and extra spaces do not matter. Built-in names always keep working. Do not give one name to two fields."
)
