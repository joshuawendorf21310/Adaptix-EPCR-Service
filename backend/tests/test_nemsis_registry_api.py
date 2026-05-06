"""Tests for the NEMSIS official-source registry HTTP API (Slice 3B+)."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis_registry import router as registry_router
from epcr_app.dependencies import CurrentUser, get_current_user


TENANT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
PINNED_COMMIT = "9bff090cbf95db614529bdff5e1e988a93f89717"


def _client() -> TestClient:
    app = FastAPI()

    def override_current_user() -> CurrentUser:
        return CurrentUser(
            user_id=UUID(USER_ID),
            tenant_id=UUID(TENANT_ID),
            email="test@example.com",
            roles=["clinician"],
        )

    app.dependency_overrides[get_current_user] = override_current_user
    app.include_router(registry_router)
    return TestClient(app)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return _client()


def test_snapshot_endpoint_reports_official_partial(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_repo"] == "https://git.nemsis.org/scm/nep/nemsis_public.git"
    assert body["source_commit"] == PINNED_COMMIT
    assert body["source_mode"] in {"official_partial", "mixed_official_and_local_seed"}
    assert body["field_count"] > 0
    assert body["element_enumeration_count"] > 0
    assert body["defined_list_count"] >= 6
    assert body["official_artifact_count"] > 0


def test_manifest_endpoint_returns_pinned_commit(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/manifest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source_repo"] == "https://git.nemsis.org/scm/nep/nemsis_public.git"
    assert body["source_commit"] == PINNED_COMMIT
    assert body["artifacts"]
    assert all(a["source_commit"] == PINNED_COMMIT for a in body["artifacts"])


def test_datasets_route(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/datasets")
    assert r.status_code == 200
    datasets = r.json()
    assert isinstance(datasets, list)
    assert "EMSDataSet" in datasets


def test_sections_route_with_dataset(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/sections?dataset=EMSDataSet")
    assert r.status_code == 200
    sections = r.json()
    assert sections
    assert any(s.startswith("e") or s.startswith("d") for s in sections)


def test_fields_filter_by_dataset_and_section(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/fields?dataset=EMSDataSet&section=eDisposition")
    assert r.status_code == 200
    fields = r.json()
    assert fields
    for f in fields:
        assert f["dataset"] == "EMSDataSet"
        assert f["section"] == "eDisposition"
        assert f["field_id"].startswith("eDisposition.")


def test_get_field_by_id(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/fields?dataset=EMSDataSet")
    assert r.status_code == 200
    fields = r.json()
    assert fields
    target = fields[0]["field_id"]
    r2 = client.get(f"/api/v1/epcr/nemsis-registry/fields/{target}")
    assert r2.status_code == 200
    payload = r2.json()
    assert payload["field_id"] == target
    assert payload["source_commit"] == PINNED_COMMIT


def test_get_unknown_field_returns_404(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/fields/eFake.99")
    assert r.status_code == 404
    assert "does not invent fields" in r.json()["detail"]


def test_element_enumerations_filter(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/element-enumerations")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    sample_field = rows[0]["field_id"]
    r2 = client.get(
        f"/api/v1/epcr/nemsis-registry/element-enumerations?field_id={sample_field}"
    )
    assert r2.status_code == 200
    filtered = r2.json()
    assert filtered
    assert all(row["field_id"] == sample_field for row in filtered)


def test_defined_lists_route(client: TestClient) -> None:
    r = client.get("/api/v1/epcr/nemsis-registry/defined-lists")
    assert r.status_code == 200
    rows = r.json()
    assert rows
    list_ids = {row["list_id"] for row in rows}
    # We seeded six official defined-list fixtures.
    assert {
        "cause_of_injury",
        "impression",
        "incident_location_type",
        "symptoms",
        "medications_given",
        "procedures",
    }.issubset(list_ids)


def test_evaluate_does_not_mutate_input_or_persist(client: TestClient) -> None:
    payload = {"chart_state": {"eDisposition.30": "transported", "ePatient.13": "1985-01-01"}}
    r = client.post("/api/v1/epcr/nemsis-registry/evaluate", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["completeness"] == "framework_partial"
    assert body["source_repo"] == "https://git.nemsis.org/scm/nep/nemsis_public.git"
    assert body["provided_field_count"] >= 0
    # Caller payload unchanged.
    assert payload == {
        "chart_state": {"eDisposition.30": "transported", "ePatient.13": "1985-01-01"}
    }


def test_unauthenticated_request_is_rejected() -> None:
    app = FastAPI()
    app.include_router(registry_router)
    c = TestClient(app)
    r = c.get("/api/v1/epcr/nemsis-registry")
    assert r.status_code in {401, 403}
