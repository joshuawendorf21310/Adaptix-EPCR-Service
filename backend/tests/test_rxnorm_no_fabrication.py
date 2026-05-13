"""Honesty guard: when RXNAV_URL is unset, the service must NOT fabricate.

The RxNormMedicationService pillar's contract:

1. With ``RXNAV_URL`` unset, :meth:`RxNormService.capability` reports
   ``read_only_cache`` with a reason explaining the env var is missing.
2. :meth:`RxNormService.build_client` returns ``None`` (no client even
   if a transport is offered — env gates capability).
3. :meth:`RxNormService.normalize_for_chart` invoked with ``client=None``
   must NOT persist any match. The raw text on the source
   :class:`MedicationAdministration` remains the authoritative record.
"""
from __future__ import annotations

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
    EpcrRxNormMedicationMatch,
    MedicationAdministration,
)
from epcr_app.services.rxnorm_service import RxNormService


@pytest.fixture(autouse=True)
def _strip_rxnav_env(monkeypatch):
    monkeypatch.delenv("RXNAV_URL", raising=False)
    yield


@pytest_asyncio.fixture
async def db():
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
            call_number="CALL-rx-honesty",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        s.add(chart)
        med = MedicationAdministration(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=chart.id,
            medication_name="Epinephrine",
            route="IV",
            indication="Cardiac arrest",
            administered_at=datetime.now(UTC),
            administered_by_user_id="user-1",
        )
        s.add(med)
        await s.commit()
        yield s, chart, med
    await engine.dispose()


async def test_capability_is_read_only_cache_when_env_unset() -> None:
    cap = RxNormService.capability()
    assert cap["capability"] == "read_only_cache"
    assert "RXNAV_URL" in cap.get("reason", "")


async def test_build_client_returns_none_when_env_unset() -> None:
    assert RxNormService.build_client() is None
    # Even if a transport is supplied, env gates capability.
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    assert RxNormService.build_client(transport=transport) is None


async def test_normalize_does_not_persist_without_client(db) -> None:
    s, chart, med = db
    outcomes = await RxNormService.normalize_for_chart(
        s, tenant_id="t1", chart_id=chart.id, client=None
    )
    await s.commit()

    # Outcome reports honest unavailability.
    assert len(outcomes) == 1
    assert outcomes[0].medication_admin_id == med.id
    assert outcomes[0].capability == "unavailable"
    assert outcomes[0].rxcui is None
    assert outcomes[0].match_id is None

    # No match row persisted — we never fabricate an rxcui.
    rows = (
        await s.execute(
            select(EpcrRxNormMedicationMatch).where(
                EpcrRxNormMedicationMatch.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert rows == []

    # Raw text on the source row is preserved.
    refreshed = (
        await s.execute(
            select(MedicationAdministration).where(
                MedicationAdministration.id == med.id
            )
        )
    ).scalar_one()
    assert refreshed.medication_name == "Epinephrine"
    # Importantly, ``rxnorm_code`` on the source row is NOT auto-populated.
    assert refreshed.rxnorm_code is None


async def test_cached_match_still_returned_when_env_unset(db) -> None:
    """Read-only cache: prior matches remain visible even without RXNAV_URL."""
    s, chart, med = db
    now = datetime.now(UTC)
    s.add(
        EpcrRxNormMedicationMatch(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            raw_text="Epinephrine",
            normalized_name="Epinephrine",
            rxcui="3992",
            tty="IN",
            source="rxnav_api",
            created_at=now,
            updated_at=now,
        )
    )
    await s.commit()

    outcomes = await RxNormService.normalize_for_chart(
        s, tenant_id="t1", chart_id=chart.id, client=None
    )
    assert len(outcomes) == 1
    assert outcomes[0].capability == "cache_hit"
    assert outcomes[0].rxcui == "3992"

    listed = await RxNormService.list_for_chart(
        s, tenant_id="t1", chart_id=chart.id
    )
    assert len(listed) == 1
    assert listed[0]["rxcui"] == "3992"
