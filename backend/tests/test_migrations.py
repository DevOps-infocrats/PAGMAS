"""The Alembic migrations (backend/migrations) must build exactly the schema of app/models.py.

Fails when a model changes without a migration:  alembic revision --autogenerate --rev-id 00NN -m "what changed"
"""

import sys
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.db import Base

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "migrations"))


def _cfg(conn) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["connection"] = conn
    return cfg


def _diff(conn) -> list:
    from legacy import include_object  # migrations/legacy.py – the same filter --autogenerate uses

    mc = MigrationContext.configure(conn, opts={"compare_type": True, "include_object": include_object})
    return compare_metadata(mc, Base.metadata)


def test_single_head():
    heads = ScriptDirectory.from_config(_cfg(None)).get_heads()
    assert len(heads) == 1, f"several migration heads {heads} – merge them (alembic merge heads)"


def test_migrations_build_the_models_schema(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with eng.connect() as conn:
        command.upgrade(_cfg(conn), "head")
        command.upgrade(_cfg(conn), "head")  # a second run changes nothing
        conn.commit()
        assert _diff(conn) == [], "app/models.py and the migrations differ – add a migration"
        head = ScriptDirectory.from_config(_cfg(conn)).get_current_head()
        assert conn.scalar(text("select version_num from alembic_version")) == head
        assert len(set(inspect(conn).get_table_names()) - {"alembic_version"}) == len(Base.metadata.tables)
    eng.dispose()


def test_baseline_adopts_an_older_database_and_keeps_its_rows(tmp_path):
    """A database made before Alembic (a table without a later column, a missing table) is completed, rows kept."""
    eng = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with eng.begin() as conn:
        Base.metadata.tables["users"].create(conn)
        conn.execute(text(
            "CREATE TABLE tickets (id INTEGER PRIMARY KEY, code VARCHAR(20) UNIQUE, subject VARCHAR(200) NOT NULL, description TEXT NOT NULL, "
            "priority VARCHAR(10) NOT NULL, status VARCHAR(20) NOT NULL, assignee_id INTEGER, assignee_name VARCHAR(120) NOT NULL, "
            "assignee_email VARCHAR(254) NOT NULL, created_by_id INTEGER, created_by_name VARCHAR(120) NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "started_at DATETIME, submitted_at DATETIME, closed_at DATETIME, closed_by_id INTEGER, closed_by_name VARCHAR(120))"
        ))  # tickets as first shipped: no circle / deleted_at / deleted_by_name yet
        conn.execute(text(
            "INSERT INTO tickets (id, code, subject, description, priority, status, assignee_name, assignee_email, created_by_name) "
            "VALUES (7, 'TKT-000007', 'Old', 'kept', 'LOW', 'OPEN', 'A', 'a@x.in', 'Admin')"
        ))
    with eng.connect() as conn:
        command.upgrade(_cfg(conn), "head")
        conn.commit()
        cols = {c["name"] for c in inspect(conn).get_columns("tickets")}
        assert {"deleted_at", "circle"} <= cols  # added to the existing table
        assert conn.execute(text("select id, code, description from tickets")).all() == [(7, "TKT-000007", "kept")]
        assert inspect(conn).has_table("ticket_gp_forwards")
    eng.dispose()
