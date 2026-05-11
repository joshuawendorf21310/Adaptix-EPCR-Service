"""Adaptix ePCR AI clinical intelligence engine.

Real Anthropic SDK integration replacing the rule-based stubs.

SAFETY CONTRACT (enforced unconditionally):
- AI never signs charts, never marks charts complete, never dispatches resources.
- Every output carries human_review_required=True.
- ai_signed and ai_marked_complete are hardcoded False on every return value.
- No PHI, prompts, completions, or tokens are written to logs.
- The model may only reference data explicitly supplied to it.
- The SAFETY_PREAMBLE is transmitted as a cached system block on every call.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Safety preamble — cached system block on every Claude call
# ---------------------------------------------------------------------------

SAFETY_PREAMBLE = """
You are an EMS documentation assistant embedded in the Adaptix ePCR platform.
CRITICAL SAFETY RULES YOU MUST FOLLOW UNCONDITIONALLY:
1. You MUST NOT diagnose patients, prescribe care, or make autonomous clinical decisions.
2. You MUST NOT finalize any clinical data without human provider review.
3. You MUST NOT mark any chart as complete or submit any data.
4. Every suggestion you make MUST be marked as requiring human review.
5. You MUST only reference information explicitly provided to you in the chart data.
6. You MUST flag unsupported statements in any generated narrative.
7. You MUST NOT invent vital signs, medications, procedures, or clinical facts.
8. Every narrative you generate must include a source reference for each statement.
""".strip()

# ---------------------------------------------------------------------------
# Protocol packs registry
# ---------------------------------------------------------------------------

PROTOCOL_PACKS: dict[str, dict] = {
    "ACLS": {
        "required_fields": ["eVitals.03", "eVitals.10", "eMedications.03", "eProcedures.03", "eArrest.01"],
        "reassessment_triggers": ["cardioversion", "pacing", "epinephrine", "amiodarone", "adenosine"],
        "documentation_prompts": [
            "Document rhythm before and after each intervention",
            "Document pulse check after each medication",
            "Document energy level for cardioversion/defibrillation",
            "Document capture status for pacing",
            "Document ROSC time if applicable",
        ],
        "billing_fields": ["eVitals.03", "eProcedures.03", "eMedications.03"],
    },
    "RSI": {
        "required_fields": [
            "eMedications.03", "eMedications.04", "eMedications.06",
            "eProcedures.03", "eVitals.12", "eVitals.16",
        ],
        "reassessment_triggers": ["intubation", "succinylcholine", "rocuronium", "etomidate", "ketamine"],
        "documentation_prompts": [
            "Document pre-oxygenation SpO2 and method",
            "Document induction agent: drug, dose, route",
            "Document paralytic: drug, dose, route",
            "Document laryngoscopy attempt count",
            "Document tube confirmation: EtCO2, CXR if applicable, bilateral breath sounds",
            "Document post-intubation SpO2 and EtCO2",
            "Document ventilator settings: mode, FiO2, PEEP, VT, RR",
            "Document post-intubation sedation if applicable",
        ],
        "billing_fields": ["eProcedures.03", "eMedications.03", "eVitals.16"],
    },
    "STEMI": {
        "required_fields": [
            "eVitals.03", "eVitals.06", "eVitals.07",
            "eTimes.03", "eTimes.07", "eSituation.11",
        ],
        "reassessment_triggers": ["aspirin", "nitroglycerin", "heparin", "fibrinolytic"],
        "documentation_prompts": [
            "Document 12-lead acquisition time",
            "Document STEMI activation time",
            "Document first medical contact time",
            "Document aspirin given: dose, route",
            "Document BP before and after nitroglycerin",
            "Document cath lab notification time if applicable",
        ],
        "billing_fields": ["eVitals.03", "eTimes.03", "eMedications.03"],
    },
    "STROKE": {
        "required_fields": [
            "eVitals.21", "eVitals.27", "eSituation.18",
            "eTimes.07", "eDisposition.17",
        ],
        "reassessment_triggers": ["glucose", "ct_scan_ordered"],
        "documentation_prompts": [
            "Document last known well time",
            "Document stroke scale used and score (CPSS, NIHSS, FAST, BE-FAST)",
            "Document glucose result",
            "Document blood pressure at least twice",
            "Document stroke center notification time",
            "Document contraindications to tPA if applicable",
        ],
        "billing_fields": ["eSituation.18", "eVitals.27", "eVitals.17"],
    },
    "CARDIAC_ARREST": {
        "required_fields": [
            "eArrest.01", "eArrest.02", "eArrest.04",
            "eArrest.08", "eArrest.11", "eTimes.07",
        ],
        "reassessment_triggers": ["cpr_started", "aed_applied", "epinephrine"],
        "documentation_prompts": [
            "Document arrest time (eArrest.11)",
            "Document who witnessed arrest (bystander/crew/none)",
            "Document first monitored rhythm",
            "Document CPR quality: depth, rate, compression fraction",
            "Document AED use if applicable",
            "Document every medication: drug, dose, time, route, response",
            "Document ROSC time if applicable",
            "Document post-ROSC vitals, rhythm, EtCO2",
            "Document hypothermia protocol if initiated",
            "Document termination of resuscitation criteria if applicable",
        ],
        "billing_fields": ["eArrest.01", "eArrest.08", "eMedications.03", "eProcedures.03"],
    },
    "SEPSIS": {
        "required_fields": [
            "eVitals.14", "eVitals.12", "eVitals.06",
            "eVitals.17", "eSituation.11",
        ],
        "reassessment_triggers": ["fluid_bolus", "vasopressor_started", "antibiotics"],
        "documentation_prompts": [
            "Document temperature and source of infection if identified",
            "Document lactate if obtained",
            "Document fluid boluses: volume, rate, patient response",
            "Document MAP assessment before/after vasopressors",
            "Document blood cultures if obtained before antibiotics",
            "Document antibiotics if given: drug, dose, time, route",
        ],
        "billing_fields": ["eVitals.14", "eMedications.03", "eProcedures.03"],
    },
    "TRAUMA": {
        "required_fields": ["eInjury.01", "eInjury.02", "eVitals.06", "eVitals.21", "eScene.09"],
        "reassessment_triggers": ["txa", "blood_product", "tourniquet"],
        "documentation_prompts": [
            "Document mechanism of injury",
            "Document trauma criteria met",
            "Document hemorrhage control measures",
            "Document GCS trend",
            "Document trauma center activation if applicable",
        ],
        "billing_fields": ["eInjury.01", "eInjury.03"],
    },
    "PALS": {
        "required_fields": [
            "ePatient.15", "ePatient.16", "eVitals.10",
            "eVitals.06", "eVitals.21",
        ],
        "reassessment_triggers": ["epinephrine_peds", "atropine", "adenosine_peds"],
        "documentation_prompts": [
            "Document patient weight and source (scale/estimated/Broselow)",
            "Document all medications as weight-based doses",
            "Document ETT size and insertion depth",
            "Document IO site if applicable",
        ],
        "billing_fields": ["ePatient.15", "eMedications.03"],
    },
    "OVERDOSE": {
        "required_fields": ["eSituation.11", "eHistory.17", "eVitals.06", "eVitals.21"],
        "reassessment_triggers": ["naloxone", "activated_charcoal", "flumazenil"],
        "documentation_prompts": [
            "Document suspected substance(s)",
            "Document toxidrome signs",
            "Document naloxone dose and patient response",
            "Document repeat doses if re-sedation",
            "Document GCS before and after intervention",
        ],
        "billing_fields": ["eMedications.03", "eSituation.11"],
    },
    "REFUSAL": {
        "required_fields": ["eDisposition.01", "ePatient.02", "eSituation.04", "eVitals.06"],
        "reassessment_triggers": [],
        "documentation_prompts": [
            "Document capacity assessment findings",
            "Document risks explained to patient",
            "Document patient's understanding of risks",
            "Document witness information if applicable",
            "Document attempts to contact medical control",
            "Document signature obtained or refused",
        ],
        "billing_fields": ["eDisposition.01", "eDisposition.29"],
    },
}

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class AdaptixClinicalAiEngine:
    """Real Anthropic SDK integration for EPCR clinical intelligence.

    All methods enforce:
    - AI cannot finalize data
    - AI cannot diagnose
    - AI cannot submit charts
    - Every output requires human review
    - SAFETY_PREAMBLE is a cached system block on every call
    """

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"

    # ------------------------------------------------------------------
    # Public async methods
    # ------------------------------------------------------------------

    async def generate_narrative(
        self,
        narrative_type: str,
        chart_data: dict,
        tenant_id: str,
        actor_id: str,
    ) -> dict:
        """Generate a clinical narrative from chart data.

        Returns a dict with keys:
            narrative_text, source_references, unsupported_statements,
            human_review_required (always True), ai_signed (always False),
            ai_marked_complete (always False), model.
        """
        chart_summary = self._build_chart_summary(chart_data)

        user_content = (
            f"Narrative type requested: {narrative_type}\n\n"
            f"Chart data summary:\n{chart_summary}\n\n"
            "Generate a clinical EMS narrative for this patient encounter. "
            "Return your response as a JSON object with the following keys:\n"
            "- narrative_text: the generated narrative text\n"
            "- source_references: list of strings, each citing which chart field "
            "supports a statement in the narrative\n"
            "- unsupported_statements: list of strings identifying any narrative "
            "statements that lack explicit chart data support\n"
            "- warnings: list of strings for any documentation concerns\n\n"
            "IMPORTANT: Respond with ONLY the JSON object, no surrounding text."
        )

        response_text = self._call_claude(user_content)

        try:
            parsed = json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat the whole response as narrative_text
            parsed = {
                "narrative_text": response_text,
                "source_references": [],
                "unsupported_statements": ["Unable to parse structured response — full text requires human review"],
                "warnings": [],
            }

        return {
            "narrative_text": parsed.get("narrative_text", ""),
            "source_references": parsed.get("source_references", []),
            "unsupported_statements": parsed.get("unsupported_statements", []),
            "warnings": parsed.get("warnings", []),
            "human_review_required": True,   # SAFETY INVARIANT — never False
            "ai_signed": False,               # SAFETY INVARIANT — never True
            "ai_marked_complete": False,      # SAFETY INVARIANT — never True
            "model": self.model,
        }

    async def detect_qa_flags(
        self,
        chart_data: dict,
        protocol_pack: str | None = None,
    ) -> list[dict]:
        """Detect QA issues in chart data.

        Returns a list of flag dicts with keys:
            flag_type, severity, description, field_path, suggested_action.
        """
        chart_summary = self._build_chart_summary(chart_data)
        pack_context = ""
        if protocol_pack and protocol_pack in PROTOCOL_PACKS:
            pack = PROTOCOL_PACKS[protocol_pack]
            pack_context = (
                f"\nActive protocol pack: {protocol_pack}\n"
                f"Required fields: {', '.join(pack['required_fields'])}\n"
                f"Reassessment triggers: {', '.join(pack['reassessment_triggers'])}\n"
            )

        flag_types = [
            "missing_reassessment", "contradictory_values", "impossible_vitals",
            "high_risk_no_reassessment", "airway_unconfirmed", "vent_no_settings",
            "arrest_no_timeline", "refusal_no_capacity", "controlled_substance_audit",
            "blood_product_no_verification", "missing_weight_pediatric",
            "duplicate_timestamp", "time_order_contradiction",
            "allergy_medication_conflict", "lab_abnormal_unmentioned",
        ]

        user_content = (
            f"Analyze the following ePCR chart data for QA issues.\n"
            f"{pack_context}\n"
            f"Chart data summary:\n{chart_summary}\n\n"
            f"Identify any QA issues from this list of flag types:\n"
            f"{', '.join(flag_types)}\n\n"
            "Return a JSON array. Each element must be an object with keys:\n"
            "- flag_type: one of the flag types listed above\n"
            "- severity: 'blocker', 'warning', or 'info'\n"
            "- description: clear explanation of the issue found\n"
            "- field_path: NEMSIS field path (e.g. 'eVitals.06') or null\n"
            "- suggested_action: recommended documentation action or null\n\n"
            "Only flag issues that are actually present in the chart data. "
            "If no issues are found, return an empty array [].\n"
            "IMPORTANT: Respond with ONLY the JSON array, no surrounding text."
        )

        response_text = self._call_claude(user_content)

        try:
            flags = json.loads(response_text)
            if not isinstance(flags, list):
                flags = []
        except (json.JSONDecodeError, ValueError):
            logger.warning("qa_flags: failed to parse AI response as JSON list")
            flags = []

        # Sanitise each flag — only keep known keys, enforce types
        clean_flags = []
        for f in flags:
            if not isinstance(f, dict):
                continue
            clean_flags.append({
                "flag_type": str(f.get("flag_type", "missing_reassessment")),
                "severity": str(f.get("severity", "warning")),
                "description": str(f.get("description", "")),
                "field_path": f.get("field_path") or None,
                "suggested_action": f.get("suggested_action") or None,
            })
        return clean_flags

    async def assess_billing_readiness(
        self,
        chart_data: dict,
        service_type: str,
    ) -> dict:
        """Assess billing completeness for CMS/payer submission.

        Returns a readiness assessment dict with keys:
            score, missing_fields, warnings, blockers, cms_service_level_risk,
            medical_necessity_complete, pcs_required, pcs_complete,
            mileage_documented, signature_complete, origin_destination_complete,
            human_review_required (always True).
        """
        chart_summary = self._build_chart_summary(chart_data)

        user_content = (
            f"Assess the billing readiness of the following ePCR chart for a "
            f"'{service_type}' service type.\n\n"
            f"Chart data summary:\n{chart_summary}\n\n"
            "Evaluate CMS ambulance billing requirements. Return a JSON object with keys:\n"
            "- score: integer 0-100 representing overall billing readiness\n"
            "- missing_fields: list of strings identifying missing required billing fields\n"
            "- warnings: list of strings for documentation concerns\n"
            "- blockers: list of strings for hard stop issues that prevent billing\n"
            "- cms_service_level_risk: string describing risk to claimed service level, or null\n"
            "- medical_necessity_complete: boolean\n"
            "- pcs_required: boolean (physician certification statement required)\n"
            "- pcs_complete: boolean\n"
            "- mileage_documented: boolean\n"
            "- signature_complete: boolean\n"
            "- origin_destination_complete: boolean\n\n"
            "Base your assessment only on information present in the chart summary. "
            "IMPORTANT: Respond with ONLY the JSON object, no surrounding text."
        )

        response_text = self._call_claude(user_content)

        try:
            parsed = json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            parsed = {}

        return {
            "score": int(parsed.get("score", 0)),
            "missing_fields": parsed.get("missing_fields", []),
            "warnings": parsed.get("warnings", []),
            "blockers": parsed.get("blockers", []),
            "cms_service_level_risk": parsed.get("cms_service_level_risk") or None,
            "medical_necessity_complete": bool(parsed.get("medical_necessity_complete", False)),
            "pcs_required": bool(parsed.get("pcs_required", False)),
            "pcs_complete": bool(parsed.get("pcs_complete", False)),
            "mileage_documented": bool(parsed.get("mileage_documented", False)),
            "signature_complete": bool(parsed.get("signature_complete", False)),
            "origin_destination_complete": bool(parsed.get("origin_destination_complete", False)),
            "human_review_required": True,   # SAFETY INVARIANT
        }

    async def generate_clinical_prompts(
        self,
        chart_data: dict,
        trigger_event: str,
        protocol_pack: str | None,
    ) -> list[dict]:
        """Generate context-aware clinical documentation prompts.

        Returns a list of prompt dicts with keys:
            prompt_type, protocol_pack, prompt_text, field_references.
        """
        chart_summary = self._build_chart_summary(chart_data)

        pack_context = ""
        if protocol_pack and protocol_pack in PROTOCOL_PACKS:
            pack = PROTOCOL_PACKS[protocol_pack]
            pack_context = (
                f"\nActive protocol pack: {protocol_pack}\n"
                f"Standard documentation prompts for this pack:\n"
                + "\n".join(f"  - {p}" for p in pack["documentation_prompts"])
                + "\n"
            )

        prompt_types = [
            "reassessment_required", "missing_field", "protocol_check",
            "intervention_followup", "medication_response_needed",
            "contradiction_detected", "billing_advisory", "qa_advisory",
        ]

        user_content = (
            f"Trigger event: {trigger_event}\n"
            f"{pack_context}\n"
            f"Chart data summary:\n{chart_summary}\n\n"
            "Generate context-aware clinical documentation prompts that the EMS provider "
            "should address. Return a JSON array. Each element must be an object with keys:\n"
            "- prompt_type: one of: " + ", ".join(prompt_types) + "\n"
            "- protocol_pack: the protocol pack name or null\n"
            "- prompt_text: the actual prompt text shown to the provider\n"
            "- field_references: list of NEMSIS field paths this prompt relates to\n\n"
            "Only generate prompts for documentation gaps that are actually evident from "
            "the chart data. If none are needed, return [].\n"
            "IMPORTANT: Respond with ONLY the JSON array, no surrounding text."
        )

        response_text = self._call_claude(user_content)

        try:
            prompts = json.loads(response_text)
            if not isinstance(prompts, list):
                prompts = []
        except (json.JSONDecodeError, ValueError):
            logger.warning("clinical_prompts: failed to parse AI response as JSON list")
            prompts = []

        clean_prompts = []
        for p in prompts:
            if not isinstance(p, dict):
                continue
            clean_prompts.append({
                "prompt_type": str(p.get("prompt_type", "missing_field")),
                "protocol_pack": p.get("protocol_pack") or protocol_pack,
                "prompt_text": str(p.get("prompt_text", "")),
                "field_references": p.get("field_references") or [],
            })
        return clean_prompts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_claude(self, user_content: str) -> str:
        """Call Claude with the cached safety preamble and return response text.

        The SAFETY_PREAMBLE is sent as a cached system block (cache_control
        ephemeral) so it is only billed once per cache TTL window.

        No PHI, prompts, completions, or tokens are written to logs.
        """
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=[
                    {
                        "type": "text",
                        "text": SAFETY_PREAMBLE,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": user_content,
                    }
                ],
            )
            return response.content[0].text if response.content else ""
        except anthropic.APIError as exc:
            logger.error("ai_engine: Anthropic API error: %s", type(exc).__name__)
            raise
        except Exception as exc:
            logger.error("ai_engine: unexpected error calling Claude: %s", type(exc).__name__)
            raise

    def _build_chart_summary(self, chart_data: dict) -> str:
        """Build a structured text summary of chart data for LLM context.

        Deliberately omits raw PHI keys (name, DOB, SSN, address) and only
        surfaces clinical context relevant to documentation quality.
        """
        lines: list[str] = []

        def _add(label: str, key: str) -> None:
            val = chart_data.get(key)
            if val is not None:
                lines.append(f"{label}: {val}")

        # Incident context
        _add("Incident type", "incident_type")
        _add("Chief complaint", "chief_complaint")
        _add("Primary impression", "primary_impression")
        _add("Secondary impression", "secondary_impression")
        _add("Service type", "service_type")
        _add("Level of care", "level_of_care")
        _add("Disposition", "disposition")

        # Patient demographics (non-identifying)
        _add("Patient age (years)", "age_years")
        _add("Patient sex", "sex")
        _add("Patient weight (kg)", "weight_kg")
        _add("Allergies", "allergies")

        # Times
        _add("Dispatch time", "dispatch_time")
        _add("On-scene time", "on_scene_time")
        _add("Patient contact time", "patient_contact_time")
        _add("Transport time", "transport_time")
        _add("Destination arrival time", "destination_arrival_time")

        # Vitals (list or single set)
        vitals = chart_data.get("vitals") or []
        if isinstance(vitals, list):
            for i, v in enumerate(vitals, start=1):
                if isinstance(v, dict):
                    vline = f"Vitals set {i}: " + ", ".join(
                        f"{k}={val}" for k, val in v.items() if val is not None
                    )
                    lines.append(vline)
        elif isinstance(vitals, dict):
            lines.append("Vitals: " + ", ".join(
                f"{k}={v}" for k, v in vitals.items() if v is not None
            ))

        # Medications
        meds = chart_data.get("medications") or []
        if isinstance(meds, list):
            for m in meds:
                if isinstance(m, dict):
                    lines.append(
                        f"Medication: {m.get('medication_name', 'unknown')} "
                        f"{m.get('dose_value', '')} {m.get('dose_unit', '')} "
                        f"via {m.get('route', '')} — indication: {m.get('indication', '')}"
                    )

        # Procedures / interventions
        procedures = chart_data.get("procedures") or chart_data.get("interventions") or []
        if isinstance(procedures, list):
            for p in procedures:
                if isinstance(p, dict):
                    lines.append(
                        f"Procedure/Intervention: {p.get('name', p.get('category', 'unknown'))} "
                        f"at {p.get('performed_at', 'unknown time')}"
                    )

        # Assessment findings
        findings = chart_data.get("findings") or []
        if isinstance(findings, list):
            for f in findings:
                if isinstance(f, dict):
                    lines.append(
                        f"Finding: {f.get('anatomy', '')} / {f.get('system', '')} — "
                        f"{f.get('finding_type', '')} ({f.get('severity', '')})"
                    )

        # Clinical notes (text only, no PHI context)
        notes = chart_data.get("clinical_notes") or []
        if isinstance(notes, list):
            for n in notes:
                if isinstance(n, dict) and n.get("derived_summary"):
                    lines.append(f"Clinical note summary: {n['derived_summary']}")

        # NEMSIS fields (flat dict keyed by NEMSIS element ID)
        nemsis = chart_data.get("nemsis_fields") or {}
        if isinstance(nemsis, dict) and nemsis:
            lines.append("NEMSIS fields present: " + ", ".join(sorted(nemsis.keys())))

        # Arrest context
        _add("Cardiac arrest", "cardiac_arrest")
        _add("Arrest witnessed by", "arrest_witnessed_by")
        _add("Initial rhythm", "initial_rhythm")
        _add("ROSC achieved", "rosc_achieved")

        # Signatures
        sigs = chart_data.get("signatures") or []
        if isinstance(sigs, list) and sigs:
            lines.append(f"Signatures present: {len(sigs)}")

        # Billing
        _add("Payer", "payer")
        _add("Medical necessity reason", "medical_necessity_reason")
        _add("Origin", "origin")
        _add("Destination", "destination")
        _add("Transport miles", "transport_miles")

        if not lines:
            return "(No chart data provided)"

        return "\n".join(lines)
