from __future__ import annotations

"""Build and persist the authoritative Allergy EMSDataSet export artifact."""

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from .runtime_injector import RuntimeInjectionContext, RuntimeValueInjector
from .template_loader import LoadedOfficialTemplate, OfficialTemplateLoader


@dataclass(frozen=True)
class BuiltExportArtifact:
    """Serialized Allergy export artifact and preservation metadata."""

    xml_bytes: bytes
    xml_path: Path
    unresolved_placeholders: list[str]
    repeated_group_counts_before: dict[str, int]
    repeated_group_counts_after: dict[str, int]


class OfficialExportBuilder:
    """Construct and persist the locked official Allergy EMS export artifact."""

    def __init__(self, output_root: Path | None = None) -> None:
        """Initialize the artifact builder.

        Args:
            output_root: Optional output directory root.

        Returns:
            None.
        """

        service_root = Path(__file__).resolve().parents[3]
        self._output_root = output_root or service_root / "artifact" / "generated"
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._injector = RuntimeValueInjector()

    def build(
        self,
        loaded_template: LoadedOfficialTemplate,
        context: RuntimeInjectionContext,
        artifact_name: str = "2025-EMS-1-Allergy_v351.xml",
    ) -> BuiltExportArtifact:
        """Build the Allergy EMSDataSet export and persist it to disk.

        Args:
            loaded_template: Authoritative template documents.
            context: Runtime injection context.
            artifact_name: Output XML file name.

        Returns:
            BuiltExportArtifact with serialized XML and structure-preservation metadata.
        """

        repeated_before = OfficialTemplateLoader.collect_repeated_group_counts(loaded_template.ems_root)
        working_root = loaded_template.copy_ems_root()
        self._injector.apply(working_root, context)
        unresolved_placeholders = self._injector.find_unresolved_placeholders(working_root)
        repeated_after = OfficialTemplateLoader.collect_repeated_group_counts(working_root)
        xml_bytes = ET.tostring(working_root, encoding="utf-8", xml_declaration=True)
        output_path = self._output_root / artifact_name
        output_path.write_bytes(xml_bytes)
        return BuiltExportArtifact(
            xml_bytes=xml_bytes,
            xml_path=output_path,
            unresolved_placeholders=unresolved_placeholders,
            repeated_group_counts_before=repeated_before,
            repeated_group_counts_after=repeated_after,
        )
