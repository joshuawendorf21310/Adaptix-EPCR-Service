"""Layer 7 — Payload persistence roundtrip proof.

Saves NemsisFieldBinding rows for ePayment.47, dAgency.27, a coded
dropdown field, a date field, a datetime field, and a numeric field.
Reloads them from the database and asserts the exact field_id and value
roundtrip with no substitution by labels, UUIDs, DB IDs, or UI keys.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import Base
from epcr_app.models.nemsis_binding import NemsisBindingStatus, NemsisFieldBinding


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield sm
    await engine.dispose()


PAYLOAD = [
    # (nemsis_element, mapped_value, source_field_name, extracted_value)
    ("ePayment.47", "9923001", "ambulance_conditions_indicator", "Ambulance Conditions Met"),
    ("dAgency.27", "9170001", "licensed_agency", "Yes"),
    ("eResponse.05", "2205001", "response_mode", "Emergency"),                # coded dropdown
    ("eTimes.03", "2026-04-22", "incident_date", "2026-04-22"),               # date
    ("eTimes.06", "2026-04-22T12:00:00+00:00", "unit_arrived_on_scene_dt", "2026-04-22T12:00:00Z"),  # datetime
    ("eVitals.06", "120", "systolic_bp", "120"),                              # numeric
]


@pytest.mark.asyncio
async def test_nemsis_field_bindings_roundtrip_exact_field_id_and_value(session_factory):
    chart_id = "00000000-0000-0000-0000-000000000001"
    tenant_id = "tenant-roundtrip"

    # --- Save ---
    async with session_factory() as session:
        for element, mapped_value, src_name, src_value in PAYLOAD:
            session.add(
                NemsisFieldBinding(
                    tenant_id=tenant_id,
                    chart_id=chart_id,
                    nemsis_element=element,
                    source_field_name=src_name,
                    extracted_value=src_value,
                    mapped_value=mapped_value,
                    status=NemsisBindingStatus.PENDING,
                    confidence_score=1.0,
                    mapped_at=datetime.now(timezone.utc),
                )
            )
        await session.commit()

    # --- Reload from a fresh session (no in-memory caching) ---
    async with session_factory() as session:
        result = await session.execute(
            select(NemsisFieldBinding)
            .where(NemsisFieldBinding.tenant_id == tenant_id)
            .where(NemsisFieldBinding.chart_id == chart_id)
            .order_by(NemsisFieldBinding.nemsis_element)
        )
        rows = result.scalars().all()

    # --- Assert ---
    assert len(rows) == len(PAYLOAD), "all bindings persisted"

    by_element = {row.nemsis_element: row for row in rows}
    expected_by_element = {element: (mapped_value, src_value) for element, mapped_value, _, src_value in PAYLOAD}

    for element, (expected_mapped, expected_src) in expected_by_element.items():
        assert element in by_element, f"{element} not reloaded"
        row = by_element[element]
        # Exact field_id roundtrip — no label, UUID, DB id, or UI key substitution
        assert row.nemsis_element == element
        # Exact mapped value roundtrip
        assert row.mapped_value == expected_mapped, (
            f"{element} mapped_value mismatch: got {row.mapped_value!r}, expected {expected_mapped!r}"
        )
        # Source value preserved for audit
        assert row.extracted_value == expected_src
        # Tenant isolation preserved
        assert row.tenant_id == tenant_id
        assert row.chart_id == chart_id
