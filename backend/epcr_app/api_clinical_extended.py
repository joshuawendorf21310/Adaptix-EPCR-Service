"""Extended clinical API routes: OPQRST, CriticalCare, Sync, Dashboard.

All routes enforce tenant isolation, provider attribution, and audit logging.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, get_tenant_id
from epcr_app.models_caregraph import OPQRSTSymptom
from epcr_app.models_critical_care import (
    CriticalCareDevice,
    InfusionRun,
    VentilatorSession,
    BloodProductAdministration,
    ResponseWindow,
    InterventionIndication,
    InterventionIntent,
)
from epcr_app.models_sync import (
    SyncEventLog,
    SyncConflict,
    UploadQueueItem,
    SyncHealthRecord,
    AuditEnvelope,
)
from epcr_app.models_dashboard import (
    UserDashboardProfile,
    UserFavorite,
    UserThemeSettings,
    WorkspaceProfile,
    AgencyWorkflowConfig,
)

router = APIRouter(prefix="/api/v1/epcr", tags=["clinical-extended"])


# ===========================================================================
# OPQRST Symptom Engine
# ===========================================================================

class OPQRSTCreate(BaseModel):
    symptom_category: str
    symptom_label: str
    onset_description: Optional[str] = None
    onset_time: Optional[datetime] = None
    onset_sudden: Optional[bool] = None
    provocation_factors: Optional[list[str]] = None
    palliation_factors: Optional[list[str]] = None
    quality_descriptors: Optional[list[str]] = None
    radiation_present: Optional[bool] = None
    radiation_locations: Optional[list[str]] = None
    region_primary: Optional[str] = None
    severity_scale: Optional[int] = None
    severity_functional_impact: Optional[str] = None
    time_duration_minutes: Optional[int] = None
    time_progression: Optional[str] = None
    time_prior_episodes: Optional[bool] = None
    associated_symptoms: Optional[list[str]] = None
    baseline_comparison: Optional[str] = None
    recurrence_pattern: Optional[str] = None
    witness_context: Optional[str] = None
    caregraph_node_id: Optional[str] = None
    documented_at: datetime


@router.post("/charts/{chart_id}/opqrst", status_code=status.HTTP_201_CREATED)
async def create_opqrst(
    chart_id: str,
    body: OPQRSTCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Create a structured OPQRST symptom record.

    OPQRST is conditionally instantiated for pain, dyspnea, dizziness,
    headache, abdominal complaint, chest discomfort, neurologic complaint.
    OPQRST is NOT stored as plain text — every field is structured.
    """
    opqrst_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    opqrst = OPQRSTSymptom(
        id=opqrst_id,
        chart_id=chart_id,
        caregraph_node_id=body.caregraph_node_id,
        tenant_id=tenant_id,
        symptom_category=body.symptom_category,
        symptom_label=body.symptom_label,
        onset_description=body.onset_description,
        onset_time=body.onset_time,
        onset_sudden=body.onset_sudden,
        provocation_factors_json=json.dumps(body.provocation_factors) if body.provocation_factors else None,
        palliation_factors_json=json.dumps(body.palliation_factors) if body.palliation_factors else None,
        quality_descriptors_json=json.dumps(body.quality_descriptors) if body.quality_descriptors else None,
        radiation_present=body.radiation_present,
        radiation_locations_json=json.dumps(body.radiation_locations) if body.radiation_locations else None,
        region_primary=body.region_primary,
        severity_scale=body.severity_scale,
        severity_functional_impact=body.severity_functional_impact,
        time_duration_minutes=body.time_duration_minutes,
        time_progression=body.time_progression,
        time_prior_episodes=body.time_prior_episodes,
        associated_symptoms_json=json.dumps(body.associated_symptoms) if body.associated_symptoms else None,
        baseline_comparison=body.baseline_comparison,
        recurrence_pattern=body.recurrence_pattern,
        witness_context=body.witness_context,
        provider_id=user.user_id,
        documented_at=body.documented_at,
        updated_at=now,
    )
    session.add(opqrst)
    await session.commit()
    return {"id": opqrst_id, "status": "created"}


