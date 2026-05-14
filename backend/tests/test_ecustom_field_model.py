"""Model-level tests for :class:`EpcrECustomFieldDefinition` and
:class:`EpcrECustomFieldValue`.

Verifies the rows round-trip through the ORM with the documented column
shapes and that the (tenant, chart, field_definition) uniqueness contract
is enforceable.
"""

from __future__ import annotations

import json
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
    EpcrECustomFieldDefinition,
    EpcrECustomFieldValue,
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


async def test_insert_and_query_definition_and_value(db_session) -> None:
    session, chart = db_session
    now = datetime.now(UTC)

    defn = EpcrECustomFieldDefinition(
        id=str(uuid4()),
        tenant_id="t1",
        agency_id="a1",
        field_key="exposure_type",
        label="Exposure Type",
        data_type="select",
        allowed_values_json=json.dumps(["smoke", "chemical", "blood"]),
        required=True,
        conditional_rule_json=None,
        nemsis_relationship="eCustomConfiguration.01",
        state_profile="CA",
        version=1,
        retired=False,
        created_at=now,
        updated_at=now,
    )
    session.add(defn)
    await session.commit()

    value = EpcrECustomFieldValue(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        field_definition_id=defn.id,
        value_json=json.dumps("smoke"),
        validation_result_json=json.dumps({"ok": True, "errors": []}),
        audit_user_id="user-1",
        created_at=now,
        updated_at=now,
    )
    session.add(value)
    await session.commit()

    fetched_def = (
        await session.execute(
            select(EpcrECustomFieldDefinition).where(
                EpcrECustomFieldDefinition.id == defn.id
            )
        )
    ).scalar_one()
    assert fetched_def.field_key == "exposure_type"
    assert fetched_def.data_type == "select"
    assert fetched_def.required is True
    assert fetched_def.nemsis_relationship == "eCustomConfiguration.01"
    assert fetched_def.state_profile == "CA"
    assert fetched_def.version == 1
    assert fetched_def.retired is False
    assert json.loads(fetched_def.allowed_values_json) == [
        "smoke",
        "chemical",
        "blood",
    ]

    fetched_value = (
        await session.execute(
            select(EpcrECustomFieldValue).where(
                EpcrECustomFieldValue.id == value.id
            )
        )
    ).scalar_one()
    assert fetched_value.chart_id == chart.id
    assert fetched_value.field_definition_id == defn.id
    assert json.loads(fetched_value.value_json) == "smoke"
    assert json.loads(fetched_value.validation_result_json) == {
        "ok": True,
        "errors": [],
    }
    assert fetched_value.audit_user_id == "user-1"
    assert fetched_value.created_at is not None
    assert fetched_value.updated_at is not None
