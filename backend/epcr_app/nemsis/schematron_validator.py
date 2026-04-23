from __future__ import annotations

"""Compile and apply the official local NEMSIS EMS Schematron rules with XSLT 2.0 support."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import argparse
import hashlib
import json

from lxml import etree
from saxonche import PySaxonProcessor


SVRL_NS = {"svrl": "http://purl.oclc.org/dsdl/svrl"}


@dataclass(frozen=True)
class SchematronIssue:
    """Structured Schematron validation issue extracted from SVRL."""

    role: str
    location: str
    text: str
    test: str | None


@dataclass(frozen=True)
class SchematronValidationResult:
    """Outcome of official Schematron validation for a NEMSIS XML document."""

    is_valid: bool
    schema_path: str
    compiled_xsl_path: str
    svrl_path: str
    errors: list[SchematronIssue]
    warnings: list[SchematronIssue]


class OfficialSchematronValidator:
    """Compile NEMSIS XSLT 2.0 Schematron rules and apply them to EMS XML."""

    def __init__(self, schema_path: Path | None = None, compile_root: Path | None = None) -> None:
        """Initialize validator paths rooted at repository-local official assets.

        Args:
            schema_path: Optional EMS Schematron source path.
            compile_root: Optional cache directory for compiled XSLT and SVRL outputs.

        Returns:
            None.

        Raises:
            FileNotFoundError: If the official EMS Schematron source is unavailable.
        """

        service_root = Path(__file__).resolve().parents[3]
        self._utilities_root = (
            service_root / "nemsis_test" / "assets" / "schematron" / "Schematron" / "utilities"
        )
        self._schema_path = schema_path or (
            service_root / "nemsis_test" / "assets" / "schematron" / "Schematron" / "rules" / "SampleEMSDataSet.sch"
        )
        self._compile_root = compile_root or service_root / "nemsis_test" / "output" / "schematron_cache"
        self._compile_root.mkdir(parents=True, exist_ok=True)
        if not self._schema_path.exists():
            raise FileNotFoundError(f"Official EMS Schematron file not found: {self._schema_path}")

    def validate(self, xml_bytes: bytes) -> SchematronValidationResult:
        """Validate an EMS XML document with the official XSLT 2.0 Schematron pipeline.

        Args:
            xml_bytes: Serialized EMSDataSet XML bytes.

        Returns:
            SchematronValidationResult including SVRL output and categorized issues.
        """

        compiled_xsl_path = self._ensure_compiled_xsl()
        source_hash = hashlib.sha256(xml_bytes).hexdigest()[:16]
        svrl_path = self._compile_root / f"SampleEMSDataSet.{source_hash}.svrl"
        with NamedTemporaryFile(suffix=".xml", delete=False) as handle:
            temp_xml_path = Path(handle.name)
            handle.write(xml_bytes)
        try:
            with PySaxonProcessor(license=False) as processor:
                xslt_proc = processor.new_xslt30_processor()
                xslt_proc.transform_to_file(
                    source_file=str(temp_xml_path),
                    stylesheet_file=str(compiled_xsl_path),
                    output_file=str(svrl_path),
                )
            svrl_doc = etree.parse(str(svrl_path))
        finally:
            temp_xml_path.unlink(missing_ok=True)

        issues = self._parse_svrl_issues(svrl_doc)
        errors = [issue for issue in issues if issue.role in {"[ERROR]", "[FATAL]"}]
        warnings = [issue for issue in issues if issue.role == "[WARNING]"]
        return SchematronValidationResult(
            is_valid=not errors,
            schema_path=str(self._schema_path),
            compiled_xsl_path=str(compiled_xsl_path),
            svrl_path=str(svrl_path),
            errors=errors,
            warnings=warnings,
        )

    def _ensure_compiled_xsl(self) -> Path:
        """Compile the official Schematron file into executable XSLT when needed.

        Args:
            None.

        Returns:
            Absolute path to the compiled XSLT stylesheet.
        """

        compiled_xsl_path = self._compile_root / f"{self._schema_path.stem}.xsl"
        compiled_sch_path = self._compile_root / f"{self._schema_path.stem}.compiled.sch"
        compiled_xsl_tmp_path = self._compile_root / f"{self._schema_path.stem}.xsl.tmp"
        compiled_sch_tmp_path = self._compile_root / f"{self._schema_path.stem}.compiled.sch.tmp"
        schema_mtime = self._schema_path.stat().st_mtime
        if compiled_xsl_path.exists() and compiled_sch_path.exists():
            if (
                compiled_xsl_path.stat().st_mtime >= schema_mtime
                and compiled_sch_path.stat().st_mtime >= schema_mtime
                and compiled_xsl_path.stat().st_size > 0
            ):
                return compiled_xsl_path

        include_stage = self._compile_root / f"{self._schema_path.stem}.include.sch"
        include_xsl = self._utilities_root / "iso-schematron-xslt2" / "iso_dsdl_include.xsl"
        abstract_xsl = self._utilities_root / "iso-schematron-xslt2" / "iso_abstract_expand.xsl"
        svrl_xsl = self._utilities_root / "iso-schematron-xslt2" / "iso_svrl_for_xslt2.xsl"
        compiled_xsl_path.unlink(missing_ok=True)
        compiled_sch_path.unlink(missing_ok=True)
        compiled_xsl_tmp_path.unlink(missing_ok=True)
        compiled_sch_tmp_path.unlink(missing_ok=True)
        try:
            with PySaxonProcessor(license=False) as processor:
                xslt_proc = processor.new_xslt30_processor()
                xslt_proc.transform_to_file(
                    source_file=str(self._schema_path),
                    stylesheet_file=str(include_xsl),
                    output_file=str(include_stage),
                )
                xslt_proc.transform_to_file(
                    source_file=str(include_stage),
                    stylesheet_file=str(abstract_xsl),
                    output_file=str(compiled_sch_tmp_path),
                )
                executable = xslt_proc.compile_stylesheet(stylesheet_file=str(svrl_xsl))
                executable.set_parameter("allow-foreign", processor.make_string_value("true"))
                executable.transform_to_file(source_file=str(compiled_sch_tmp_path), output_file=str(compiled_xsl_tmp_path))
            compiled_sch_tmp_path.replace(compiled_sch_path)
            compiled_xsl_tmp_path.replace(compiled_xsl_path)
        finally:
            include_stage.unlink(missing_ok=True)
            compiled_sch_tmp_path.unlink(missing_ok=True)
            compiled_xsl_tmp_path.unlink(missing_ok=True)
        return compiled_xsl_path

    @staticmethod
    def _parse_svrl_issues(svrl_doc: etree._ElementTree) -> list[SchematronIssue]:
        """Extract failed assertions and successful reports from SVRL output.

        Args:
            svrl_doc: Parsed SVRL document.

        Returns:
            Ordered list of structured Schematron issues.
        """

        issues: list[SchematronIssue] = []
        for node in svrl_doc.xpath("//svrl:failed-assert | //svrl:successful-report", namespaces=SVRL_NS):
            text_node = node.find("svrl:text", SVRL_NS)
            issues.append(
                SchematronIssue(
                    role=node.get("role", ""),
                    location=node.get("location", ""),
                    text=(text_node.text or "").strip() if text_node is not None else "",
                    test=node.get("test"),
                )
            )
        return issues


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a NEMSIS XML artifact with the official EMS Schematron rules.")
    parser.add_argument("xml_path", help="Path to the XML file to validate.")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[3] / "artifact" / "validation" / "schematron-result.json"),
        help="Path to write the JSON Schematron result.",
    )
    return parser


def main() -> int:
    args = _build_cli_parser().parse_args()
    xml_path = Path(args.xml_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = OfficialSchematronValidator().validate(xml_path.read_bytes())
    payload = {
        "is_valid": result.is_valid,
        "schema_path": result.schema_path,
        "compiled_xsl_path": result.compiled_xsl_path,
        "svrl_path": result.svrl_path,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("SCHEMATRON PASS" if result.is_valid else "SCHEMATRON FAIL")
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
