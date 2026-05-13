"""Model-level tests for :class:`EpcrMapLocationContext`.

Verifies the row round-trips through the ORM with the documented column
shape (including Numeric precision for lat/lng/accuracy, the boolean
``reverse_geocoded`` flag, optional ``facility_type``, and timestamps).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

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
    EpcrMapLocationContext,
)


@pytest_asyncio.fixture
async def db_session():
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


async def test_insert_and_query_back(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrMapLocationContext(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        kind="scene",
        address_text=None,
        latitude=Decimal("47.606200"),
        longitude=Decimal("-122.332100"),
        accuracy_meters=Decimal("5.50"),
        reverse_geocoded=False,
        facility_type=None,
        distance_meters=None,
        captured_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrMapLocationContext).where(
                EpcrMapLocationContext.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.kind == "scene"
    assert float(fetched.latitude) == pytest.approx(47.606200)
    assert float(fetched.longitude) == pytest.approx(-122.332100)
    assert float(fetched.accuracy_meters) == pytest.approx(5.5)
    assert fetched.reverse_geocoded is False
    assert fetched.address_text is None
    assert fetched.facility_type is None
    assert fetched.captured_at is not None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_destination_with_facility_type_round_trips(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrMapLocationContext(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        kind="destination",
        address_text="Harborview Medical Center, 325 9th Ave, Seattle WA",
        latitude=Decimal("47.603100"),
        longitude=Decimal("-122.323300"),
        accuracy_meters=None,
        reverse_geocoded=True,
        facility_type="trauma_center",
        distance_meters=Decimal("1234.56"),
        captured_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrMapLocationContext).where(
                EpcrMapLocationContext.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.kind == "destination"
    assert fetched.facility_type == "trauma_center"
    assert fetched.reverse_geocoded is True
    assert fetched.address_text.startswith("Harborview")
    assert float(fetched.distance_meters) == pytest.approx(1234.56)
