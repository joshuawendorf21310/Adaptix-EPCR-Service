from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from adaptix_contracts.schemas.nemsis_exports import ExportReadinessSnapshot, ExportTriggerSource, GenerateExportRequest
from epcr_app.api import finalize_chart, get_audit_log
from epcr_app.dependencies import CurrentUser
from epcr_app.models import Base, ChartStatus, EpcrAuditLog
from epcr_app.models_export import NemsisExportAttempt
from epcr_app.chart_service import NEMSIS_MANDATORY_FIELDS
from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
from epcr_app.services import ChartService
from epcr_app.services_export import ExportValidationFailure, NemsisExportService


@pytest_asyncio.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_finalize_chart_persists_audit_entry(test_db) -> None:
    tenant_id = str(uuid4())
    user_id = str(uuid4())

    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=tenant_id,
            call_number="CALL-AUDIT-001",
            incident_type="medical",
            created_by_user_id=user_id,
        )

        for field, value in NEMSIS_MANDATORY_FIELDS.items():
            await ChartService.record_nemsis_field(
                session=session,
                tenant_id=tenant_id,
                chart_id=chart.id,
                nemsis_field=field,
                nemsis_value=value,
                source="manual",
            )

        response = await finalize_chart(
            chart_id=chart.id,
            session=session,
            current_user=CurrentUser(user_id=user_id, tenant_id=tenant_id),
        )

        assert response["status"] == ChartStatus.FINALIZED.value

        payload = await get_audit_log(
            chart_id=chart.id,
            session=session,
            current_user=CurrentUser(user_id=user_id, tenant_id=tenant_id),
        )
        assert payload["count"] > 0
        assert payload["entries"][0]["action"] == "chart_finalized"


@pytest.mark.asyncio
async def test_get_audit_log_filters_by_tenant(test_db) -> None:
    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    user_id = str(uuid4())

    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=tenant_a,
            call_number="CALL-AUDIT-002",
            incident_type="medical",
            created_by_user_id=user_id,
        )
        await ChartService.audit(
            session=session,
            tenant_id=tenant_b,
            chart_id=chart.id,
            user_id=user_id,
            action="wrong_tenant_entry",
            detail={"source": "regression"},
        )

        payload = await get_audit_log(
            chart_id=chart.id,
            session=session,
            current_user=CurrentUser(user_id=user_id, tenant_id=tenant_a),
        )

        assert payload["count"] == 1
        assert payload["entries"][0]["action"] == "chart_created"


@pytest.mark.asyncio
async def test_generate_export_failure_persists_validation_details_and_audit(test_db, monkeypatch) -> None:
    tenant_id = str(uuid4())
    user_id = str(uuid4())

    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=tenant_id,
            call_number="CALL-AUDIT-003",
            incident_type="medical",
            created_by_user_id=user_id,
        )

        async def fake_snapshot(*_args, **_kwargs):
            return ExportReadinessSnapshot(
                ready_for_export=True,
                blocker_count=0,
                warning_count=0,
                mandatory_completion_percentage=100.0,
                missing_mandatory_fields=[],
            )

        async def fake_artifact(*_args, **_kwargs):
            raise ExportValidationFailure(
                "Validation failed",
                {
                    "xsd_valid": False,
                    "schematron_valid": True,
                    "errors": ["sState.01 is required"],
                    "warnings": [],
                    "validator_asset_version": "test-assets",
                },
            )

        chart_id = chart.id

        monkeypatch.setattr(NemsisExportService, "_snapshot", fake_snapshot)
        monkeypatch.setattr(NemsisExportService, "_artifact", fake_artifact)
        monkeypatch.setattr("epcr_app.db._require_database_url", lambda: "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr("epcr_app.db._get_session_maker", lambda _database_url: test_db)

        response = await NemsisExportService.generate_export(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            request=GenerateExportRequest(chart_id=chart_id, trigger_source=ExportTriggerSource.API),
        )

        assert response.success is False
        assert response.failure_type.value == "validation_error"

        attempt = (
            await session.execute(select(NemsisExportAttempt).where(NemsisExportAttempt.chart_id == chart_id))
        ).scalar_one()
        assert attempt.status == "validation_failed"
        assert attempt.validator_errors == ["sState.01 is required"]

        audit_entries = (
            await session.execute(
                select(EpcrAuditLog)
                .where(EpcrAuditLog.chart_id == chart_id)
                .order_by(EpcrAuditLog.performed_at.asc())
            )
        ).scalars().all()
        assert audit_entries[-1].action == "nemsis_export_validation_failed"


@pytest.mark.asyncio
async def test_generate_export_success_persists_artifact_metadata_and_audit(test_db, monkeypatch) -> None:
    tenant_id = str(uuid4())
    user_id = str(uuid4())

    async with test_db() as session:
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=tenant_id,
            call_number="CALL-AUDIT-004",
            incident_type="medical",
            created_by_user_id=user_id,
        )

        async def fake_snapshot(*_args, **_kwargs):
            return ExportReadinessSnapshot(
                ready_for_export=True,
                blocker_count=0,
                warning_count=0,
                mandatory_completion_percentage=100.0,
                missing_mandatory_fields=[],
            )

        xml_bytes = b"<StateDataSet />"
        checksum = NemsisXmlBuilder.compute_sha256(xml_bytes)

        async def fake_artifact(*_args, **_kwargs):
            return (
                xml_bytes,
                f"nemsis/{tenant_id}/{chart.id}/1.xml",
                checksum,
                {
                    "valid": True,
                    "xsd_valid": True,
                    "schematron_valid": True,
                    "errors": [],
                    "warnings": [],
                },
            )

        class FakeBody:
            def read(self) -> bytes:
                return xml_bytes

        class FakeS3Client:
            def get_object(self, *, Bucket, Key):  # noqa: N803
                return {"Body": FakeBody()}

        chart_id = chart.id

        monkeypatch.setattr(NemsisExportService, "_snapshot", fake_snapshot)
        monkeypatch.setattr(NemsisExportService, "_artifact", fake_artifact)
        monkeypatch.setattr("epcr_app.db._require_database_url", lambda: "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr("epcr_app.db._get_session_maker", lambda _database_url: test_db)
        monkeypatch.setattr("epcr_app.services_export._get_s3_client", lambda: FakeS3Client())
        monkeypatch.setattr("epcr_app.services_export._get_s3_bucket", lambda: "adaptix-test-exports")

        response = await NemsisExportService.generate_export(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            request=GenerateExportRequest(chart_id=chart_id, trigger_source=ExportTriggerSource.API),
        )

        assert response.success is True
        assert response.artifact is not None
        assert response.artifact.storage_key is not None

        async with test_db() as verify_session:
            attempt = (
                await verify_session.execute(select(NemsisExportAttempt).where(NemsisExportAttempt.chart_id == chart_id))
            ).scalar_one()
            assert attempt.status == "generated"
            assert attempt.artifact_storage_key is not None
            assert attempt.artifact_file_name is not None

            artifact_bytes, file_name, mime_type, artifact_checksum = await NemsisExportService.get_export_artifact(
                verify_session,
                tenant_id=tenant_id,
                export_id=attempt.id,
            )
            assert artifact_bytes == xml_bytes
            assert file_name.endswith(".xml")
            assert mime_type == "application/xml"
            assert artifact_checksum == checksum

            audit_entries = (
                await verify_session.execute(
                    select(EpcrAuditLog)
                    .where(EpcrAuditLog.chart_id == chart_id)
                    .order_by(EpcrAuditLog.performed_at.asc())
                )
            ).scalars().all()
            assert audit_entries[-1].action == "nemsis_export_generated"