"""Stable ORM export boundary for the EPCR service.

The repository contains both a legacy flat module at `epcr_app/models.py` and a
package at `epcr_app/models/`. This package intentionally re-exports the real
ORM symbols from the legacy module file so downstream imports from
`epcr_app.models` continue to work even when the package shadows the module.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_legacy_models_module():
    module_path = Path(__file__).resolve().parents[1] / "models.py"
    spec = importlib.util.spec_from_file_location("epcr_app._legacy_models", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load legacy models module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_legacy_models = _load_legacy_models_module()

Base = _legacy_models.Base
Chart = _legacy_models.Chart
ChartStatus = _legacy_models.ChartStatus
ComplianceStatus = _legacy_models.ComplianceStatus
FieldSource = _legacy_models.FieldSource
ReviewState = _legacy_models.ReviewState
FindingEvolution = _legacy_models.FindingEvolution
ArSessionStatus = _legacy_models.ArSessionStatus
AddressValidationState = _legacy_models.AddressValidationState
ProtocolFamily = _legacy_models.ProtocolFamily
InterventionExportState = _legacy_models.InterventionExportState
ClinicalNoteReviewState = _legacy_models.ClinicalNoteReviewState
ProtocolRecommendationState = _legacy_models.ProtocolRecommendationState
DerivedOutputType = _legacy_models.DerivedOutputType
Vitals = _legacy_models.Vitals
Assessment = _legacy_models.Assessment
PatientProfile = _legacy_models.PatientProfile
AssessmentFinding = _legacy_models.AssessmentFinding
VisualOverlay = _legacy_models.VisualOverlay
ArSession = _legacy_models.ArSession
ArAnchor = _legacy_models.ArAnchor
ChartAddress = _legacy_models.ChartAddress
MedicationAdministration = _legacy_models.MedicationAdministration
EpcrSignatureArtifact = _legacy_models.EpcrSignatureArtifact
ClinicalIntervention = _legacy_models.ClinicalIntervention
ClinicalNote = _legacy_models.ClinicalNote
ProtocolRecommendation = _legacy_models.ProtocolRecommendation
DerivedChartOutput = _legacy_models.DerivedChartOutput
NemsisMappingRecord = _legacy_models.NemsisMappingRecord
NemsisCompliance = _legacy_models.NemsisCompliance
NemsisExportHistory = _legacy_models.NemsisExportHistory
EpcrAuditLog = _legacy_models.EpcrAuditLog

from epcr_app.models.ocr import (  # noqa: E402
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
from epcr_app.models.transport_link import (  # noqa: E402
    CareTransportLink,
    CareEncounterArtifactLink,
    CareOcrReviewQueue,
)
from epcr_app.models.nemsis_binding import (  # noqa: E402
    NemsisBindingStatus,
    NemsisBindingReviewAction,
    NemsisFieldBinding,
    NemsisBindingReview,
    NemsisExportReadinessSnapshot,
    NemsisBindingSourceLink,
)
from epcr_app.models.structured_extraction import StructuredExtraction  # noqa: E402

__all__ = [
    "Base",
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
    "CareTransportLink",
    "CareEncounterArtifactLink",
    "CareOcrReviewQueue",
    "NemsisBindingStatus",
    "NemsisBindingReviewAction",
    "NemsisFieldBinding",
    "NemsisBindingReview",
    "NemsisExportReadinessSnapshot",
    "NemsisBindingSourceLink",
    "StructuredExtraction",
]
