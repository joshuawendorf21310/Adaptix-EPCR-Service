"""Care domain FastAPI application with lifespan management.

Main application factory for the care (ePCR) service. Initializes database
on startup and includes all routers. Implements truthful health checks that
report actual system state.

Routers included:
- api: core ePCR chart lifecycle routes
- api_export: NEMSIS export generation and download
- api_nemsis: NEMSIS validation, readiness, mapping, and preview (4 routes)
- api_nemsis_packs: NEMSIS resource pack lifecycle (9 routes)
- api_nemsis_submissions: NEMSIS state submission lifecycle (8 routes)
- api_nemsis_validation: NEMSIS validation persistence and history (3 routes)
- api_timeline: Patient state timeline tracking (3 routes)
"""
import logging
from contextlib import asynccontextmanager
import os

from epcr_app.env_loader import load_local_env

load_local_env()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from epcr_app.api import router
from epcr_app.api_auth import router as auth_router
from epcr_app.api_export import router as export_router
from epcr_app.api_nemsis import router as nemsis_router
from epcr_app.api_nemsis_packs import router as nemsis_packs_router
from epcr_app.api_nemsis_submissions import router as nemsis_submissions_router
from epcr_app.api_nemsis_validation import router as nemsis_validation_router
from epcr_app.api_timeline import router as timeline_router
from epcr_app.db import init_db

logger = logging.getLogger(__name__)


def _cors_allow_origins() -> list[str]:
    """Return allowed CORS origins for local and configured clients."""

    configured = os.environ.get("EPCR_CORS_ALLOW_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: startup and shutdown.
    
    On startup: initializes database tables from models.
    On shutdown: cleans up resources.
    
    Yields:
        None: Control returns to FastAPI during running state.
    """
    logger.info("Care service starting: initializing database")
    try:
        await init_db()
        logger.info("Care service startup complete")
    except Exception as e:
        logger.error(f"Care service startup failed: {str(e)}", exc_info=True)
        raise
    
    yield
    
    logger.info("Care service shutdown")


app = FastAPI(
    title="Care Service (ePCR)",
    description="Emergency Patient Care Records with NEMSIS 3.5.1 compliance validation",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
app.include_router(export_router)
app.include_router(nemsis_router)
app.include_router(nemsis_packs_router)
app.include_router(nemsis_submissions_router)
app.include_router(nemsis_validation_router)
app.include_router(timeline_router)

logger.info("Care service configured")


@app.get("/healthz")
async def healthz() -> dict:
    """Health check endpoint for the care (ePCR) service.

    Returns:
        dict: Service health status.
    """
    return {"status": "healthy", "service": "epcr"}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8001)
