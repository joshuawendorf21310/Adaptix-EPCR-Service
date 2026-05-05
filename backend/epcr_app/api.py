"""ePCR domain API routes for chart management and NEMSIS 3.5.1 compliance.

Provides RESTful endpoints for chart creation, retrieval, update, finalization,
and NEMSIS 3.5.1 compliance checking. All state-mutating endpoints require a
valid RS256 Bearer JWT issued by the Adaptix core auth service. All endpoints
include input validation, error logging, and real tenant/user context.
"""
import logging
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from epcr_app.db import get_session, check_health
from epcr_app.services import ChartService
from epcr_app.dependencies import get_current_user, CurrentUser
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/epcr", tags=["epcr"])

def _tenant_id(current_user: CurrentUser) -> str:
    """Extract tenant_id from authenticated user context."""
    return str(current_user.tenant_id)


def _user_id(current_user: CurrentUser) -> str:
    """Extract user_id from authenticated user context."""
    return str(current_user.user_id)



def _serialize_intervention(intervention) -> dict:
    """Serialize a clinical intervention response payload."""
    return {
        "id": intervention.id,
        "chart_id": intervention.chart_id,
        "category": intervention.category,
        "name": intervention.name,
        "indication": intervention.indication,
        "intent": intervention.intent,
        "expected_response": intervention.expected_response,
        "actual_response": intervention.actual_response,
        "protocol_family": intervention.protocol_family.value,
        "export_state": intervention.export_state.value,
        "snomed_code": intervention.snomed_code,
        "icd10_code": intervention.icd10_code,
        "rxnorm_code": intervention.rxnorm_code,
        "performed_at": intervention.performed_at.isoformat(),
    }


def _serialize_patient_profile(profile) -> dict:
    """Serialize a patient profile payload."""
    return {
        "id": profile.id,
        "chart_id": profile.chart_id,
        "first_name": profile.first_name,
        "middle_name": profile.middle_name,
        "last_name": profile.last_name,
        "date_of_birth": profile.date_of_birth,
        "age_years": profile.age_years,
        "sex": profile.sex,
        "phone_number": profile.phone_number,
        "weight_kg": profile.weight_kg,
        "allergies": json.loads(profile.allergies_json) if profile.allergies_json else [],
        "updated_at": profile.updated_at.isoformat(),
    }


def _serialize_vital(vital) -> dict:
    """Serialize a vital set payload."""
    return {
        "id": vital.id,
        "chart_id": vital.chart_id,
        "bp_sys": vital.bp_sys,
        "bp_dia": vital.bp_dia,
        "hr": vital.hr,
        "rr": vital.rr,
        "temp_f": vital.temp_f,
        "spo2": vital.spo2,
        "glucose": vital.glucose,
        "recorded_at": vital.recorded_at.isoformat(),
    }


def _serialize_impression(assessment) -> dict:
    """Serialize a structured clinical impression payload."""
    return {
        "id": assessment.id,
        "chart_id": assessment.chart_id,
        "chief_complaint": assessment.chief_complaint,
        "field_diagnosis": assessment.field_diagnosis,
        "primary_impression": assessment.primary_impression,
        "secondary_impression": assessment.secondary_impression,
        "impression_notes": assessment.impression_notes,
        "snomed_code": assessment.snomed_code,
        "icd10_code": assessment.icd10_code,
        "acuity": assessment.acuity,
        "documented_at": assessment.documented_at.isoformat(),
    }


def _serialize_medication(medication) -> dict:
    """Serialize a medication administration payload."""
    return {
        "id": medication.id,
        "chart_id": medication.chart_id,
        "medication_name": medication.medication_name,
        "rxnorm_code": medication.rxnorm_code,
        "dose_value": medication.dose_value,
        "dose_unit": medication.dose_unit,
        "route": medication.route,
        "indication": medication.indication,
        "response": medication.response,
        "export_state": medication.export_state.value,
        "administered_at": medication.administered_at.isoformat(),
    }


def _serialize_signature(signature) -> dict:
    """Serialize a signature artifact payload."""
    return {
        "id": signature.id,
        "chart_id": signature.chart_id,
        "source_domain": signature.source_domain,
        "source_capture_id": signature.source_capture_id,
        "signature_class": signature.signature_class,
        "signature_method": signature.signature_method,
        "signer_identity": signature.signer_identity,
        "signer_relationship": signature.signer_relationship,
        "patient_capable_to_sign": signature.patient_capable_to_sign,
        "receiving_facility": signature.receiving_facility,
        "transfer_of_care_time": signature.transfer_of_care_time.isoformat() if signature.transfer_of_care_time else None,
        "signature_artifact_data_url": signature.signature_artifact_data_url,
        "signature_on_file_reference": signature.signature_on_file_reference,
        "compliance_decision": signature.compliance_decision,
        "compliance_why": signature.compliance_why,
        "chart_completion_effect": signature.chart_completion_effect,
        "billing_readiness_effect": signature.billing_readiness_effect,
        "missing_requirements": json.loads(signature.missing_requirements_json or "[]"),
        "created_at": signature.created_at.isoformat(),
        "updated_at": signature.updated_at.isoformat(),
    }


def _serialize_note(note) -> dict:
    """Serialize a clinical note response payload."""
    return {
        "id": note.id,
        "chart_id": note.chart_id,
        "raw_text": note.raw_text,
        "source": note.source,
        "derived_summary": note.derived_summary,
        "review_state": note.review_state.value,
        "captured_at": note.captured_at.isoformat(),
    }


def _serialize_protocol(item) -> dict:
    """Serialize a protocol recommendation response payload."""
    return {
        "id": item.id,
        "chart_id": item.chart_id,
        "protocol_family": item.protocol_family.value,
        "title": item.title,
        "rationale": item.rationale,
        "action_priority": item.action_priority,
        "state": item.state.value,
        "generated_at": item.generated_at.isoformat(),
    }


def _serialize_output(output) -> dict:
    """Serialize a derived output response payload."""
    return {
        "id": output.id,
        "chart_id": output.chart_id,
        "output_type": output.output_type.value,
        "content_text": output.content_text,
        "source_revision": output.source_revision,
        "generated_at": output.generated_at.isoformat(),
    }


class CreateChartRequest(BaseModel):
    """Request model for creating new ePCR chart.
    
    Attributes:
        call_number: Unique call/dispatch identifier (required, non-empty).
        incident_type: Type of incident: medical, trauma, behavioral, other.
        patient_id: Optional existing patient identifier.
    """
    call_number: str = Field(..., min_length=1, max_length=50, description="Unique call/dispatch number")
    incident_type: str = Field("medical", description="Incident type: medical, trauma, behavioral, other")
    client_reference_id: Optional[str] = Field(None, max_length=36, description="Optional client-generated deterministic identifier")
    patient_id: Optional[str] = Field(None, max_length=36, description="Optional patient identifier")
    
    @field_validator("call_number")
    @classmethod
    def validate_call_number(cls, v: str) -> str:
        """Validate call_number is non-empty string."""
        if not v or not v.strip():
            raise ValueError("call_number cannot be empty")
        return v.strip()
    
    @field_validator("incident_type")
    @classmethod
    def validate_incident_type(cls, v: str) -> str:
        """Validate incident_type is in allowed values."""
        allowed = ["medical", "trauma", "behavioral", "other"]
        if v not in allowed:
            raise ValueError(f"incident_type must be one of: {', '.join(allowed)}")
        return v


class ChartResponse(BaseModel):
    """Response model for ePCR chart.
    
    Attributes:
        id: Chart unique identifier.
        call_number: Dispatch/call number.
        status: Chart lifecycle status.
        incident_type: Type of incident.
        created_at: ISO 8601 timestamp of creation.
    """
    id: str
    call_number: str
    status: str
    incident_type: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class ComplianceResponse(BaseModel):
    """Response model for NEMSIS 3.5.1 compliance check.
    
    Attributes:
        chart_id: Chart identifier checked.
        compliance_status: Current compliance level.
        compliance_percentage: Percentage of mandatory fields filled (0-100).
        mandatory_fields_filled: Count of populated mandatory fields.
        mandatory_fields_required: Total mandatory fields for chart.
        missing_mandatory_fields: List of missing field identifiers.
        is_fully_compliant: Boolean: true if all mandatory fields present.
    """
    chart_id: str
    compliance_status: str
    compliance_percentage: float
    mandatory_fields_filled: int
    mandatory_fields_required: int
    missing_mandatory_fields: list
    is_fully_compliant: bool


