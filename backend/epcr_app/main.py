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
- api_transfer_packet: Transfer packet OCR extraction + review manifest (7 routes)
- api_audit: Chart field audit trail (5 routes)
"""
import logging
from contextlib import asynccontextmanager
import os
import asyncio

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
from epcr_app.api_cpae import router as cpae_router
from epcr_app.api_vision import router as vision_router
from epcr_app.api_ocr import router as ocr_router
from epcr_app.api_clinical_extended import router as clinical_extended_router
from epcr_app.api_smart_text_address import router as smart_text_address_router
from epcr_app.api_desktop import router as desktop_router
from epcr_app.api_chart_workspace import router as chart_workspace_router
from epcr_app.api_patient_registry import router as patient_registry_router
from epcr_app.api_nemsis_defined_lists import router as nemsis_defined_lists_router
from epcr_app.api_nemsis_custom_elements import router as nemsis_custom_elements_router
from epcr_app.api_nemsis_field_graph import router as nemsis_field_graph_router
from epcr_app.api_nemsis_registry import router as nemsis_registry_router
from epcr_app.api_nemsis_scenarios import router as nemsis_scenarios_router
from epcr_app.api_nemsis_field_values import router as nemsis_field_values_router
from epcr_app.api_nemsis_datasets import router as nemsis_datasets_router
from epcr_app.api_cta_testing import router as cta_testing_router
from epcr_app.api_tac_schematron_packages import router as tac_schematron_packages_router
from epcr_app.api_version import router as version_router
# NEMSIS v3.5.1 vertical slices (migrations 024..039)
from epcr_app.api_chart_times import router as chart_times_router
from epcr_app.api_chart_dispatch import router as chart_dispatch_router
from epcr_app.api_chart_crew import router as chart_crew_router
from epcr_app.api_chart_response import router as chart_response_router
from epcr_app.api_chart_scene import router as chart_scene_router
from epcr_app.api_chart_situation import router as chart_situation_router
from epcr_app.api_chart_history import router as chart_history_router
from epcr_app.api_chart_injury import router as chart_injury_router
from epcr_app.api_chart_arrest import router as chart_arrest_router
from epcr_app.api_chart_disposition import router as chart_disposition_router
from epcr_app.api_chart_payment import router as chart_payment_router
from epcr_app.api_chart_outcome import router as chart_outcome_router
from epcr_app.api_chart_exam import router as chart_exam_router
from epcr_app.api_patient_profile_ext import router as patient_profile_ext_router
from epcr_app.api_vitals_ext import router as vitals_ext_router
from epcr_app.api_medication_admin_ext import router as medication_admin_ext_router
from epcr_app.api_intervention_ext import router as intervention_ext_router
from epcr_app.api_ai import router as ai_router
from epcr_app.api_transfer_packet import router as transfer_packet_router
from epcr_app.api_audit import router as audit_router
from epcr_app.api_quality import router as quality_router
import epcr_app.models_audit  # noqa: F401 — ensures audit tables are registered with Base
import epcr_app.models_quality  # noqa: F401 — ensures quality module tables are registered with Base
from epcr_app.db import init_db
from adaptix_contracts.event_contracts import LocalEventConsumerRegistry
from epcr_app.background_worker import EventProcessingWorker
from epcr_app.event_consumers import FireIncidentEventConsumer

logger = logging.getLogger(__name__)

_event_worker: EventProcessingWorker | None = None
_event_worker_task: asyncio.Task | None = None


def _cors_allow_origins() -> list[str]:
    """Return allowed CORS origins for local and configured clients."""

    configured = (
        os.environ.get("EPCR_CORS_ALLOW_ORIGINS", "").strip()
        or os.environ.get("CORS_ORIGINS", "").strip()
    )
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://adaptixcore.com",
        "https://www.adaptixcore.com",
        "https://app.adaptixcore.com",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: startup and shutdown.
    
    On startup: initializes database tables from models.
    On shutdown: cleans up resources.
    
    Yields:
        None: Control returns to FastAPI during running state.
    """
    global _event_worker, _event_worker_task
    logger.info("Care service starting: initializing database")
    try:
        await init_db()
    except Exception as exc:
        logger.warning("Care service database initialization deferred: %s", str(exc))
    try:
        if os.getenv("CORE_EVENT_BUS_URL") and (os.getenv("CORE_EVENT_BUS_TOKEN") or os.getenv("CORE_PROVISIONING_TOKEN")):
            registry = LocalEventConsumerRegistry()
            registry.register("fire.incident.created", FireIncidentEventConsumer.on_incident_created)
            _event_worker = EventProcessingWorker(event_registry=registry)
            await _event_worker.initialize()
            _event_worker_task = asyncio.create_task(_event_worker.run())
            logger.info("Care event worker started with registrations=%s", registry.list_registrations())
        else:
            logger.warning("Care event worker not started; Core event bus configuration is absent")
    except Exception as exc:
        logger.warning("Care event worker initialization deferred: %s", str(exc))
    logger.info("Care service startup complete")
    
    yield
    if _event_worker is not None:
        await _event_worker.stop()
    if _event_worker_task is not None:
        _event_worker_task.cancel()
        try:
            await _event_worker_task
        except asyncio.CancelledError:
            pass
    
    logger.info("Care service shutdown")


