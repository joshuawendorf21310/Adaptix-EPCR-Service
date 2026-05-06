"""Tests for the NEMSIS Custom Element Catalog (Slice 4).

Covers:
* deterministic empty catalog when no registry is configured
* dataset filter accepts DEMDataSet and EMSDataSet
* dataset filter rejects unknown values (UnknownDatasetError)
* ``get_custom_element`` returns ``None`` for unknown ids
* HTTP catalog endpoint returns 200
* HTTP catalog endpoint accepts ?dataset=... filter
* HTTP catalog endpoint rejects unknown ?dataset= values with 400
* HTTP detail endpoint returns 404 for unknown element ids
* the catalog response includes ``source`` and ``version``
* the service does not mutate returned tuples between calls
* Slice 2 schematron-gate import still works
* Slice 3 defined-list service import still works
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis_custom_elements import (
    router as custom_elements_router,
)
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_custom_elements import (
    ALLOWED_DATASETS,
    CUSTOM_ELEMENTS_DEFAULT_VERSION,
    CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED,
    DATASET_DEM,
    DATASET_EMS,
    NemsisCustomElement,
    NemsisCustomElementService,
    UnknownDatasetError,
    get_default_custom_element_service,
)


TENANT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"


def _build_test_client() -> TestClient:
    app = FastAPI()

    def override_current_user() -> CurrentUser:
        return CurrentUser(
            user_id=UUID(USER_ID),
            tenant_id=UUID(TENANT_ID),
            email="test@example.com",
            roles=["ems"],
        )

    app.dependency_overrides[get_current_user] = override_current_user
    app.include_router(custom_elements_router)
    return TestClient(app)


def _seeded_service() -> NemsisCustomElementService:
    return NemsisCustomElementService(
        registry=(
            NemsisCustomElement(
                element_id="eCustomDem.01",
                dataset=DATASET_DEM,
                section="dCustomConfiguration",
                label="Sample DEM custom",
                data_type="string",
                required=False,
                allowed_values=(),
            ),
            NemsisCustomElement(
                element_id="eCustomEms.01",
                dataset=DATASET_EMS,
                section="eCustomConfiguration",
                label="Sample EMS custom",
                data_type="string",
                required=True,
                allowed_values=("alpha", "bravo"),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestServiceEmptyDefault:
    def test_default_service_returns_empty_not_configured_catalog(self) -> None:
        service = NemsisCustomElementService()
        catalog = service.catalog()
        assert catalog.field_count == 0
        assert catalog.source == CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED
        assert catalog.version == CUSTOM_ELEMENTS_DEFAULT_VERSION
        assert catalog.elements == ()

    def test_default_service_lists_canonical_datasets(self) -> None:
        service = NemsisCustomElementService()
        assert service.list_datasets() == ALLOWED_DATASETS
        assert DATASET_DEM in service.list_datasets()
        assert DATASET_EMS in service.list_datasets()

    def test_default_service_get_unknown_returns_none(self) -> None:
        service = NemsisCustomElementService()
        assert service.get_custom_element("eCustomDem.99") is None


class TestServiceFilters:
    def test_dataset_filter_dem_returns_only_dem_elements(self) -> None:
        service = _seeded_service()
        elements = service.list_custom_elements(DATASET_DEM)
        assert len(elements) == 1
        assert elements[0].dataset == DATASET_DEM
        assert elements[0].element_id == "eCustomDem.01"

    def test_dataset_filter_ems_returns_only_ems_elements(self) -> None:
        service = _seeded_service()
        elements = service.list_custom_elements(DATASET_EMS)
        assert len(elements) == 1
        assert elements[0].dataset == DATASET_EMS
        assert elements[0].element_id == "eCustomEms.01"

    def test_unknown_dataset_filter_raises(self) -> None:
        service = _seeded_service()
        with pytest.raises(UnknownDatasetError):
            service.list_custom_elements("BogusDataSet")

    def test_seeded_service_returns_seeded_source_and_version(self) -> None:
        service = _seeded_service()
        catalog = service.catalog()
        assert catalog.field_count == 2
        assert catalog.source != CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED
        assert catalog.version == CUSTOM_ELEMENTS_DEFAULT_VERSION


class TestServicePurity:
    def test_repeated_calls_return_equivalent_data(self) -> None:
        service = _seeded_service()
        first = service.list_custom_elements()
        second = service.list_custom_elements()
        # Tuple identity not required, but values must match.
        assert first == second
        # Frozen dataclasses cannot be mutated; confirm membership stable.
        ids_first = tuple(element.element_id for element in first)
        ids_second = tuple(element.element_id for element in second)
        assert ids_first == ids_second

    def test_get_default_service_is_singleton(self) -> None:
        a = get_default_custom_element_service()
        b = get_default_custom_element_service()
        assert a is b

    def test_invalid_registry_member_raises(self) -> None:
        with pytest.raises(UnknownDatasetError):
            NemsisCustomElementService(
                registry=(
                    NemsisCustomElement(
                        element_id="eCustomBad.01",
                        dataset="BogusDataSet",
                        section="x",
                        label="x",
                        data_type="string",
                        required=False,
                    ),
                )
            )


# ---------------------------------------------------------------------------
# HTTP-layer tests
# ---------------------------------------------------------------------------


class TestCustomElementsApi:
    def test_catalog_returns_200_with_source_and_version(self) -> None:
        client = _build_test_client()
        response = client.get("/api/v1/epcr/nemsis-custom-elements")
        assert response.status_code == 200, response.text
        body = response.json()
        assert "source" in body
        assert "version" in body
        assert "field_count" in body
        assert "elements" in body
        # Default registry is empty -> not_configured catalog.
        assert body["source"] == CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED
        assert body["field_count"] == 0
        assert body["elements"] == []

    def test_catalog_dataset_filter_dem_returns_200(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-custom-elements",
            params={"dataset": DATASET_DEM},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Default registry empty - filter still returns 200 with empty list.
        assert body["field_count"] == 0
        assert body["elements"] == []

    def test_catalog_dataset_filter_ems_returns_200(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-custom-elements",
            params={"dataset": DATASET_EMS},
        )
        assert response.status_code == 200, response.text
        assert response.json()["field_count"] == 0

    def test_catalog_rejects_unknown_dataset_with_400(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-custom-elements",
            params={"dataset": "BogusDataSet"},
        )
        assert response.status_code == 400, response.text
        assert "BogusDataSet" in response.json()["detail"]

    def test_detail_returns_404_for_unknown_element(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-custom-elements/eCustomImaginary.999"
        )
        assert response.status_code == 404, response.text
        assert "eCustomImaginary.999" in response.json()["detail"]
        assert "not present" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Cross-slice safety: imports of Slice 2 + Slice 3 still resolve.
# ---------------------------------------------------------------------------


class TestPreviousSlicesPreserved:
    def test_slice2_finalization_gate_import(self) -> None:
        from epcr_app import nemsis_finalization_gate

        assert hasattr(nemsis_finalization_gate, "SchematronFinalizationGate")
        assert hasattr(nemsis_finalization_gate, "GATE_STATUS_OK")
        assert hasattr(nemsis_finalization_gate, "GATE_STATUS_BLOCKED")
        assert hasattr(nemsis_finalization_gate, "GATE_STATUS_UNAVAILABLE")

    def test_slice3_defined_list_service_import(self) -> None:
        from epcr_app.nemsis_defined_lists import (
            NemsisDefinedListService,
            get_default_defined_list_service,
        )

        service = NemsisDefinedListService()
        # Listing must work and remain non-fabricated.
        assert isinstance(service.list_defined_lists(), tuple)
        assert get_default_defined_list_service() is get_default_defined_list_service()
