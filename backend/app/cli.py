"""Command-line administration.

  python -m app.cli create-user --email you@company.com --name "Your Name" --role admin
  python -m app.cli import-file "../data/raw/Master Data V8.2 Daily track 09-10-26.xlsb"
  python -m app.cli reconcile
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

from .db import SessionLocal, init_db
from .models import User
from .security.core import hash_password, password_problems


def create_user(args: argparse.Namespace) -> int:
    email = args.email.strip().lower()
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
    r = sub.add_parser("reconcile")
    r.set_defaults(fn=reconcile_cmd)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
