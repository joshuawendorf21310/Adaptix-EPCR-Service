"""Tests for CadHandoffIngestService.

Real service logic tests — no mocks, no fake data.
Tests verify the service correctly ingests CAD handoff payloads,
maps fields to NEMSIS elements, enforces tenant isolation,
and identifies missing required elements.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from epcr_app.cad_handoff_ingest_service import (
    CadHandoffIngestService,
    REQUIRED_NEMSIS_ELEMENTS,
    CLINICIAN_REVIEW_REQUIRED_ELEMENTS,
    _get_nested_value,
)


@pytest.fixture
def service() -> CadHandoffIngestService:
    return CadHandoffIngestService()


@pytest.fixture
def full_cad_payload() -> dict:
    """Real CAD handoff payload with all fields populated."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "handoff_id": "hndff-001",
        "cad_dispatch_id": "disp-001",
        "tenant_id": "tenant-001",
        "transport_type": "INTERFACILITY",
        "level_of_care": "ALS",
        "priority": "high",
        "unit_id": "UNIT-12",
        "vehicle_id": "VEH-12",
        "crew_members": [
            {"crew_id": "crew-001", "role": "PARAMEDIC", "certification_level": "ALS"},
            {"crew_id": "crew-002", "role": "EMT", "certification_level": "BLS"},
        ],
        "origin_facility": {
            "facility_name": "St. Mary's Hospital",
            "facility_address": "123 Main St, Springfield, IL 62701",
            "facility_department": "ICU",
            "latitude": 39.7817,
            "longitude": -89.6501,
        },
        "destination_facility": {
            "facility_name": "University Medical Center",
            "facility_address": "456 Oak Ave, Chicago, IL 60601",
            "facility_department": "Cardiac Care",
            "latitude": 41.8781,
            "longitude": -87.6298,
        },
        "mileage_estimate": 24.7,
        "route_eta_minutes": 38.0,
        "timeline": {
            "call_received_at": now,
            "unit_notified_at": now,
            "unit_enroute_at": now,
            "unit_arrived_origin_at": now,
            "patient_contact_at": now,
            "transport_begin_at": now,
            "arrived_destination_at": now,
            "transfer_of_care_at": now,
            "unit_clear_at": now,
            "dispatch_created_at": now,
            "unit_assigned_at": now,
        },
        "cad_notes": "Patient requires cardiac monitoring during transport",
        "crew_briefing": "ALS transport, cardiac monitoring required",
        "facility_handoff_notes": "Receiving cardiologist notified",
        "handoff_source": "adaptix-cad",
        "handoff_version": "1.0",
    }


@pytest.fixture
def minimal_cad_payload() -> dict:
    """Minimal CAD handoff payload with only required fields."""
    return {
        "handoff_id": "hndff-002",
        "cad_dispatch_id": "disp-002",
        "tenant_id": "tenant-001",
        "transport_type": "SCHEDULED",
        "level_of_care": "BLS",
        "crew_members": [],
        "origin_facility": {},
        "destination_facility": {},
        "timeline": {},
        "handoff_source": "adaptix-cad",
        "handoff_version": "1.0",
    }


