from __future__ import annotations

"""Load official NEMSIS vertical-slice source artifacts from the repository workspace."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final
import copy
import re
import xml.etree.ElementTree as ET


SUPPORTED_CASE_ID: Final[str] = "2025-EMS-1-Allergy_v351"
SUPPORTED_DEM_ID: Final[str] = "2025-DEM-1_v351"
SUPPORTED_STATE_ID: Final[str] = "2025-STATE-1_v351"
LOCKED_TACTICAL_TEST_KEY: Final[str] = "351-241102-005-1"
LOCKED_FALLBACK_AGENCY_NAME: Final[str] = "Okaloosa County Emergency Medical Services"


class UnsupportedTemplateCaseError(ValueError):
    """Raised when a caller requests a case outside the locked vertical slice."""


@dataclass(frozen=True)
class OfficialTemplatePaths:
    """Absolute paths for the authoritative Allergy vertical-slice assets."""

    case_id: str
    vendor_html_path: Path
    dem_vendor_html_path: Path
    ems_xml_path: Path
    dem_xml_path: Path
    state_xml_path: Path


@dataclass(frozen=True)
class LoadedOfficialTemplate:
    """Loaded authoritative source documents for the Allergy vertical slice."""

    paths: OfficialTemplatePaths
    ems_root: ET.Element
    dem_root: ET.Element
    state_root: ET.Element
    vendor_html_text: str
    dem_vendor_html_text: str
    vendor_tac_key: str

    def copy_ems_root(self) -> ET.Element:
        """Return a deep copy of the official EMS template tree for safe mutation."""

        return copy.deepcopy(self.ems_root)


class OfficialTemplateLoader:
    """Resolve and load the single supported official CTA case from workspace assets."""

    def __init__(self, service_root: Path | None = None, workspace_root: Path | None = None) -> None:
        """Initialize loader paths rooted at the EPCR service workspace.

        Args:
            service_root: Optional repository root for `Adaptix-EPCR-Service`.
            workspace_root: Optional parent workspace containing sibling repositories.

        Returns:
            None.

        Raises:
            FileNotFoundError: If the official artifact directories cannot be located.
        """

        resolved_file = Path(__file__).resolve()
        self._service_root = service_root or resolved_file.parents[3]
        self._workspace_root = workspace_root or self._service_root.parent
        self._vendor_dir = (
            self._service_root
            / "nemsis_test"
            / "assets"
            / "cta"
            / "cta_uploaded_package"
            / "v3.5.1 C&S for vendors"
        )
        self._core_upload_dir = self._workspace_root / "Adaptix-Core-Service" / "cta_upload"
        if not self._vendor_dir.exists():
            raise FileNotFoundError(f"Vendor CTA asset directory not found: {self._vendor_dir}")
        if not self._core_upload_dir.exists():
            raise FileNotFoundError(f"Core CTA upload directory not found: {self._core_upload_dir}")

    def get_paths(self, case_id: str = SUPPORTED_CASE_ID) -> OfficialTemplatePaths:
        """Resolve the locked official Allergy case artifact paths.

        Args:
            case_id: Requested case identifier.

        Returns:
            OfficialTemplatePaths for the supported case.

        Raises:
            UnsupportedTemplateCaseError: If the case identifier is not the locked Allergy case.
            FileNotFoundError: If any authoritative source asset is missing.
        """

        if case_id != SUPPORTED_CASE_ID:
            raise UnsupportedTemplateCaseError(
                f"Unsupported case '{case_id}'. Only '{SUPPORTED_CASE_ID}' is allowed for this vertical slice."
            )

        paths = OfficialTemplatePaths(
            case_id=case_id,
            vendor_html_path=self._vendor_dir / f"{SUPPORTED_CASE_ID}.html",
            dem_vendor_html_path=self._vendor_dir / f"{SUPPORTED_DEM_ID}.html",
            ems_xml_path=self._core_upload_dir / f"{SUPPORTED_CASE_ID}.xml",
            dem_xml_path=self._core_upload_dir / f"{SUPPORTED_DEM_ID}.xml",
            state_xml_path=self._vendor_dir / f"{SUPPORTED_STATE_ID}.xml",
        )
        for candidate in (
            paths.vendor_html_path,
            paths.dem_vendor_html_path,
            paths.ems_xml_path,
            paths.dem_xml_path,
            paths.state_xml_path,
        ):
            if not candidate.exists():
                raise FileNotFoundError(f"Official vertical-slice artifact not found: {candidate}")
        return paths

    def load(self, case_id: str = SUPPORTED_CASE_ID) -> LoadedOfficialTemplate:
        """Load authoritative XML and vendor HTML documents for the Allergy slice.

        Args:
            case_id: Requested case identifier.

        Returns:
            LoadedOfficialTemplate with parsed XML roots and extracted TAC key.

        Raises:
            ValueError: If the vendor HTML TAC key cannot be found or mismatches the locked case key.
            ET.ParseError: If any XML artifact is malformed.
        """

        paths = self.get_paths(case_id)
        vendor_html_text = paths.vendor_html_path.read_text(encoding="utf-8")
        dem_vendor_html_text = paths.dem_vendor_html_path.read_text(encoding="utf-8")
        vendor_tac_key = self._extract_vendor_tac_key(vendor_html_text)
        if vendor_tac_key != LOCKED_TACTICAL_TEST_KEY:
            raise ValueError(
                "Vendor HTML TAC key mismatch for the official Allergy case: "
                f"expected {LOCKED_TACTICAL_TEST_KEY}, found {vendor_tac_key}."
            )

        return LoadedOfficialTemplate(
            paths=paths,
            ems_root=ET.parse(paths.ems_xml_path).getroot(),
            dem_root=ET.parse(paths.dem_xml_path).getroot(),
            state_root=ET.parse(paths.state_xml_path).getroot(),
            vendor_html_text=vendor_html_text,
            dem_vendor_html_text=dem_vendor_html_text,
            vendor_tac_key=vendor_tac_key,
        )

    @staticmethod
    def _extract_vendor_tac_key(vendor_html_text: str) -> str:
        """Extract the required `eResponse.04` TAC key from the vendor HTML source.

        Args:
            vendor_html_text: Raw vendor HTML document contents.

        Returns:
            The extracted TAC test key.

        Raises:
            ValueError: If the expected TAC key cannot be found.
        """

        match = re.search(r"eResponse\.04</td>\s*<td[^>]*>([^<]+)</td>", vendor_html_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"351-241102-005-1", vendor_html_text)
        if match:
            return match.group(0)
        raise ValueError("Unable to locate eResponse.04 TAC key in the official vendor HTML asset.")

    @staticmethod
    def collect_repeated_group_counts(root: ET.Element) -> dict[str, int]:
        """Count repeating element groups so downstream code can prove structure preservation.

        Args:
            root: XML root to analyze.

        Returns:
            Mapping of fully qualified tag names to counts for tags repeated more than once.
        """

        counts: dict[str, int] = {}
        for element in root.iter():
            counts[element.tag] = counts.get(element.tag, 0) + 1
        return {tag: count for tag, count in counts.items() if count > 1}
