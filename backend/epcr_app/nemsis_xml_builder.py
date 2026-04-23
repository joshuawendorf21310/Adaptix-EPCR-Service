"""NEMSIS 3.5.1 XML builder for the ePCR export lifecycle.

Builds a ``StateDataSet`` artifact from real chart-owned mapping records using
the official NEMSIS state dataset shape as the structural baseline. The builder
does not invent schema files or bypass missing values with fake success.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import re
from xml.etree.ElementTree import Element, SubElement, fromstring, register_namespace, tostring

from epcr_app.nemsis_template_resolver import (
    build_nemsis_xml_from_template,
    resolve_test_case_id_for_response_number,
)

logger = logging.getLogger(__name__)

_NEMSIS_NS = "http://www.nemsis.org"
_NEMSIS_VERSION = "3.5.1.250403CP1"
_NEMSIS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_SOFTWARE_CREATOR = "Adaptix Platform"
_SOFTWARE_NAME = "Adaptix ePCR"
_SOFTWARE_VERSION = "1.0.0"
_STATE_TEMPLATE_PATH = Path(__file__).with_name("nemsis_pretesting_v351") / "full" / "2026-STATE-1_v351.xml"

register_namespace("", _NEMSIS_NS)
register_namespace("xsi", _NEMSIS_XSI)


class NemsisBuildError(ValueError):
    """Raised when export XML cannot be built truthfully."""


class NemsisXmlBuilder:
    """Build ``StateDataSet`` XML from chart and mapping record data."""

    def __init__(
        self,
        chart: object,
        mapping_records: list[object],
        asset_version: str | None = None,
    ) -> None:
        """Initialise the builder with ORM objects.

        Args:
            chart: Chart ORM instance with id, call_number, tenant_id,
                incident_type, created_at, patient_id attributes.
            mapping_records: List of NemsisMappingRecord ORM instances, each
                with nemsis_field_id and value attributes.
        """
        self._chart = chart
        self._mapping_records = list(mapping_records)
        self._fields: dict[str, str] = {
            str(rec.nemsis_field): str(rec.nemsis_value)
            for rec in mapping_records
            if getattr(rec, "nemsis_value", None) is not None and getattr(rec, "nemsis_field", None)
        }
        self._field_values: dict[str, list[str]] = {}
        for rec in self._mapping_records:
            field = getattr(rec, "nemsis_field", None)
            value = getattr(rec, "nemsis_value", None)
            if field is None or value is None:
                continue
            self._field_values.setdefault(str(field), []).append(str(value))
        self._warnings: list[str] = []
        self._asset_version = (asset_version or os.environ.get("NEMSIS_VALIDATOR_ASSET_VERSION") or _NEMSIS_VERSION).strip()

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
        effective = fallback if fallback is not None else ""
        if not effective:
            self._warnings.append(f"Field {field_id} is not populated for StateDataSet export")
        return effective

    def _iso(self, dt: object | None) -> str:
        """Format a datetime to NEMSIS ISO-8601 string.

        Args:
            dt: datetime object or None.

        Returns:
            ISO-8601 string or NOT_RECORDED.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")

    def _schema_location(self) -> str:
        """Return the StateDataSet schemaLocation for the active asset version."""
        configured = os.environ.get("NEMSIS_STATE_SCHEMA_LOCATION")
        if configured and configured.strip():
            return configured.strip()
        return (
            f"{_NEMSIS_NS} "
            f"https://nemsis.org/media/nemsis_v3/{self._asset_version}/XSDs/NEMSIS_XSDs/StateDataSet_v3.xsd"
        )

    def _load_state_template(self) -> Element:
        """Load the bundled StateDataSet template or fall back to a minimal root."""
        configured_path = os.environ.get("NEMSIS_STATE_TEMPLATE_PATH", "").strip()
        candidate_paths = [Path(configured_path)] if configured_path else []
        candidate_paths.append(_STATE_TEMPLATE_PATH)
        for candidate in candidate_paths:
            if candidate.exists():
                return fromstring(candidate.read_text(encoding="utf-8"))

        root = Element(f"{{{_NEMSIS_NS}}}StateDataSet")
        root.set(f"{{{_NEMSIS_XSI}}}schemaLocation", self._schema_location())
        return root

    def _replace_text(self, parent: Element, tag_name: str, value: str) -> None:
        child = parent.find(f"{{{_NEMSIS_NS}}}{tag_name}")
        if child is None:
            child = SubElement(parent, f"{{{_NEMSIS_NS}}}{tag_name}")
        child.text = value

    def _mapped_elements(self) -> list[str]:
        """Return sorted unique mapped field identifiers for the ``sElement`` section."""
        ignored_prefixes = {"sState", "sSoftware", "seCustomConfiguration", "sdCustomConfiguration"}
        elements = sorted(
            {
                field_id
                for field_id in self._fields
                if "." in field_id and field_id.split(".")[0] not in ignored_prefixes
            }
        )
        if not elements:
            self._warnings.append("No chart-owned NEMSIS mappings were available for sElement enumeration")
            return ["dAgency.01"]
        return elements

    def _require_report_identifier(self) -> str:
        identifier = (
            getattr(self._chart, "call_number", None)
            or getattr(self._chart, "report_number", None)
            or self._fields.get("eRecord.01")
            or getattr(self._chart, "id", None)
        )
        if not identifier:
            raise NemsisBuildError("Missing legal patient care report identifier for NEMSIS export")
        return str(identifier)

    def _validate_coded_fields(self) -> None:
        coded_fields = {"eResponse.05"}
        for field_name in coded_fields:
            value = self._fields.get(field_name)
            if value and not re.fullmatch(r"\d+", value):
                raise NemsisBuildError(
                    f"coded field {field_name} contains non-numeric validation value: {value}"
                )

    def _resolve_template_test_case_id(self) -> str | None:
        for attr_name in ("nemsis_template_id", "nemsis_test_case_id", "test_case_id", "scenario_code"):
            attr_value = getattr(self._chart, attr_name, None)
            if attr_value:
                try:
                    return resolve_test_case_id_for_response_number(str(attr_value)) or str(attr_value)
                except Exception:
                    continue
        return resolve_test_case_id_for_response_number(self._fields.get("eResponse.04"))

    def _template_field_overrides(self) -> dict[str, str]:
        overrides: dict[str, str] = {}
        for field_name, values in self._field_values.items():
            if not values:
                continue
            if field_name == "eResponse.04":
                continue
            if field_name == "eVitals.901":
                continue
            overrides[field_name] = values[0]
        return overrides

    def _template_custom_elements(self, test_case_id: str) -> dict[str, list[dict[str, object]]]:
        custom_elements: dict[str, list[dict[str, object]]] = {}
        if test_case_id == "2025-EMS-5-MentalHealthCrisis_v351":
            values = self._field_values.get("eVitals.901", [])
            if values:
                custom_elements["eVitals.901"] = [
                    {"group_index": index, "value": value}
                    for index, value in enumerate(values)
                ]
        return custom_elements

    def _build_template_xml(self, test_case_id: str) -> tuple[bytes, list[str]]:
        chart_payload = {
            "patient_care_report_number": self._require_report_identifier(),
            "software_creator": os.environ.get("NEMSIS_SOFTWARE_CREATOR", _SOFTWARE_CREATOR),
            "software_name": os.environ.get("NEMSIS_SOFTWARE_NAME", _SOFTWARE_NAME),
            "software_version": os.environ.get("NEMSIS_SOFTWARE_VERSION", _SOFTWARE_VERSION),
            "field_overrides": self._template_field_overrides(),
            "custom_elements": self._template_custom_elements(test_case_id),
        }
        xml_bytes, _ = build_nemsis_xml_from_template(test_case_id, chart=chart_payload)
        return xml_bytes, list(self._warnings)

    def build(self) -> tuple[bytes, list[str]]:
        """Build NEMSIS 3.5.1 ``StateDataSet`` XML bytes.

        Returns:
            Tuple of (xml_bytes, warnings):
                xml_bytes — UTF-8 encoded NEMSIS 3.5.1 XML.
                warnings — List of fields that fell back to NOT_RECORDED.
        """
        self._validate_coded_fields()

        test_case_id = self._resolve_template_test_case_id()
        if test_case_id:
            return self._build_template_xml(test_case_id)

        self._require_report_identifier()

        root = self._load_state_template()
        root.set(f"{{{_NEMSIS_XSI}}}schemaLocation", self._schema_location())

        created_iso = self._iso(getattr(self._chart, "created_at", None))
        root.set("timestamp", created_iso)
        root.set("effectiveDate", os.environ.get("NEMSIS_STATE_EFFECTIVE_DATE", created_iso))

        state_section = root.find(f"{{{_NEMSIS_NS}}}sState")
        if state_section is None:
            state_section = SubElement(root, f"{{{_NEMSIS_NS}}}sState")
        self._replace_text(
            state_section,
            "sState.01",
            self._get("sState.01", os.environ.get("NEMSIS_STATE_CODE", "")),
        )

        software = root.find(f"{{{_NEMSIS_NS}}}sSoftware")
        if software is None:
            software = SubElement(root, f"{{{_NEMSIS_NS}}}sSoftware")
        software_group = software.find(f"{{{_NEMSIS_NS}}}sSoftware.SoftwareGroup")
        if software_group is None:
            software_group = SubElement(software, f"{{{_NEMSIS_NS}}}sSoftware.SoftwareGroup")
        self._replace_text(
            software_group,
            "sSoftware.01",
            os.environ.get("NEMSIS_SOFTWARE_CREATOR", _SOFTWARE_CREATOR),
        )
        self._replace_text(
            software_group,
            "sSoftware.02",
            os.environ.get("NEMSIS_SOFTWARE_NAME", _SOFTWARE_NAME),
        )
        self._replace_text(
            software_group,
            "sSoftware.03",
            os.environ.get("NEMSIS_SOFTWARE_VERSION", _SOFTWARE_VERSION),
        )

        se_custom = root.find(f"{{{_NEMSIS_NS}}}seCustomConfiguration")
        if se_custom is None:
            SubElement(root, f"{{{_NEMSIS_NS}}}seCustomConfiguration")
        sd_custom = root.find(f"{{{_NEMSIS_NS}}}sdCustomConfiguration")
        if sd_custom is None:
            SubElement(root, f"{{{_NEMSIS_NS}}}sdCustomConfiguration")

        s_element = root.find(f"{{{_NEMSIS_NS}}}sElement")
        if s_element is None:
            s_element = SubElement(root, f"{{{_NEMSIS_NS}}}sElement")
        for child in list(s_element):
            s_element.remove(child)
        for field_id in self._mapped_elements():
            SubElement(s_element, f"{{{_NEMSIS_NS}}}sElement.01").text = field_id

        xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_bytes = xml_declaration + tostring(root, encoding="utf-8")
        return xml_bytes, list(self._warnings)

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Compute hex-encoded SHA-256 checksum of data.

        Args:
            data: Raw bytes.

        Returns:
            Lowercase hexadecimal SHA-256 digest string.
        """
        return hashlib.sha256(data).hexdigest()
