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


BACKEND_DIR = Path(__file__).resolve().parent.parent


def init_db() -> None:
    """PostgreSQL: bring the schema to the newest migration (backend/migrations – Alembic). Only migrations change the
    schema; a migration that already ran is skipped, so a restart without a new migration changes nothing.
    SQLite (tests, local fallback): tables straight from the models."""
    from . import models  # noqa: F401  (register tables)

    if is_postgres():
        upgrade_db()
    else:
        Base.metadata.create_all(engine)


def upgrade_db(revision: str = "head") -> None:
    """`alembic upgrade head` on the API's own engine (same as running it from backend/ by hand)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)
        conn.commit()
