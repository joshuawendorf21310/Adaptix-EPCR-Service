"""API contract test for the 3D Physical Assessment anatomical_findings.

PATCH the assessment section with an anatomical findings payload, then
GET the workspace and assert the findings reload, the capability flag
is ``live``, and audit rows are persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.api_chart_workspace import router as chart_workspace_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import AgencyProfile, Base, EpcrAuditLog


@pytest_asyncio.fixture
async def workspace_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker() as session:
        now = datetime.now(UTC)
        session.add(
            AgencyProfile(
                id=str(uuid4()),
                tenant_id="tenant-anat",
                agency_code="MADISONEMS",
                agency_name="Madison EMS",
                numbering_policy_json="{}",
                activated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    app = FastAPI()
    app.include_router(chart_workspace_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-anat",
            user_id="user-anat",
            email="api@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield app, sessionmaker
    await engine.dispose()


def _finding(**overrides):
    payload = {
        "regionId": "region_head",
        "regionLabel": "Head",
        "bodyView": "front",
        "findingType": "laceration",
        "severity": "moderate",
        "laterality": "midline",
        "painScale": 6,
        "burnTbsaPercent": None,
        "cms": {
            "pulse": "present",
            "motor": "intact",
            "sensation": "intact",
            "capillaryRefill": "normal",
        },
        "pertinentNegative": False,
        "notes": "3cm lac",
        "assessedAt": "2026-05-12T10:00:00Z",
        "assessedBy": "user-anat",
    }
    payload.update(overrides)
    return payload


def test_patch_assessment_persists_anatomical_findings(workspace_app) -> None:
    app, sessionmaker = workspace_app
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={
                "call_number": "ANAT-001",
                "incident_type": "trauma",
                "agency_code": "MADISONEMS",
            },
        )
        assert create.status_code == 201, create.text
        chart_id = create.json()["chart"]["id"]

        patch = client.patch(
            f"/api/v1/epcr/chart-workspaces/{chart_id}/sections/assessment",
            json={
                "anatomical_findings": [
                    _finding(),
                    _finding(regionId="region_chest", regionLabel="Chest"),
                ]
            },
        )
        assert patch.status_code == 200, patch.text
        body = patch.json()
        assert "anatomical_findings" in body["assessment"]
        assert len(body["assessment"]["anatomical_findings"]) == 2
        assert (
            body["capabilities"]["assessment_anatomical"]["capability"] == "live"
        )

        get_resp = client.get(f"/api/v1/epcr/chart-workspaces/{chart_id}")
        assert get_resp.status_code == 200
        reloaded = get_resp.json()
        assert len(reloaded["assessment"]["anatomical_findings"]) == 2
        regions = sorted(
            f["regionId"] for f in reloaded["assessment"]["anatomical_findings"]
        )
        assert regions == ["region_chest", "region_head"]
        # Audit rows must be persisted
        import asyncio

        async def _count():
            async with sessionmaker() as session:
                rows = (
                    await session.execute(
                        select(EpcrAuditLog).where(
                            EpcrAuditLog.chart_id == chart_id,
                            EpcrAuditLog.action.like("anatomical_finding.%"),
                        )
                    )
                ).scalars().all()
                return len(rows)

        count = asyncio.get_event_loop().run_until_complete(_count())
        assert count == 2


def test_patch_invalid_payload_returns_400(workspace_app) -> None:
    app, _ = workspace_app
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={
                "call_number": "ANAT-002",
                "incident_type": "medical",
                "agency_code": "MADISONEMS",
            },
        )
        chart_id = create.json()["chart"]["id"]
        patch = client.patch(
            f"/api/v1/epcr/chart-workspaces/{chart_id}/sections/assessment",
            json={
                "anatomical_findings": [
                    _finding(regionId="not_a_region"),
                ]
            },
        )
        assert patch.status_code == 400, patch.text
        detail = patch.json()["detail"]
        assert "errors" in detail
        assert any(
            "regionId" in e["field"] for e in detail["errors"]
        )
