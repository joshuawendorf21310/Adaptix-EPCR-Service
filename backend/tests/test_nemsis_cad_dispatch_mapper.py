"""Tests for CadDispatchNemsisMapper.

Real service logic tests — no mocks, no fake data.
Tests verify the mapper correctly maps CAD dispatch fields to NEMSIS 3.5.1
element values, applies correct value set codes, and identifies missing elements.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from epcr_app.nemsis.cad_dispatch_mapper import (
    CadDispatchNemsisMapper,
    TRANSPORT_TYPE_TO_NEMSIS,
    LEVEL_OF_CARE_TO_NEMSIS,
    NEMSIS_CAD_DISPATCH_ELEMENTS,
)


@pytest.fixture
def mapper() -> CadDispatchNemsisMapper:
    return CadDispatchNemsisMapper()


@pytest.fixture
def full_handoff_payload() -> dict:
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
            "latitude": 39.7817,
            "longitude": -89.6501,
        },
        "destination_facility": {
            "facility_name": "University Medical Center",
            "facility_address": "456 Oak Ave, Chicago, IL 60601",
        },
        "mileage_estimate": 24.7,
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
        },
        "handoff_source": "adaptix-cad",
        "handoff_version": "1.0",
    }


@pytest.fixture
def minimal_handoff_payload() -> dict:
    """Minimal CAD handoff payload."""
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
    }


class TestMapFromCadHandoff:
    """Tests for map_from_cad_handoff method."""

    def test_maps_transport_type_to_nemsis_code(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """INTERFACILITY transport type must map to NEMSIS code 2205001."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eResponse.05"] == "2205001"

    def test_maps_level_of_care_to_nemsis_code(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """ALS level of care must map to NEMSIS code 2207003."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eResponse.07"] == "2207003"

    def test_maps_unit_id_to_eresponse_13(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Unit ID must map to eResponse.13."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eResponse.13"] == "UNIT-12"

    def test_maps_timeline_enroute_to_etimes_05(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """unit_enroute_at must map to eTimes.05."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "eTimes.05" in result["nemsis_values"]
        assert result["nemsis_values"]["eTimes.05"] is not None

    def test_maps_timeline_arrived_origin_to_etimes_06(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """unit_arrived_origin_at must map to eTimes.06."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "eTimes.06" in result["nemsis_values"]

    def test_maps_timeline_arrived_destination_to_etimes_11(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """arrived_destination_at must map to eTimes.11."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "eTimes.11" in result["nemsis_values"]

    def test_maps_timeline_unit_clear_to_etimes_13(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """unit_clear_at must map to eTimes.13."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "eTimes.13" in result["nemsis_values"]

    def test_maps_origin_facility_name_to_escene_21(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Origin facility name must map to eScene.21."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eScene.21"] == "St. Mary's Hospital"

    def test_maps_origin_address_to_escene_15(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Origin address must map to eScene.15."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eScene.15"] == "123 Main St, Springfield, IL 62701"

    def test_maps_origin_coordinates_to_escene_11_12(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Origin coordinates must map to eScene.11 and eScene.12."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eScene.11"] == "39.7817"
        assert result["nemsis_values"]["eScene.12"] == "-89.6501"

    def test_maps_destination_facility_name_to_edisposition_02(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Destination facility name must map to eDisposition.02."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eDisposition.02"] == "University Medical Center"

    def test_maps_mileage_to_edisposition_17(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Mileage estimate must map to eDisposition.17."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["nemsis_values"]["eDisposition.17"] == "24.7"

    def test_maps_crew_members_to_ecrew(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Crew members must be mapped to eCrew elements."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "eCrew.02[0]" in result["nemsis_values"]
        assert result["nemsis_values"]["eCrew.02[0]"] == "crew-001"
        assert "eCrew.01[0]" in result["nemsis_values"]
        assert result["nemsis_values"]["eCrew.01[0]"] == "PARAMEDIC"

    def test_identifies_missing_required_elements_when_timeline_empty(
        self, mapper: CadDispatchNemsisMapper, minimal_handoff_payload: dict
    ) -> None:
        """Missing required NEMSIS elements must be identified."""
        result = mapper.map_from_cad_handoff(minimal_handoff_payload)
        assert "eTimes.05" in result["missing_required"]
        assert "eTimes.06" in result["missing_required"]
        assert "eTimes.11" in result["missing_required"]
        assert "eTimes.13" in result["missing_required"]

    def test_no_missing_required_when_all_present(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """No missing required elements when all are present."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["missing_required"] == []

    def test_returns_mapping_audit(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Mapping audit must be returned with all mapped fields."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert len(result["mapping_audit"]) > 0
        for audit_record in result["mapping_audit"]:
            assert "nemsis_element" in audit_record
            assert "cad_source" in audit_record
            assert audit_record["cad_source"] == "adaptix-cad"

    def test_returns_warnings_for_missing_required(
        self, mapper: CadDispatchNemsisMapper, minimal_handoff_payload: dict
    ) -> None:
        """Warnings must be returned for missing required elements."""
        result = mapper.map_from_cad_handoff(minimal_handoff_payload)
        assert len(result["warnings"]) > 0

    def test_returns_cad_source_attribution(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Result must include CAD source attribution."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert result["cad_source"] == "adaptix-cad"
        assert result["cad_handoff_id"] == "hndff-001"
        assert result["cad_dispatch_id"] == "disp-001"

    def test_does_not_generate_xml(
        self, mapper: CadDispatchNemsisMapper, full_handoff_payload: dict
    ) -> None:
        """Mapper must NOT generate NEMSIS XML — only element values."""
        result = mapper.map_from_cad_handoff(full_handoff_payload)
        assert "xml" not in result
        assert "xml_bytes" not in result
        assert "xml_content" not in result
        # nemsis_values must be a dict of element codes to values, not XML
        assert isinstance(result["nemsis_values"], dict)


class TestTransportTypeMapping:
    """Tests for TRANSPORT_TYPE_TO_NEMSIS value set."""

    def test_interfacility_maps_to_2205001(self) -> None:
        assert TRANSPORT_TYPE_TO_NEMSIS["INTERFACILITY"] == "2205001"

    def test_unscheduled_maps_to_2205003(self) -> None:
        assert TRANSPORT_TYPE_TO_NEMSIS["UNSCHEDULED"] == "2205003"

    def test_scheduled_maps_to_2205001(self) -> None:
        assert TRANSPORT_TYPE_TO_NEMSIS["SCHEDULED"] == "2205001"

    def test_hems_maps_to_2205001(self) -> None:
        assert TRANSPORT_TYPE_TO_NEMSIS["HEMS"] == "2205001"

    def test_community_paramedicine_maps_to_2205009(self) -> None:
        assert TRANSPORT_TYPE_TO_NEMSIS["COMMUNITY_PARAMEDICINE"] == "2205009"


class TestLevelOfCareMapping:
    """Tests for LEVEL_OF_CARE_TO_NEMSIS value set."""

    def test_bls_maps_to_2207001(self) -> None:
        assert LEVEL_OF_CARE_TO_NEMSIS["BLS"] == "2207001"

    def test_als_maps_to_2207003(self) -> None:
        assert LEVEL_OF_CARE_TO_NEMSIS["ALS"] == "2207003"

    def test_cct_maps_to_2207005(self) -> None:
        assert LEVEL_OF_CARE_TO_NEMSIS["CCT"] == "2207005"

    def test_hems_maps_to_2207007(self) -> None:
        assert LEVEL_OF_CARE_TO_NEMSIS["HEMS"] == "2207007"

    def test_unknown_maps_to_2207017(self) -> None:
        assert LEVEL_OF_CARE_TO_NEMSIS["UNKNOWN"] == "2207017"


class TestElementDefinitions:
    """Tests for get_element_definitions method."""

    def test_returns_all_element_definitions(
        self, mapper: CadDispatchNemsisMapper
    ) -> None:
        """Must return definitions for all CAD dispatch NEMSIS elements."""
        defs = mapper.get_element_definitions()
        assert len(defs) == len(NEMSIS_CAD_DISPATCH_ELEMENTS)

    def test_element_definitions_have_required_fields(
        self, mapper: CadDispatchNemsisMapper
    ) -> None:
        """Each element definition must have required fields."""
        defs = mapper.get_element_definitions()
        for d in defs:
            assert "nemsis_element" in d
            assert "xml_path" in d
            assert "description" in d
            assert "required_for_submission" in d

    def test_required_elements_are_marked(
        self, mapper: CadDispatchNemsisMapper
    ) -> None:
        """Required elements must be marked as required_for_submission=True."""
        defs = mapper.get_element_definitions()
        required_elements = {d["nemsis_element"] for d in defs if d["required_for_submission"]}
        assert "eResponse.05" in required_elements
        assert "eResponse.07" in required_elements
        assert "eTimes.05" in required_elements
        assert "eTimes.06" in required_elements
        assert "eTimes.11" in required_elements
        assert "eTimes.13" in required_elements
