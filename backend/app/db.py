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


# Nullable columns added after a table first shipped: create_all does not alter existing tables.
ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "escalation_contacts": {
        "ba": "VARCHAR(80)",
        "am_email": "VARCHAR(200)",
        "shq_email": "VARCHAR(200)",
        "coh_email": "VARCHAR(200)",
        "cbh_email": "VARCHAR(200)",
    },
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
