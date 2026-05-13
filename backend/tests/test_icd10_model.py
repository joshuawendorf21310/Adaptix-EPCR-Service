"""Model-level tests for :class:`EpcrIcd10DocumentationSuggestion`.

Verifies the row round-trips through the ORM with the documented column
shape and defaults (``provider_acknowledged=False``,
``provider_selected_code=None``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

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
    EpcrIcd10DocumentationSuggestion,
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
    row = EpcrIcd10DocumentationSuggestion(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        complaint_text="chest pain",
        prompt_kind="specificity",
        prompt_text="Clarify quality of chest pain.",
        candidate_codes_json='[{"code":"R07.9","description":"Chest pain, unspecified"}]',
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrIcd10DocumentationSuggestion).where(
                EpcrIcd10DocumentationSuggestion.id == row.id
            )
        )
    ).scalar_one()

    assert fetched.prompt_kind == "specificity"
    assert fetched.prompt_text.startswith("Clarify")
    assert fetched.provider_acknowledged is False
    assert fetched.provider_selected_code is None
    assert fetched.provider_selected_at is None
    assert "R07.9" in fetched.candidate_codes_json


async def test_provider_selection_round_trip(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)
    row = EpcrIcd10DocumentationSuggestion(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        complaint_text="fall from standing",
        prompt_kind="mechanism",
        prompt_text="Document height, surface, LOC.",
        candidate_codes_json=None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    row.provider_acknowledged = True
    row.provider_selected_code = "W19.XXXA"
    row.provider_selected_at = datetime.now(UTC)
    await session.commit()

    fetched = (
        await session.execute(
            select(EpcrIcd10DocumentationSuggestion).where(
                EpcrIcd10DocumentationSuggestion.id == row.id
            )
        )
    ).scalar_one()
    assert fetched.provider_acknowledged is True
    assert fetched.provider_selected_code == "W19.XXXA"
    assert fetched.provider_selected_at is not None
