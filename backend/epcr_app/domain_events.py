"""ePCR domain event publication utilities.

Publishes ePCR domain events to Core event bus with structured payloads.
Maintains compatibility with legacy log-based event publication for
backward compatibility during transition.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, UTC

from epcr_app.services.event_publisher import EpcrEventPublisher

logger = logging.getLogger("epcr_app.events")


async def publish_chart_finalized(
    chart_id: str,
    tenant_id: str,
    call_number: str,
) -> str:
    """Publish epcr.chart.finalized domain event.

    Args:
        chart_id: Finalized chart identifier.
        tenant_id: Tenant context.
        call_number: Chart call number.
        
    Returns:
        The ID of the published event.
    """
    # Maintain backward compatibility with log-based event publication
    logger.info(
        "DOMAIN_EVENT epcr.chart.finalized chart_id=%s tenant_id=%s "
        "call_number=%s published_at=%s",
        chart_id,
        tenant_id,
        call_number,
        datetime.now(UTC).isoformat(),
    )
    
    # Use the real event publisher for cross-service communication
    chart_data = {
        "call_number": call_number,
        "finalized_at": datetime.now(UTC).isoformat(),
    }
    
    try:
        event_id = await EpcrEventPublisher.publish_chart_finalized(
            tenant_id=tenant_id,
            chart_id=chart_id,
            chart_data=chart_data,
        )
        logger.info("Published chart finalized event to Core: %s", event_id)
        return event_id
    except Exception as e:
        logger.error("Failed to publish chart finalized event: %s", e)
        raise


def publish_chart_finalized_sync(
    chart_id: str,
    tenant_id: str,
    call_number: str,
) -> None:
    """Synchronous wrapper for publish_chart_finalized.
    
    For compatibility with synchronous code paths.
    
    Args:
        chart_id: Finalized chart identifier.
        tenant_id: Tenant context.
        call_number: Chart call number.
    """
    try:
        asyncio.create_task(publish_chart_finalized(chart_id, tenant_id, call_number))
    except Exception as e:
        logger.error("Failed to create async task for chart finalized event: %s", e)
