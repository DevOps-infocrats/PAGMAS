"""Command-line administration.

  python -m app.cli create-user --email you@company.com --name "Your Name" --role admin
  python -m app.cli import-file "../data/raw/Master Data V8.2 Daily track 09-10-26.xlsb"
  python -m app.cli reconcile
  python -m app.cli backfill-daily "../data/raw/Master Data V8.2 Daily track 14-10-26.xlsb"
  python -m app.cli backfill-periods            (weekly / monthly history from the kept imports)
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

from .db import SessionLocal, init_db
from .models import User
from .security.core import hash_password, password_problems, valid_email


def create_user(args: argparse.Namespace) -> int:
    email = valid_email(args.email)
    if email is None:
        print(f"{args.email!r} is not a valid e-mail address (the account could never sign in).", file=sys.stderr)
        return 2
    password = args.password or getpass.getpass("Password (input hidden): ")
    if not args.password and password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    problems = password_problems(password, email)
    if problems:
        print("Password needs: " + "; ".join(problems))
        return 1
    with SessionLocal() as db:
        if db.scalars(select(User).where(func.lower(User.email) == email)).first():
            print(f"User {email} already exists.")
            return 1
        db.add(User(email=email, name=args.name, role=args.role, password_hash=hash_password(password)))
        db.commit()
    print(f"Created {args.role} {email}")
    return 0


def import_cmd(args: argparse.Namespace) -> int:
    from .ingestion.service import import_file

    ds = import_file(Path(args.path).resolve())
    print(f"Dataset {ds.id}: {ds.status} - {ds.rows_accepted} rows, data as of {ds.data_as_of}" + (f" - {ds.message}" if ds.message else ""))
    return 0 if ds.status in {"SUCCESS", "PARTIAL"} else 1


def backfill_daily_cmd(args: argparse.Namespace) -> int:
    """Put the daily availability of an (older) workbook into the cross-upload history only – no dataset is
    created and the active data is untouched. Days the history already has from a newer file are kept."""
    from .ingestion.history import history_months, merge_daily
    from .ingestion.packs import wide_frames
    from .ingestion.parser import parse_workbook

    path = Path(args.path).resolve()
    parsed = parse_workbook(path)
    if parsed.data_as_of is None:
        print("No data date found in the file.")
        return 1
    daily = wide_frames(parsed.availability)["D"]
    with SessionLocal() as db:
        months = merge_daily(db, daily, parsed.data_as_of, path.name)
        db.commit()
        print(f"{path.name}: data as of {parsed.data_as_of}, {daily.shape[1]} days x {daily.shape[0]} GPs merged into {', '.join(months)}")
        for m in history_months(db):
            print(f"  {m['month']}: {m['days']} days (newest file data date {m['dataAsOf']}, {m['sourceFile']})")
    return 0


def backfill_periods_cmd(args: argparse.Namespace) -> int:
    """Fill the weekly / monthly period history (period_history) from workbooks – no dataset is created and the active
    data is untouched. Without paths: the stored files of the imports still kept. Newer data always wins."""
    from sqlalchemy import select

    from .ingestion.history import merge_periods, period_history_summary
    from .ingestion.parser import parse_workbook
    from .models import Dataset

    paths = [Path(a).resolve() for a in args.paths]
    if not paths:
        with SessionLocal() as db:
            rows = db.execute(select(Dataset.stored_path, Dataset.data_as_of).where(Dataset.status.in_(("SUCCESS", "PARTIAL"))).order_by(Dataset.data_as_of)).all()
        paths = [Path(r.stored_path) for r in rows if r.stored_path and Path(r.stored_path).exists()]
    for path in paths:
        parsed = parse_workbook(path)
        with SessionLocal() as db:
            got = merge_periods(db, parsed, path.name)
            db.commit()
        print(f"{path.name}: data as of {parsed.data_as_of} - {len(got['added'])} added, {len(got['updated'])} updated, {len(got['kept'])} kept (newer data)")
    with SessionLocal() as db:
        rows = period_history_summary(db)
    kinds: dict[str, list[str]] = {}
    for r in rows:
        kinds.setdefault(r["kind"], []).append(r["period"])
    for k, v in kinds.items():
        print(f"  {k}: {len(v)} periods ({v[0]} … {v[-1]})")
    return 0


def reconcile_cmd(_: argparse.Namespace) -> int:
    from .analytics.reconcile import reconcile
    from .analytics.store import get_store

    r = reconcile(get_store())
    print(f"Data as of {r['dataAsOf']}; source MTD column ends {r['sourceMtdEnd']}")
    for row in r["rows"]:
        print(f"{row['status']:<13} {row['state']:<10} {row['metric']:<40} reported={row['reported']!s:<10} computed={row['computed']!s:<10} {row['note'] or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    init_db()
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(required=True)
    c = sub.add_parser("create-user")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    c.add_argument("--password", help="omit to be prompted (recommended)")
    c.set_defaults(fn=create_user)
    i = sub.add_parser("import-file")
    i.add_argument("path")
    i.set_defaults(fn=import_cmd)
    bp = sub.add_parser("backfill-periods")
    bp.add_argument("paths", nargs="*")
    bp.set_defaults(fn=backfill_periods_cmd)
    b = sub.add_parser("backfill-daily")
    b.add_argument("path")
    b.set_defaults(fn=backfill_daily_cmd)
    r = sub.add_parser("reconcile")
    r.set_defaults(fn=reconcile_cmd)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
