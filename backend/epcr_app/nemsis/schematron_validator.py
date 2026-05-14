from __future__ import annotations

"""Compile and apply the official local NEMSIS EMS Schematron rules with XSLT 2.0 support."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
import argparse
import hashlib
import json

from lxml import etree

try:  # pragma: no cover - optional dependency for environments without Saxon-C
    from saxonche import PySaxonProcessor
except ImportError:  # pragma: no cover
    PySaxonProcessor = None  # type: ignore[assignment]


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

    def __init__(
        self,
        schema_path: Path | None = None,
        compile_root: Path | None = None,
        utilities_root: Path | None = None,
    ) -> None:
        """Initialize validator paths rooted at repository-local official assets.

        Args:
            schema_path: Optional EMS Schematron source path.
            compile_root: Optional cache directory for compiled XSLT and SVRL outputs.
            utilities_root: Optional ISO Schematron utility root override.

        Returns:
            None.

        Raises:
            FileNotFoundError: If the official EMS Schematron source is unavailable.
        """
        service_root = self._resolve_service_root(Path(__file__).resolve())
        baked_schematron_root = service_root / "nemsis" / "schematron" / "Schematron"
        legacy_schematron_root = service_root / "nemsis_test" / "assets" / "schematron" / "Schematron"
        default_schematron_root = baked_schematron_root if baked_schematron_root.exists() else legacy_schematron_root

        self._schema_path = schema_path or self._infer_default_schema_path(service_root, default_schematron_root)
        self._utilities_root = utilities_root or self._infer_utilities_root(self._schema_path, default_schematron_root)
        self._compile_root = compile_root or service_root / "artifact" / "validation" / "schematron_cache"
        self._compile_root.mkdir(parents=True, exist_ok=True)
        if not self._schema_path.exists():
            raise FileNotFoundError(f"Official EMS Schematron file not found: {self._schema_path}")
        if not self._utilities_root.exists():
            raise FileNotFoundError(f"Official ISO Schematron utilities not found: {self._utilities_root}")

    @staticmethod
    def _resolve_service_root(module_path: Path) -> Path:
        """Find the backend root that owns baked NEMSIS assets."""

        for parent in module_path.parents:
            if (parent / "nemsis" / "schematron" / "Schematron").exists():
                return parent
            if (parent / "nemsis_test" / "assets" / "schematron" / "Schematron").exists():
                return parent
        return module_path.parents[2]

    @staticmethod
    def _infer_utilities_root(schema_path: Path, default_schematron_root: Path) -> Path:
        """Resolve ISO Schematron utilities next to an explicit schema when possible."""

        sibling_utilities = schema_path.parent.parent / "utilities"
        if sibling_utilities.exists():
            return sibling_utilities
        return default_schematron_root / "utilities"

    @staticmethod
    def _infer_default_schema_path(service_root: Path, default_schematron_root: Path) -> Path:
        """Prefer the canonical baked EMSDataSet schema, then fall back to legacy sample assets."""

        candidates = (
            service_root / "nemsis" / "schematron" / "EMSDataSet.sch",
            default_schematron_root / "rules" / "SampleEMSDataSet.sch",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def validate(self, xml_bytes: bytes) -> SchematronValidationResult:
        """Validate an EMS XML document with the official XSLT 2.0 Schematron pipeline.

        Args:
            xml_bytes: Serialized EMSDataSet XML bytes.

        Returns:
            SchematronValidationResult including SVRL output and categorized issues.
        """

        if PySaxonProcessor is None:
            raise RuntimeError(
                "saxonche is not installed; Schematron validation disabled"
            )

        compiled_xsl_path = self._ensure_compiled_xsl()
        source_hash = hashlib.sha256(xml_bytes).hexdigest()[:16]
        svrl_path = self._compile_root / f"{self._schema_path.stem}.{source_hash}.svrl"
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
        errors = [
            issue
            for issue in issues
            if self._normalized_issue_role(issue.role) in {"ERROR", "FATAL"}
        ]
        warnings = [
            issue
            for issue in issues
            if self._normalized_issue_role(issue.role) == "WARNING"
        ]
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

        if PySaxonProcessor is None:
            raise RuntimeError(
                "saxonche is not installed; Schematron validation disabled"
            )

        compiled_xsl_path = self._compile_root / f"{self._schema_path.stem}.xsl"
        compiled_sch_path = self._compile_root / f"{self._schema_path.stem}.compiled.sch"
        compiled_xsl_tmp_path = self._compile_root / f"{self._schema_path.stem}.xsl.tmp"
        compiled_sch_tmp_path = self._compile_root / f"{self._schema_path.stem}.compiled.sch.tmp"
        dependency_paths = self._schematron_dependency_paths()
        latest_dependency_mtime = max(path.stat().st_mtime for path in dependency_paths)
        if compiled_xsl_path.exists() and compiled_sch_path.exists():
            if (
                compiled_xsl_path.stat().st_mtime >= latest_dependency_mtime
                and compiled_sch_path.stat().st_mtime >= latest_dependency_mtime
                and compiled_xsl_path.stat().st_size > 0
            ):
                return compiled_xsl_path

        include_stage = self._compile_root / f"{self._schema_path.stem}.include.sch"
        include_xsl, abstract_xsl, svrl_xsl = dependency_paths[1:]
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

    def _schematron_dependency_paths(self) -> tuple[Path, Path, Path, Path]:
        """Return the schema and ISO Schematron utility files required to build executable XSL."""

        iso_xslt2_root = self._utilities_root / "iso-schematron-xslt2"
        dependency_paths = (
            self._schema_path,
            iso_xslt2_root / "iso_dsdl_include.xsl",
            iso_xslt2_root / "iso_abstract_expand.xsl",
            iso_xslt2_root / "iso_svrl_for_xslt2.xsl",
        )
        missing_paths = [path for path in dependency_paths if not path.exists()]
        if missing_paths:
            missing = ", ".join(str(path) for path in missing_paths)
            raise FileNotFoundError(f"Official Schematron build dependencies not found: {missing}")
        return dependency_paths

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

    @staticmethod
    def _normalized_issue_role(role: str) -> str:
        """Normalize SVRL role values before severity classification."""

        return role.strip().strip("[]").upper()


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
