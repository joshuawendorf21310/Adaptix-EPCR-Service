"""NEMSIS 3.5.1 XSD and Schematron validator for the ePCR export lifecycle.

Validation is deterministic: missing assets or missing libraries are reported as
hard validation failures, not as skipped checks.
"""
from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NemsisXSDValidator:
    """Validates NEMSIS 3.5.1 XML using XSD and Schematron rules.

    Relies on lxml for XSD validation and uses Saxon/CHE for official
    XSLT 2.0 Schematron when required by the published NEMSIS rules.
    Missing processors or assets are reported as hard validation failures.
    """

    def __init__(self) -> None:
        """Initialize validator, detecting lxml and asset availability."""
        self._lxml_available = self._check_lxml()
        self._saxon_available = self._check_saxonche()
        self._xsd_path = os.environ.get("NEMSIS_XSD_PATH", "")
        self._sch_path = os.environ.get("NEMSIS_SCHEMATRON_PATH", "")
        self.asset_version = os.environ.get("NEMSIS_VALIDATOR_ASSET_VERSION", "").strip() or None
        self._xsd_tempdir: tempfile.TemporaryDirectory[str] | None = None

    @staticmethod
    def _check_lxml() -> bool:
        """Return True if lxml is importable."""
        try:
            import lxml.etree  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_saxonche() -> bool:
        """Return True if saxonche is importable for XSLT 2.0 schematron."""
        try:
            import saxonche  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _result(
        *,
        valid: bool,
        xsd_valid: bool,
        schematron_valid: bool,
        xsd_errors: list[str] | None = None,
        schematron_errors: list[str] | None = None,
        schematron_warnings: list[str] | None = None,
        asset_version: str | None = None,
    ) -> dict[str, Any]:
        xsd_errors = xsd_errors or []
        schematron_errors = schematron_errors or []
        schematron_warnings = schematron_warnings or []
        return {
            "valid": valid,
            "validation_skipped": False,
            "xsd_valid": xsd_valid,
            "schematron_valid": schematron_valid,
            "xsd_errors": xsd_errors,
            "schematron_errors": schematron_errors,
            "schematron_warnings": schematron_warnings,
            "cardinality_errors": [],
            "errors": [*xsd_errors, *schematron_errors],
            "warnings": list(schematron_warnings),
            "validator_asset_version": asset_version,
        }

    @staticmethod
    def _find_asset(base_path: str, candidates: tuple[str, ...]) -> str | None:
        for root, _, files in os.walk(base_path):
            names = set(files)
            for candidate in candidates:
                if candidate in names:
                    return os.path.join(root, candidate)
        return None

    def _resolve_xsd_search_root(self) -> str | None:
        """Return a filesystem directory containing XSD assets.

        Supports either an extracted directory or the official ``NEMSIS_XSDs.zip``
        bundle path. ZIP bundles are extracted once per validator instance into a
        temporary directory so downstream validation can keep using normal file
        resolution for schema includes/imports.
        """
        if not self._xsd_path:
            return None
        if os.path.isdir(self._xsd_path):
            return self._xsd_path
        if os.path.isfile(self._xsd_path) and zipfile.is_zipfile(self._xsd_path):
            if self._xsd_tempdir is None:
                self._xsd_tempdir = tempfile.TemporaryDirectory(prefix="adaptix-nemsis-xsd-")
                with zipfile.ZipFile(self._xsd_path) as archive:
                    archive.extractall(self._xsd_tempdir.name)
            return self._xsd_tempdir.name
        return None

    @staticmethod
    def _extract_schematron_messages(report_root: Any) -> tuple[list[str], list[str]]:
        """Extract error and warning messages from an SVRL report tree."""
        errors: list[str] = []
        warnings: list[str] = []
        for el in report_root.iter():
            if not isinstance(getattr(el, "tag", None), str):
                continue
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            text = " ".join(chunk.strip() for chunk in el.itertext() if chunk and chunk.strip())
            if not text:
                continue
            if tag in ("failed-assert", "successful-report"):
                role = str(el.get("role", "error")).lower()
                if "warning" in role:
                    warnings.append(text)
                else:
                    errors.append(text)
        return errors, warnings

    @staticmethod
    def run_schematron_validation(xml_bytes: bytes, sch_file: str, search_root: str) -> tuple[list[str], list[str]]:
        """Run official Schematron validation, supporting XSLT 2.0 via Saxon/CHE."""
        import lxml.etree as lxml_etree

        with open(sch_file, "rb") as fh:
            sch_doc = lxml_etree.parse(fh)
        query_binding = str(sch_doc.getroot().get("queryBinding", "")).strip().lower()

        if "xslt2" not in query_binding:
            from lxml.isoschematron import Schematron

            schematron = Schematron(sch_doc, store_report=True)
            document = lxml_etree.fromstring(xml_bytes)
            if schematron.validate(document):
                return [], []
            report = schematron.validation_report
            if report is None:
                return ["Schematron validation failed without an SVRL report"], []
            return NemsisXSDValidator._extract_schematron_messages(report)

        try:
            from saxonche import PySaxonProcessor
        except ImportError:
            return [
                "Schematron validation error: saxonche is required for official XSLT 2.0 Schematron execution"
            ], []

        include_xsl = NemsisXSDValidator._find_asset(search_root, ("iso_dsdl_include.xsl",))
        abstract_xsl = NemsisXSDValidator._find_asset(search_root, ("iso_abstract_expand.xsl",))
        svrl_xsl = NemsisXSDValidator._find_asset(search_root, ("iso_svrl_for_xslt2.xsl",))
        missing_assets = [
            name
            for name, path in (
                ("iso_dsdl_include.xsl", include_xsl),
                ("iso_abstract_expand.xsl", abstract_xsl),
                ("iso_svrl_for_xslt2.xsl", svrl_xsl),
            )
            if not path
        ]
        if missing_assets:
            return [
                "Schematron validation error: official XSLT 2.0 utility files are missing: "
                + ", ".join(missing_assets)
            ], []

        try:
            with tempfile.TemporaryDirectory(prefix="adaptix-schematron-") as tmp_dir:
                tmp_path = Path(tmp_dir)
                stage1_path = tmp_path / "stage1.sch"
                stage2_path = tmp_path / "stage2.sch"
                compiled_xsl_path = tmp_path / "compiled.xsl"
                xml_path = tmp_path / "document.xml"
                xml_path.write_bytes(xml_bytes)

                with PySaxonProcessor(license=False) as processor:
                    xslt30 = processor.new_xslt30_processor()

                    stage1_exec = xslt30.compile_stylesheet(stylesheet_file=str(include_xsl))
                    stage1_output = stage1_exec.transform_to_string(source_file=str(sch_file))
                    stage1_path.write_text(stage1_output or "", encoding="utf-8")

                    stage2_exec = xslt30.compile_stylesheet(stylesheet_file=str(abstract_xsl))
                    stage2_output = stage2_exec.transform_to_string(source_file=str(stage1_path))
                    stage2_path.write_text(stage2_output or "", encoding="utf-8")

                    compile_exec = xslt30.compile_stylesheet(stylesheet_file=str(svrl_xsl))
                    compile_exec.set_parameter("allow-foreign", processor.make_string_value("true"))
                    compiled_xsl = compile_exec.transform_to_string(source_file=str(stage2_path))
                    compiled_xsl_path.write_text(compiled_xsl or "", encoding="utf-8")

                    validate_exec = xslt30.compile_stylesheet(stylesheet_file=str(compiled_xsl_path))
                    svrl_report = validate_exec.transform_to_string(source_file=str(xml_path))

                if not svrl_report:
                    return ["Schematron validation error: generated no SVRL output"], []
                report_root = lxml_etree.fromstring(svrl_report.encode("utf-8"))
                return NemsisXSDValidator._extract_schematron_messages(report_root)
        except Exception as exc:
            logger.exception("NemsisXSDValidator: XSLT 2.0 Schematron raised exception")
            return [f"Schematron validation error: {exc}"], []

    def _resolve_xsd_path(self, dataset_name: str, search_root: str) -> str | None:
        candidates = {
            "StateDataSet": ("StateDataSet_v3.xsd",),
            "EMSDataSet": ("NEMSIS_XSDs/NEMSIS_NAEmsDataSet_v3.xsd", "NEMSIS_NAEmsDataSet_v3.xsd", "EMSDataSet_v3.xsd"),
            "DEMDataSet": ("DEMDataSet_v3.xsd",),
        }.get(dataset_name, tuple())
        normalized = tuple(os.path.basename(candidate) for candidate in candidates)
        return self._find_asset(search_root, normalized)

    def get_xsd_asset_path(self, dataset_name: str) -> str | None:
        """Return the resolved XSD file path for a given dataset name."""
        search_root = self._resolve_xsd_search_root()
        if not search_root:
            return None
        return self._resolve_xsd_path(dataset_name, search_root)

    def _resolve_schematron_path(self, dataset_name: str) -> str | None:
        candidates = {
            "StateDataSet": ("StateDataSet.sch", "StateDataSet_v3.sch"),
            "EMSDataSet": ("EMSDataSet.sch", "NEMSIS_NAEmsDataSet_v3.sch", "nemsis-schematron.sch"),
            "DEMDataSet": ("DEMDataSet.sch",),
        }.get(dataset_name, tuple())
        return self._find_asset(self._sch_path, candidates)

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
            logger.warning("NemsisXSDValidator: lxml not available")
            return self._result(
                valid=False,
                xsd_valid=False,
                schematron_valid=False,
                xsd_errors=["lxml library not installed; official NEMSIS validation cannot run"],
                asset_version=self.asset_version,
            )

        xsd_search_root = self._resolve_xsd_search_root()
        if not xsd_search_root:
            logger.warning("NemsisXSDValidator: NEMSIS_XSD_PATH not configured or missing")
            return self._result(
                valid=False,
                xsd_valid=False,
                schematron_valid=False,
                xsd_errors=[
                    f"Official NEMSIS XSD assets not found at '{self._xsd_path}'. "
                    "Provide either an extracted directory or the official NEMSIS_XSDs.zip bundle."
                ],
                asset_version=self.asset_version,
            )

        if not self._sch_path or not os.path.isdir(self._sch_path):
            logger.warning("NemsisXSDValidator: NEMSIS_SCHEMATRON_PATH not configured or missing")
            return self._result(
                valid=False,
                xsd_valid=False,
                schematron_valid=False,
                xsd_errors=[f"Official NEMSIS Schematron assets not found at '{self._sch_path}'"],
                asset_version=self.asset_version,
            )

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
            return self._result(
                valid=False,
                xsd_valid=False,
                schematron_valid=False,
                xsd_errors=[f"XML parse error: {exc}"],
                asset_version=self.asset_version,
            )

        dataset_name = doc.tag.split("}")[-1] if "}" in doc.tag else doc.tag
        xsd_file = self._resolve_xsd_path(dataset_name, xsd_search_root)
        if not xsd_file:
            return self._result(
                valid=False,
                xsd_valid=False,
                schematron_valid=False,
                xsd_errors=[f"No official XSD asset found for dataset '{dataset_name}' under '{self._xsd_path}'"],
                asset_version=self.asset_version,
            )

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

        xsd_valid = not xsd_errors
        if xsd_valid:
            sch_file = self._resolve_schematron_path(dataset_name)
            if not sch_file:
                schematron_errors.append(
                    f"No official Schematron asset found for dataset '{dataset_name}' under '{self._sch_path}'"
                )
            else:
                try:
                    schematron_errors, schematron_warnings = self.run_schematron_validation(
                        xml_bytes,
                        sch_file,
                        self._sch_path,
                    )
                except Exception as exc:
                    schematron_errors.append(f"Schematron validation error: {exc}")
                    logger.exception("NemsisXSDValidator: Schematron raised exception")
        else:
            schematron_warnings.append("Schematron validation not executed because XSD validation failed")

        schematron_valid = xsd_valid and not schematron_errors
        return self._result(
            valid=xsd_valid and schematron_valid,
            xsd_valid=xsd_valid,
            schematron_valid=schematron_valid,
            xsd_errors=xsd_errors,
            schematron_errors=schematron_errors,
            schematron_warnings=schematron_warnings,
            asset_version=self.asset_version,
        )

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
            "NemsisXSDValidator: export %s — valid=%s xsd_valid=%s sch_valid=%s xsd_errors=%d sch_errors=%d",
            export_id,
            result.get("valid"),
            result.get("xsd_valid"),
            result.get("schematron_valid"),
            len(result.get("xsd_errors", [])),
            len(result.get("schematron_errors", [])),
        )
        return result
