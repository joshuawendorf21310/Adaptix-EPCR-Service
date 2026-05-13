"""Honesty-mode tests for the Mapbox ePCR location pillar.

When ``MAPBOX_TOKEN`` is not configured the service MUST behave honestly
rather than fabricating geocode/route results:

- :meth:`MapLocationService.record_location` records the row with
  ``reverse_geocoded=False`` and ``address_text=None``.
- :meth:`MapLocationService.compute_route` returns the canonical
  ``{"available": False, "reason": "MAPBOX_TOKEN not configured"}``
  shape, with no ``distance_meters`` or ``duration_seconds`` keys.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import Base, Chart, ChartStatus
from epcr_app.services.map_location_service import MapLocationService


@pytest_asyncio.fixture
async def db_setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_record_location_unavailable_path(db_setup, monkeypatch) -> None:
    # Explicit env-unset path (real environment clear, not a mock)
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    session, chart = db_setup
    result = await MapLocationService.record_location(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        kind="scene",
        lat=47.6062,
        lng=-122.3321,
        accuracy=None,
        captured_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=UTC),
        user_id="user-1",
    )
    await session.commit()

    assert result["reverseGeocoded"] is False
    assert result["addressText"] is None
    # Service never invents a facility type either
    assert result["facilityType"] is None


async def test_compute_route_unavailable_shape(monkeypatch) -> None:
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    out = await MapLocationService.compute_route(
        scene={"latitude": 47.6062, "longitude": -122.3321},
        destination={"latitude": 47.6031, "longitude": -122.3233},
    )
    assert out == {
        "available": False,
        "reason": "MAPBOX_TOKEN not configured",
    }
    assert "distance_meters" not in out
    assert "duration_seconds" not in out


async def test_empty_token_treated_as_unset(monkeypatch) -> None:
    # Whitespace-only / empty token must be treated as unset, not as
    # an authenticated request that would fabricate a result.
    monkeypatch.setenv("MAPBOX_TOKEN", "   ")
    out = await MapLocationService.compute_route(
        scene={"latitude": 47.6062, "longitude": -122.3321},
        destination={"latitude": 47.6031, "longitude": -122.3233},
    )
    assert out["available"] is False
    assert out["reason"] == "MAPBOX_TOKEN not configured"
