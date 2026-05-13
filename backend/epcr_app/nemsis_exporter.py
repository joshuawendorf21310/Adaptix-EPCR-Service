"""NEMSIS 3.5.1 XML exporter for the epcr domain.

Generates structured EMSDataSet XML from Chart and related clinical data.
Covers all 13 required sections: eRecord, eResponse, eTimes, ePatient,
eSituation, eHistory, eVitals, eMedications, eProcedures, eNarrative,
eDisposition, eIncident, and dAgency.

Software field semantics (eRecord.SoftwareApplicationGroup):
- eRecord.02: software creator organization name
- eRecord.03: software application name
- eRecord.04: software application version
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

NEMSIS_NS = "http://www.nemsis.org"
NEMSIS_VERSION = "3.5.1"
NEMSIS_VERSION_FULL = "3.5.1.251001CP2"
NV_NOT_RECORDED = "7701003"
NV_NOT_APPLICABLE = "7701001"
NV_NOT_REPORTING = "7701005"

SOFTWARE_CREATOR = "FusionEMSQuantum"
SOFTWARE_NAME = "Adaptix ePCR"
SOFTWARE_VERSION = "1.0.0"

_GENDER_MAP: dict[str, str] = {
    "male": "9906001",
    "female": "9906003",
    "other": "9906011",
    "unknown": "9906009",
    "transgender_male": "9906007",
    "transgender_female": "9906005",
}

_RACE_MAP: dict[str, str] = {
    "white": "2514001",
    "black": "2514003",
    "asian": "2514005",
    "native": "2514007",
    "pacific": "2514009",
    "other": "2514011",
    "hispanic": "2514013",
}

_TRANSPORT_MODE_MAP: dict[str, str] = {
    "emergent": "4233001",
    "non_emergent": "4233003",
    "cancel": "4233005",
}

_LEVEL_OF_CARE_MAP: dict[str, str] = {
    "bls": "9917001",
    "als": "9917003",
    "cct": "9917007",
    "hems": "9917011",
}


# NEMSIS 3.5.1 eExam body region code mapping for the 18 canonical 3D
# Physical Assessment region IDs. Codes target eExam.19 (Exam Body
# Region). Regions that lack a precise eExam mapping are emitted as
# ``NV_NOT_RECORDED`` here but ALWAYS surface their structured form in
# the custom-element block below so no data is silently dropped.
# TODO: re-validate full set of eExam.19 codes against the released
# NEMSIS 3.5.1 schema; pelvis / abdomen split is approximate.
_EEXAM_BODY_REGION_MAP: dict[str, str] = {
    "region_head": "3319031",        # Head
    "region_neck": "3319037",        # Neck
    "region_chest": "3319011",       # Chest
    "region_abdomen": "3319001",     # Abdomen
    "region_back": "3319005",        # Back
    "region_pelvis": "3319041",      # Pelvis/Genitourinary
    "region_left_upper_arm": "3319033",   # Left Upper Extremity
    "region_left_forearm": "3319033",
    "region_left_hand": "3319033",
    "region_right_upper_arm": "3319049",  # Right Upper Extremity
    "region_right_forearm": "3319049",
    "region_right_hand": "3319049",
    "region_left_thigh": "3319035",       # Left Lower Extremity
    "region_left_lower_leg": "3319035",
    "region_left_foot": "3319035",
    "region_right_thigh": "3319051",      # Right Lower Extremity
    "region_right_lower_leg": "3319051",
    "region_right_foot": "3319051",
}


def _sub(parent: ET.Element, tag: str, text: str | None = None, attrib: dict[str, str] | None = None) -> ET.Element:
    """Create an XML SubElement with optional text and attributes.

    Args:
        parent: Parent XML element.
        tag: Element tag name.
        text: Optional text content.
        attrib: Optional attribute dictionary.

    Returns:
        Newly created SubElement.
    """
    el = ET.SubElement(parent, tag, attrib=attrib or {})
    if text is not None:
        el.text = text
    return el


def _fmt_time(val: Any) -> str:
    """Convert a datetime or ISO string to NEMSIS timestamp format.

    Args:
        val: datetime object or ISO 8601 string.

    Returns:
        NEMSIS-format timestamp string or NV_NOT_RECORDED sentinel.
    """
    if not val:
        return NV_NOT_RECORDED
    try:
        if isinstance(val, str):
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        elif isinstance(val, datetime):
            dt = val
        else:
            return NV_NOT_RECORDED
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return NV_NOT_RECORDED


def _nv(val: Any) -> str:
    """Return NV_NOT_RECORDED sentinel when a value is empty or None.

    Args:
        val: Any value to coerce.

    Returns:
        String value or NV_NOT_RECORDED.
    """
    if val is None:
        return NV_NOT_RECORDED
    s = str(val).strip()
    return s if s else NV_NOT_RECORDED


def _ns(tag: str) -> str:
    """Build a fully-qualified NEMSIS namespace tag.

    Args:
        tag: Local element tag.

    Returns:
        Clark-notation namespaced tag string.
    """
    return f"{{{NEMSIS_NS}}}{tag}"


class NEMSISExporter:
    """Generates NEMSIS 3.5.1-compliant XML from chart data dictionaries.

    Accepts a chart_dict (keyed by standard field names) and agency_info dict.
    Returns raw UTF-8 XML bytes with XML declaration. All missing values are
    replaced with the appropriate NEMSIS Not-Value sentinel. No fabrication.
    """

    def export_chart(self, chart_dict: dict[str, Any], agency_info: dict[str, Any]) -> bytes:
        """Build a complete NEMSIS 3.5.1 EMSDataSet document for one chart.

        Args:
            chart_dict: Chart data keyed by field name (patient, times, vitals, etc.).
            agency_info: Agency metadata (state_code, agency_number, agency_name, etc.).

        Returns:
            UTF-8 encoded XML bytes with XML declaration.
        """
        root = ET.Element("EMSDataSet")
        root.set("xmlns", NEMSIS_NS)
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:schemaLocation", f"{NEMSIS_NS} {NEMSIS_NS}")
        root.set("nemsisVersion", NEMSIS_VERSION)
        root.set("generatedAt", datetime.now(UTC).isoformat())

        header = _sub(root, "Header")
        dem_grp = _sub(header, "DemographicGroup")
        dagency_grp = _sub(dem_grp, "dAgency.AgencyGroup")
        _sub(dagency_grp, "dAgency.01", _nv(agency_info.get("state_code")))
        _sub(dagency_grp, "dAgency.02", _nv(agency_info.get("agency_number")))
        _sub(dagency_grp, "dAgency.03", _nv(agency_info.get("agency_name")))
        _sub(dagency_grp, "dAgency.04", _nv(agency_info.get("state_code")))

        pcr = _sub(root, "PatientCareReport")
        report_number = chart_dict.get("report_number") or chart_dict.get("id") or "UNKNOWN"
        pcr.set("patientCareReportNumber", str(report_number))

        self._build_erecord(pcr, chart_dict)
        self._build_eresponse(pcr, chart_dict)
        self._build_etimes(pcr, chart_dict)
        self._build_epatient(pcr, chart_dict)
        self._build_esituation(pcr, chart_dict)
        self._build_ehistory(pcr, chart_dict)
        self._build_evitals(pcr, chart_dict)
        self._build_emedications(pcr, chart_dict)
        self._build_eprocedures(pcr, chart_dict)
        self._build_enarrative(pcr, chart_dict)
        self._build_edisposition(pcr, chart_dict)
        self._build_eincident(pcr, chart_dict)
        self._build_eexam_anatomical(pcr, chart_dict)

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        logger.info("NEMSISExporter: exported chart %s (%d bytes)", report_number, len(xml_bytes))
        return xml_bytes

    def _build_erecord(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eRecord section with software creator metadata."""
        erec = _sub(pcr, "eRecord")
        _sub(erec, "eRecord.01", _nv(c.get("pcr_number") or c.get("report_number") or c.get("id")))
        sw_grp = _sub(erec, "eRecord.SoftwareApplicationGroup")
        _sub(sw_grp, "eRecord.02", SOFTWARE_CREATOR)
        _sub(sw_grp, "eRecord.03", SOFTWARE_NAME)
        _sub(sw_grp, "eRecord.04", SOFTWARE_VERSION)

    def _build_eresponse(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eResponse section with unit and service level."""
        eresp = _sub(pcr, "eResponse")
        _sub(eresp, "eResponse.03", _nv(c.get("incident_number")))
        _sub(eresp, "eResponse.04", _nv(c.get("response_number")))
        _sub(eresp, "eResponse.05", _nv(c.get("priority")))
        _sub(eresp, "eResponse.23", _TRANSPORT_MODE_MAP.get(str(c.get("transport_mode", "")), NV_NOT_RECORDED))
        _sub(eresp, "eResponse.28", _LEVEL_OF_CARE_MAP.get(str(c.get("level_of_care", "")), NV_NOT_RECORDED))

    def _build_etimes(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eTimes section with all 8 standard timing fields."""
        etimes = _sub(pcr, "eTimes")
        _sub(etimes, "eTimes.01", _fmt_time(c.get("call_received_at")))
        _sub(etimes, "eTimes.03", _fmt_time(c.get("dispatched_at")))
        _sub(etimes, "eTimes.05", _fmt_time(c.get("en_route_at")))
        _sub(etimes, "eTimes.06", _fmt_time(c.get("on_scene_at")))
        _sub(etimes, "eTimes.07", _fmt_time(c.get("arrival_time")))
        _sub(etimes, "eTimes.09", _fmt_time(c.get("transport_at")))
        _sub(etimes, "eTimes.11", _fmt_time(c.get("cleared_at")))
        _sub(etimes, "eTimes.12", NV_NOT_RECORDED)

    def _build_epatient(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the ePatient section with demographics."""
        epat = _sub(pcr, "ePatient")
        name_grp = _sub(epat, "ePatient.PatientNameGroup")
        _sub(name_grp, "ePatient.02", _nv(c.get("patient_last_name")))
        _sub(name_grp, "ePatient.03", _nv(c.get("patient_first_name")))
        raw_gender = c.get("patient_gender") or ""
        if hasattr(raw_gender, "value"):
            raw_gender = raw_gender.value
        _sub(epat, "ePatient.13", _GENDER_MAP.get(str(raw_gender).lower(), NV_NOT_RECORDED))
        dob = c.get("patient_dob")
        if dob:
            if isinstance(dob, datetime):
                _sub(epat, "ePatient.17", dob.strftime("%Y-%m-%d"))
            else:
                _sub(epat, "ePatient.17", str(dob)[:10])
        raw_race = c.get("patient_race") or ""
        _sub(epat, "ePatient.14", _RACE_MAP.get(str(raw_race).lower(), NV_NOT_RECORDED))
        if c.get("patient_address"):
            _sub(epat, "ePatient.15", str(c["patient_address"]))
        if c.get("patient_phone"):
            _sub(epat, "ePatient.18", str(c["patient_phone"]))

    def _build_esituation(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eSituation section with complaint and dispatch information."""
        esit = _sub(pcr, "eSituation")
        _sub(esit, "eSituation.01", _fmt_time(c.get("created_at")))
        _sub(esit, "eSituation.04", _nv(c.get("dispatch_complaint")))
        _sub(esit, "eSituation.09", _nv(c.get("chief_complaint")))
        _sub(esit, "eSituation.11", _nv(c.get("chief_complaint")))

    def _build_ehistory(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eHistory section with allergies and past medical history."""
        ehist = _sub(pcr, "eHistory")
        allergies = c.get("allergies") or []
        _sub(ehist, "eHistory.01", "; ".join(allergies) if allergies else NV_NOT_RECORDED)
        history = c.get("history") or []
        _sub(ehist, "eHistory.08", "; ".join(history) if history else NV_NOT_RECORDED)

    def _build_evitals(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eVitals section with all vital measurement sets (up to 20)."""
        vitals = c.get("vitals") or []
        if not isinstance(vitals, list) or not vitals:
            return
        evit = _sub(pcr, "eVitals")
        for v in vitals[:20]:
            if not isinstance(v, dict):
                continue
            vgrp = _sub(evit, "eVitals.VitalGroup")
            _sub(vgrp, "eVitals.01", _fmt_time(v.get("time") or v.get("recorded_at")))
            _sub(vgrp, "eVitals.06", _nv(v.get("systolic_bp") or v.get("bp_sys")))
            _sub(vgrp, "eVitals.07", _nv(v.get("diastolic_bp") or v.get("bp_dia")))
            _sub(vgrp, "eVitals.10", _nv(v.get("heart_rate") or v.get("hr")))
            _sub(vgrp, "eVitals.14", _nv(v.get("respiratory_rate") or v.get("rr")))
            _sub(vgrp, "eVitals.16", _nv(v.get("spo2")))
            _sub(vgrp, "eVitals.17", _nv(v.get("etco2")))
            _sub(vgrp, "eVitals.18", _nv(v.get("glucose")))
            _sub(vgrp, "eVitals.19", _nv(v.get("gcs_total")))
            _sub(vgrp, "eVitals.20", _nv(v.get("gcs_eye")))
            _sub(vgrp, "eVitals.21", _nv(v.get("gcs_verbal")))
            _sub(vgrp, "eVitals.22", _nv(v.get("gcs_motor")))
            _sub(vgrp, "eVitals.26", _nv(v.get("temperature_c") or v.get("temp_f")))
            _sub(vgrp, "eVitals.27", _nv(v.get("pain_scale")))

    def _build_emedications(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eMedications section with each administered medication."""
        medications = c.get("medications") or []
        if not isinstance(medications, list) or not medications:
            return
        emeds = _sub(pcr, "eMedications")
        for med in medications:
            if not isinstance(med, dict):
                continue
            mg = _sub(emeds, "eMedications.MedicationGroup")
            _sub(mg, "eMedications.03", _fmt_time(med.get("time") or med.get("time_given")))
            _sub(mg, "eMedications.04", _nv(med.get("drug") or med.get("medication_name")))
            _sub(mg, "eMedications.05", _nv(med.get("dose")))
            _sub(mg, "eMedications.06", _nv(med.get("dose_unit") or med.get("unit")))
            _sub(mg, "eMedications.07", _nv(med.get("route")))
            _sub(mg, "eMedications.10", "9909003" if med.get("prior_to_our_care") else "9909001")

    def _build_eprocedures(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eProcedures section with each performed procedure."""
        procedures = c.get("procedures") or []
        if not isinstance(procedures, list) or not procedures:
            return
        eproc = _sub(pcr, "eProcedures")
        for proc in procedures:
            if not isinstance(proc, dict):
                continue
            pg = _sub(eproc, "eProcedures.ProcedureGroup")
            _sub(pg, "eProcedures.03", _fmt_time(proc.get("time") or proc.get("time_performed")))
            _sub(pg, "eProcedures.05", _nv(proc.get("procedure") or proc.get("procedure_name")))
            _sub(pg, "eProcedures.06", str(proc.get("attempts", 1)))
            _sub(pg, "eProcedures.07", "9923001" if proc.get("successful") else "9923003")
            _sub(pg, "eProcedures.08", _nv(proc.get("complications")))
            _sub(pg, "eProcedures.10", "9909003" if proc.get("prior_to_our_care") else "9909001")

    def _build_enarrative(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eNarrative section with patient care report narrative text."""
        enar = _sub(pcr, "eNarrative")
        _sub(enar, "eNarrative.01", _nv(c.get("narrative")))

    def _build_edisposition(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eDisposition section with transport and destination data."""
        edisp = _sub(pcr, "eDisposition")
        disp_grp = _sub(edisp, "eDisposition.IncidentDispositionGroup")
        _sub(disp_grp, "eDisposition.27", NV_NOT_RECORDED)
        _sub(disp_grp, "eDisposition.28", NV_NOT_RECORDED)
        if c.get("refusal"):
            _sub(edisp, "eDisposition.12", "4216009")
        else:
            _sub(edisp, "eDisposition.12", _nv(c.get("disposition_code")))
        _sub(edisp, "eDisposition.16", _nv(c.get("destination_facility")))
        _sub(edisp, "eDisposition.21", _nv(c.get("destination_facility")))

    def _build_eincident(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Build the eIncident section with incident number cross-reference."""
        einc = _sub(pcr, "eIncident")
        _sub(einc, "eIncident.01", _nv(c.get("incident_number")))

    def _build_eexam_anatomical(self, pcr: ET.Element, c: dict[str, Any]) -> None:
        """Emit eExam body-region findings and a structured custom block.

        NEMSIS 3.5.1 captures exam findings under ``eExam`` (fields
        eExam.18 — eExam.23). Each anatomical finding produces:

        - One ``eExam.ExamGroup`` containing the mapped body-region
          code (eExam.19), assessed timestamp (eExam.18), severity
          (eExam.20 or eExam.21 — left to TODO when finalized against
          the schema), and a brief text mirror of the structured shape.
        - A row in an ``AdaptixCustomElements/AnatomicalFindings``
          block carrying the FULL camelCase payload so no data is
          trapped if a code is unmapped or the consumer needs richer
          context than the eExam fields expose.
        """
        findings = c.get("anatomical_findings") or []
        if not isinstance(findings, list) or not findings:
            return

        eexam = _sub(pcr, "eExam")
        for f in findings:
            if not isinstance(f, dict):
                continue
            group = _sub(eexam, "eExam.ExamGroup")
            _sub(group, "eExam.18", _fmt_time(f.get("assessedAt")))
            region_id = str(f.get("regionId") or "")
            code = _EEXAM_BODY_REGION_MAP.get(region_id, NV_NOT_RECORDED)
            _sub(group, "eExam.19", code)
            # TODO(NEMSIS): finalize eExam.20/.21 severity binding once
            # the schematron value set is confirmed for the 3D module.
            _sub(group, "eExam.20", _nv(f.get("severity")))
            _sub(group, "eExam.21", _nv(f.get("findingType")))
            if f.get("notes"):
                _sub(group, "eExam.23", str(f["notes"]))

        # Custom-element block — never silent drops; carries the full
        # structured shape regardless of mapping completeness.
        custom = _sub(pcr, "AdaptixCustomElements")
        anatomical_block = _sub(custom, "AnatomicalFindings")
        for f in findings:
            if not isinstance(f, dict):
                continue
            row = _sub(anatomical_block, "AnatomicalFinding")
            for key in (
                "id",
                "regionId",
                "regionLabel",
                "bodyView",
                "findingType",
                "severity",
                "laterality",
                "painScale",
                "burnTbsaPercent",
                "pertinentNegative",
                "notes",
                "assessedAt",
                "assessedBy",
            ):
                val = f.get(key)
                if val is None:
                    continue
                _sub(row, key, str(val))
            cms = f.get("cms") or {}
            if isinstance(cms, dict) and any(v is not None for v in cms.values()):
                cms_el = _sub(row, "cms")
                for ck in ("pulse", "motor", "sensation", "capillaryRefill"):
                    if cms.get(ck) is not None:
                        _sub(cms_el, ck, str(cms[ck]))
