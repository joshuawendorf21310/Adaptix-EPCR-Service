"""Dataset-aware NEMSIS 3.5.1 XML builder.

Reads the row-per-occurrence ``epcr_nemsis_field_values`` ledger
(``services_nemsis_field_values.NemsisFieldValueService``) and emits one
NEMSIS XML artifact per dataset (``EMSDataSet``, ``DEMDataSet``,
``StateDataSet``).

This is the truthful replacement for the legacy ``NemsisXmlBuilder``
path that consumed ``NemsisMappingRecord`` rows and could only emit a
single StateDataSet artifact. The legacy builder is preserved (still
imported for the EMS template/scenario flow) but new export paths
should prefer this builder so DEM and State values captured through
the new persistence slice actually leave the system as compliant XML.

Truth contract:
- Reads ONLY from ``epcr_nemsis_field_values`` via the canonical service.
- Groups rows by dataset using the official registry (no hardcoded
  dataset-to-section maps).
- Preserves repeating-group truth: rows with the same ``element_number``
  but different ``occurrence_id`` are emitted as separate XML elements.
- Honors ``attributes_json`` sidecars: ``NV`` and ``PN`` are emitted as
  XML attributes, ``xsiNil`` becomes ``xsi:nil="true"`` with empty text.
- Emits per-dataset SHA-256 checksums alongside each artifact.
- If a chart has no rows for a given dataset, the artifact for that
  dataset is omitted from the output (no fake-empty XML).
- If the registry cannot resolve a row's dataset (unknown element), the
  row is reported in ``warnings`` and excluded — never silently dropped
  into the wrong dataset.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.nemsis_registry_service import (
    NemsisRegistryService,
    get_default_registry_service,
)
from epcr_app.services_nemsis_field_values import NemsisFieldValueService

logger = logging.getLogger(__name__)

NEMSIS_NS = "http://www.nemsis.org"
NEMSIS_XSI = "http://www.w3.org/2001/XMLSchema-instance"
NEMSIS_VERSION = "3.5.1.251001CP2"

DATASET_ROOT_ELEMENT = {
    "EMSDataSet": "EMSDataSet",
    "DEMDataSet": "DEMDataSet",
    "StateDataSet": "StateDataSet",
}

DATASET_XSD_URL = {
    "EMSDataSet": (
        f"{NEMSIS_NS} "
        f"https://nemsis.org/media/nemsis_v3/{NEMSIS_VERSION}/XSDs/NEMSIS_XSDs/EMSDataSet_v3.xsd"
    ),
    "DEMDataSet": (
        f"{NEMSIS_NS} "
        f"https://nemsis.org/media/nemsis_v3/{NEMSIS_VERSION}/XSDs/NEMSIS_XSDs/DEMDataSet_v3.xsd"
    ),
    "StateDataSet": (
        f"{NEMSIS_NS} "
        f"https://nemsis.org/media/nemsis_v3/{NEMSIS_VERSION}/XSDs/NEMSIS_XSDs/StateDataSet_v3.xsd"
    ),
}

register_namespace("", NEMSIS_NS)
register_namespace("xsi", NEMSIS_XSI)


class DatasetBuildError(ValueError):
    """Raised when dataset XML cannot be built truthfully."""


@dataclass
class DatasetArtifact:
    """One built NEMSIS dataset XML artifact."""

    dataset: str
    xml_bytes: bytes
    sha256: str
    row_count: int
    section_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "xml": self.xml_bytes.decode("utf-8"),
            "sha256": self.sha256,
            "row_count": self.row_count,
            "section_count": self.section_count,
            "warnings": list(self.warnings),
            "size_bytes": len(self.xml_bytes),
        }


@dataclass
class DatasetBuildResult:
    """Aggregate of all dataset artifacts built for one chart."""

    chart_id: str
    tenant_id: str
    artifacts: list[DatasetArtifact] = field(default_factory=list)
    skipped_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def datasets(self) -> list[str]:
        return [a.dataset for a in self.artifacts]

    def get(self, dataset: str) -> DatasetArtifact | None:
        for a in self.artifacts:
            if a.dataset == dataset:
                return a
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_id": self.chart_id,
            "tenant_id": self.tenant_id,
            "datasets": self.datasets(),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "skipped_rows": list(self.skipped_rows),
            "warnings": list(self.warnings),
        }


class NemsisDatasetXmlBuilder:
    """Build per-dataset NEMSIS XML from the row-per-occurrence ledger."""

    def __init__(self, registry: NemsisRegistryService | None = None) -> None:
        self._registry = registry or get_default_registry_service()
        self._dataset_for_section_cache: dict[str, str] = {}
        self._element_to_dataset_cache: dict[str, str] = {}

    # -- public API -------------------------------------------------------- #

    async def build_for_chart(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        chart_id: str,
        datasets: Iterable[str] | None = None,
    ) -> DatasetBuildResult:
        """Read the field-values ledger and build one artifact per dataset.

        Args:
            session: Async DB session.
            tenant_id: Tenant identifier (enforced at SQL layer).
            chart_id: Chart identifier.
            datasets: Optional restriction set. Defaults to all 3.

        Returns:
            DatasetBuildResult with one DatasetArtifact per dataset that
            actually had rows. Datasets with zero rows are omitted.
        """
        if not tenant_id:
            raise DatasetBuildError("tenant_id is required")
        if not chart_id:
            raise DatasetBuildError("chart_id is required")

        rows = await NemsisFieldValueService.list_for_chart(
            session,
            tenant_id=tenant_id,
            chart_id=chart_id,
        )

        result = DatasetBuildResult(chart_id=chart_id, tenant_id=tenant_id)
        target_datasets = set(datasets) if datasets else set(DATASET_ROOT_ELEMENT)

        # Group rows by dataset using the official registry. Unknown
        # elements are reported, not silently misrouted.
        grouped: dict[str, list[dict[str, Any]]] = {ds: [] for ds in target_datasets}
        for row in rows:
            dataset = self._resolve_dataset_for_row(row)
            if dataset is None:
                result.skipped_rows.append({
                    "element_number": row.get("element_number"),
                    "section": row.get("section"),
                    "reason": "element_not_in_registry",
                })
                continue
            if dataset not in target_datasets:
                continue
            grouped[dataset].append(row)

        for dataset, dataset_rows in grouped.items():
            if not dataset_rows:
                continue
            artifact = self._build_dataset_artifact(dataset, dataset_rows)
            result.artifacts.append(artifact)

        return result

    # -- internal --------------------------------------------------------- #

    def _resolve_dataset_for_row(self, row: dict[str, Any]) -> str | None:
        """Resolve the dataset for a stored row using the registry.

        Resolution order:
          1. Cached element-to-dataset mapping.
          2. ``registry.get_field(element_number)["dataset"]``.
          3. Section-prefix heuristic (last resort, registry-driven):
             section in registry's section list for that dataset.
        """
        element = (row.get("element_number") or "").strip()
        section = (row.get("section") or "").strip()

        if element and element in self._element_to_dataset_cache:
            return self._element_to_dataset_cache[element]

        if element:
            meta = self._registry.get_field(element)
            if meta and meta.get("dataset") in DATASET_ROOT_ELEMENT:
                ds = meta["dataset"]
                self._element_to_dataset_cache[element] = ds
                return ds

        if section:
            ds = self._dataset_for_section(section)
            if ds:
                if element:
                    self._element_to_dataset_cache[element] = ds
                return ds

        return None

    def _dataset_for_section(self, section: str) -> str | None:
        if section in self._dataset_for_section_cache:
            return self._dataset_for_section_cache[section]
        for dataset in DATASET_ROOT_ELEMENT:
            if section in self._registry.list_sections(dataset=dataset):
                self._dataset_for_section_cache[section] = dataset
                return dataset
        return None

    def _build_dataset_artifact(
        self, dataset: str, rows: list[dict[str, Any]]
    ) -> DatasetArtifact:
        warnings: list[str] = []
        root_tag = DATASET_ROOT_ELEMENT[dataset]
        root = Element(f"{{{NEMSIS_NS}}}{root_tag}")
        root.set(f"{{{NEMSIS_XSI}}}schemaLocation", DATASET_XSD_URL[dataset])

        # Group rows by section, preserving registry section order.
        by_section: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_section.setdefault(row["section"], []).append(row)

        registry_section_order = self._registry.list_sections(dataset=dataset)
        ordered_sections = [s for s in registry_section_order if s in by_section]
        # Append any section not in the registry list (defensive).
        for s in by_section:
            if s not in ordered_sections:
                ordered_sections.append(s)
                warnings.append(
                    f"section {s!r} not enumerated in registry for {dataset}"
                )

        for section in ordered_sections:
            section_el = SubElement(root, f"{{{NEMSIS_NS}}}{section}")
            self._emit_section_rows(section_el, by_section[section], warnings)

        xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_bytes = xml_declaration + tostring(root, encoding="utf-8")

        return DatasetArtifact(
            dataset=dataset,
            xml_bytes=xml_bytes,
            sha256=hashlib.sha256(xml_bytes).hexdigest(),
            row_count=len(rows),
            section_count=len(ordered_sections),
            warnings=warnings,
        )

    def _emit_section_rows(
        self,
        section_el: Element,
        rows: list[dict[str, Any]],
        warnings: list[str],
    ) -> None:
        """Emit one XML element per ledger row.

        Repeating-group truth: distinct ``occurrence_id`` values produce
        distinct XML elements. ``sequence_index`` controls ordering.
        Group nesting via ``group_path`` is preserved as a parent-chain
        under the section root so consumers can reconstruct repeating
        group containers if their downstream NEMSIS schema demands them.
        """
        # Sort by group_path then sequence_index then occurrence_id for
        # deterministic, registry-faithful ordering.
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                r.get("group_path") or "",
                int(r.get("sequence_index") or 0),
                r.get("occurrence_id") or "",
                r.get("element_number") or "",
            ),
        )

        # Build group containers per (group_path, occurrence_id).
        # Empty group_path or group_path equal to the section means the
        # element is emitted directly under the section element.
        group_containers: dict[tuple[str, str], Element] = {}

        section_name = section_el.tag.rsplit("}", 1)[-1]

        for row in rows_sorted:
            element_number = row.get("element_number")
            if not element_number:
                warnings.append("row with empty element_number was skipped")
                continue

            group_path = (row.get("group_path") or "").strip()
            occurrence_id = (row.get("occurrence_id") or "").strip()
            parent = section_el

            # Build group container chain only when group_path goes
            # below the section. Path segments after the section name
            # become repeating-group container elements.
            if group_path and group_path != section_name:
                parent = self._ensure_group_container(
                    section_el,
                    section_name,
                    group_path,
                    occurrence_id,
                    group_containers,
                )

            self._emit_row_element(parent, row)

    def _ensure_group_container(
        self,
        section_el: Element,
        section_name: str,
        group_path: str,
        occurrence_id: str,
        cache: dict[tuple[str, str], Element],
    ) -> Element:
        # Strip section prefix so containers nest correctly.
        path = group_path
        if path.startswith(section_name + "."):
            path = path[len(section_name) + 1 :]
        elif path == section_name:
            return section_el

        cache_key = (path, occurrence_id)
        if cache_key in cache:
            return cache[cache_key]

        # Walk segments left-to-right; reuse the same occurrence_id at
        # every level so repeating groups stay coherent.
        current = section_el
        accumulated = ""
        for segment in path.split("."):
            if not segment:
                continue
            accumulated = (
                f"{accumulated}.{segment}" if accumulated else segment
            )
            sub_key = (accumulated, occurrence_id)
            existing = cache.get(sub_key)
            if existing is not None:
                current = existing
                continue
            container = SubElement(current, f"{{{NEMSIS_NS}}}{segment}")
            cache[sub_key] = container
            current = container

        cache[cache_key] = current
        return current

    def _emit_row_element(self, parent: Element, row: dict[str, Any]) -> None:
        element_number = row["element_number"]
        attributes = row.get("attributes") or {}
        value = row.get("value")

        el = SubElement(parent, f"{{{NEMSIS_NS}}}{element_number}")

        # NV (NOT value) -> NEMSIS NV attribute on the element.
        nv = attributes.get("NV")
        if nv:
            el.set("NV", str(nv))

        # PN (Pertinent Negative) -> NEMSIS PN attribute on the element.
        pn = attributes.get("PN")
        if pn:
            el.set("PN", str(pn))

        # xsi:nil -> XSI nil attribute, empty text.
        xsi_nil = attributes.get("xsiNil") or attributes.get("xsi_nil")
        if xsi_nil:
            el.set(f"{{{NEMSIS_XSI}}}nil", "true")
            return

        # Pass-through extra attributes (e.g. CorrelationID, dateTime
        # qualifiers) verbatim, except the structural sidecars above.
        for key, val in attributes.items():
            if key in {"NV", "PN", "xsiNil", "xsi_nil"}:
                continue
            if val is None or val == "":
                continue
            el.set(str(key), str(val))

        if value is None:
            return
        if isinstance(value, (list, tuple)):
            # Coerce list into space-separated tokens; NEMSIS list types
            # (xs:NMTOKENS, IsoCountrySubdivisionCodeUSAList, etc.)
            # serialize this way per XSD.
            el.text = " ".join(str(v) for v in value if v is not None)
        else:
            el.text = str(value)


__all__ = [
    "NemsisDatasetXmlBuilder",
    "DatasetArtifact",
    "DatasetBuildResult",
    "DatasetBuildError",
    "DATASET_ROOT_ELEMENT",
]
