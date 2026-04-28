"""Fire event consumers for ePCR integration."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adaptix_contracts.schemas.fire_contracts import FireIncidentCreatedEvent

try:
    from epcr_app.models import FireIncidentLink
except ImportError:
    FireIncidentLink = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class FireIncidentEventConsumer:
    """Consumes Fire incident events and persists ePCR-side linkage truth."""

    @staticmethod
    async def on_incident_created(event: dict, session: AsyncSession) -> bool:
        """Persist a fire incident link for a ``fire.incident.created`` event."""
        payload = event.get("payload", event)
        validated_event = FireIncidentCreatedEvent.model_validate(payload)
        if validated_event.event_type != "fire.incident.created":
            raise ValueError(f"Invalid event_type: {validated_event.event_type}")

        result = await session.execute(
            select(FireIncidentLink).where(
                FireIncidentLink.tenant_id == validated_event.tenant_id,
                FireIncidentLink.fire_incident_id == validated_event.incident_id,
            )
        )
        existing_link = result.scalar_one_or_none()
        if existing_link is not None:
            logger.info(
                "epcr.fire_consumer: fire incident link already exists incident_id=%s tenant_id=%s",
                validated_event.incident_id,
                validated_event.tenant_id,
            )
            return True

        link = FireIncidentLink(
            id=str(uuid.uuid4()),
            chart_id=None,
            tenant_id=validated_event.tenant_id,
            fire_incident_id=validated_event.incident_id,
            fire_incident_number=validated_event.incident_number,
            fire_address=validated_event.address,
            fire_incident_type=validated_event.incident_type,
            link_status="pending",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(link)
        await session.commit()
        logger.info(
            "epcr.fire_consumer: fire incident link persisted incident_id=%s tenant_id=%s link_id=%s",
            validated_event.incident_id,
            validated_event.tenant_id,
            link.id,
        )
        return True