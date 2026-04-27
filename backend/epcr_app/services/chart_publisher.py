"""Event publisher service for EPCR chart events.

Contains functions for publishing chart-related events to the event bus.
"""
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from adaptix_contracts.event_contracts import EventSchema, EventMetadata
from epcr_app.services.event_bus import publish_event


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_chart_finalized_event(
    tenant_id: str,
    chart_id: str,
    chart_data: Dict[str, Any],
    finalized_by: str,
    correlation_id: Optional[str] = None,
) -> EventSchema:
    """Build a validated chart-finalized event payload."""
    return EventSchema(
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
            "finalized_by": finalized_by,
            "finalized_at": _utc_now_iso(),
            **chart_data,
        },
    )


async def publish_chart_created(
    tenant_id: str,
    chart_id: str,
    chart_data: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is created.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the created chart.
        chart_data: The data of the created chart.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
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
    
    return await publish_event(event)


async def publish_chart_updated(
    tenant_id: str,
    chart_id: str,
    chart_data: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is updated.
    
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


async def publish_chart_finalized(
    tenant_id: str,
    chart_id: str,
    chart_data: Dict[str, Any],
    finalized_by: str,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is finalized.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the finalized chart.
        chart_data: The data of the finalized chart.
        finalized_by: The ID of the user who finalized the chart.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = build_chart_finalized_event(
        tenant_id=tenant_id,
        chart_id=chart_id,
        chart_data=chart_data,
        finalized_by=finalized_by,
        correlation_id=correlation_id,
    )
    return await publish_event(event)


async def publish_chart_signed(
    tenant_id: str,
    chart_id: str,
    signer_id: str,
    signer_name: str,
    signature_type: str,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is signed.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the signed chart.
        signer_id: The ID of the user who signed the chart.
        signer_name: The name of the user who signed the chart.
        signature_type: The type of signature (e.g., "patient", "provider").
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
        event_type="epcr.chart.signed",
        metadata=EventMetadata(
            tenant_id=tenant_id,
            timestamp=_utc_now_iso(),
            source_service="epcr",
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload={
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "signer_id": signer_id,
            "signer_name": signer_name,
            "signature_type": signature_type,
            "signed_at": _utc_now_iso(),
        },
    )
    
    return await publish_event(event)


async def publish_chart_locked(
    tenant_id: str,
    chart_id: str,
    locked_by: str,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is locked for editing.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the locked chart.
        locked_by: The ID of the user who locked the chart.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
        event_type="epcr.chart.locked",
        metadata=EventMetadata(
            tenant_id=tenant_id,
            timestamp=_utc_now_iso(),
            source_service="epcr",
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload={
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "locked_by": locked_by,
            "locked_at": _utc_now_iso(),
        },
    )
    
    return await publish_event(event)


async def publish_chart_unlocked(
    tenant_id: str,
    chart_id: str,
    unlocked_by: str,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when a chart is unlocked for editing.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the unlocked chart.
        unlocked_by: The ID of the user who unlocked the chart.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
        event_type="epcr.chart.unlocked",
        metadata=EventMetadata(
            tenant_id=tenant_id,
            timestamp=_utc_now_iso(),
            source_service="epcr",
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload={
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "unlocked_by": unlocked_by,
            "unlocked_at": _utc_now_iso(),
        },
    )
    
    return await publish_event(event)


async def publish_nemsis_validation_completed(
    tenant_id: str,
    chart_id: str,
    is_valid: bool,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when NEMSIS validation is completed for a chart.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the validated chart.
        is_valid: Whether the chart passed NEMSIS validation.
        validation_errors: List of validation errors if the chart failed validation.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
        event_type="epcr.chart.nemsis_validation_completed",
        metadata=EventMetadata(
            tenant_id=tenant_id,
            timestamp=_utc_now_iso(),
            source_service="epcr",
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload={
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "is_valid": is_valid,
            "validation_errors": validation_errors or [],
            "validated_at": _utc_now_iso(),
        },
    )
    
    return await publish_event(event)


async def publish_nemsis_export_completed(
    tenant_id: str,
    chart_id: str,
    export_id: str,
    export_status: str,
    export_url: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """Publish an event when NEMSIS export is completed for a chart.
    
    Args:
        tenant_id: The ID of the tenant.
        chart_id: The ID of the exported chart.
        export_id: The ID of the export.
        export_status: The status of the export (e.g., "success", "failure").
        export_url: Optional URL to download the export.
        correlation_id: Optional correlation ID for event tracking.
        
    Returns:
        The ID of the published event.
    """
    event = EventSchema(
        event_type="epcr.chart.nemsis_export_completed",
        metadata=EventMetadata(
            tenant_id=tenant_id,
            timestamp=_utc_now_iso(),
            source_service="epcr",
            correlation_id=correlation_id or str(uuid.uuid4()),
        ),
        payload={
            "chart_id": chart_id,
            "tenant_id": tenant_id,
            "export_id": export_id,
            "export_status": export_status,
            "export_url": export_url,
            "exported_at": _utc_now_iso(),
        },
    )
    
    return await publish_event(event)