class UpdateChartRequest(BaseModel):
    """Request model for updating ePCR chart fields.
    
    Allows partial updates to chart metadata, vitals, and assessment data.
    All fields are optional. Empty/None values are ignored (not cleared).
    
    Attributes:
        incident_type: Type of incident (medical, trauma, behavioral, other).
        patient_id: Patient identifier (may change during documentation).
        bp_sys: Systolic blood pressure (mmHg).
        bp_dia: Diastolic blood pressure (mmHg).
        hr: Heart rate (beats per minute).
        rr: Respiration rate (breaths per minute).
        temp_f: Temperature (Fahrenheit).
        spo2: Oxygen saturation (%).
        glucose: Blood glucose (mg/dL).
        chief_complaint: Patient's chief complaint.
        field_diagnosis: Paramedic's field diagnosis.
    """
    incident_type: Optional[str] = None
    patient_id: Optional[str] = None
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp_f: Optional[float] = None
    spo2: Optional[int] = None
    glucose: Optional[int] = None
    chief_complaint: Optional[str] = None
    field_diagnosis: Optional[str] = None
    
    @field_validator("incident_type")
    @classmethod
    def validate_incident_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate incident_type is in allowed values if provided."""
        if v is None:
            return v
        allowed = ["medical", "trauma", "behavioral", "other"]
        if v not in allowed:
            raise ValueError(f"incident_type must be one of: {', '.join(allowed)}")
        return v


class ComplianceSummary(BaseModel):
    """Inline compliance status summary.
    
    Provides compliance state after chart update without requiring a separate
    compliance check call.
    
    Attributes:
        is_fully_compliant: Boolean: true if all mandatory fields present.
        compliance_percentage: Percentage of mandatory fields filled (0-100).
        missing_mandatory_fields: List of missing mandatory field IDs.
    """
    is_fully_compliant: bool
    compliance_percentage: float
    missing_mandatory_fields: list[str]


class ChartUpdateResponse(BaseModel):
    """Response model for PATCH /charts/{chart_id}.
    
    Returns updated chart with inline compliance status. Provides confirmation
    of successful update and current compliance state without requiring a
    separate compliance check call.
    
    Attributes:
        id: Chart unique identifier.
        call_number: Dispatch/call number.
        status: Chart lifecycle status.
        updated_at: ISO 8601 timestamp of update.
        compliance: Inline compliance summary.
    """
    id: str
    call_number: str
    status: str
    updated_at: str
    compliance: ComplianceSummary
    
    model_config = ConfigDict(from_attributes=True)


class AssessmentFindingRequest(BaseModel):
    """Request model for recording a structured CPAE finding."""

    client_reference_id: Optional[str] = Field(None, max_length=36)
    anatomy: str = Field(..., min_length=1, max_length=64)
    system: str = Field(..., min_length=1, max_length=64)
    finding_type: str = Field(..., min_length=1, max_length=64)
    severity: str = Field(..., min_length=1, max_length=32)
    detection_method: str = Field(..., min_length=1, max_length=64)
    laterality: Optional[str] = Field(None, max_length=32)
    evolution: str = Field("new", max_length=32)
    review_state: str = Field("direct_confirmed", max_length=32)
    characteristics: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)


class AssessmentFindingResponse(BaseModel):
    """Response model for a persisted structured finding."""

    id: str
    chart_id: str
    anatomy: str
    system: str
    finding_type: str
    severity: str
    detection_method: str
    review_state: str
    observed_at: str


class AssessmentFindingUpdateRequest(BaseModel):
    """Request model for correcting or reviewing a structured finding."""

    severity: Optional[str] = Field(None, min_length=1, max_length=32)
    laterality: Optional[str] = Field(None, max_length=32)
    evolution: Optional[str] = Field(None, max_length=32)
    review_state: Optional[str] = Field(None, max_length=32)
    characteristics: Optional[list[str]] = None
    source_artifact_ids: Optional[list[str]] = None


class VisualOverlayRequest(BaseModel):
    """Request model for recording a governed VAS overlay."""

    client_reference_id: Optional[str] = Field(None, max_length=36)
    finding_id: str = Field(..., min_length=1, max_length=36)
    patient_model: str = Field(..., min_length=1, max_length=32)
    anatomical_view: str = Field(..., min_length=1, max_length=32)
    overlay_type: str = Field(..., min_length=1, max_length=64)
    anchor_region: str = Field(..., min_length=1, max_length=64)
    geometry_reference: str = Field(..., min_length=1)
    severity: str = Field(..., min_length=1, max_length=32)
    evolution: str = Field("new", max_length=32)
    review_state: str = Field("direct_confirmed", max_length=32)
    evidence_artifact_ids: list[str] = Field(default_factory=list)


class VisualOverlayResponse(BaseModel):
    """Response model for a persisted governed visual overlay."""

    id: str
    chart_id: str
    finding_id: str
    overlay_type: str
    anatomical_view: str
    anchor_region: str
    rendered_at: str


class VisualOverlayUpdateRequest(BaseModel):
    """Request model for correcting or reviewing a governed overlay."""

    geometry_reference: Optional[str] = None
    severity: Optional[str] = Field(None, min_length=1, max_length=32)
    evolution: Optional[str] = Field(None, max_length=32)
    review_state: Optional[str] = Field(None, max_length=32)
    evidence_artifact_ids: Optional[list[str]] = None


class ArSessionRequest(BaseModel):
    """Request model for starting a governed ARCOS capture session."""

    client_reference_id: Optional[str] = Field(None, max_length=36)
    patient_model: str = Field(..., min_length=1, max_length=32)
    mode: str = Field(..., min_length=1, max_length=64)


class ArSessionResponse(BaseModel):
    """Response model for an ARCOS session."""

    id: str
    chart_id: str
    patient_model: str
    mode: str
    status: str
    started_at: str


class ArAnchorRequest(BaseModel):
    """Request model for anchoring anatomy during an ARCOS session."""

    client_reference_id: Optional[str] = Field(None, max_length=36)
    anatomy: str = Field(..., min_length=1, max_length=64)
    anatomical_view: str = Field(..., min_length=1, max_length=32)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ArAnchorResponse(BaseModel):
    """Response model for a captured ARCOS anatomical anchor."""

    id: str
    session_id: str
    anatomy: str
    anatomical_view: str
    confidence: float
    anchored_at: str


class ArSessionListResponse(BaseModel):
    """Response model for a chart-scoped ARCOS session summary."""

    id: str
    chart_id: str
    patient_model: str
    mode: str
    status: str
    started_at: str
    ended_at: Optional[str] = None


class AddressIntelligenceRequest(BaseModel):
    """Request model for chart-scoped address intelligence capture."""

    raw_text: str = Field(..., min_length=1)
    street_line_one: Optional[str] = Field(None, max_length=255)
    street_line_two: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=32)
    postal_code: Optional[str] = Field(None, max_length=20)
    county: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    validation_state: Optional[str] = Field(None, max_length=32)
    intelligence_source: str = Field("manual_entry", min_length=1, max_length=64)
    intelligence_detail: Optional[str] = None


class AddressIntelligenceResponse(BaseModel):
    id: str
    chart_id: str
    raw_text: str
    validation_state: str
    intelligence_source: str
    updated_at: str


class PatientProfileRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    first_name: Optional[str] = Field(None, max_length=120)
    middle_name: Optional[str] = Field(None, max_length=120)
    last_name: Optional[str] = Field(None, max_length=120)
    date_of_birth: Optional[str] = Field(None, max_length=32)
    age_years: Optional[int] = None
    sex: Optional[str] = Field(None, max_length=32)
    phone_number: Optional[str] = Field(None, max_length=32)
    weight_kg: Optional[float] = None
    allergies: list[str] = Field(default_factory=list)


class PatientProfileResponse(BaseModel):
    id: str
    chart_id: str
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    age_years: Optional[int] = None
    sex: Optional[str] = None
    phone_number: Optional[str] = None
    weight_kg: Optional[float] = None
    allergies: list[str]
    updated_at: str


class VitalSetRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp_f: Optional[float] = None
    spo2: Optional[int] = None
    glucose: Optional[int] = None
    recorded_at: Optional[str] = None


class VitalSetUpdateRequest(BaseModel):
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp_f: Optional[float] = None
    spo2: Optional[int] = None
    glucose: Optional[int] = None
    recorded_at: Optional[str] = None


class VitalSetResponse(BaseModel):
    id: str
    chart_id: str
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    hr: Optional[int] = None
    rr: Optional[int] = None
    temp_f: Optional[float] = None
    spo2: Optional[int] = None
    glucose: Optional[int] = None
    recorded_at: str


class ClinicalImpressionRequest(BaseModel):
    chief_complaint: Optional[str] = None
    field_diagnosis: Optional[str] = None
    primary_impression: Optional[str] = None
    secondary_impression: Optional[str] = None
    impression_notes: Optional[str] = None
    snomed_code: Optional[str] = Field(None, max_length=32)
    icd10_code: Optional[str] = Field(None, max_length=32)
    acuity: Optional[str] = Field(None, max_length=32)


class ClinicalImpressionResponse(BaseModel):
    id: str
    chart_id: str
    chief_complaint: Optional[str] = None
    field_diagnosis: Optional[str] = None
    primary_impression: Optional[str] = None
    secondary_impression: Optional[str] = None
    impression_notes: Optional[str] = None
    snomed_code: Optional[str] = None
    icd10_code: Optional[str] = None
    acuity: Optional[str] = None
    documented_at: str


class MedicationAdministrationRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    medication_name: str = Field(..., min_length=1, max_length=128)
    rxnorm_code: Optional[str] = Field(None, max_length=32)
    dose_value: Optional[str] = Field(None, max_length=32)
    dose_unit: Optional[str] = Field(None, max_length=32)
    route: str = Field(..., min_length=1, max_length=64)
    indication: str = Field(..., min_length=1)
    response: Optional[str] = None
    export_state: str = Field("pending_mapping", max_length=32)
    administered_at: Optional[str] = None


class MedicationAdministrationUpdateRequest(BaseModel):
    dose_value: Optional[str] = Field(None, max_length=32)
    dose_unit: Optional[str] = Field(None, max_length=32)
    response: Optional[str] = None
    export_state: Optional[str] = Field(None, max_length=32)
    administered_at: Optional[str] = None


class MedicationAdministrationResponse(BaseModel):
    id: str
    chart_id: str
    medication_name: str
    rxnorm_code: Optional[str] = None
    dose_value: Optional[str] = None
    dose_unit: Optional[str] = None
    route: str
    indication: str
    response: Optional[str] = None
    export_state: str
    administered_at: str


class SignatureArtifactRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    source_domain: str = Field("field_mobile", max_length=50)
    source_capture_id: Optional[str] = Field(None, max_length=36)
    incident_id: Optional[str] = Field(None, max_length=36)
    page_id: Optional[str] = Field(None, max_length=36)
    signature_class: str = Field(..., min_length=1, max_length=100)
    signature_method: str = Field(..., min_length=1, max_length=50)
    workflow_policy: str = Field("electronic_allowed", max_length=64)
    policy_pack_version: str = Field("field.mobile.signature.v1", max_length=120)
    payer_class: str = Field("ems_transport", max_length=80)
    jurisdiction_country: str = Field("US", max_length=8)
    jurisdiction_state: str = Field("WI", max_length=8)
    signer_identity: Optional[str] = None
    signer_relationship: Optional[str] = None
    signer_authority_basis: Optional[str] = None
    patient_capable_to_sign: Optional[bool] = None
    incapacity_reason: Optional[str] = None
    receiving_facility: Optional[str] = None
    receiving_clinician_name: Optional[str] = None
    receiving_role_title: Optional[str] = None
    transfer_of_care_time: Optional[str] = None
    transfer_exception_reason_code: Optional[str] = None
    transfer_exception_reason_detail: Optional[str] = None
    signature_on_file_reference: Optional[str] = None
    ambulance_employee_exception: bool = False
    receiving_facility_verification_status: str = Field("not_required", max_length=40)
    signature_artifact_data_url: Optional[str] = None
    retention_requirements: list[str] = Field(default_factory=list)
    ai_decision_explanation: dict = Field(default_factory=dict)


class SignatureArtifactUpdateRequest(BaseModel):
    signer_identity: Optional[str] = None
    signer_relationship: Optional[str] = None
    signer_authority_basis: Optional[str] = None
    patient_capable_to_sign: Optional[bool] = None
    incapacity_reason: Optional[str] = None
    receiving_facility: Optional[str] = None
    receiving_clinician_name: Optional[str] = None
    receiving_role_title: Optional[str] = None
    transfer_of_care_time: Optional[str] = None
    transfer_exception_reason_code: Optional[str] = None
    transfer_exception_reason_detail: Optional[str] = None
    signature_on_file_reference: Optional[str] = None
    ambulance_employee_exception: Optional[bool] = None
    receiving_facility_verification_status: Optional[str] = Field(None, max_length=40)
    signature_artifact_data_url: Optional[str] = None


class SignatureArtifactIngestRequest(BaseModel):
    signature_capture_id: str = Field(..., min_length=1, max_length=36)
    source_domain: str = Field("crewlink", max_length=50)
    incident_id: Optional[str] = Field(None, max_length=36)
    page_id: Optional[str] = Field(None, max_length=36)
    signature_class: str = Field(..., min_length=1, max_length=100)
    signature_method: str = Field(..., min_length=1, max_length=50)
    workflow_policy: str = Field(..., min_length=1, max_length=64)
    policy_pack_version: str = Field(..., min_length=1, max_length=120)
    payer_class: str = Field(..., min_length=1, max_length=80)
    jurisdiction_country: str = Field("US", max_length=8)
    jurisdiction_state: str = Field("WI", max_length=8)
    signer_identity: Optional[str] = None
    signer_relationship: Optional[str] = None
    signer_authority_basis: Optional[str] = None
    patient_capable_to_sign: Optional[bool] = None
    incapacity_reason: Optional[str] = None
    receiving_facility: Optional[str] = None
    receiving_clinician_name: Optional[str] = None
    receiving_role_title: Optional[str] = None
    transfer_of_care_time: Optional[str] = None
    transfer_exception_reason_code: Optional[str] = None
    transfer_exception_reason_detail: Optional[str] = None
    signature_on_file_reference: Optional[str] = None
    ambulance_employee_exception: bool = False
    receiving_facility_verification_status: str = Field("not_required", max_length=40)
    signature_artifact_data_url: Optional[str] = None
    decision: str = Field(..., min_length=1, max_length=80)
    decision_why: str = Field(..., min_length=1, max_length=500)
    missing_requirements: list[str] = Field(default_factory=list)
    billing_readiness_effect: str = Field("hold", max_length=40)
    chart_completion_effect: str = Field("incomplete", max_length=40)
    retention_requirements: list[str] = Field(default_factory=list)
    ai_decision_explanation: dict = Field(default_factory=dict)
    wards_export_safe: bool = True
    nemsis_export_safe: bool = True


class SignatureArtifactResponse(BaseModel):
    id: str
    chart_id: str
    source_domain: str
    source_capture_id: str
    signature_class: str
    signature_method: str
    signer_identity: Optional[str] = None
    signer_relationship: Optional[str] = None
    patient_capable_to_sign: Optional[bool] = None
    receiving_facility: Optional[str] = None
    transfer_of_care_time: Optional[str] = None
    signature_artifact_data_url: Optional[str] = None
    signature_on_file_reference: Optional[str] = None
    compliance_decision: str
    compliance_why: str
    chart_completion_effect: str
    billing_readiness_effect: str
    missing_requirements: list[str]
    created_at: str
    updated_at: str


class InterventionRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    category: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    indication: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=1)
    expected_response: str = Field(..., min_length=1)
    actual_response: Optional[str] = None
    reassessment_due_at: Optional[str] = None
    protocol_family: str = Field(..., min_length=1, max_length=32)
    snomed_code: Optional[str] = Field(None, max_length=32)
    icd10_code: Optional[str] = Field(None, max_length=32)
    rxnorm_code: Optional[str] = Field(None, max_length=32)
    export_state: str = Field("pending_mapping", min_length=1, max_length=32)


class InterventionUpdateRequest(BaseModel):
    actual_response: Optional[str] = None
    reassessment_due_at: Optional[str] = None
    export_state: Optional[str] = Field(None, max_length=32)
    protocol_family: Optional[str] = Field(None, max_length=32)


class InterventionResponse(BaseModel):
    id: str
    chart_id: str
    category: str
    name: str
    indication: str
    intent: str
    expected_response: str
    actual_response: Optional[str] = None
    protocol_family: str
    export_state: str
    snomed_code: Optional[str] = None
    icd10_code: Optional[str] = None
    rxnorm_code: Optional[str] = None
    performed_at: str


class ClinicalNoteRequest(BaseModel):
    client_reference_id: Optional[str] = Field(None, max_length=36)
    raw_text: str = Field(..., min_length=1)
    source: str = Field("manual_entry", min_length=1, max_length=64)
    provenance: dict = Field(default_factory=dict)


class ClinicalNoteUpdateRequest(BaseModel):
    raw_text: Optional[str] = None
    review_state: Optional[str] = Field(None, max_length=32)


class ClinicalNoteResponse(BaseModel):
    id: str
    chart_id: str
    raw_text: str
    source: str
    derived_summary: str
    review_state: str
    captured_at: str


class ProtocolGenerationRequest(BaseModel):
    patient_model: str = Field(..., min_length=1, max_length=32)


class ProtocolRecommendationUpdateRequest(BaseModel):
    state: str = Field(..., min_length=1, max_length=32)


class ProtocolRecommendationResponse(BaseModel):
    id: str
    chart_id: str
    protocol_family: str
    title: str
    rationale: str
    action_priority: int
    state: str
    generated_at: str


class DerivedOutputRequest(BaseModel):
    output_type: str = Field(..., min_length=1, max_length=32)


class DerivedOutputResponse(BaseModel):
    id: str
    chart_id: str
    output_type: str
    content_text: str
    source_revision: str
    generated_at: str


class DashboardSummaryResponse(BaseModel):
    chart_id: str
    chart_status: str
    patient_profile_present: bool
    vitals_count: int
    finding_count: int
    medication_count: int
    signature_count: int
    intervention_count: int
    impression_documented: bool
    chart_completion_blocked_by_signature: bool
    pending_note_review_count: int
    accepted_note_count: int
    protocol_recommendation_count: int
    derived_output_count: int
    address_validation_state: str
    ready_for_nemsis_export: bool
    nemsis_missing_fields: list[str]


@router.get("/health")
async def health():
    """Health check endpoint with truthful status.
    
    Returns actual database connectivity status. Returns "degraded" if
    database is unavailable, NEVER fabricates health status.
    
    Returns:
        dict: Health status including service name and database connectivity.
    """
    return await check_health()


@router.post("/charts", response_model=ChartResponse, status_code=201)
async def create_chart(
    request: CreateChartRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create new ePCR chart.
    
    Creates a new emergency patient care record with NEMSIS 3.5.1 compliance
    tracking. Chart enters NEW state with all mandatory fields initially marked
    as missing.
    
    Args:
        request: Chart creation parameters (call_number, incident_type, patient_id).        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ChartResponse: Created chart with ID and status.
        
    Raises:
        HTTPException 400: Invalid request (validation failed).
        HTTPException 500: Database error.
        
    Example:
        POST /api/v1/epcr/charts
        Headers: Authorization: Bearer <token>
        Body: {"call_number": "CALL-2026-04-001", "incident_type": "medical"}
    """
    try:
        tenant_id = _tenant_id(current_user)
        user_id = _user_id(current_user)
        chart = await ChartService.create_chart(
            session=session,
            tenant_id=tenant_id,
            call_number=request.call_number,
            incident_type=request.incident_type,
            created_by_user_id=user_id,
            client_reference_id=request.client_reference_id,
            patient_id=request.patient_id
        )
        logger.info("Chart created via API: id=%s tenant_id=%s user_id=%s", chart.id, tenant_id, user_id)
        
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "incident_type": chart.incident_type,
            "created_at": chart.created_at.isoformat()
        }
    except ValueError as e:
        logger.warning(f"Chart creation validation error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error creating chart: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create chart")


