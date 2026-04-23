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

    def _fail(self, message: str, checksum: str) -> dict[str, Any]:
        return {
            "valid": False,
            "xsd_valid": False,
            "schematron_valid": False,
            "errors": [message],
            "warnings": [],
            "checksum_sha256": checksum,
            "validator_asset_version": self.asset_version,
            "execution_ms": 0,
        }

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
            return self._fail(f"XML parse error: {exc}", checksum)

        try:
            xsd_root = self._resolve_xsd_root()
            sch_root = self._resolve_schematron_root()
        except Exception as exc:
            return self._fail(str(exc), checksum)

        dataset = doc.tag.split("}")[-1]

        xsd_file = self._find(xsd_root, (f"{dataset}_v3.xsd",))
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
            sch_file = self._find(sch_root, (f"{dataset}.sch", f"{dataset}_v3.sch"))
            if not sch_file:
                schematron_errors.append("Missing Schematron file")
            else:
                try:
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