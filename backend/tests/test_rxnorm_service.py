"""Service-level tests for :class:`RxNormService` and :class:`RxNavClient`.

Strategy: drive the real ``httpx.AsyncClient`` against an
``httpx.MockTransport``. The transport substitutes the wire only; the
production HTTP code path (request building, response handling, JSON
parsing) is exercised unchanged.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
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
from epcr_app.services.rxnorm_service import (
    RxNavClient,
    RxNormService,
    SOURCE_PROVIDER,
    SOURCE_RXNAV,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


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
            call_number="CALL-rxsvc-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        s.add(chart)
        await s.commit()
        yield s, chart
    await engine.dispose()


async def _make_med(
    session: AsyncSession,
    *,
    chart_id: str,
    name: str,
    tenant_id: str = "t1",
) -> MedicationAdministration:
    med = MedicationAdministration(
        id=str(uuid4()),
        tenant_id=tenant_id,
        chart_id=chart_id,
        medication_name=name,
        route="IV",
        indication="Test indication",
        administered_at=datetime.now(UTC),
        administered_by_user_id="user-1",
    )
    session.add(med)
    await session.flush()
    return med


# --------------------------------------------------------------------------- #
# Mock transport                                                              #
# --------------------------------------------------------------------------- #


def _rxcui_payload(rxcui: str, name: str) -> dict:
    return {"idGroup": {"name": name, "rxnormId": [rxcui]}}


def _allrelated_payload(name: str, dose_form: str | None = None) -> dict:
    groups = [
        {
            "tty": "IN",
            "conceptGroup": [],
            "conceptProperties": [{"name": name, "tty": "IN"}],
        }
    ]
    if dose_form:
        groups.append(
            {
                "tty": "DF",
                "conceptProperties": [{"name": dose_form, "tty": "DF"}],
            }
        )
    return {"allRelatedGroup": {"conceptGroup": groups}}


def _make_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _ensure_rxnav_env(monkeypatch):
    monkeypatch.setenv("RXNAV_URL", "https://rxnav.test/REST")
    yield


# --------------------------------------------------------------------------- #
# Client tests                                                                #
# --------------------------------------------------------------------------- #


async def test_client_get_rxcui_by_name_returns_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rxcui.json"):
            return httpx.Response(200, json=_rxcui_payload("3992", "Epinephrine"))
        if request.url.path.endswith("/rxcui/3992/allrelated.json"):
            return httpx.Response(
                200, json=_allrelated_payload("Epinephrine", dose_form="Injection")
            )
        return httpx.Response(404)

    async with RxNavClient(
        "https://rxnav.test/REST", transport=_make_transport(handler)
    ) as client:
        result = await client.get_rxcui_by_name("Epinephrine")
    assert result is not None
    assert result.rxcui == "3992"
    assert result.tty == "IN"
    assert result.dose_form == "Injection"
    assert result.normalized_name == "Epinephrine"
    assert Decimal("0") <= result.confidence <= Decimal("1")


async def test_client_get_rxcui_by_name_no_match_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"idGroup": {"name": "Bogus"}})

    async with RxNavClient(
        "https://rxnav.test/REST", transport=_make_transport(handler)
    ) as client:
        result = await client.get_rxcui_by_name("Bogus")
    assert result is None


# --------------------------------------------------------------------------- #
# Service tests                                                               #
# --------------------------------------------------------------------------- #


async def test_normalize_for_chart_persists_match(db) -> None:
    s, chart = db
    med = await _make_med(s, chart_id=chart.id, name="Epinephrine")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rxcui.json"):
            return httpx.Response(200, json=_rxcui_payload("3992", "Epinephrine"))
        return httpx.Response(
            200, json=_allrelated_payload("Epinephrine", dose_form="Injection")
        )

    client = RxNavClient(
        "https://rxnav.test/REST", transport=_make_transport(handler)
    )
    try:
        outcomes = await RxNormService.normalize_for_chart(
            s, tenant_id="t1", chart_id=chart.id, client=client
        )
    finally:
        await client.aclose()
    await s.commit()

    assert len(outcomes) == 1
    assert outcomes[0].capability == "live_match"
    assert outcomes[0].rxcui == "3992"

    rows = (
        await s.execute(
            select(EpcrRxNormMedicationMatch).where(
                EpcrRxNormMedicationMatch.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].rxcui == "3992"
    assert rows[0].source == SOURCE_RXNAV
    assert rows[0].raw_text == "Epinephrine"
    assert rows[0].medication_admin_id == med.id


async def test_normalize_for_chart_cache_hit_skips_api(db) -> None:
    s, chart = db
    med = await _make_med(s, chart_id=chart.id, name="Aspirin")
    now = datetime.now(UTC)
    s.add(
        EpcrRxNormMedicationMatch(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            raw_text="Aspirin",
            normalized_name="Aspirin",
            rxcui="1191",
            tty="IN",
            source=SOURCE_RXNAV,
            confidence=Decimal("0.95"),
            created_at=now,
            updated_at=now,
        )
    )
    await s.commit()

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500)

    client = RxNavClient(
        "https://rxnav.test/REST", transport=_make_transport(handler)
    )
    try:
        outcomes = await RxNormService.normalize_for_chart(
            s, tenant_id="t1", chart_id=chart.id, client=client
        )
    finally:
        await client.aclose()

    assert calls == []  # never called RxNav
    assert len(outcomes) == 1
    assert outcomes[0].capability == "cache_hit"
    assert outcomes[0].rxcui == "1191"


async def test_normalize_no_match_does_not_persist(db) -> None:
    s, chart = db
    await _make_med(s, chart_id=chart.id, name="MysteryDrugXYZ")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"idGroup": {"name": "MysteryDrugXYZ"}})

    client = RxNavClient(
        "https://rxnav.test/REST", transport=_make_transport(handler)
    )
    try:
        outcomes = await RxNormService.normalize_for_chart(
            s, tenant_id="t1", chart_id=chart.id, client=client
        )
    finally:
        await client.aclose()
    await s.commit()

    assert len(outcomes) == 1
    assert outcomes[0].capability == "no_match"
    assert outcomes[0].rxcui is None
    rows = (
        await s.execute(
            select(EpcrRxNormMedicationMatch).where(
                EpcrRxNormMedicationMatch.chart_id == chart.id
            )
        )
    ).scalars().all()
    assert rows == []  # never fabricates


async def test_confirm_marks_provider_confirmed(db) -> None:
    s, chart = db
    med = await _make_med(s, chart_id=chart.id, name="Epi")
    now = datetime.now(UTC)
    row = EpcrRxNormMedicationMatch(
        id=str(uuid4()),
        tenant_id="t1",
        chart_id=chart.id,
        medication_admin_id=med.id,
        raw_text="Epi",
        normalized_name="something-wrong",
        rxcui="0000",
        tty="IN",
        source=SOURCE_RXNAV,
        confidence=Decimal("0.40"),
        created_at=now,
        updated_at=now,
    )
    s.add(row)
    await s.commit()

    updated = await RxNormService.confirm(
        s,
        tenant_id="t1",
        chart_id=chart.id,
        match_id=row.id,
        normalized_name="Epinephrine",
        rxcui="3992",
        provider_id="provider-7",
        tty="IN",
    )
    await s.commit()

    assert updated.rxcui == "3992"
    assert updated.normalized_name == "Epinephrine"
    assert updated.source == SOURCE_PROVIDER
    assert updated.provider_confirmed is True
    assert updated.provider_id == "provider-7"
    assert updated.confirmed_at is not None
    assert updated.confidence == Decimal("1.00")


async def test_capability_reports_live_when_env_set(monkeypatch) -> None:
    monkeypatch.setenv("RXNAV_URL", "https://rxnav.test/REST")
    cap = RxNormService.capability()
    assert cap["capability"] == "live"
    assert cap["source"] == "rxnorm_service"


async def test_list_for_chart_returns_serialized_rows(db) -> None:
    s, chart = db
    med = await _make_med(s, chart_id=chart.id, name="Epi")
    now = datetime.now(UTC)
    s.add(
        EpcrRxNormMedicationMatch(
            id=str(uuid4()),
            tenant_id="t1",
            chart_id=chart.id,
            medication_admin_id=med.id,
            raw_text="Epi",
            normalized_name="Epinephrine",
            rxcui="3992",
            tty="IN",
            source=SOURCE_RXNAV,
            confidence=Decimal("0.95"),
            created_at=now,
            updated_at=now,
        )
    )
    await s.commit()

    rows = await RxNormService.list_for_chart(
        s, tenant_id="t1", chart_id=chart.id
    )
    assert len(rows) == 1
    assert rows[0]["rxcui"] == "3992"
    assert rows[0]["source"] == SOURCE_RXNAV
    assert rows[0]["providerConfirmed"] is False