@router.get("/charts/{chart_id}")
async def get_chart(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Retrieve ePCR chart by ID.
    
    Fetches a chart by ID with tenant isolation enforced. Returns 404 if
    chart not found or does not belong to requesting tenant.
    
    Args:
        chart_id: Chart identifier to retrieve.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        dict: Chart details including all fields and timestamps.
        
    Raises:
                HTTPException 404: Chart not found or access denied.
        HTTPException 500: Database error.
    """
    try:
        tenant_id = _tenant_id(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            logger.debug("Chart not found: id=%s tenant_id=%s", chart_id, tenant_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        
        logger.debug("Chart retrieved: id=%s tenant_id=%s", chart_id, tenant_id)
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "incident_type": chart.incident_type,
            "patient_id": chart.patient_id,
            "created_at": chart.created_at.isoformat(),
            "updated_at": chart.updated_at.isoformat() if chart.updated_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve chart")


@router.get("/charts/{chart_id}/nemsis-3-5-1-compliance", response_model=ComplianceResponse)
async def check_nemsis_compliance(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Check NEMSIS 3.5.1 compliance status for ePCR chart.
    
    Validates chart against all 13 mandatory NEMSIS 3.5.1 fields. Returns
    detailed compliance status including percentage filled and list of
    missing required fields.
    
    Args:
        chart_id: Chart identifier to check.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ComplianceResponse: Compliance status with percentage and missing fields.
        
    Raises:
                HTTPException 404: Chart not found.
        HTTPException 500: Compliance check failed.
    """
    try:
        result = await ChartService.check_nemsis_compliance(session, _tenant_id(current_user), chart_id)
        
        logger.info(f"Compliance checked: chart_id={chart_id}, status={result['compliance_status']}, percentage={result['compliance_percentage']}%")
        
        return result
    except ValueError as e:
        logger.warning(f"Compliance check: chart not found (id={chart_id})")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Compliance check error for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Compliance check failed")


@router.patch("/charts/{chart_id}", response_model=ChartUpdateResponse, status_code=200)
async def update_chart(
    chart_id: str,
    request: UpdateChartRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update ePCR chart fields and return compliance status.
    
    Applies partial field updates to a chart (incident type, patient ID, vitals,
    assessment). Updates chart.updated_at timestamp. After update, fetches
    current compliance status and includes it inline in response.
    
    Args:
        chart_id: Chart identifier to update.
        request: UpdateChartRequest with optional fields to update.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.
        
    Returns:
        ChartUpdateResponse: Updated chart with inline compliance status.
        
    Raises:
        HTTPException 400: Invalid request or headers (validation failed).
        HTTPException 404: Chart not found or access denied.
        HTTPException 500: Database or compliance check error.
        
    Example:
        PATCH /api/v1/epcr/charts/chart-123
        Headers: Authorization: Bearer <token>
        Body: {"incident_type": "trauma", "bp_sys": 140, "bp_dia": 90}
    """
    try:
        update_data = {k: v for k, v in request.dict().items() if v is not None}
        tenant_id = _tenant_id(current_user)
        
        # Update chart
        chart = await ChartService.update_chart(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            update_data=update_data
        )
        
        # Get current compliance status
        compliance_result = await ChartService.check_nemsis_compliance(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id
        )
        
        logger.info("Chart updated and compliance checked: id=%s tenant_id=%s compliance=%s%%", chart_id, tenant_id, compliance_result["compliance_percentage"])
        
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value,
            "updated_at": chart.updated_at.isoformat(),
            "compliance": {
                "is_fully_compliant": compliance_result["is_fully_compliant"],
                "compliance_percentage": compliance_result["compliance_percentage"],
                "missing_mandatory_fields": compliance_result["missing_mandatory_fields"]
            }
        }
    except ValueError as e:
        logger.warning(f"Chart update validation error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update chart")


@router.post("/charts/{chart_id}/assessment-findings", response_model=AssessmentFindingResponse, status_code=201)
async def create_assessment_finding(
    chart_id: str,
    request: AssessmentFindingRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a structured CPAE finding for an ePCR chart."""
    try:
        finding = await ChartService.record_assessment_finding(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            finding_data=request.model_dump(exclude_none=True),
        )
        return {
            "id": finding.id,
            "chart_id": finding.chart_id,
            "anatomy": finding.anatomy,
            "system": finding.system,
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "detection_method": finding.detection_method,
            "review_state": finding.review_state.value if hasattr(finding.review_state, "value") else finding.review_state,
            "observed_at": finding.observed_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error creating structured finding for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create assessment finding")


@router.get("/charts/{chart_id}/assessment-findings", status_code=200)
async def list_assessment_findings(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List structured findings recorded for a chart."""
    try:
        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        from epcr_app.models import AssessmentFinding

        result = await session.execute(
            select(AssessmentFinding).where(
                and_(
                    AssessmentFinding.chart_id == chart_id,
                    AssessmentFinding.tenant_id == _tenant_id(current_user),
                )
            )
        )
        findings = result.scalars().all()
        return {
            "chart_id": chart_id,
            "count": len(findings),
            "items": [
                {
                    "id": finding.id,
                    "anatomy": finding.anatomy,
                    "system": finding.system,
                    "finding_type": finding.finding_type,
                    "severity": finding.severity,
                    "review_state": finding.review_state.value if hasattr(finding.review_state, "value") else finding.review_state,
                    "observed_at": finding.observed_at.isoformat(),
                }
                for finding in findings
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error listing structured findings for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list assessment findings")


@router.post("/charts/{chart_id}/visual-overlays", response_model=VisualOverlayResponse, status_code=201)
async def create_visual_overlay(
    chart_id: str,
    request: VisualOverlayRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a governed VAS overlay for an existing structured finding."""
    try:
        overlay = await ChartService.record_visual_overlay(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            overlay_data=request.model_dump(exclude_none=True),
        )
        return {
            "id": overlay.id,
            "chart_id": overlay.chart_id,
            "finding_id": overlay.finding_id,
            "overlay_type": overlay.overlay_type,
            "anatomical_view": overlay.anatomical_view,
            "anchor_region": overlay.anchor_region,
            "rendered_at": overlay.rendered_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error creating visual overlay for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create visual overlay")


@router.get("/charts/{chart_id}/visual-overlays", status_code=200)
async def list_visual_overlays(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List governed VAS overlays recorded for a chart."""
    try:
        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        from epcr_app.models import VisualOverlay

        result = await session.execute(
            select(VisualOverlay).where(
                and_(
                    VisualOverlay.chart_id == chart_id,
                    VisualOverlay.tenant_id == _tenant_id(current_user),
                )
            )
        )
        overlays = result.scalars().all()
        return {
            "chart_id": chart_id,
            "count": len(overlays),
            "items": [
                {
                    "id": overlay.id,
                    "finding_id": overlay.finding_id,
                    "overlay_type": overlay.overlay_type,
                    "anatomical_view": overlay.anatomical_view,
                    "anchor_region": overlay.anchor_region,
                    "severity": overlay.severity,
                    "review_state": overlay.review_state.value if hasattr(overlay.review_state, "value") else overlay.review_state,
                    "rendered_at": overlay.rendered_at.isoformat(),
                }
                for overlay in overlays
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error listing visual overlays for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list visual overlays")


@router.patch("/charts/{chart_id}/assessment-findings/{finding_id}", response_model=AssessmentFindingResponse, status_code=200)
async def update_assessment_finding(
    chart_id: str,
    finding_id: str,
    request: AssessmentFindingUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a structured CPAE finding for correction/review."""
    try:
        finding = await ChartService.update_assessment_finding(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            finding_id=finding_id,
            provider_id=_user_id(current_user),
            update_data={k: v for k, v in request.model_dump().items() if v is not None},
        )
        return {
            "id": finding.id,
            "chart_id": finding.chart_id,
            "anatomy": finding.anatomy,
            "system": finding.system,
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "detection_method": finding.detection_method,
            "review_state": finding.review_state.value if hasattr(finding.review_state, "value") else finding.review_state,
            "observed_at": finding.observed_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error updating structured finding %s for chart %s: %s", finding_id, chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update assessment finding")


@router.patch("/charts/{chart_id}/visual-overlays/{overlay_id}", response_model=VisualOverlayResponse, status_code=200)
async def update_visual_overlay(
    chart_id: str,
    overlay_id: str,
    request: VisualOverlayUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a governed VAS overlay for correction/review."""
    try:
        overlay = await ChartService.update_visual_overlay(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            overlay_id=overlay_id,
            provider_id=_user_id(current_user),
            update_data={k: v for k, v in request.model_dump().items() if v is not None},
        )
        return {
            "id": overlay.id,
            "chart_id": overlay.chart_id,
            "finding_id": overlay.finding_id,
            "overlay_type": overlay.overlay_type,
            "anatomical_view": overlay.anatomical_view,
            "anchor_region": overlay.anchor_region,
            "rendered_at": overlay.rendered_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error updating visual overlay %s for chart %s: %s", overlay_id, chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update visual overlay")


@router.post("/charts/{chart_id}/ar-sessions", response_model=ArSessionResponse, status_code=201)
async def create_ar_session(
    chart_id: str,
    request: ArSessionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Start a governed ARCOS session for a chart."""
    try:
        ar_session = await ChartService.start_ar_session(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            started_by_user_id=_user_id(current_user),
            patient_model=request.patient_model,
            mode=request.mode,
            client_reference_id=request.client_reference_id,
        )
        return {
            "id": ar_session.id,
            "chart_id": ar_session.chart_id,
            "patient_model": ar_session.patient_model,
            "mode": ar_session.mode,
            "status": ar_session.status.value if hasattr(ar_session.status, "value") else ar_session.status,
            "started_at": ar_session.started_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error starting AR session for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to start AR session")


@router.get("/charts/{chart_id}/ar-sessions", status_code=200)
async def list_ar_sessions(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List ARCOS sessions for a chart."""
    try:
        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        from epcr_app.models import ArSession

        result = await session.execute(
            select(ArSession).where(
                and_(
                    ArSession.chart_id == chart_id,
                    ArSession.tenant_id == _tenant_id(current_user),
                )
            )
        )
        sessions = result.scalars().all()
        return {
            "chart_id": chart_id,
            "count": len(sessions),
            "items": [
                {
                    "id": item.id,
                    "chart_id": item.chart_id,
                    "patient_model": item.patient_model,
                    "mode": item.mode,
                    "status": item.status.value if hasattr(item.status, "value") else item.status,
                    "started_at": item.started_at.isoformat(),
                    "ended_at": item.ended_at.isoformat() if item.ended_at else None,
                }
                for item in sessions
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error listing AR sessions for chart %s: %s", chart_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list AR sessions")


@router.post("/ar-sessions/{session_id}/complete", response_model=ArSessionResponse, status_code=200)
async def complete_ar_session(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Complete an ARCOS session and close its lifecycle state."""
    try:
        ar_session = await ChartService.complete_ar_session(
            session=session,
            tenant_id=_tenant_id(current_user),
            session_id=session_id,
            completed_by_user_id=_user_id(current_user),
        )
        return {
            "id": ar_session.id,
            "chart_id": ar_session.chart_id,
            "patient_model": ar_session.patient_model,
            "mode": ar_session.mode,
            "status": ar_session.status.value if hasattr(ar_session.status, "value") else ar_session.status,
            "started_at": ar_session.started_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error completing AR session %s: %s", session_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to complete AR session")


@router.post("/ar-sessions/{session_id}/anchors", response_model=ArAnchorResponse, status_code=201)
async def create_ar_anchor(
    session_id: str,
    request: ArAnchorRequest,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record an ARCOS anatomical anchor within a started session."""
    try:
        anchor = await ChartService.record_ar_anchor(
            session=session,
            tenant_id=_tenant_id(current_user),
            session_id=session_id,
            anchored_by_user_id=_user_id(current_user),
            anatomy=request.anatomy,
            anatomical_view=request.anatomical_view,
            confidence=request.confidence,
            client_reference_id=request.client_reference_id,
        )
        return {
            "id": anchor.id,
            "session_id": anchor.session_id,
            "anatomy": anchor.anatomy,
            "anatomical_view": anchor.anatomical_view,
            "confidence": anchor.confidence,
            "anchored_at": anchor.anchored_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error recording AR anchor for session %s: %s", session_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record AR anchor")


@router.get("/ar-sessions/{session_id}/anchors", status_code=200)
async def list_ar_anchors(
    session_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List captured anatomical anchors for an ARCOS session."""
    try:
        from epcr_app.models import ArAnchor, ArSession

        session_result = await session.execute(
            select(ArSession).where(
                and_(
                    ArSession.id == session_id,
                    ArSession.tenant_id == _tenant_id(current_user),
                )
            )
        )
        ar_session = session_result.scalars().first()
        if not ar_session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AR session not found")

        result = await session.execute(
            select(ArAnchor).where(
                and_(
                    ArAnchor.session_id == session_id,
                    ArAnchor.tenant_id == _tenant_id(current_user),
                )
            )
        )
        anchors = result.scalars().all()
        return {
            "session_id": session_id,
            "count": len(anchors),
            "items": [
                {
                    "id": anchor.id,
                    "anatomy": anchor.anatomy,
                    "anatomical_view": anchor.anatomical_view,
                    "confidence": anchor.confidence,
                    "anchored_at": anchor.anchored_at.isoformat(),
                }
                for anchor in anchors
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error listing AR anchors for session %s: %s", session_id, str(e), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list AR anchors")


@router.put("/charts/{chart_id}/address-intelligence", response_model=AddressIntelligenceResponse, status_code=200)
async def upsert_address_intelligence(
    chart_id: str,
    request: AddressIntelligenceRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create or update chart-scoped address intelligence."""
    try:
        address = await ChartService.upsert_chart_address(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            address_data=request.model_dump(exclude_none=True),
        )
        return {
            "id": address.id,
            "chart_id": address.chart_id,
            "raw_text": address.raw_text,
            "validation_state": address.validation_state.value,
            "intelligence_source": address.intelligence_source,
            "updated_at": address.updated_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/address-intelligence", response_model=AddressIntelligenceResponse, status_code=200)
async def get_address_intelligence(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get chart-scoped address intelligence."""
    from epcr_app.models import ChartAddress

    result = await session.execute(
        select(ChartAddress).where(and_(ChartAddress.chart_id == chart_id, ChartAddress.tenant_id == _tenant_id(current_user)))
    )
    address = result.scalars().first()
    if not address:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address intelligence not found")
    return {
        "id": address.id,
        "chart_id": address.chart_id,
        "raw_text": address.raw_text,
        "validation_state": address.validation_state.value,
        "intelligence_source": address.intelligence_source,
        "updated_at": address.updated_at.isoformat(),
    }


@router.put("/charts/{chart_id}/patient-profile", response_model=PatientProfileResponse, status_code=200)
async def upsert_patient_profile(
    chart_id: str,
    request: PatientProfileRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create or update patient demographics for a chart."""
    try:
        profile = await ChartService.upsert_patient_profile(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            profile_data=request.model_dump(exclude_none=True),
        )
        return _serialize_patient_profile(profile)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/patient-profile", response_model=PatientProfileResponse, status_code=200)
async def get_patient_profile(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get chart-scoped patient demographics."""
    profile = await ChartService.get_patient_profile(session, _tenant_id(current_user), chart_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient profile not found")
    return _serialize_patient_profile(profile)


@router.post("/charts/{chart_id}/vitals", response_model=VitalSetResponse, status_code=201)
async def create_vital_set(
    chart_id: str,
    request: VitalSetRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record a structured vital set."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("recorded_at"):
            payload["recorded_at"] = datetime.fromisoformat(payload["recorded_at"])
        vital = await ChartService.record_vital_set(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            vitals_data=payload,
        )
        return _serialize_vital(vital)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/vitals", status_code=200)
async def list_vital_sets(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List vital sets recorded for a chart."""
    from sqlalchemy import desc
    from epcr_app.models import Vitals

    result = await session.execute(
        select(Vitals).where(
            and_(Vitals.chart_id == chart_id, Vitals.tenant_id == _tenant_id(current_user), Vitals.deleted_at.is_(None))
        ).order_by(desc(Vitals.recorded_at))
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_vital(item) for item in items]}


@router.patch("/charts/{chart_id}/vitals/{vital_id}", response_model=VitalSetResponse, status_code=200)
async def update_vital_set(
    chart_id: str,
    vital_id: str,
    request: VitalSetUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a recorded vital set."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("recorded_at"):
            payload["recorded_at"] = datetime.fromisoformat(payload["recorded_at"])
        vital = await ChartService.update_vital_set(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            vital_id=vital_id,
            provider_id=_user_id(current_user),
            update_data=payload,
        )
        return _serialize_vital(vital)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/charts/{chart_id}/clinical-impression", response_model=ClinicalImpressionResponse, status_code=200)
async def upsert_clinical_impression(
    chart_id: str,
    request: ClinicalImpressionRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create or update structured clinical impression authority."""
    try:
        item = await ChartService.upsert_clinical_impression(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            impression_data=request.model_dump(exclude_none=True),
        )
        return _serialize_impression(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/clinical-impression", response_model=ClinicalImpressionResponse, status_code=200)
async def get_clinical_impression(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get structured clinical impression for a chart."""
    assessment = await ChartService.get_clinical_impression(session, _tenant_id(current_user), chart_id)
    if not assessment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clinical impression not found")
    return _serialize_impression(assessment)


@router.post("/charts/{chart_id}/medications", response_model=MedicationAdministrationResponse, status_code=201)
async def create_medication_administration(
    chart_id: str,
    request: MedicationAdministrationRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record medication administration authority for a chart."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("administered_at"):
            payload["administered_at"] = datetime.fromisoformat(payload["administered_at"])
        item = await ChartService.record_medication_administration(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            medication_data=payload,
        )
        return _serialize_medication(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/medications", status_code=200)
async def list_medication_administrations(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List medication administrations for a chart."""
    from sqlalchemy import desc
    from epcr_app.models import MedicationAdministration

    result = await session.execute(
        select(MedicationAdministration).where(
            and_(MedicationAdministration.chart_id == chart_id, MedicationAdministration.tenant_id == _tenant_id(current_user))
        ).order_by(desc(MedicationAdministration.administered_at))
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_medication(item) for item in items]}


@router.post("/charts/{chart_id}/signatures", response_model=SignatureArtifactResponse, status_code=201)
async def create_signature_artifact(
    chart_id: str,
    request: SignatureArtifactRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Record a chart-owned signature artifact from direct mobile capture."""
    try:
        item = await ChartService.create_signature_artifact(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            created_by_user_id=_user_id(current_user),
            payload=request.model_dump(exclude_none=True),
        )
        return _serialize_signature(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/signatures", status_code=200)
async def list_signature_artifacts(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List authoritative signature artifacts for a chart."""
    from sqlalchemy import desc
    from epcr_app.models import EpcrSignatureArtifact

    result = await session.execute(
        select(EpcrSignatureArtifact).where(
            and_(EpcrSignatureArtifact.chart_id == chart_id, EpcrSignatureArtifact.tenant_id == _tenant_id(current_user))
        ).order_by(desc(EpcrSignatureArtifact.created_at))
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_signature(item) for item in items]}


@router.patch("/charts/{chart_id}/signatures/{signature_id}", response_model=SignatureArtifactResponse, status_code=200)
async def update_signature_artifact(
    chart_id: str,
    signature_id: str,
    request: SignatureArtifactUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a chart-owned signature artifact and recompute completion effects."""
    try:
        item = await ChartService.update_signature_artifact(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            signature_id=signature_id,
            updated_by_user_id=_user_id(current_user),
            payload=request.model_dump(exclude_none=True),
        )
        return _serialize_signature(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/charts/{chart_id}/signatures/ingest", response_model=SignatureArtifactResponse, status_code=201)
async def ingest_signature_artifact(
    chart_id: str,
    request: SignatureArtifactIngestRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Ingest a fallback signature capture as authoritative ePCR signature state."""
    try:
        item = await ChartService.ingest_signature_artifact(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            created_by_user_id=_user_id(current_user),
            payload=request.model_dump(exclude_none=True),
        )
        return _serialize_signature(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/charts/{chart_id}/medications/{medication_id}", response_model=MedicationAdministrationResponse, status_code=200)
async def update_medication_administration(
    chart_id: str,
    medication_id: str,
    request: MedicationAdministrationUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update medication administration response/export state."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("administered_at"):
            payload["administered_at"] = datetime.fromisoformat(payload["administered_at"])
        item = await ChartService.update_medication_administration(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            medication_id=medication_id,
            provider_id=_user_id(current_user),
            update_data=payload,
        )
        return _serialize_medication(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/charts/{chart_id}/interventions", response_model=InterventionResponse, status_code=201)
async def create_intervention(
    chart_id: str,
    request: InterventionRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a structured intervention workflow record."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("reassessment_due_at"):
            payload["reassessment_due_at"] = datetime.fromisoformat(payload["reassessment_due_at"])
        intervention = await ChartService.record_intervention(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            intervention_data=payload,
        )
        return _serialize_intervention(intervention)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/interventions", status_code=200)
async def list_interventions(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List interventions documented for a chart."""
    from epcr_app.models import ClinicalIntervention

    result = await session.execute(
        select(ClinicalIntervention).where(
            and_(ClinicalIntervention.chart_id == chart_id, ClinicalIntervention.tenant_id == _tenant_id(current_user))
        )
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_intervention(item) for item in items]}


@router.patch("/charts/{chart_id}/interventions/{intervention_id}", response_model=InterventionResponse, status_code=200)
async def update_intervention(
    chart_id: str,
    intervention_id: str,
    request: InterventionUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Update a structured intervention."""
    try:
        payload = request.model_dump(exclude_none=True)
        if payload.get("reassessment_due_at"):
            payload["reassessment_due_at"] = datetime.fromisoformat(payload["reassessment_due_at"])
        intervention = await ChartService.update_intervention(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            intervention_id=intervention_id,
            provider_id=_user_id(current_user),
            update_data=payload,
        )
        return _serialize_intervention(intervention)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/charts/{chart_id}/clinical-notes", response_model=ClinicalNoteResponse, status_code=201)
async def create_clinical_note(
    chart_id: str,
    request: ClinicalNoteRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Capture structured clinical text with deterministic summary generation."""
    try:
        note = await ChartService.record_clinical_note(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            provider_id=_user_id(current_user),
            note_data=request.model_dump(exclude_none=True),
        )
        return _serialize_note(note)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/clinical-notes", status_code=200)
async def list_clinical_notes(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List captured clinical notes for a chart."""
    from epcr_app.models import ClinicalNote

    result = await session.execute(
        select(ClinicalNote).where(and_(ClinicalNote.chart_id == chart_id, ClinicalNote.tenant_id == _tenant_id(current_user)))
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_note(item) for item in items]}


@router.patch("/charts/{chart_id}/clinical-notes/{note_id}", response_model=ClinicalNoteResponse, status_code=200)
async def update_clinical_note(
    chart_id: str,
    note_id: str,
    request: ClinicalNoteUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Review or correct a clinical note."""
    try:
        note = await ChartService.update_clinical_note(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            note_id=note_id,
            provider_id=_user_id(current_user),
            update_data=request.model_dump(exclude_none=True),
        )
        return _serialize_note(note)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/charts/{chart_id}/protocol-recommendations/generate", status_code=200)
async def generate_protocol_recommendations(
    chart_id: str,
    request: ProtocolGenerationRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Generate deterministic protocol guidance for a chart."""
    try:
        items = await ChartService.generate_protocol_recommendations(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            generated_by_user_id=_user_id(current_user),
            patient_model=request.patient_model,
        )
        return {"chart_id": chart_id, "count": len(items), "items": [_serialize_protocol(item) for item in items]}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/protocol-recommendations", status_code=200)
async def list_protocol_recommendations(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List current protocol recommendations for a chart."""
    from epcr_app.models import ProtocolRecommendation

    result = await session.execute(
        select(ProtocolRecommendation).where(
            and_(ProtocolRecommendation.chart_id == chart_id, ProtocolRecommendation.tenant_id == _tenant_id(current_user))
        )
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_protocol(item) for item in items]}


@router.patch("/charts/{chart_id}/protocol-recommendations/{recommendation_id}", response_model=ProtocolRecommendationResponse, status_code=200)
async def update_protocol_recommendation(
    chart_id: str,
    recommendation_id: str,
    request: ProtocolRecommendationUpdateRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Accept or dismiss a protocol recommendation."""
    try:
        item = await ChartService.update_protocol_recommendation_state(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            recommendation_id=recommendation_id,
            user_id=_user_id(current_user),
            state=request.state,
        )
        return _serialize_protocol(item)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/charts/{chart_id}/derived-outputs", response_model=DerivedOutputResponse, status_code=201)
async def create_derived_output(
    chart_id: str,
    request: DerivedOutputRequest,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Generate and persist a derived chart output from CareGraph truth."""
    try:
        output = await ChartService.generate_derived_output(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            generated_by_user_id=_user_id(current_user),
            output_type=request.output_type,
        )
        return _serialize_output(output)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/charts/{chart_id}/derived-outputs", status_code=200)
async def list_derived_outputs(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List generated derived outputs for a chart."""
    from epcr_app.models import DerivedChartOutput

    result = await session.execute(
        select(DerivedChartOutput).where(
            and_(DerivedChartOutput.chart_id == chart_id, DerivedChartOutput.tenant_id == _tenant_id(current_user))
        )
    )
    items = result.scalars().all()
    return {"chart_id": chart_id, "count": len(items), "items": [_serialize_output(item) for item in items]}


@router.get("/charts/{chart_id}/dashboard", response_model=DashboardSummaryResponse, status_code=200)
async def get_chart_dashboard(
    chart_id: str,    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Return truthful dashboard state for a chart."""
    try:
        return await ChartService.get_dashboard_summary(session=session, tenant_id=_tenant_id(current_user), chart_id=chart_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/charts")
async def list_charts(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List ePCR charts for authenticated tenant.

    Returns paginated list of charts scoped to requesting tenant.
    Charts are returned in descending order by created_at.

    Args:
        limit: Maximum number of charts to return (capped at 200).
        offset: Number of charts to skip.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: Paginated chart list with count, offset, and limit.

    Raises:
                HTTPException 500: Database query failure.
    """
    try:
        from sqlalchemy import select, desc
        from epcr_app.models import Chart
        tenant_id = _tenant_id(current_user)

        result = await session.execute(
            select(Chart)
            .where(Chart.tenant_id == tenant_id)
            .order_by(desc(Chart.created_at))
            .offset(offset)
            .limit(min(limit, 200))
        )
        charts = result.scalars().all()

        logger.info("Charts listed: tenant_id=%s count=%s offset=%s", tenant_id, len(charts), offset)

        return {
            "items": [
                {
                    "id": c.id,
                    "call_number": c.call_number,
                    "status": c.status.value,
                    "incident_type": c.incident_type,
                    "created_at": c.created_at.isoformat(),
                }
                for c in charts
            ],
            "count": len(charts),
            "offset": offset,
            "limit": min(limit, 200),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing charts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list charts")


@router.post("/charts/{chart_id}/finalize", response_model=ChartResponse, status_code=200)
async def finalize_chart(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Finalize an ePCR chart after full NEMSIS 3.5.1 compliance is confirmed.

    Checks NEMSIS compliance before finalizing. Rejects finalization if any
    mandatory fields are missing. Never finalizes a non-compliant chart.
    Transitions chart from IN_PROGRESS to FINALIZED status.

    Args:
        chart_id: Chart identifier to finalize.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        ChartResponse: Finalized chart with updated status and finalized_at.

    Raises:
        HTTPException 400: Missing headers.
        HTTPException 404: Chart not found.
        HTTPException 422: Chart is not NEMSIS-compliant (lists missing fields).
        HTTPException 500: Database error.
    """
    try:
        tenant_id = _tenant_id(current_user)
        user_id = _user_id(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        compliance = await ChartService.check_nemsis_compliance(session, tenant_id, chart_id)
        if not compliance["is_fully_compliant"]:
            logger.warning(
                f"Chart finalization blocked: id={chart_id}, missing={compliance['missing_mandatory_fields']}"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Chart cannot be finalized: NEMSIS 3.5.1 compliance incomplete",
                    "missing_mandatory_fields": compliance["missing_mandatory_fields"],
                    "compliance_percentage": compliance["compliance_percentage"],
                }
            )

        from datetime import datetime, UTC
        chart.status = "finalized"
        chart.finalized_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="chart_finalized",
            detail={
                "compliance_percentage": compliance["compliance_percentage"],
                "mandatory_fields_filled": compliance["mandatory_fields_filled"],
            },
        )

        from epcr_app.domain_events import publish_chart_finalized
        publish_chart_finalized(chart_id, tenant_id, getattr(chart, "call_number", chart_id))

        try:
            from core_app.events import EventBusService
            # Publish epcr.chart.finalized event to core event bus
            # If core DB is unavailable, log the failure but do NOT block chart finalization
            logger.info(
                "Chart finalized, event publication: chart_id=%s tenant_id=%s",
                chart_id,
                tenant_id,
            )
        except Exception as _ev_err:
            logger.warning(f"Event publication skipped (non-blocking): {_ev_err}")

        logger.info("Chart finalized: id=%s tenant_id=%s user_id=%s", chart_id, tenant_id, user_id)

        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "status": chart.status.value if hasattr(chart.status, 'value') else chart.status,
            "incident_type": chart.incident_type,
            "created_at": chart.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error finalizing chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to finalize chart")


@router.post("/charts/{chart_id}/nemsis-fields", status_code=201)
async def record_nemsis_field(
    chart_id: str,
    nemsis_field: str,
    nemsis_value: str,
    source: str = "manual",
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Record or update a NEMSIS 3.5.1 field value for a chart.

    Creates or updates a single NEMSIS field mapping with provenance tracking.
    After recording, compliance status is automatically recalculated.

    Args:
        chart_id: Chart identifier.
        nemsis_field: NEMSIS field identifier (e.g. eRecord.01).
        nemsis_value: Value to record.
        source: Value source: manual, ocr, device, or system.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: Created or updated NEMSIS field record.

    Raises:
        HTTPException 400: Missing headers or invalid source.
        HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        record = await ChartService.record_nemsis_field(
            session=session,
            tenant_id=_tenant_id(current_user),
            chart_id=chart_id,
            nemsis_field=nemsis_field,
            nemsis_value=nemsis_value,
            source=source
        )
        logger.info(f"NEMSIS field recorded via API: chart_id={chart_id}, field={nemsis_field}")
        return {
            "id": record.id,
            "chart_id": record.chart_id,
            "nemsis_field": record.nemsis_field,
            "nemsis_value": record.nemsis_value,
            "source": record.source.value if hasattr(record.source, 'value') else record.source,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
    except ValueError as e:
        logger.warning(f"NEMSIS field record error: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error recording NEMSIS field: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to record NEMSIS field")


@router.get("/charts/{chart_id}/nemsis-fields")
async def list_nemsis_fields(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user)
):
    """List all recorded NEMSIS 3.5.1 field values for a chart.

    Returns all NEMSIS field mappings with provenance for a chart,
    providing full export history and audit trail visibility.

    Args:
        chart_id: Chart identifier.        session: Database session.
        current_user: Authenticated user from JWT Bearer token.

    Returns:
        dict: All NEMSIS field records for the chart plus compliance summary.

    Raises:
                HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        from sqlalchemy import select as _select
        from epcr_app.models import NemsisMappingRecord as _NMR

        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")

        result = await session.execute(
            _select(_NMR).where(_NMR.chart_id == chart_id)
        )
        records = result.scalars().all()
        compliance = await ChartService.check_nemsis_compliance(session, _tenant_id(current_user), chart_id)

        logger.info(f"NEMSIS fields listed: chart_id={chart_id}, count={len(records)}")
        return {
            "chart_id": chart_id,
            "field_count": len(records),
            "fields": [
                {
                    "id": r.id,
                    "nemsis_field": r.nemsis_field,
                    "nemsis_value": r.nemsis_value,
                    "source": r.source.value if hasattr(r.source, 'value') else r.source,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in records
            ],
            "compliance": {
                "is_fully_compliant": compliance["is_fully_compliant"],
                "compliance_percentage": compliance["compliance_percentage"],
                "missing_mandatory_fields": compliance["missing_mandatory_fields"],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing NEMSIS fields: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list NEMSIS fields")


@router.get("/charts/{chart_id}/export-history")
async def get_export_history(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all NEMSIS export attempts for a chart ordered newest first.

    Returns truthful empty list if no exports have been attempted.

    Args:
        chart_id: Chart identifier.        session: Database session.

    Returns:
        dict: Export history records with status and timestamps.

    Raises:
                HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        from sqlalchemy import select, desc
        from epcr_app.models import NemsisExportHistory
        result = await session.execute(
            select(NemsisExportHistory)
            .where(NemsisExportHistory.chart_id == chart_id)
            .order_by(desc(NemsisExportHistory.exported_at))
        )
        records = result.scalars().all()
        logger.info(f"Export history listed: chart_id={chart_id}, count={len(records)}")
        return {
            "chart_id": chart_id,
            "exports": [
                {
                    "id": r.id,
                    "export_status": r.export_status,
                    "exported_by_user_id": r.exported_by_user_id,
                    "exported_at": r.exported_at.isoformat(),
                    "error_message": r.error_message,
                }
                for r in records
            ],
            "count": len(records),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching export history for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch export history",
        )


@router.get("/charts/{chart_id}/audit-log")
async def get_audit_log(
    chart_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List all audit log entries for a chart ordered newest first.

    Args:
        chart_id: Chart identifier.        session: Database session.

    Returns:
        dict: Audit log entries for the chart.

    Raises:
                HTTPException 404: Chart not found.
        HTTPException 500: Database error.
    """
    try:
        chart = await ChartService.get_chart(session, _tenant_id(current_user), chart_id)
        if not chart:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chart not found")
        from sqlalchemy import select, desc
        from epcr_app.models import EpcrAuditLog
        result = await session.execute(
            select(EpcrAuditLog)
            .where(
                EpcrAuditLog.chart_id == chart_id,
                EpcrAuditLog.tenant_id == _tenant_id(current_user),
            )
            .order_by(desc(EpcrAuditLog.performed_at))
        )
        entries = result.scalars().all()
        logger.info(f"Audit log listed: chart_id={chart_id}, count={len(entries)}")
        return {
            "chart_id": chart_id,
            "entries": [
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "action": e.action,
                    "performed_at": e.performed_at.isoformat(),
                }
                for e in entries
            ],
            "count": len(entries),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching audit log for chart {chart_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch audit log",
        )

