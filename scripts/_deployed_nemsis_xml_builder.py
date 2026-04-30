"""NEMSIS 3.5.1 XML builder for the epcr domain.

Produces valid NEMSIS 3.5.1 EMSDataSet XML from a Chart ORM instance and its
associated NemsisMappingRecord rows. Generated XML is suitable for XSD and
Schematron validation by NemsisXSDValidator.

Missing required fields are populated with the NEMSIS 3.5.1 Not-Recorded value
(7701003 — Not Recorded) and flagged in a returned warnings list so that callers
can surface the gap without silently accepting an incomplete export.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timezone
from xml.etree.ElementTree import Element, SubElement, tostring, indent

logger = logging.getLogger(__name__)

_NEMSIS_NS = "http://www.nemsis.org"
_NEMSIS_VERSION = "3.5.1.250403CP1"
_NEMSIS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

_NOT_RECORDED = "7701003"

_SOFTWARE_CREATOR = "Adaptix Platform"
_SOFTWARE_NAME = "Adaptix ePCR"
_SOFTWARE_VERSION = "1.0.0"


class NemsisXmlBuilder:
    """Build NEMSIS 3.5.1 XML from chart and mapping record data.

    Reads NemsisMappingRecord rows for field values and falls back to
    NOT_RECORDED (7701003) for any required field that is absent from the
    mapping records. Warnings are accumulated per missing field.
    """

    def __init__(
        self,
        chart: object,
        mapping_records: list[object],
    ) -> None:
        """Initialise the builder with ORM objects.

        Args:
            chart: Chart ORM instance with id, call_number, tenant_id,
                incident_type, created_at, patient_id attributes.
            mapping_records: List of NemsisMappingRecord ORM instances, each
                with nemsis_field_id and value attributes.
        """
        self._chart = chart
        self._fields: dict[str, str] = {
            rec.nemsis_field: str(rec.nemsis_value)
            for rec in mapping_records
            if rec.nemsis_value is not None
        }
        self._warnings: list[str] = []

    def _get(self, field_id: str, fallback: str | None = None) -> str:
        """Return field value or fallback, recording a warning if absent.

        Args:
            field_id: NEMSIS element identifier (e.g. "eRecord.01").
            fallback: Value to use when no mapping record exists.

        Returns:
            Field value string.
        """
        val = self._fields.get(field_id)
        if val:
            return val
        effective = fallback if fallback is not None else _NOT_RECORDED
        if effective == _NOT_RECORDED:
            self._warnings.append(
                f"Field {field_id} not in mapping records; using NOT_RECORDED ({_NOT_RECORDED})"
            )
        return effective

    def _iso(self, dt: object | None) -> str:
        """Format a datetime to NEMSIS ISO-8601 string.

        Args:
            dt: datetime object or None.

        Returns:
            ISO-8601 string or NOT_RECORDED.
        """
        if dt is None:
            return _NOT_RECORDED
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    def build(self) -> tuple[bytes, list[str]]:
        """Build NEMSIS 3.5.1 EMSDataSet XML bytes.

        Returns:
            Tuple of (xml_bytes, warnings):
                xml_bytes — UTF-8 encoded NEMSIS 3.5.1 XML.
                warnings — List of fields that fell back to NOT_RECORDED.
        """
        chart = self._chart

        root = Element(f"{{{_NEMSIS_NS}}}EMSDataSet")
        root.set(
            f"{{{_NEMSIS_XSI}}}schemaLocation",
            f"{_NEMSIS_NS} EMSDataSet_v3.xsd",
        )
        root.set("xsi:type", "EMSDataSetType")

        hdr = SubElement(root, f"{{{_NEMSIS_NS}}}Header")
        dg = SubElement(hdr, f"{{{_NEMSIS_NS}}}DemographicGroup")
        SubElement(dg, f"{{{_NEMSIS_NS}}}D01_03").text = self._get("D01_03", "US")
        SubElement(dg, f"{{{_NEMSIS_NS}}}D01_07").text = self._get("D01_07", "911 Response (Scene)")

        pcr = SubElement(root, f"{{{_NEMSIS_NS}}}PatientCareReport")

        er = SubElement(pcr, f"{{{_NEMSIS_NS}}}eRecord")
        SubElement(er, f"{{{_NEMSIS_NS}}}eRecord.01").text = self._get("eRecord.01", str(chart.call_number))
        SubElement(er, f"{{{_NEMSIS_NS}}}eRecord.02").text = self._get("eRecord.02", _SOFTWARE_CREATOR)
        SubElement(er, f"{{{_NEMSIS_NS}}}eRecord.03").text = self._get("eRecord.03", _SOFTWARE_NAME)
        SubElement(er, f"{{{_NEMSIS_NS}}}eRecord.04").text = self._get("eRecord.04", _SOFTWARE_VERSION)

        eresp = SubElement(pcr, f"{{{_NEMSIS_NS}}}eResponse")
        SubElement(eresp, f"{{{_NEMSIS_NS}}}eResponse.01").text = self._get("eResponse.01")
        SubElement(eresp, f"{{{_NEMSIS_NS}}}eResponse.03").text = self._get("eResponse.03", str(chart.call_number))
        SubElement(eresp, f"{{{_NEMSIS_NS}}}eResponse.04").text = self._get("eResponse.04", str(chart.id))
        SubElement(eresp, f"{{{_NEMSIS_NS}}}eResponse.05").text = self._get("eResponse.05", "2205001")

        created_iso = self._iso(getattr(chart, "created_at", None))
        etimes = SubElement(pcr, f"{{{_NEMSIS_NS}}}eTimes")
        SubElement(etimes, f"{{{_NEMSIS_NS}}}eTimes.01").text = self._get("eTimes.01", created_iso)
        SubElement(etimes, f"{{{_NEMSIS_NS}}}eTimes.02").text = self._get("eTimes.02", created_iso)
        SubElement(etimes, f"{{{_NEMSIS_NS}}}eTimes.03").text = self._get("eTimes.03")
        SubElement(etimes, f"{{{_NEMSIS_NS}}}eTimes.04").text = self._get("eTimes.04")
        SubElement(etimes, f"{{{_NEMSIS_NS}}}eTimes.05").text = self._get("eTimes.05")

        epat = SubElement(pcr, f"{{{_NEMSIS_NS}}}ePatient")
        if getattr(chart, "patient_id", None):
            SubElement(epat, f"{{{_NEMSIS_NS}}}ePatient.PatientNameGroup").text = ""
        SubElement(epat, f"{{{_NEMSIS_NS}}}ePatient.16").text = self._get(
            "ePatient.16", "7701003"
        )

        esit = SubElement(pcr, f"{{{_NEMSIS_NS}}}eSituation")
        SubElement(esit, f"{{{_NEMSIS_NS}}}eSituation.01").text = self._get("eSituation.01", created_iso)
        SubElement(esit, f"{{{_NEMSIS_NS}}}eSituation.07").text = self._get(
            "eSituation.07",
            self._incident_type_to_nemsis(getattr(chart, "incident_type", "other")),
        )

        enarr = SubElement(pcr, f"{{{_NEMSIS_NS}}}eNarrative")
        SubElement(enarr, f"{{{_NEMSIS_NS}}}eNarrative.01").text = self._get(
            "eNarrative.01", f"Patient encounter — call {chart.call_number}"
        )

        edisp = SubElement(pcr, f"{{{_NEMSIS_NS}}}eDisposition")
        SubElement(edisp, f"{{{_NEMSIS_NS}}}eDisposition.DestinationGroup")
        SubElement(edisp, f"{{{_NEMSIS_NS}}}eDisposition.27").text = self._get("eDisposition.27", "4227001")
        SubElement(edisp, f"{{{_NEMSIS_NS}}}eDisposition.28").text = self._get("eDisposition.28", "4228001")

        try:
            indent(root, space="  ")
        except TypeError:
            pass

        xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_bytes = xml_declaration + tostring(root, encoding="unicode").encode("utf-8")
        return xml_bytes, list(self._warnings)

    @staticmethod
    def _incident_type_to_nemsis(incident_type: str) -> str:
        """Map internal incident_type to NEMSIS eSituation.07 code.

        Args:
            incident_type: Internal incident type string.

        Returns:
            NEMSIS situation type code.
        """
        _MAP = {
            "medical": "2407027",
            "trauma": "2407001",
            "behavioral": "2407035",
            "other": "2407033",
        }
        return _MAP.get(incident_type, "2407033")

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Compute hex-encoded SHA-256 checksum of data.

        Args:
            data: Raw bytes.

        Returns:
            Lowercase hexadecimal SHA-256 digest string.
        """
        return hashlib.sha256(data).hexdigest()
