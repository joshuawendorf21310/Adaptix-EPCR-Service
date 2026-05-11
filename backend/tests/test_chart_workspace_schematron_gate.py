from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api import finalize_chart
from epcr_app.chart_finalization_service import ChartFinalizationService
from epcr_app.chart_workspace_service import ChartWorkspaceError, ChartWorkspaceService
from epcr_app.models import Base, ChartStatus
from epcr_app.nemsis_finalization_gate import (
    GATE_STATUS_BLOCKED,
    GATE_STATUS_OK,
    GATE_STATUS_UNAVAILABLE,
    SchematronGateEvaluation,
    SchematronGateIssue,
)
from tests.agency_helpers import seed_active_agency


@pytest_asyncio.fixture
async def workspace_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as s:
        await seed_active_agency(s, tenant_id="tenant-gate")
        await s.commit()
    yield sessionmaker
    await engine.dispose()


def _user(tenant_id: str = "tenant-gate", user_id: str = "user-gate") -> SimpleNamespace:
    return SimpleNamespace(tenant_id=tenant_id, user_id=user_id, email="gate@x", roles=[])


async def _create_chart(session: AsyncSession) -> str:
    created = await ChartWorkspaceService.create_workspace_chart(
        session,
        _user(),
        {"call_number": "CALL-GATE-001", "incident_type": "medical"},
    )
    return created["chart"]["id"]


def _compliant_payload() -> dict:
    return {
        "is_fully_compliant": True,
        "missing_mandatory_fields": [],
        "compliance_percentage": 100,
        "mandatory_fields_filled": 10,
    }


async def _compliant_check(*args, **kwargs) -> dict:
    return _compliant_payload()


async def _xml_bytes(*args, **kwargs) -> bytes:
    return b"<EMSDataSet />"


async def _no_xml(*args, **kwargs) -> None:
    return None


async def _blocked_gate(*args, **kwargs):
    return (
        SchematronGateEvaluation(
            can_finalize=False,
            blocked=True,
            status=GATE_STATUS_BLOCKED,
            errors=[
                SchematronGateIssue(
                    severity="error",
                    message="Agency name is required.",
                    location="/EMSDataSet/Header/AgencyName",
                    test="exists(.)",
                    role="error",
                )
            ],
            warnings=[],
            blocking_reason="Schematron reported 1 error-severity assertion.",
        ),
        {"validator_source": "test"},
    )


async def _warning_gate(*args, **kwargs):
    return (
        SchematronGateEvaluation(
            can_finalize=True,
            blocked=False,
            status=GATE_STATUS_OK,
            errors=[],
            warnings=[
                SchematronGateIssue(
                    severity="warning",
                    message="Agency state is recommended.",
                    location="/EMSDataSet/Header/AgencyState",
                    test="exists(.)",
                    role="warning",
                )
            ],
        ),
        {"validator_source": "test"},
    )


async def _unavailable_gate(*args, **kwargs):
    return (
        SchematronGateEvaluation(
            can_finalize=True,
            blocked=False,
            status=GATE_STATUS_UNAVAILABLE,
            errors=[],
            warnings=[],
            unavailable_reason="No NEMSIS XML available for this chart.",
        ),
        {"validator_source": "test"},
    )


@pytest.mark.asyncio
async def test_workspace_finalize_blocks_on_schematron_error(workspace_db, monkeypatch) -> None:
    async with workspace_db() as session:
        chart_id = await _create_chart(session)
        monkeypatch.setattr(
            "epcr_app.chart_finalization_service.ChartService.check_nemsis_compliance",
            _compliant_check,
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_build_chart_xml",
            staticmethod(_xml_bytes),
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_evaluate_schematron",
            staticmethod(_blocked_gate),
        )

        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.finalize_workspace(session, _user(), chart_id)

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["schematron"]["status"] == GATE_STATUS_BLOCKED
        assert excinfo.value.detail["schematron"]["blocked"] is True


@pytest.mark.asyncio
async def test_workspace_finalize_allows_warning_and_surfaces_payload(workspace_db, monkeypatch) -> None:
    async with workspace_db() as session:
        chart_id = await _create_chart(session)
        monkeypatch.setattr(
            "epcr_app.chart_finalization_service.ChartService.check_nemsis_compliance",
            _compliant_check,
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_build_chart_xml",
            staticmethod(_xml_bytes),
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_evaluate_schematron",
            staticmethod(_warning_gate),
        )

        result = await ChartWorkspaceService.finalize_workspace(session, _user(), chart_id)

        assert result["chart"]["status"] == ChartStatus.FINALIZED.value
        assert result["schematron"]["status"] == GATE_STATUS_OK
        assert result["schematron"]["warnings"][0]["natural_language_message"] == "Agency state is recommended."


@pytest.mark.asyncio
async def test_chart_and_workspace_finalize_share_equivalent_gate_contract(workspace_db, monkeypatch) -> None:
    async with workspace_db() as session:
        chart_id = await _create_chart(session)
        monkeypatch.setattr(
            "epcr_app.chart_finalization_service.ChartService.check_nemsis_compliance",
            _compliant_check,
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_build_chart_xml",
            staticmethod(_xml_bytes),
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_evaluate_schematron",
            staticmethod(_blocked_gate),
        )

        with pytest.raises(ChartWorkspaceError) as workspace_exc:
            await ChartWorkspaceService.finalize_workspace(session, _user(), chart_id)

        with pytest.raises(HTTPException) as legacy_exc:
            await finalize_chart(
                chart_id=chart_id,
                session=session,
                current_user=_user(),
            )

        assert workspace_exc.value.detail["schematron"] == legacy_exc.value.detail["schematron"]


@pytest.mark.asyncio
async def test_unavailable_schematron_is_not_rendered_as_success(workspace_db, monkeypatch) -> None:
    async with workspace_db() as session:
        chart_id = await _create_chart(session)
        monkeypatch.setattr(
            "epcr_app.chart_finalization_service.ChartService.check_nemsis_compliance",
            _compliant_check,
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_build_chart_xml",
            staticmethod(_no_xml),
        )
        monkeypatch.setattr(
            ChartFinalizationService,
            "_evaluate_schematron",
            staticmethod(_unavailable_gate),
        )

        workspace_result = await ChartWorkspaceService.finalize_workspace(session, _user(), chart_id)
        legacy_result = await finalize_chart(
            chart_id=chart_id,
            session=session,
            current_user=_user(),
        )

        assert workspace_result["schematron"]["status"] == GATE_STATUS_UNAVAILABLE
        assert workspace_result["schematron"]["status"] != GATE_STATUS_OK
        assert legacy_result["schematron"]["status"] == GATE_STATUS_UNAVAILABLE
        assert legacy_result["schematron"]["blocked"] is False