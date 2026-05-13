"""Model-level tests for :class:`EpcrRxNormMedicationMatch`.

Validates schema portability and the confidence-range CheckConstraint.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Base,
    Chart,
    ChartStatus,
    EpcrRxNormMedicationMatch,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as s:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-rx-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        s.add(chart)
        await s.commit()
        yield s, chart
    await engine.dispose()


async def test_insert_full_row(session) -> None:
    s, chart = session
    now = datetime.now(UTC)
    row = EpcrRxNormMedicationMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        medication_admin_id=str(uuid4()),
        raw_text="Epi 1mg IV",
        normalized_name="Epinephrine",
        rxcui="3992",
        tty="IN",
        dose_form="Injection",
        strength="1 MG/ML",
        confidence=Decimal("0.95"),
        source="rxnav_api",
        provider_confirmed=False,
        provider_id=None,
        confirmed_at=None,
        created_at=now,
        updated_at=now,
    )
    s.add(row)
    await s.commit()
    fetched = (
        await s.execute(
            select(EpcrRxNormMedicationMatch).where(
                EpcrRxNormMedicationMatch.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.rxcui == "3992"
    assert fetched.tty == "IN"
    assert fetched.source == "rxnav_api"
    assert fetched.provider_confirmed is False
    assert fetched.raw_text == "Epi 1mg IV"


async def test_minimal_unmatched_row_allows_null_rxcui(session) -> None:
    s, chart = session
    now = datetime.now(UTC)
    # Only raw_text required at the rxcui axis; rxcui/normalized_name/etc
    # remain NULL when we have no live match cached but still want to
    # remember we tried.
    row = EpcrRxNormMedicationMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        medication_admin_id=str(uuid4()),
        raw_text="UnknownMed",
        source="local_cache",
        created_at=now,
        updated_at=now,
    )
    s.add(row)
    await s.commit()
    fetched = (
        await s.execute(
            select(EpcrRxNormMedicationMatch).where(
                EpcrRxNormMedicationMatch.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.rxcui is None
    assert fetched.normalized_name is None
    assert fetched.provider_confirmed is False


async def test_confidence_check_constraint_rejects_out_of_range(session) -> None:
    s, chart = session
    now = datetime.now(UTC)
    row = EpcrRxNormMedicationMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        medication_admin_id=str(uuid4()),
        raw_text="Aspirin",
        rxcui="1191",
        source="rxnav_api",
        confidence=Decimal("1.50"),  # out of [0, 1]
        created_at=now,
        updated_at=now,
    )
    s.add(row)
    with pytest.raises(IntegrityError):
        await s.commit()
