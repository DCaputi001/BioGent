"""Alembic environment for the BioGent RAG service.

Two things here differ from Alembic's generated template, both deliberate:

1. The database URL comes from app.db_credentials.get_database_url(), not from
   sqlalchemy.url in alembic.ini. The RDS password lives only in Secrets
   Manager (AGENTS.md), so a URL written into a committed ini file could only
   ever be wrong or a leak.

2. include_object(), imported from app.models, hides the langchain_pg_* tables
   from autogenerate. They are created and owned by langchain-postgres at
   ingest time, not by us. Without it, the first `alembic revision
   --autogenerate` emits DROP TABLE for both -- Alembic sees tables in the
   database that no model declares and concludes they should not exist. It is
   defined in app/models.py rather than here so a test can import it; this
   module runs migrations at import time and cannot be imported from a test.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# alembic/ is a sibling of app/, not inside it, so `app` is not importable by
# default when Alembic runs this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db_credentials
from app.models import Base, include_object

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting, for review or manual application."""
    context.configure(
        url=db_credentials.get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the resolved database."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_credentials.get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            # Without this a column type change is silently skipped, which
            # makes a migration look applied while the column is unchanged.
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