app = FastAPI(
    title="Care Service (ePCR)",
    description="Emergency Patient Care Records with NEMSIS 3.5.1 compliance validation",
    version="1.0.0",
    lifespan=lifespan
)


from fastapi import Request
from typing import Callable


@app.middleware("http")
async def rewrite_legacy_path(request: Request, call_next: Callable):
    path = request.scope.get("path", "")
    if path.startswith("/api/epcr") and not path.startswith("/api/v1/"):
        request.scope["path"] = "/api/v1/epcr" + path[len("/api/epcr"):]
    return await call_next(request)


@app.get("/api/epcr/health", include_in_schema=False)
@app.get("/api/epcr/healthz", include_in_schema=False)
async def legacy_epcr_health():
    return {"status": "ok", "service": "epcr"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Authorization",
        "Content-Language",
        "Content-Type",
        "X-Requested-With",
        "X-Tenant-ID",
        "X-User-ID",
        "X-User-Email",
        "X-User-Roles",
        "X-Correlation-ID",
    ],
)

# Mount the local CTA testing portal auth router only when explicitly enabled.
# This router (epcr_app.api_auth) issues HS256 tokens from a local secret and
# exists for local/CTA testing portals only. It MUST NOT be exposed in
# production: real production auth is the Adaptix Core Keycloak/OIDC flow.
def _local_auth_enabled() -> bool:
    """Return True if EPCR local CTA portal auth is explicitly enabled."""
    return os.getenv("EPCR_ENABLE_LOCAL_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}

if _local_auth_enabled():
    logger.warning(
        "Care service: EPCR_ENABLE_LOCAL_AUTH is enabled. "
        "Mounting local CTA portal auth router. This must never be enabled in production."
    )
    app.include_router(auth_router)
    # Also mount auth router under gateway-prefixed path for ALB routing
    app.include_router(auth_router, prefix="/api/v1/epcr", include_in_schema=False)
else:
    logger.info(
        "Care service: local CTA portal auth router is disabled "
        "(set EPCR_ENABLE_LOCAL_AUTH=true to enable for local CTA testing only)."
    )
app.include_router(router)
app.include_router(export_router)
app.include_router(nemsis_router)
app.include_router(nemsis_packs_router)
app.include_router(nemsis_submissions_router)
app.include_router(nemsis_validation_router)
app.include_router(timeline_router)
app.include_router(cpae_router)
app.include_router(vision_router)
app.include_router(ocr_router)
app.include_router(clinical_extended_router)
app.include_router(smart_text_address_router)
app.include_router(desktop_router)
app.include_router(chart_workspace_router)
app.include_router(patient_registry_router)
app.include_router(nemsis_defined_lists_router)
app.include_router(nemsis_custom_elements_router)
app.include_router(nemsis_field_graph_router)
app.include_router(nemsis_registry_router)
app.include_router(nemsis_scenarios_router)
app.include_router(nemsis_field_values_router)
app.include_router(nemsis_datasets_router)
app.include_router(cta_testing_router)
app.include_router(tac_schematron_packages_router)
app.include_router(version_router)
# NEMSIS v3.5.1 vertical slice routers
app.include_router(chart_times_router)
app.include_router(chart_dispatch_router)
app.include_router(chart_crew_router)
app.include_router(chart_response_router)
app.include_router(chart_scene_router)
app.include_router(chart_situation_router)
app.include_router(chart_history_router)
app.include_router(chart_injury_router)
app.include_router(chart_arrest_router)
app.include_router(chart_disposition_router)
app.include_router(chart_payment_router)
app.include_router(chart_outcome_router)
app.include_router(patient_profile_ext_router)
app.include_router(vitals_ext_router)
app.include_router(medication_admin_ext_router)
app.include_router(intervention_ext_router)
app.include_router(chart_exam_router)
# AI clinical intelligence engine
app.include_router(ai_router)
# Transfer packet intelligence + chart field audit trail
app.include_router(transfer_packet_router)
app.include_router(audit_router)
# Medical Director, QA, and QI quality governance module
app.include_router(quality_router)
# Clinical protocols catalog
from epcr_app.protocols.router import router as protocols_router  # noqa: E402
app.include_router(protocols_router)

logger.info("Care service configured with all routers: CareGraph, CPAE, VAS, Vision, CriticalCare, Sync, Dashboard, SmartText, Address, Desktop, NEMSIS v3.5.1 slices (eTimes, eDispatch, eCrew, eResponse, eScene, eSituation, eHistory, eInjury, eArrest, eDisposition, ePayment, eOutcome, eExam, ePatient-ext, eVitals-ext, eMedications-ext, eProcedures-ext), AI, TransferPacket, Audit")


@app.get("/healthz")
async def healthz() -> dict:
    """Health check endpoint for the care (ePCR) service."""
    return {"status": "ok", "service": "epcr"}


@app.get("/readyz")
async def readyz() -> dict:
    """Readiness check endpoint for the care (ePCR) service."""
    return {"status": "ok", "service": "epcr"}


@app.get("/api/v1/epcr/healthz", include_in_schema=False)
async def api_v1_epcr_healthz() -> dict:
    """Prefixed health check for gateway routing."""
    return {"status": "ok", "service": "epcr"}


@app.get("/api/v1/epcr/readyz", include_in_schema=False)
async def api_v1_epcr_readyz() -> dict:
    """Prefixed readiness check for gateway routing."""
    return {"status": "ok", "service": "epcr"}


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8001)
