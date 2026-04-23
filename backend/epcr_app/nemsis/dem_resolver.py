from __future__ import annotations

"""Resolve authoritative DEM and state-reference values for the Allergy vertical slice."""

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET

from .template_loader import LOCKED_FALLBACK_AGENCY_NAME


NEMSIS_NS = {"nem": "http://www.nemsis.org"}


@dataclass(frozen=True)
class ResolvedDemographics:
    """Resolved demographic identifiers and agency descriptors used during export."""

    agency_id: str
    agency_number: str
    agency_state_code: str | None
    agency_state_name: str
    agency_name: str


class DemographicResolver:
    """Resolve DEM values while preserving raw source semantics and safe fallbacks."""

    def resolve(
        self,
        dem_root: ET.Element,
        state_root: ET.Element,
        dem_vendor_html_text: str | None = None,
        ems_root: ET.Element | None = None,
    ) -> ResolvedDemographics:
        """Resolve agency identifiers, state semantics, and fallback agency name.

        Args:
            dem_root: Parsed DEMDataSet root element.
            state_root: Parsed StateDataSet root element.
            dem_vendor_html_text: Optional official DEM vendor HTML text used to preserve semantic labels.
            ems_root: Optional official EMS root used to preserve agency display text.

        Returns:
            ResolvedDemographics with preserved identifiers and fallback-safe naming.

        Raises:
            ValueError: If required DEM values are missing.
        """

        agency_id = self._read_required_text(dem_root, ".//nem:dAgency.01")
        agency_number = self._read_required_text(dem_root, ".//nem:dAgency.02")
        agency_state_code = self._read_required_text(dem_root, ".//nem:dAgency.04")
        agency_state_name = self._resolve_agency_state_name(
            dem_root=dem_root,
            dem_vendor_html_text=dem_vendor_html_text,
        )
        agency_name = self._resolve_agency_name(
            dem_root=dem_root,
            state_root=state_root,
            agency_number=agency_number,
            ems_root=ems_root,
        )

        return ResolvedDemographics(
            agency_id=agency_id,
            agency_number=agency_number,
            agency_state_code=agency_state_code,
            agency_state_name=agency_state_name,
            agency_name=agency_name,
        )

    def _resolve_agency_name(
        self,
        *,
        dem_root: ET.Element,
        state_root: ET.Element,
        agency_number: str,
        ems_root: ET.Element | None,
    ) -> str:
        """Resolve the agency display name without altering the official coded fields.

        Args:
            dem_root: Parsed DEMDataSet root element.
            state_root: Parsed StateDataSet root element.
            agency_number: Agency number from DEM.
            ems_root: Optional official EMS root.

        Returns:
            Agency display name sourced from the official EMS file when available.
        """

        if ems_root is not None:
            official_response_name = self._read_optional_text(ems_root, ".//nem:eResponse.02")
            if official_response_name:
                return official_response_name
        return self._read_optional_text(dem_root, ".//nem:dAgency.03") or self._resolve_state_fallback_name(
            state_root=state_root,
            agency_number=agency_number,
        )

    def _resolve_state_fallback_name(self, state_root: ET.Element, agency_number: str) -> str:
        """Resolve agency name from StateDataSet, falling back to the locked safe value.

        Args:
            state_root: Parsed StateDataSet root element.
            agency_number: Agency number from DEM.

        Returns:
            Matching state agency name or the locked fallback agency name.
        """

        for group in state_root.findall(".//nem:sAgencyGroup", NEMSIS_NS):
            state_agency_number = self._read_optional_text(group, "./nem:sAgency.02")
            if state_agency_number != agency_number:
                continue
            agency_name = self._read_optional_text(group, "./nem:sAgency.03")
            if agency_name:
                return agency_name
        return LOCKED_FALLBACK_AGENCY_NAME

    def _resolve_agency_state_name(self, dem_root: ET.Element, dem_vendor_html_text: str | None) -> str:
        """Resolve the semantic state name, preferring the official vendor HTML label.

        Args:
            dem_root: Parsed DEMDataSet root element.
            dem_vendor_html_text: Optional official vendor HTML text.

        Returns:
            The semantic state name, such as `Florida`.

        Raises:
            ValueError: If no resolvable state label is available.
        """

        if dem_vendor_html_text:
            html_match = re.search(
                r"dAgency\.04.*?<td>([^<]+)</td>",
                dem_vendor_html_text,
                re.IGNORECASE | re.DOTALL,
            )
            if html_match:
                semantic_name = html_match.group(1).strip()
                if semantic_name:
                    return semantic_name
        return self._read_required_text(dem_root, ".//nem:dAgency.04")

    @staticmethod
    def _read_required_text(root: ET.Element, xpath: str) -> str:
        """Read a required namespaced element text value.

        Args:
            root: XML context node.
            xpath: XPath expression.

        Returns:
            Stripped text value.

        Raises:
            ValueError: If the node is missing or empty.
        """

        node = root.find(xpath, NEMSIS_NS)
        text = (node.text or "").strip() if node is not None else ""
        if not text:
            raise ValueError(f"Required DEM value missing for XPath: {xpath}")
        return text

    @staticmethod
    def _read_optional_text(root: ET.Element, xpath: str) -> str | None:
        """Read an optional namespaced element text value.

        Args:
            root: XML context node.
            xpath: XPath expression.

        Returns:
            Stripped text value if present, otherwise `None`.
        """

        node = root.find(xpath, NEMSIS_NS)
        if node is None or node.text is None:
            return None
        value = node.text.strip()
        return value or None
