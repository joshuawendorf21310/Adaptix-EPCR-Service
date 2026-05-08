from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import epcr_app.models_tac_schematron  # noqa: F401
from epcr_app.api_tac_schematron_packages import router as tac_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base
from epcr_app.models_tac_schematron import TacSchematronAuditLog
from epcr_app.tac_schematron_package_service import TacSchematronPackageService


DEM_SCH = b"""<?xml version='1.0'?>
<sch:schema xmlns:sch='http://purl.oclc.org/dsdl/schematron'>
  <sch:pattern id='dem'>
    <sch:rule context='DEMDataSet'>
      <sch:assert role='warning' test='true()'>DEM warning message</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
"""

EMS_SCH = b"""<?xml version='1.0'?>
<sch:schema xmlns:sch='http://purl.oclc.org/dsdl/schematron'>
  <sch:pattern id='ems'>
    <sch:rule context='EMSDataSet'>
      <sch:assert role='error' test='true()'>EMS error message</sch:assert>
      <sch:report role='warning' test='true()'>EMS warning message</sch:report>
    </sch:rule>
  </sch:pattern>
</sch:schema>
"""

UNKNOWN_SCH = b"""<?xml version='1.0'?>
<sch:schema xmlns:sch='http://purl.oclc.org/dsdl/schematron'>
  <sch:pattern id='unknown'>
    <sch:rule context='SomethingElse'>
      <sch:assert role='warning' test='true()'>Unknown dataset</sch:assert>
    </sch:rule>
  </sch:pattern>
</sch:schema>
"""


@pytest_asyncio.fixture
async def package_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILES_S3_BUCKET", "")
    monkeypatch.setattr("epcr_app.tac_schematron_package_service._DEFAULT_STORAGE", tmp_path / "storage")
    monkeypatch.setattr("epcr_app.tac_schematron_package_service._LOCAL_CACHE", tmp_path / "cache")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(tac_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-tac",
            user_id="user-tac",
            email="tac@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    yield app, sessionmaker, tmp_path
    await engine.dispose()


def test_upload_dem_and_ems_creates_inactive_package_with_preview(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/epcr/nemsis/schematron-packages/upload",
            data={"package_label": "TAC Demo Package"},
            files=[
                ("files", ("demo-dem.sch", DEM_SCH, "application/xml")),
                ("files", ("demo-ems.sch", EMS_SCH, "application/xml")),
            ],
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "inactive"
        assert len(body["assets"]) == 2
        assets = {asset["dataset_type"]: asset for asset in body["assets"]}
        assert assets["DEMDataSet"]["sha256"] == hashlib.sha256(DEM_SCH).hexdigest()
        assert assets["EMSDataSet"]["warning_count"] == 1
        assert assets["EMSDataSet"]["error_count"] == 1
        assert "EMS error message" in assets["EMSDataSet"]["natural_language_messages"]


def test_invalid_xml_rejected(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/epcr/nemsis/schematron-packages/upload",
            data={"package_label": "Broken"},
            files=[("files", ("broken.sch", b"<sch:schema>", "application/xml"))],
        )
        assert response.status_code == 422
        assert response.json()["detail"]["message"] == "Invalid XML uploaded for TAC Schematron package"


def test_unknown_package_cannot_activate(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/epcr/nemsis/schematron-packages/upload",
            data={"package_label": "Unknown"},
            files=[("files", ("unknown.sch", UNKNOWN_SCH, "application/xml"))],
        )
        assert upload.status_code == 201, upload.text
        package_id = upload.json()["id"]

        activate = client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/activate")
        assert activate.status_code == 422
        assert "known dataset types" in activate.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_activation_is_tenant_scoped_and_selected_by_validation(package_app) -> None:
    app, sessionmaker, _ = package_app
    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/epcr/nemsis/schematron-packages/upload",
            data={"package_label": "Scoped"},
            files=[
                ("files", ("scoped-dem.sch", DEM_SCH, "application/xml")),
                ("files", ("scoped-ems.sch", EMS_SCH, "application/xml")),
            ],
        )
        package_id = upload.json()["id"]
        activate = client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/activate")
        assert activate.status_code == 200, activate.text

    async with sessionmaker() as session:
        resolved = await TacSchematronPackageService(session).resolve_validator_for_xml(
            tenant_id="tenant-tac",
            xml_bytes=b"<EMSDataSet />",
        )
        assert resolved.provenance.validator_source == "tenant_active_package"
        assert resolved.provenance.package_id == package_id
        assert resolved.provenance.dataset_type == "EMSDataSet"


@pytest.mark.asyncio
async def test_activation_writes_audit_and_no_fake_submission_state(package_app) -> None:
    app, sessionmaker, _ = package_app
    with TestClient(app) as client:
        upload = client.post(
            "/api/v1/epcr/nemsis/schematron-packages/upload",
            data={"package_label": "Audit"},
            files=[
                ("files", ("audit-dem.sch", DEM_SCH, "application/xml")),
                ("files", ("audit-ems.sch", EMS_SCH, "application/xml")),
            ],
        )
        package_id = upload.json()["id"]
        activate = client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/activate")
        assert activate.status_code == 200, activate.text
        assert "submission" not in json.dumps(activate.json()).lower()
        assert "certif" not in json.dumps(activate.json()).lower()

    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(TacSchematronAuditLog).where(TacSchematronAuditLog.package_id == package_id)
            )
        ).scalars().all()
        actions = {row.action for row in rows}
        assert "tac_schematron_package_uploaded" in actions
        assert "tac_schematron_package_activated" in actions
