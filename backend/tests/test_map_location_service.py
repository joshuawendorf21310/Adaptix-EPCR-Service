"""Service-level tests for :class:`MapLocationService`.

Covers the canonical flow:

- ``record_location`` persists a row and writes a
  ``map_location.recorded`` audit entry.
- With ``MAPBOX_TOKEN`` unset, the persisted row honestly reports
  ``reverse_geocoded=False`` and ``address_text=None``.
- ``list_for_chart`` returns the recorded rows in capture order.
- The Mapbox reverse-geocode HTTP boundary is exercised via
  :class:`httpx.MockTransport`, which keeps the production code path
  under test (real ``httpx.AsyncClient`` machinery).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrAuditLog,
    EpcrMapLocationContext,
)
from epcr_app.services.map_location_service import (
    MapLocationService,
    build_client,
)


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


async def test_record_location_persists_and_audits_without_token(
    db_setup, monkeypatch
) -> None:
    # Real env clear: ensure MAPBOX_TOKEN is unset for this test
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    session, chart = db_setup
    result = await MapLocationService.record_location(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        kind="scene",
        lat=47.6062,
        lng=-122.3321,
        accuracy=5.5,
        captured_at="2026-05-12T10:00:00Z",
        user_id="user-1",
    )
    await session.commit()

    assert result["kind"] == "scene"
    assert result["reverseGeocoded"] is False
    assert result["addressText"] is None

    rows = (
        await session.execute(
            select(EpcrMapLocationContext).where(
                EpcrMapLocationContext.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].reverse_geocoded is False
    assert rows[0].address_text is None
    assert float(rows[0].latitude) == pytest.approx(47.6062)

    audits = (
        await session.execute(
            select(EpcrAuditLog).where(
                EpcrAuditLog.chart_id == chart.id,
                EpcrAuditLog.action == "map_location.recorded",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    detail = json.loads(audits[0].detail_json)
    assert detail["kind"] == "scene"
    assert detail["reverse_geocoded"] is False


async def test_list_for_chart_returns_recorded_rows_in_order(
    db_setup, monkeypatch
) -> None:
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    session, chart = db_setup
    await MapLocationService.record_location(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        kind="scene",
        lat=47.6,
        lng=-122.33,
        accuracy=None,
        captured_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=UTC),
        user_id="user-1",
    )
    await MapLocationService.record_location(
        session,
        tenant_id="t1",
        chart_id=chart.id,
        kind="destination",
        lat=47.61,
        lng=-122.32,
        accuracy=None,
        captured_at=datetime(2026, 5, 12, 10, 15, 0, tzinfo=UTC),
        user_id="user-1",
    )
    await session.commit()

    listed = await MapLocationService.list_for_chart(
        session, tenant_id="t1", chart_id=chart.id
    )
    assert [r["kind"] for r in listed] == ["scene", "destination"]
    # tenant scoping: other tenant returns nothing
    other = await MapLocationService.list_for_chart(
        session, tenant_id="t2", chart_id=chart.id
    )
    assert other == []


async def test_reverse_geocode_via_mock_transport_marks_row(
    db_setup, monkeypatch
) -> None:
    """Exercise the real Mapbox geocode HTTP path with httpx.MockTransport.

    This deliberately tests the production reverse-geocode flow (not a
    fake) by injecting a transport that satisfies the actual Mapbox
    geocoding API contract and verifying the service marks the row as
    ``reverse_geocoded=True`` with the returned ``place_name``.
    """
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token-not-real")

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "/geocoding/v5/mapbox.places/" in request.url.path
        assert request.url.params.get("access_token") == "test-token-not-real"
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "place_name": (
                            "1234 Pine St, Seattle, Washington 98101, "
                            "United States"
                        )
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = build_client(transport=transport)
    try:
        session, chart = db_setup
        result = await MapLocationService.record_location(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            kind="scene",
            lat=47.6062,
            lng=-122.3321,
            accuracy=None,
            captured_at="2026-05-12T10:00:00Z",
            user_id="user-1",
            http_client=client,
        )
        await session.commit()
    finally:
        await client.aclose()

    assert len(calls) == 1
    assert result["reverseGeocoded"] is True
    assert result["addressText"].startswith("1234 Pine St")


async def test_reverse_geocode_http_failure_records_row_honestly(
    db_setup, monkeypatch
) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token-not-real")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = build_client(transport=transport)
    try:
        session, chart = db_setup
        result = await MapLocationService.record_location(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            kind="scene",
            lat=47.6062,
            lng=-122.3321,
            accuracy=None,
            captured_at="2026-05-12T10:00:00Z",
            user_id="user-1",
            http_client=client,
        )
        await session.commit()
    finally:
        await client.aclose()

    # Row durable, but honestly marked as not reverse-geocoded
    assert result["reverseGeocoded"] is False
    assert result["addressText"] is None


async def test_invalid_kind_rejected(db_setup, monkeypatch) -> None:
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    session, chart = db_setup
    with pytest.raises(ValueError):
        await MapLocationService.record_location(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            kind="not_a_real_kind",
            lat=47.0,
            lng=-122.0,
            accuracy=None,
            captured_at="2026-05-12T10:00:00Z",
        )


async def test_invalid_facility_type_rejected(db_setup, monkeypatch) -> None:
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    session, chart = db_setup
    with pytest.raises(ValueError):
        await MapLocationService.record_location(
            session,
            tenant_id="t1",
            chart_id=chart.id,
            kind="destination",
            lat=47.0,
            lng=-122.0,
            accuracy=None,
            captured_at="2026-05-12T10:00:00Z",
            facility_type="hospital_general",  # not in canonical set
        )
