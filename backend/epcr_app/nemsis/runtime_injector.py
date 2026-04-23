from __future__ import annotations

"""Inject runtime values into the locked official Allergy EMS template without altering structure."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable
from uuid import uuid4
import xml.etree.ElementTree as ET

from .dem_resolver import ResolvedDemographics
from .template_loader import LOCKED_TACTICAL_TEST_KEY


NEMSIS_NS = {"nem": "http://www.nemsis.org", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
XMLNS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


@dataclass(frozen=True)
class RuntimeInjectionContext:
    """Runtime values injected into the official Allergy EMS template."""

    demographics: ResolvedDemographics
    patient_care_report_number: str = "PCR-ALLERGY-2025-0001"
    software_creator: str = "Adaptix EPCR Service"
    software_name: str = "Adaptix EPCR Allergy CTA Slice"
    software_version: str = "3.5.1"
    timestamp_utc: datetime | None = None

    @property
    def resolved_timestamp(self) -> datetime:
        """Return a timezone-aware timestamp for deterministic runtime injection.

        Args:
            None.

        Returns:
            A UTC timestamp used for runtime field substitution.
        """

        return self.timestamp_utc or datetime.now(UTC)


class RuntimeValueInjector:
    """Apply runtime values to the official Allergy EMSDataSet template."""

    def apply(self, root: ET.Element, context: RuntimeInjectionContext) -> ET.Element:
        """Inject runtime metadata while preserving official ordering, NV, and PN semantics.

        Args:
            root: EMSDataSet XML root to mutate.
            context: Resolved runtime data.

        Returns:
            The mutated EMSDataSet root.

        Raises:
            ValueError: If a required target element is missing from the official template.
        """

        self._replace_uuid_placeholders(root)
        self._set_text(root, ".//nem:eResponse.04", LOCKED_TACTICAL_TEST_KEY)
        self._replace_placeholders(root, context)
        return root

    def _replace_uuid_placeholders(self, root: ET.Element) -> None:
        """Replace UUID attributes only when the official template contains a UUID placeholder.

        Args:
            root: EMSDataSet XML root.

        Returns:
            None.
        """

        for element in root.iter():
            for attr_name, attr_value in list(element.attrib.items()):
                if "[Your UUID]" not in attr_value:
                    continue
                element.attrib[attr_name] = attr_value.replace("[Your UUID]", str(uuid4()).upper())

    def _replace_placeholders(self, root: ET.Element, context: RuntimeInjectionContext) -> None:
        """Replace any explicit official placeholder tokens that remain in text or attributes.

        Args:
            root: EMSDataSet XML root.
            context: Runtime value context.

        Returns:
            None.
        """

        placeholder_map = {
            "[Your Patient Care Report Number]": context.patient_care_report_number,
            "[Your Software Creator]": context.software_creator,
            "[Your Software Name]": context.software_name,
            "[Your Software Version]": context.software_version,
            "[Your Timestamp]": context.resolved_timestamp.isoformat().replace("+00:00", "Z"),
            "[Agency Name]": context.demographics.agency_name,
            "[Software Creator]": context.software_creator,
            "[Software Name]": context.software_name,
            "[Software Version]": context.software_version,
        }
        for element in root.iter():
            if element.text:
                element.text = self._replace_tokens(element.text, placeholder_map)
            if element.tail:
                element.tail = self._replace_tokens(element.tail, placeholder_map)
            for attr_name, attr_value in list(element.attrib.items()):
                element.attrib[attr_name] = self._replace_tokens(attr_value, placeholder_map)

    @staticmethod
    def find_unresolved_placeholders(root: ET.Element) -> list[str]:
        """Collect unresolved square-bracket placeholders still present after injection.

        Args:
            root: EMSDataSet XML root.

        Returns:
            Sorted unique placeholder snippets still present in the document.
        """

        leftovers: set[str] = set()
        for value in RuntimeValueInjector._iter_text_and_attributes(root):
            if "[" not in value or "]" not in value:
                continue
            for fragment in value.split("["):
                if "]" not in fragment:
                    continue
                leftovers.add("[" + fragment.split("]", 1)[0] + "]")
        return sorted(leftovers)

    @staticmethod
    def _iter_text_and_attributes(root: ET.Element) -> Iterable[str]:
        """Yield all text and attribute values from the XML tree.

        Args:
            root: XML root.

        Returns:
            Iterator of textual values.
        """

        for element in root.iter():
            if element.text:
                yield element.text
            if element.tail:
                yield element.tail
            for attr_value in element.attrib.values():
                yield attr_value

    @staticmethod
    def _replace_tokens(value: str, placeholder_map: dict[str, str]) -> str:
        """Replace exact placeholder tokens in a string.

        Args:
            value: Source string.
            placeholder_map: Replacement mapping.

        Returns:
            Updated string with known placeholders replaced.
        """

        updated = value
        for placeholder, replacement in placeholder_map.items():
            updated = updated.replace(placeholder, replacement)
        return updated

    @staticmethod
    def _set_text(root: ET.Element, xpath: str, value: str) -> None:
        """Set a required element text value and clear incompatible nil/not-value attributes.

        Args:
            root: XML root.
            xpath: Namespaced XPath expression.
            value: Text value to write.

        Returns:
            None.

        Raises:
            ValueError: If the required target element is missing.
        """

        node = root.find(xpath, NEMSIS_NS)
        if node is None:
            raise ValueError(f"Required official template field missing for XPath: {xpath}")
        node.text = value
        node.attrib.pop("NV", None)
        node.attrib.pop("PN", None)
        node.attrib.pop(f"{{{XMLNS_XSI}}}nil", None)
