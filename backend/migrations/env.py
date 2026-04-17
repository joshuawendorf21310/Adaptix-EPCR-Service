"""Alembic environment for Adaptix ePCR domain migrations.

Supports async SQLAlchemy with asyncpg for production RDS PostgreSQL.
Reads EPCR_DATABASE_URL (or legacy CARE_DATABASE_URL) from the environment;
raises RuntimeError if not set so that misconfiguration is immediately visible.
target_metadata is bound to epcr_app.models.Base so autogenerate can detect
schema drift against the ORM models.
"""
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from epcr_app.models import Base  # noqa: E402

target_metadata = Base.metadata

_db_url = os.environ.get("EPCR_DATABASE_URL") or os.environ.get("CARE_DATABASE_URL")
if not _db_url:
    raise RuntimeError(
        "EPCR_DATABASE_URL is not set. "
        "Alembic cannot run without a configured database URL."
    )
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    """Run migrations in offline mode (no live DB connection required).

    Generates SQL scripts against the configured URL without connecting.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations on an active synchronous connection.

    Args:
        connection: Active SQLAlchemy connection handed in by the async runner.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine from alembic.ini config and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode; drives the async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
