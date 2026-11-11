"""Admin editing of the plan files in the data folder (review_plan.json, amc_month_targets.json).

Every save is validated with the same model the dashboard reads the file with, written atomically and kept as a
version under DATA_DIR/plan_history/<file stem>/ (who saved it and when), so an earlier version can be restored.
The readers re-read a file when its modification time changes, so a save shows on the dashboard at once.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from . import amc_plan, review_targets

MAX_BYTES = 64 * 1024
KEEP_VERSIONS = 50

FILES: dict[str, dict[str, Any]] = {
    review_targets.PLAN_FILE: {
        "label": "Management plan (Management Review, AMC Conversion)",
        "model": review_targets._Plan,
        "sections": [
            {"key": "monthlyPlan", "label": "Monthly conversion plan (GPs per state)", "rowKind": "month"},
            {"key": "weeklyClosureTargets", "label": "Weekly closure targets (old target, GPs per state)", "rowKind": "week"},
        ],
        "fields": [{"key": "amcBaselineMonth", "label": "AMC baseline month (YYYY-MM)", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"}],
        "cache": review_targets._plan_cache,
    },
    amc_plan.TARGETS_FILE: {
        "label": "Month targets fallback (AMC Conversion → Monthly Plan vs Execution)",
        "model": amc_plan._MonthTargets,
        "sections": [{"key": "targets", "label": "Monthly targets (GPs per state)", "rowKind": "month"}],
        "fields": [],
        "cache": amc_plan._targets_cache,
    },
}

_lock = threading.Lock()


class PlanFileError(ValueError):
    pass


def _path(name: str) -> Path:
    if name not in FILES:
        raise PlanFileError(f"Unknown plan file {name!r}")
    return get_settings().data_dir / name


def _history_dir(name: str) -> Path:
    return get_settings().data_dir / "plan_history" / Path(name).stem


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _problem(name: str, data: dict[str, Any]) -> str | None:
    model: type[BaseModel] = FILES[name]["model"]
    try:
        model.model_validate({k: v for k, v in data.items() if not k.startswith("_")})
    except ValidationError as exc:
        return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'file'}: {e['msg']}" for e in exc.errors()[:5])
    return None


def describe(name: str) -> dict[str, Any]:
    path = _path(name)
    spec = FILES[name]
    data = _read(path)
    return {
        "name": name,
        "label": spec["label"],
        "exists": path.exists(),
        "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if path.exists() else None,
        "sections": spec["sections"],
        "fields": spec["fields"],
        "data": data,
        "problem": _problem(name, data) if path.exists() else None,
    }


def list_files() -> list[dict[str, Any]]:
    return [describe(n) for n in FILES]


def _normalise(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate an edited file. Keys starting with "_" (help text) are kept as they are; empty state cells -> null."""
    if not isinstance(data, dict):
        raise PlanFileError("The file must be a JSON object")
    spec = FILES[name]
    out: dict[str, Any] = dict(data)
    for sec in spec["sections"]:
        rows = out.get(sec["key"]) or {}
        if not isinstance(rows, dict):
            raise PlanFileError(f"{sec['label']}: must be an object of rows")
        clean: dict[str, dict[str, int | None]] = {}
        for row, vals in rows.items():
            row = str(row).strip()
            if not isinstance(vals, dict):
                raise PlanFileError(f"{sec['label']} → {row}: must be an object of states")
            cells: dict[str, int | None] = {}
            for state, v in vals.items():
                state = re.sub(r"\s+", " ", str(state)).strip().upper()
                if not state:
                    continue
                if v in (None, ""):
                    cells[state] = None
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                    raise PlanFileError(f"{sec['label']} → {row} → {state}: must be a whole number")
                try:
                    num = float(v)
                except ValueError:
                    raise PlanFileError(f"{sec['label']} → {row} → {state}: {v!r} is not a number") from None
                if num != int(num) or num < 0:
                    raise PlanFileError(f"{sec['label']} → {row} → {state}: must be a whole number ≥ 0")
                cells[state] = int(num)
            clean[row] = cells
        out[sec["key"]] = dict(sorted(clean.items(), key=lambda kv: _row_order(kv[0])))
    for f in spec["fields"]:
        if out.get(f["key"]) in ("", None):
            out[f["key"]] = None
    problem = _problem(name, out)
    if problem:
        raise PlanFileError(problem)
    if len(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_BYTES:
        raise PlanFileError(f"The file would be larger than {MAX_BYTES // 1024} KB")
    return out


def _row_order(key: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", key)
    if m:
        return int(m[1]), int(m[2])
    m = re.fullmatch(r"W-(\d{1,2})", key)
    return (0, int(m[1])) if m else (9999, 0)


def _archive(name: str, data: dict[str, Any], who: str, note: str) -> None:
    d = _history_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    (d / f"{stamp}.json").write_text(
        json.dumps({"savedAt": datetime.now(UTC).isoformat(), "savedBy": who, "note": note, "content": data}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for old in sorted(d.glob("*.json"))[:-KEEP_VERSIONS]:
        old.unlink(missing_ok=True)


def save(name: str, data: dict[str, Any], who: str) -> dict[str, Any]:
    path = _path(name)
    clean = _normalise(name, data)
    with _lock:
        if path.exists() and not any(_history_dir(name).glob("*.json")):
            _archive(name, _read(path), "file before the first edit", "original")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        FILES[name]["cache"].clear()
        _archive(name, clean, who, "saved")
    return describe(name)


def history(name: str) -> list[dict[str, Any]]:
    _path(name)
    out = []
    for p in sorted(_history_dir(name).glob("*.json"), reverse=True):
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"id": p.stem, "savedAt": v.get("savedAt"), "savedBy": v.get("savedBy"), "note": v.get("note"), "content": v.get("content") or {}})
    return out
