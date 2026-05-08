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

# Use an EPCR-scoped alembic version table so we never touch a sibling
# service's `alembic_version` row on shared RDS.
_VERSION_TABLE = os.environ.get("EPCR_ALEMBIC_VERSION_TABLE", "epcr_alembic_version")

# Accept EPCR_DATABASE_URL (preferred) or CARE_DATABASE_URL (legacy) or
# DATABASE_URL (the actual ECS secret name in staging/production).
_db_url = (
    os.environ.get("EPCR_DATABASE_URL")
    or os.environ.get("CARE_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
)
if not _db_url:
    raise RuntimeError(
        "None of EPCR_DATABASE_URL / CARE_DATABASE_URL / DATABASE_URL is set. "
        "Alembic cannot run without a configured database URL."
    )

# Normalize scheme + strip libpq-only query params that asyncpg rejects.
import urllib.parse as _up
import ssl as _ssl

_LIBPQ_ONLY = {
    "sslmode", "sslcert", "sslkey", "sslrootcert", "sslcrl",
    "sslcompression", "channel_binding", "gssencmode", "target_session_attrs",
}
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql+psycopg://"):
    _db_url = _db_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

_p = _up.urlparse(_db_url)
_connect_args: dict = {}
if _p.scheme.startswith("postgresql"):
    _qs = _up.parse_qs(_p.query, keep_blank_values=True)
    _sslmode = _qs.get("sslmode", [""])[0].lower()
    if _sslmode in ("require", "verify-ca", "verify-full", "prefer", "allow"):
        _ctx = _ssl.create_default_context()
        _ctx.check_hostname = False
        _ctx.verify_mode = _ssl.CERT_NONE
        _connect_args["ssl"] = _ctx
    _qs2 = {k: v for k, v in _qs.items() if k not in _LIBPQ_ONLY}
    _db_url = _up.urlunparse(
        _p._replace(query=_up.urlencode({k: v[0] for k, v in _qs2.items()}))
    )

# alembic.ini uses ConfigParser interpolation: any '%' in the URL must be
# doubled to escape it. Pass the URL via raw set in main_options instead.
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))


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
        version_table=_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations on an active synchronous connection.

    Args:
        connection: Active SQLAlchemy connection handed in by the async runner.
    """
    context.configure(connection=connection, target_metadata=target_metadata, version_table=_VERSION_TABLE)
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
