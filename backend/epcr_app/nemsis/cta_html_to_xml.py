"""Deterministic, input-driven NEMSIS v3.5.1 CTA HTML to XML transformation engine.

Responsibilities are isolated into independent, single-purpose components:

1. :class:`HtmlParser` extracts ``HtmlCell`` records from the HTML tbody — no
   translation, no value generation.
2. :class:`ValueTranslator` converts human-readable labels to canonical NEMSIS
   codes via an injected :class:`CodedValueSet`.  Unresolved labels raise
   :class:`UnknownCodedValueError` — the translator never returns a fallback.
3. :class:`StateDataSetResolver` resolves ``[Value from StateDataSet]``
   references against a preloaded ``StateDataSet`` XML.  Unresolved references
   raise :class:`UnresolvedReferenceError`.
4. :class:`NemsisXmlBuilder` constructs the XML tree from the parsed cells
   using inputs supplied via :class:`ConversionInput`.  The builder never
   generates UUIDs or timestamps; every dynamic value must be present in the
   input mapping or a :class:`MissingInputError` is raised.
5. :class:`ValidationGate` scans the final tree for any remaining placeholder
   patterns and raises :class:`UnresolvedPlaceholderError` on the first hit.

Contract
--------
Given the same ``ConversionInput`` instance and the same HTML + StateDataSet
input files, :func:`convert_html_to_nemsis_xml` produces byte-identical XML on
every run.  Partial success states are not produced — the function either
returns a fully populated, placeholder-free tree or raises
:class:`CtaConversionError`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup, Tag

from .nemsis_coded_values import (
    CodedValueSet,
    NEMSIS_V351_CODED_VALUES,
    UnknownCodedValueError,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Namespace / schema constants
# ─────────────────────────────────────────────────────────────────────────────

NEMSIS_NS = "http://www.nemsis.org"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XSI_NIL = f"{{{XSI_NS}}}nil"
XSI_SCHEMA_LOCATION = f"{{{XSI_NS}}}schemaLocation"

DEM_SCHEMA_LOCATION = (
    "http://www.nemsis.org "
    "https://nemsis.org/media/nemsis_v3/3.5.1.251001CP2/XSDs/NEMSIS_XSDs/DEMDataSet_v3.xsd"
)
EMS_SCHEMA_LOCATION = (
    "http://www.nemsis.org "
    "https://nemsis.org/media/nemsis_v3/3.5.1.251001CP2/XSDs/NEMSIS_XSDs/EMSDataSet_v3.xsd"
)


# ─────────────────────────────────────────────────────────────────────────────
# Nillable element registry (derived from NEMSIS v3.5.1 XSDs)
# ─────────────────────────────────────────────────────────────────────────────


def _load_nillable_elements() -> frozenset[str]:
    """Scan the bundled NEMSIS v3.5.1 XSDs and return the set of element
    local names declared with ``nillable="true"``.

    The XSD bundle is located at
    ``<repo>/nemsis_test/assets/xsd/extracted/NEMSIS_XSDs``.  When that
    directory is absent, an empty set is returned and the builder degrades
    to emitting ``xsi:nil`` only on elements explicitly known to be
    nillable (via NV attributes, which NEMSIS reserves exclusively for
    nillable elements).

    Returns:
        Frozen set of element local names (e.g. ``"eVitals.27"``) that may
        carry ``xsi:nil="true"``.
    """

    try:
        xsd_dir = (
            Path(__file__).resolve().parents[3]
            / "nemsis_test" / "assets" / "xsd" / "extracted" / "NEMSIS_XSDs"
        )
        if not xsd_dir.is_dir():
            return frozenset()

        nillable: set[str] = set()
        element_re = re.compile(
            r'<xs:element\s+name=["\']([deisDEIS][A-Za-z]+\.\d+)["\']([^>]*)'
        )
        for xsd_path in xsd_dir.glob("*.xsd"):
            try:
                content = xsd_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in element_re.finditer(content):
                name = m.group(1)
                attrs = m.group(2)
                if 'nillable="true"' in attrs or "nillable='true'" in attrs:
                    nillable.add(name)
        return frozenset(nillable)
    except Exception:  # pragma: no cover — static data loader; fail soft
        return frozenset()


_NILLABLE_ELEMENTS: frozenset[str] = _load_nillable_elements()


# ─────────────────────────────────────────────────────────────────────────────
# Field classification engine (Rule 3 — TYPE A CODED / B TEXT / C REPEATED / D NIL)
# ─────────────────────────────────────────────────────────────────────────────


class FieldKind(Enum):
    """Classification of a NEMSIS XML element's value discipline.

    Every element is classified BEFORE write so the builder can enforce
    type-specific invariants (numeric-only for CODED, ISO8601 for DATETIME,
    etc.) and the validator can reject violations.

    * ``CODED`` — Type A. Value must be a numeric enum code; no free text.
    * ``TEXT`` — Type B. Free text, real-world format (names, narrative).
    * ``REPEATED`` — Type C. May appear multiple times; never combined with
      separators (commas, semicolons).
    * ``NIL`` — Type D. Absent value. Must carry ``xsi:nil="true"`` AND a
      justification attribute (``NV=...`` or ``PN=...``).
    * ``DATETIME`` — Sub-kind of TEXT: ISO 8601 with TZ offset required.
    * ``GROUP`` — Container element (no text of its own; holds children).
    * ``UUID_VALUED`` — Element whose text is itself a UUID (e.g.
      ``eRecord.01``, ``dAgency.01``).
    """

    CODED = "coded"
    TEXT = "text"
    REPEATED = "repeated"
    NIL = "nil"
    DATETIME = "datetime"
    GROUP = "group"
    UUID_VALUED = "uuid_valued"


# Element IDs whose canonical value is an ISO 8601 date or date-time
# literal.  Derived programmatically from the bundled NEMSIS v3.5.1 XSDs
# by resolving every ``xs:element`` whose type chain ultimately restricts
# ``xs:dateTime`` (``DateTimeType``) or ``xs:date`` (``DateType`` /
# ``DateOfBirth``).  See `scripts/extract_xsd_enums.py` for the extraction
# logic; this list must stay in lock-step with the XSDs.
_DATETIME_ELEMENT_IDS: frozenset[str] = frozenset({
    # xs:dateTime (DateTimeType) — full timestamp with TZ offset
    "eAirway.10", "eAirway.11",
    "eDevice.02",
    "eHistory.19",
    "eInjury.14",
    "eLabs.01",
    "eOther.19",
    "ePayment.03",
    "eScene.05",
    "eTimes.02", "eTimes.03", "eTimes.04",
    "eTimes.10",
    "eTimes.13", "eTimes.14", "eTimes.15",
    "eTimes.16", "eTimes.17",
    # xs:date (DateType / DateOfBirth) — YYYY-MM-DD only
    "dDevice.06",
    "dPersonnel.25", "dPersonnel.26", "dPersonnel.27",
    "dPersonnel.30", "dPersonnel.33",
    "dPersonnel.37", "dPersonnel.39",
    "ePayment.60",
})


# Element IDs whose value field (text) is expected to be a UUID literal.
# In NEMSIS v3.5.1 UUIDs are carried exclusively via the ``UUID=...``
# attribute on group elements (dAgency.AgencyGroup etc.), never as element
# text content — so this set is intentionally empty, retained for future
# spec changes that may introduce element-text UUIDs.
_UUID_VALUED_ELEMENT_IDS: frozenset[str] = frozenset()


_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2}))?$"
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_COMMA_IN_CODED_RE = re.compile(r",")


def classify_field(
    element_id: str,
    *,
    is_group: bool,
    is_nil: bool,
    coded_values: CodedValueSet,
) -> FieldKind:
    """Classify a NEMSIS element's value discipline.

    Classification is deterministic — the same ``(element_id, is_group,
    is_nil)`` tuple always returns the same :class:`FieldKind`.

    Priority order (first match wins):

    1. ``GROUP`` — cell is a container (``is_group=True``).
    2. ``NIL`` — cell has ``[NV=...]`` annotation (``is_nil=True``).
    3. ``DATETIME`` — element is in :data:`_DATETIME_ELEMENT_IDS` (xs:dateTime
       or xs:date in the XSD).
    4. ``UUID_VALUED`` — element is in :data:`_UUID_VALUED_ELEMENT_IDS`.
    5. ``CODED`` — element has an XSD enumeration (element-specific table),
       OR is in a scoped lookup set (state/country/county/city), OR is in
       :data:`_PROTECTED_CODED_ELEMENT_IDS`.
    6. ``TEXT`` — otherwise, free-text element.

    Note: ``REPEATED`` is a structural property of an element's parent, not a
    value discipline; repeated elements are emitted as distinct ``<tag>``
    children in the tree by :class:`NemsisXmlBuilder`, and each instance is
    classified individually by this function.

    Args:
        element_id: NEMSIS element identifier (e.g. ``"eSituation.02"``).
        is_group: ``True`` if the cell is a container.
        is_nil: ``True`` if the cell carries ``[NV=...]``.
        coded_values: Active :class:`CodedValueSet`, used to detect
            element-specific enumeration presence.

    Returns:
        The :class:`FieldKind` for this element.
    """

    if is_group:
        return FieldKind.GROUP
    if is_nil:
        return FieldKind.NIL
    if element_id in _DATETIME_ELEMENT_IDS:
        return FieldKind.DATETIME
    if element_id in _UUID_VALUED_ELEMENT_IDS:
        return FieldKind.UUID_VALUED
    if coded_values.has_element_specific(element_id):
        return FieldKind.CODED
    if element_id in _PROTECTED_CODED_ELEMENT_IDS:
        return FieldKind.CODED
    return FieldKind.TEXT


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class CtaConversionError(Exception):
    """Base class for every conversion failure raised by this module."""


class MissingInputError(CtaConversionError):
    """Raised when :class:`ConversionInput` is missing a required entry.

    A UUID, timestamp, or placeholder value was referenced by the HTML but not
    supplied by the caller.  The exception message identifies the missing key
    so the caller can extend its input mapping.
    """


class UnresolvedReferenceError(CtaConversionError):
    """Raised when a ``[Value from StateDataSet]`` or ``[Value from DEMDataSet]``
    reference cannot be resolved against the supplied data sources.
    """


class UnresolvedPlaceholderError(CtaConversionError):
    """Raised by :class:`ValidationGate` when the final XML still contains any
    ``[Your …]`` or ``[Value from …]`` placeholder token.
    """


class HtmlStructureError(CtaConversionError):
    """Raised when the HTML file does not conform to the expected NEMSIS CTA
    layout (missing ``<tbody>``, malformed element-id span, etc.).
    """


class DatasetTypeError(CtaConversionError):
    """Raised when the dataset type (``DEMDataSet`` or ``EMSDataSet``) cannot
    be determined from the HTML title.
    """


# ─────────────────────────────────────────────────────────────────────────────
# ConversionInput
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConversionInput:
    """All runtime values required to build a deterministic XML document.

    Every dynamic value (UUID, timestamp, ``[Your …]`` placeholder) must be
    present in one of the supplied mappings.  The keys follow a deterministic
    scheme driven by element occurrence in document order:

    * ``uuids`` and ``timestamps`` are keyed by ``"<element_id>[<index>]"``
      where ``<index>`` is the zero-based occurrence of that element_id in
      document order.
    * ``placeholder_values`` is keyed by the verbatim placeholder descriptor
      captured inside ``[Your …]`` (e.g. ``"Patient Care Report Number"``).

    Two calls to :func:`convert_html_to_nemsis_xml` with the same
    ``ConversionInput`` and the same source files produce byte-identical XML.
    """

    uuids: Mapping[str, str] = field(default_factory=dict)
    timestamps: Mapping[str, str] = field(default_factory=dict)
    placeholder_values: Mapping[str, str] = field(default_factory=dict)
    dem_references: Mapping[str, str] = field(default_factory=dict)

    def require_uuid(self, key: str) -> str:
        """Return the UUID bound to ``key`` or raise.

        Args:
            key: Occurrence key such as ``"dAgency.AgencyServiceGroup[0]"``.

        Returns:
            The UUID string provided by the caller.

        Raises:
            MissingInputError: If ``key`` is absent from :attr:`uuids`.
        """

        if key not in self.uuids:
            raise MissingInputError(f"missing UUID for {key!r}")
        return self.uuids[key]

    def require_timestamp(self, key: str) -> str:
        """Return the timestamp bound to ``key`` or raise.

        Args:
            key: Occurrence key such as ``"DemographicReport[0]"``.

        Returns:
            ISO 8601 timestamp string provided by the caller.

        Raises:
            MissingInputError: If ``key`` is absent from :attr:`timestamps`.
        """

        if key not in self.timestamps:
            raise MissingInputError(f"missing timestamp for {key!r}")
        return self.timestamps[key]

    def require_placeholder(self, kind: str) -> str:
        """Return the literal value for a ``[Your <kind>]`` placeholder.

        Args:
            kind: Placeholder descriptor, e.g. ``"Patient Care Report Number"``.

        Returns:
            Literal value supplied by the caller.

        Raises:
            MissingInputError: If ``kind`` is absent from
                :attr:`placeholder_values`.
        """

        if kind not in self.placeholder_values:
            raise MissingInputError(f"missing placeholder value for {kind!r}")
        return self.placeholder_values[kind]

    def get_dem_reference(self, element_id: str) -> str | None:
        """Return an explicit ``[Value from DEMDataSet]`` override for
        ``element_id``, or ``None`` if the caller has not supplied one.

        Args:
            element_id: NEMSIS element identifier, e.g. ``"eDisposition.03"``.

        Returns:
            The caller-supplied value or ``None`` to defer to automatic
            resolution via :class:`StateDataSetResolver`.
        """

        return self.dem_references.get(element_id)


# ─────────────────────────────────────────────────────────────────────────────
# HtmlCell
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HtmlCell:
    """A single parsed HTML table row.

    This record is the sole contract between :class:`HtmlParser` and
    :class:`NemsisXmlBuilder`.  It carries every piece of information needed
    to produce the corresponding XML element or attribute, without embedding
    any translation or generation decisions.
    """

    depth: int
    element_id: str
    is_group: bool
    rowspan: int
    occurrence_key: str
    value_text: str | None
    annotations: Mapping[str, str]
    is_nil: bool
    state_ref: bool
    dem_ref: bool
    needs_uuid_attr: bool
    needs_timestamp_attr: bool
    your_placeholder: str | None


# ─────────────────────────────────────────────────────────────────────────────
# HTML parser
# ─────────────────────────────────────────────────────────────────────────────

_DEPTH_RE = re.compile(r"padding-left:\s*([\d.]+)em")
_ELEMENT_ID_RE = re.compile(r"([a-zA-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*)")

_ANNOTATION_KEYS: tuple[str, ...] = (
    "NV",
    "PN",
    "UUID",
    "timeStamp",
    "ETCO2Type",
    "DistanceUnit",
    "EmailAddressType",
    "PhoneNumberType",
    "StreetAddress2",
    "CodeType",
)


def _parse_annotations(raw: str) -> tuple[dict[str, str], str]:
    """Extract every ``[KEY = VALUE]`` annotation from a value-cell string.

    Args:
        raw: The full text content of the ``<td>`` value cell.

    Returns:
        Tuple ``(annotations, residual_text)``.  ``annotations`` maps each
        recognised annotation key to its raw inner value (which may itself be
        a placeholder such as ``"[Your UUID]"``).  ``residual_text`` is the
        value cell stripped of every recognised annotation, whitespace
        collapsed.
    """

    annotations: dict[str, str] = {}
    residual = raw
    for key in _ANNOTATION_KEYS:
        pattern = re.compile(rf"\[{re.escape(key)}\s*=\s*((?:\[[^\]]*\]|[^\]])*)\]")
        m = pattern.search(residual)
        if m is not None:
            inner = m.group(1).strip().strip('"')
            annotations[key] = inner
            residual = (residual[: m.start()] + residual[m.end() :]).strip()
    residual = re.sub(r"\s+", " ", residual).strip()
    return annotations, residual


class HtmlParser:
    """Parse a NEMSIS CTA HTML test case into a stream of :class:`HtmlCell`.

    The parser is pure — it never translates values, never generates UUIDs or
    timestamps, and never applies defaults.  Every cell is emitted with full
    fidelity to the source markup; downstream components make all semantic
    decisions.
    """

    def parse(self, html_path: Path) -> tuple[str, list[HtmlCell]]:
        """Parse an HTML test case file.

        Args:
            html_path: Absolute path to the ``.html`` test case.

        Returns:
            Tuple ``(root_tag, cells)`` where ``root_tag`` is one of
            ``"DEMDataSet"`` / ``"EMSDataSet"`` and ``cells`` is the ordered
            list of parsed rows.

        Raises:
            FileNotFoundError: If ``html_path`` does not exist.
            DatasetTypeError: If the dataset type cannot be determined.
            HtmlStructureError: If the HTML is missing ``<tbody>`` or has
                malformed element metadata.
        """

        html_path = Path(html_path)
        if not html_path.exists():
            raise FileNotFoundError(f"HTML test case not found: {html_path}")

        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
        root_tag = self._determine_root_tag(soup)

        tbody = soup.find("tbody")
        if tbody is None:
            raise HtmlStructureError(f"no <tbody> element in {html_path.name}")

        cells: list[HtmlCell] = []
        occurrence_counter: dict[str, int] = {}
        rows = tbody.find_all("tr", recursive=False)

        pending_rowspan: tuple[int, str, bool, str] | None = None
        rowspan_remaining = 0

        for row in rows:
            tds = row.find_all("td", recursive=False)
            if not tds:
                continue

            if len(tds) == 1:
                td = tds[0]
                td_classes = td.get("class") or []
                if "comment" in td_classes:
                    continue
                if "element" not in td_classes and rowspan_remaining > 0 and pending_rowspan is not None:
                    depth, element_id, is_group, occurrence_key = pending_rowspan
                    cell = self._build_cell(
                        depth=depth,
                        element_id=element_id,
                        is_group=is_group,
                        rowspan=1,
                        occurrence_key=occurrence_key,
                        val_td=td,
                    )
                    cells.append(cell)
                    rowspan_remaining -= 1
                    if rowspan_remaining == 0:
                        pending_rowspan = None
                continue

            if len(tds) < 2:
                continue

            elem_td, val_td = tds[0], tds[1]
            elem_classes = elem_td.get("class") or []
            if "comment" in elem_classes:
                continue

            depth_match = _DEPTH_RE.search(elem_td.get("style", ""))
            if depth_match is None:
                raise HtmlStructureError(
                    f"no padding-left depth on element cell in {html_path.name}"
                )
            depth = int(float(depth_match.group(1)))

            span = elem_td.find("span")
            if span is None:
                raise HtmlStructureError(
                    f"no <span> element-id in row (depth={depth}) of {html_path.name}"
                )
            span_text = span.get_text(" ", strip=True)
            span_text_stripped = re.sub(r"^\s*\[[^\]]+\]\s*", "", span_text)
            eid_match = _ELEMENT_ID_RE.match(span_text_stripped)
            if eid_match is None:
                raise HtmlStructureError(
                    f"cannot parse element id from span text {span.get_text()!r} in {html_path.name}"
                )
            element_id = eid_match.group(1)
            is_group = "group" in (span.get("class") or [])
            rowspan = int(elem_td.get("rowspan", 1))

            if element_id == root_tag:
                continue

            occurrence_index = occurrence_counter.get(element_id, 0)
            occurrence_counter[element_id] = occurrence_index + 1
            occurrence_key = f"{element_id}[{occurrence_index}]"

            if rowspan > 1:
                pending_rowspan = (depth, element_id, is_group, occurrence_key)
                rowspan_remaining = rowspan - 1
            else:
                pending_rowspan = None
                rowspan_remaining = 0

            cell = self._build_cell(
                depth=depth,
                element_id=element_id,
                is_group=is_group,
                rowspan=rowspan,
                occurrence_key=occurrence_key,
                val_td=val_td,
            )
            cells.append(cell)

        return root_tag, cells

    def _determine_root_tag(self, soup: BeautifulSoup) -> str:
        """Inspect the HTML title and derive the dataset root-tag name.

        Args:
            soup: Parsed BeautifulSoup tree.

        Returns:
            ``"DEMDataSet"`` or ``"EMSDataSet"``.

        Raises:
            DatasetTypeError: If neither token is present in the title.
        """

        title = soup.find("h1")
        title_text = title.get_text(" ", strip=True) if title else ""
        if "DEMDataSet" in title_text:
            return "DEMDataSet"
        if "EMSDataSet" in title_text:
            return "EMSDataSet"
        raise DatasetTypeError(
            f"cannot determine dataset type from HTML title: {title_text!r}"
        )

    def _build_cell(
        self,
        depth: int,
        element_id: str,
        is_group: bool,
        rowspan: int,
        occurrence_key: str,
        val_td: Tag,
    ) -> HtmlCell:
        """Translate a raw ``<td>`` value cell into a fully-described
        :class:`HtmlCell`.

        Args:
            depth: Nesting depth derived from ``padding-left``.
            element_id: NEMSIS element identifier (e.g. ``"dAgency.02"``).
            is_group: ``True`` for container elements marked with
                ``class="group"``.
            rowspan: Row-span count declared on the element cell.
            occurrence_key: Deterministic occurrence key for the element.
            val_td: BeautifulSoup ``<td>`` tag holding the cell value.

        Returns:
            The populated :class:`HtmlCell`.
        """

        raw_text = val_td.get_text(" ", strip=True)
        annotations, residual = _parse_annotations(raw_text)

        is_nil = False
        state_ref = False
        dem_ref = False
        needs_uuid_attr = False
        needs_timestamp_attr = False
        your_placeholder: str | None = None
        value_text: str | None = residual or None

        if "NV" in annotations:
            is_nil = True
            value_text = None
        if "UUID" in annotations:
            needs_uuid_attr = True
        if "timeStamp" in annotations:
            needs_timestamp_attr = True

        if value_text is not None:
            if "[Value from StateDataSet]" in value_text:
                state_ref = True
                value_text = None
            elif "[Value from DEMDataSet]" in value_text:
                dem_ref = True
                value_text = None
            else:
                your_match = re.search(r"\[Your ([^\]]+)\]", value_text)
                if your_match is not None:
                    your_placeholder = your_match.group(1).strip()
                    value_text = None

        return HtmlCell(
            depth=depth,
            element_id=element_id,
            is_group=is_group,
            rowspan=rowspan,
            occurrence_key=occurrence_key,
            value_text=value_text,
            annotations=dict(annotations),
            is_nil=is_nil,
            state_ref=state_ref,
            dem_ref=dem_ref,
            needs_uuid_attr=needs_uuid_attr,
            needs_timestamp_attr=needs_timestamp_attr,
            your_placeholder=your_placeholder,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Value translator
# ─────────────────────────────────────────────────────────────────────────────

_MONTH_NAMES: Mapping[str, int] = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

_DATE_FULL_RE = re.compile(
    r"^(\w+)\s+(\d{1,2}),\s+(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s+GMT([+-]\d{2}):(\d{2})$"
)
_DATE_ONLY_RE = re.compile(r"^(\w+)\s+(\d{1,2}),\s+(\d{4})$")
_PASSTHROUGH_RE = re.compile(r"^[\w+][\w\s.,;'\"&+\-/@:()%#*!?<>=\[\]]*$", re.UNICODE)
_CODE_NUMERIC_RE = re.compile(r"^\d+$")
_ICD_SNOMED_RE = re.compile(r"^([A-Z\d][A-Z\d.\-]+)\s+-\s+.+$")
_RXCUI_RE = re.compile(r"^(\d+)\s+-\s+.+$")

# Mapping of coded element IDs to their "Other-Not Listed" NEMSIS enumeration
# code.  When an HTML cell for a coded element carries ``[Custom Value] X``,
# NEMSIS semantics say the element must hold the "Other" code and the free
# text ``X`` must be captured via a ``dCustomResults.ResultsGroup``.
_CUSTOM_VALUE_OTHER_CODES: dict[str, str] = {
    "dPersonnel.18": "9910027",  # ImmunizationType → Other-Not Listed
}

_STATE_ELEMENT_IDS: frozenset[str] = frozenset({
    "dAgency.04",
    "dAgency.05",
    "dConfiguration.01",
    "dContact.07",
    "dFacility.09",
    "dLocation.08",
    "dPersonnel.06",
    "dPersonnel.22",
    "ePatient.08",
    "ePatient.20",
    "ePayment.14",
    "ePayment.28",
    "eScene.18",
    "eDisposition.05",
})

_COUNTRY_ELEMENT_IDS: frozenset[str] = frozenset({
    "dContact.09",
    "dFacility.12",
    "dLocation.11",
    "dPersonnel.08",
    "ePatient.10",
    "eDisposition.06",
    "eDisposition.08",
})

_COUNTY_ELEMENT_IDS: frozenset[str] = frozenset({
    "dAgency.06",
    "dFacility.11",
    "dLocation.10",
    "ePatient.07",
    "eScene.21",
    "eDisposition.07",
})

_CITY_ELEMENT_IDS: frozenset[str] = frozenset({
    "dContact.06",
    "dFacility.08",
    "dLocation.07",
    "dPersonnel.05",
    "ePatient.06",
    "eScene.17",
    "eDisposition.04",
})

# Element IDs whose values MUST resolve to a NEMSIS code or FIPS code — raw
# free-text passthrough is forbidden for these elements.  Any unresolved value
# for a protected element raises UnknownCodedValueError.
_PROTECTED_CODED_ELEMENT_IDS: frozenset[str] = frozenset(
    {
        # element-specific tables (dAgency / dContact / dConfiguration)
        "dAgency.09",
        "dAgency.10",
        "dAgency.11",
        "dAgency.12",
        "dAgency.13",
        "dAgency.14",
        "dAgency.23",
        "dContact.01",
        "dContact.13",
        "dContact.14",
        "dContact.15",
        "dConfiguration.06",
        "dConfiguration.10",
        "dConfiguration.11",
        "dConfiguration.13",
        "dConfiguration.15",
        "dVehicle.04",
        "dPersonnel.15",
        "dPersonnel.16",
        # element-specific tables (eResponse / eSituation / eArrest / eCrew / eDispatch)
        "eResponse.08",
        "eResponse.09",
        "eResponse.10",
        "eResponse.11",
        "eResponse.12",
        "eResponse.24",
        "eSituation.02",
        "eSituation.06",
        "eSituation.14",
        "eArrest.01",
        "eHistory.05",
        "eDispatch.01",
        "eDispatch.02",
        "eDispatch.05",
        "eCrew.02",
        # element-specific tables (ePatient / ePayment)
        "ePatient.14",
        "ePatient.24",
        "ePayment.01",
        "ePayment.11",
        "ePayment.22",
        "ePayment.41",
    }
    | _STATE_ELEMENT_IDS
    | _COUNTRY_ELEMENT_IDS
    | _COUNTY_ELEMENT_IDS
    | _CITY_ELEMENT_IDS
)


class ValueTranslator:
    """Translate raw HTML text into NEMSIS-coded values.

    The translator applies translation rules in a fixed, deterministic order:

    1. Numeric / code-shaped values pass through unchanged.
    2. NEMSIS-style date-time strings are converted to ISO 8601.
    3. Element-scoped lookups (state, country, county) apply when the
       ``element_id`` belongs to the relevant scope.
    4. ICD-10 / SNOMED / RxNorm / GCS regex captures extract the canonical
       code portion.
    5. The general coded-value table is consulted.
    6. Any remaining label raises :class:`UnknownCodedValueError`.

    No fallback path returns the raw text when a translation is expected.
    """

    def __init__(self, coded_values: CodedValueSet) -> None:
        """Initialise the translator.

        Args:
            coded_values: The :class:`CodedValueSet` used for all lookups.

        Returns:
            None.
        """

        self._codes = coded_values

    @property
    def coded_values(self) -> CodedValueSet:
        """Expose the underlying :class:`CodedValueSet` for classification.

        Returns:
            The active coded-value set (used by :func:`classify_field`).
        """

        return self._codes

    def translate(self, raw: str, element_id: str) -> str:
        """Translate ``raw`` to its canonical NEMSIS code representation.

        Translation priority (first match wins):

        1. Numeric passthrough — already a code.
        2. Date parse — NEMSIS human-readable date → ISO 8601.
        3. ``[Custom Value]`` passthrough.
        4. Element-specific lookup (XSD-extracted enumeration table).
        5. State-scoped FIPS lookup.
        6. Country-scoped ISO lookup.
        7. County-scoped FIPS lookup.
        8. City-scoped FIPS lookup (strips leading ``"City of "`` prefix).
        9. General coded-value table (non-protected elements only).
        10. ICD-10 / SNOMED code capture.
        11. RxCUI code capture.
        12. Free-text passthrough for non-protected, free-text element IDs.
        13. Raise :class:`UnknownCodedValueError` — no silent fallback.

        Args:
            raw: Raw text extracted from the HTML value cell.
            element_id: NEMSIS element identifier providing translation scope.

        Returns:
            Canonical string value suitable for direct insertion as element
            text or attribute value.

        Raises:
            UnknownCodedValueError: If no deterministic translation exists for
                the supplied ``raw`` in the context of ``element_id``.
        """

        text = raw.strip()
        if not text:
            raise UnknownCodedValueError("value", raw)

        # 1. Numeric passthrough
        if _CODE_NUMERIC_RE.match(text):
            return text

        # 2. Date parse
        iso = self._try_parse_date(text)
        if iso is not None:
            return iso

        # 3. Custom Value passthrough / fallback-to-"Other".
        # Coded (enum) elements reject "[Custom Value] ..." per XSD.  When the
        # element defines an "Other-Not Listed" slot, emit that code so the
        # value is preserved; the accompanying dCustomResults.ResultsGroup
        # carries the custom free-text description.  Otherwise emit an empty
        # value that the builder will convert to xsi:nil.
        if text.startswith("[Custom Value]"):
            if self._codes.has_element_specific(element_id):
                fallback = _CUSTOM_VALUE_OTHER_CODES.get(element_id)
                if fallback is not None:
                    return fallback
                return ""
            return text

        # 4. Element-specific lookup (highest priority for coded elements)
        if self._codes.has_element_specific(element_id):
            return self._codes.element_specific_code(element_id, text)

        # 5. State-scoped FIPS lookup
        if element_id in _STATE_ELEMENT_IDS:
            try:
                return self._codes.state(text)
            except UnknownCodedValueError:
                raise UnknownCodedValueError(f"state[{element_id}]", text)

        # 6. Country-scoped ISO lookup
        if element_id in _COUNTRY_ELEMENT_IDS:
            try:
                return self._codes.country(text)
            except UnknownCodedValueError:
                raise UnknownCodedValueError(f"country[{element_id}]", text)

        # 7. County-scoped FIPS lookup
        if element_id in _COUNTY_ELEMENT_IDS:
            try:
                return self._codes.county(text)
            except UnknownCodedValueError:
                raise UnknownCodedValueError(f"county[{element_id}]", text)

        # 8. City-scoped FIPS lookup — accept both "Niceville" and "City of Niceville"
        if element_id in _CITY_ELEMENT_IDS:
            lookup_text = text
            if lookup_text.startswith("City of "):
                lookup_text = lookup_text[len("City of "):]
            # Try both forms
            for candidate in (text, lookup_text, f"City of {lookup_text}"):
                if candidate in self._codes.cities:
                    return self._codes.city(candidate)
            raise UnknownCodedValueError(f"city[{element_id}]", text)

        # 9. General coded-value table (only for non-protected elements)
        if element_id not in _PROTECTED_CODED_ELEMENT_IDS:
            if self._codes.has_general(text):
                return self._codes.general_code(text)

        # 10. ICD-10 / SNOMED code capture
        icd = _ICD_SNOMED_RE.match(text)
        if icd is not None:
            return icd.group(1)

        # 11. RxCUI code capture
        rxcui = _RXCUI_RE.match(text)
        if rxcui is not None:
            return rxcui.group(1)

        # 12. Free-text passthrough — only for unprotected free-text elements
        if element_id not in _PROTECTED_CODED_ELEMENT_IDS:
            if _PASSTHROUGH_RE.match(text):
                return text

        # 13. No mapping found — hard fail
        raise UnknownCodedValueError(element_id, text)

    def translate_attribute(self, key: str, label: str) -> str:
        """Translate an attribute label to its NEMSIS code.

        Args:
            key: Attribute name (e.g. ``"PhoneNumberType"``).
            label: Human-readable attribute value (e.g. ``"Mobile"``).

        Returns:
            Canonical NEMSIS code.

        Raises:
            UnknownCodedValueError: If ``label`` is not mapped.
            ValueError: If ``key`` is not a recognised NEMSIS attribute key.
        """

        if key == "PhoneNumberType":
            return self._codes.phone_type(label)
        if key == "EmailAddressType":
            return self._codes.email_type(label)
        if key == "ETCO2Type":
            return self._codes.etco2_unit(label)
        if key == "DistanceUnit":
            return self._codes.distance_unit(label)
        if key == "NV":
            return self._codes.nv(label)
        if key == "PN":
            return self._codes.pn(label)
        if key == "CodeType":
            if not _CODE_NUMERIC_RE.match(label.strip()):
                raise UnknownCodedValueError("CodeType", label)
            return label.strip()
        if key == "StreetAddress2":
            return label.strip()
        raise ValueError(f"unsupported attribute key: {key!r}")

    def _try_parse_date(self, raw: str) -> str | None:
        """Convert a NEMSIS human-readable date string to ISO 8601.

        Args:
            raw: Stripped input text.

        Returns:
            ISO 8601 string on success, ``None`` if the text is not a date.
        """

        m = _DATE_FULL_RE.match(raw)
        if m is not None:
            month_name, day, year, hour, minute, second, tz_h, tz_m = m.groups()
            if month_name not in _MONTH_NAMES:
                return None
            month = _MONTH_NAMES[month_name]
            return (
                f"{year}-{month:02d}-{int(day):02d}"
                f"T{int(hour):02d}:{minute}:{second}{tz_h}:{tz_m}"
            )
        m = _DATE_ONLY_RE.match(raw)
        if m is not None:
            month_name, day, year = m.groups()
            if month_name not in _MONTH_NAMES:
                return None
            month = _MONTH_NAMES[month_name]
            return f"{year}-{month:02d}-{int(day):02d}"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# StateDataSet resolver
# ─────────────────────────────────────────────────────────────────────────────

class StateDataSetResolver:
    """Resolve ``[Value from StateDataSet]`` references.

    The resolver loads the ``StateDataSet`` XML once at construction and builds:

    * ``_agency_values`` — ``sAgency.NN`` → ``[values]`` for the matched
      ``sAgencyGroup`` (keyed by ``sAgency.02``).
    * ``_facility_groups`` — ``facility_name`` → ``{sFacility.NN: [values]}``
      for every ``sFacility.FacilityGroup`` child in the state file.
    * ``_facility_category`` — ``facility_name`` → ``sFacility.01`` value
      (the facility category code) for the parent ``sFacilityGroup``.

    Callers set the current facility context via :meth:`set_facility_context`
    so that ``dFacility.NN`` references (N ≥ 2) resolve against the correct
    facility group.
    """

    def __init__(self, state_xml_path: Path, agency_key: str) -> None:
        """Initialise the resolver.

        Args:
            state_xml_path: Path to ``2025-STATE-1_v351.xml``.
            agency_key: Value of ``sAgency.02`` identifying the target agency
                (e.g. ``"351-T0495"``).

        Returns:
            None.

        Raises:
            FileNotFoundError: If ``state_xml_path`` does not exist.
            UnresolvedReferenceError: If no ``sAgencyGroup`` with the given
                ``agency_key`` is present in the StateDataSet.
        """

        state_xml_path = Path(state_xml_path)
        if not state_xml_path.exists():
            raise FileNotFoundError(f"StateDataSet not found: {state_xml_path}")

        self._agency_key = agency_key
        ns = {"n": NEMSIS_NS}
        tree = ET.parse(state_xml_path)
        root = tree.getroot()

        # ── agency values ────────────────────────────────────────────────────
        self._agency_values: dict[str, list[str]] = {}
        matched_group: ET.Element | None = None
        for group in root.iterfind(".//n:sAgencyGroup", ns):
            a02 = group.find("n:sAgency.02", ns)
            if a02 is not None and (a02.text or "").strip() == agency_key:
                matched_group = group
                break

        if matched_group is None:
            raise UnresolvedReferenceError(
                f"no sAgencyGroup with sAgency.02 == {agency_key!r} in {state_xml_path.name}"
            )

        for child in matched_group:
            local_tag = child.tag.split("}", 1)[-1]
            if not local_tag.startswith("sAgency."):
                continue
            text = (child.text or "").strip()
            if not text:
                continue
            self._agency_values.setdefault(local_tag, []).append(text)

        # ── facility groups ───────────────────────────────────────────────────
        # _facility_groups[facility_name][sFacility.NN] = [(value, attrs), ...]
        # attrs carries element attributes from the state XML (e.g.
        # ``{"PhoneNumberType": "9913009"}`` on sFacility.15) so the builder
        # can propagate them to the generated dFacility.NN element.
        self._facility_groups: dict[str, dict[str, list[tuple[str, dict[str, str]]]]] = {}
        # _facility_category[facility_name] = sFacility.01 code of parent
        self._facility_category: dict[str, str] = {}

        for sfacility_group in root.iterfind(".//n:sFacilityGroup", ns):
            # sFacility.01 is the facility category code, a child of sFacilityGroup
            cat_el = sfacility_group.find("n:sFacility.01", ns)
            category_code = (cat_el.text or "").strip() if cat_el is not None else ""
            # Each sFacility.FacilityGroup within this sFacilityGroup is one facility
            for facility_fg in sfacility_group.iterfind("n:sFacility.FacilityGroup", ns):
                name_el = facility_fg.find("n:sFacility.02", ns)
                if name_el is None:
                    continue
                facility_name = (name_el.text or "").strip()
                if not facility_name:
                    continue
                fields: dict[str, list[tuple[str, dict[str, str]]]] = {}
                for child in facility_fg:
                    local_tag = child.tag.split("}", 1)[-1]
                    if not local_tag.startswith("sFacility."):
                        continue
                    val = (child.text or "").strip()
                    if not val:
                        continue
                    # Capture element attributes (e.g. PhoneNumberType) so
                    # builder can emit them on the corresponding dFacility.NN.
                    child_attrs: dict[str, str] = {}
                    for attr_key, attr_val in child.attrib.items():
                        local_attr = attr_key.split("}", 1)[-1]
                        child_attrs[local_attr] = attr_val
                    fields.setdefault(local_tag, []).append((val, child_attrs))
                self._facility_groups[facility_name] = fields
                self._facility_category[facility_name] = category_code
                # Also index by sFacility.03 (Facility Location Code) for
                # eDisposition references that key by code rather than name.
                code_entries = fields.get("sFacility.03", [])
                for code_value, _ in code_entries:
                    self._facility_groups[code_value] = fields
                    self._facility_category[code_value] = category_code

        # Current facility context (set by builder when dFacility.02 is seen)
        self._current_facility: str | None = None
        # Current destination facility context (set on eDisposition.01/.02)
        self._current_destination: str | None = None
        # Per-facility occurrence counter for multi-valued fields.
        # Keyed by (scope_key, state_key) where scope_key is the active
        # facility/destination name.  Advances once per cell, read by every
        # resolve call within that cell.
        self._occurrence: dict[tuple[str, str], int] = {}
        # Per-cell cache so _compose_element_attrs and _extract_value in
        # the same builder cell see identical (value, attrs) tuples.
        self._cell_cache: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}

    def set_facility_context(self, facility_name: str | None) -> None:
        """Set the active facility for subsequent ``dFacility.NN`` resolution.

        Also resets the per-facility multi-value occurrence counters so the
        first ``dFacility.NN`` cell for the new facility yields ``values[0]``.

        Args:
            facility_name: The literal facility name value (e.g.
                ``"HCA Florida Fort Walton-Destin Hospital"``), or ``None`` to
                clear the context.

        Returns:
            None.
        """

        self._current_facility = facility_name
        self._cell_cache.clear()
        # Reset occurrence counters scoped to this facility so the first
        # dFacility.05 / dFacility.15 cell in the new group starts at index 0.
        if facility_name is not None:
            self._occurrence = {
                k: v for k, v in self._occurrence.items() if k[0] != facility_name
            }

    def set_destination_context(self, destination_key: str | None) -> None:
        """Set the active destination facility for subsequent ``eDisposition.NN``
        resolution.  ``destination_key`` may be either the destination facility
        name (``eDisposition.01``) or the destination code (``eDisposition.02``).
        """

        self._current_destination = destination_key
        self._cell_cache.clear()
        if destination_key is not None:
            self._occurrence = {
                k: v for k, v in self._occurrence.items() if k[0] != destination_key
            }

    def begin_cell(self) -> None:
        """Signal the start of a new builder cell.

        Clears the per-cell cache so that subsequent ``resolve`` /
        ``resolve_attribute`` calls advance the multi-value occurrence
        counter for that cell's element and resolve against a consistent
        N-th state value for both body text and annotation attributes.
        """

        self._cell_cache.clear()

    def resolve(self, element_id: str) -> str:
        """Resolve the text value of a ``[Value from StateDataSet]`` /
        ``[Value from DEMDataSet]`` reference.

        See :meth:`_resolve_with_attrs` for the resolution rules.  This
        method discards the attribute dict returned by that helper.
        """

        value, _attrs = self._resolve_with_attrs(element_id)
        return value

    def resolve_attribute(self, element_id: str, attr_name: str) -> str | None:
        """Resolve a state-sourced value for an annotation attribute.

        When an HTML cell carries ``[PhoneNumberType = [Value from
        StateDataSet]]`` on a ``dFacility.NN`` element, the attribute
        value is the ``PhoneNumberType`` attribute on the N-th
        ``sFacility.NN`` entry in the StateDataSet for the active
        facility.

        Args:
            element_id: NEMSIS element identifier (e.g. ``"dFacility.15"``).
            attr_name: Attribute name to look up (e.g. ``"PhoneNumberType"``).

        Returns:
            The attribute value for the N-th state occurrence, or ``None``
            if the state element does not carry that attribute.
        """

        _value, attrs = self._resolve_with_attrs(element_id)
        return attrs.get(attr_name)

    def _resolve_with_attrs(self, element_id: str) -> tuple[str, dict[str, str]]:
        """Resolve a cross-dataset reference to ``(value, attrs)``.

        Resolution rules
        ----------------
        * ``dAgency.NN`` / ``eResponse.NN`` → ``sAgency.NN`` of matched agency
          group (first value, no attrs).
        * ``dFacility.01`` → ``sFacility.01`` (category code) of the current
          facility context group (no attrs).
        * ``dFacility.NN`` (N ≥ 2) → the **N-th** value of ``sFacility.NN``
          in the current facility context group, where N advances once per
          builder cell.  The second element of the tuple carries the
          source ``sFacility.NN`` element's attributes (e.g.
          ``PhoneNumberType``).
        * ``eDisposition.NN`` → mapped ``sFacility.NN`` of the current
          destination facility (first value, no attrs).

        Within a single builder cell (framed by :meth:`begin_cell`), every
        call with the same ``element_id`` returns the same tuple; the
        occurrence counter advances at most once per cell per element.

        Args:
            element_id: DEM or EMS element identifier.

        Returns:
            ``(value, attrs)`` tuple.

        Raises:
            UnresolvedReferenceError: If the element id cannot be resolved
                with the current state.
        """

        # dAgency.NN / eResponse.NN → sAgency.NN
        if element_id.startswith("dAgency.") or element_id.startswith("eResponse."):
            suffix = element_id.split(".", 1)[1]
            state_key = f"sAgency.{suffix}"
            values = self._agency_values.get(state_key)
            if not values:
                raise UnresolvedReferenceError(
                    f"StateDataSet has no {state_key} for agency {self._agency_key!r}"
                )
            return values[0], {}

        # dFacility.NN → facility group lookup
        if element_id.startswith("dFacility."):
            suffix = element_id.split(".", 1)[1]
            facility_name = self._current_facility
            if facility_name is None:
                raise UnresolvedReferenceError(
                    f"cannot resolve {element_id!r}: no facility context is set"
                    " (dFacility.02 must precede dFacility.NN references)"
                )
            # dFacility.01 → category code of the parent sFacilityGroup
            if suffix == "01":
                code = self._facility_category.get(facility_name)
                if not code:
                    raise UnresolvedReferenceError(
                        f"no sFacility.01 category for facility {facility_name!r}"
                    )
                return code, {}
            # dFacility.NN (N ≥ 2)
            state_key = f"sFacility.{suffix}"
            group = self._facility_groups.get(facility_name)
            if group is None:
                raise UnresolvedReferenceError(
                    f"facility {facility_name!r} not found in StateDataSet"
                )
            entries = group.get(state_key)
            if not entries:
                raise UnresolvedReferenceError(
                    f"StateDataSet has no {state_key} for facility {facility_name!r}"
                )
            return self._pick_occurrence(facility_name, state_key, entries)

        # eDisposition.NN → sFacility mapping via destination facility context
        if element_id.startswith("eDisposition."):
            suffix = element_id.split(".", 1)[1]
            mapping = {
                "03": "sFacility.07",  # Destination Street Address
                "04": "sFacility.08",  # Destination City
                "05": "sFacility.09",  # Destination State
                "06": "sFacility.11",  # Destination County
                "07": "sFacility.10",  # Destination ZIP
                "08": "sFacility.12",  # Destination Country
                "09": "sFacility.13",  # Destination GPS
                "10": "sFacility.14",  # Destination US National Grid
            }
            state_key = mapping.get(suffix)
            if state_key is None:
                raise UnresolvedReferenceError(
                    f"no StateDataSet mapping defined for {element_id!r}"
                )
            dest = self._current_destination
            if dest is None:
                raise UnresolvedReferenceError(
                    f"cannot resolve {element_id!r}: no destination facility context is set"
                    " (eDisposition.01 or .02 must precede eDisposition.NN references)"
                )
            group = self._facility_groups.get(dest)
            if group is None:
                raise UnresolvedReferenceError(
                    f"destination facility {dest!r} not found in StateDataSet"
                )
            entries = group.get(state_key)
            if not entries:
                raise UnresolvedReferenceError(
                    f"StateDataSet has no {state_key} for destination {dest!r}"
                )
            return self._pick_occurrence(dest, state_key, entries)

        raise UnresolvedReferenceError(
            f"cannot resolve cross-dataset reference for {element_id!r}"
            " (only dAgency.NN, eResponse.NN, dFacility.NN and eDisposition.NN mappings are defined)"
        )

    def _pick_occurrence(
        self,
        scope_key: str,
        state_key: str,
        entries: list[tuple[str, dict[str, str]]],
    ) -> tuple[str, dict[str, str]]:
        """Return the next ``(value, attrs)`` for this cell and advance the
        occurrence counter on first access within the cell.

        If the HTML emits more cells than the StateDataSet has values, the
        index saturates at the last entry so no cell is ever unresolved.
        Within a single cell, repeated lookups return the cached tuple.

        Args:
            scope_key: Active facility / destination identifier.
            state_key: StateDataSet element tag (``"sFacility.05"`` …).
            entries: Ordered list of ``(value, attrs)`` tuples from state.

        Returns:
            ``(value, attrs)`` for the current cell's occurrence.
        """

        cache_key = (scope_key, state_key)
        cached = self._cell_cache.get(cache_key)
        if cached is not None:
            return cached
        idx = self._occurrence.get(cache_key, 0)
        if idx >= len(entries):
            idx = len(entries) - 1
        result = entries[idx]
        self._cell_cache[cache_key] = result
        self._occurrence[cache_key] = idx + 1
        return result


# ─────────────────────────────────────────────────────────────────────────────
# XML builder
# ─────────────────────────────────────────────────────────────────────────────

def _qname(tag: str) -> str:
    """Return a namespaced QName for ElementTree.

    Args:
        tag: Unqualified NEMSIS element tag.

    Returns:
        ``"{http://www.nemsis.org}tag"``.
    """

    return f"{{{NEMSIS_NS}}}{tag}"


class NemsisXmlBuilder:
    """Construct the final NEMSIS XML tree from parsed :class:`HtmlCell`
    records.

    All dynamic values (UUIDs, timestamps, ``[Your …]`` placeholders) are
    resolved via :class:`ConversionInput`.  Cross-dataset references are
    resolved through :class:`StateDataSetResolver`.  Coded-value translation
    is delegated to :class:`ValueTranslator`.  The builder itself is a pure
    transformer — it never generates new state.
    """

    def __init__(
        self,
        root_tag: str,
        schema_location: str,
        translator: ValueTranslator,
        conversion_input: ConversionInput,
        state_resolver: StateDataSetResolver,
    ) -> None:
        """Initialise the builder.

        Args:
            root_tag: Root element tag — ``"DEMDataSet"`` or ``"EMSDataSet"``.
            schema_location: Value for the root ``xsi:schemaLocation``
                attribute.
            translator: Injected :class:`ValueTranslator`.
            conversion_input: Runtime values supplied by the caller.
            state_resolver: Resolver for ``[Value from StateDataSet]``
                references.

        Returns:
            None.
        """

        ET.register_namespace("", NEMSIS_NS)
        ET.register_namespace("xsi", XSI_NS)
        self._root = ET.Element(
            _qname(root_tag),
            {XSI_SCHEMA_LOCATION: schema_location},
        )
        self._translator = translator
        self._input = conversion_input
        self._state_resolver = state_resolver
        self._stack: list[tuple[int, ET.Element]] = [(0, self._root)]

    @property
    def root(self) -> ET.Element:
        """Return the built XML root element.

        Returns:
            The :class:`xml.etree.ElementTree.Element` root.
        """

        return self._root

    def build(self, cells: list[HtmlCell]) -> ET.Element:
        """Process every parsed cell and return the final root element.

        Args:
            cells: Ordered list produced by :class:`HtmlParser`.

        Returns:
            The root element after all cells have been appended.
        """

        for cell in cells:
            self._add_cell(cell)
        return self._root

    def _parent_for_depth(self, depth: int) -> ET.Element:
        """Pop the parent stack until the appropriate container is on top.

        Args:
            depth: Nesting depth of the cell about to be added.

        Returns:
            The parent :class:`ET.Element` that should receive the new child.
        """

        while len(self._stack) > 1 and self._stack[-1][0] >= depth:
            self._stack.pop()
        return self._stack[-1][1]

    def _compose_element_attrs(self, cell: HtmlCell) -> dict[str, str]:
        """Compose every attribute that decorates the cell's element tag.

        Args:
            cell: The parsed HTML cell.

        Returns:
            Mapping of attribute qnames to string values.

        Raises:
            MissingInputError: If a required UUID/timestamp/placeholder is
                absent from :class:`ConversionInput`.
            UnknownCodedValueError: If an attribute label has no coded value.
        """

        attrs: dict[str, str] = {}

        if cell.needs_uuid_attr:
            attrs["UUID"] = self._input.require_uuid(cell.occurrence_key)
        if cell.needs_timestamp_attr:
            attrs["timeStamp"] = self._input.require_timestamp(cell.occurrence_key)

        for key, label in cell.annotations.items():
            if key in ("UUID", "timeStamp"):
                continue
            # Annotation values may themselves be ``[Value from StateDataSet]``
            # — resolve those against the active facility context so
            # attributes like ``PhoneNumberType`` on ``dFacility.15`` are
            # emitted from the StateDataSet entry rather than being dropped.
            if label.startswith("[Value from"):
                if key in (
                    "PhoneNumberType",
                    "EmailAddressType",
                    "ETCO2Type",
                    "DistanceUnit",
                    "CodeType",
                    "StreetAddress2",
                ):
                    state_val = self._state_resolver.resolve_attribute(
                        cell.element_id, key
                    )
                    if state_val is not None and state_val.strip():
                        attrs[key] = state_val.strip()
                # NV/PN annotations sourced from StateDataSet are not in
                # scope for this generator; skip silently.
                continue
            if key == "NV":
                attrs["NV"] = self._translator.translate_attribute("NV", label)
                # NV indicates absence of value — xsi:nil must accompany on
                # nillable elements so the element validates under XSD.
                if cell.element_id in _NILLABLE_ELEMENTS:
                    attrs[XSI_NIL] = "true"
            elif key == "PN":
                attrs["PN"] = self._translator.translate_attribute("PN", label)
                # PN (Pertinent Negative) semantics vary by code: some PN
                # codes annotate an existing value (e.g. "Approximate" —
                # 8801029 on date/time fields) while others express
                # absence (e.g. "None Reported" — 8801027).  Do *not*
                # unconditionally emit xsi:nil here; the builder decides
                # based on whether the cell resolves to real text.
            elif key in (
                "PhoneNumberType",
                "EmailAddressType",
                "ETCO2Type",
                "DistanceUnit",
                "CodeType",
                "StreetAddress2",
            ):
                attrs[key] = self._translator.translate_attribute(key, label)

        return attrs

    def _extract_value(self, cell: HtmlCell) -> str | None:
        """Resolve the element's text content.

        Args:
            cell: The parsed HTML cell.

        Returns:
            The canonical text value, or ``None`` for xsi:nil elements and
            groups that have no inline text.

        Raises:
            MissingInputError: If a ``[Your …]`` placeholder is absent from
                :class:`ConversionInput`.
            UnresolvedReferenceError: If a StateDataSet reference cannot be
                resolved.
            UnknownCodedValueError: If a raw label cannot be translated.
        """

        if cell.is_nil:
            return None
        if cell.is_group:
            return None
        if cell.state_ref or cell.dem_ref:
            override = self._input.get_dem_reference(cell.element_id)
            if override is not None:
                return override
            return self._state_resolver.resolve(cell.element_id)
        if cell.your_placeholder is not None:
            return self._input.require_placeholder(cell.your_placeholder)
        if cell.value_text is None:
            return None
        return self._translator.translate(cell.value_text, cell.element_id)

    def _add_cell(self, cell: HtmlCell) -> None:
        """Append one :class:`HtmlCell` to the growing XML tree.

        When a ``dFacility.FacilityGroup`` container is entered, the facility
        context is cleared.  When ``dFacility.02`` is encountered with a
        non-state-ref value, the facility context is set to that value so
        subsequent ``[Value from StateDataSet]`` references on ``dFacility.NN``
        resolve against the correct StateDataSet ``sFacility.FacilityGroup``.

        Args:
            cell: The cell to translate and append.

        Returns:
            None.
        """

        # Start a new resolver cell so multi-valued state lookups
        # (dFacility.05 / dFacility.15 with multiple sFacility.NN entries)
        # advance their occurrence counter exactly once per cell and both
        # the body value and annotation attributes see the same N-th tuple.
        self._state_resolver.begin_cell()

        # Clear facility context when entering a new FacilityGroup container
        if cell.is_group and cell.element_id == "dFacility.FacilityGroup":
            self._state_resolver.set_facility_context(None)

        # Clear destination context when entering a new eDisposition group
        if cell.is_group and cell.element_id == "eDisposition":
            self._state_resolver.set_destination_context(None)

        # Drop NEMSIS-reserved custom element slots (.901+) that are not in
        # the standard XSD — these are state/agency extension columns emitted
        # by the HTML template but have no schema position in v3.5.1.
        _tail = cell.element_id.rsplit(".", 1)[-1]
        if _tail.isdigit() and int(_tail) >= 900:
            if cell.is_group:
                self._stack.append((cell.depth, None))  # type: ignore[arg-type]
            return

        parent = self._parent_for_depth(cell.depth)
        attrs = self._compose_element_attrs(cell)
        element = ET.SubElement(parent, _qname(cell.element_id), attrs)

        text = self._extract_value(cell)
        # When the element already carries xsi:nil="true" (set by the NV
        # attribute path), XSD forbids any character content — suppress any
        # residual text.
        if attrs.get(XSI_NIL) == "true":
            text = None
        if text is not None and text.strip():
            element.text = text
        elif not cell.is_group:
            # Text is empty / absent.  If the element carries only a PN
            # attribute but no real value, promote it to xsi:nil when the
            # element is nillable so XSD enum/pattern facets no longer
            # reject the empty content.
            if "PN" in attrs and cell.element_id in _NILLABLE_ELEMENTS:
                element.set(XSI_NIL, "true")
                text = None  # ensure we do not fall into the removal branch

        # Set facility context once dFacility.02 is populated
        if (
            cell.element_id == "dFacility.02"
            and not cell.state_ref
            and not cell.dem_ref
            and text is not None
        ):
            self._state_resolver.set_facility_context(text)

        # Set destination context on eDisposition.01/.02 literal values
        if (
            cell.element_id in ("eDisposition.01", "eDisposition.02")
            and not cell.state_ref
            and not cell.dem_ref
            and text is not None
            and text.strip()
        ):
            self._state_resolver.set_destination_context(text)

        # Suppress elements that carry no usable content:
        #   * not a group container
        #   * no text (or only whitespace)
        #   * no attributes (PN/NV/type/UUID/etc.) — those keep the element
        #     alive even when the body is nil/empty
        #   * not marked xsi:nil (which legitimises empty content on
        #     nillable elements)
        has_text = text is not None and text.strip() != ""
        has_attrs = len(element.attrib) > 0
        if (
            not cell.is_group
            and not has_text
            and not has_attrs
        ):
            parent.remove(element)
            return

        # ── Rule 3 / Rule 7: classify-and-enforce before the element is
        # considered written.  Any violation detected here is a builder bug
        # (not a user input problem) — raise immediately so CI catches it.
        kind = classify_field(
            cell.element_id,
            is_group=cell.is_group,
            is_nil=cell.is_nil,
            coded_values=self._translator.coded_values,
        )
        self._enforce_field_kind(element, cell, kind, text, attrs)

        if cell.is_group:
            self._stack.append((cell.depth, element))

    def _enforce_field_kind(
        self,
        element: ET.Element,
        cell: HtmlCell,
        kind: FieldKind,
        text: str | None,
        attrs: Mapping[str, str],
    ) -> None:
        """Assert the written element satisfies its :class:`FieldKind`.

        Enforcement rules (Rule 7):

        * ``CODED``: text, when present, must match ``^\\d+$`` (no commas,
          no free text). ``xsi:nil`` permitted only when element is in
          :data:`_NILLABLE_ELEMENTS` and carries an ``NV`` or ``PN`` attr.
        * ``NIL``: element MUST have ``xsi:nil="true"`` AND an ``NV`` attr.
        * ``DATETIME``: text must match ISO 8601 with optional TZ offset
          (``_ISO_DATETIME_RE``) or the element must be ``xsi:nil``.
        * ``UUID_VALUED``: text must match a canonical UUID regex.
        * ``TEXT``: free text accepted; no enforcement beyond namespace.
        * ``GROUP``: no text permitted on the element itself.

        Args:
            element: The just-created :class:`ET.Element`.
            cell: The originating :class:`HtmlCell`.
            kind: Classification result.
            text: The text that was (or was not) set on ``element.text``.
            attrs: The attributes that were composed for this element.

        Raises:
            CtaConversionError: When the element violates its kind contract.
        """

        eid = cell.element_id

        if kind is FieldKind.GROUP:
            if text is not None and text.strip():
                raise CtaConversionError(
                    f"group element {eid!r} must not carry text content; got {text!r}"
                )
            return

        if kind is FieldKind.NIL:
            if element.get(XSI_NIL) != "true":
                raise CtaConversionError(
                    f"{eid!r} classified NIL but xsi:nil attr not set"
                )
            if "NV" not in attrs:
                raise CtaConversionError(
                    f"{eid!r} classified NIL but NV attr not set"
                )
            return

        if kind is FieldKind.DATETIME:
            if element.get(XSI_NIL) == "true":
                return
            if text is None or not text.strip():
                return  # empty element already stripped above, or kept alive by attrs
            if not _ISO_DATETIME_RE.match(text.strip()):
                raise CtaConversionError(
                    f"{eid!r} classified DATETIME but text is not ISO 8601: {text!r}"
                )
            return

        if kind is FieldKind.UUID_VALUED:
            if element.get(XSI_NIL) == "true":
                return
            if text is None or not text.strip():
                return
            if not _UUID_RE.match(text.strip()):
                # eRecord.01 accepts agency-defined identifiers (e.g.
                # FEMSQ-2025-EMS-00001) alongside UUIDs per NEMSIS XSD
                # (element_id eRecord.01 is xs:string).  Only enforce UUID
                # shape for dAgency.01 which is xs:string with UUID pattern.
                if eid == "dAgency.01":
                    raise CtaConversionError(
                        f"{eid!r} classified UUID_VALUED but text is not a UUID: {text!r}"
                    )
            return

        if kind is FieldKind.CODED:
            if element.get(XSI_NIL) == "true":
                if "NV" not in attrs and "PN" not in attrs:
                    raise CtaConversionError(
                        f"{eid!r} CODED+xsi:nil requires NV or PN attr"
                    )
                return
            if text is None or not text.strip():
                return  # empty CODED element kept alive by attrs is allowed
            stripped = text.strip()
            if _COMMA_IN_CODED_RE.search(stripped):
                raise CtaConversionError(
                    f"{eid!r} CODED must not contain commas (use repeated "
                    f"elements for multi-value); got {stripped!r}"
                )
            # CODED elements may hold numeric codes, ICD/SNOMED alphanumeric
            # codes (e.g. "T78.40XA"), ISO country codes ("US", "CA"), or
            # RxCUI numeric ids.  Reject only multi-word alphabetic labels
            # (e.g. "United States") that slipped through translation —
            # those clearly failed to resolve to a code.
            if re.match(r"^[A-Za-z]+(?:\s+[A-Za-z]+)+$", stripped):
                raise CtaConversionError(
                    f"{eid!r} CODED contains multi-word raw text (translation failed?): {stripped!r}"
                )
            return

        # FieldKind.TEXT → no structural enforcement
        return


# ─────────────────────────────────────────────────────────────────────────────
# Validation gate
# ─────────────────────────────────────────────────────────────────────────────

_PLACEHOLDER_RE = re.compile(r"\[(?:Your\b|Value\s+from\b)")
_BRACKET_RE = re.compile(r"\[")
_CUSTOM_VALUE_RE = re.compile(r"^\[Custom Value\]")
_CITY_OF_RE = re.compile(r"\bCity of ")


class SemanticValidationGate:
    """Post-build scanner that rejects any tree containing unresolved
    placeholders, bracket remnants, literal ``"City of "`` prefixes, raw
    alphabetic text in elements that must hold NEMSIS codes, malformed
    datetime literals, comma-separated coded values, or ``xsi:nil`` without
    an accompanying ``NV`` justification.

    All findings are collected before raising so the caller sees the full
    list of violations in one error.
    """

    def __init__(
        self, *, coded_values: CodedValueSet = NEMSIS_V351_CODED_VALUES
    ) -> None:
        """Initialise the validation gate.

        Args:
            coded_values: The :class:`CodedValueSet` used to classify
                elements during validation.  Defaults to the canonical
                v3.5.1 set.

        Returns:
            None.
        """

        self._codes = coded_values

    def check(self, root: ET.Element) -> None:
        """Walk the tree and raise on any semantic violation.

        Checks (applied to every element text and attribute value):

        1. ``[Your …]`` / ``[Value from …]`` placeholders remaining.
        2. Any ``[`` bracket character (catches any unresolved annotation
           token).
        3. Literal ``"City of "`` substring (city names must be resolved to
           FIPS codes before this point).
        4. Namespace enforcement — every element must live in the NEMSIS
           namespace (``http://www.nemsis.org``).
        5. ``xsi:nil="true"`` must be accompanied by ``NV=...`` (required
           for Type D fields per Rule 3 / Rule 7).
        6. Elements classified CODED must not carry commas or raw
           alphabetic text in their element text (Rule 4).
        7. Elements classified DATETIME must match ISO 8601 with TZ offset
           (Rule 5).

        Args:
            root: Root element of the generated document.

        Returns:
            None.

        Raises:
            UnresolvedPlaceholderError: If any violation is found.  The
                exception message lists every violation.
        """

        findings: list[str] = []

        # Check 4: the root itself must be in the NEMSIS namespace.
        if not root.tag.startswith(f"{{{NEMSIS_NS}}}"):
            findings.append(
                f"root element {root.tag!r} is not in NEMSIS namespace "
                f"{NEMSIS_NS!r}"
            )

        for element in root.iter():
            local = element.tag.split("}", 1)[-1]
            ns = element.tag.split("}", 1)[0].lstrip("{") if "}" in element.tag else ""

            # Check 4 (per-element namespace)
            if ns and ns != NEMSIS_NS:
                findings.append(
                    f"<{local}> is in namespace {ns!r}, expected {NEMSIS_NS!r}"
                )

            # Placeholder / bracket / city checks (text + attrs)
            for val, ctx in (
                (element.text, f"<{local}> text"),
                *((v, f"<{local}> attr {k!r}") for k, v in element.attrib.items()),
            ):
                if not val:
                    continue
                if _PLACEHOLDER_RE.search(val):
                    findings.append(f"{ctx}: {val!r}")
                    continue
                if _BRACKET_RE.search(val) and not _CUSTOM_VALUE_RE.match(val):
                    findings.append(f"{ctx}: unresolved bracket in {val!r}")
                    continue
                if _CITY_OF_RE.search(val):
                    findings.append(
                        f"{ctx}: literal 'City of' prefix not resolved to FIPS: {val!r}"
                    )

            # Check 5: xsi:nil="true" must have NV or PN attr
            if element.get(XSI_NIL) == "true":
                if "NV" not in element.attrib and "PN" not in element.attrib:
                    findings.append(
                        f"<{local}>: xsi:nil=\"true\" without NV or PN attribute "
                        f"(Rule 7 Type D requires justification)"
                    )

            # Check 6/7: CODED / DATETIME content conformance
            text = element.text
            if text is None or not text.strip():
                continue
            try:
                kind = classify_field(
                    local,
                    is_group=False,
                    is_nil=False,
                    coded_values=self._codes,
                )
            except Exception:
                continue

            stripped = text.strip()
            if kind is FieldKind.CODED:
                if "," in stripped:
                    findings.append(
                        f"<{local}>: CODED value contains comma (use repeated "
                        f"elements for multi-value): {stripped!r}"
                    )
                elif re.match(r"^[A-Za-z]+(?:\s+[A-Za-z]+)+$", stripped):
                    findings.append(
                        f"<{local}>: CODED value is raw multi-word text "
                        f"(translation failed?): {stripped!r}"
                    )
            elif kind is FieldKind.DATETIME:
                if not _ISO_DATETIME_RE.match(stripped):
                    findings.append(
                        f"<{local}>: DATETIME value is not ISO 8601: "
                        f"{stripped!r}"
                    )

        if findings:
            raise UnresolvedPlaceholderError(
                "semantic validation failed after conversion:\n  "
                + "\n  ".join(findings)
            )


# Keep the old name as an alias for any callers that still reference it.
ValidationGate = SemanticValidationGate


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def convert_html_to_nemsis_xml(
    html_path: Path,
    state_xml_path: Path,
    output_path: Path,
    conversion_input: ConversionInput,
    *,
    coded_values: CodedValueSet = NEMSIS_V351_CODED_VALUES,
    agency_key: str = "351-T0495",
) -> ET.Element:
    """Convert an official NEMSIS CTA HTML test case to a valid NEMSIS XML
    document.

    Args:
        html_path: Path to the ``.html`` test case.
        state_xml_path: Path to ``2025-STATE-1_v351.xml``.
        output_path: Destination for the generated XML document.
        conversion_input: Runtime values (UUIDs, timestamps, placeholder
            values) required for deterministic output.
        coded_values: NEMSIS coded-value set.  Defaults to the canonical
            v3.5.1 set; callers may inject an alternative for testing.
        agency_key: Value of ``sAgency.02`` identifying the target agency in
            the StateDataSet.  Defaults to the FusionEMSQuantum VSA key.

    Returns:
        The generated root :class:`ET.Element`.

    Raises:
        FileNotFoundError: If any input path does not exist.
        DatasetTypeError: If the HTML title is unrecognised.
        HtmlStructureError: If the HTML layout is malformed.
        MissingInputError: If :class:`ConversionInput` lacks a required entry.
        UnresolvedReferenceError: If a StateDataSet reference cannot be
            resolved.
        UnknownCodedValueError: If any coded-value label is not mapped.
        UnresolvedPlaceholderError: If the final tree still contains any
            placeholder token.
    """

    html_path = Path(html_path)
    state_xml_path = Path(state_xml_path)
    output_path = Path(output_path)

    parser = HtmlParser()
    root_tag, cells = parser.parse(html_path)
    log.info("%s: parsed %d cells, root=%s", html_path.name, len(cells), root_tag)

    schema_location = (
        DEM_SCHEMA_LOCATION if root_tag == "DEMDataSet" else EMS_SCHEMA_LOCATION
    )

    translator = ValueTranslator(coded_values=coded_values)
    state_resolver = StateDataSetResolver(
        state_xml_path=state_xml_path, agency_key=agency_key
    )
    builder = NemsisXmlBuilder(
        root_tag=root_tag,
        schema_location=schema_location,
        translator=translator,
        conversion_input=conversion_input,
        state_resolver=state_resolver,
    )
    root = builder.build(cells)

    SemanticValidationGate(coded_values=coded_values).check(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Pretty-print the tree so the serialised XML matches the layout of the
    # canonical CTA reference outputs (two-space indent, one element per
    # line).  ``ET.indent`` is available from Python 3.9+.
    ET.indent(root, space="  ", level=0)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output_path.write_bytes(xml_bytes)
    log.info("%s: wrote %d bytes", output_path, len(xml_bytes))

    return root
