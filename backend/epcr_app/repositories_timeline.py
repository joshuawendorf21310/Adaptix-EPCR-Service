"""Patient state timeline repository.

Provides append-only data access for patient state progression tracking.
No updates or deletes - immutable audit log only.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from epcr_app.models_timeline import PatientStateTimeline


class PatientStateTimelineRepository:
    """Repository for patient state timeline persistence."""

    def __init__(self, db: Session):
        self.db = db

    def append_state_transition(
        self,
        *,
        tenant_id: str,
        incident_id: str,
        patient_id: str | None,
        state_name: str,
        prior_state: str | None = None,
        changed_by: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PatientStateTimeline:
        """Append a new state transition to the timeline.

        This is an append-only operation. No updates or deletes allowed.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Optional patient UUID
            state_name: Name of the new state
            prior_state: Optional previous state
            changed_by: Optional user UUID who triggered the change
            entity_type: Optional entity type (vital, intervention, etc.)
            entity_id: Optional entity UUID
            metadata: Optional metadata dictionary

        Returns:
            Persisted PatientStateTimeline instance
        """
        entry = PatientStateTimeline(
            id=str(uuid4()),
            tenant_id=tenant_id,
            incident_id=incident_id,
            patient_id=patient_id,
            state_name=state_name,
            prior_state=prior_state,
            changed_by=changed_by,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(metadata) if metadata else None,
            changed_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def get_timeline(
        self, *, tenant_id: str, incident_id: str, patient_id: str | None = None
    ) -> list[PatientStateTimeline]:
        """Get the complete state timeline for an incident or patient.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            patient_id: Optional patient UUID to filter by

        Returns:
            List of timeline entries ordered by changed_at ascending
        """
        stmt = select(PatientStateTimeline).where(
            PatientStateTimeline.tenant_id == tenant_id,
            PatientStateTimeline.incident_id == incident_id,
        )

        if patient_id:
            stmt = stmt.where(PatientStateTimeline.patient_id == patient_id)

        stmt = stmt.order_by(PatientStateTimeline.changed_at.asc())

        return list(self.db.execute(stmt).scalars().all())

    def get_timeline_by_entity(
        self, *, tenant_id: str, entity_type: str, entity_id: str
    ) -> list[PatientStateTimeline]:
        """Get timeline entries for a specific entity.

        Args:
            tenant_id: Tenant UUID
            entity_type: Entity type (vital, intervention, etc.)
            entity_id: Entity UUID

        Returns:
            List of timeline entries ordered by changed_at ascending
        """
        stmt = (
            select(PatientStateTimeline)
            .where(
                PatientStateTimeline.tenant_id == tenant_id,
                PatientStateTimeline.entity_type == entity_type,
                PatientStateTimeline.entity_id == entity_id,
            )
            .order_by(PatientStateTimeline.changed_at.asc())
        )

        return list(self.db.execute(stmt).scalars().all())

    def get_recent_transitions(
        self, *, tenant_id: str, incident_id: str, limit: int = 20
    ) -> list[PatientStateTimeline]:
        """Get the most recent state transitions for an incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID
            limit: Maximum number of entries to return

        Returns:
            List of timeline entries ordered by changed_at descending
        """
        stmt = (
            select(PatientStateTimeline)
            .where(
                PatientStateTimeline.tenant_id == tenant_id,
                PatientStateTimeline.incident_id == incident_id,
            )
            .order_by(PatientStateTimeline.changed_at.desc())
            .limit(limit)
        )

        return list(self.db.execute(stmt).scalars().all())

    def get_state_count(self, *, tenant_id: str, incident_id: str) -> int:
        """Get the total count of state transitions for an incident.

        Args:
            tenant_id: Tenant UUID
            incident_id: Incident/chart UUID

        Returns:
            Count of timeline entries
        """
        stmt = select(PatientStateTimeline).where(
            PatientStateTimeline.tenant_id == tenant_id,
            PatientStateTimeline.incident_id == incident_id,
        )
        return len(list(self.db.execute(stmt).scalars().all()))
