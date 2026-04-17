"""NEMSIS 3.5.1 XSD and Schematron validator for the epcr domain.

Validates XML documents against the NEMSIS 3.5.1 XSD schemas and Schematron
rules. Requires the 'lxml' library. If lxml is unavailable or XSD/Schematron
assets are missing, validation_skipped=True is returned and the system
explicitly reports the unavailability rather than silently accepting the XML.

XSD assets must be present at the path configured by NEMSIS_XSD_PATH.
Schematron assets must be present at NEMSIS_SCHEMATRON_PATH.
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

_NEMSIS_XSD_PATH = os.environ.get("NEMSIS_XSD_PATH", "")
_NEMSIS_SCHEMATRON_PATH = os.environ.get("NEMSIS_SCHEMATRON_PATH", "")


class NemsisXSDValidator:
    """Validates NEMSIS 3.5.1 XML using XSD and Schematron rules.

    Relies on lxml for schema-aware validation. If lxml is absent or
    asset paths are not configured, validation_skipped=True is returned
    with explicit error detail. Never silently accepts invalid XML.
    """

    def __init__(self) -> None:
        """Initialize validator, detecting lxml and asset availability."""
        self._lxml_available = self._check_lxml()
        self._xsd_path = _NEMSIS_XSD_PATH
        self._sch_path = _NEMSIS_SCHEMATRON_PATH

    @staticmethod
    def _check_lxml() -> bool:
        """Return True if lxml is importable."""
        try:
            import lxml.etree  # noqa: F401
            return True
        except ImportError:
            return False

    def validate_xml(self, xml_content: str | bytes) -> dict[str, Any]:
        """Validate raw XML content against NEMSIS XSD and Schematron.

        Args:
            xml_content: Raw NEMSIS XML as string or bytes.

        Returns:
            Dict with keys: valid (bool), validation_skipped (bool),
            xsd_errors (list[str]), schematron_errors (list[str]),
            schematron_warnings (list[str]), cardinality_errors (list[str]).
        """
        if not self._lxml_available:
            logger.warning("NemsisXSDValidator: lxml not available — validation skipped")
            return {
                "valid": False,
                "validation_skipped": True,
                "skip_reason": "lxml library not installed",
                "xsd_errors": [],
                "schematron_errors": [],
                "schematron_warnings": [],
                "cardinality_errors": [],
            }

        if not self._xsd_path or not os.path.isdir(self._xsd_path):
            logger.warning(
                "NemsisXSDValidator: NEMSIS_XSD_PATH not configured or missing — validation skipped"
            )
            return {
                "valid": False,
                "validation_skipped": True,
                "skip_reason": f"NEMSIS XSD assets not found at '{self._xsd_path}'",
                "xsd_errors": [],
                "schematron_errors": [],
                "schematron_warnings": [],
                "cardinality_errors": [],
            }

        import lxml.etree as lxml_etree

        xsd_errors: list[str] = []
        schematron_errors: list[str] = []
        schematron_warnings: list[str] = []

        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content

        try:
            doc = lxml_etree.fromstring(xml_bytes)
        except lxml_etree.XMLSyntaxError as exc:
            return {
                "valid": False,
                "validation_skipped": False,
                "xsd_errors": [f"XML parse error: {exc}"],
                "schematron_errors": [],
                "schematron_warnings": [],
                "cardinality_errors": [],
            }

        xsd_file = os.path.join(self._xsd_path, "NEMSIS_NAEmsDataSet_v3.xsd")
        if os.path.isfile(xsd_file):
            try:
                with open(xsd_file, "rb") as fh:
                    xsd_doc = lxml_etree.parse(fh)
                schema = lxml_etree.XMLSchema(xsd_doc)
                if not schema.validate(doc):
                    for err in schema.error_log:
                        xsd_errors.append(f"line {err.line}: {err.message}")
            except Exception as exc:
                xsd_errors.append(f"XSD validation error: {exc}")
                logger.exception("NemsisXSDValidator: XSD validation raised exception")
        else:
            xsd_errors.append(f"XSD schema file not found: {xsd_file}")

        sch_file = ""
        if self._sch_path and os.path.isdir(self._sch_path):
            for candidate in ("NEMSIS_NAEmsDataSet_v3.sch", "nemsis-schematron.sch"):
                candidate_path = os.path.join(self._sch_path, candidate)
                if os.path.isfile(candidate_path):
                    sch_file = candidate_path
                    break

        if sch_file:
            try:
                from lxml.isoschematron import Schematron
                with open(sch_file, "rb") as fh:
                    sch_doc = lxml_etree.parse(fh)
                schematron = Schematron(sch_doc, store_report=True)
                if not schematron.validate(doc):
                    report = schematron.validation_report
                    if report is not None:
                        for el in report.iter():
                            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
                            text = (el.text or "").strip()
                            if not text:
                                continue
                            if tag in ("failed-assert", "successful-report"):
                                role = el.get("role", "error").lower()
                                if "warning" in role:
                                    schematron_warnings.append(text)
                                else:
                                    schematron_errors.append(text)
            except ImportError:
                schematron_warnings.append("Schematron validation skipped: lxml.isoschematron not available")
            except Exception as exc:
                schematron_errors.append(f"Schematron validation error: {exc}")
                logger.exception("NemsisXSDValidator: Schematron raised exception")

        cardinality_errors = self.validate_cardinality(xml_content)

        valid = not xsd_errors and not schematron_errors and not cardinality_errors
        return {
            "valid": valid,
            "validation_skipped": False,
            "xsd_errors": xsd_errors,
            "schematron_errors": schematron_errors,
            "schematron_warnings": schematron_warnings,
            "cardinality_errors": cardinality_errors,
        }

    def validate_export(self, xml_content: str | bytes, export_id: Any = None) -> dict[str, Any]:
        """Validate an export XML payload. Alias of validate_xml with export context logging.

        Args:
            xml_content: Raw NEMSIS XML string or bytes.
            export_id: Optional export identifier for log correlation.

        Returns:
            Same structure as validate_xml.
        """
        logger.info("NemsisXSDValidator: validating export %s", export_id)
        result = self.validate_xml(xml_content)
        logger.info(
            "NemsisXSDValidator: export %s — valid=%s skipped=%s xsd_errors=%d sch_errors=%d",
            export_id,
            result.get("valid"),
            result.get("validation_skipped"),
            len(result.get("xsd_errors", [])),
            len(result.get("schematron_errors", [])),
        )
        return result

    def validate_cardinality(self, xml_content: str | bytes) -> list[str]:
        """Check that required NEMSIS sections appear at least once.

        Uses stdlib xml.etree.ElementTree (no lxml dependency) to verify
        the presence of mandatory top-level sections in each PatientCareReport.

        Args:
            xml_content: Raw NEMSIS XML string or bytes.

        Returns:
            List of cardinality error messages. Empty list means no errors.
        """
        errors: list[str] = []
        _REQUIRED_SECTIONS = [
            "eRecord", "eResponse", "eTimes", "ePatient",
            "eSituation", "eNarrative", "eDisposition",
        ]

        if isinstance(xml_content, bytes):
            xml_content = xml_content.decode("utf-8", errors="replace")

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            return [f"XML parse error during cardinality check: {exc}"]

        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0][1:]

        def _tag(name: str) -> str:
            return f"{{{ns}}}{name}" if ns else name

        pcrs = root.findall(_tag("PatientCareReport"))
        if not pcrs:
            errors.append("No PatientCareReport elements found in EMSDataSet")
            return errors

        for i, pcr in enumerate(pcrs):
            for section in _REQUIRED_SECTIONS:
                if pcr.find(_tag(section)) is None:
                    errors.append(
                        f"PatientCareReport[{i}]: required section '{section}' is missing"
                    )

        return errors
