"""Tests for the Internal CTA Testing Workbench API."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_cta_testing import (
    _CTA_2025_TEST_CASES,
    _reset_state_for_tests,
    router as cta_router,
)
from epcr_app.dependencies import CurrentUser, get_current_user


BASE = "/api/v1/epcr/internal/cta-testing"

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "33333333-3333-4333-8333-333333333333"
USER_A = "22222222-2222-4222-8222-222222222222"
USER_B = "44444444-4444-4444-8444-444444444444"

VALID_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<EMSDataSet xmlns="http://www.nemsis.org" '
    b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    b"<Header/></EMSDataSet>"
)


def _user(user_id: str, tenant_id: str) -> CurrentUser:
    return CurrentUser(
        user_id=UUID(user_id),
        tenant_id=UUID(tenant_id),
        email="cta@example.com",
        roles=["clinician"],
    )


def _make_client(user: CurrentUser) -> TestClient:
    app = FastAPI()

    def _override() -> CurrentUser:
        return user

    app.dependency_overrides[get_current_user] = _override
    app.include_router(cta_router)
    return TestClient(app)


def _ensure_bedrock_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state_for_tests()
    _ensure_bedrock_unset(monkeypatch)
    yield
    _reset_state_for_tests()


# --------------------------------------------------------------------------- #
# /test-cases
# --------------------------------------------------------------------------- #


def test_list_test_cases_returns_six_2025_cases() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.get(f"{BASE}/test-cases")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["nemsis_version"] == "3.5.1"
    assert body["nemsis_asset_version"] == "3.5.1.250403CP1"
    ids = [c["test_case_id"] for c in body["test_cases"]]
    assert ids == [c["test_case_id"] for c in _CTA_2025_TEST_CASES]
    assert "2025-DEM1" in ids
    assert "2025-EMS 5-Mental Health Crisis" in ids
    for case in body["test_cases"]:
        assert case["dataset_type"] in {"DEM", "EMS"}
        assert case["fixture_filename"].endswith("_v351.xml")
        assert isinstance(case["fixture_available"], bool)


# --------------------------------------------------------------------------- #
# /uploads
# --------------------------------------------------------------------------- #


def test_upload_xml_returns_metadata_and_checksum() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("rehearsal.xml", VALID_XML, "application/xml")},
        data={"test_case_id": "2025-DEM1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tenant_id"] == TENANT_A
    assert body["filename"] == "rehearsal.xml"
    assert body["suffix"] == ".xml"
    assert body["size_bytes"] == len(VALID_XML)
    assert body["purpose"] == "xml_input"
    assert body["test_case_id"] == "2025-DEM1"
    assert len(body["checksum_sha256"]) == 64


@pytest.mark.parametrize(
    "filename,suffix,purpose",
    [
        ("schema.xsd", ".xsd", "xsd_asset"),
        ("rules.sch", ".sch", "schematron_asset"),
        ("transform.xsl", ".xsl", "schematron_asset"),
        ("transform.xslt", ".xslt", "schematron_asset"),
        ("notes.txt", ".txt", "other"),
        ("evidence.pdf", ".pdf", "other"),
        ("screenshot.png", ".png", "other"),
        ("photo.jpg", ".jpg", "other"),
        ("photo.jpeg", ".jpeg", "other"),
        ("bundle.zip", ".zip", "other"),
    ],
)
def test_upload_accepts_all_allowed_suffixes(
    filename: str, suffix: str, purpose: str
) -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": (filename, b"abc123", "application/octet-stream")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["suffix"] == suffix
    assert body["purpose"] == purpose


def test_upload_rejects_unsupported_suffix() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert resp.status_code == 415


def test_upload_rejects_empty_payload() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("a.xml", b"", "application/xml")},
    )
    assert resp.status_code == 400


def test_upload_rejects_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    # Re-import module-level constant via env override would require restart;
    # instead patch the constant directly.
    import epcr_app.api_cta_testing as mod

    monkeypatch.setattr(mod, "_UPLOAD_MAX_BYTES", 8)
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("big.xml", b"0123456789", "application/xml")},
    )
    assert resp.status_code == 413


def test_upload_rejects_bad_test_case_id() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("a.xml", VALID_XML, "application/xml")},
        data={"test_case_id": "BOGUS"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# /validation-runs (uploaded_xml mode)
# --------------------------------------------------------------------------- #


def _create_xml_upload(client: TestClient, test_case_id: str = "2025-DEM1") -> str:
    resp = client.post(
        f"{BASE}/uploads",
        files={"file": ("ems.xml", VALID_XML, "application/xml")},
        data={"test_case_id": test_case_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["upload_id"]


def test_validation_run_uploaded_xml_mode_succeeds_for_owner() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    upload_id = _create_xml_upload(client)
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
            "use_deployed_assets": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tenant_id"] == TENANT_A
    assert body["test_case_id"] == "2025-DEM1"
    assert body["mode"] == "uploaded_xml"
    assert body["xml_upload_id"] == upload_id
    assert isinstance(body["xsd_valid"], bool)
    assert isinstance(body["schematron_valid"], bool)
    assert body["nemsis_version"] == "3.5.1"
    assert len(body["checksum_sha256"]) == 64


def test_validation_run_uploaded_xml_requires_upload_id() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
        },
    )
    assert resp.status_code == 400


def test_validation_run_rejects_unknown_test_case() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    upload_id = _create_xml_upload(client)
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "BOGUS",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
        },
    )
    assert resp.status_code == 400


def test_validation_run_rejects_non_xml_upload_for_uploaded_xml_mode() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    pdf = client.post(
        f"{BASE}/uploads",
        files={"file": ("doc.pdf", b"%PDF-1.4 stub", "application/pdf")},
    )
    upload_id = pdf.json()["upload_id"]
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
        },
    )
    assert resp.status_code == 400


def test_validation_run_uploaded_xml_blocks_cross_tenant_upload() -> None:
    client_a = _make_client(_user(USER_A, TENANT_A))
    upload_id = _create_xml_upload(client_a)

    client_b = _make_client(_user(USER_B, TENANT_B))
    resp = client_b.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
        },
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /validation-runs (fixture_xml mode)
# --------------------------------------------------------------------------- #


def _fixture_present(test_case_id: str) -> bool:
    case = next(c for c in _CTA_2025_TEST_CASES if c["test_case_id"] == test_case_id)
    from epcr_app.api_cta_testing import _fixture_root

    return (_fixture_root() / case["fixture_filename"]).is_file()


@pytest.mark.parametrize("test_case_id", [c["test_case_id"] for c in _CTA_2025_TEST_CASES])
def test_validation_run_fixture_mode_runs_for_each_case(test_case_id: str) -> None:
    if not _fixture_present(test_case_id):
        pytest.skip(f"Fixture for {test_case_id} not bundled in this environment")
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/validation-runs",
        json={"test_case_id": test_case_id, "mode": "fixture_xml"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == "fixture_xml"
    assert body["test_case_id"] == test_case_id
    assert body["source_label"].startswith("fixture:")
    # The validator should have actually run; checksum is from real bytes.
    assert len(body["checksum_sha256"]) == 64


# --------------------------------------------------------------------------- #
# /validation-runs (generated_chart_xml mode — truthful blocking)
# --------------------------------------------------------------------------- #


def test_validation_run_generated_chart_xml_returns_truthful_501() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "generated_chart_xml",
            "chart_id": "chart-uuid-not-real",
        },
    )
    assert resp.status_code == 501
    assert "chart export" in resp.json()["detail"].lower()


def test_validation_run_generated_chart_xml_requires_chart_id() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(
        f"{BASE}/validation-runs",
        json={"test_case_id": "2025-DEM1", "mode": "generated_chart_xml"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# GET /validation-runs/{id}  (tenant isolation)
# --------------------------------------------------------------------------- #


def test_get_validation_run_blocks_cross_tenant() -> None:
    client_a = _make_client(_user(USER_A, TENANT_A))
    upload_id = _create_xml_upload(client_a)
    create = client_a.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
        },
    )
    run_id = create.json()["validation_run_id"]
    assert client_a.get(f"{BASE}/validation-runs/{run_id}").status_code == 200

    client_b = _make_client(_user(USER_B, TENANT_B))
    foreign = client_b.get(f"{BASE}/validation-runs/{run_id}")
    assert foreign.status_code == 404


# --------------------------------------------------------------------------- #
# /validation-runs/{id}/ai-review  (Bedrock advisory contract)
# --------------------------------------------------------------------------- #


def _create_run(client: TestClient) -> dict:
    upload_id = _create_xml_upload(client)
    resp = client.post(
        f"{BASE}/validation-runs",
        json={
            "test_case_id": "2025-DEM1",
            "mode": "uploaded_xml",
            "xml_upload_id": upload_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_ai_review_returns_provider_not_configured_when_bedrock_unset() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client)
    resp = client.post(f"{BASE}/validation-runs/{run['validation_run_id']}/ai-review")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "provider_not_configured"
    assert body["provider"] == "aws_bedrock"
    assert "authoritative" in body["authority_notice"].lower()
    assert body["validation_run_id"] == run["validation_run_id"]


def test_ai_review_does_not_mutate_validator_verdicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client)
    before = client.get(f"{BASE}/validation-runs/{run['validation_run_id']}").json()

    # Even when "configured", the run record's xsd_valid/schematron_valid
    # must not change.
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-test")
    review = client.post(
        f"{BASE}/validation-runs/{run['validation_run_id']}/ai-review"
    )
    assert review.status_code == 200
    body = review.json()
    assert body["status"] in {"completed", "failed", "provider_not_configured"}
    assert "authoritative" in body["authority_notice"].lower()

    after = client.get(f"{BASE}/validation-runs/{run['validation_run_id']}").json()
    assert after["xsd_valid"] == before["xsd_valid"]
    assert after["schematron_valid"] == before["schematron_valid"]
    assert after["xsd_errors"] == before["xsd_errors"]
    assert after["schematron_errors"] == before["schematron_errors"]


def test_ai_review_blocks_cross_tenant() -> None:
    client_a = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client_a)

    client_b = _make_client(_user(USER_B, TENANT_B))
    resp = client_b.post(f"{BASE}/validation-runs/{run['validation_run_id']}/ai-review")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# /evidence-packets
# --------------------------------------------------------------------------- #


def test_evidence_packet_requires_validation_run_id() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    resp = client.post(f"{BASE}/evidence-packets", json={})
    # FastAPI returns 422 for missing pydantic field
    assert resp.status_code in {400, 422}


def test_evidence_packet_includes_registry_and_asset_proof() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client)

    pkt = client.post(
        f"{BASE}/evidence-packets",
        json={"validation_run_id": run["validation_run_id"]},
    )
    assert pkt.status_code == 201, pkt.text
    body = pkt.json()
    assert body["validation_run_id"] == run["validation_run_id"]
    assert body["tenant_id"] == TENANT_A
    assert body["test_case_id"] == "2025-DEM1"
    assert body["nemsis_version"] == "3.5.1"
    assert body["mode"] == "uploaded_xml"
    assert body["xsd_errors_count"] == len(run["xsd_errors"])
    assert body["schematron_errors_count"] == len(run["schematron_errors"])
    assert body["warnings_count"] == len(run["schematron_warnings"])
    assert body["resubmission_ready"] == (
        run["xsd_valid"]
        and run["schematron_valid"]
        and not run["validation_skipped"]
    )
    # Registry version + source commit must be sourced (or honestly null).
    assert "registry_version" in body
    assert "source_commit" in body


def test_evidence_packet_includes_bedrock_summary_when_review_present() -> None:
    client = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client)
    client.post(f"{BASE}/validation-runs/{run['validation_run_id']}/ai-review")

    pkt = client.post(
        f"{BASE}/evidence-packets",
        json={"validation_run_id": run["validation_run_id"]},
    )
    assert pkt.status_code == 201
    assert pkt.json()["bedrock_summary"] is not None


def test_evidence_packet_blocks_cross_tenant() -> None:
    client_a = _make_client(_user(USER_A, TENANT_A))
    run = _create_run(client_a)

    client_b = _make_client(_user(USER_B, TENANT_B))
    resp = client_b.post(
        f"{BASE}/evidence-packets",
        json={"validation_run_id": run["validation_run_id"]},
    )
    assert resp.status_code == 404
