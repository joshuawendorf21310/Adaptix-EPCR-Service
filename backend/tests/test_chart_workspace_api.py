"""API-level tests for the chart workspace router.

Verifies the FastAPI router enforces auth, returns truthful payloads, and
delegates to the canonical chart service. Uses dependency overrides for
both ``get_current_user`` and ``get_session`` so the test is hermetic and
does not require live authentication infrastructure.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.api_chart_workspace import router as chart_workspace_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base


@pytest_asyncio.fixture
async def workspace_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(chart_workspace_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-api",
            user_id="user-api",
            email="api@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield app
    await engine.dispose()


def test_create_get_status_workspace_round_trip(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={"call_number": "API-CALL-001", "incident_type": "medical"},
        )
        assert create.status_code == 201, create.text
        body = create.json()
        chart_id = body["chart"]["id"]

        get_resp = client.get(f"/api/v1/epcr/chart-workspaces/{chart_id}")
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        assert get_body["chart"]["call_number"] == "API-CALL-001"
        assert get_body["submission_status"]["status"] == "submission_unavailable"
        assert get_body["export_status"]["status"] == "not_generated"

        status_resp = client.get(f"/api/v1/epcr/chart-workspaces/{chart_id}/status")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["chart_id"] == chart_id
        assert status_body["submission_status"] == "submission_unavailable"


def test_unsupported_section_returns_422_field_not_mapped(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={"call_number": "API-CALL-002", "incident_type": "medical"},
        )
        chart_id = create.json()["chart"]["id"]
        resp = client.patch(
            f"/api/v1/epcr/chart-workspaces/{chart_id}/sections/disposition",
            json={"foo": "bar"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["field_not_mapped"] == ["disposition"]


def test_finalize_blocks_when_compliance_incomplete(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={"call_number": "API-CALL-003", "incident_type": "medical"},
        )
        chart_id = create.json()["chart"]["id"]
        resp = client.post(f"/api/v1/epcr/chart-workspaces/{chart_id}/finalize")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "missing_mandatory_fields" in detail


def test_unknown_chart_returns_404(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        resp = client.get("/api/v1/epcr/chart-workspaces/does-not-exist")
        assert resp.status_code == 404


def test_export_endpoint_reports_not_generated(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={"call_number": "API-CALL-004", "incident_type": "medical"},
        )
        chart_id = create.json()["chart"]["id"]
        resp = client.post(f"/api/v1/epcr/chart-workspaces/{chart_id}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "export_not_generated"
        assert body["last_export_id"] is None


def test_submit_endpoint_reports_unavailable(workspace_app) -> None:
    with TestClient(workspace_app) as client:
        create = client.post(
            "/api/v1/epcr/chart-workspaces",
            json={"call_number": "API-CALL-005", "incident_type": "medical"},
        )
        chart_id = create.json()["chart"]["id"]
        resp = client.post(f"/api/v1/epcr/chart-workspaces/{chart_id}/submit")
        assert resp.status_code == 200
        assert resp.json()["status"] == "submission_unavailable"


def test_protected_nemsis_files_have_zero_diff() -> None:
    """Slice 3B+ NEMSIS files must remain untouched by the workspace agent."""
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    protected = [
        "backend/epcr_app/nemsis_registry_importer.py",
        "backend/epcr_app/nemsis_registry_service.py",
        "backend/epcr_app/api_nemsis_registry.py",
        "backend/epcr_app/api_nemsis.py",
        "backend/epcr_app/api_nemsis_packs.py",
        "backend/epcr_app/api_nemsis_submissions.py",
        "backend/epcr_app/api_nemsis_validation.py",
        "backend/epcr_app/api_export.py",
        "backend/epcr_app/nemsis_finalization_gate.py",
    ]
    for path in protected:
        full = repo_root / path
        if not full.exists():
            continue
        result = subprocess.run(
            ["git", "diff", "--stat", "--", path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        # If git is not available skip silently rather than fabricate a pass
        if result.returncode != 0:
            pytest.skip(f"git not available or path outside repo for {path}")
        assert not result.stdout.strip(), f"protected file modified: {path}\n{result.stdout}"
