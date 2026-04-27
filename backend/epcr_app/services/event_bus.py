"""Core-backed event publisher for EPCR service domain events."""

import logging
import os
import uuid
from typing import Any, Callable

import httpx

from adaptix_contracts.event_contracts import (
    EventSchema,
    EventValidator,
    LocalEventConsumerRegistry,
)

logger = logging.getLogger(__name__)

event_registry = LocalEventConsumerRegistry()


class EventPublishConfigurationError(RuntimeError):
    """Raised when the production event bus is not configured."""


class EventPublishError(RuntimeError):
    """Raised when Core rejects or cannot persist an event."""


async def publish_event(event: EventSchema) -> str:
    """Publish an event to Core's durable event bus.

    The call fails closed when Core event bus configuration is absent. Local
    in-process handlers are intentionally not used as a delivery substitute.
    """
    validator = EventValidator()
    validator.validate_event(event)
    payload_tenant_id = event.payload.get("tenant_id")
    if payload_tenant_id is not None and str(payload_tenant_id) != str(event.metadata.tenant_id):
        raise ValueError("Payload tenant_id must match event metadata tenant_id")

    core_url = os.getenv("CORE_EVENT_BUS_URL", "").rstrip("/")
    token = os.getenv("CORE_EVENT_BUS_TOKEN", "") or os.getenv("CORE_PROVISIONING_TOKEN", "")
    if not core_url or not token:
        raise EventPublishConfigurationError(
            "CORE_EVENT_BUS_URL and CORE_EVENT_BUS_TOKEN must be configured for event publishing"
        )

    correlation_id = event.metadata.correlation_id or str(uuid.uuid4())
    body = {
        "tenant_id": event.metadata.tenant_id,
        "event_type": event.event_type,
        "source_domain": event.metadata.source_service,
        "payload": event.payload,
        "correlation_id": correlation_id,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": correlation_id,
    }
    attempts = max(1, int(os.getenv("CORE_EVENT_BUS_RETRIES", "3")))
    timeout = float(os.getenv("CORE_EVENT_BUS_TIMEOUT_SECONDS", "5"))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{core_url}/api/core/internal/events", json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            event_id = data.get("id")
            if not event_id:
                raise EventPublishError("Core event bus response did not include an event id")
            logger.info("Published event %s to Core id=%s tenant=%s", event.event_type, event_id, event.metadata.tenant_id)
            return str(event_id)
        except (httpx.HTTPError, ValueError, EventPublishError) as exc:
            last_error = exc
            logger.warning("Event publish attempt %s/%s failed: %s", attempt, attempts, exc)
    raise EventPublishError(f"Failed to publish event after {attempts} attempts: {last_error}") from last_error


async def _process_event_locally(event: EventSchema) -> None:
    """Reject local event processing as a cross-service delivery substitute."""
    raise EventPublishConfigurationError("Local event processing is not valid cross-service delivery")


async def register_event_handler(
    event_type: str, handler: Callable[[EventSchema], Any]
) -> None:
    """Register a handler for a specific event type.
    
    Args:
        event_type: The type of event to handle.
        handler: The function to call when an event of this type is received.
    """
    event_registry.register(event_type, handler)


async def unregister_event_handler(event_type: str, handler: Callable[[EventSchema], Any]) -> None:
    """Unregister a handler for a specific event type.
    
    Args:
        event_type: The type of event to stop handling.
        handler: The handler to unregister.
    """
    event_registry.unregister(event_type, handler)