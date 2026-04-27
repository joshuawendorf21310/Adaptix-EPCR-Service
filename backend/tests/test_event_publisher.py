"""EPCR event publisher truth tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from adaptix_contracts.event_contracts import EventMetadata, EventSchema, EventValidator
from epcr_app.services.chart_publisher import build_chart_finalized_event, publish_chart_finalized
from epcr_app.services.event_bus import EventPublishConfigurationError, publish_event


def test_chart_finalized_event_is_valid() -> None:
    tenant_id = str(uuid4())
    event = build_chart_finalized_event(
        tenant_id=tenant_id,
        chart_id=str(uuid4()),
        chart_data={"chart_number": "EPCR-EVENT-1", "patient_id": str(uuid4()), "provider_id": str(uuid4())},
        finalized_by=str(uuid4()),
        correlation_id="epcr-event-test",
    )

    EventValidator().validate_event(event)
    assert event.event_type == "epcr.chart.finalized"
    assert event.metadata.tenant_id == tenant_id
    assert event.payload["tenant_id"] == tenant_id
    assert event.metadata.correlation_id == "epcr-event-test"


@pytest.mark.asyncio
async def test_publish_rejects_tenant_mismatch() -> None:
    event = EventSchema(
        event_type="epcr.chart.finalized",
        metadata=EventMetadata(tenant_id=str(uuid4()), timestamp="2026-04-26T00:00:00Z", source_service="epcr"),
        payload={"tenant_id": str(uuid4())},
    )

    with pytest.raises(ValueError, match="tenant_id"):
        await publish_event(event)


@pytest.mark.asyncio
async def test_publish_fails_closed_when_core_bus_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORE_EVENT_BUS_URL", raising=False)
    monkeypatch.delenv("CORE_EVENT_BUS_TOKEN", raising=False)
    monkeypatch.delenv("CORE_PROVISIONING_TOKEN", raising=False)

    with pytest.raises(EventPublishConfigurationError):
        await publish_chart_finalized(
            tenant_id=str(uuid4()),
            chart_id=str(uuid4()),
            chart_data={"chart_number": "EPCR-EVENT-2", "patient_id": str(uuid4()), "provider_id": str(uuid4())},
            finalized_by=str(uuid4()),
        )