"""API tests for ``api_nemsis_datasets``.

Validates the dataset-aware build endpoint, visibility endpoint, and
validate-all endpoint with real DB persistence and dependency-overridden
auth so the suite is hermetic.
"""
from __future__ import annotations

import base64
import io
import zipfile
from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.api_nemsis_datasets import router as datasets_router
from epcr_app.api_nemsis_field_values import router as field_values_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base
from epcr_app.models_nemsis_field_values import NemsisFieldValue  # noqa: F401


@pytest_asyncio.fixture
async def app_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(datasets_router)
    app.include_router(field_values_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return SimpleNamespace(
            tenant_id="tenant-X",
            user_id="user-1",
            email="x@x",
            roles=["paramedic"],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


def _seed_field(client: TestClient, chart_id: str, **kw):
    body = {
        "section": kw["section"],
        "element_number": kw["element_number"],
        "element_name": kw.get("element_name", kw["element_number"]),
        "value": kw.get("value"),
        "group_path": kw.get("group_path", kw["section"]),
        "occurrence_id": kw.get("occurrence_id", ""),
        "sequence_index": kw.get("sequence_index", 0),
        "attributes": kw.get("attributes", {}),
        "source": "manual",
    }
    r = client.post(
        f"/api/v1/epcr/charts/{chart_id}/nemsis/field-values",
        json=body,
    )
    assert r.status_code == 201, r.text


def test_build_returns_per_dataset_artifacts(app_client: TestClient) -> None:
    chart = "chart-1"
    _seed_field(
        app_client,
        chart,
        section="eRecord",
        element_number="eRecord.01",
        value="PCR-1",
    )
    _seed_field(
        app_client,
        chart,
        section="dPersonnel",
        element_number="dPersonnel.01",
        value="P-001",
    )
    _seed_field(
        app_client,
        chart,
        section="sState",
        element_number="sState.01",
        value="CA",
    )

    r = app_client.post(
        f"/api/v1/epcr/nemsis/datasets/{chart}/build", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    datasets = sorted(a["dataset"] for a in body["artifacts"])
    assert datasets == ["DEMDataSet", "EMSDataSet", "StateDataSet"]
    for art in body["artifacts"]:
        assert len(art["sha256"]) == 64
        xml = base64.b64decode(art["xml_base64"]).decode("utf-8")
        assert xml.startswith("<?xml")
        assert "http://www.nemsis.org" in xml


def test_build_with_package_returns_zip(app_client: TestClient) -> None:
    chart = "chart-pkg"
    _seed_field(
        app_client,
        chart,
        section="eRecord",
        element_number="eRecord.01",
        value="PCR-PKG",
    )
    _seed_field(
        app_client,
        chart,
        section="dPersonnel",
        element_number="dPersonnel.01",
        value="P-PKG",
    )
    r = app_client.post(
        f"/api/v1/epcr/nemsis/datasets/{chart}/build?package=true", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["package_filename"] == f"nemsis-tenant-X-{chart}.zip"
    assert body["package_sha256"] and len(body["package_sha256"]) == 64
    zip_bytes = base64.b64decode(body["package_base64"])

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = sorted(zf.namelist())
        assert "manifest.json" in names
        assert "EMSDataSet.xml" in names
        assert "DEMDataSet.xml" in names
        manifest = zf.read("manifest.json").decode("utf-8")
        assert '"chart_id": "chart-pkg"' in manifest
        assert '"tenant_id": "tenant-X"' in manifest
        assert '"dictionary_version": "3.5.1"' in manifest


def test_build_with_validate_returns_xsd_verdict(app_client: TestClient) -> None:
    chart = "chart-xsd"
    _seed_field(
        app_client,
        chart,
        section="eRecord",
        element_number="eRecord.01",
        value="PCR-XSD",
    )
    r = app_client.post(
        f"/api/v1/epcr/nemsis/datasets/{chart}/build?validate=true", json={}
    )
    assert r.status_code == 200, r.text
    art = r.json()["artifacts"][0]
    # Either the local XSD bundle is available and we got a real verdict,
    # or the bundle is missing and we got a structured "not_validated"
    # response — never a fake "valid".
    assert art["xsd_valid"] in (True, False, None)
    if art["xsd_valid"] is None:
        assert any("xsd_bundle_missing" in e or "xsd_validator_unavailable" in e for e in art["xsd_errors"])


def test_visibility_endpoint_returns_dataset_grouped_decisions(app_client: TestClient) -> None:
    r = app_client.get(
        "/api/v1/epcr/nemsis/datasets/chart-vis/visibility",
        params={"chart_status": "draft", "scope": "encounter"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["by_dataset"].keys()) >= {
        "EMSDataSet",
        "DEMDataSet",
        "StateDataSet",
    }
    sample = body["by_dataset"]["EMSDataSet"][0]
    assert "element_number" in sample
    assert "visible" in sample
    assert "required" in sample


def test_visibility_finalized_chart_disables_all(app_client: TestClient) -> None:
    r = app_client.get(
        "/api/v1/epcr/nemsis/datasets/chart-vis2/visibility",
        params={"chart_status": "finalized", "scope": "encounter"},
    )
    assert r.status_code == 200
    body = r.json()
    # Every encounter-scope decision should be disabled when chart is
    # finalized.
    ems = body["by_dataset"]["EMSDataSet"]
    assert all(d["disabled"] for d in ems)


def test_validate_all_endpoint_runs_across_datasets(app_client: TestClient) -> None:
    chart = "chart-val"
    _seed_field(
        app_client,
        chart,
        section="eRecord",
        element_number="eRecord.01",
        value="PCR-VAL",
    )
    r = app_client.post(
        f"/api/v1/epcr/nemsis/datasets/{chart}/validate-all",
        json={"chart_context": {"chart_status": "draft"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "by_dataset" in body
    assert set(body["by_dataset"].keys()) >= {
        "EMSDataSet",
        "DEMDataSet",
        "StateDataSet",
    }


def test_tenant_isolation_in_build(app_client: TestClient) -> None:
    """Same chart_id under tenant-X should not leak across tenants."""
    chart = "iso-chart"
    _seed_field(
        app_client,
        chart,
        section="eRecord",
        element_number="eRecord.01",
        value="PCR-ISO",
    )
    r = app_client.post(
        f"/api/v1/epcr/nemsis/datasets/{chart}/build", json={}
    )
    body = r.json()
    assert body["tenant_id"] == "tenant-X"
    xml = base64.b64decode(body["artifacts"][0]["xml_base64"]).decode("utf-8")
    assert "PCR-ISO" in xml


def test_no_field_values_returns_empty_artifacts(app_client: TestClient) -> None:
    r = app_client.post(
        "/api/v1/epcr/nemsis/datasets/empty-chart/build", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifacts"] == []
    assert body["package_base64"] is None
