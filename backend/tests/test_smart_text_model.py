"""Model-level tests for :class:`EpcrSmartTextSuggestion`.

Verifies the row round-trips through the ORM with the documented column
shape, the provenance triple (source + confidence + compliance_state)
is preserved, and the acceptance state can transition from offered
(NULL) -> accepted (True) or rejected (False).
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
    EpcrSmartTextSuggestion,
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
            call_number="CALL-ST-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_round_trip_full_payload(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        section="narrative",
        field_key="chief_complaint",
        phrase="Patient reports chest pain radiating to left arm.",
        source="agency_library",
        confidence=Decimal("0.92"),
        compliance_state="approved",
        evidence_link_id=None,
        accepted=None,
        accepted_at=None,
        performed_by=None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.id == row.id
            )
        )
    ).scalar_one()

    assert fetched.chart_id == chart.id
    assert fetched.tenant_id == "t1"
    assert fetched.section == "narrative"
    assert fetched.field_key == "chief_complaint"
    assert fetched.phrase.startswith("Patient reports chest pain")
    assert fetched.source == "agency_library"
    assert float(fetched.confidence) == pytest.approx(0.92)
    assert fetched.compliance_state == "approved"
    assert fetched.evidence_link_id is None
    assert fetched.accepted is None
    assert fetched.accepted_at is None
    assert fetched.performed_by is None
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


async def test_acceptance_transitions(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        section="assessment",
        field_key="impression",
        phrase="Suspected ACS.",
        source="ai",
        confidence=Decimal("0.71"),
        compliance_state="pending",
        evidence_link_id="ev-1",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    # Offered -> accepted
    row.accepted = True
    row.accepted_at = datetime.now(UTC)
    row.performed_by = "user-1"
    await session.commit()

    refetched = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.id == row.id
            )
        )
    ).scalar_one()
    assert refetched.accepted is True
    assert refetched.performed_by == "user-1"
    assert refetched.evidence_link_id == "ev-1"


async def test_rejected_is_distinct_from_offered(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    offered = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        section="narrative",
        field_key="hpi",
        phrase="No known allergies.",
        source="provider_favorite",
        confidence=Decimal("0.55"),
        compliance_state="approved",
        created_at=now,
        updated_at=now,
    )
    rejected = EpcrSmartTextSuggestion(
        id=str(uuid4()),
        chart_id=chart.id,
        tenant_id="t1",
        section="narrative",
        field_key="hpi",
        phrase="Patient denies prior cardiac history.",
        source="protocol",
        confidence=Decimal("0.40"),
        compliance_state="risk",
        accepted=False,
        accepted_at=now,
        performed_by="user-2",
        created_at=now,
        updated_at=now,
    )
    session.add_all([offered, rejected])
    await session.commit()

    pending = (
        await session.execute(
            select(EpcrSmartTextSuggestion).where(
                EpcrSmartTextSuggestion.chart_id == chart.id,
                EpcrSmartTextSuggestion.accepted.is_(None),
            )
        )
    ).scalars().all()
    assert {r.id for r in pending} == {offered.id}
