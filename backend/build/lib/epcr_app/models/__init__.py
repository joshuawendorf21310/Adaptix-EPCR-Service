"""epcr models sub-package init.

Exposes all new OCR, transport link, NEMSIS binding, and structured
extraction models. Defines Base inline and re-exports core models
from epcr_app.models_core so callers can import from this package.
"""
import importlib
import sys
from pathlib import Path

# Load the sibling models.py file directly since the package shadows it.
_models_file = Path(__file__).resolve().parent.parent / "models.py"
_spec = importlib.util.spec_from_file_location("epcr_app._models_core", str(_models_file))
_models_core = importlib.util.module_from_spec(_spec)
sys.modules["epcr_app._models_core"] = _models_core
_spec.loader.exec_module(_models_core)

# Re-export everything from the core models file
from epcr_app._models_core import (
    Base,
    Chart,
    ChartStatus,
    ComplianceStatus,
    FieldSource,
    Vitals,
    Assessment,
    NemsisMappingRecord,
    NemsisCompliance,
    NemsisExportHistory,
    EpcrAuditLog,
)
from epcr_app.models.ocr import (
    OcrSourceType,
    OcrJobStatus,
    OcrFieldConfidence,
    OcrJob,
    OcrSource,
    OcrResult,
    OcrFieldCandidate,
    OcrFieldReview,
)
from epcr_app.models.transport_link import (
    CareTransportLink,
    CareEncounterArtifactLink,
    CareOcrReviewQueue,
)
from epcr_app.models.nemsis_binding import (
    NemsisBidingStatus,
    NemsisFieldBinding,
    NemsisBindingReview,
    NemsisExportReadinessSnapshot,
    CareNemsisTransportBindingLink,
)
from epcr_app.models.extract import TransportStructuredExtraction

__all__ = [
    "Base",
    "Chart",
    "ChartStatus",
    "ComplianceStatus",
    "FieldSource",
    "Vitals",
    "Assessment",
    "NemsisMappingRecord",
    "NemsisCompliance",
    "NemsisExportHistory",
    "EpcrAuditLog",
    "OcrSourceType",
    "OcrJobStatus",
    "OcrFieldConfidence",
    "OcrJob",
    "OcrSource",
    "OcrResult",
    "OcrFieldCandidate",
    "OcrFieldReview",
    "CareTransportLink",
    "CareEncounterArtifactLink",
    "CareOcrReviewQueue",
    "NemsisBidingStatus",
    "NemsisFieldBinding",
    "NemsisBindingReview",
    "NemsisExportReadinessSnapshot",
    "CareNemsisTransportBindingLink",
    "TransportStructuredExtraction",
]
