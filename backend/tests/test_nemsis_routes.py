"""Regression tests for NEMSIS validation, readiness, and export-preview API routes.

These tests validate response structure, deterministic compliance propagation,
and HTTP contract behavior for shared NEMSIS validation infrastructure.
"""

from __future__ import annotations

from uuid import UUID
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis import router
from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user


TENANT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"


MOCK_COMPLIANCE_READY = {
    "is_fully_compliant": True,
    "compliance_percentage": 100.0,
    "mandatory_fields_filled": 42,
    "total_mandatory_fields": 42,
    "missing_mandatory_fields": [],
}

MOCK_COMPLIANCE_BLOCKED = {
    "is_fully_compliant": False,
    "compliance_percentage": 78.5,
    "mandatory_fields_filled": 33,
    "total_mandatory_fields": 42,
    "missing_mandatory_fields": ["ePatient.10", "eTimes.01", "eScene.01"],
}


def build_test_client() -> TestClient:
    """Create isolated FastAPI test client with dependency overrides."""
    app = FastAPI()

    async def override_session():
        yield object()

    def override_current_user() -> CurrentUser:
        return CurrentUser(
            user_id=UUID(USER_ID),
            tenant_id=UUID(TENANT_ID),
            email="test@example.com",
            roles=["ems"],
        )

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user
    app.include_router(router)

    return TestClient(app)


class TestValidateRoute:
    """Tests for POST /api/v1/epcr/nemsis/validate."""

    def test_validate_ready_chart_returns_valid_true(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.post(
                "/api/v1/epcr/nemsis/validate",
                params={"chart_id": "chart-001", "state_code": "CA"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["chart_id"] == "chart-001"
        assert body["blockers"] == []
        assert body["mapped_elements"] == 42

    def test_validate_blocked_chart_returns_valid_false_with_blockers(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.post(
                "/api/v1/epcr/nemsis/validate",
                params={"chart_id": "chart-002", "state_code": "CA"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert len(body["blockers"]) == 3
        assert body["blockers"][0]["field"] == "ePatient.10"
        assert body["blockers"][0]["type"] == "blocker"

    def test_validate_without_propagated_tenant_header_uses_jwt_context(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.post(
                "/api/v1/epcr/nemsis/validate",
                params={"chart_id": "chart-001"},
            )

        assert resp.status_code == 200
        assert resp.json()["valid"] is True


class TestReadinessRoute:
    """Tests for GET /api/v1/epcr/nemsis/readiness."""

    def test_readiness_ready_chart_returns_ready_true(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/readiness",
                params={"chart_id": "chart-001"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ready_for_export"] is True
        assert body["blockers"] == []

    def test_readiness_blocked_chart_returns_ready_false(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/readiness",
                params={"chart_id": "chart-002"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ready_for_export"] is False
        assert len(body["blockers"]) == 3

    def test_readiness_without_propagated_tenant_header_uses_jwt_context(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/readiness",
                params={"chart_id": "chart-001"},
            )

        assert resp.status_code == 200
        assert resp.json()["ready_for_export"] is True


class TestExportPreviewRoute:
    """Tests for GET /api/v1/epcr/nemsis/export-preview."""

    def test_export_preview_ready_chart_can_export_true(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/export-preview",
                params={"chart_id": "chart-001", "state_dataset": "CA-3.5.1"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["can_export"] is True
        assert body["nemsis_version"] == "3.5.1"
        assert body["state_dataset"] == "CA-3.5.1"

    def test_export_preview_blocked_chart_can_export_false(self) -> None:
        client = build_test_client()

        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/export-preview",
                params={"chart_id": "chart-002", "state_dataset": "CA-3.5.1"},
                headers={"X-Tenant-ID": TENANT_ID},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["can_export"] is False
        assert len(body["blockers"]) == 3