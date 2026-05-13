"""Tests for ``LockReadinessService`` aggregation pillar.

The service is AGGREGATION-only: it does not create models or run
migrations. These tests therefore mock the canonical NEMSIS compliance
check and seed only the rows the service reads directly
(``EpcrAuditLog``). The compliance shape mirrors what
``ChartService.check_nemsis_compliance`` returns in production:

    {
        "chart_id": ...,
        "compliance_status": ...,
        "compliance_percentage": ...,
        "mandatory_fields_filled": int,
        "mandatory_fields_required": int,
        "missing_mandatory_fields": list[str],
        "is_fully_compliant": bool,
    }
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import Base, Chart, ChartStatus, EpcrAuditLog
from epcr_app.services import ChartService
from epcr_app.services.lock_readiness_service import LockReadinessService


TENANT = "tenant-lr"


@pytest_asyncio.fixture
async def lr_db():
    """In-memory SQLite session factory for lock-readiness tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield sessionmaker
    finally:
        await engine.dispose()


async def _seed_chart(sessionmaker) -> str:
    """Insert a minimum-viable Chart row and return its id."""
    chart_id = str(uuid4())
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        session.add(
            Chart(
                id=chart_id,
                tenant_id=TENANT,
                call_number=f"CALL-{chart_id[:8]}",
                incident_type="medical",
                status=ChartStatus.NEW,
                created_by_user_id="user-lr",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    return chart_id


def _install_compliance_stub(monkeypatch, payload: dict | Exception) -> None:
    """Replace ``ChartService.check_nemsis_compliance`` for the test.

    Accepts either a dict payload (returned) or an Exception (raised).
    The stub is a real async function — no fake-success fallback.
    """

    async def _stub(session, tenant_id, chart_id):  # noqa: ANN001
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(
        ChartService, "check_nemsis_compliance", staticmethod(_stub)
    )


# --------------------------------------------------------------------- #
# Case 1: empty / fully compliant chart with no anomalies.              #
# Score should be 1.0, no blockers, no warnings, only advisories from   #
# the explicitly-empty unmapped_sections override.                      #
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_for_chart_empty_no_blockers(lr_db, monkeypatch) -> None:
    chart_id = await _seed_chart(lr_db)
    _install_compliance_stub(
        monkeypatch,
        {
            "chart_id": chart_id,
            "compliance_status": "compliant",
            "compliance_percentage": 100,
            "mandatory_fields_filled": 13,
            "mandatory_fields_required": 13,
            "missing_mandatory_fields": [],
            "is_fully_compliant": True,
        },
    )

    async with lr_db() as session:
        result = await LockReadinessService.get_for_chart(
            session, TENANT, chart_id, unmapped_sections=()
        )

    assert result["score"] == 1.0
    assert result["blockers"] == []
    assert result["warnings"] == []
    assert result["advisories"] == []
    assert isinstance(result["generated_at"], str)
    # ISO-8601 round-trip should parse.
    datetime.fromisoformat(result["generated_at"])


# --------------------------------------------------------------------- #
# Case 2: missing mandatory fields → blockers, score floored to 0.0.    #
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_for_chart_blockers_floor_score(lr_db, monkeypatch) -> None:
    chart_id = await _seed_chart(lr_db)
    _install_compliance_stub(
        monkeypatch,
        {
            "chart_id": chart_id,
            "compliance_status": "incomplete",
            "compliance_percentage": 60,
            "mandatory_fields_filled": 8,
            "mandatory_fields_required": 13,
            "missing_mandatory_fields": [
                "ePatient.13", "eSituation.11", "eVitals.06",
            ],
            "is_fully_compliant": False,
        },
    )

    async with lr_db() as session:
        result = await LockReadinessService.get_for_chart(
            session, TENANT, chart_id, unmapped_sections=()
        )

    # Three blockers, one per missing field.
    assert len(result["blockers"]) == 3
    fields = {b["field"] for b in result["blockers"]}
    assert fields == {"ePatient.13", "eSituation.11", "eVitals.06"}
    for blocker in result["blockers"]:
        assert blocker["kind"] == "missing_mandatory_field"
        assert blocker["source"] == "nemsis_finalization_gate"

    # Partial readiness emits a single warning row.
    assert any(
        w["kind"] == "readiness_partial"
        and w["required_present"] == 8
        and w["required_total"] == 13
        for w in result["warnings"]
    )

    # Blockers force score floor to 0.0 regardless of fill ratio.
    assert result["score"] == 0.0


# --------------------------------------------------------------------- #
# Case 3: warnings from audit anomalies + unmapped-section advisories.  #
# No blockers, so score follows fill ratio minus warning penalty.       #
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_for_chart_warnings_and_advisories(
    lr_db, monkeypatch
) -> None:
    chart_id = await _seed_chart(lr_db)
    _install_compliance_stub(
        monkeypatch,
        {
            "chart_id": chart_id,
            "compliance_status": "compliant",
            "compliance_percentage": 100,
            "mandatory_fields_filled": 13,
            "mandatory_fields_required": 13,
            "missing_mandatory_fields": [],
            "is_fully_compliant": True,
        },
    )

    # Seed two audit anomalies + one ordinary audit row (must be ignored).
    now = datetime.now(UTC)
    async with lr_db() as session:
        session.add_all(
            [
                EpcrAuditLog(
                    id=str(uuid4()),
                    chart_id=chart_id,
                    tenant_id=TENANT,
                    user_id="user-1",
                    action="vitals_anomaly_detected",
                    detail_json='{"hr": 250}',
                    performed_at=now,
                ),
                EpcrAuditLog(
                    id=str(uuid4()),
                    chart_id=chart_id,
                    tenant_id=TENANT,
                    user_id="user-1",
                    action="medication_anomaly",
                    detail_json='{"dose": "10x"}',
                    performed_at=now,
                ),
                EpcrAuditLog(
                    id=str(uuid4()),
                    chart_id=chart_id,
                    tenant_id=TENANT,
                    user_id="user-1",
                    action="update",
                    detail_json="{}",
                    performed_at=now,
                ),
            ]
        )
        await session.commit()

    async with lr_db() as session:
        result = await LockReadinessService.get_for_chart(
            session,
            TENANT,
            chart_id,
            unmapped_sections=("attachments", "destination"),
        )

    # Two audit-anomaly warnings, no other warning (compliance is full).
    anomaly_warnings = [
        w for w in result["warnings"] if w["kind"] == "audit_anomaly"
    ]
    assert len(anomaly_warnings) == 2
    assert {w["action"] for w in anomaly_warnings} == {
        "vitals_anomaly_detected",
        "medication_anomaly",
    }

    # Unmapped sections surfaced as advisories, sorted.
    advisory_sections = [
        a["section"] for a in result["advisories"] if a["kind"] == "unmapped_field"
    ]
    assert advisory_sections == ["attachments", "destination"]

    # No blockers.
    assert result["blockers"] == []

    # Score = 1.0 base − 0.05 × 2 warnings = 0.9.
    assert result["score"] == pytest.approx(0.9, rel=1e-6)


# --------------------------------------------------------------------- #
# Case 4: explicit score math — partial fill + warnings.                #
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_for_chart_score_math_partial(lr_db, monkeypatch) -> None:
    chart_id = await _seed_chart(lr_db)
    # No missing fields so no blockers; partial fill triggers a single
    # readiness_partial warning. Use a clean fraction (5/10 = 0.5) so the
    # arithmetic is unambiguous.
    _install_compliance_stub(
        monkeypatch,
        {
            "chart_id": chart_id,
            "compliance_status": "incomplete",
            "compliance_percentage": 50,
            "mandatory_fields_filled": 5,
            "mandatory_fields_required": 10,
            "missing_mandatory_fields": [],
            "is_fully_compliant": False,
        },
    )

    async with lr_db() as session:
        result = await LockReadinessService.get_for_chart(
            session, TENANT, chart_id, unmapped_sections=()
        )

    assert result["blockers"] == []
    # Exactly one warning: the readiness_partial row.
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["kind"] == "readiness_partial"
    # Score = 5/10 − 0.05 × 1 warning = 0.45.
    assert result["score"] == pytest.approx(0.45, rel=1e-6)


# --------------------------------------------------------------------- #
# Case 5: compliance check raises → honest advisory, score collapses.   #
# --------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_for_chart_compliance_failure_is_honest(
    lr_db, monkeypatch
) -> None:
    chart_id = await _seed_chart(lr_db)
    _install_compliance_stub(monkeypatch, RuntimeError("db offline"))

    async with lr_db() as session:
        result = await LockReadinessService.get_for_chart(
            session, TENANT, chart_id, unmapped_sections=()
        )

    assert result["score"] == 0.0
    assert result["blockers"] == []
    assert result["warnings"] == []
    assert any(
        a["kind"] == "nemsis_compliance_unavailable"
        and "db offline" in a["detail"]
        for a in result["advisories"]
    )
