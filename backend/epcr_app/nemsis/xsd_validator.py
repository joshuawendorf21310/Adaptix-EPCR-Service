from __future__ import annotations

"""Validate NEMSIS XML artifacts against the official local 3.5.1 XSD assets."""

from dataclasses import dataclass
from pathlib import Path
import argparse
import json
import zipfile

from lxml import etree


@dataclass(frozen=True)
class XsdValidationResult:
    """Outcome of XSD validation for a NEMSIS XML document."""

    is_valid: bool
    dataset_name: str
    xsd_path: str
    errors: list[str]


class OfficialXsdValidator:
    """Resolve and apply the official local NEMSIS XSD bundle."""

    def __init__(self, xsd_zip_path: Path | None = None, extraction_root: Path | None = None) -> None:
        """Initialize the XSD validator with repository-local bundle defaults.

        Args:
            xsd_zip_path: Optional path to the official XSD zip bundle.
            extraction_root: Optional extraction/cache directory.

        Returns:
            None.

        Raises:
            FileNotFoundError: If the local XSD bundle is unavailable.
        """

        service_root = Path(__file__).resolve().parents[3]
        self._xsd_zip_path = xsd_zip_path or service_root / "nemsis_test" / "assets" / "xsd" / "NEMSIS_XSDs.zip"
        self._extraction_root = extraction_root or service_root / "nemsis_test" / "output" / "xsd_cache"
        if not self._xsd_zip_path.exists():
            raise FileNotFoundError(f"Official XSD bundle not found: {self._xsd_zip_path}")

    def validate(self, xml_bytes: bytes) -> XsdValidationResult:
        """Validate XML bytes against the matching EMS/DEM/State dataset XSD.

        Args:
            xml_bytes: Serialized XML document bytes.

        Returns:
            XsdValidationResult with resolved dataset and all schema errors.

        Raises:
            ValueError: If the XML root does not map to a supported NEMSIS dataset.
        """

        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        document = etree.fromstring(xml_bytes, parser=parser)
        dataset_name = etree.QName(document.tag).localname
        xsd_path = self._resolve_xsd_path(dataset_name)
        schema = etree.XMLSchema(etree.parse(str(xsd_path), parser))
        document_tree = etree.ElementTree(document)
        is_valid = schema.validate(document_tree)
        errors = [entry.message for entry in schema.error_log] if not is_valid else []
        return XsdValidationResult(
            is_valid=is_valid,
            dataset_name=dataset_name,
            xsd_path=str(xsd_path),
            errors=errors,
        )

    def _resolve_xsd_path(self, dataset_name: str) -> Path:
        """Resolve the dataset-specific XSD file from the local official bundle.

        Args:
            dataset_name: XML root local name, such as `EMSDataSet`.

        Returns:
            Absolute path to the matching dataset XSD.

        Raises:
            FileNotFoundError: If the dataset XSD cannot be found.
            ValueError: If the dataset name is unsupported.
        """

        if dataset_name not in {"EMSDataSet", "DEMDataSet", "StateDataSet"}:
            raise ValueError(f"Unsupported NEMSIS dataset root for XSD validation: {dataset_name}")
        target_name = f"{dataset_name}_v3.xsd"
        extraction_dir = self._ensure_extracted_bundle()
        for candidate in extraction_dir.rglob(target_name):
            return candidate
        raise FileNotFoundError(f"Unable to locate {target_name} in extracted XSD bundle {extraction_dir}")

    def _ensure_extracted_bundle(self) -> Path:
        """Extract the official XSD bundle once into a local cache directory.

        Args:
            None.

        Returns:
            Extraction directory containing the official XSD files.
        """

        marker = self._extraction_root / ".complete"
        if marker.exists():
            return self._extraction_root
        self._extraction_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self._xsd_zip_path, "r") as archive:
            archive.extractall(self._extraction_root)
        marker.write_text("ok", encoding="utf-8")
        return self._extraction_root


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a NEMSIS XML artifact against the official XSD bundle.")
    parser.add_argument("xml_path", help="Path to the XML file to validate.")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[3] / "artifact" / "validation" / "xsd-result.json"),
        help="Path to write the JSON validation result.",
    )
    return parser


def main() -> int:
    args = _build_cli_parser().parse_args()
    xml_path = Path(args.xml_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = OfficialXsdValidator().validate(xml_path.read_bytes())
    output_path.write_text(json.dumps({
        "is_valid": result.is_valid,
        "dataset_name": result.dataset_name,
        "xsd_path": result.xsd_path,
        "errors": result.errors,
    }, indent=2), encoding="utf-8")
    print("XSD PASS" if result.is_valid else "XSD FAIL")
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
