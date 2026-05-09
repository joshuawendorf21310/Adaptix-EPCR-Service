from __future__ import annotations

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

DEM_SCH = b"""<?xml version='1.0'?><sch:schema xmlns:sch='http://purl.oclc.org/dsdl/schematron'><sch:pattern><sch:rule context='DEMDataSet'><sch:assert role='warning' test='true()'>DEM warning</sch:assert></sch:rule></sch:pattern></sch:schema>"""
EMS_SCH = b"""<?xml version='1.0'?><sch:schema xmlns:sch='http://purl.oclc.org/dsdl/schematron'><sch:pattern><sch:rule context='EMSDataSet'><sch:assert role='error' test='true()'>EMS error</sch:assert></sch:rule></sch:pattern></sch:schema>"""


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
            tenant_id="tenant-delete",
            user_id="user-delete",
            email="delete@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    yield app, sessionmaker, tmp_path
    await engine.dispose()


def _upload(client: TestClient, label: str) -> str:
    response = client.post(
        "/api/v1/epcr/nemsis/schematron-packages/upload",
        data={"package_label": label},
        files=[
            ("files", (f"{label}-dem.sch", DEM_SCH, "application/xml")),
            ("files", (f"{label}-ems.sch", EMS_SCH, "application/xml")),
        ],
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_inactive_package_can_be_deleted(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        package_id = _upload(client, "inactive")
        deleted = client.request("DELETE", f"/api/v1/epcr/nemsis/schematron-packages/{package_id}", json={"reason": "reset"})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["status"] == "deleted"


def test_active_package_cannot_be_deleted_until_deactivated(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        package_id = _upload(client, "active")
        activate = client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/activate")
        assert activate.status_code == 200, activate.text
        deleted = client.request("DELETE", f"/api/v1/epcr/nemsis/schematron-packages/{package_id}", json={"reason": "reset"})
        assert deleted.status_code == 409
        assert "deactivated before deletion" in deleted.json()["detail"]["message"]


def test_deactivated_package_can_be_deleted(package_app) -> None:
    app, _, _ = package_app
    with TestClient(app) as client:
        package_id = _upload(client, "deactivate")
        assert client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/activate").status_code == 200
        assert client.post(f"/api/v1/epcr/nemsis/schematron-packages/{package_id}/deactivate").status_code == 200
        deleted = client.request("DELETE", f"/api/v1/epcr/nemsis/schematron-packages/{package_id}", json={"reason": "done"})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_at"] is not None


@pytest.mark.asyncio
async def test_delete_is_tenant_scoped_and_audited_and_falls_back_to_baked(package_app) -> None:
    app, sessionmaker, tmp_path = package_app
    cta_template_dir = Path(__file__).resolve().parent.parent / "nemsis" / "templates" / "cta"
    with TestClient(app) as client:
        package_id = _upload(client, "tenant")
        deleted = client.request("DELETE", f"/api/v1/epcr/nemsis/schematron-packages/{package_id}", json={"reason": "cleanup"})
        assert deleted.status_code == 200, deleted.text

    async with sessionmaker() as session:
        resolved = await TacSchematronPackageService(session).resolve_validator_for_xml(
            tenant_id="tenant-delete",
            xml_bytes=b"<EMSDataSet />",
        )
        assert resolved.provenance.validator_source == "baked_default"
        audit_rows = (
            await session.execute(
                select(TacSchematronAuditLog).where(TacSchematronAuditLog.package_id == package_id)
            )
        ).scalars().all()
        assert any(row.action == "tac_schematron_package_deleted" for row in audit_rows)

    assert cta_template_dir.exists()
    assert (tmp_path / "storage").exists()
