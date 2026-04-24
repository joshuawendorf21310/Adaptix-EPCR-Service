"""Regression tests for the local CTA testing portal auth and run API.

These tests prove the local portal can authenticate, encrypt credential input,
execute a CTA run through the real service surface, and preserve browser-readable
artifact evidence without depending on the platform auth gateway.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_auth import router as auth_router
from epcr_app.api_nemsis_cta_testing import router as portal_router


def build_client(monkeypatch, tmp_path: Path) -> TestClient:
    """Build a FastAPI client with isolated CTA portal storage.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        tmp_path: Temporary directory.

    Returns:
        TestClient: Isolated test client.
    """

    monkeypatch.setenv("EPCR_PORTAL_LOGIN_EMAIL", "local.operator@adaptix.dev")
    monkeypatch.setenv("EPCR_PORTAL_LOGIN_PASSWORD", "AdaptixLocalPortal!2026")
    monkeypatch.setenv("EPCR_PORTAL_TENANT_SLUG", "local-cta-lab")
    monkeypatch.setenv("EPCR_PORTAL_TENANT_ID", "11111111-1111-4111-8111-111111111111")
    monkeypatch.setenv("EPCR_PORTAL_USER_ID", "22222222-2222-4222-8222-222222222222")
    monkeypatch.setenv("EPCR_PORTAL_LOGIN_ROLES", "epcr,nemsis-testing")
    monkeypatch.setenv("EPCR_PORTAL_JWT_SECRET", "test-secret-for-cta-portal")
    monkeypatch.setenv("CTA_TESTING_PORTAL_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("CTA_TESTING_PORTAL_SECRET_ROOT", str(tmp_path / "secret"))

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(portal_router)
    return TestClient(app)


def login(client: TestClient) -> dict[str, str]:
    """Log in through the local CTA portal auth route.

    Args:
        client: Test client.

    Returns:
        dict[str, str]: Token payload.
    """

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "local.operator@adaptix.dev",
            "password": "AdaptixLocalPortal!2026",
            "tenant_slug": "local-cta-lab",
        },
    )
    assert response.status_code == 200
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    """Return authorization headers for the portal.

    Args:
        token: Access token.

    Returns:
        dict[str, str]: Authorization header mapping.
    """

    return {"Authorization": f"Bearer {token}"}


def test_local_auth_login_validate_refresh_and_logout(monkeypatch, tmp_path: Path) -> None:
    """The local CTA portal auth flow should satisfy the Web App contract."""

    client = build_client(monkeypatch, tmp_path)
    tokens = login(client)

    validate_response = client.get("/api/v1/auth/validate", headers=auth_headers(tokens["token"]))
    assert validate_response.status_code == 200
    claims = validate_response.json()
    assert claims["email"] == "local.operator@adaptix.dev"
    assert claims["tenant_id"] == "11111111-1111-4111-8111-111111111111"

    refresh_response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 200
    refreshed = refresh_response.json()
    assert refreshed["token"] != tokens["token"]

    logout_response = client.post("/api/v1/auth/logout", headers=auth_headers(refreshed["token"]))
    assert logout_response.status_code == 204


def test_portal_bootstrap_and_encrypted_credentials_flow(monkeypatch, tmp_path: Path) -> None:
    """The portal should advertise scenarios and persist encrypted VSA credentials."""

    client = build_client(monkeypatch, tmp_path)
    tokens = login(client)
    headers = auth_headers(tokens["token"])

    bootstrap_response = client.get("/api/v1/nemsis/cta/testing/scenarios", headers=headers)
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()
    assert any(item["scenario_code"] == "2025_DEM_1" for item in bootstrap["items"])
    assert any(item["scenario_code"] == "2025_EMS_1" for item in bootstrap["items"])
    assert bootstrap["credentials"]["saved"] is False

    save_response = client.post(
        "/api/v1/nemsis/cta/testing/settings/credentials",
        headers=headers,
        json={
            "username": "FusionEMSQuantum",
            "password": "Addyson12345!",
            "organization": "FusionEMSQuantum",
            "endpoint": "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws",
        },
    )
    assert save_response.status_code == 200
    status_payload = save_response.json()
    assert status_payload["saved"] is True
    assert status_payload["username_masked"] is not None
    assert status_payload["organization"] == "FusionEMSQuantum"

    encrypted_store = tmp_path / "secret" / "credentials.enc"
    assert encrypted_store.exists()
    assert b"Addyson12345!" not in encrypted_store.read_bytes()


def test_portal_run_preserves_artifacts_and_redacts_password(monkeypatch, tmp_path: Path) -> None:
    """Running a CTA scenario should preserve all artifacts for browser inspection."""

    client = build_client(monkeypatch, tmp_path)
    tokens = login(client)
    headers = auth_headers(tokens["token"])

    save_response = client.post(
        "/api/v1/nemsis/cta/testing/settings/credentials",
        headers=headers,
        json={
            "username": "FusionEMSQuantum",
            "password": "Addyson12345!",
            "organization": "FusionEMSQuantum",
            "endpoint": "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws",
        },
    )
    assert save_response.status_code == 200

    monkeypatch.setattr(
        "epcr_app.cta_testing_portal._generate_pretesting_xml_or_500",
        lambda scenario_id, scenario: b"<EMSDataSet><eRecord.01>test</eRecord.01></EMSDataSet>",
    )

    class FakeValidator:
        """Deterministic validator double used for portal run tests."""

        def validate_xml(self, xml_bytes: bytes) -> dict[str, object]:
            return {
                "valid": True,
                "validation_skipped": False,
                "xsd_valid": True,
                "schematron_valid": True,
                "xsd_errors": [],
                "schematron_errors": [],
                "schematron_warnings": [],
                "cardinality_errors": [],
            }

    monkeypatch.setattr("epcr_app.cta_testing_portal.NemsisXSDValidator", FakeValidator)

    class FakeResult:
        """Structured fake CTA client result."""

        def to_dict(self) -> dict[str, object]:
            return {
                "integration_enabled": True,
                "submitted": False,
                "request_timestamp_utc": "2026-04-23T00:00:00+00:00",
                "endpoint": "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws",
                "http_status": 200,
                "response_status": "rejected",
                "status_code": "-1",
                "request_handle": None,
                "message": "Login credentials are invalid",
                "request_body": "<ws:password>Addyson12345!</ws:password>",
                "response_body": "<statusCode>-1</statusCode>",
            }

    class FakeClient:
        """Fake CTA submission client for deterministic run tests."""

        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def submit(self, *args, **kwargs) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr("epcr_app.cta_testing_portal.CtaSubmissionClient", FakeClient)

    run_response = client.post(
        "/api/v1/nemsis/cta/testing/runs",
        headers=headers,
        json={"scenario_code": "2025_EMS_1"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["scenario_code"] == "2025_EMS_1"
    assert run_payload["status"] == "cta_failed"
    assert len(run_payload["artifacts"]) >= 5

    list_response = client.get("/api/v1/nemsis/cta/testing/runs", headers=headers)
    assert list_response.status_code == 200
    run_id = list_response.json()["items"][0]["run_id"]

    artifact_response = client.get(
        f"/api/v1/nemsis/cta/testing/runs/{run_id}/artifacts/soap-request.xml",
        headers=headers,
    )
    assert artifact_response.status_code == 200
    artifact_payload = artifact_response.json()
    assert "[REDACTED]" in artifact_payload["content"]
    assert "Addyson12345!" not in artifact_payload["content"]

    summary_path = tmp_path / "runtime" / "runs" / run_id / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["credentials"]["organization"] == "FusionEMSQuantum"