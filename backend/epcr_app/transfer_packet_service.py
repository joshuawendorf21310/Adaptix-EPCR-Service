"""Transfer packet intelligence service.

Maps transfer document OCR extractions (OcrFieldCandidate rows) into a
structured TransferPacketExtraction and then projects that extraction into
ePCR section-ready review manifests.

This module is intentionally free of FastAPI / SQLAlchemy imports so it can
be unit-tested in isolation.  The only external dependency is the OCR model
layer (OcrFieldCandidate).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# High-risk field keys that must always surface at the top of review queues.
# ---------------------------------------------------------------------------
_HIGH_RISK_FIELDS: frozenset[str] = frozenset(
    {
        "allergies",
        "code_status",
        "dnr_polst_documented",
        "isolation_status",
        "current_infusions",
        "active_lines",
        "vent_settings",
        "oxygen_requirements",
        "primary_diagnosis",
    }
)

# ---------------------------------------------------------------------------
# Mapping: OCR field_name -> (epcr_section, field_key, nemsis_element)
# ---------------------------------------------------------------------------
_OCR_FIELD_MAP: dict[str, tuple[str, str, str | None]] = {
    # ePatient
    "patient_first_name": ("ePatient", "first_name", "ePatient.13"),
    "patient_last_name": ("ePatient", "last_name", "ePatient.15"),
    "patient_dob": ("ePatient", "date_of_birth", "ePatient.17"),
    "patient_sex": ("ePatient", "sex", "ePatient.21"),
    "patient_phone": ("ePatient", "phone_number", "ePatient.20"),
    "patient_weight_kg": ("ePatient", "weight_kg", "ePatient.23"),
    "sending_facility": ("eDisposition", "sending_facility", "eDisposition.02"),
    "receiving_facility": ("eDisposition", "receiving_facility", "eDisposition.03"),
    "transfer_reason": ("eDisposition", "transfer_reason", "eDisposition.12"),
    # eHistory
    "primary_diagnosis": ("eHistory", "primary_diagnosis", "eHistory.17"),
    "pmh": ("eHistory", "past_medical_history", "eHistory.09"),
    "allergies": ("eHistory", "allergies", "eHistory.06"),
    # eMedications (current medications / infusions)
    "current_medications": ("eMedications", "current_medications", "eMedications.03"),
    "current_infusions": ("eMedications", "current_infusions", None),
    # Clinical context
    "active_lines": ("eHistory", "active_lines", None),
    "oxygen_requirements": ("eHistory", "oxygen_requirements", "eVitals.26"),
    "vent_settings": ("eHistory", "vent_settings", None),
    # Labs
    "labs": ("labs", "labs", None),
    # Isolation / code status
    "isolation_status": ("eHistory", "isolation_status", None),
    "code_status": ("eHistory", "code_status", None),
    "dnr_polst_documented": ("eHistory", "dnr_polst_documented", None),
    "mobility_status": ("eHistory", "mobility_status", None),
    # Insurance
    "insurance_info": ("ePatient", "insurance_info", "ePayment.01"),
    # Imaging / procedures / sending provider
    "imaging_findings": ("eHistory", "imaging_findings", None),
    "procedures": ("eHistory", "procedures", None),
    "sending_provider": ("eHistory", "sending_provider", None),
    "receiving_provider": ("eDisposition", "receiving_provider", None),
}


@dataclass
class TransferPacketExtraction:
    """Result of AI+OCR extraction from a transfer document."""

    source_document_id: str
    extraction_id: str
    patient_demographics: dict[str, Any] = field(default_factory=dict)
    sending_facility: str | None = None
    receiving_facility: str | None = None
    primary_diagnosis: str | None = None
    diagnosis_list: list[str] = field(default_factory=list)
    pmh: list[str] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)
    current_medications: list[dict] = field(default_factory=list)
    current_infusions: list[dict] = field(default_factory=list)
    active_lines: list[str] = field(default_factory=list)
    oxygen_requirements: str | None = None
    vent_settings: dict | None = None
    labs: list[dict] = field(default_factory=list)
    imaging_findings: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    isolation_status: str | None = None
    code_status: str | None = None
    dnr_polst_documented: bool = False
    mobility_status: str | None = None
    transfer_reason: str | None = None
    sending_provider: str | None = None
    receiving_provider: str | None = None
    insurance_info: dict | None = None
    pcs_indicators: list[str] = field(default_factory=list)
    confidence_scores: dict[str, float] = field(default_factory=dict)
    review_required_fields: list[str] = field(default_factory=list)
    raw_text: str = ""
    extraction_warnings: list[str] = field(default_factory=list)


class TransferPacketService:
    """Maps transfer document extractions to ePCR chart sections.

    Uses OCR field candidates and normalises them into a
    TransferPacketExtraction that the review manifest builder can consume.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_from_ocr_candidates(
        self,
        candidates: list,  # list[OcrFieldCandidate]
        chart_id: str,
        tenant_id: str,
    ) -> TransferPacketExtraction:
        """Build a TransferPacketExtraction from a list of OcrFieldCandidates.

        Each OcrFieldCandidate carries field_name, extracted_value /
        normalized_value, confidence_score, and review_status.  We collect
        those into the typed extraction dataclass and record per-field
        confidence scores so the manifest can sort by risk + confidence.
        """
        extraction = TransferPacketExtraction(
            source_document_id=chart_id,
            extraction_id=f"tp-{chart_id}",
        )
        confidence_scores: dict[str, float] = {}
        review_required: list[str] = []
        raw_parts: list[str] = []
        warnings: list[str] = []

        for c in candidates:
            fname: str = getattr(c, "field_name", "")
            value: str = (
                getattr(c, "normalized_value", None)
                or getattr(c, "extracted_value", "")
                or ""
            )
            score: float = float(getattr(c, "confidence_score", 0.0))
            confidence_scores[fname] = score
            raw_parts.append(f"{fname}: {value}")

            if score < 0.75 or fname in _HIGH_RISK_FIELDS:
                review_required.append(fname)

            self._apply_candidate(extraction, fname, value, warnings)

        # High-risk fields always require review regardless of confidence
        for hr in _HIGH_RISK_FIELDS:
            if hr not in review_required:
                review_required.append(hr)

        extraction.confidence_scores = confidence_scores
        extraction.review_required_fields = list(dict.fromkeys(review_required))
        extraction.raw_text = "\n".join(raw_parts)
        extraction.extraction_warnings = warnings
        return extraction

    def map_to_epcr_sections(
        self, extraction: TransferPacketExtraction
    ) -> dict[str, list[dict]]:
        """Map extraction to ePCR sections ready for the review queue.

        Returns a dict keyed by section name, each value a list of field
        dicts with keys: field_key, nemsis_element, value, confidence, high_risk.
        """
        sections: dict[str, list[dict]] = {
            "eHistory": [],
            "eMedications": [],
            "ePatient": [],
            "allergies": [],
            "labs": [],
            "eDisposition": [],
        }

        def _put(section: str, field_key: str, nemsis_element: str | None, value: Any) -> None:
            if value is None or value == "" or value == [] or value == {}:
                return
            confidence = extraction.confidence_scores.get(field_key, 0.0)
            sections.setdefault(section, []).append(
                {
                    "field_key": field_key,
                    "nemsis_element": nemsis_element,
                    "value": value,
                    "confidence": confidence,
                    "high_risk": field_key in _HIGH_RISK_FIELDS,
                }
            )

        # ePatient
        if extraction.patient_demographics:
            for k, v in extraction.patient_demographics.items():
                _put("ePatient", k, None, v)
        _put("ePatient", "insurance_info", "ePayment.01", extraction.insurance_info)

        # eHistory
        _put("eHistory", "primary_diagnosis", "eHistory.17", extraction.primary_diagnosis)
        _put("eHistory", "past_medical_history", "eHistory.09", extraction.pmh or None)
        _put("eHistory", "active_lines", None, extraction.active_lines or None)
        _put("eHistory", "oxygen_requirements", "eVitals.26", extraction.oxygen_requirements)
        _put("eHistory", "vent_settings", None, extraction.vent_settings)
        _put("eHistory", "isolation_status", None, extraction.isolation_status)
        _put("eHistory", "code_status", None, extraction.code_status)
        _put("eHistory", "dnr_polst_documented", None, extraction.dnr_polst_documented)
        _put("eHistory", "mobility_status", None, extraction.mobility_status)
        _put("eHistory", "imaging_findings", None, extraction.imaging_findings or None)
        _put("eHistory", "procedures", None, extraction.procedures or None)
        _put("eHistory", "sending_provider", None, extraction.sending_provider)

        # allergies (own section so the UI can surface them prominently)
        if extraction.allergies:
            for i, allergy in enumerate(extraction.allergies):
                sections["allergies"].append(
                    {
                        "field_key": f"allergy_{i}",
                        "nemsis_element": "eHistory.06",
                        "value": allergy,
                        "confidence": extraction.confidence_scores.get("allergies", 0.0),
                        "high_risk": True,
                    }
                )

        # eMedications
        if extraction.current_medications:
            _put("eMedications", "current_medications", "eMedications.03", extraction.current_medications)
        if extraction.current_infusions:
            _put("eMedications", "current_infusions", None, extraction.current_infusions)

        # labs
        if extraction.labs:
            for lab in extraction.labs:
                sections["labs"].append(
                    {
                        "field_key": lab.get("name", "lab"),
                        "nemsis_element": None,
                        "value": lab,
                        "confidence": extraction.confidence_scores.get("labs", 0.0),
                        "high_risk": bool(lab.get("abnormal_flag")),
                    }
                )

        # eDisposition
        _put("eDisposition", "sending_facility", "eDisposition.02", extraction.sending_facility)
        _put("eDisposition", "receiving_facility", "eDisposition.03", extraction.receiving_facility)
        _put("eDisposition", "transfer_reason", "eDisposition.12", extraction.transfer_reason)
        _put("eDisposition", "receiving_provider", None, extraction.receiving_provider)

        return sections

    def build_review_manifest(self, mapped_sections: dict) -> dict:
        """Build a flat review manifest sorted by: high_risk first, then confidence ascending.

        Lower confidence items appear earlier so reviewers tackle the least
        certain fields (after clearing all high-risk items first).
        """
        all_items: list[dict] = []
        for section, fields in mapped_sections.items():
            for f in fields:
                all_items.append({**f, "section": section})

        # Sort: high_risk=True first, then confidence ascending (lowest confidence reviewed first)
        all_items.sort(
            key=lambda x: (not x.get("high_risk", False), x.get("confidence", 1.0))
        )

        return {
            "total": len(all_items),
            "high_risk_count": sum(1 for x in all_items if x.get("high_risk")),
            "items": all_items,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_candidate(
        self,
        extraction: TransferPacketExtraction,
        field_name: str,
        value: str,
        warnings: list[str],
    ) -> None:
        """Apply a single candidate value onto the extraction dataclass."""
        if field_name == "patient_first_name":
            extraction.patient_demographics["first_name"] = value
        elif field_name == "patient_last_name":
            extraction.patient_demographics["last_name"] = value
        elif field_name == "patient_dob":
            extraction.patient_demographics["date_of_birth"] = value
        elif field_name == "patient_sex":
            extraction.patient_demographics["sex"] = value
        elif field_name == "patient_phone":
            extraction.patient_demographics["phone_number"] = value
        elif field_name == "patient_weight_kg":
            try:
                extraction.patient_demographics["weight_kg"] = float(value)
            except (ValueError, TypeError):
                warnings.append(f"Could not parse patient_weight_kg: {value!r}")
        elif field_name == "sending_facility":
            extraction.sending_facility = value
        elif field_name == "receiving_facility":
            extraction.receiving_facility = value
        elif field_name == "primary_diagnosis":
            extraction.primary_diagnosis = value
        elif field_name == "pmh":
            extraction.pmh = [v.strip() for v in value.split(",") if v.strip()] if isinstance(value, str) else list(value)
        elif field_name == "allergies":
            extraction.allergies = [v.strip() for v in value.split(",") if v.strip()] if isinstance(value, str) else list(value)
        elif field_name == "current_medications":
            import json
            try:
                extraction.current_medications = json.loads(value) if isinstance(value, str) else list(value)
            except Exception:
                extraction.current_medications = [{"raw": value}]
        elif field_name == "current_infusions":
            import json
            try:
                extraction.current_infusions = json.loads(value) if isinstance(value, str) else list(value)
            except Exception:
                extraction.current_infusions = [{"raw": value}]
        elif field_name == "active_lines":
            extraction.active_lines = [v.strip() for v in value.split(",") if v.strip()] if isinstance(value, str) else list(value)
        elif field_name == "oxygen_requirements":
            extraction.oxygen_requirements = value
        elif field_name == "vent_settings":
            import json
            try:
                extraction.vent_settings = json.loads(value) if isinstance(value, str) else dict(value)
            except Exception:
                extraction.vent_settings = {"raw": value}
        elif field_name == "labs":
            import json
            try:
                extraction.labs = json.loads(value) if isinstance(value, str) else list(value)
            except Exception:
                extraction.labs = [{"raw": value}]
        elif field_name == "imaging_findings":
            extraction.imaging_findings = [v.strip() for v in value.split(";") if v.strip()] if isinstance(value, str) else list(value)
        elif field_name == "procedures":
            extraction.procedures = [v.strip() for v in value.split(";") if v.strip()] if isinstance(value, str) else list(value)
        elif field_name == "isolation_status":
            extraction.isolation_status = value
        elif field_name == "code_status":
            extraction.code_status = value
        elif field_name == "dnr_polst_documented":
            extraction.dnr_polst_documented = value.lower() in {"true", "yes", "1"}
        elif field_name == "mobility_status":
            extraction.mobility_status = value
        elif field_name == "transfer_reason":
            extraction.transfer_reason = value
        elif field_name == "sending_provider":
            extraction.sending_provider = value
        elif field_name == "receiving_provider":
            extraction.receiving_provider = value
        elif field_name == "insurance_info":
            import json
            try:
                extraction.insurance_info = json.loads(value) if isinstance(value, str) else dict(value)
            except Exception:
                extraction.insurance_info = {"raw": value}
        else:
            logger.debug("TransferPacketService: unmapped OCR field %r", field_name)


__all__ = ["TransferPacketExtraction", "TransferPacketService"]
