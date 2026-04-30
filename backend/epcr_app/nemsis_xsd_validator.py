""""NEMSIS 3.5.1 gravity-level XSD and Schematron validator.

Deterministic, audit-safe validation engine with:
- strict asset enforcement
- structured issue output
- checksum binding
- execution telemetry
- lifecycle-safe error classification
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


class NemsisValidationError(Exception):
    pass


class NemsisXSDValidator:

    def __init__(self) -> None:
        self._lxml_available = self._check_lxml()
        self._saxon_available = self._check_saxonche()

        self._xsd_path = os.environ.get("NEMSIS_XSD_PATH", "")
        self._sch_path = os.environ.get("NEMSIS_SCHEMATRON_PATH", "")

        self.asset_version = os.environ.get("NEMSIS_VALIDATOR_ASSET_VERSION", "").strip() or None

        self._xsd_tempdir: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._xsd_tempdir:
            self._xsd_tempdir.cleanup()
            self._xsd_tempdir = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _check_lxml() -> bool:
        try:
            import lxml.etree  # noqa
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_saxonche() -> bool:
        try:
            import saxonche  # noqa
            return True
        except ImportError:
            return False

    def _fail(
        self,
        message: str,
        checksum: str,
        *,
        validation_skipped: bool = True,
    ) -> dict[str, Any]:
        return {
            "valid": False,
            "xsd_valid": False,
            "schematron_valid": False,
            "validation_skipped": validation_skipped,
            "blocking_reason": f"Validation did not run: {message}" if validation_skipped else None,
            "xsd_errors": [message],
            "schematron_errors": [],
            "schematron_warnings": [],
            "cardinality_errors": [],
            "errors": [message],
            "warnings": [],
            "checksum_sha256": checksum,
            "validator_asset_version": self.asset_version,
            "execution_ms": 0,
        }

    def get_xsd_asset_path(self, dataset: str) -> str | None:
        try:
            xsd_root = self._resolve_xsd_root()
        except Exception:
            return None
        return self._find(xsd_root, (f"{dataset}_v3.xsd",))

    def get_schematron_asset_path(self, dataset: str) -> str | None:
        try:
            sch_root = self._resolve_schematron_root()
        except Exception:
            return None
        return self._find(sch_root, (f"{dataset}.sch", f"{dataset}_v3.sch"))

    def _resolve_xsd_root(self) -> str:
        if not self._xsd_path:
            raise NemsisValidationError("NEMSIS_XSD_PATH not configured")

        if os.path.isdir(self._xsd_path):
            return self._xsd_path

        if zipfile.is_zipfile(self._xsd_path):
            if not self._xsd_tempdir:
                self._xsd_tempdir = tempfile.TemporaryDirectory()
                with zipfile.ZipFile(self._xsd_path) as z:
                    z.extractall(self._xsd_tempdir.name)
            return self._xsd_tempdir.name

        raise NemsisValidationError("Invalid XSD asset path")

    def _resolve_schematron_root(self) -> str:
        if not self._sch_path or not os.path.isdir(self._sch_path):
            raise NemsisValidationError("NEMSIS_SCHEMATRON_PATH invalid")
        return self._sch_path

    def _find(self, root: str, names: tuple[str, ...]) -> str | None:
        for r, _, files in os.walk(root):
            for name in names:
                if name in files:
                    return os.path.join(r, name)
        return None

    def validate_xml(self, xml: str | bytes) -> dict[str, Any]:
        start = perf_counter()

        xml_bytes = xml.encode() if isinstance(xml, str) else xml
        checksum = hashlib.sha256(xml_bytes).hexdigest()

        if not self._lxml_available:
            return self._fail("lxml not installed", checksum)

        try:
            import lxml.etree as ET
        except Exception:
            return self._fail("lxml import failure", checksum)

        try:
            doc = ET.fromstring(xml_bytes)
        except Exception as exc:
            return self._fail(f"XML parse error: {exc}", checksum, validation_skipped=False)

        try:
            xsd_root = self._resolve_xsd_root()
            sch_root = self._resolve_schematron_root()
        except Exception as exc:
            return self._fail(str(exc), checksum)

        dataset = doc.tag.split("}")[-1]

        xsd_file = self.get_xsd_asset_path(dataset)
        if not xsd_file:
            return self._fail(f"Missing XSD for dataset {dataset}", checksum)

        xsd_errors: list[str] = []
        schematron_errors: list[str] = []
        schematron_warnings: list[str] = []

        try:
            schema = ET.XMLSchema(ET.parse(xsd_file))
            if not schema.validate(doc):
                for e in schema.error_log:
                    xsd_errors.append(f"{e.line}: {e.message}")
        except Exception as exc:
            xsd_errors.append(str(exc))

        if not xsd_errors:
            sch_file = self.get_schematron_asset_path(dataset)
            if not sch_file:
                schematron_errors.append("Missing Schematron file")
            else:
                try:
                    sch_text = Path(sch_file).read_text(encoding="utf-8", errors="ignore")
                    is_xslt2 = 'queryBinding="xslt2"' in sch_text or "queryBinding='xslt2'" in sch_text
                    if is_xslt2:
                        if not self._saxon_available:
                            return self._fail(
                                f"Schematron {Path(sch_file).name} requires saxonche/XSLT2 support",
                                checksum,
                            )
                        sch_errs, sch_warns = self._run_saxon_schematron(
                            xml_bytes, sch_file, sch_root
                        )
                        schematron_errors.extend(sch_errs)
                        schematron_warnings.extend(sch_warns)
                    else:
                        from lxml.isoschematron import Schematron

                        schematron = Schematron(ET.parse(sch_file), store_report=True)
                        if not schematron.validate(doc):
                            report = schematron.validation_report
                            for el in report.iter():
                                text = "".join(el.itertext()).strip()
                                if not text:
                                    continue
                                if "warning" in (el.get("role") or "").lower():
                                    schematron_warnings.append(text)
                                else:
                                    schematron_errors.append(text)
                except Exception as exc:
                    schematron_errors.append(str(exc))

        valid = not xsd_errors and not schematron_errors

        return {
            "valid": valid,
            "xsd_valid": not xsd_errors,
            "schematron_valid": not schematron_errors,
            "validation_skipped": False,
            "blocking_reason": None,
            "xsd_errors": xsd_errors,
            "schematron_errors": schematron_errors,
            "schematron_warnings": schematron_warnings,
            "cardinality_errors": [],
            "errors": [*xsd_errors, *schematron_errors],
            "warnings": schematron_warnings,
            "checksum_sha256": checksum,
            "validator_asset_version": self.asset_version,
            "execution_ms": int((perf_counter() - start) * 1000),
        }

    def validate_export(self, xml: str | bytes, export_id: Any = None) -> dict[str, Any]:
        logger.info("validate_export start export_id=%s", export_id)
        result = self.validate_xml(xml)
        logger.info("validate_export result export_id=%s valid=%s", export_id, result["valid"])
        return result

    # --- Saxon-based ISO Schematron (XSLT2) evaluation -------------------------------

    _SAXON_SKELETON_RELATIVE_CANDIDATES = (
        "iso-schematron-xslt2",
        "Schematron/utilities/iso-schematron-xslt2",
        "utilities/iso-schematron-xslt2",
    )

    def _find_saxon_skeleton_dir(self, sch_root: str) -> str | None:
        for rel in self._SAXON_SKELETON_RELATIVE_CANDIDATES:
            candidate = os.path.join(sch_root, rel)
            if os.path.isdir(candidate) and os.path.isfile(
                os.path.join(candidate, "iso_svrl_for_xslt2.xsl")
            ):
                return candidate
        for r, _dirs, files in os.walk(sch_root):
            if "iso_svrl_for_xslt2.xsl" in files:
                return r
        return None

    def _run_saxon_schematron(
        self,
        xml_bytes: bytes,
        sch_file: str,
        sch_root: str,
    ) -> tuple[list[str], list[str]]:
        """Compile schematron via the standard 3-stage XSLT2 pipeline using saxonche
        and apply the resulting transform to the document. Parse SVRL output for
        failed-asserts (errors) and successful-reports (warnings)."""
        skeleton_dir = self._find_saxon_skeleton_dir(sch_root)
        if not skeleton_dir:
            return (
                ["Saxon ISO Schematron skeleton XSLT files not found under "
                 "NEMSIS_SCHEMATRON_PATH"],
                [],
            )

        include_xsl = os.path.join(skeleton_dir, "iso_dsdl_include.xsl")
        expand_xsl = os.path.join(skeleton_dir, "iso_abstract_expand.xsl")
        skeleton_xsl = os.path.join(skeleton_dir, "iso_svrl_for_xslt2.xsl")

        for required in (include_xsl, expand_xsl, skeleton_xsl):
            if not os.path.isfile(required):
                return ([f"Required Schematron XSLT missing: {required}"], [])

        try:
            from saxonche import PySaxonProcessor  # type: ignore
        except Exception as exc:  # pragma: no cover - guarded by _saxon_available
            return ([f"saxonche unavailable: {exc}"], [])

        try:
            with PySaxonProcessor(license=False) as proc:
                xslt = proc.new_xslt30_processor()

                include_exec = xslt.compile_stylesheet(stylesheet_file=include_xsl)
                expand_exec = xslt.compile_stylesheet(stylesheet_file=expand_xsl)
                skeleton_exec = xslt.compile_stylesheet(stylesheet_file=skeleton_xsl)
                # NEMSIS schematron uses xsl:variable / xsl:template inside <sch:schema>;
                # iso_svrl_for_xslt2 only forwards those when allow-foreign=true.
                try:
                    skeleton_exec.set_parameter(
                        "allow-foreign", proc.make_string_value("true")
                    )
                except Exception:
                    pass

                # Stage 1: dsdl include (input = schematron file)
                stage1 = include_exec.transform_to_string(source_file=sch_file)
                if not stage1:
                    return ([f"Saxon schematron stage1 produced empty output: {include_exec.error_message}"], [])

                # Stage 2: abstract expand
                stage2_node = proc.parse_xml(xml_text=stage1)
                stage2 = expand_exec.transform_to_string(xdm_node=stage2_node)
                if not stage2:
                    return ([f"Saxon schematron stage2 produced empty output: {expand_exec.error_message}"], [])

                # Stage 3: compile to runnable XSLT
                stage3_node = proc.parse_xml(xml_text=stage2)
                compiled_xsl_text = skeleton_exec.transform_to_string(xdm_node=stage3_node)
                if not compiled_xsl_text:
                    return ([f"Saxon schematron stage3 produced empty output: {skeleton_exec.error_message}"], [])

                # Apply compiled XSLT to the document → SVRL
                runnable = xslt.compile_stylesheet(stylesheet_text=compiled_xsl_text)
                doc_node = proc.parse_xml(xml_text=xml_bytes.decode("utf-8"))
                svrl_text = runnable.transform_to_string(xdm_node=doc_node)
        except Exception as exc:
            return ([f"Saxon schematron pipeline failure: {exc}"], [])

        if not svrl_text:
            return ([], [])

        return self._parse_svrl(svrl_text)

    @staticmethod
    def _parse_svrl(svrl_text: str) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        try:
            import lxml.etree as ET

            root = ET.fromstring(svrl_text.encode("utf-8"))
        except Exception as exc:
            return ([f"SVRL parse failure: {exc}"], [])

        ns = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
        for fa in root.findall(".//svrl:failed-assert", ns):
            text = "".join(fa.itertext()).strip()
            role = (fa.get("role") or "").lower()
            location = fa.get("location") or ""
            msg = f"{text} [{location}]" if location else text
            if not msg:
                continue
            if "warn" in role or "info" in role:
                warnings.append(msg)
            else:
                errors.append(msg)

        for sr in root.findall(".//svrl:successful-report", ns):
            text = "".join(sr.itertext()).strip()
            role = (sr.get("role") or "").lower()
            location = sr.get("location") or ""
            msg = f"{text} [{location}]" if location else text
            if not msg:
                continue
            if "error" in role or "fatal" in role:
                errors.append(msg)
            else:
                warnings.append(msg)

        return (errors, warnings)