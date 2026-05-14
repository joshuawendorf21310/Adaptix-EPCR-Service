"""NEMSIS Field Graph foundation (Slice A).

Deterministic, read-only metadata layer describing NEMSIS 3.5.1 fields used by
the Adaptix ePCR cockpit. This module owns *field metadata* only; it does NOT
own per-chart binding values (that lives in ``NemsisFieldBinding``) and it does
NOT decide export readiness (that lives in ``NemsisExportService``). It is the
substrate that downstream services (lock readiness, eCustom, validation
explanation, section completion) will consume in later slices.

Design rules enforced here:
* No external service calls.
* No I/O side effects on import.
* No PHI is stored.
* Catalog is a curated local seed for cockpit-critical fields. Each field is
  marked with ``source="local_seed"`` so callers can distinguish it from a
  future template-derived expansion.
* Required-if expressions are simple, declarative, and evaluated against a
  flat ``chart_state`` mapping of ``{field_id: value}``. Unknown operators or
  unknown referenced fields are treated as *unsatisfied* — never silently
  passed — so missing data cannot mask a real blocker.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Sequence


__all__ = [
    "NemsisFieldDefinition",
    "NemsisRequiredIfRule",
    "NemsisSectionSummary",
    "NemsisFieldGraphEvaluation",
    "NemsisFieldGraphService",
    "DEFAULT_GRAPH_SOURCE",
]


DEFAULT_GRAPH_SOURCE = "local_seed"


@dataclass(frozen=True)
class NemsisRequiredIfRule:
    """Declarative conditional-required rule attached to a field definition."""

    field_id: str
    operator: str
    expected: object | None = None

    def evaluate(self, chart_state: Mapping[str, object]) -> bool:
        """Return ``True`` when the rule's predicate is satisfied by chart_state.

        Unknown operators always return ``False`` so missing logic cannot
        accidentally mark a field as required-met.
        """

        if self.field_id not in chart_state:
            return False
        actual = chart_state.get(self.field_id)
        if self.operator == "present":
            return actual not in (None, "", [])
        if self.operator == "equals":
            return actual == self.expected
        if self.operator == "in":
            if isinstance(self.expected, (list, tuple, set, frozenset)):
                return actual in self.expected
            return False
        return False


@dataclass(frozen=True)
class NemsisFieldDefinition:
    """Canonical metadata for a single NEMSIS field."""

    field_id: str
    section: str
    label: str
    data_type: str
    required_level: str  # one of: required | required_if | recommended | optional
    allowed_values: tuple[str, ...] = ()
    required_if: tuple[NemsisRequiredIfRule, ...] = ()
    source: str = DEFAULT_GRAPH_SOURCE

    def is_effectively_required(self, chart_state: Mapping[str, object]) -> bool:
        """Decide whether this field is required for the given chart state."""

        if self.required_level == "required":
            return True
        if self.required_level == "required_if":
            return any(rule.evaluate(chart_state) for rule in self.required_if)
        return False

    def is_satisfied(self, chart_state: Mapping[str, object]) -> bool:
        """Return ``True`` when the field has a non-empty value in chart_state."""

        if self.field_id not in chart_state:
            return False
        value = chart_state[self.field_id]
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, tuple, dict, set, frozenset)) and len(value) == 0:
            return False
        if self.allowed_values and isinstance(value, str):
            if value not in self.allowed_values:
                return False
        return True

    def to_payload(self) -> dict[str, object]:
        """Serialize to a JSON-ready dictionary (no PHI, metadata only)."""

        payload = asdict(self)
        payload["required_if"] = [asdict(rule) for rule in self.required_if]
        payload["allowed_values"] = list(self.allowed_values)
        return payload


@dataclass(frozen=True)
class NemsisSectionSummary:
    """Aggregate counts for a NEMSIS section."""

    section: str
    total_fields: int
    required_fields: int
    required_if_fields: int
    recommended_fields: int
    optional_fields: int

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NemsisFieldGraphEvaluation:
    """Result of evaluating chart_state against the graph."""

    section: str | None
    evaluated_fields: int
    satisfied_fields: int
    unsatisfied_required_fields: tuple[str, ...]
    unsatisfied_required_if_fields: tuple[str, ...]

    @property
    def has_blockers(self) -> bool:
        return bool(self.unsatisfied_required_fields) or bool(
            self.unsatisfied_required_if_fields
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "section": self.section,
            "evaluated_fields": self.evaluated_fields,
            "satisfied_fields": self.satisfied_fields,
            "unsatisfied_required_fields": list(self.unsatisfied_required_fields),
            "unsatisfied_required_if_fields": list(
                self.unsatisfied_required_if_fields
            ),
            "has_blockers": self.has_blockers,
        }


# ---------------------------------------------------------------------------
# Curated seed catalog (cockpit-critical NEMSIS 3.5.1 fields).
# Field identifiers, sections, and data types follow the NEMSIS 3.5.1 dataset
# naming convention already used in the ePCR codebase
# (see ``NEMSIS_FIELD_SECTIONS`` in ``api_nemsis.py``). The catalog is bounded
# and explicitly labelled ``source="local_seed"`` so future slices can replace
# or extend it from the official template loader without breaking callers.
# ---------------------------------------------------------------------------


def _build_seed_catalog() -> tuple[NemsisFieldDefinition, ...]:
    """Return the deterministic seed catalog of cockpit-critical fields."""

    # eRecord
    record_fields = (
        NemsisFieldDefinition(
            field_id="eRecord.01",
            section="eRecord",
            label="Patient Care Report Number",
            data_type="string",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eRecord.SoftwareApplication.03",
            section="eRecord",
            label="Software Name",
            data_type="string",
            required_level="required",
        ),
    )

    # eResponse
    response_fields = (
        NemsisFieldDefinition(
            field_id="eResponse.03",
            section="eResponse",
            label="EMS Agency Number",
            data_type="string",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eResponse.05",
            section="eResponse",
            label="Type of Service Requested",
            data_type="code",
            required_level="required",
            allowed_values=("emergency", "non_emergency", "intercept", "standby"),
        ),
        NemsisFieldDefinition(
            field_id="eResponse.10",
            section="eResponse",
            label="Unit Call Sign",
            data_type="string",
            required_level="required",
        ),
    )

    # eTimes
    times_fields = (
        NemsisFieldDefinition(
            field_id="eTimes.03",
            section="eTimes",
            label="Unit Notified by Dispatch Time",
            data_type="datetime",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eTimes.06",
            section="eTimes",
            label="Unit En Route Time",
            data_type="datetime",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eTimes.07",
            section="eTimes",
            label="Unit Arrived on Scene Time",
            data_type="datetime",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eTimes.13",
            section="eTimes",
            label="Patient Arrived at Destination Time",
            data_type="datetime",
            required_level="required_if",
            required_if=(
                NemsisRequiredIfRule(
                    field_id="eDisposition.30",
                    operator="equals",
                    expected="transported",
                ),
            ),
        ),
    )

    # ePatient
    patient_fields = (
        NemsisFieldDefinition(
            field_id="ePatient.13",
            section="ePatient",
            label="Patient Last Name",
            data_type="string",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="ePatient.14",
            section="ePatient",
            label="Patient First Name",
            data_type="string",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="ePatient.15",
            section="ePatient",
            label="Patient Date of Birth",
            data_type="date",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="ePatient.13.NotApplicable",
            section="ePatient",
            label="Patient Last Name Not Applicable Reason",
            data_type="code",
            required_level="required_if",
            allowed_values=("unknown", "refused", "not_recorded"),
            required_if=(
                NemsisRequiredIfRule(
                    field_id="ePatient.13",
                    operator="in",
                    expected=("", None),
                ),
            ),
        ),
    )

    # eSituation
    situation_fields = (
        NemsisFieldDefinition(
            field_id="eSituation.04",
            section="eSituation",
            label="Possible Injury",
            data_type="code",
            required_level="required",
            allowed_values=("yes", "no", "unknown"),
        ),
        NemsisFieldDefinition(
            field_id="eSituation.11",
            section="eSituation",
            label="Provider's Primary Impression",
            data_type="code",
            required_level="required",
        ),
    )

    # eVitals
    vitals_fields = (
        NemsisFieldDefinition(
            field_id="eVitals.01",
            section="eVitals",
            label="Vital Signs Taken Date/Time",
            data_type="datetime",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eVitals.06",
            section="eVitals",
            label="SBP (Systolic Blood Pressure)",
            data_type="integer",
            required_level="recommended",
        ),
        NemsisFieldDefinition(
            field_id="eVitals.10",
            section="eVitals",
            label="Heart Rate",
            data_type="integer",
            required_level="recommended",
        ),
    )

    # eDisposition
    disposition_fields = (
        NemsisFieldDefinition(
            field_id="eDisposition.12",
            section="eDisposition",
            label="Incident/Patient Disposition",
            data_type="code",
            required_level="required",
        ),
        NemsisFieldDefinition(
            field_id="eDisposition.30",
            section="eDisposition",
            label="Transport Disposition",
            data_type="code",
            required_level="required",
            allowed_values=(
                "transported",
                "treated_not_transported",
                "no_treatment_no_transport",
                "canceled",
                "dead_at_scene",
            ),
        ),
    )

    # eNarrative
    narrative_fields = (
        NemsisFieldDefinition(
            field_id="eNarrative.01",
            section="eNarrative",
            label="Patient Care Report Narrative",
            data_type="text",
            required_level="required",
        ),
    )

    return (
        record_fields
        + response_fields
        + times_fields
        + patient_fields
        + situation_fields
        + vitals_fields
        + disposition_fields
        + narrative_fields
    )


class NemsisFieldGraphService:
    """Read-only service exposing the NEMSIS field graph."""

    def __init__(
        self,
        catalog: Sequence[NemsisFieldDefinition] | None = None,
    ) -> None:
        seeded = catalog if catalog is not None else _build_seed_catalog()
        # Index defensively; reject duplicate field ids so the graph stays
        # deterministic.
        index: dict[str, NemsisFieldDefinition] = {}
        for definition in seeded:
            if definition.field_id in index:
                raise ValueError(
                    f"Duplicate NEMSIS field definition: {definition.field_id}"
                )
            index[definition.field_id] = definition
        self._index = index
        self._ordered: tuple[NemsisFieldDefinition, ...] = tuple(seeded)

    # -- Lookup -----------------------------------------------------------

    def get_field(self, field_id: str) -> NemsisFieldDefinition | None:
        """Return the definition for ``field_id`` or ``None`` if unknown."""

        return self._index.get(field_id)

    def list_fields(self) -> tuple[NemsisFieldDefinition, ...]:
        """Return all fields in deterministic catalog order."""

        return self._ordered

    def list_section(self, section: str) -> tuple[NemsisFieldDefinition, ...]:
        """Return only the fields in ``section`` (deterministic order)."""

        return tuple(f for f in self._ordered if f.section == section)

    def list_sections(self) -> tuple[NemsisSectionSummary, ...]:
        """Return per-section summaries in deterministic order."""

        section_order: list[str] = []
        seen: set[str] = set()
        for definition in self._ordered:
            if definition.section not in seen:
                section_order.append(definition.section)
                seen.add(definition.section)

        summaries: list[NemsisSectionSummary] = []
        for section in section_order:
            fields = self.list_section(section)
            summaries.append(
                NemsisSectionSummary(
                    section=section,
                    total_fields=len(fields),
                    required_fields=sum(
                        1 for f in fields if f.required_level == "required"
                    ),
                    required_if_fields=sum(
                        1 for f in fields if f.required_level == "required_if"
                    ),
                    recommended_fields=sum(
                        1 for f in fields if f.required_level == "recommended"
                    ),
                    optional_fields=sum(
                        1 for f in fields if f.required_level == "optional"
                    ),
                )
            )
        return tuple(summaries)

    # -- Evaluation -------------------------------------------------------

    def evaluate_required(
        self,
        chart_state: Mapping[str, object],
        section: str | None = None,
    ) -> NemsisFieldGraphEvaluation:
        """Evaluate ``chart_state`` against the graph.

        Returns a deterministic ``NemsisFieldGraphEvaluation`` listing
        unsatisfied required and required-if fields. When ``section`` is
        supplied, evaluation is scoped to that section only.
        """

        scope: Iterable[NemsisFieldDefinition] = (
            self.list_section(section) if section is not None else self._ordered
        )
        scope_tuple = tuple(scope)

        unsatisfied_required: list[str] = []
        unsatisfied_required_if: list[str] = []
        satisfied = 0

        for definition in scope_tuple:
            if not definition.is_effectively_required(chart_state):
                if definition.is_satisfied(chart_state):
                    satisfied += 1
                continue

            if definition.is_satisfied(chart_state):
                satisfied += 1
                continue

            if definition.required_level == "required":
                unsatisfied_required.append(definition.field_id)
            else:
                unsatisfied_required_if.append(definition.field_id)

        return NemsisFieldGraphEvaluation(
            section=section,
            evaluated_fields=len(scope_tuple),
            satisfied_fields=satisfied,
            unsatisfied_required_fields=tuple(unsatisfied_required),
            unsatisfied_required_if_fields=tuple(unsatisfied_required_if),
        )


_default_service: NemsisFieldGraphService | None = None


def get_default_service() -> NemsisFieldGraphService:
    """Return a process-wide default ``NemsisFieldGraphService`` instance."""

    global _default_service
    if _default_service is None:
        _default_service = NemsisFieldGraphService()
    return _default_service
