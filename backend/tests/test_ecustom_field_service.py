"""Service-level tests for :class:`ECustomFieldService`.

Validates the replace-for-chart diff semantics:

- {} -> {a, b} inserts 2 rows + 2 ``ecustom_value.created`` audit rows.
- {a, b} -> {a', c} updates ``a``, inserts ``c``, deletes ``b`` with 3
  audit rows in the diff.
"""

from __future__ import annotations

import json
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
    EpcrAuditLog,
    EpcrECustomFieldDefinition,
    EpcrECustomFieldValue,
)
from epcr_app.services.ecustom_field_service import ECustomFieldService


TENANT = "t1"
AGENCY = "a1"


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
            tenant_id=TENANT,
            call_number="CALL-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)

        now = datetime.now(UTC)
        defs = [
            EpcrECustomFieldDefinition(
                id=str(uuid4()),
                tenant_id=TENANT,
                agency_id=AGENCY,
                field_key="exposure_type",
                label="Exposure Type",
                data_type="select",
                allowed_values_json=json.dumps(
                    ["smoke", "chemical", "blood"]
                ),
                required=False,
                version=1,
                retired=False,
                created_at=now,
                updated_at=now,
            ),
            EpcrECustomFieldDefinition(
                id=str(uuid4()),
                tenant_id=TENANT,
                agency_id=AGENCY,
                field_key="responder_count",
                label="Responder Count",
                data_type="number",
                required=False,
                version=1,
                retired=False,
                created_at=now,
                updated_at=now,
            ),
            EpcrECustomFieldDefinition(
                id=str(uuid4()),
                tenant_id=TENANT,
                agency_id=AGENCY,
                field_key="hazmat_present",
                label="Hazmat Present",
                data_type="boolean",
                required=False,
                version=1,
                retired=False,
                created_at=now,
                updated_at=now,
            ),
        ]
        for d in defs:
            session.add(d)
        await session.commit()
        yield session, chart, {d.field_key: d for d in defs}
    await engine.dispose()


async def _audit_actions(session, chart_id: str) -> list[str]:
    rows = (
        await session.execute(
            select(EpcrAuditLog).where(EpcrAuditLog.chart_id == chart_id)
        )
    ).scalars().all()
    return [r.action for r in rows]


async def _live_values(session, chart_id: str):
    return (
        await session.execute(
            select(EpcrECustomFieldValue).where(
                EpcrECustomFieldValue.chart_id == chart_id
            )
        )
    ).scalars().all()


async def test_empty_to_two_inserts_two_values_and_two_audits(
    db_setup,
) -> None:
    session, chart, _defs = db_setup
    result = await ECustomFieldService.replace_for_chart(
        session,
        tenant_id=TENANT,
        chart_id=chart.id,
        user_id="user-1",
        agency_id=AGENCY,
        values={
            "exposure_type": "smoke",
            "responder_count": 3,
        },
    )
    await session.commit()
    assert len(result) == 2
    rows = await _live_values(session, chart.id)
    assert len(rows) == 2

    actions = await _audit_actions(session, chart.id)
    created = [a for a in actions if a == "ecustom_value.created"]
    assert len(created) == 2


async def test_diff_updates_inserts_and_deletes(db_setup) -> None:
    session, chart, _defs = db_setup
    await ECustomFieldService.replace_for_chart(
        session,
        tenant_id=TENANT,
        chart_id=chart.id,
        user_id="user-1",
        agency_id=AGENCY,
        values={
            "exposure_type": "smoke",
            "responder_count": 3,
        },
    )
    await session.commit()

    before_actions = await _audit_actions(session, chart.id)
    before_count = len(before_actions)

    # exposure_type updated, responder_count dropped, hazmat_present new.
    result = await ECustomFieldService.replace_for_chart(
        session,
        tenant_id=TENANT,
        chart_id=chart.id,
        user_id="user-1",
        agency_id=AGENCY,
        values={
            "exposure_type": "chemical",
            "hazmat_present": True,
        },
    )
    await session.commit()

    assert len(result) == 2
    rows = await _live_values(session, chart.id)
    assert len(rows) == 2

    diff_actions = (await _audit_actions(session, chart.id))[before_count:]
    assert sorted(diff_actions) == sorted(
        [
            "ecustom_value.updated",
            "ecustom_value.created",
            "ecustom_value.deleted",
        ]
    )


async def test_upsert_value_creates_then_updates(db_setup) -> None:
    session, chart, _defs = db_setup

    row1 = await ECustomFieldService.upsert_value(
        session,
        tenant_id=TENANT,
        chart_id=chart.id,
        user_id="user-1",
        field_key="exposure_type",
        value="smoke",
        agency_id=AGENCY,
    )
    await session.commit()
    assert json.loads(row1.value_json) == "smoke"
    actions = await _audit_actions(session, chart.id)
    assert actions.count("ecustom_value.created") == 1

    row2 = await ECustomFieldService.upsert_value(
        session,
        tenant_id=TENANT,
        chart_id=chart.id,
        user_id="user-1",
        field_key="exposure_type",
        value="chemical",
        agency_id=AGENCY,
    )
    await session.commit()
    assert row2.id == row1.id
    assert json.loads(row2.value_json) == "chemical"
    actions = await _audit_actions(session, chart.id)
    assert actions.count("ecustom_value.updated") == 1


async def test_list_definitions_filters_retired(db_setup) -> None:
    session, _chart, defs = db_setup
    # Retire one definition.
    target = defs["responder_count"]
    target.retired = True
    await session.commit()

    rows = await ECustomFieldService.list_definitions(
        session, TENANT, AGENCY
    )
    keys = sorted(r.field_key for r in rows)
    assert keys == ["exposure_type", "hazmat_present"]