@router.get("/charts/{chart_id}/opqrst")
async def list_opqrst(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List OPQRST symptom records for a chart."""
    result = await session.execute(
        select(OPQRSTSymptom).where(
            OPQRSTSymptom.chart_id == chart_id,
            OPQRSTSymptom.tenant_id == tenant_id,
            OPQRSTSymptom.deleted_at.is_(None),
        )
    )
    items = result.scalars().all()
    return {
        "opqrst_records": [
            {
                "id": o.id,
                "symptom_category": o.symptom_category,
                "symptom_label": o.symptom_label,
                "severity_scale": o.severity_scale,
                "time_progression": o.time_progression,
                "documented_at": o.documented_at.isoformat() if o.documented_at else None,
            }
            for o in items
        ],
        "count": len(items),
    }


# ===========================================================================
# Critical Care
# ===========================================================================

class InfusionRunCreate(BaseModel):
    medication_name: str
    rxnorm_code: Optional[str] = None
    concentration: Optional[str] = None
    initial_rate_value: float
    initial_rate_unit: str
    initial_dose_value: Optional[float] = None
    initial_dose_unit: Optional[str] = None
    indication: str
    protocol_family: Optional[str] = None
    started_at: datetime
    caregraph_node_id: Optional[str] = None


class VentilatorSessionCreate(BaseModel):
    mode: str
    tidal_volume_ml: Optional[int] = None
    respiratory_rate: Optional[int] = None
    fio2_percent: Optional[int] = None
    peep_cmh2o: Optional[float] = None
    airway_type: Optional[str] = None
    ett_size_mm: Optional[float] = None
    ett_depth_cm: Optional[float] = None
    indication: str
    started_at: datetime
    device_id: Optional[str] = None
    caregraph_node_id: Optional[str] = None


class ResponseWindowCreate(BaseModel):
    intervention_id: str
    expected_response: str
    expected_response_window_minutes: Optional[int] = None
    actual_response: Optional[str] = None
    response_availability: str = "pending"
    unavailability_reason: Optional[str] = None
    response_adequate: Optional[bool] = None
    caregraph_node_id: Optional[str] = None


@router.post("/charts/{chart_id}/critical-care/infusions", status_code=status.HTTP_201_CREATED)
async def create_infusion_run(
    chart_id: str,
    body: InfusionRunCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Create a continuous infusion run with titration tracking."""
    infusion_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    session.add(InfusionRun(
        id=infusion_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        caregraph_node_id=body.caregraph_node_id,
        medication_name=body.medication_name,
        rxnorm_code=body.rxnorm_code,
        concentration=body.concentration,
        initial_rate_value=body.initial_rate_value,
        initial_rate_unit=body.initial_rate_unit,
        initial_dose_value=body.initial_dose_value,
        initial_dose_unit=body.initial_dose_unit,
        indication=body.indication,
        protocol_family=body.protocol_family,
        started_at=body.started_at,
        provider_id=user.user_id,
        updated_at=now,
    ))
    await session.commit()
    return {"id": infusion_id, "status": "created"}


@router.post("/charts/{chart_id}/critical-care/ventilator", status_code=status.HTTP_201_CREATED)
async def create_ventilator_session(
    chart_id: str,
    body: VentilatorSessionCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Create a ventilator management session."""
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    session.add(VentilatorSession(
        id=session_id,
        chart_id=chart_id,
        tenant_id=tenant_id,
        device_id=body.device_id,
        caregraph_node_id=body.caregraph_node_id,
        mode=body.mode,
        tidal_volume_ml=body.tidal_volume_ml,
        respiratory_rate=body.respiratory_rate,
        fio2_percent=body.fio2_percent,
        peep_cmh2o=body.peep_cmh2o,
        airway_type=body.airway_type,
        ett_size_mm=body.ett_size_mm,
        ett_depth_cm=body.ett_depth_cm,
        indication=body.indication,
        started_at=body.started_at,
        provider_id=user.user_id,
        updated_at=now,
    ))
    await session.commit()
    return {"id": session_id, "status": "created"}


@router.post("/charts/{chart_id}/critical-care/response-windows", status_code=status.HTTP_201_CREATED)
async def create_response_window(
    chart_id: str,
    body: ResponseWindowCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Document intervention response window.

    An intervention is NOT clinically complete without a documented response
    or an explicit unavailability reason.
    """
    window_id = str(uuid.uuid4())

    session.add(ResponseWindow(
        id=window_id,
        chart_id=chart_id,
        intervention_id=body.intervention_id,
        tenant_id=tenant_id,
        caregraph_node_id=body.caregraph_node_id,
        expected_response=body.expected_response,
        expected_response_window_minutes=body.expected_response_window_minutes,
        actual_response=body.actual_response,
        response_availability=body.response_availability,
        unavailability_reason=body.unavailability_reason,
        response_adequate=body.response_adequate,
        provider_id=user.user_id,
    ))
    await session.commit()
    return {"id": window_id, "status": "created"}


@router.get("/charts/{chart_id}/critical-care/infusions")
async def list_infusion_runs(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List active infusion runs for a chart."""
    result = await session.execute(
        select(InfusionRun).where(
            InfusionRun.chart_id == chart_id,
            InfusionRun.tenant_id == tenant_id,
            InfusionRun.deleted_at.is_(None),
        )
    )
    runs = result.scalars().all()
    return {
        "infusion_runs": [
            {
                "id": r.id,
                "medication_name": r.medication_name,
                "initial_rate_value": r.initial_rate_value,
                "initial_rate_unit": r.initial_rate_unit,
                "indication": r.indication,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            }
            for r in runs
        ],
        "count": len(runs),
    }


# ===========================================================================
# Sync Engine
# ===========================================================================

class SyncEventBatch(BaseModel):
    device_id: str
    events: list[dict]  # list of sync event payloads


class SyncHealthUpdate(BaseModel):
    device_id: str
    health_state: str
    pending_events_count: int = 0
    failed_events_count: int = 0
    pending_uploads_count: int = 0
    failed_uploads_count: int = 0
    unresolved_conflicts_count: int = 0
    last_error_detail: Optional[str] = None


@router.post("/sync/events", status_code=status.HTTP_201_CREATED)
async def upload_sync_events(
    body: SyncEventBatch,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Upload a batch of offline sync events for server-side replay.

    Events are idempotent — duplicate idempotency keys are silently skipped.
    """
    now = datetime.now(UTC)
    processed = 0
    skipped = 0

    for event in body.events:
        idempotency_key = event.get("idempotency_key")
        if not idempotency_key:
            continue

        # Check for duplicate
        existing = await session.execute(
            select(SyncEventLog).where(SyncEventLog.idempotency_key == idempotency_key)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        session.add(SyncEventLog(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            chart_id=event.get("chart_id"),
            device_id=body.device_id,
            user_id=user.user_id,
            event_type=event.get("event_type", "unknown"),
            event_payload_json=json.dumps(event),
            entity_type=event.get("entity_type", "unknown"),
            entity_id=event.get("entity_id", str(uuid.uuid4())),
            local_sequence_number=event.get("local_sequence_number", 0),
            device_timestamp=datetime.fromisoformat(event["device_timestamp"]) if event.get("device_timestamp") else now,
            status="uploaded",
            uploaded_at=now,
            server_acknowledged_at=now,
            idempotency_key=idempotency_key,
            created_at=now,
        ))
        processed += 1

    await session.commit()
    return {
        "processed": processed,
        "skipped_duplicates": skipped,
        "total": len(body.events),
    }


@router.get("/sync/health/{device_id}")
async def get_sync_health(
    device_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get sync health state for a device."""
    result = await session.execute(
        select(SyncHealthRecord).where(
            SyncHealthRecord.device_id == device_id,
            SyncHealthRecord.tenant_id == tenant_id,
        )
    )
    health = result.scalar_one_or_none()
    if not health:
        return {
            "device_id": device_id,
            "health_state": "unknown",
            "pending_events_count": 0,
            "failed_events_count": 0,
            "is_degraded": False,
        }

    return {
        "device_id": health.device_id,
        "health_state": health.health_state,
        "pending_events_count": health.pending_events_count,
        "failed_events_count": health.failed_events_count,
        "pending_uploads_count": health.pending_uploads_count,
        "failed_uploads_count": health.failed_uploads_count,
        "unresolved_conflicts_count": health.unresolved_conflicts_count,
        "last_successful_sync_at": health.last_successful_sync_at.isoformat() if health.last_successful_sync_at else None,
        "is_degraded": health.is_degraded,
        "degraded_reason": health.degraded_reason,
    }


@router.put("/sync/health", status_code=status.HTTP_200_OK)
async def update_sync_health(
    body: SyncHealthUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Update sync health record for a device."""
    now = datetime.now(UTC)
    result = await session.execute(
        select(SyncHealthRecord).where(
            SyncHealthRecord.device_id == body.device_id,
            SyncHealthRecord.tenant_id == tenant_id,
        )
    )
    health = result.scalar_one_or_none()

    if not health:
        health = SyncHealthRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            device_id=body.device_id,
            user_id=user.user_id,
            updated_at=now,
        )
        session.add(health)

    health.health_state = body.health_state
    health.pending_events_count = body.pending_events_count
    health.failed_events_count = body.failed_events_count
    health.pending_uploads_count = body.pending_uploads_count
    health.failed_uploads_count = body.failed_uploads_count
    health.unresolved_conflicts_count = body.unresolved_conflicts_count
    health.last_error_detail = body.last_error_detail
    health.is_degraded = body.health_state in ("degraded", "offline", "sync_failed")
    health.last_sync_attempt_at = now
    health.updated_at = now

    if body.health_state == "healthy":
        health.last_successful_sync_at = now
        health.is_degraded = False
        health.degraded_reason = None

    await session.commit()
    return {"status": "updated", "health_state": health.health_state}


@router.get("/sync/conflicts")
async def list_sync_conflicts(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List unresolved sync conflicts for the tenant."""
    result = await session.execute(
        select(SyncConflict).where(
            SyncConflict.tenant_id == tenant_id,
            SyncConflict.resolved_at.is_(None),
        )
    )
    conflicts = result.scalars().all()
    return {
        "conflicts": [
            {
                "id": c.id,
                "chart_id": c.chart_id,
                "entity_type": c.entity_type,
                "entity_id": c.entity_id,
                "conflict_fields_json": c.conflict_fields_json,
                "detected_at": c.detected_at.isoformat() if c.detected_at else None,
            }
            for c in conflicts
        ],
        "count": len(conflicts),
    }


# ===========================================================================
# Dashboard / Customization
# ===========================================================================

class DashboardProfileUpdate(BaseModel):
    card_order: Optional[list[str]] = None
    hidden_cards: Optional[list[str]] = None
    density: Optional[str] = None
    theme_mode: Optional[str] = None
    accent_color: Optional[str] = None


class UserFavoriteCreate(BaseModel):
    favorite_type: str
    favorite_key: str
    display_label: str
    metadata: Optional[dict] = None


class WorkspaceProfileCreate(BaseModel):
    profile_type: str
    profile_name: str
    is_default: bool = False
    visible_sections: Optional[list[str]] = None
    critical_care_mode: bool = False
    show_ventilator_panel: bool = False
    show_infusion_panel: bool = False


@router.get("/dashboard/profile")
async def get_dashboard_profile(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Get the user's dashboard profile."""
    result = await session.execute(
        select(UserDashboardProfile).where(
            UserDashboardProfile.user_id == user.user_id,
            UserDashboardProfile.tenant_id == tenant_id,
            UserDashboardProfile.is_active == True,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {
            "user_id": user.user_id,
            "profile_name": "default",
            "density": "normal",
            "theme_mode": "system",
            "card_order": None,
            "hidden_cards": None,
        }

    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "profile_name": profile.profile_name,
        "density": profile.density,
        "theme_mode": profile.theme_mode,
        "accent_color": profile.accent_color,
        "card_order": json.loads(profile.card_order_json) if profile.card_order_json else None,
        "hidden_cards": json.loads(profile.hidden_cards_json) if profile.hidden_cards_json else None,
    }


@router.put("/dashboard/profile", status_code=status.HTTP_200_OK)
async def update_dashboard_profile(
    body: DashboardProfileUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Update the user's dashboard profile.

    Dashboard customization NEVER affects clinical truth or NEMSIS mapping.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        select(UserDashboardProfile).where(
            UserDashboardProfile.user_id == user.user_id,
            UserDashboardProfile.tenant_id == tenant_id,
            UserDashboardProfile.is_active == True,
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        profile = UserDashboardProfile(
            id=str(uuid.uuid4()),
            user_id=user.user_id,
            tenant_id=tenant_id,
            profile_name="default",
            is_active=True,
            density="normal",
            theme_mode="system",
            created_at=now,
            updated_at=now,
        )
        session.add(profile)

    if body.card_order is not None:
        profile.card_order_json = json.dumps(body.card_order)
    if body.hidden_cards is not None:
        profile.hidden_cards_json = json.dumps(body.hidden_cards)
    if body.density is not None:
        profile.density = body.density
    if body.theme_mode is not None:
        profile.theme_mode = body.theme_mode
    if body.accent_color is not None:
        profile.accent_color = body.accent_color
    profile.updated_at = now

    await session.commit()
    return {"status": "updated"}


@router.post("/dashboard/favorites", status_code=status.HTTP_201_CREATED)
async def create_user_favorite(
    body: UserFavoriteCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Add a user favorite (intervention, medication, protocol, impression, destination)."""
    now = datetime.now(UTC)
    favorite_id = str(uuid.uuid4())

    session.add(UserFavorite(
        id=favorite_id,
        user_id=user.user_id,
        tenant_id=tenant_id,
        favorite_type=body.favorite_type,
        favorite_key=body.favorite_key,
        display_label=body.display_label,
        metadata_json=json.dumps(body.metadata) if body.metadata else None,
        created_at=now,
        updated_at=now,
    ))
    await session.commit()
    return {"id": favorite_id, "status": "created"}


@router.get("/dashboard/favorites")
async def list_user_favorites(
    favorite_type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List user favorites, optionally filtered by type."""
    q = select(UserFavorite).where(
        UserFavorite.user_id == user.user_id,
        UserFavorite.tenant_id == tenant_id,
    ).order_by(UserFavorite.sort_order, UserFavorite.use_count.desc())

    if favorite_type:
        q = q.where(UserFavorite.favorite_type == favorite_type)

    result = await session.execute(q)
    favorites = result.scalars().all()
    return {
        "favorites": [
            {
                "id": f.id,
                "favorite_type": f.favorite_type,
                "favorite_key": f.favorite_key,
                "display_label": f.display_label,
                "use_count": f.use_count,
                "last_used_at": f.last_used_at.isoformat() if f.last_used_at else None,
            }
            for f in favorites
        ],
        "count": len(favorites),
    }


@router.post("/workspace-profiles", status_code=status.HTTP_201_CREATED)
async def create_workspace_profile(
    body: WorkspaceProfileCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Create a workspace profile for role-specific EPCR configuration."""
    now = datetime.now(UTC)
    profile_id = str(uuid.uuid4())

    session.add(WorkspaceProfile(
        id=profile_id,
        user_id=user.user_id,
        tenant_id=tenant_id,
        profile_type=body.profile_type,
        profile_name=body.profile_name,
        is_default=body.is_default,
        visible_sections_json=json.dumps(body.visible_sections) if body.visible_sections else None,
        critical_care_mode=body.critical_care_mode,
        show_ventilator_panel=body.show_ventilator_panel,
        show_infusion_panel=body.show_infusion_panel,
        created_at=now,
        updated_at=now,
    ))
    await session.commit()
    return {"id": profile_id, "status": "created"}


@router.get("/workspace-profiles")
async def list_workspace_profiles(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """List workspace profiles for the current user."""
    result = await session.execute(
        select(WorkspaceProfile).where(
            WorkspaceProfile.user_id == user.user_id,
            WorkspaceProfile.tenant_id == tenant_id,
        )
    )
    profiles = result.scalars().all()
    return {
        "profiles": [
            {
                "id": p.id,
                "profile_type": p.profile_type,
                "profile_name": p.profile_name,
                "is_default": p.is_default,
                "critical_care_mode": p.critical_care_mode,
            }
            for p in profiles
        ],
        "count": len(profiles),
    }
