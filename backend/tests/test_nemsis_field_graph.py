"""Tests for the NEMSIS Field Graph foundation (Slice A).

Covers:
* deterministic catalog lookup (``get_field``, ``list_fields``)
* section-scoped listing
* deterministic section summaries
* required and required-if evaluation against a chart_state
* HTTP routes for the graph and for an individual section

No PHI is used. Tests rely only on the seed catalog so they are stable.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from epcr_app.api_nemsis_field_graph import router as field_graph_router
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.nemsis_field_graph import (
    DEFAULT_GRAPH_SOURCE,
    NemsisFieldDefinition,
    NemsisFieldGraphService,
    NemsisRequiredIfRule,
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
    app.include_router(field_graph_router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestServiceLookup:
    def test_get_field_returns_known_definition(self) -> None:
        service = get_default_service()
        field = service.get_field("ePatient.13")
        assert field is not None
        assert field.field_id == "ePatient.13"
        assert field.section == "ePatient"
        assert field.required_level == "required"
        assert field.source == DEFAULT_GRAPH_SOURCE

    def test_get_field_returns_none_for_unknown(self) -> None:
        service = get_default_service()
        assert service.get_field("eUnknown.99") is None

    def test_list_section_returns_only_requested_section(self) -> None:
        service = get_default_service()
        fields = service.list_section("eTimes")
        assert fields, "seed catalog must include eTimes fields"
        assert all(f.section == "eTimes" for f in fields)

    def test_list_section_returns_empty_for_unknown_section(self) -> None:
        service = get_default_service()
        assert service.list_section("eDoesNotExist") == ()

    def test_list_sections_is_deterministic(self) -> None:
        service = get_default_service()
        first = service.list_sections()
        second = service.list_sections()
        assert [s.section for s in first] == [s.section for s in second]
        assert all(
            s.total_fields
            == s.required_fields
            + s.required_if_fields
            + s.recommended_fields
            + s.optional_fields
            for s in first
        )

    def test_duplicate_field_definition_is_rejected(self) -> None:
        dup = NemsisFieldDefinition(
            field_id="eX.01",
            section="eX",
            label="X",
            data_type="string",
            required_level="required",
        )
        try:
            NemsisFieldGraphService(catalog=(dup, dup))
        except ValueError as exc:
            assert "Duplicate" in str(exc)
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected ValueError for duplicate field id")


# ---------------------------------------------------------------------------
# Evaluation tests
# ---------------------------------------------------------------------------


class TestEvaluateRequired:
    def test_missing_required_field_is_reported_as_blocker(self) -> None:
        service = get_default_service()
        result = service.evaluate_required({}, section="ePatient")
        assert "ePatient.13" in result.unsatisfied_required_fields
        assert "ePatient.14" in result.unsatisfied_required_fields
        assert result.has_blockers is True

    def test_satisfied_required_field_is_not_blocker(self) -> None:
        service = get_default_service()
        chart_state = {
            "ePatient.13": "Doe",
            "ePatient.14": "Jane",
            "ePatient.15": "1980-01-01",
        }
        result = service.evaluate_required(chart_state, section="ePatient")
        assert "ePatient.13" not in result.unsatisfied_required_fields
        assert result.satisfied_fields >= 3

    def test_required_if_only_fires_when_predicate_satisfied(self) -> None:
        service = get_default_service()
        # eTimes.13 (destination time) is required_if eDisposition.30 == "transported".
        not_transported = {
            "eDisposition.30": "treated_not_transported",
        }
        result = service.evaluate_required(not_transported, section="eTimes")
        assert "eTimes.13" not in result.unsatisfied_required_if_fields

        transported = {"eDisposition.30": "transported"}
        result_transported = service.evaluate_required(
            transported, section="eTimes"
        )
        assert "eTimes.13" in result_transported.unsatisfied_required_if_fields

    def test_unknown_operator_treated_as_unsatisfied(self) -> None:
        custom = NemsisFieldDefinition(
            field_id="eX.02",
            section="eX",
            label="X2",
            data_type="string",
            required_level="required_if",
            required_if=(
                NemsisRequiredIfRule(
                    field_id="eX.01", operator="bogus_operator", expected="y"
                ),
            ),
        )
        seed = NemsisFieldDefinition(
            field_id="eX.01",
            section="eX",
            label="X1",
            data_type="string",
            required_level="optional",
        )
        service = NemsisFieldGraphService(catalog=(seed, custom))
        result = service.evaluate_required({"eX.01": "y"}, section="eX")
        # Unknown operator must NOT silently mark as required-met.
        assert "eX.02" not in result.unsatisfied_required_if_fields
        # And because predicate is unsatisfied, eX.02 was not required at all.
        assert result.has_blockers is False


# ---------------------------------------------------------------------------
# HTTP-layer tests
# ---------------------------------------------------------------------------


class TestRoutes:
    def test_graph_endpoint_returns_200_with_metadata(self) -> None:
        client = _build_test_client()
        resp = client.get("/api/v1/epcr/nemsis-field-graph")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == DEFAULT_GRAPH_SOURCE
        assert body["field_count"] > 0
        assert body["section_count"] > 0
        assert isinstance(body["fields"], list)
        assert isinstance(body["sections"], list)
        # PHI must never appear in metadata payloads.
        joined = repr(body).lower()
        assert "patient_value" not in joined

    def test_section_endpoint_returns_200_for_known_section(self) -> None:
        client = _build_test_client()
        resp = client.get("/api/v1/epcr/nemsis-field-graph/sections/ePatient")
        assert resp.status_code == 200
        body = resp.json()
        assert body["section"] == "ePatient"
        assert body["summary"]["total_fields"] >= 3
        assert all(f["section"] == "ePatient" for f in body["fields"])

    def test_section_endpoint_returns_404_for_unknown_section(self) -> None:
        client = _build_test_client()
        resp = client.get("/api/v1/epcr/nemsis-field-graph/sections/eDoesNotExist")
        assert resp.status_code == 404
