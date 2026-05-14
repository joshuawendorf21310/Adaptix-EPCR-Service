"""ePCR NEMSIS CAD Dispatch Mapper.

Maps CAD dispatch-origin fields from a CAD handoff payload to the correct
NEMSIS 3.5.1 XML element paths for inclusion in the ePCR chart.

ePCR OWNS:
- Final NEMSIS 3.5.1 mapping
- XML generation
- XSD validation
- Schematron validation
- Clinical chart review

This mapper only maps dispatch-origin data that CAD legitimately provides.
All clinical fields must be entered by clinicians in ePCR.
NEMSIS XML is generated only from ePCR-owned validated chart state.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# NEMSIS 3.5.1 element paths for CAD-contributed dispatch fields
# Format: (nemsis_element, xml_path, description, required_for_submission)
NEMSIS_CAD_DISPATCH_ELEMENTS = [
    # eResponse section
    ("eResponse.05", "EMSDataSet/Header/PatientCareReport/eResponse/eResponse.05",
     "Type of Service Requested", True),
    ("eResponse.07", "EMSDataSet/Header/PatientCareReport/eResponse/eResponse.07",
     "Primary Role of the Unit", True),
    ("eResponse.13", "EMSDataSet/Header/PatientCareReport/eResponse/eResponse.13",
     "EMS Unit Number", False),
    ("eResponse.23", "EMSDataSet/Header/PatientCareReport/eResponse/eResponse.23",
     "Response Priority", False),
    # eTimes section
    ("eTimes.01", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.01",
     "PSAP Call Date/Time", False),
    ("eTimes.03", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.03",
     "Unit Notified by Dispatch Date/Time", False),
    ("eTimes.05", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.05",
     "Unit En Route Date/Time", True),
    ("eTimes.06", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.06",
     "Unit Arrived on Scene Date/Time", True),
    ("eTimes.07", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.07",
     "Arrived at Patient Date/Time", False),
    ("eTimes.09", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.09",
     "Unit Left Scene Date/Time", False),
    ("eTimes.11", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.11",
     "Patient Arrived at Destination Date/Time", True),
    ("eTimes.12", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.12",
     "Destination Patient Transfer of Care Date/Time", False),
    ("eTimes.13", "EMSDataSet/Header/PatientCareReport/eTimes/eTimes.13",
     "Unit Back in Service Date/Time", True),
    # eScene section
    ("eScene.11", "EMSDataSet/Header/PatientCareReport/eScene/eScene.11",
     "Scene GPS Latitude", False),
    ("eScene.12", "EMSDataSet/Header/PatientCareReport/eScene/eScene.12",
     "Scene GPS Longitude", False),
    ("eScene.15", "EMSDataSet/Header/PatientCareReport/eScene/eScene.15",
     "Scene Address", False),
    ("eScene.21", "EMSDataSet/Header/PatientCareReport/eScene/eScene.21",
     "Scene Facility or Landmark Name", False),
    # eDisposition section
    ("eDisposition.02", "EMSDataSet/Header/PatientCareReport/eDisposition/eDisposition.02",
     "Destination/Transferred To, Name", False),
    ("eDisposition.03", "EMSDataSet/Header/PatientCareReport/eDisposition/eDisposition.03",
     "Destination/Transferred To, Address", False),
    ("eDisposition.17", "EMSDataSet/Header/PatientCareReport/eDisposition/eDisposition.17",
     "Transport Distance", False),
    # eCrew section
    ("eCrew.01", "EMSDataSet/Header/PatientCareReport/eCrew/eCrew.01",
     "Crew Member Level", False),
    ("eCrew.02", "EMSDataSet/Header/PatientCareReport/eCrew/eCrew.02",
     "Crew Member ID", False),
    ("eCrew.03", "EMSDataSet/Header/PatientCareReport/eCrew/eCrew.03",
     "Crew Member Response Role", False),
]

# NEMSIS value set mappings for CAD transport type to NEMSIS eResponse.05 codes
TRANSPORT_TYPE_TO_NEMSIS = {
    "SCHEDULED": "2205001",       # Interfacility Transport
    "UNSCHEDULED": "2205003",     # Emergency Response (Primary)
    "INTERFACILITY": "2205001",   # Interfacility Transport
    "DISCHARGE": "2205001",       # Interfacility Transport
    "FACILITY_TO_FACILITY": "2205001",
    "SCENE_TO_FACILITY_MEDICAL": "2205003",
    "COMMUNITY_PARAMEDICINE": "2205009",
    "STANDBY": "2205011",
    "HEMS": "2205001",            # Interfacility Transport (air)
}

# NEMSIS value set mappings for CAD level of care to NEMSIS eResponse.07 codes
LEVEL_OF_CARE_TO_NEMSIS = {
    "BLS": "2207001",   # BLS
    "ALS": "2207003",   # ALS
    "CCT": "2207005",   # Critical Care Transport
    "SCT": "2207005",   # Critical Care Transport
    "WHEELCHAIR": "2207013",
    "STRETCHER": "2207015",
    "HEMS": "2207007",  # Air Medical
    "UNKNOWN": "2207017",
}


class CadDispatchNemsisMapper:
    """Maps CAD dispatch fields from a handoff payload to NEMSIS 3.5.1 element values.

    This mapper produces a structured dict of NEMSIS element values
    that can be used to pre-populate an ePCR chart draft.

    IMPORTANT:
    - This mapper does NOT generate NEMSIS XML.
    - XML generation is owned by the NEMSIS export pipeline.
    - All mapped values must be reviewed by clinicians before finalization.
    - Missing required elements are flagged for ePCR UI display.
    """

    def map_from_cad_handoff(
        self, handoff_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Map CAD handoff payload to NEMSIS element values.

        Args:
            handoff_payload: Full CadNemsisHandoffPayload as dict.

        Returns:
            Dict with:
            - nemsis_values: Dict of NEMSIS element -> value
            - missing_required: List of missing required NEMSIS elements
            - mapping_audit: List of mapping records for audit trail
            - warnings: List of validation warnings
        """
        nemsis_values: Dict[str, Any] = {}
        missing_required: List[str] = []
        mapping_audit: List[Dict[str, Any]] = []
        warnings: List[str] = []

        timeline = handoff_payload.get("timeline", {})
        origin = handoff_payload.get("origin_facility", {})
        destination = handoff_payload.get("destination_facility", {})
        crew_members = handoff_payload.get("crew_members", [])

        # eResponse.05 — Type of Service Requested
        transport_type = handoff_payload.get("transport_type")
        nemsis_transport = TRANSPORT_TYPE_TO_NEMSIS.get(transport_type) if transport_type else None
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eResponse.05",
            label="Type of Service Requested",
            cad_value=transport_type,
            nemsis_value=nemsis_transport,
            required=True,
            note=f"CAD transport_type '{transport_type}' mapped to NEMSIS code '{nemsis_transport}'" if nemsis_transport else None,
        )

        # eResponse.07 — Primary Role of the Unit
        level_of_care = handoff_payload.get("level_of_care")
        nemsis_loc = LEVEL_OF_CARE_TO_NEMSIS.get(level_of_care) if level_of_care else None
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eResponse.07",
            label="Primary Role of the Unit",
            cad_value=level_of_care,
            nemsis_value=nemsis_loc,
            required=True,
            note=f"CAD level_of_care '{level_of_care}' mapped to NEMSIS code '{nemsis_loc}'" if nemsis_loc else None,
        )

        # eResponse.13 — EMS Unit Number
        unit_id = handoff_payload.get("unit_id")
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eResponse.13",
            label="EMS Unit Number",
            cad_value=unit_id,
            nemsis_value=unit_id,
            required=False,
        )

        # eResponse.23 — Response Priority
        priority = handoff_payload.get("priority")
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eResponse.23",
            label="Response Priority",
            cad_value=priority,
            nemsis_value=priority,
            required=False,
        )

        # eTimes section — dispatch timeline
        time_mappings = [
            ("call_received_at", "eTimes.01", "PSAP Call Date/Time", False),
            ("unit_notified_at", "eTimes.03", "Unit Notified by Dispatch Date/Time", False),
            ("unit_enroute_at", "eTimes.05", "Unit En Route Date/Time", True),
            ("unit_arrived_origin_at", "eTimes.06", "Unit Arrived on Scene Date/Time", True),
            ("patient_contact_at", "eTimes.07", "Arrived at Patient Date/Time", False),
            ("transport_begin_at", "eTimes.09", "Unit Left Scene Date/Time", False),
            ("arrived_destination_at", "eTimes.11", "Patient Arrived at Destination Date/Time", True),
            ("transfer_of_care_at", "eTimes.12", "Destination Patient Transfer of Care Date/Time", False),
            ("unit_clear_at", "eTimes.13", "Unit Back in Service Date/Time", True),
        ]
        for cad_field, element, label, required in time_mappings:
            value = timeline.get(cad_field)
            self._record_mapping(
                nemsis_values, mapping_audit, missing_required, warnings,
                element=element,
                label=label,
                cad_value=value,
                nemsis_value=value,
                required=required,
            )

        # eScene section — origin/scene
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eScene.11",
            label="Scene GPS Latitude",
            cad_value=origin.get("latitude"),
            nemsis_value=str(origin.get("latitude")) if origin.get("latitude") is not None else None,
            required=False,
        )
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eScene.12",
            label="Scene GPS Longitude",
            cad_value=origin.get("longitude"),
            nemsis_value=str(origin.get("longitude")) if origin.get("longitude") is not None else None,
            required=False,
        )
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eScene.15",
            label="Scene Address",
            cad_value=origin.get("facility_address"),
            nemsis_value=origin.get("facility_address"),
            required=False,
        )
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eScene.21",
            label="Scene Facility or Landmark Name",
            cad_value=origin.get("facility_name"),
            nemsis_value=origin.get("facility_name"),
            required=False,
        )

        # eDisposition section — destination
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eDisposition.02",
            label="Destination/Transferred To, Name",
            cad_value=destination.get("facility_name"),
            nemsis_value=destination.get("facility_name"),
            required=False,
        )
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eDisposition.03",
            label="Destination/Transferred To, Address",
            cad_value=destination.get("facility_address"),
            nemsis_value=destination.get("facility_address"),
            required=False,
        )
        mileage = handoff_payload.get("mileage_estimate")
        self._record_mapping(
            nemsis_values, mapping_audit, missing_required, warnings,
            element="eDisposition.17",
            label="Transport Distance",
            cad_value=mileage,
            nemsis_value=str(mileage) if mileage is not None else None,
            required=False,
            note="Requires clinician verification before finalization",
        )

        # eCrew section — crew identifiers
        if crew_members:
            for i, crew in enumerate(crew_members):
                crew_id = crew.get("crew_id")
                crew_role = crew.get("role")
                cert_level = crew.get("certification_level")
                if crew_id:
                    nemsis_values[f"eCrew.02[{i}]"] = crew_id
                if crew_role:
                    nemsis_values[f"eCrew.01[{i}]"] = crew_role
                if cert_level:
                    nemsis_values[f"eCrew.03[{i}]"] = cert_level
            mapping_audit.append({
                "nemsis_element": "eCrew",
                "label": "Crew Members",
                "cad_value": crew_members,
                "nemsis_value": f"{len(crew_members)} crew member(s) mapped",
                "mapped": True,
                "cad_source": "adaptix-cad",
            })

        return {
            "nemsis_values": nemsis_values,
            "missing_required": missing_required,
            "mapping_audit": mapping_audit,
            "warnings": warnings,
            "mapped_count": len([m for m in mapping_audit if m.get("mapped")]),
            "missing_count": len(missing_required),
            "cad_source": handoff_payload.get("handoff_source", "adaptix-cad"),
            "cad_handoff_id": handoff_payload.get("handoff_id"),
            "cad_dispatch_id": handoff_payload.get("cad_dispatch_id"),
        }

    def _record_mapping(
        self,
        nemsis_values: Dict[str, Any],
        mapping_audit: List[Dict[str, Any]],
        missing_required: List[str],
        warnings: List[str],
        *,
        element: str,
        label: str,
        cad_value: Any,
        nemsis_value: Any,
        required: bool,
        note: Optional[str] = None,
    ) -> None:
        """Record a single field mapping result.

        Args:
            nemsis_values: Dict to update with mapped value.
            mapping_audit: List to append audit record to.
            missing_required: List to append missing required elements to.
            warnings: List to append validation warnings to.
            element: NEMSIS element code.
            label: NEMSIS element label.
            cad_value: Original CAD value.
            nemsis_value: Mapped NEMSIS value.
            required: Whether this element is required for submission.
            note: Optional mapping note.
        """
        mapped = nemsis_value is not None and nemsis_value != ""

        if mapped:
            nemsis_values[element] = nemsis_value
        elif required:
            missing_required.append(element)
            warnings.append(
                f"Required NEMSIS element {element} ({label}) "
                f"not available from CAD handoff — must be entered in ePCR"
            )

        mapping_audit.append({
            "nemsis_element": element,
            "label": label,
            "cad_value": cad_value,
            "nemsis_value": nemsis_value,
            "mapped": mapped,
            "required": required,
            "note": note,
            "cad_source": "adaptix-cad",
        })

    def get_element_definitions(self) -> List[Dict[str, Any]]:
        """Return all NEMSIS element definitions for CAD dispatch fields.

        Returns:
            List of element definition dicts.
        """
        return [
            {
                "nemsis_element": element,
                "xml_path": xml_path,
                "description": description,
                "required_for_submission": required,
            }
            for element, xml_path, description, required in NEMSIS_CAD_DISPATCH_ELEMENTS
        ]
