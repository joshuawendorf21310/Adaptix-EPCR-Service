"""Integration between chart services and state timeline.

Provides helper functions to wire timeline recording into existing
chart lifecycle and clinical data recording workflows.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from epcr_app.services_timeline import PatientStateTimelineService


def record_chart_created_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record chart creation in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        user_id: User who created chart
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_incident_created(
            tenant_id=tenant_id,
            incident_id=incident_id,
            user_id=user_id,
            metadata=metadata,
        )
    except Exception as e:
        # Log but don't fail the primary operation
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record chart created timeline: {str(e)}")


def record_chart_status_change_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    user_id: str,
    from_status: str,
    to_status: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record chart status transition in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        user_id: User who changed status
        from_status: Previous status
        to_status: New status
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_incident_status_change(
            tenant_id=tenant_id,
            incident_id=incident_id,
            user_id=user_id,
            from_status=from_status,
            to_status=to_status,
            metadata=metadata,
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record status change timeline: {str(e)}")


def record_patient_added_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    patient_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record patient added in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        patient_id: Patient UUID
        user_id: User who added patient
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_patient_added(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            user_id=user_id,
            metadata=metadata,
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record patient added timeline: {str(e)}")


def record_vitals_recorded_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    patient_id: str,
    vital_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record vitals captured in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        patient_id: Patient UUID
        vital_id: Vital record UUID
        user_id: User who recorded vitals
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_vitals_recorded(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            vital_id=vital_id,
            user_id=user_id,
            metadata=metadata,
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record vitals timeline: {str(e)}")


def record_intervention_performed_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    patient_id: str,
    intervention_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record intervention performed in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        patient_id: Patient UUID
        intervention_id: Intervention record UUID
        user_id: User who performed intervention
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_intervention_performed(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            intervention_id=intervention_id,
            user_id=user_id,
            metadata=metadata,
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record intervention timeline: {str(e)}")


def record_chart_locked_timeline(
    db: Session,
    *,
    tenant_id: str,
    incident_id: str,
    user_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record chart locked in timeline.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        incident_id: Chart/incident UUID
        user_id: User who locked chart
        metadata: Optional metadata
    """
    try:
        service = PatientStateTimelineService(db)
        service.record_chart_locked(
            tenant_id=tenant_id,
            incident_id=incident_id,
            user_id=user_id,
            metadata=metadata,
        )
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to record chart locked timeline: {str(e)}")
