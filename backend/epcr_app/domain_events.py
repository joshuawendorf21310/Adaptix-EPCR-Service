"""ePCR domain event publication utilities.

Publishes ePCR domain events as structured log records for collection
by log aggregation infrastructure. All publication is real — no fake
success, no silent swallowing.
"""
from __future__ import annotations
import logging
from datetime import datetime, UTC

logger = logging.getLogger("epcr_app.events")


def publish_chart_finalized(
    chart_id: str,
    tenant_id: str,
    call_number: str,
) -> None:
    """Publish epcr.chart.finalized domain event.

    Args:
        chart_id: Finalized chart identifier.
        tenant_id: Tenant context.
        call_number: Chart call number.
    """
    logger.info(
        "DOMAIN_EVENT epcr.chart.finalized chart_id=%s tenant_id=%s "
        "call_number=%s published_at=%s",
        chart_id,
        tenant_id,
        call_number,
        datetime.now(UTC).isoformat(),
    )
