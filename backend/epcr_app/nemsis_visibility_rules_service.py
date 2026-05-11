"""NEMSIS field visibility / requiredness rules.

Backend-authoritative resolver for whether a NEMSIS element should be
shown, required, or disabled given chart context. The frontend MUST
defer to this service's verdict — it is not allowed to decide
requiredness alone (Adaptix governance: validation is not optional).

Inputs the service uses (when present in ``chart_context``):
- patient age, patient sex
- incident type
- transport status
- cardiac arrest status
- injury / trauma status
- medication administered (bool)
- procedure performed (bool)
- agency configuration
- active state pack
- chart status (open / locked / finalized)
- user role
- custom element configuration

Output shape per element:
    {
      "element_number": "eArrest.01",
      "dataset": "EMSDataSet",
      "section": "eArrest",
      "visible": true,
      "required": false,
      "disabled": false,
      "deprecated": false,
      "reason": "...",
      "source": "dictionary|state|agency|workflow|role"
    }

Rules:
- Mandatory fields: always visible; required when their section is active.
- Required fields: visible when section/group is active; required if condition holds.
- Conditional fields: ``required_if`` interpreted minimally; unknown
  conditions default to visible-but-not-required (never silently hidden).
- State-required fields: required when active state pack lists them.
- Deprecated fields: hidden unless ``compatibility_mode=True`` in context.
- Backend-generated fields: visible read-only.
- Role restriction: chart status ``finalized`` => disabled for everyone.
- Unknown elements: visible but flagged with reason ``element_not_in_registry``
  so the frontend can render BLOCKED rather than silently hide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from epcr_app.nemsis_registry_service import (
    NemsisRegistryService,
    get_default_registry_service,
)

# Sections that are only relevant when a specific workflow flag is true.
# Conservative — when the flag is absent we keep them visible (better
# than silently hiding clinically important fields).
WORKFLOW_GATED_SECTIONS: dict[str, str] = {
    "eArrest": "cardiac_arrest",
    "eInjury": "trauma_injury",
    "eMedications": "medication_administered",
    "eProcedures": "procedure_performed",
    "eLabs": "labs_performed",
}

# DEM and State sections that are agency/admin scoped, NOT per-encounter.
# They remain accessible (admin tools), but are not surfaced as required
# inside a patient encounter chart.
AGENCY_ADMIN_SECTIONS: set[str] = {
    "dAgency",
    "dConfiguration",
    "dContact",
    "dCustomConfiguration",
    "dCustomResults",
    "dDevice",
    "dFacility",
    "dLocation",
    "dPersonnel",
    "dVehicle",
    "sAgency",
    "sConfiguration",
    "sElement",
    "sFacility",
    "sSoftware",
    "sState",
    "sdCustomConfiguration",
    "seCustomConfiguration",
}


@dataclass
class VisibilityDecision:
    element_number: str
    dataset: str
    section: str
    visible: bool
    required: bool
    disabled: bool
    deprecated: bool
    reason: str
    source: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "element_number": self.element_number,
            "dataset": self.dataset,
            "section": self.section,
            "visible": self.visible,
            "required": self.required,
            "disabled": self.disabled,
            "deprecated": self.deprecated,
            "reason": self.reason,
            "source": self.source,
        }
        if self.extra:
            out["extra"] = dict(self.extra)
        return out


class NemsisVisibilityRulesService:
    """Backend-authoritative visibility/requiredness resolver."""

    def __init__(self, registry: NemsisRegistryService | None = None) -> None:
        self._registry = registry or get_default_registry_service()

    # -- public API -------------------------------------------------------- #

    def evaluate(
        self,
        element_number: str,
        chart_context: dict[str, Any] | None = None,
    ) -> VisibilityDecision:
        ctx = chart_context or {}
        meta = self._registry.get_field(element_number)
        if not meta:
            return VisibilityDecision(
                element_number=element_number,
                dataset="",
                section=element_number.split(".")[0] if "." in element_number else "",
                visible=True,
                required=False,
                disabled=True,
                deprecated=False,
                reason="element not present in NEMSIS registry",
                source="dictionary",
                extra={"warning": "element_not_in_registry"},
            )

        dataset = str(meta.get("dataset") or "")
        section = str(meta.get("section") or "")
        usage = str(meta.get("usage") or meta.get("required_level") or "Optional")
        deprecated = bool(meta.get("deprecated"))
        compatibility_mode = bool(ctx.get("compatibility_mode"))
        chart_status = str(ctx.get("chart_status") or "open").lower()

        # Deprecated fields: hidden unless compatibility mode.
        if deprecated and not compatibility_mode:
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=False,
                required=False,
                disabled=True,
                deprecated=True,
                reason="element is deprecated in NEMSIS 3.5.1",
                source="dictionary",
            )

        # Finalized charts: read-only across the board.
        if chart_status in {"finalized", "locked", "submitted"}:
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=True,
                required=False,
                disabled=True,
                deprecated=deprecated,
                reason=f"chart is {chart_status}; read-only",
                source="workflow",
            )

        # Agency/admin sections inside an encounter chart: accessible but
        # not required as part of the encounter.
        if section in AGENCY_ADMIN_SECTIONS and ctx.get("scope") == "encounter":
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=True,
                required=False,
                disabled=False,
                deprecated=deprecated,
                reason=f"{section} is agency/admin-scoped; not required for this encounter",
                source="agency",
            )

        # State pack adds requiredness for explicitly listed elements.
        state_pack = ctx.get("state_pack") or {}
        state_required: Iterable[str] = state_pack.get("required_elements") or []
        if element_number in set(state_required):
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=True,
                required=True,
                disabled=False,
                deprecated=deprecated,
                reason=f"required by active state pack {state_pack.get('id', '')}".strip(),
                source="state",
            )

        # Workflow-gated sections.
        gate_flag = WORKFLOW_GATED_SECTIONS.get(section)
        if gate_flag is not None and gate_flag in ctx and ctx.get(gate_flag) is False:
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=False,
                required=False,
                disabled=False,
                deprecated=deprecated,
                reason=f"section {section} not active for this chart ({gate_flag} is false)",
                source="workflow",
            )

        # Required-if conditional logic. Conservative: only honor a small
        # set of well-known keys; otherwise leave the field visible but
        # not required (never silently hide on unknown conditions).
        required_if = meta.get("required_if")
        if isinstance(required_if, dict):
            satisfied = self._evaluate_required_if(required_if, ctx)
            if satisfied:
                return VisibilityDecision(
                    element_number=element_number,
                    dataset=dataset,
                    section=section,
                    visible=True,
                    required=True,
                    disabled=False,
                    deprecated=deprecated,
                    reason=f"required_if condition satisfied: {required_if}",
                    source="dictionary",
                )
            # condition present but unsatisfied -> visible, not required.
            return VisibilityDecision(
                element_number=element_number,
                dataset=dataset,
                section=section,
                visible=True,
                required=False,
                disabled=False,
                deprecated=deprecated,
                reason="required_if condition not satisfied",
                source="dictionary",
            )

        # Standard usage interpretation.
        required = usage.lower() == "mandatory" or (
            usage.lower() == "required" and section in WORKFLOW_GATED_SECTIONS
            and ctx.get(WORKFLOW_GATED_SECTIONS[section], True)
        )

        return VisibilityDecision(
            element_number=element_number,
            dataset=dataset,
            section=section,
            visible=True,
            required=required,
            disabled=False,
            deprecated=deprecated,
            reason=f"usage={usage}",
            source="dictionary",
        )

    def evaluate_section(
        self,
        section: str,
        chart_context: dict[str, Any] | None = None,
        dataset: str | None = None,
    ) -> list[dict[str, Any]]:
        fields = self._registry.list_fields(dataset=dataset, section=section)
        out: list[dict[str, Any]] = []
        for f in fields:
            element = f.get("field_id") or f.get("element_id")
            if not element:
                continue
            out.append(self.evaluate(element, chart_context).to_dict())
        return out

    def evaluate_chart(
        self,
        chart_context: dict[str, Any] | None = None,
        datasets: Iterable[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return decisions grouped by dataset → list of decisions."""
        target = list(datasets) if datasets else ["EMSDataSet", "DEMDataSet", "StateDataSet"]
        out: dict[str, list[dict[str, Any]]] = {}
        for ds in target:
            ds_decisions: list[dict[str, Any]] = []
            for f in self._registry.list_fields(dataset=ds):
                element = f.get("field_id") or f.get("element_id")
                if not element:
                    continue
                ds_decisions.append(self.evaluate(element, chart_context).to_dict())
            out[ds] = ds_decisions
        return out

    # -- internal --------------------------------------------------------- #

    @staticmethod
    def _evaluate_required_if(rule: dict[str, Any], ctx: dict[str, Any]) -> bool:
        """Conservative required_if interpreter.

        Honors only ``equals``, ``not_equals``, ``in`` operators on
        chart-context keys. Unknown operators / keys return False (NOT
        required) so the field stays visible but optional.
        """
        when = rule.get("when") or rule.get("conditions") or []
        if not isinstance(when, list):
            return False
        for cond in when:
            if not isinstance(cond, dict):
                return False
            key = cond.get("field") or cond.get("key")
            if key not in ctx:
                return False
            actual = ctx.get(key)
            if "equals" in cond and actual != cond["equals"]:
                return False
            if "not_equals" in cond and actual == cond["not_equals"]:
                return False
            if "in" in cond:
                allowed = cond["in"]
                if not isinstance(allowed, (list, tuple, set)) or actual not in allowed:
                    return False
        return bool(when)


_default_visibility_service: NemsisVisibilityRulesService | None = None


def get_default_visibility_service() -> NemsisVisibilityRulesService:
    global _default_visibility_service
    if _default_visibility_service is None:
        _default_visibility_service = NemsisVisibilityRulesService()
    return _default_visibility_service


__all__ = [
    "NemsisVisibilityRulesService",
    "VisibilityDecision",
    "get_default_visibility_service",
    "WORKFLOW_GATED_SECTIONS",
    "AGENCY_ADMIN_SECTIONS",
]
