"""Local EPCR lifecycle proof using the real seed, workspace, and export services.

This regression exercises the truthful local path that remains available when
live infrastructure credentials are absent: seed a deterministic chart, load it
through the workspace facade, persist a real narrative update, then generate and
retrieve a real XML export while stubbing only artifact storage.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from adaptix_contracts.schemas.nemsis_exports import (
    ExportLifecycleStatus,
    ExportScope,
    ExportTriggerSource,
    GenerateExportRequest,
)
from epcr_app.chart_workspace_service import ChartWorkspaceService
from epcr_app.db import _get_session_maker, _require_database_url, init_db
from epcr_app.dependencies import CurrentUser
from epcr_app.models import ClinicalNote
from epcr_app.models_export import NemsisExportAttempt
from epcr_app.services_export import NemsisExportService

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_SCRIPT_PATH = _REPO_ROOT / "scripts" / "seed_demo_pcr.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo_pcr", _SEED_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load seed script from {_SEED_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _BodyReader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, object]] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):  # noqa: N803
        self.objects[(Bucket, Key)] = {
            "body": Body,
            "content_type": ContentType,
            "server_side_encryption": ServerSideEncryption,
        }

    def get_object(self, *, Bucket, Key):  # noqa: N803
        record = self.objects[(Bucket, Key)]
        return {"Body": _BodyReader(record["body"])}


@pytest.mark.asyncio
async def test_seeded_chart_updates_and_exports_locally(monkeypatch) -> None:
    seed_module = _load_seed_module()
    fake_s3 = _FakeS3Client()

    monkeypatch.setenv("NEMSIS_STATE_CODE", "12")
    monkeypatch.setenv("NEMSIS_EXPORT_S3_BUCKET", "adaptix-test-exports")
    monkeypatch.setattr("epcr_app.services_export._get_s3_client", lambda: fake_s3)
    monkeypatch.setattr("epcr_app.services_export._get_s3_bucket", lambda: "adaptix-test-exports")

    await init_db()
    seed_result = await seed_module._seed(os.environ["EPCR_DATABASE_URL"])
    assert seed_result["status"] == "PASS"

    chart_id = seed_module._det("chart")
    tenant_id = UUID(seed_module.DEMO_TENANT_ID)
    user_id = UUID(seed_module.DEMO_USER_ID)
    tenant_id_str = seed_module.DEMO_TENANT_ID
    user_id_str = seed_module.DEMO_USER_ID
    current_user = CurrentUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email="demo.clinician@example.test",
    )
    narrative_text = (
        "Crew updated the report after reassessment; chest pain improved after nitroglycerin "
        "and the receiving facility received the transmitted 12-lead."
    )

    session_maker = _get_session_maker(_require_database_url())

    async with session_maker() as session:
        workspace = await ChartWorkspaceService.get_workspace(session, current_user, chart_id)
        assert workspace["chart"]["status"] == "under_review"

        updated_workspace = await ChartWorkspaceService.update_workspace_section(
            session,
            current_user,
            chart_id,
            "narrative",
            {
                "raw_text": narrative_text,
                "source": "manual_entry",
                "review_state": "pending_review",
            },
        )
        assert any(note["raw_text"] == narrative_text for note in updated_workspace["narrative"])

        readiness = await ChartWorkspaceService.get_workspace_readiness(session, current_user, chart_id)
        assert readiness["readiness"]["compliance_status"] == "fully_compliant"
        assert readiness["readiness"]["is_fully_compliant"] is True

        response = await NemsisExportService.generate_export(
            session,
            tenant_id=tenant_id_str,
            user_id=user_id_str,
            request=GenerateExportRequest(
                chart_id=chart_id,
                scope=ExportScope.SINGLE_RECORD,
                trigger_source=ExportTriggerSource.CHART,
                allow_retry_of_failed_attempt=True,
            ),
        )

        assert response.success is True
        assert response.status == ExportLifecycleStatus.GENERATED
        assert response.failure_reason is None
        assert response.artifact is not None

    async with session_maker() as verify_session:
        notes = (
            await verify_session.execute(
                select(ClinicalNote)
                .where(ClinicalNote.chart_id == chart_id)
                .order_by(ClinicalNote.updated_at.desc())
            )
        ).scalars().all()
        assert notes[0].raw_text == narrative_text

        attempt = (
            await verify_session.execute(
                select(NemsisExportAttempt)
                .where(NemsisExportAttempt.chart_id == chart_id)
                .order_by(NemsisExportAttempt.created_at.desc())
            )
        ).scalars().first()
        assert attempt is not None
        assert attempt.status == ExportLifecycleStatus.GENERATED.value
        assert attempt.failure_reason is None
        assert attempt.artifact_storage_key == response.artifact.storage_key
        assert attempt.artifact_checksum_sha256 == response.artifact.checksum_sha256

        artifact_bytes, file_name, mime_type, checksum = await NemsisExportService.get_export_artifact(
            verify_session,
            tenant_id=tenant_id_str,
            export_id=attempt.id,
        )

        assert artifact_bytes.startswith(b"<?xml")
        assert file_name.endswith(".xml")
        assert mime_type == "application/xml"
        assert checksum == response.artifact.checksum_sha256
        assert (
            "adaptix-test-exports",
            response.artifact.storage_key,
        ) in fake_s3.objects