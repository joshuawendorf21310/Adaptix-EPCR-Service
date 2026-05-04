"""ePCR CAD Handoff Ingest Service.

Ingests a CAD-to-ePCR handoff payload into an ePCR chart draft.
Maps CAD dispatch-origin fields to NEMSIS 3.5.1 elements where applicable.
Preserves CAD source attribution on every mapped field.
Does NOT overwrite clinician-entered ePCR data without explicit review.

ePCR OWNS:
- Final NEMSIS 3.5.1 mapping
- XML generation
- XSD validation
- Schematron validation
- Clinical chart review

CAD DOES NOT OWN:
- Clinical fields
- NEMSIS XML generation
- NEMSIS validation
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# NEMSIS 3.5.1 elements that CAD handoff can contribute to
# Maps: (cad_payload_path, nemsis_element, nemsis_label, requires_clinician_review)
CAD_TO_NEMSIS_FIELD_MAP: List[Tuple[str, str, str, bool]] = [
    # eResponse section — dispatch/response metadata
    ("transport_type", "eResponse.05", "Type of Service Requested", False),
    ("level_of_care", "eResponse.07", "Primary Role of the Unit", False),
    ("priority", "eResponse.23", "Response Priority", False),
    ("unit_id", "eResponse.13", "EMS Unit Number", False),
    # eTimes section — dispatch timeline
    ("timeline.call_received_at", "eTimes.01", "PSAP Call Date/Time", False),
    ("timeline.unit_notified_at", "eTimes.03", "Unit Notified by Dispatch Date/Time", False),
    ("timeline.unit_enroute_at", "eTimes.05", "Unit En Route Date/Time", False),
    ("timeline.unit_arrived_origin_at", "eTimes.06", "Unit Arrived on Scene Date/Time", False),
    ("timeline.patient_contact_at", "eTimes.07", "Arrived at Patient Date/Time", False),
    ("timeline.transport_begin_at", "eTimes.09", "Unit Left Scene Date/Time", False),
    ("timeline.arrived_destination_at", "eTimes.11", "Patient Arrived at Destination Date/Time", False),
    ("timeline.transfer_of_care_at", "eTimes.12", "Destination Patient Transfer of Care Date/Time", False),
    ("timeline.unit_clear_at", "eTimes.13", "Unit Back in Service Date/Time", False),
    # eScene section — origin/scene
    ("origin_facility.facility_name", "eScene.21", "Scene Facility or Landmark Name", False),
    ("origin_facility.facility_address", "eScene.15", "Scene Address", False),
    ("origin_facility.latitude", "eScene.11", "Scene GPS Latitude", False),
    ("origin_facility.longitude", "eScene.12", "Scene GPS Longitude", False),
    # eDisposition section — destination
    ("destination_facility.facility_name", "eDisposition.02", "Destination/Transferred To, Name", False),
    ("destination_facility.facility_address", "eDisposition.03", "Destination/Transferred To, Address", False),
    ("mileage_estimate", "eDisposition.17", "Transport Distance", False),
    # eCrew section — crew identifiers
    ("crew_members", "eCrew", "Crew Members", False),
]

# NEMSIS elements that require clinician review before acceptance
CLINICIAN_REVIEW_REQUIRED_ELEMENTS = {
    "eDisposition.17",  # Transport distance — clinician should verify
}

# Required NEMSIS elements that CAD can contribute to
REQUIRED_NEMSIS_ELEMENTS = {
    "eResponse.05",
    "eResponse.07",
    "eTimes.05",
    "eTimes.06",
    "eTimes.11",
    "eTimes.13",
}


def _get_nested_value(data: Dict[str, Any], path: str) -> Any:
    """Get a nested value from a dict using dot-notation path.

    Args:
        data: Source dict.
        path: Dot-notation path (e.g. 'timeline.unit_enroute_at').

    Returns:
        Value at path or None if not found.
    """
    parts = path.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class CadHandoffIngestService:
    """Service for ingesting CAD handoff payloads into ePCR chart drafts.

    Maps CAD dispatch-origin fields to NEMSIS 3.5.1 elements.
    Preserves CAD source attribution.
    Does NOT overwrite clinician-entered data.
    Marks missing required NEMSIS elements.
    Returns validation warnings to ePCR UI.
    Stores handoff mapping audit.
    """

    def ingest(
        self,
        *,
        handoff_id: str,
        cad_dispatch_id: str,
        tenant_id: str,
        handoff_payload: Dict[str, Any],
        epcr_chart_id: Optional[str] = None,
        ingest_requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingest a CAD handoff payload into an ePCR chart draft.

        Args:
            handoff_id: Unique handoff record ID.
            cad_dispatch_id: CAD dispatch/case ID.
            tenant_id: Tenant ID for multi-tenancy.
            handoff_payload: Full CadNemsisHandoffPayload as dict.
            epcr_chart_id: If provided, ingest into existing chart. If None, create new draft.
            ingest_requested_by: User ID requesting the ingest.

        Returns:
            Dict with ingest result including field mappings, warnings, and audit info.

        Raises:
            ValueError: If required fields are missing from handoff payload.
        """
        if not handoff_id:
            raise ValueError("handoff_id is required for CAD handoff ingest")
        if not cad_dispatch_id:
            raise ValueError("cad_dispatch_id is required for CAD handoff ingest")
        if not tenant_id:
            raise ValueError("tenant_id is required for CAD handoff ingest")
        if not handoff_payload:
            raise ValueError("handoff_payload is required for CAD handoff ingest")

        # Verify tenant isolation — payload tenant must match request tenant
        payload_tenant = handoff_payload.get("tenant_id")
        if payload_tenant and payload_tenant != tenant_id:
            raise ValueError(
                f"Tenant mismatch: handoff payload tenant '{payload_tenant}' "
                f"does not match request tenant '{tenant_id}'"
            )

        chart_id = epcr_chart_id or str(uuid.uuid4())
        audit_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        field_mappings, validation_warnings, missing_required = self._map_fields(handoff_payload)

        fields_mapped = sum(1 for m in field_mappings if m["mapped"])
        fields_missing = sum(1 for m in field_mappings if not m["mapped"])
        fields_requiring_review = sum(1 for m in field_mappings if m.get("requires_clinician_review"))

        ingest_status = "success"
        if missing_required:
            ingest_status = "partial"
        if fields_mapped == 0:
            ingest_status = "failed"

        logger.info(
            "CAD handoff ingested into ePCR chart",
            extra={
                "handoff_id": handoff_id,
                "cad_dispatch_id": cad_dispatch_id,
                "epcr_chart_id": chart_id,
                "tenant_id": tenant_id,
                "ingest_status": ingest_status,
                "fields_mapped": fields_mapped,
                "fields_missing": fields_missing,
                "missing_required_count": len(missing_required),
                "audit_id": audit_id,
            },
        )

        if missing_required:
            logger.warning(
                "CAD handoff ingest has missing required NEMSIS elements",
                extra={
                    "handoff_id": handoff_id,
                    "missing_required": missing_required,
                },
            )

        return {
            "handoff_id": handoff_id,
            "cad_dispatch_id": cad_dispatch_id,
            "epcr_chart_id": chart_id,
            "tenant_id": tenant_id,
            "ingest_status": ingest_status,
            "fields_mapped": fields_mapped,
            "fields_missing": fields_missing,
            "fields_requiring_review": fields_requiring_review,
            "field_mappings": field_mappings,
            "validation_warnings": validation_warnings,
            "missing_required_nemsis_elements": missing_required,
            "cad_source": handoff_payload.get("handoff_source", "adaptix-cad"),
            "cad_handoff_version": handoff_payload.get("handoff_version", "1.0"),
            "audit_id": audit_id,
            "ingested_at": now.isoformat(),
            "ingest_requested_by": ingest_requested_by,
        }

    def _map_fields(
        self, payload: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        """Map CAD payload fields to NEMSIS elements.

        Args:
            payload: CAD handoff payload dict.

        Returns:
            Tuple of (field_mappings, validation_warnings, missing_required_elements).
        """
        field_mappings: List[Dict[str, Any]] = []
        validation_warnings: List[str] = []
        missing_required: List[str] = []

        for cad_path, nemsis_element, nemsis_label, _ in CAD_TO_NEMSIS_FIELD_MAP:
            requires_review = nemsis_element in CLINICIAN_REVIEW_REQUIRED_ELEMENTS

            if cad_path == "crew_members":
                # Special handling for crew list
                crew_members = payload.get("crew_members", [])
                mapped = bool(crew_members)
                cad_value = crew_members if mapped else None
                mapping_note = f"{len(crew_members)} crew member(s) from CAD dispatch" if mapped else "No crew assigned in CAD"
            else:
                cad_value = _get_nested_value(payload, cad_path)
                mapped = cad_value is not None and cad_value != "" and cad_value != []
                mapping_note = None

            if not mapped and nemsis_element in REQUIRED_NEMSIS_ELEMENTS:
                missing_required.append(nemsis_element)
                validation_warnings.append(
                    f"Required NEMSIS element {nemsis_element} ({nemsis_label}) "
                    f"not available from CAD handoff — must be entered in ePCR"
                )

            if mapped and requires_review:
                validation_warnings.append(
                    f"NEMSIS element {nemsis_element} ({nemsis_label}) "
                    f"mapped from CAD — requires clinician review before finalization"
                )

            field_mappings.append({
                "nemsis_element": nemsis_element,
                "nemsis_label": nemsis_label,
                "cad_source_field": cad_path,
                "cad_value": cad_value,
                "mapped": mapped,
                "mapping_note": mapping_note,
                "requires_clinician_review": requires_review,
                "missing_required": not mapped and nemsis_element in REQUIRED_NEMSIS_ELEMENTS,
                "cad_source_attribution": "adaptix-cad",
            })

        return field_mappings, validation_warnings, missing_required
