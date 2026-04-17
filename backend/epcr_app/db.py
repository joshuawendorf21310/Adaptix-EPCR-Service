"""Care domain database configuration and health checks.

Provides async database connection management with truthful health verification.
Health checks validate actual database connectivity before reporting healthy status.

Raises RuntimeError at import time if EPCR_DATABASE_URL (or legacy CARE_DATABASE_URL)
is not configured so that misconfigured deployments fail explicitly.
"""
import logging
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

_raw_url = os.environ.get("EPCR_DATABASE_URL") or os.environ.get("CARE_DATABASE_URL")
if not _raw_url:
    raise RuntimeError(
        "EPCR_DATABASE_URL is not configured. "
        "Set this environment variable to a valid asyncpg connection string "
        "before starting the ePCR service. SQLite is not permitted in production."
    )

DATABASE_URL: str = _raw_url

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_session():
    """Dependency for FastAPI to inject AsyncSession into route handlers.
    
    Yields:
        AsyncSession: Database session for the request lifetime.
    """
    async with async_session_maker() as session:
        yield session


async def init_db():
    """Initialize database tables from models.
    
    Creates all tables defined in Base.metadata if they don't exist.
    Must be called during application startup.
    
    Raises:
        SQLAlchemyError: If database initialization fails.
    """
    try:
        from epcr_app.models import Base
        async with engine.begin() as conn:
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
    try:
        async with async_session_maker() as session:
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
