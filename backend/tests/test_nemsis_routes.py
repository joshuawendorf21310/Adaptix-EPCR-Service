"""Tests for NEMSIS validation and readiness API routes.

Validates that NEMSIS routes return correctly structured responses
and that readiness/validation logic flows through ChartService correctly.
Uses FastAPI TestClient with patched ChartService to avoid DB dependency.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from epcr_app.main import app
from epcr_app.api_nemsis import router

client = TestClient(app)

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


class TestValidateRoute:
    """Tests for POST /api/v1/epcr/nemsis/validate."""

    def test_validate_ready_chart_returns_valid_true(self):
        """Validate endpoint returns valid=True when chart is fully compliant."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.post(
                "/api/v1/epcr/nemsis/validate",
                params={"chart_id": "chart-001", "state_code": "CA"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["chart_id"] == "chart-001"
        assert body["blockers"] == []
        assert body["mapped_elements"] == 42

    def test_validate_blocked_chart_returns_valid_false_with_blockers(self):
        """Validate endpoint returns valid=False with blockers when fields are missing."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.post(
                "/api/v1/epcr/nemsis/validate",
                params={"chart_id": "chart-002", "state_code": "CA"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert len(body["blockers"]) == 3
        assert body["blockers"][0]["field"] == "ePatient.10"
        assert body["blockers"][0]["type"] == "blocker"

    def test_validate_missing_tenant_id_returns_400(self):
        """Validate endpoint returns 400 when X-Tenant-ID header is absent."""
        resp = client.post(
            "/api/v1/epcr/nemsis/validate",
            params={"chart_id": "chart-001"},
        )
        assert resp.status_code == 400


class TestReadinessRoute:
    """Tests for GET /api/v1/epcr/nemsis/readiness."""

    def test_readiness_ready_chart_returns_ready_true(self):
        """Readiness endpoint returns ready_for_export=True when chart is compliant."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/readiness",
                params={"chart_id": "chart-001"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready_for_export"] is True
        assert body["blockers"] == []

    def test_readiness_blocked_chart_returns_ready_false(self):
        """Readiness endpoint returns ready_for_export=False when fields are missing."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/readiness",
                params={"chart_id": "chart-002"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready_for_export"] is False
        assert len(body["blockers"]) == 3

    def test_readiness_missing_tenant_id_returns_400(self):
        """Readiness endpoint returns 400 when X-Tenant-ID header is absent."""
        resp = client.get(
            "/api/v1/epcr/nemsis/readiness",
            params={"chart_id": "chart-001"},
        )
        assert resp.status_code == 400


class TestExportPreviewRoute:
    """Tests for GET /api/v1/epcr/nemsis/export-preview."""

    def test_export_preview_ready_chart_can_export_true(self):
        """Export preview returns can_export=True for compliant chart."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_READY,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/export-preview",
                params={"chart_id": "chart-001", "state_dataset": "CA-3.5.1"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["can_export"] is True
        assert body["nemsis_version"] == "3.5.1"
        assert body["state_dataset"] == "CA-3.5.1"

    def test_export_preview_blocked_chart_can_export_false(self):
        """Export preview returns can_export=False for non-compliant chart."""
        with patch(
            "epcr_app.api_nemsis.ChartService.check_nemsis_compliance",
            new_callable=AsyncMock,
            return_value=MOCK_COMPLIANCE_BLOCKED,
        ):
            resp = client.get(
                "/api/v1/epcr/nemsis/export-preview",
                params={"chart_id": "chart-002", "state_dataset": "CA-3.5.1"},
                headers={"X-Tenant-ID": "tenant-001"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["can_export"] is False
        assert len(body["blockers"]) == 3
