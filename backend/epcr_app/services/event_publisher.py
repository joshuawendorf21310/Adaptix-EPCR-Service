"""Event publisher service for EPCR events.

Contains functions for publishing EPCR-related events to the event bus.
"""
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from adaptix_contracts.event_contracts import EventSchema, EventMetadata
from epcr_app.services.event_bus import publish_event
from epcr_app.models import Chart


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EpcrEventPublisher:
    """Event publisher for EPCR-related events.
    
    Provides methods for publishing standardized EPCR events to the event bus.
    """
    @staticmethod
    def build_chart_created_event(
        tenant_id: str,
        chart_id: str,
        chart_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> EventSchema:
        """Build an epcr.chart.created event payload."""
        return EventSchema(
            event_type="epcr.chart.created",
            metadata=EventMetadata(
                tenant_id=tenant_id,
                timestamp=_utc_now_iso(),
                source_service="epcr",
                correlation_id=correlation_id or str(uuid.uuid4()),
            ),
            payload={
                "chart_id": chart_id,
                "tenant_id": tenant_id,
                **chart_data,
            },
        )

    @staticmethod
    async def publish_chart_created(
        tenant_id: str,
        chart_id: str,
        chart_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event when an EPCR chart is created.
        
        Args:
            tenant_id: The ID of the tenant.
            chart_id: The ID of the created chart.
            chart_data: The data of the created chart.
            correlation_id: Optional correlation ID for event tracking.
            
        Returns:
            The ID of the published event.
        """
        event = EpcrEventPublisher.build_chart_created_event(
            tenant_id=tenant_id,
            chart_id=chart_id,
            chart_data=chart_data,
            correlation_id=correlation_id,
        )
        return await publish_event(event)
    
    @staticmethod
    async def publish_chart_updated(
        tenant_id: str,
        chart_id: str,
        chart_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event when an EPCR chart is updated.
        
        Args:
            tenant_id: The ID of the tenant.
            chart_id: The ID of the updated chart.
            chart_data: The data of the updated chart.
            correlation_id: Optional correlation ID for event tracking.
            
        Returns:
            The ID of the published event.
        """
        event = EventSchema(
            event_type="epcr.chart.updated",
            metadata=EventMetadata(
                tenant_id=tenant_id,
                timestamp=_utc_now_iso(),
                source_service="epcr",
                correlation_id=correlation_id or str(uuid.uuid4()),
            ),
            payload={
                "chart_id": chart_id,
                "tenant_id": tenant_id,
                **chart_data,
            },
        )
        
        return await publish_event(event)
    
    @staticmethod
    async def publish_chart_finalized(
        tenant_id: str,
        chart_id: str,
        chart_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event when an EPCR chart is finalized.
        
        Args:
            tenant_id: The ID of the tenant.
            chart_id: The ID of the finalized chart.
            chart_data: The data of the finalized chart.
            correlation_id: Optional correlation ID for event tracking.
            
        Returns:
            The ID of the published event.
        """
        event = EventSchema(
            event_type="epcr.chart.finalized",
            metadata=EventMetadata(
                tenant_id=tenant_id,
                timestamp=_utc_now_iso(),
                source_service="epcr",
                correlation_id=correlation_id or str(uuid.uuid4()),
            ),
            payload={
                "chart_id": chart_id,
                "tenant_id": tenant_id,
                **chart_data,
            },
        )
        
        return await publish_event(event)

    @staticmethod
    async def publish_chart_from_model(
        chart: Chart,
        event_type: str,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event from a Chart model instance.
        
        Args:
            chart: The Chart model instance.
            event_type: The type of event to publish.
            correlation_id: Optional correlation ID for event tracking.
            
        Returns:
            The ID of the published event.
        """
        # Create a dictionary representation of the chart with important fields
        chart_data = {
            "chart_id": chart.id,
            "tenant_id": chart.tenant_id,
            "call_number": chart.call_number,
            "incident_type": chart.incident_type,
            "status": str(chart.status),
            "created_at": chart.created_at.isoformat() if chart.created_at else None,
            "updated_at": chart.updated_at.isoformat() if chart.updated_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None,
            "version": chart.version,
        }
        
        # Add patient information if available
        if hasattr(chart, 'patient_profile') and chart.patient_profile:
            chart_data["patient_info"] = {
                "first_name": chart.patient_profile.first_name,
                "last_name": chart.patient_profile.last_name,
                "date_of_birth": chart.patient_profile.date_of_birth,
            }
            
        event = EventSchema(
            event_type=event_type,
            metadata=EventMetadata(
                tenant_id=chart.tenant_id,
                timestamp=_utc_now_iso(),
                source_service="epcr",
                correlation_id=correlation_id or str(uuid.uuid4()),
            ),
            payload=chart_data,
        )
        
        return await publish_event(event)