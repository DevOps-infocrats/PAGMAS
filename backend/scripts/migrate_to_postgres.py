"""One-time move from SQLite (backend/var/app.db) to PostgreSQL.

    1. users + audit log are copied (logins, roles, password hashes and history stay as they are)
    2. the newest master-data workbook in data/raw is imported into PostgreSQL (all sheets the dashboard uses);
       skipped when PostgreSQL already has active data, unless --force-import is given
    3. row counts are checked

Run from backend/ with DATABASE_URL=postgresql+psycopg://… in .env:

    .venv\\Scripts\\python scripts\\migrate_to_postgres.py

The SQLite file is only read, never changed – removing DATABASE_URL from .env switches back to it.
The target must be empty (the script refuses to run twice); pass --replace-users to overwrite users / audit log.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, delete, func, insert, select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine as target, init_db, is_postgres  # noqa: E402
from app.models import AuditLog, CircleSheetValue, Dataset, Gp, GpAvailability, User  # noqa: E402

SOURCE = f"sqlite:///{(BACKEND / 'var' / 'app.db').as_posix()}"


def _utc(row: dict) -> dict:
    """SQLite keeps naive UTC timestamps; PostgreSQL columns are timezone-aware."""
    return {k: (v.replace(tzinfo=UTC) if isinstance(v, datetime) and v.tzinfo is None else v) for k, v in row.items()}


def _copy(src, table, replace: bool, keep_users: set[int] | None = None) -> int:
    rows = [_utc(dict(r._mapping)) for r in src.execute(select(table))]
    if keep_users is not None:
        # audit entries of a user deleted earlier keep their row; the user link becomes empty (ON DELETE SET NULL)
        for r in rows:
            if r.get("user_id") is not None and r["user_id"] not in keep_users:
                r["user_id"] = None
    with target.begin() as dst:
        if replace:
            dst.execute(delete(table))
        if rows:
            dst.execute(insert(table), rows)
        # keep the id sequence ahead of the copied ids
        dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"))
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replace-users", action="store_true", help="overwrite users / audit log already in PostgreSQL")
    ap.add_argument("--skip-import", action="store_true", help="only copy users / audit log")
    ap.add_argument("--force-import", action="store_true", help="import the workbook even when PostgreSQL already has active data")
    args = ap.parse_args()

    if not is_postgres():
        print("DATABASE_URL in backend/.env does not point to PostgreSQL (postgresql+psycopg://…). Nothing done.")
        return 1
    if not (BACKEND / "var" / "app.db").exists():
        print("No SQLite database found at backend/var/app.db. Nothing to copy.")
        return 1

    init_db()  # creates every table (no-op for existing ones)
    with target.connect() as c:
        have_users = c.scalar(select(func.count()).select_from(User)) or 0
        have_data = c.scalar(select(func.count()).select_from(Dataset)) or 0
        have_active = c.scalar(select(func.count()).select_from(Dataset).where(Dataset.is_active.is_(True))) or 0
    if (have_users or have_data) and not args.replace_users:
        print(f"PostgreSQL already has {have_users} user(s) and {have_data} dataset(s). Run with --replace-users to overwrite users / audit log.")
        return 1

    src_engine = create_engine(SOURCE)
    with src_engine.connect() as src:
        users = _copy(src, User.__table__, args.replace_users)
        user_ids = set(src.scalars(select(User.id)))
        audits = _copy(src, AuditLog.__table__, args.replace_users, keep_users=user_ids)
        src_users = src.scalar(select(func.count()).select_from(User))
        src_audits = src.scalar(select(func.count()).select_from(AuditLog))
    print(f"users      : {users} copied (SQLite {src_users})")
    print(f"audit log  : {audits} copied (SQLite {src_audits})")
    ok = users == src_users and audits == src_audits

    if have_active and not args.skip_import and not args.force_import:
        print("import     : skipped - PostgreSQL already has active data (pass --force-import to import the workbook again)")
    elif not args.skip_import:
        raw = get_settings().raw_dir
        # Newest by modification time: names carry dd-mm-yy dates, which do not sort.
        files = [p for p in raw.glob("*") if p.suffix.lower() in {".xlsb", ".xlsx", ".xlsm"} and "escalation" not in p.name.lower()]
        if not files:
            print(f"No workbook in {raw} - upload one from Data Operations.")
            return 1
        from app.ingestion.service import import_file

        newest = max(files, key=lambda p: p.stat().st_mtime)
        started = datetime.now(UTC)
        ds = import_file(newest)
        secs = (datetime.now(UTC) - started).total_seconds()
        print(f"import     : {newest.name} -> dataset {ds.id} {ds.status} in {secs:.0f}s ({ds.rows_accepted} GP rows accepted, {ds.rows_rejected} rejected, data as of {ds.data_as_of})")
        with target.connect() as c:
            gps = c.scalar(select(func.count()).select_from(Gp).where(Gp.dataset_id == ds.id))
            vals = c.scalar(select(func.count()).select_from(GpAvailability).where(GpAvailability.dataset_id == ds.id))
            sheets = c.scalar(select(func.count()).select_from(CircleSheetValue).where(CircleSheetValue.dataset_id == ds.id))
        print(f"tables     : gps {gps:,} · gp_availability {vals:,} · circle_sheet_values {sheets:,}")
        ok = ok and ds.status in ("SUCCESS", "PARTIAL") and bool(ds.is_active)

    print("RESULT     : OK" if ok else "RESULT     : CHECK THE LINES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
