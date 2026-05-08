"""Care domain database configuration and health checks.

Provides async database connection management with truthful health verification.
Health checks validate actual database connectivity before reporting healthy status.

The database URL is validated lazily so test modules can import the application,
override dependencies, and exercise non-database paths without fabricating a
production configuration. Startup and database-backed flows still fail
explicitly when the database URL is missing.
"""
from functools import lru_cache
import logging
import os
from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _configured_database_url() -> str | None:
    """Return the configured database URL if present."""
    return os.environ.get("EPCR_DATABASE_URL") or os.environ.get("CARE_DATABASE_URL")


def _require_database_url() -> str:
    """Return the configured database URL or fail with a production-safe message."""
    database_url = _configured_database_url()
    if not database_url:
        raise RuntimeError(
            "EPCR_DATABASE_URL is not configured. "
            "Set this environment variable to a valid asyncpg connection string "
            "before starting the ePCR service. SQLite is not permitted in production."
        )
    return database_url


def _engine_options(database_url: str) -> dict:
    """Build engine options that respect the selected SQLAlchemy dialect.

    SQLite test engines use StaticPool/NullPool semantics that do not accept
    queue pool sizing arguments, while production asyncpg deployments do.

    Args:
        database_url: SQLAlchemy connection URL.

    Returns:
        dict: Keyword arguments safe to pass into ``create_async_engine``.
    """
    options = {
        "echo": False,
        "pool_pre_ping": True,
    }

    dialect_name = make_url(database_url).get_backend_name()
    if dialect_name != "sqlite":
        options["pool_size"] = 10
        options["max_overflow"] = 20

    return options


@lru_cache(maxsize=None)
def _get_engine(database_url: str):
    """Create or reuse an async engine for the provided database URL."""
    return create_async_engine(
        database_url,
        **_engine_options(database_url),
    )


@lru_cache(maxsize=None)
def _get_session_maker(database_url: str):
    """Create or reuse a sessionmaker bound to the configured database URL."""
    return async_sessionmaker(
        _get_engine(database_url),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_session():
    """Dependency for FastAPI to inject AsyncSession into route handlers.
    
    Yields:
        AsyncSession: Database session for the request lifetime.
    """
    async with _get_session_maker(_require_database_url())() as session:
        yield session


async def init_db():
    """Initialize database tables from models.
    
    Creates all tables defined in Base.metadata if they don't exist.
    Must be called during application startup.
    
    Raises:
        SQLAlchemyError: If database initialization fails.
    """
    try:
        from epcr_app.models import Base  # noqa: F401 — registers core tables
        # Import all new model modules to register their tables with Base.metadata
        import epcr_app.models_caregraph  # noqa: F401
        import epcr_app.models_cpae  # noqa: F401
        import epcr_app.models_vas  # noqa: F401
        import epcr_app.models_vision  # noqa: F401
        import epcr_app.models_critical_care  # noqa: F401
        import epcr_app.models_terminology  # noqa: F401
        import epcr_app.models_sync  # noqa: F401
        import epcr_app.models_dashboard  # noqa: F401
        import epcr_app.models_smart_text  # noqa: F401
        import epcr_app.models_tac_schematron  # noqa: F401
        async with _get_engine(_require_database_url()).begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except SQLAlchemyError as e:
        logger.error(f"Database initialization failed: {str(e)}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error during database initialization: {str(e)}", exc_info=True)
        raise


async def check_health() -> dict:
    """Check actual database connectivity and report truthful health status.
    
    Attempts to execute a simple query. Returns degraded-state response if
    database is unavailable, NEVER fabricates health status.
    
    Returns:
        dict: Health status with keys:
            - status: "healthy" if DB connected, "degraded" if unavailable
            - service: "epcr"
            - database: "connected" or error message
            
    Example:
        >>> health = await check_health()
        >>> assert health["status"] in ["healthy", "degraded"]
    """
    database_url = _configured_database_url()
    if not database_url:
        logger.warning("Health check failed: database URL is not configured")
        return {
            "status": "degraded",
            "service": "epcr",
            "database": "misconfigured: missing EPCR_DATABASE_URL",
        }

    try:
        async with _get_session_maker(database_url)() as session:
            await session.execute(text("SELECT 1"))
        logger.debug("Health check: database responsive")
        return {
            "status": "healthy",
            "service": "epcr",
            "database": "connected"
        }
    except SQLAlchemyError as e:
        logger.warning(f"Health check failed: database unavailable ({str(e)})")
        return {
            "status": "degraded",
            "service": "epcr",
            "database": f"unavailable: {type(e).__name__}"
        }
    except Exception as e:
        logger.error(f"Health check error: {str(e)}", exc_info=True)
        return {
            "status": "degraded",
            "service": "epcr",
            "database": f"error: {type(e).__name__}"
        }
