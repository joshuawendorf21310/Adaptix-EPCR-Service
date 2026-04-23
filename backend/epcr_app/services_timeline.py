"""Patient state timeline service.

Orchestrates state transition recording for patient care workflows.
Provides methods for tracking all significant state changes.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from epcr_app.repositories_timeline import PatientStateTimelineRepository
from epcr_app.models_timeline import PatientStateTimeline


class PatientStateTimelineService:
    """Service for patient state timeline tracking."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PatientStateTimelineRepository(db)

    def record_incident_created(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record incident creation state.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            user_id: User who created the incident
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=None,
            state_name="incident_created",
            prior_state=None,
            changed_by=user_id,
            entity_type="incident",
            entity_id=incident_id,
            metadata=metadata,
        )

    def record_incident_status_change(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        user_id: str,
        from_status: str,
        to_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record incident status transition.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            user_id: User who changed status
            from_status: Previous status
            to_status: New status
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=None,
            state_name=f"incident_status_{to_status}",
            prior_state=f"incident_status_{from_status}",
            changed_by=user_id,
            entity_type="incident",
            entity_id=incident_id,
            metadata=metadata or {"from_status": from_status, "to_status": to_status},
        )

    def record_patient_added(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        patient_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record patient added to incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Patient UUID
            user_id: User who added patient
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            state_name="patient_added",
            prior_state=None,
            changed_by=user_id,
            entity_type="patient",
            entity_id=patient_id,
            metadata=metadata,
        )

    def record_vitals_recorded(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        patient_id: str,
        vital_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record vitals captured.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Patient UUID
            vital_id: Vital record UUID
            user_id: User who recorded vitals
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            state_name="vitals_recorded",
            prior_state=None,
            changed_by=user_id,
            entity_type="vital",
            entity_id=vital_id,
            metadata=metadata,
        )

    def record_intervention_performed(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        patient_id: str,
        intervention_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record intervention performed.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Patient UUID
            intervention_id: Intervention record UUID
            user_id: User who performed intervention
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            state_name="intervention_performed",
            prior_state=None,
            changed_by=user_id,
            entity_type="intervention",
            entity_id=intervention_id,
            metadata=metadata,
        )

    def record_chart_locked(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record chart locked.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            user_id: User who locked chart
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=None,
            state_name="chart_locked",
            prior_state="chart_unlocked",
            changed_by=user_id,
            entity_type="incident",
            entity_id=incident_id,
            metadata=metadata,
        )

    def record_chart_unlocked(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record chart unlocked.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            user_id: User who unlocked chart
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=None,
            state_name="chart_unlocked",
            prior_state="chart_locked",
            changed_by=user_id,
            entity_type="incident",
            entity_id=incident_id,
            metadata=metadata,
        )

    def record_narrative_updated(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        patient_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Record narrative updated.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Patient UUID
            user_id: User who updated narrative
            metadata: Optional metadata

        Returns:
            Timeline entry
        """
        return self.repo.append_state_transition(
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            state_name="narrative_updated",
            prior_state=None,
            changed_by=user_id,
            entity_type="narrative",
            entity_id=patient_id,
            metadata=metadata,
        )

    def get_timeline(
        self, *, tenant_id: str, incident_id: str, patient_id: str | None = None
    ) -> list[PatientStateTimeline]:
        """Get full timeline for incident or patient.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Optional patient UUID

        Returns:
            List of timeline entries
        """
        return self.repo.get_timeline(
            tenant_id=tenant_id, incident_id=incident_id, patient_id=patient_id
        )

    def get_recent_transitions(
        self, *, tenant_id: str, incident_id: str, limit: int = 20
    ) -> list[PatientStateTimeline]:
        """Get recent timeline entries.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            limit: Maximum entries to return

        Returns:
            List of recent timeline entries
        """
        return self.repo.get_recent_transitions(
            tenant_id=tenant_id, incident_id=incident_id, limit=limit
        )
