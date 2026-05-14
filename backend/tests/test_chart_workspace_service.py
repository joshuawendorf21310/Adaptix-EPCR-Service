"""Service-level tests for the chart workspace orchestrator.

Verifies the workspace service is a truthful façade over canonical
``ChartService`` methods. No fabricated success — unsupported sections
return ``field_not_mapped``, and submission/export honestly report
unavailable/not-generated states until the underlying capabilities
produce real artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.chart_workspace_service import (
    ALL_SECTIONS,
    SUPPORTED_SECTIONS,
    UNMAPPED_SECTIONS,
    ChartWorkspaceError,
    ChartWorkspaceService,
)
from epcr_app.models import AgencyProfile, Base, ChartStatus, PatientRegistryChartLink
from epcr_app.services import ChartService


@pytest_asyncio.fixture
async def workspace_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                AgencyProfile(
                    id=str(uuid4()),
                    tenant_id="tenant-ws",
                    agency_code="MADISONEMS",
                    agency_name="Madison EMS",
                    numbering_policy_json="{}",
                    activated_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                AgencyProfile(
                    id=str(uuid4()),
                    tenant_id="tenant-A",
                    agency_code="TENANTAEMS",
                    agency_name="Tenant A EMS",
                    numbering_policy_json="{}",
                    activated_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.commit()
    yield sessionmaker
    await engine.dispose()


def _user(tenant_id: str = "tenant-ws", user_id: str = "user-ws") -> SimpleNamespace:
    return SimpleNamespace(tenant_id=tenant_id, user_id=user_id, email="t@x", roles=[])


@pytest.mark.asyncio
async def test_create_workspace_chart_creates_real_chart(workspace_db) -> None:
    async with workspace_db() as session:
        result = await ChartWorkspaceService.create_workspace_chart(
            session,
            _user(),
            {"call_number": "CALL-WS-001", "incident_type": "medical"},
        )
        assert result["chart"]["id"]
        assert result["chart"]["call_number"] == "CALL-WS-001"
        assert result["chart"]["incident_number"] == "2026-MADISONEMS-000001"
        assert result["chart"]["response_number"] == "2026-MADISONEMS-000001-R01"
        assert result["chart"]["pcr_number"] == "2026-MADISONEMS-000001-PCR01"
        assert result["chart"]["billing_case_number"] == "2026-MADISONEMS-000001-BILL01"
        assert result["chart"]["status"] == ChartStatus.NEW.value
        # Verify the chart actually exists via canonical service
        fetched = await ChartService.get_chart(session, "tenant-ws", result["chart"]["id"])
        assert fetched is not None


@pytest.mark.asyncio
async def test_create_workspace_chart_allows_missing_legacy_call_number(workspace_db) -> None:
    async with workspace_db() as session:
        result = await ChartWorkspaceService.create_workspace_chart(
            session,
            _user(),
            {"incident_type": "medical"},
        )
        assert result["chart"]["call_number"] == "2026-MADISONEMS-000001"
        assert result["chart"]["incident_number"] == "2026-MADISONEMS-000001"
        assert result["incident_number"] == "2026-MADISONEMS-000001"
        assert result["response_number"] == "2026-MADISONEMS-000001-R01"
        assert result["pcr_number"] == "2026-MADISONEMS-000001-PCR01"
        assert result["billing_case_number"] == "2026-MADISONEMS-000001-BILL01"


@pytest.mark.asyncio
async def test_create_workspace_chart_requires_fields(workspace_db) -> None:
    async with workspace_db() as session:
        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.create_workspace_chart(
                session, _user(), {"call_number": "", "incident_type": ""}
            )
        assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_get_workspace_returns_full_aggregate(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-002", "incident_type": "trauma"}
        )
        chart_id = created["chart"]["id"]
        ws = await ChartWorkspaceService.get_workspace(session, _user(), chart_id)
        # All required top-level keys present
        for key in (
            "chart", "patient", "incident", "response", "crew", "scene",
            "complaint", "history", "allergies", "home_medications",
            "assessment", "vitals", "procedures", "medications_administered",
            "narrative", "disposition", "destination", "signatures",
            "attachments", "nemsis_readiness", "schematron", "export_status",
            "submission_status", "field_mappings", "unmapped_fields",
            "registry", "defined_lists", "custom_elements", "audit",
        ):
            assert key in ws, f"missing workspace key: {key}"
        assert ws["chart"]["incident_type"] == "trauma"
        assert ws["incident_number"] == "2026-MADISONEMS-000001"
        assert ws["response_number"] == "2026-MADISONEMS-000001-R01"
        assert ws["pcr_number"] == "2026-MADISONEMS-000001-PCR01"
        assert ws["billing_case_number"] == "2026-MADISONEMS-000001-BILL01"
        assert ws["vitals"] == []
        assert ws["procedures"] == []


@pytest.mark.asyncio
async def test_get_workspace_unknown_chart_returns_404(workspace_db) -> None:
    async with workspace_db() as session:
        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.get_workspace(session, _user(), "nonexistent")
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_unsupported_section_returns_field_not_mapped(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-003", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        for section in UNMAPPED_SECTIONS:
            with pytest.raises(ChartWorkspaceError) as excinfo:
                await ChartWorkspaceService.update_workspace_section(
                    session, _user(), chart_id, section, {}
                )
            assert excinfo.value.status_code == 422
            assert section in (excinfo.value.detail.get("field_not_mapped") or [])


@pytest.mark.asyncio
async def test_unknown_section_returns_400(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-004", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.update_workspace_section(
                session, _user(), chart_id, "fictional_section", {}
            )
        assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_patient_section_persists_via_canonical_service(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-005", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        ws = await ChartWorkspaceService.update_workspace_section(
            session, _user(), chart_id, "patient",
            {"first_name": "Ada", "last_name": "Lovelace", "sex": "female"},
        )
        assert ws["patient"]["first_name"] == "Ada"
        assert ws["patient"]["last_name"] == "Lovelace"
        # Confirm canonical service sees the same row
        profile = await ChartService.get_patient_profile(session, "tenant-ws", chart_id)
        assert profile is not None and profile.first_name == "Ada"
        registry = await session.execute(select(PatientRegistryChartLink).where(PatientRegistryChartLink.chart_id == chart_id))
        registry_link = registry.scalars().first()
        assert registry_link is not None
        assert registry_link.link_status == "linked"


@pytest.mark.asyncio
async def test_vitals_section_records_through_chart_service(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-006", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        ws = await ChartWorkspaceService.update_workspace_section(
            session, _user(), chart_id, "vitals",
            {"bp_sys": 120, "bp_dia": 80, "hr": 72, "rr": 16, "spo2": 98},
        )
        assert len(ws["vitals"]) == 1
        assert ws["vitals"][0]["bp_sys"] == 120


@pytest.mark.asyncio
async def test_nemsis_field_update_records_mapping(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-007", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        ws = await ChartWorkspaceService.update_workspace_field(
            session, _user(), chart_id, "nemsis", "eRecord.01", "test-value"
        )
        recorded = [m for m in ws["field_mappings"] if m["nemsis_field"] == "eRecord.01"]
        assert recorded and recorded[0]["nemsis_value"] == "test-value"


@pytest.mark.asyncio
async def test_finalize_blocked_when_compliance_incomplete(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-008", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.finalize_workspace(session, _user(), chart_id)
        assert excinfo.value.status_code == 422
        assert "missing_mandatory_fields" in excinfo.value.detail


@pytest.mark.asyncio
async def test_export_returns_not_generated_until_canonical_export_runs(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-009", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        result = await ChartWorkspaceService.export_workspace(session, _user(), chart_id)
        assert result["status"] == "export_not_generated"
        assert result["last_export_id"] is None


@pytest.mark.asyncio
async def test_submit_returns_unavailable_when_cta_not_configured(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-010", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        result = await ChartWorkspaceService.submit_workspace(session, _user(), chart_id)
        assert result["status"] == "submission_unavailable"
        assert result["last_submission_id"] is None


@pytest.mark.asyncio
async def test_status_endpoint_reports_current_state(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(), {"call_number": "CALL-WS-011", "incident_type": "medical"}
        )
        chart_id = created["chart"]["id"]
        status_payload = await ChartWorkspaceService.get_workspace_status(
            session, _user(), chart_id
        )
        assert status_payload["chart_id"] == chart_id
        assert status_payload["status"] == ChartStatus.NEW.value
        assert status_payload["submission_status"] == "submission_unavailable"


@pytest.mark.asyncio
async def test_tenant_isolation_blocks_cross_tenant_access(workspace_db) -> None:
    async with workspace_db() as session:
        created = await ChartWorkspaceService.create_workspace_chart(
            session, _user(tenant_id="tenant-A"),
            {"call_number": "CALL-WS-012", "incident_type": "medical"},
        )
        chart_id = created["chart"]["id"]
        with pytest.raises(ChartWorkspaceError) as excinfo:
            await ChartWorkspaceService.get_workspace(
                session, _user(tenant_id="tenant-B"), chart_id
            )
        assert excinfo.value.status_code == 404


def test_section_taxonomy_is_complete() -> None:
    assert SUPPORTED_SECTIONS.isdisjoint(UNMAPPED_SECTIONS)
    assert SUPPORTED_SECTIONS | UNMAPPED_SECTIONS == ALL_SECTIONS
    expected = {
        "patient", "incident", "response", "crew", "scene", "complaint",
        "history", "allergies", "home_medications", "assessment", "vitals",
        "treatment", "procedures", "medications_administered", "narrative",
        "disposition", "destination", "signatures", "attachments", "nemsis",
        "export",
    }
    assert ALL_SECTIONS == expected
