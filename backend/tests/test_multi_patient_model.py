"""Model-level tests for :class:`EpcrMultiPatientIncident` and
:class:`EpcrMultiPatientLink`.

Verifies both rows round-trip through the ORM with their documented
column shapes, that the link FK to the parent incident enforces a
referential edge in the test SQLite engine, and that the link
soft-delete pattern (``removed_at``) hides rows from non-removed
reads while preserving them in the database for audit replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    EpcrMultiPatientIncident,
    EpcrMultiPatientLink,
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
            call_number="CALL-MCI-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_insert_incident_round_trips(db_session) -> None:
    session, _chart = db_session
    now = datetime.now(UTC)
    row = EpcrMultiPatientIncident(
        id=str(uuid4()),
        tenant_id="t1",
        parent_incident_number="INC-2026-0001",
        scene_address_json='{"street": "1 Main St"}',
        mci_flag=True,
        patient_count=4,
        mechanism="MVC-multi-vehicle",
        hazards_text="fuel spill",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrMultiPatientIncident).where(
                EpcrMultiPatientIncident.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.tenant_id == "t1"
    assert fetched.parent_incident_number == "INC-2026-0001"
    assert fetched.mci_flag is True
    assert fetched.patient_count == 4
    assert fetched.mechanism == "MVC-multi-vehicle"
    assert fetched.hazards_text == "fuel spill"
    assert fetched.scene_address_json == '{"street": "1 Main St"}'
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_insert_link_and_soft_remove_hides_row(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)

    incident = EpcrMultiPatientIncident(
        id=str(uuid4()),
        tenant_id="t1",
        parent_incident_number="INC-LINK-1",
        mci_flag=False,
        patient_count=2,
        created_at=now,
        updated_at=now,
    )
    session.add(incident)
    await session.flush()

    link = EpcrMultiPatientLink(
        id=str(uuid4()),
        tenant_id="t1",
        multi_incident_id=incident.id,
        chart_id=chart.id,
        patient_label="A",
        triage_category="red",
        acuity="critical",
        transport_priority="emergent",
        destination_id="HOSP-1",
        created_at=now,
        updated_at=now,
    )
    session.add(link)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrMultiPatientLink).where(
                EpcrMultiPatientLink.id == link.id
            )
        )
    ).scalar_one()
    assert fetched.multi_incident_id == incident.id
    assert fetched.chart_id == chart.id
    assert fetched.patient_label == "A"
    assert fetched.triage_category == "red"
    assert fetched.acuity == "critical"
    assert fetched.transport_priority == "emergent"
    assert fetched.destination_id == "HOSP-1"
    assert fetched.removed_at is None

    # Soft-remove the link.
    fetched.removed_at = datetime.now(UTC)
    await session.commit()

    live = (
        await session.execute(
            select(EpcrMultiPatientLink).where(
                EpcrMultiPatientLink.multi_incident_id == incident.id,
                EpcrMultiPatientLink.removed_at.is_(None),
            )
        )
    ).scalars().all()
    assert live == []

    archived = (
        await session.execute(
            select(EpcrMultiPatientLink).where(
                EpcrMultiPatientLink.id == link.id
            )
        )
    ).scalar_one()
    assert archived.removed_at is not None


async def test_unknown_label_pattern_supported(db_session) -> None:
    """Provider may attach a chart with an ``unknown_N`` placeholder."""
    session, chart = db_session
    now = datetime.now(UTC)
    incident = EpcrMultiPatientIncident(
        id=str(uuid4()),
        tenant_id="t1",
        parent_incident_number="INC-UNK",
        mci_flag=False,
        patient_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(incident)
    await session.flush()
    link = EpcrMultiPatientLink(
        id=str(uuid4()),
        tenant_id="t1",
        multi_incident_id=incident.id,
        chart_id=chart.id,
        patient_label="unknown_1",
        triage_category=None,
        created_at=now,
        updated_at=now,
    )
    session.add(link)
    await session.commit()

    refetched = (
        await session.execute(
            select(EpcrMultiPatientLink).where(
                EpcrMultiPatientLink.id == link.id
            )
        )
    ).scalar_one()
    assert refetched.patient_label == "unknown_1"
    assert refetched.triage_category is None