class TestIngest:
    """Tests for ingest method."""

    def test_ingest_full_payload_returns_success(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Full payload ingest must return success status."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        assert result["ingest_status"] == "success"
        assert result["fields_mapped"] > 0
        assert result["handoff_id"] == "hndff-001"
        assert result["cad_dispatch_id"] == "disp-001"
        assert result["tenant_id"] == "tenant-001"

    def test_ingest_minimal_payload_returns_partial(
        self, service: CadHandoffIngestService, minimal_cad_payload: dict
    ) -> None:
        """Minimal payload without timeline must return partial status."""
        result = service.ingest(
            handoff_id="hndff-002",
            cad_dispatch_id="disp-002",
            tenant_id="tenant-001",
            handoff_payload=minimal_cad_payload,
        )
        assert result["ingest_status"] == "partial"
        assert len(result["missing_required_nemsis_elements"]) > 0

    def test_ingest_creates_new_chart_id_when_not_provided(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """New chart ID must be generated when not provided."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        assert result["epcr_chart_id"] is not None
        assert len(result["epcr_chart_id"]) > 0

    def test_ingest_uses_provided_chart_id(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Provided chart ID must be used."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
            epcr_chart_id="chart-existing-001",
        )
        assert result["epcr_chart_id"] == "chart-existing-001"

    def test_ingest_raises_on_missing_handoff_id(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """ValueError must be raised when handoff_id is missing."""
        with pytest.raises(ValueError, match="handoff_id is required"):
            service.ingest(
                handoff_id="",
                cad_dispatch_id="disp-001",
                tenant_id="tenant-001",
                handoff_payload=full_cad_payload,
            )

    def test_ingest_raises_on_missing_dispatch_id(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """ValueError must be raised when cad_dispatch_id is missing."""
        with pytest.raises(ValueError, match="cad_dispatch_id is required"):
            service.ingest(
                handoff_id="hndff-001",
                cad_dispatch_id="",
                tenant_id="tenant-001",
                handoff_payload=full_cad_payload,
            )

    def test_ingest_raises_on_missing_tenant_id(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """ValueError must be raised when tenant_id is missing."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            service.ingest(
                handoff_id="hndff-001",
                cad_dispatch_id="disp-001",
                tenant_id="",
                handoff_payload=full_cad_payload,
            )

    def test_ingest_raises_on_tenant_mismatch(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """ValueError must be raised when payload tenant does not match request tenant."""
        with pytest.raises(ValueError, match="Tenant mismatch"):
            service.ingest(
                handoff_id="hndff-001",
                cad_dispatch_id="disp-001",
                tenant_id="tenant-DIFFERENT",
                handoff_payload=full_cad_payload,
            )

    def test_ingest_maps_transport_type_to_nemsis_element(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """transport_type must be mapped to eResponse.05."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        eresponse_05 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eResponse.05"),
            None,
        )
        assert eresponse_05 is not None
        assert eresponse_05["mapped"] is True
        assert eresponse_05["cad_value"] == "INTERFACILITY"

    def test_ingest_maps_level_of_care_to_nemsis_element(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """level_of_care must be mapped to eResponse.07."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        eresponse_07 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eResponse.07"),
            None,
        )
        assert eresponse_07 is not None
        assert eresponse_07["mapped"] is True
        assert eresponse_07["cad_value"] == "ALS"

    def test_ingest_maps_timeline_timestamps(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Timeline timestamps must be mapped to eTimes elements."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        etimes_05 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eTimes.05"),
            None,
        )
        assert etimes_05 is not None
        assert etimes_05["mapped"] is True

        etimes_11 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eTimes.11"),
            None,
        )
        assert etimes_11 is not None
        assert etimes_11["mapped"] is True

    def test_ingest_maps_origin_facility(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Origin facility must be mapped to eScene elements."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        escene_21 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eScene.21"),
            None,
        )
        assert escene_21 is not None
        assert escene_21["mapped"] is True
        assert escene_21["cad_value"] == "St. Mary's Hospital"

    def test_ingest_maps_destination_facility(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Destination facility must be mapped to eDisposition elements."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        edisposition_02 = next(
            (m for m in result["field_mappings"] if m["nemsis_element"] == "eDisposition.02"),
            None,
        )
        assert edisposition_02 is not None
        assert edisposition_02["mapped"] is True
        assert edisposition_02["cad_value"] == "University Medical Center"

    def test_ingest_preserves_cad_source_attribution(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Every mapped field must have CAD source attribution."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        assert result["cad_source"] == "adaptix-cad"
        for mapping in result["field_mappings"]:
            assert mapping["cad_source_attribution"] == "adaptix-cad"

    def test_ingest_returns_validation_warnings_for_missing_required(
        self, service: CadHandoffIngestService, minimal_cad_payload: dict
    ) -> None:
        """Validation warnings must be returned for missing required NEMSIS elements."""
        result = service.ingest(
            handoff_id="hndff-002",
            cad_dispatch_id="disp-002",
            tenant_id="tenant-001",
            handoff_payload=minimal_cad_payload,
        )
        assert len(result["validation_warnings"]) > 0
        # All warnings must reference NEMSIS elements
        for warning in result["validation_warnings"]:
            assert "NEMSIS" in warning or "eTimes" in warning or "eResponse" in warning

    def test_ingest_includes_audit_id(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Ingest result must include an audit ID."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        assert result["audit_id"] is not None
        assert len(result["audit_id"]) > 0

    def test_ingest_includes_ingested_at_timestamp(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Ingest result must include ingested_at timestamp."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        assert result["ingested_at"] is not None

    def test_ingest_does_not_include_clinical_fields(
        self, service: CadHandoffIngestService, full_cad_payload: dict
    ) -> None:
        """Ingest result must not include clinical fields invented by CAD."""
        result = service.ingest(
            handoff_id="hndff-001",
            cad_dispatch_id="disp-001",
            tenant_id="tenant-001",
            handoff_payload=full_cad_payload,
        )
        # Clinical fields must not be in the result
        assert "chief_complaint" not in result
        assert "vitals" not in result
        assert "medications" not in result
        assert "procedures" not in result
        assert "clinical_assessment" not in result


class TestGetNestedValue:
    """Tests for _get_nested_value helper."""

    def test_gets_top_level_value(self) -> None:
        data = {"transport_type": "INTERFACILITY"}
        assert _get_nested_value(data, "transport_type") == "INTERFACILITY"

    def test_gets_nested_value(self) -> None:
        data = {"timeline": {"unit_enroute_at": "2026-05-03T12:00:00Z"}}
        assert _get_nested_value(data, "timeline.unit_enroute_at") == "2026-05-03T12:00:00Z"

    def test_returns_none_for_missing_key(self) -> None:
        data = {"timeline": {}}
        assert _get_nested_value(data, "timeline.unit_enroute_at") is None

    def test_returns_none_for_missing_parent(self) -> None:
        data = {}
        assert _get_nested_value(data, "timeline.unit_enroute_at") is None

    def test_returns_none_for_non_dict_parent(self) -> None:
        data = {"timeline": "not_a_dict"}
        assert _get_nested_value(data, "timeline.unit_enroute_at") is None


class TestRequiredElements:
    """Tests for required NEMSIS elements configuration."""

    def test_required_elements_set_is_complete(self) -> None:
        """Required NEMSIS elements set must include all critical elements."""
        assert "eResponse.05" in REQUIRED_NEMSIS_ELEMENTS
        assert "eResponse.07" in REQUIRED_NEMSIS_ELEMENTS
        assert "eTimes.05" in REQUIRED_NEMSIS_ELEMENTS
        assert "eTimes.06" in REQUIRED_NEMSIS_ELEMENTS
        assert "eTimes.11" in REQUIRED_NEMSIS_ELEMENTS
        assert "eTimes.13" in REQUIRED_NEMSIS_ELEMENTS

    def test_clinician_review_elements_set(self) -> None:
        """Clinician review elements must include transport distance."""
        assert "eDisposition.17" in CLINICIAN_REVIEW_REQUIRED_ELEMENTS
