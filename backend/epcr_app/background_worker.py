"""Core event bus worker for ePCR consumers."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adaptix_contracts.event_contracts import EventBusPublisherClient, LocalEventConsumerRegistry
from epcr_app.db import _get_session_maker, _require_database_url

logger = logging.getLogger(__name__)


class EventProcessingWorker:
    """Polls Core for pending events and applies registered ePCR handlers."""

    def __init__(
        self,
        event_registry: LocalEventConsumerRegistry | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        poll_interval_seconds: float = 5.0,
        batch_size: int = 10,
        max_retries: int = 3,
    ) -> None:
        self.event_registry = event_registry or LocalEventConsumerRegistry()
        self.session_factory = session_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._running = False

    async def initialize(self) -> None:
        """Initialize the domain database session factory."""
        if self.session_factory is None:
            self.session_factory = _get_session_maker(_require_database_url())

    async def run(self) -> None:
        """Run the worker loop until stopped."""
        if self.session_factory is None:
            await self.initialize()
        self._running = True
        while self._running:
            try:
                async with self.session_factory() as session:
                    await self.process_once(session)
            except Exception as exc:
                logger.error("epcr.event_worker: loop failure: %s", exc, exc_info=True)
            if self._running:
                await asyncio.sleep(self.poll_interval_seconds)

    async def stop(self) -> None:
        """Stop the worker loop."""
        self._running = False

    async def process_once(self, session: AsyncSession) -> int:
        """Process one batch and return the number of handled events."""
        events = await EventBusPublisherClient.get_pending_events_unfiltered(None, limit=self.batch_size)
        processed_count = 0
        for event in events:
            processed_count += await self._process_event(event, session)
        return processed_count

    async def _process_event(self, event: dict, session: AsyncSession) -> int:
        event_id = UUID(event["id"])
        event_type = event["event_type"]
        retry_count = int(event.get("retry_count") or 0)
        handlers = self.event_registry.get_handlers(event_type)
        if not handlers:
            logger.debug("epcr.event_worker: no local handler for event_type=%s event_id=%s", event_type, event_id)
            return 0

        try:
            for handler in handlers:
                result = await handler(event, session)
                if not result:
                    raise RuntimeError(f"Handler {handler.__qualname__} returned false")
            await EventBusPublisherClient.mark_delivered(None, event_id)
            return 1
        except Exception as exc:
            if retry_count >= self.max_retries:
                await EventBusPublisherClient.mark_failed(None, event_id, str(exc)[:500])
            logger.error("epcr.event_worker: event processing failed event_id=%s error=%s", event_id, exc, exc_info=True)
            return 0