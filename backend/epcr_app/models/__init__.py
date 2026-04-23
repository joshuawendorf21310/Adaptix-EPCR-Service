"""Gravity-level shared ORM model exports.

Authoritative aggregation layer for all ORM models used across:
- core clinical domain
- OCR ingestion and review
- structured extraction
- transport-link artifacts
- NEMSIS binding and export readiness

This module enforces:
- explicit export surface (no wildcard leakage)
- zero duplicate symbol exposure
- stable import boundary for all downstream services
"""

from __future__ import annotations

# -------------------------
# Core Models
# -------------------------

from epcr_app.models.core import (
    Base,
    Chart,
    ChartStatus,
    ComplianceStatus,
    FieldSource,
    ReviewState,
    FindingEvolution,
    ArSessionStatus,
    AddressValidationState,
    ProtocolFamily,
    InterventionExportState,
    ClinicalNoteReviewState,
    ProtocolRecommendationState,
    DerivedOutputType,
    Vitals,
    Assessment,
    PatientProfile,
    AssessmentFinding,
    VisualOverlay,
    ArSession,
    ArAnchor,
    ChartAddress,
    MedicationAdministration,
    EpcrSignatureArtifact,
    ClinicalIntervention,
    ClinicalNote,
    ProtocolRecommendation,
    DerivedChartOutput,
    NemsisMappingRecord,
    NemsisCompliance,
    NemsisExportHistory,
    EpcrAuditLog,
)

# -------------------------
# OCR Models
# -------------------------

from epcr_app.models.ocr import (
    OcrSourceType,
    OcrJobStatus,
    OcrFieldConfidence,
    OcrFieldReviewAction,
    OcrFieldReviewStatus,
    OcrJob,
    OcrSource,
    OcrResult,
    OcrFieldCandidate,
    OcrFieldReview,
)

# -------------------------
# Transport Link Models
# -------------------------

from epcr_app.models.transport_link import (
    CareTransportLink,
    CareEncounterArtifactLink,
    CareOcrReviewQueue,
)

# -------------------------
# NEMSIS Binding Models
# -------------------------

from epcr_app.models.nemsis_binding import (
    NemsisBindingStatus,
    NemsisBindingReviewAction,
    NemsisFieldBinding,
    NemsisBindingReview,
    NemsisExportReadinessSnapshot,
    NemsisBindingSourceLink,
)

# -------------------------
# Structured Extraction
# -------------------------

from epcr_app.models.structured_extraction import StructuredExtraction


# -------------------------
# Explicit Export Surface
# -------------------------

__all__ = [
    # Base
    "Base",

    # Core
    "Chart",
    "ChartStatus",
    "ComplianceStatus",
    "FieldSource",
    "ReviewState",
    "FindingEvolution",
    "ArSessionStatus",
    "AddressValidationState",
    "ProtocolFamily",
    "InterventionExportState",
    "ClinicalNoteReviewState",
    "ProtocolRecommendationState",
    "DerivedOutputType",
    "Vitals",
    "Assessment",
    "PatientProfile",
    "AssessmentFinding",
    "VisualOverlay",
    "ArSession",
    "ArAnchor",
    "ChartAddress",
    "MedicationAdministration",
    "EpcrSignatureArtifact",
    "ClinicalIntervention",
    "ClinicalNote",
    "ProtocolRecommendation",
    "DerivedChartOutput",
    "NemsisMappingRecord",
    "NemsisCompliance",
    "NemsisExportHistory",
    "EpcrAuditLog",

    # OCR
    "OcrSourceType",
    "OcrJobStatus",
    "OcrFieldConfidence",
    "OcrFieldReviewAction",
    "OcrFieldReviewStatus",
    "OcrJob",
    "OcrSource",
    "OcrResult",
    "OcrFieldCandidate",
    "OcrFieldReview",

    # Transport
    "CareTransportLink",
    "CareEncounterArtifactLink",
    "CareOcrReviewQueue",

    # NEMSIS Binding
    "NemsisBindingStatus",
    "NemsisBindingReviewAction",
    "NemsisFieldBinding",
    "NemsisBindingReview",
    "NemsisExportReadinessSnapshot",
    "NemsisBindingSourceLink",

    # Structured Extraction
    "StructuredExtraction",
]


# -------------------------
# Integrity Enforcement
# -------------------------

def _validate_no_duplicates():
    seen = set()
    duplicates = set()

    for name in __all__:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    if duplicates:
        raise RuntimeError(f"Duplicate exports detected in models package: {duplicates}")


def _validate_symbol_resolution():
    missing = []

    for name in __all__:
        if name not in globals():
            missing.append(name)

    if missing:
        raise RuntimeError(f"Missing model exports: {missing}")


_validate_no_duplicates()
_validate_symbol_resolution()