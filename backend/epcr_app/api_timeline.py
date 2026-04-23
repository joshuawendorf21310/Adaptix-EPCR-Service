"""Patient state timeline API routes.

Provides endpoints for retrieving patient care state progression
timeline for audit, compliance, and temporal analysis.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user, CurrentUser
from epcr_app.services_timeline import PatientStateTimelineService

router = APIRouter(prefix="/timeline", tags=["timeline"])


class TimelineEntryResponse(BaseModel):
    """Timeline entry response."""

    id: str
    tenant_id: str
    incident_id: str
    patient_id: str | None
    state_name: str
    prior_state: str | None
    changed_by: str | None
    entity_type: str | None
    entity_id: str | None
    metadata_json: str | None
    changed_at: str
    created_at: str


class TimelineResponse(BaseModel):
    """Timeline response."""

    incident_id: str
    patient_id: str | None
    total_entries: int
    entries: list[TimelineEntryResponse]


@router.get("/incident/{incident_id}", response_model=TimelineResponse)
def get_incident_timeline(
    incident_id: str,
    patient_id: str | None = None,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> TimelineResponse:
    """Get full state timeline for an incident or patient.

    Returns the complete immutable state progression log for the
    specified incident. Optionally filter by patient_id.

    Args:
        incident_id: Incident/chart UUID
        patient_id: Optional patient UUID to filter by
        db: Database session
        current_user: Current authenticated user
        tenant_id: Current tenant ID

    Returns:
        Full timeline with all state transitions
    """
    service = PatientStateTimelineService(db)

    entries = service.get_timeline(
        tenant_id=str(current_user.tenant_id), incident_id=incident_id, patient_id=patient_id
    )

    timeline_entries = [
        TimelineEntryResponse(
            id=e.id,
            tenant_id=e.tenant_id,
            incident_id=e.incident_id,
            patient_id=e.patient_id,
            state_name=e.state_name,
            prior_state=e.prior_state,
            changed_by=e.changed_by,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            metadata_json=e.metadata_json,
            changed_at=e.changed_at.isoformat(),
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]

    return TimelineResponse(
        incident_id=incident_id,
        patient_id=patient_id,
        total_entries=len(timeline_entries),
        entries=timeline_entries,
    )


@router.get("/incident/{incident_id}/patient/{patient_id}", response_model=TimelineResponse)
def get_patient_timeline(
    incident_id: str,
    patient_id: str,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> TimelineResponse:
    """Get state timeline for a specific patient.

    Returns all state transitions for the specified patient within
    the incident context.

    Args:
        incident_id: Incident/chart UUID
        patient_id: Patient UUID
        db: Database session
        current_user: Current authenticated user
        tenant_id: Current tenant ID

    Returns:
        Patient-specific timeline
    """
    service = PatientStateTimelineService(db)

    entries = service.get_timeline(
        tenant_id=str(current_user.tenant_id), incident_id=incident_id, patient_id=patient_id
    )

    timeline_entries = [
        TimelineEntryResponse(
            id=e.id,
            tenant_id=e.tenant_id,
            incident_id=e.incident_id,
            patient_id=e.patient_id,
            state_name=e.state_name,
            prior_state=e.prior_state,
            changed_by=e.changed_by,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            metadata_json=e.metadata_json,
            changed_at=e.changed_at.isoformat(),
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]

    return TimelineResponse(
        incident_id=incident_id,
        patient_id=patient_id,
        total_entries=len(timeline_entries),
        entries=timeline_entries,
    )


@router.get("/incident/{incident_id}/recent", response_model=TimelineResponse)
def get_recent_timeline(
    incident_id: str,
    limit: int = 20,
    db: Session = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> TimelineResponse:
    """Get recent state transitions for an incident.

    Returns the most recent state transitions, useful for displaying
    recent activity or real-time updates.

    Args:
        incident_id: Incident/chart UUID
        limit: Maximum number of entries to return (default 20)
        db: Database session
        current_user: Current authenticated user
        tenant_id: Current tenant ID

    Returns:
        Recent timeline entries
    """
    service = PatientStateTimelineService(db)

    entries = service.get_recent_transitions(
        tenant_id=str(current_user.tenant_id), incident_id=incident_id, limit=limit
    )

    timeline_entries = [
        TimelineEntryResponse(
            id=e.id,
            tenant_id=e.tenant_id,
            incident_id=e.incident_id,
            patient_id=e.patient_id,
            state_name=e.state_name,
            prior_state=e.prior_state,
            changed_by=e.changed_by,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            metadata_json=e.metadata_json,
            changed_at=e.changed_at.isoformat(),
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]

    return TimelineResponse(
        incident_id=incident_id,
        patient_id=None,
        total_entries=len(timeline_entries),
        entries=timeline_entries,
    )
