"""Tests for the NEMSIS Defined-List Picker Catalog (Slice 3).

Covers:
* deterministic catalog assembly from the field graph seed
* ``get_defined_list`` for a known defined-list-backed field
* ``get_defined_list`` returns ``None`` for unknown / non-list-backed fields
* every value carries ``code`` and ``display``
* the service does not mutate field-graph internals
* HTTP list endpoint returns 200 with deterministic shape
* HTTP detail endpoint returns 200 for a known defined-list field
* HTTP detail endpoint returns 404 (honest, not fabricated values) for an
  unknown field
* the existing Slice 2 schematron-gate decisions are unaffected by importing
  this module (smoke import only).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis_defined_lists import router as defined_lists_router
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_defined_lists import (
    COVERAGE_MODE_LOCAL_SEED_ONLY,
    COVERAGE_MODE_MIXED,
    COVERAGE_MODE_OFFICIAL_PARTIAL,
    DEFAULT_OFFICIAL_FIXTURE_DIR,
    DEFINED_LIST_SOURCE,
    DEFINED_LIST_VERSION,
    DefinedListField,
    DefinedListValue,
    LOCAL_SEED_DEFINED_LIST_SOURCE,
    NemsisDefinedListService,
    OFFICIAL_DEFINED_LIST_SOURCE,
    OFFICIAL_DEFINED_LIST_SOURCE_URL,
    get_default_defined_list_service,
)
from epcr_app.nemsis_field_graph import (
    NemsisFieldDefinition,
    NemsisFieldGraphService,
    get_default_service,
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
    app.include_router(defined_lists_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestServiceListing:
    def test_list_defined_lists_is_deterministic(self) -> None:
        service_a = NemsisDefinedListService()
        service_b = NemsisDefinedListService()

        ids_a = [picker.field_id for picker in service_a.list_defined_lists()]
        ids_b = [picker.field_id for picker in service_b.list_defined_lists()]

        assert ids_a == ids_b
        # We only expose fields with non-empty allowed_values, so the catalog
        # MUST contain at least the well-known seed defined-list fields.
        assert "eResponse.05" in ids_a
        assert "eDisposition.30" in ids_a
        assert "eSituation.04" in ids_a

    def test_list_defined_list_fields_returns_only_defined_list_field_ids(self) -> None:
        service = NemsisDefinedListService()
        ids = service.list_defined_list_fields()

        assert isinstance(ids, tuple)
        # Field with no allowed_values must NOT appear.
        assert "eRecord.01" not in ids
        assert "eNarrative.01" not in ids
        # Field with allowed_values MUST appear.
        assert "eDisposition.30" in ids

    def test_get_defined_list_returns_known_field(self) -> None:
        service = NemsisDefinedListService()
        picker = service.get_defined_list("eDisposition.30")
        assert picker is not None
        assert isinstance(picker, DefinedListField)
        assert picker.field_id == "eDisposition.30"
        assert picker.section == "eDisposition"
        assert picker.label
        assert picker.source == DEFINED_LIST_SOURCE
        codes = [value.code for value in picker.values]
        assert "transported" in codes
        assert "dead_at_scene" in codes

    def test_get_defined_list_returns_none_for_unknown_field(self) -> None:
        service = NemsisDefinedListService()
        # Field that does not exist in the graph at all.
        assert service.get_defined_list("eImaginary.999") is None
        # Field that exists in the graph but has NO allowed_values.
        assert service.get_defined_list("eRecord.01") is None


class TestServiceValueShape:
    def test_every_value_has_code_and_display(self) -> None:
        service = NemsisDefinedListService()
        for picker in service.list_defined_lists():
            assert picker.values, f"{picker.field_id} has no values"
            for value in picker.values:
                assert isinstance(value, DefinedListValue)
                assert isinstance(value.code, str) and value.code
                assert isinstance(value.display, str) and value.display

    def test_values_use_curated_display_when_available(self) -> None:
        service = NemsisDefinedListService()
        picker = service.get_defined_list("eResponse.05")
        assert picker is not None
        display_by_code = {value.code: value.display for value in picker.values}
        # Curated label, not the raw code.
        assert display_by_code["emergency"] == "Emergency Response (Immediate)"

    def test_uncurated_codes_fall_back_to_humanized_code(self) -> None:
        # Build a tiny custom graph to prove fallback behavior without
        # mutating the global field graph.
        custom_field = NemsisFieldDefinition(
            field_id="eTest.99",
            section="eTest",
            label="Custom Code List",
            data_type="code",
            required_level="optional",
            allowed_values=("alpha_one", "BravoTwo"),
        )
        graph = NemsisFieldGraphService(catalog=(custom_field,))
        service = NemsisDefinedListService(field_graph=graph)
        picker = service.get_defined_list("eTest.99")
        assert picker is not None
        display_by_code = {value.code: value.display for value in picker.values}
        # Codes preserved verbatim; display is honest best-effort.
        assert display_by_code["alpha_one"] == "Alpha one"
        assert display_by_code["BravoTwo"] == "BravoTwo"


class TestServicePurity:
    def test_service_does_not_mutate_field_graph_state(self) -> None:
        graph = get_default_service()
        before_field_ids = [f.field_id for f in graph.list_fields()]
        before_section_count = len(graph.list_sections())

        # Construct multiple defined-list services and exercise the API.
        for _ in range(3):
            service = NemsisDefinedListService(field_graph=graph)
            _ = service.list_defined_lists()
            _ = service.list_defined_list_fields()
            _ = service.get_defined_list("eDisposition.30")
            _ = service.get_defined_list("eImaginary.999")

        after_field_ids = [f.field_id for f in graph.list_fields()]
        after_section_count = len(graph.list_sections())

        assert before_field_ids == after_field_ids
        assert before_section_count == after_section_count

    def test_default_service_singleton_is_stable(self) -> None:
        a = get_default_defined_list_service()
        b = get_default_defined_list_service()
        assert a is b


# ---------------------------------------------------------------------------
# HTTP route tests
# ---------------------------------------------------------------------------


class TestDefinedListsApi:
    def test_list_endpoint_returns_200_with_catalog(self) -> None:
        client = _build_test_client()
        response = client.get("/api/v1/epcr/nemsis-defined-lists")
        assert response.status_code == 200
        body = response.json()
        # Slice 3B: source can be one of three honest values; we accept all
        # three but require version + counts + coverage_mode + field_count.
        assert body["source"] in {
            LOCAL_SEED_DEFINED_LIST_SOURCE,
            OFFICIAL_DEFINED_LIST_SOURCE,
            COVERAGE_MODE_MIXED,
        }
        assert body["version"] == DEFINED_LIST_VERSION
        assert body["field_count"] == len(body["fields"])
        assert body["field_count"] >= 1
        # Slice 3B catalog metadata must be present.
        assert body["official_source_url"] == OFFICIAL_DEFINED_LIST_SOURCE_URL
        assert isinstance(body["official_list_count"], int)
        assert isinstance(body["local_seed_fallback_count"], int)
        assert body["coverage_mode"] in {
            COVERAGE_MODE_LOCAL_SEED_ONLY,
            COVERAGE_MODE_OFFICIAL_PARTIAL,
            COVERAGE_MODE_MIXED,
        }
        # Slice 3B+ registry import provenance is exposed when present.
        assert "source_repo" in body
        assert "source_commit" in body
        assert "official_artifact_count" in body
        assert "source_mode" in body
        if body.get("source_repo"):
            assert body["source_repo"] == "https://git.nemsis.org/scm/nep/nemsis_public.git"

        first = body["fields"][0]
        assert "field_id" in first
        assert "section" in first
        assert "label" in first
        assert "values" in first
        assert isinstance(first["values"], list)
        for value in first["values"]:
            assert "code" in value
            assert "display" in value

    def test_detail_endpoint_returns_200_for_known_field(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-defined-lists/eDisposition.30",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["field_id"] == "eDisposition.30"
        assert body["section"] == "eDisposition"
        assert body["source"] == DEFINED_LIST_SOURCE
        codes = [value["code"] for value in body["values"]]
        assert "transported" in codes
        assert "dead_at_scene" in codes

    def test_detail_endpoint_returns_404_for_unknown_field(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-defined-lists/eImaginary.999",
        )
        assert response.status_code == 404
        body = response.json()
        # Honest, descriptive detail. We do NOT fabricate values for unknown
        # fields.
        assert "not present" in body["detail"]

    def test_detail_endpoint_returns_404_for_field_without_defined_list(self) -> None:
        # eRecord.01 exists in the field graph but has NO allowed_values,
        # so it must not appear as a defined-list-backed picker.
        client = _build_test_client()
        response = client.get("/api/v1/epcr/nemsis-defined-lists/eRecord.01")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cross-slice safety smoke
# ---------------------------------------------------------------------------


class TestSlice2GatePreserved:
    def test_schematron_gate_module_still_imports(self) -> None:
        # Importing this module must not break the Slice 2 gate.
        from epcr_app import nemsis_finalization_gate as gate

        assert hasattr(gate, "SchematronFinalizationGate")
        assert hasattr(gate, "GATE_STATUS_OK")
        assert hasattr(gate, "GATE_STATUS_BLOCKED")
        assert hasattr(gate, "GATE_STATUS_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Slice 3B: official defined-list fixture import
# ---------------------------------------------------------------------------


class TestOfficialFixtureLoading:
    def test_default_fixture_dir_exists_and_contains_json(self) -> None:
        # Slice 3B precondition: official fixture directory exists and has
        # at least one JSON envelope present in the repository.
        assert DEFAULT_OFFICIAL_FIXTURE_DIR.exists()
        assert DEFAULT_OFFICIAL_FIXTURE_DIR.is_dir()
        files = sorted(DEFAULT_OFFICIAL_FIXTURE_DIR.glob("*.json"))
        assert len(files) >= 1, (
            "Expected at least one official NEMSIS defined-list JSON "
            "envelope in the fixture directory."
        )

    def test_official_fixture_envelope_carries_provenance(self) -> None:
        # Every fixture must declare source_url + nemsis_element_ids and at
        # least one value with code+display - we never fabricate values.
        import json

        for path in sorted(DEFAULT_OFFICIAL_FIXTURE_DIR.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(payload, dict), path
            assert payload.get("source_url"), f"{path} missing source_url"
            assert payload.get("source_name"), f"{path} missing source_name"
            assert payload.get("list_name"), f"{path} missing list_name"
            assert payload.get("download_format") == "json", path
            assert payload.get("retrieved_at"), f"{path} missing retrieved_at"
            elements = payload.get("nemsis_element_ids") or []
            assert isinstance(elements, list) and elements, (
                f"{path} missing nemsis_element_ids"
            )
            values = payload.get("values") or []
            assert isinstance(values, list) and values, (
                f"{path} missing values"
            )
            for value in values[:5]:
                assert isinstance(value, dict)
                assert value.get("code")
                assert value.get("display")

    def test_service_loads_official_fixtures_deterministically(self) -> None:
        a = NemsisDefinedListService()
        b = NemsisDefinedListService()
        ids_a = [f.field_id for f in a.list_defined_lists()]
        ids_b = [f.field_id for f in b.list_defined_lists()]
        assert ids_a == ids_b
        assert a.official_field_count() == b.official_field_count()
        assert a.local_seed_fallback_count() == b.local_seed_fallback_count()
        assert a.coverage_mode() == b.coverage_mode()

    def test_service_reports_official_partial_or_mixed_coverage(self) -> None:
        # With at least one official fixture present, coverage MUST be
        # either official_partial or mixed (never local_seed_only).
        service = NemsisDefinedListService()
        assert service.official_field_count() >= 1
        assert service.coverage_mode() in {
            COVERAGE_MODE_OFFICIAL_PARTIAL,
            COVERAGE_MODE_MIXED,
        }
        catalog = service.catalog()
        assert catalog.official_source_url == OFFICIAL_DEFINED_LIST_SOURCE_URL
        assert catalog.official_list_count == service.official_field_count()
        assert catalog.local_seed_fallback_count == service.local_seed_fallback_count()

    def test_official_fields_are_labeled_official_source(self) -> None:
        service = NemsisDefinedListService()
        official_fields = [
            f
            for f in service.list_defined_lists()
            if f.source == OFFICIAL_DEFINED_LIST_SOURCE
        ]
        assert official_fields, (
            "Expected at least one official_nemsis_defined_list field"
        )
        for field in official_fields:
            assert field.source_url and field.source_url.startswith("http")
            assert field.list_name
            assert field.retrieved_at
            assert field.values
            for value in field.values:
                assert value.code
                assert value.display

    def test_local_seed_fallback_preserved_for_uncovered_fields(self) -> None:
        # eDisposition.30 is not in any official fixture, so it must remain
        # as the local_seed_field_graph fallback.
        service = NemsisDefinedListService()
        picker = service.get_defined_list("eDisposition.30")
        assert picker is not None
        assert picker.source == LOCAL_SEED_DEFINED_LIST_SOURCE

    def test_catalog_distinguishes_official_from_local_seed(self) -> None:
        service = NemsisDefinedListService()
        sources = {field.source for field in service.list_defined_lists()}
        # When mixed coverage is in effect, both labels MUST appear.
        if service.coverage_mode() == COVERAGE_MODE_MIXED:
            assert OFFICIAL_DEFINED_LIST_SOURCE in sources
            assert LOCAL_SEED_DEFINED_LIST_SOURCE in sources

    def test_unknown_field_still_returns_404_after_official_load(self) -> None:
        client = _build_test_client()
        response = client.get(
            "/api/v1/epcr/nemsis-defined-lists/eImaginaryOfficial.999",
        )
        assert response.status_code == 404
        assert "not present" in response.json()["detail"]

    def test_existing_routes_remain_unchanged(self) -> None:
        # Same prefix, same path templates - just additive metadata.
        from epcr_app.api_nemsis_defined_lists import router

        paths = sorted(route.path for route in router.routes)
        assert paths == [
            "/api/v1/epcr/nemsis-defined-lists",
            "/api/v1/epcr/nemsis-defined-lists/{field_id}",
        ]

    def test_slice4_custom_elements_still_imports(self) -> None:
        from epcr_app.nemsis_custom_elements import (
            NemsisCustomElementService,
            get_default_custom_element_service,
        )

        service = NemsisCustomElementService()
        # Slice 4 default registry MUST stay empty / not_configured; Slice 3B
        # must NOT bleed defined-list values into custom elements.
        catalog = service.catalog()
        assert catalog.field_count == 0
        assert catalog.elements == ()
        assert get_default_custom_element_service() is get_default_custom_element_service()
