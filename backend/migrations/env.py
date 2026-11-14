"""Alembic environment – the database comes from app.config (DATABASE_URL in backend/.env), never from alembic.ini,
so the password stays in .env only.

    cd backend
    .venv\\Scripts\\alembic upgrade head                              # apply every pending migration
    .venv\\Scripts\\alembic current                                   # revision of the database
    .venv\\Scripts\\alembic revision --autogenerate -m "what changed"  # after changing app/models.py – then READ the file
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ -> `import app`

from app import models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.db import Base, engine  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from legacy import include_object  # noqa: E402

config = context.config
# The API calls the migrations itself (app.db.upgrade_db) and passes its connection – it keeps its own logging then.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite cannot ALTER most things in place
    )
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL statement_timeout = 0"))  # the API's 60 s limit must not cut off an index build
        context.run_migrations()


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it (review before a production change)."""
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as connection:
        _run(connection)
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
