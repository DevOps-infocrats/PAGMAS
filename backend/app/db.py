from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def is_postgres() -> bool:
    return get_settings().database_url.startswith("postgresql")


def _make_engine():
    """SQLite (default, backend/var/app.db) or PostgreSQL when DATABASE_URL=postgresql+psycopg://… is set."""
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    elif url.startswith("postgresql"):
        # Small fixed pool (one API process); a stuck query is cancelled after 60 s instead of hanging a request.
        kwargs.update(pool_size=5, max_overflow=5, pool_recycle=1800)
        kwargs["connect_args"] = {"connect_timeout": 10, "application_name": "pratap-api", "options": "-c statement_timeout=60000"}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()
    _relax_not_null()
    _gp_forward_unique_per_step()


def _gp_forward_unique_per_step() -> None:
    """ticket_gp_forwards first shipped unique on (GP, recipient, action), which blocks forwarding a GP to the same SME /
    COH again after a send-back. Swap it for (review step, recipient) – only the constraint changes, no row does."""
    if not is_postgres():  # SQLite test databases are created from the current models
        return
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if not insp.has_table("ticket_gp_forwards"):
        return
    names = {u["name"] for u in insp.get_unique_constraints("ticket_gp_forwards")}
    with engine.begin() as conn:
        if "uq_gp_forward" in names:
            conn.execute(text("ALTER TABLE ticket_gp_forwards DROP CONSTRAINT uq_gp_forward"))
        if "uq_gp_forward_step" not in names:
            conn.execute(text("ALTER TABLE ticket_gp_forwards ADD CONSTRAINT uq_gp_forward_step UNIQUE (review_id, recipient_id)"))


# Nullable columns added after a table first shipped: create_all does not alter existing tables.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "escalation_contacts": {
        "ba": "VARCHAR(80)",
        "am_email": "VARCHAR(200)",
        "shq_email": "VARCHAR(200)",
        "coh_email": "VARCHAR(200)",
        "cbh_email": "VARCHAR(200)",
        "fe_email": "VARCHAR(200)",
    },
    "gp_amc_plan": {"approval_status": "VARCHAR(60)"},
    "mail_configs": {"extra_recipients": "TEXT"},
    "tickets": {"circle": "VARCHAR(80)", "deleted_at": "TIMESTAMP WITH TIME ZONE", "deleted_by_name": "VARCHAR(120)"},
    "ticket_tasks": {"circle": "VARCHAR(80)", "cbh_name": "VARCHAR(160)"},
    "ticket_task_gps": {
        "fe_name": "VARCHAR(120)", "fe_email": "VARCHAR(200)", "gp_category": "VARCHAR(1)", "review": "VARCHAR(20)", "review_at": "TIMESTAMP WITH TIME ZONE",
        "letter_date": "DATE", "amc_on": "DATE", "added_by": "VARCHAR(120)",
    },
    "ticket_progress_lines": {"category": "VARCHAR(1)"},
    "ticket_recipients": {"am_name": "VARCHAR(160)", "fe_mail": "VARCHAR(200)"},
}


def _add_missing_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table, columns in ADDED_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


# Columns that became optional after the table first shipped (create_all never alters an existing table).
RELAXED_COLUMNS = {"gps": ("total_rkm",)}  # blank TOTAL RKM = not reported, stored as NULL (never invented as 0)


def _relax_not_null() -> None:
    if not is_postgres():  # SQLite test databases are created from the current models
        return
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table, names in RELAXED_COLUMNS.items():
        if not insp.has_table(table):
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for name in names:
                if name in cols and not cols[name]["nullable"]:
                    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {name} DROP NOT NULL"))
