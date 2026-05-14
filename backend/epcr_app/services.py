"""Care domain business services for ePCR and NEMSIS 3.5.1 compliance.

This module provides core business logic for managing ePCR charts, including
chart lifecycle management, clinical data recording, and NEMSIS 3.5.1 compliance
validation and tracking. All operations log activity and failures for audit trails.
"""
import uuid
import json
import logging
from datetime import datetime, UTC
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from epcr_app.models import (
    Chart,
    ChartStatus,
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
)
from epcr_app.incident_numbering_service import IncidentNumberingService

logger = logging.getLogger(__name__)


NEMSIS_MANDATORY_FIELDS = {
    "eRecord.01": "Patient Care Report Number",
    "eRecord.02": "Software Creator",
    "eRecord.03": "Software Name",
    "eRecord.04": "Software Version",
    "eResponse.01": "EMS Agency Number",
    "eResponse.03": "Incident Number",
    "eResponse.04": "EMS Response Number",
    "eResponse.05": "Type of Service Requested",
    "eTimes.01": "Time Incident Report Called In",
    "eTimes.02": "Time Unit Dispatched",
    "eTimes.03": "Time Unit On Scene",
    "eTimes.04": "Time Unit Left Scene",
    "eTimes.05": "Time at Destination",
}


class ChartService:
    """ePCR chart lifecycle and NEMSIS 3.5.1 compliance management.
    
    Provides methods for creating charts, recording clinical data,
    tracking NEMSIS compliance, and managing chart state transitions.
    All operations include logging and validation.
    """

    @staticmethod
    def _parse_optional_datetime(value: str | datetime | None) -> datetime | None:
        """Normalize optional ISO date-time strings into datetime objects."""
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return None

    @staticmethod
    def _evaluate_signature_payload(payload: dict) -> tuple[str, str, str, str, list[str]]:
        """Compute truthful signature readiness effects from the supplied payload."""
        signature_method = str(payload.get("signature_method") or "").strip().lower()
        signature_class = str(payload.get("signature_class") or "").strip().lower()
        signature_data = str(payload.get("signature_artifact_data_url") or "").strip()
        signature_on_file = str(payload.get("signature_on_file_reference") or "").strip()
        transfer_exception = str(payload.get("transfer_exception_reason_code") or "").strip()
        receiving_facility = str(payload.get("receiving_facility") or "").strip()
        signer_identity = str(payload.get("signer_identity") or "").strip()
        patient_capable_to_sign = payload.get("patient_capable_to_sign")
        ambulance_exception = bool(payload.get("ambulance_employee_exception"))
        transfer_of_care_time = ChartService._parse_optional_datetime(payload.get("transfer_of_care_time"))

        missing_requirements: list[str] = []
        if signature_method in {"electronic", "handwritten"} and not signature_data and not ambulance_exception:
            missing_requirements.append("signature_artifact_data_url")
        if signature_method == "signature_on_file" and not signature_on_file:
            missing_requirements.append("signature_on_file_reference")
        if signature_class == "transfer_of_care":
            if transfer_of_care_time is None and not transfer_exception:
                missing_requirements.append("transfer_of_care_time_or_exception")
            if not receiving_facility and not transfer_exception:
                missing_requirements.append("receiving_facility_or_exception")
        if patient_capable_to_sign is False and not signer_identity and not signature_on_file and not ambulance_exception:
            missing_requirements.append("authorized_representative_identity")

        if missing_requirements:
            why = "Signature completion is blocked until the missing signature requirements are documented."
            return (
                "blocked_missing_requirements",
                why,
                "incomplete",
                "hold",
                missing_requirements,
            )

        why = "Signature capture requirements are satisfied for the current chart workflow."
        return (
            "captured_compliant",
            why,
            "complete",
            "ready",
            [],
        )

    @staticmethod
    async def _sync_signature_nemsis_effects(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        artifact: EpcrSignatureArtifact,
    ) -> None:
        """Write signature-driven NEMSIS effects when transfer-of-care time is present."""
        if artifact.transfer_of_care_time is None:
            artifact.transfer_etimes12_recorded = False
            return
        await ChartService.record_nemsis_field(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            nemsis_field="eTimes.12",
            nemsis_value=artifact.transfer_of_care_time.isoformat(),
            source="manual",
        )
        artifact.transfer_etimes12_recorded = True

    @staticmethod
    async def upsert_patient_profile(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        profile_data: dict,
    ) -> PatientProfile:
        """Create or update chart-scoped patient demographics owned by ePCR."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        result = await session.execute(
            select(PatientProfile).where(
                and_(PatientProfile.chart_id == chart_id, PatientProfile.tenant_id == tenant_id)
            )
        )
        profile = result.scalars().first()
        if profile is None:
            profile = PatientProfile(
                id=profile_data.get("client_reference_id") or str(uuid.uuid4()),
                chart_id=chart_id,
                tenant_id=tenant_id,
                updated_at=datetime.now(UTC),
            )
            session.add(profile)
            action = "patient_profile_created"
        else:
            action = "patient_profile_updated"

        for field in (
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "age_years",
            "sex",
            "phone_number",
            "weight_kg",
        ):
            if field in profile_data:
                setattr(profile, field, profile_data.get(field))
        if "allergies" in profile_data:
            profile.allergies_json = json.dumps(profile_data.get("allergies") or [])
        profile.updated_at = datetime.now(UTC)
        chart.patient_id = profile.id

        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action=action,
            detail={"patient_profile_id": profile.id},
        )
        return profile

    @staticmethod
    async def get_patient_profile(session: AsyncSession, tenant_id: str, chart_id: str) -> PatientProfile | None:
        """Fetch chart-scoped patient demographics if present."""
        result = await session.execute(
            select(PatientProfile).where(
                and_(PatientProfile.chart_id == chart_id, PatientProfile.tenant_id == tenant_id)
            )
        )
        return result.scalars().first()

    @staticmethod
    async def record_vital_set(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        vitals_data: dict,
    ) -> Vitals:
        """Create a structured vital set for reassessment-aware charting."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        vital = Vitals(
            id=vitals_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            bp_sys=vitals_data.get("bp_sys"),
            bp_dia=vitals_data.get("bp_dia"),
            hr=vitals_data.get("hr"),
            rr=vitals_data.get("rr"),
            temp_f=vitals_data.get("temp_f"),
            spo2=vitals_data.get("spo2"),
            glucose=vitals_data.get("glucose"),
            recorded_at=vitals_data.get("recorded_at", datetime.now(UTC)),
        )
        session.add(vital)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="vital_set_recorded",
            detail={"vital_id": vital.id},
        )
        return vital

    @staticmethod
    async def update_vital_set(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        vital_id: str,
        provider_id: str,
        update_data: dict,
    ) -> Vitals:
        """Update an existing vital set."""
        result = await session.execute(
            select(Vitals).where(
                and_(Vitals.id == vital_id, Vitals.chart_id == chart_id, Vitals.tenant_id == tenant_id, Vitals.deleted_at.is_(None))
            )
        )
        vital = result.scalars().first()
        if not vital:
            raise ValueError(f"Vital set {vital_id} not found for chart {chart_id}")

        for field in ("bp_sys", "bp_dia", "hr", "rr", "temp_f", "spo2", "glucose", "recorded_at"):
            if field in update_data and update_data[field] is not None:
                setattr(vital, field, update_data[field])

        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="vital_set_updated",
            detail={"vital_id": vital_id, "updated_fields": sorted(update_data.keys())},
        )
        return vital

    @staticmethod
    async def upsert_clinical_impression(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        impression_data: dict,
    ) -> Assessment:
        """Create or update structured chief complaint and impression authority."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        result = await session.execute(
            select(Assessment).where(
                and_(Assessment.chart_id == chart_id, Assessment.tenant_id == tenant_id, Assessment.deleted_at.is_(None))
            )
        )
        assessment = result.scalars().first()
        if assessment is None:
            assessment = Assessment(
                id=str(uuid.uuid4()),
                chart_id=chart_id,
                tenant_id=tenant_id,
                documented_at=datetime.now(UTC),
            )
            session.add(assessment)
            action = "clinical_impression_created"
        else:
            action = "clinical_impression_updated"

        for field in (
            "chief_complaint",
            "field_diagnosis",
            "primary_impression",
            "secondary_impression",
            "impression_notes",
            "snomed_code",
            "icd10_code",
            "acuity",
        ):
            if field in impression_data:
                setattr(assessment, field, impression_data.get(field))
        assessment.documented_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action=action,
            detail={"assessment_id": assessment.id},
        )
        return assessment

    @staticmethod
    async def get_clinical_impression(session: AsyncSession, tenant_id: str, chart_id: str) -> Assessment | None:
        """Fetch chart-scoped structured impression authority if present."""
        result = await session.execute(
            select(Assessment).where(
                and_(Assessment.chart_id == chart_id, Assessment.tenant_id == tenant_id, Assessment.deleted_at.is_(None))
            )
        )
        return result.scalars().first()

    @staticmethod
    async def record_medication_administration(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        medication_data: dict,
    ) -> MedicationAdministration:
        """Record a medication administration as chart-owned clinical truth."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        required = {"medication_name", "route", "indication"}
        missing = sorted(field for field in required if not medication_data.get(field))
        if missing:
            raise ValueError(f"Missing required medication fields: {', '.join(missing)}")

        medication = MedicationAdministration(
            id=medication_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            medication_name=medication_data["medication_name"],
            rxnorm_code=medication_data.get("rxnorm_code"),
            dose_value=medication_data.get("dose_value"),
            dose_unit=medication_data.get("dose_unit"),
            route=medication_data["route"],
            indication=medication_data["indication"],
            response=medication_data.get("response"),
            export_state=InterventionExportState(medication_data.get("export_state", InterventionExportState.PENDING_MAPPING.value)),
            administered_at=medication_data.get("administered_at", datetime.now(UTC)),
            administered_by_user_id=provider_id,
            updated_at=datetime.now(UTC),
        )
        session.add(medication)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="medication_administration_created",
            detail={"medication_id": medication.id, "medication_name": medication.medication_name},
        )
        return medication

    @staticmethod
    async def update_medication_administration(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        medication_id: str,
        provider_id: str,
        update_data: dict,
    ) -> MedicationAdministration:
        """Update a documented medication administration."""
        result = await session.execute(
            select(MedicationAdministration).where(
                and_(
                    MedicationAdministration.id == medication_id,
                    MedicationAdministration.chart_id == chart_id,
                    MedicationAdministration.tenant_id == tenant_id,
                )
            )
        )
        medication = result.scalars().first()
        if not medication:
            raise ValueError(f"Medication administration {medication_id} not found for chart {chart_id}")

        for key, value in update_data.items():
            if value is None:
                continue
            if key == "export_state":
                medication.export_state = InterventionExportState(value)
            else:
                setattr(medication, key, value)
        medication.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="medication_administration_updated",
            detail={"medication_id": medication_id, "updated_fields": sorted(update_data.keys())},
        )
        return medication

    @staticmethod
    async def create_signature_artifact(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        created_by_user_id: str,
        payload: dict,
    ) -> EpcrSignatureArtifact:
        """Create an authoritative ePCR signature artifact from direct mobile capture."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        if not payload.get("signature_class"):
            raise ValueError("signature_class is required")
        if not payload.get("signature_method"):
            raise ValueError("signature_method is required")

        decision, why, chart_effect, billing_effect, missing_requirements = ChartService._evaluate_signature_payload(payload)
        transfer_of_care_time = ChartService._parse_optional_datetime(payload.get("transfer_of_care_time"))
        artifact = EpcrSignatureArtifact(
            id=payload.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            source_domain=payload.get("source_domain", "field_mobile"),
            source_capture_id=payload.get("source_capture_id") or payload.get("client_reference_id") or str(uuid.uuid4()),
            incident_id=payload.get("incident_id"),
            page_id=payload.get("page_id"),
            signature_class=payload["signature_class"],
            signature_method=payload["signature_method"],
            workflow_policy=payload.get("workflow_policy", "electronic_allowed"),
            policy_pack_version=payload.get("policy_pack_version", "field.mobile.signature.v1"),
            payer_class=payload.get("payer_class", "ems_transport"),
            jurisdiction_country=payload.get("jurisdiction_country", "US"),
            jurisdiction_state=payload.get("jurisdiction_state", "WI"),
            signer_identity=payload.get("signer_identity"),
            signer_relationship=payload.get("signer_relationship"),
            signer_authority_basis=payload.get("signer_authority_basis"),
            patient_capable_to_sign=payload.get("patient_capable_to_sign"),
            incapacity_reason=payload.get("incapacity_reason"),
            receiving_facility=payload.get("receiving_facility"),
            receiving_clinician_name=payload.get("receiving_clinician_name"),
            receiving_role_title=payload.get("receiving_role_title"),
            transfer_of_care_time=transfer_of_care_time,
            transfer_exception_reason_code=payload.get("transfer_exception_reason_code"),
            transfer_exception_reason_detail=payload.get("transfer_exception_reason_detail"),
            signature_on_file_reference=payload.get("signature_on_file_reference"),
            ambulance_employee_exception=payload.get("ambulance_employee_exception", False),
            receiving_facility_verification_status=payload.get("receiving_facility_verification_status", "not_required"),
            signature_artifact_data_url=payload.get("signature_artifact_data_url"),
            compliance_decision=decision,
            compliance_why=why,
            missing_requirements_json=json.dumps(missing_requirements),
            billing_readiness_effect=billing_effect,
            chart_completion_effect=chart_effect,
            retention_requirements_json=json.dumps(payload.get("retention_requirements", [])),
            ai_decision_explanation_json=json.dumps(payload.get("ai_decision_explanation", {})),
            transfer_etimes12_recorded=False,
            wards_export_safe=not missing_requirements,
            nemsis_export_safe=not missing_requirements,
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(artifact)
        await ChartService._sync_signature_nemsis_effects(session, tenant_id, chart_id, artifact)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=created_by_user_id,
            action="signature_created",
            detail={
                "artifact_id": artifact.id,
                "signature_class": artifact.signature_class,
                "compliance_decision": artifact.compliance_decision,
            },
        )
        return artifact

    @staticmethod
    async def update_signature_artifact(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        signature_id: str,
        updated_by_user_id: str,
        payload: dict,
    ) -> EpcrSignatureArtifact:
        """Update an authoritative signature artifact and recompute workflow effects."""
        result = await session.execute(
            select(EpcrSignatureArtifact).where(
                and_(
                    EpcrSignatureArtifact.id == signature_id,
                    EpcrSignatureArtifact.chart_id == chart_id,
                    EpcrSignatureArtifact.tenant_id == tenant_id,
                )
            )
        )
        artifact = result.scalars().first()
        if not artifact:
            raise ValueError(f"Signature artifact {signature_id} not found for chart {chart_id}")

        for field in (
            "signer_identity",
            "signer_relationship",
            "signer_authority_basis",
            "incapacity_reason",
            "receiving_facility",
            "receiving_clinician_name",
            "receiving_role_title",
            "transfer_exception_reason_code",
            "transfer_exception_reason_detail",
            "signature_on_file_reference",
            "receiving_facility_verification_status",
            "signature_artifact_data_url",
        ):
            if field in payload:
                setattr(artifact, field, payload.get(field))
        if "patient_capable_to_sign" in payload:
            artifact.patient_capable_to_sign = payload.get("patient_capable_to_sign")
        if "ambulance_employee_exception" in payload:
            artifact.ambulance_employee_exception = bool(payload.get("ambulance_employee_exception"))
        if "transfer_of_care_time" in payload:
            artifact.transfer_of_care_time = ChartService._parse_optional_datetime(payload.get("transfer_of_care_time"))

        evaluation_payload = {
            "signature_class": artifact.signature_class,
            "signature_method": artifact.signature_method,
            "patient_capable_to_sign": artifact.patient_capable_to_sign,
            "signer_identity": artifact.signer_identity,
            "receiving_facility": artifact.receiving_facility,
            "transfer_of_care_time": artifact.transfer_of_care_time,
            "transfer_exception_reason_code": artifact.transfer_exception_reason_code,
            "signature_artifact_data_url": artifact.signature_artifact_data_url,
            "signature_on_file_reference": artifact.signature_on_file_reference,
            "ambulance_employee_exception": artifact.ambulance_employee_exception,
        }
        decision, why, chart_effect, billing_effect, missing_requirements = ChartService._evaluate_signature_payload(evaluation_payload)
        artifact.compliance_decision = decision
        artifact.compliance_why = why
        artifact.chart_completion_effect = chart_effect
        artifact.billing_readiness_effect = billing_effect
        artifact.missing_requirements_json = json.dumps(missing_requirements)
        artifact.wards_export_safe = not missing_requirements
        artifact.nemsis_export_safe = not missing_requirements
        artifact.updated_at = datetime.now(UTC)
        await ChartService._sync_signature_nemsis_effects(session, tenant_id, chart_id, artifact)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=updated_by_user_id,
            action="signature_updated",
            detail={"artifact_id": artifact.id, "updated_fields": sorted(payload.keys())},
        )
        return artifact

    @staticmethod
    async def ingest_signature_artifact(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        created_by_user_id: str,
        payload: dict,
    ) -> EpcrSignatureArtifact:
        """Ingest a fallback signature package as authoritative ePCR artifact state."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        if not payload.get("signature_capture_id"):
            raise ValueError("signature_capture_id is required")

        transfer_of_care_time = ChartService._parse_optional_datetime(payload.get("transfer_of_care_time"))
        artifact = EpcrSignatureArtifact(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            source_domain=payload.get("source_domain", "crewlink"),
            source_capture_id=payload["signature_capture_id"],
            incident_id=payload.get("incident_id"),
            page_id=payload.get("page_id"),
            signature_class=payload["signature_class"],
            signature_method=payload["signature_method"],
            workflow_policy=payload["workflow_policy"],
            policy_pack_version=payload["policy_pack_version"],
            payer_class=payload["payer_class"],
            jurisdiction_country=payload.get("jurisdiction_country", "US"),
            jurisdiction_state=payload.get("jurisdiction_state", "WI"),
            signer_identity=payload.get("signer_identity"),
            signer_relationship=payload.get("signer_relationship"),
            signer_authority_basis=payload.get("signer_authority_basis"),
            patient_capable_to_sign=payload.get("patient_capable_to_sign"),
            incapacity_reason=payload.get("incapacity_reason"),
            receiving_facility=payload.get("receiving_facility"),
            receiving_clinician_name=payload.get("receiving_clinician_name"),
            receiving_role_title=payload.get("receiving_role_title"),
            transfer_of_care_time=transfer_of_care_time,
            transfer_exception_reason_code=payload.get("transfer_exception_reason_code"),
            transfer_exception_reason_detail=payload.get("transfer_exception_reason_detail"),
            signature_on_file_reference=payload.get("signature_on_file_reference"),
            ambulance_employee_exception=payload.get("ambulance_employee_exception", False),
            receiving_facility_verification_status=payload.get("receiving_facility_verification_status", "not_required"),
            signature_artifact_data_url=payload.get("signature_artifact_data_url"),
            compliance_decision=payload["decision"],
            compliance_why=payload["decision_why"],
            missing_requirements_json=json.dumps(payload.get("missing_requirements", [])),
            billing_readiness_effect=payload.get("billing_readiness_effect", "hold"),
            chart_completion_effect=payload.get("chart_completion_effect", "incomplete"),
            retention_requirements_json=json.dumps(payload.get("retention_requirements", [])),
            ai_decision_explanation_json=json.dumps(payload.get("ai_decision_explanation", {})),
            transfer_etimes12_recorded=False,
            wards_export_safe=payload.get("wards_export_safe", True),
            nemsis_export_safe=payload.get("nemsis_export_safe", True),
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(artifact)
        await ChartService._sync_signature_nemsis_effects(session, tenant_id, chart_id, artifact)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=created_by_user_id,
            action="signature_ingested",
            detail={
                "artifact_id": artifact.id,
                "signature_class": artifact.signature_class,
                "source_capture_id": artifact.source_capture_id,
                "compliance_decision": artifact.compliance_decision,
            },
        )
        return artifact

    @staticmethod
    async def create_chart(
        session: AsyncSession,
        tenant_id: str,
        call_number: str | None,
        incident_type: str,
        created_by_user_id: str,
        client_reference_id: str = None,
        patient_id: str = None,
        agency_id: str | None = None,
        agency_code: str | None = None,
        incident_datetime: datetime | None = None,
        cad_incident_number: str | None = None,
    ) -> Chart:
        """Create new ePCR chart with NEMSIS compliance tracking.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier for multi-tenant isolation.
            call_number: Optional legacy call/dispatch number. Preserved for backward compatibility.
            incident_type: Type of incident (medical, trauma, behavioral, other).
            created_by_user_id: User ID of chart creator (must be non-empty).
            patient_id: Optional patient identifier.
            
        Returns:
            Chart: Created chart object with NEMSIS compliance record.
            
        Raises:
            ValueError: If validation fails (empty fields, invalid incident_type).
            SQLAlchemyError: If database operation fails.
        """
        if not tenant_id or not isinstance(tenant_id, str) or len(tenant_id.strip()) == 0:
            logger.warning("Chart creation rejected: invalid tenant_id")
            raise ValueError("tenant_id is required and cannot be empty")
        
        if not created_by_user_id or not isinstance(created_by_user_id, str) or len(created_by_user_id.strip()) == 0:
            logger.warning("Chart creation rejected: invalid created_by_user_id")
            raise ValueError("created_by_user_id is required and cannot be empty")
        
        valid_incident_types = ["medical", "trauma", "behavioral", "other"]
        if incident_type not in valid_incident_types:
            logger.warning(f"Chart creation rejected: invalid incident_type '{incident_type}'")
            raise ValueError(f"incident_type must be one of: {', '.join(valid_incident_types)}")
        
        try:
            profile = await IncidentNumberingService.resolve_agency_profile(
                session=session,
                tenant_id=tenant_id.strip(),
                agency_id=agency_id,
                agency_code=agency_code,
            )
            numbering_policy = IncidentNumberingService.parse_numbering_policy(profile)
            numbering = await IncidentNumberingService.generate_incident_number(
                session=session,
                tenant_id=tenant_id.strip(),
                agency_code=profile.agency_code,
                incident_datetime=incident_datetime,
            )
            authoritative_incident_number = numbering.incident_number
            if numbering_policy.get("incidentNumberSource") == "cad_imported":
                if not cad_incident_number or not str(cad_incident_number).strip():
                    raise ValueError(
                        "cad_incident_number is required when incidentNumberSource is cad_imported"
                    )
                authoritative_incident_number = str(cad_incident_number).strip()

            chart = Chart(
                id=client_reference_id or str(uuid.uuid4()),
                tenant_id=tenant_id.strip(),
                call_number=(call_number or authoritative_incident_number).strip(),
                agency_code=numbering.agency_code,
                incident_year=numbering.incident_year,
                incident_sequence=numbering.incident_sequence,
                response_sequence=numbering.response_sequence,
                pcr_sequence=numbering.pcr_sequence,
                billing_sequence=numbering.billing_sequence,
                incident_number=authoritative_incident_number,
                response_number=numbering.response_number,
                pcr_number=numbering.pcr_number,
                billing_case_number=numbering.billing_case_number,
                cad_incident_number=(str(cad_incident_number).strip() if cad_incident_number else None),
                incident_type=incident_type,
                created_by_user_id=created_by_user_id.strip(),
                patient_id=patient_id
            )
            session.add(chart)
            
            compliance = NemsisCompliance(
                id=str(uuid.uuid4()),
                chart_id=chart.id,
                tenant_id=tenant_id.strip(),
                mandatory_fields_required=len(NEMSIS_MANDATORY_FIELDS),
                missing_mandatory_fields=json.dumps(list(NEMSIS_MANDATORY_FIELDS.keys()))
            )
            session.add(compliance)
            
            await session.commit()
            await ChartService.audit(
                session=session,
                tenant_id=tenant_id.strip(),
                chart_id=chart.id,
                user_id=created_by_user_id.strip(),
                action="chart_created",
                detail={
                    "call_number": chart.call_number,
                    "agency_code": chart.agency_code,
                    "incident_number": chart.incident_number,
                    "response_number": chart.response_number,
                    "pcr_number": chart.pcr_number,
                    "billing_case_number": chart.billing_case_number,
                    "incident_type": chart.incident_type,
                    "patient_id": chart.patient_id,
                },
            )
            await ChartService.audit(
                session=session,
                tenant_id=tenant_id.strip(),
                chart_id=chart.id,
                user_id=created_by_user_id.strip(),
                action="incident_numbers_assigned",
                detail={
                    "incident_number": chart.incident_number,
                    "response_number": chart.response_number,
                    "pcr_number": chart.pcr_number,
                    "billing_case_number": chart.billing_case_number,
                    "agency_code": chart.agency_code,
                    "incident_year": chart.incident_year,
                },
            )
            logger.info(f"Chart created: id={chart.id}, call_number={call_number}, incident_type={incident_type}, tenant_id={tenant_id}")
            return chart
        except SQLAlchemyError as e:
            logger.error(f"Database error creating chart for tenant {tenant_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating chart: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_chart(session: AsyncSession, tenant_id: str, chart_id: str) -> Chart:
        """Retrieve chart by ID.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to retrieve.
            
        Returns:
            Chart: Chart object if found, None otherwise.
            
        Raises:
            SQLAlchemyError: If database query fails.
        """
        try:
            result = await session.execute(
                select(Chart).where(
                    and_(
                        Chart.id == chart_id,
                        Chart.tenant_id == tenant_id,
                        Chart.deleted_at.is_(None)
                    )
                )
            )
            chart = result.scalars().first()
            if chart:
                logger.debug(f"Retrieved chart: id={chart_id}, tenant_id={tenant_id}")
            else:
                logger.debug(f"Chart not found: id={chart_id}, tenant_id={tenant_id}")
            return chart
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving chart {chart_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def check_nemsis_compliance(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str
    ) -> dict:
        """Check NEMSIS 3.5.1 compliance for chart.
        
        Validates chart against mandatory NEMSIS 3.5.1 fields and returns
        detailed compliance status, including percentage filled and list
        of missing required fields.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to check.
            
        Returns:
            dict: Compliance status with keys:
                - chart_id: Chart identifier
                - compliance_status: Current compliance status
                - compliance_percentage: Percentage of mandatory fields filled
                - mandatory_fields_filled: Count of populated mandatory fields
                - mandatory_fields_required: Total mandatory fields
                - missing_mandatory_fields: List of missing field IDs
                - is_fully_compliant: Boolean indicating full compliance
                
        Raises:
            ValueError: If chart not found.
            SQLAlchemyError: If database operation fails.
        """
        try:
            chart = await ChartService.get_chart(session, tenant_id, chart_id)
            if not chart:
                logger.warning(f"Compliance check failed: chart not found (id={chart_id}, tenant_id={tenant_id})")
                raise ValueError(f"Chart {chart_id} not found")

            # Legacy mapping table (pre-typed-editor path)
            result = await session.execute(
                select(NemsisMappingRecord).where(
                    and_(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.nemsis_value.isnot(None)
                    )
                )
            )
            populated = {r.nemsis_field for r in result.scalars().all()}

            # New row-per-occurrence ledger (typed-editor projection path).
            # Importing here to avoid a circular-import risk at module load time.
            try:
                from epcr_app.models_nemsis_field_values import NemsisFieldValue
                ledger_result = await session.execute(
                    select(NemsisFieldValue.element_number).where(
                        and_(
                            NemsisFieldValue.chart_id == chart_id,
                            NemsisFieldValue.tenant_id == tenant_id,
                            NemsisFieldValue.deleted_at.is_(None),
                            NemsisFieldValue.value_json.isnot(None),
                        )
                    ).distinct()
                )
                populated.update(row[0] for row in ledger_result.all())
            except Exception:
                pass  # ledger not available in older test setups; legacy check is sufficient

            missing = [f for f in NEMSIS_MANDATORY_FIELDS.keys() if f not in populated]
            
            filled = len(NEMSIS_MANDATORY_FIELDS) - len(missing)
            total = len(NEMSIS_MANDATORY_FIELDS)
            percentage = (filled / total * 100) if total > 0 else 0
            
            if filled == 0:
                status = ComplianceStatus.NOT_STARTED
            elif not missing:
                status = ComplianceStatus.FULLY_COMPLIANT
            elif percentage >= 75:
                status = ComplianceStatus.PARTIALLY_COMPLIANT
            else:
                status = ComplianceStatus.IN_PROGRESS
            
            compliance_result = await session.execute(
                select(NemsisCompliance).where(NemsisCompliance.chart_id == chart_id)
            )
            compliance = compliance_result.scalars().first()
            
            if compliance:
                compliance.compliance_status = status
                compliance.mandatory_fields_filled = filled
                compliance.missing_mandatory_fields = json.dumps(missing)
                compliance.compliance_checked_at = datetime.now(UTC)
                await session.commit()
                logger.info(f"Compliance updated: chart_id={chart_id}, status={status.value}, percentage={percentage:.1f}%")
            
            return {
                "chart_id": chart_id,
                "compliance_status": status.value,
                "compliance_percentage": round(percentage, 2),
                "mandatory_fields_filled": filled,
                "mandatory_fields_required": total,
                "missing_mandatory_fields": missing,
                "is_fully_compliant": status == ComplianceStatus.FULLY_COMPLIANT
            }
        except ValueError:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error checking compliance for chart {chart_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error checking compliance: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def update_chart(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        update_data: dict
    ) -> Chart:
        """Update ePCR chart fields (incident_type, patient_id, vitals, assessment).
        
        Applies partial field updates to a chart, including optional vitals and
        assessment data. Updates chart.updated_at timestamp. Enforces tenant
        isolation and soft-delete filtering.
        
        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier to update.
            update_data: Dict with optional keys:
                - incident_type: str (medical, trauma, behavioral, other)
                - patient_id: str (optional patient identifier)
                - bp_sys, bp_dia, hr, rr, temp_f, spo2, glucose: vitals data
                - chief_complaint, field_diagnosis: assessment data
                
        Returns:
            Chart: Updated chart object.
            
        Raises:
            ValueError: If chart not found or update_data is invalid.
            SQLAlchemyError: If database operation fails.
        """
        try:
            chart = await ChartService.get_chart(session, tenant_id, chart_id)
            if not chart:
                logger.warning(f"Update chart rejected: chart not found (id={chart_id}, tenant_id={tenant_id})")
                raise ValueError(f"Chart {chart_id} not found")
            
            # Update Chart fields if present
            if "incident_type" in update_data and update_data["incident_type"] is not None:
                incident_type = update_data["incident_type"]
                valid_types = ["medical", "trauma", "behavioral", "other"]
                if incident_type not in valid_types:
                    logger.warning(f"Update rejected: invalid incident_type '{incident_type}'")
                    raise ValueError(f"incident_type must be one of: {', '.join(valid_types)}")
                chart.incident_type = incident_type
            
            if "patient_id" in update_data and update_data["patient_id"] is not None:
                chart.patient_id = update_data["patient_id"]
            
            # Update or create Vitals if any vital fields are present
            vital_fields = {"bp_sys", "bp_dia", "hr", "rr", "temp_f", "spo2", "glucose"}
            has_vital_update = any(k in update_data for k in vital_fields)
            
            if has_vital_update:
                result = await session.execute(
                    select(Vitals).where(
                        and_(
                            Vitals.chart_id == chart_id,
                            Vitals.deleted_at.is_(None)
                        )
                    )
                )
                vitals = result.scalars().first()
                
                if not vitals:
                    vitals = Vitals(
                        id=str(uuid.uuid4()),
                        chart_id=chart_id,
                        tenant_id=tenant_id,
                        recorded_at=datetime.now(UTC)
                    )
                    session.add(vitals)
                
                for field in vital_fields:
                    if field in update_data and update_data[field] is not None:
                        setattr(vitals, field, update_data[field])
            
            # Update or create Assessment if assessment fields are present
            assessment_fields = {"chief_complaint", "field_diagnosis"}
            has_assessment_update = any(k in update_data for k in assessment_fields)
            
            if has_assessment_update:
                result = await session.execute(
                    select(Assessment).where(
                        and_(
                            Assessment.chart_id == chart_id,
                            Assessment.deleted_at.is_(None)
                        )
                    )
                )
                assessment = result.scalars().first()
                
                if not assessment:
                    assessment = Assessment(
                        id=str(uuid.uuid4()),
                        chart_id=chart_id,
                        tenant_id=tenant_id,
                        documented_at=datetime.now(UTC)
                    )
                    session.add(assessment)
                
                for field in assessment_fields:
                    if field in update_data and update_data[field] is not None:
                        setattr(assessment, field, update_data[field])
            
            # Update chart timestamp
            chart.updated_at = datetime.now(UTC)
            
            await session.commit()
            logger.info(f"Chart updated: id={chart_id}, tenant_id={tenant_id}, fields_updated={list(update_data.keys())}")
            return chart
        except ValueError:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error updating chart {chart_id}: {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating chart: {str(e)}", exc_info=True)
            raise

    _VALID_TRANSITIONS: dict = {
        ChartStatus.NEW: {ChartStatus.IN_PROGRESS},
        ChartStatus.IN_PROGRESS: {ChartStatus.UNDER_REVIEW, ChartStatus.FINALIZED},
        ChartStatus.UNDER_REVIEW: {ChartStatus.IN_PROGRESS, ChartStatus.FINALIZED},
        ChartStatus.FINALIZED: {ChartStatus.LOCKED},
        ChartStatus.LOCKED: set(),
    }

    @staticmethod
    async def transition_chart_status(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        to_status: ChartStatus,
        user_id: str,
    ) -> Chart:
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        allowed = ChartService._VALID_TRANSITIONS.get(chart.status, set())
        if to_status not in allowed:
            raise ValueError(
                f"Invalid status transition from {chart.status!r} to {to_status!r}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        chart.status = to_status
        chart.updated_at = datetime.now(UTC)
        await session.commit()
        logger.info(f"Chart {chart_id} transitioned to {to_status!r} by user {user_id}")
        return chart

    @staticmethod
    async def record_assessment_finding(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        finding_data: dict,
    ) -> AssessmentFinding:
        """Create a structured CPAE assessment finding for a chart.

        Args:
            session: Async database session.
            tenant_id: Tenant identifier.
            chart_id: Target chart identifier.
            provider_id: User recording the finding.
            finding_data: Structured finding payload.

        Returns:
            Newly created assessment finding.

        Raises:
            ValueError: If chart does not exist or required finding fields are missing.
        """
        required_fields = {"anatomy", "system", "finding_type", "severity", "detection_method"}
        missing = sorted(field for field in required_fields if not finding_data.get(field))
        if missing:
            raise ValueError(f"Missing required finding fields: {', '.join(missing)}")

        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        finding = AssessmentFinding(
            id=finding_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            anatomy=finding_data["anatomy"],
            system=finding_data["system"],
            finding_type=finding_data["finding_type"],
            severity=finding_data["severity"],
            laterality=finding_data.get("laterality"),
            evolution=FindingEvolution(finding_data.get("evolution", FindingEvolution.NEW.value)),
            characteristics_json=json.dumps(finding_data.get("characteristics", [])),
            detection_method=finding_data["detection_method"],
            review_state=ReviewState(finding_data.get("review_state", ReviewState.DIRECT_CONFIRMED.value)),
            provider_id=provider_id,
            source_artifact_ids_json=json.dumps(finding_data.get("source_artifact_ids", [])),
            observed_at=finding_data.get("observed_at", datetime.now(UTC)),
            updated_at=datetime.now(UTC),
        )
        session.add(finding)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_visual_finding_created",
            detail={
                "finding_id": finding.id,
                "anatomy": finding.anatomy,
                "system": finding.system,
                "finding_type": finding.finding_type,
            },
        )
        logger.info("Assessment finding recorded: chart_id=%s finding_id=%s", chart_id, finding.id)
        return finding

    @staticmethod
    async def update_assessment_finding(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        finding_id: str,
        provider_id: str,
        update_data: dict,
    ) -> AssessmentFinding:
        """Update a structured CPAE finding for correction and review workflows."""
        result = await session.execute(
            select(AssessmentFinding).where(
                and_(
                    AssessmentFinding.id == finding_id,
                    AssessmentFinding.chart_id == chart_id,
                    AssessmentFinding.tenant_id == tenant_id,
                )
            )
        )
        finding = result.scalars().first()
        if not finding:
            raise ValueError(f"Finding {finding_id} not found for chart {chart_id}")

        allowed_fields = {
            "severity",
            "laterality",
            "evolution",
            "review_state",
            "characteristics",
            "source_artifact_ids",
        }
        for key, value in update_data.items():
            if key not in allowed_fields or value is None:
                continue
            if key == "evolution":
                finding.evolution = FindingEvolution(value)
            elif key == "review_state":
                finding.review_state = ReviewState(value)
            elif key == "characteristics":
                finding.characteristics_json = json.dumps(value)
            elif key == "source_artifact_ids":
                finding.source_artifact_ids_json = json.dumps(value)
            else:
                setattr(finding, key, value)

        finding.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_visual_finding_updated",
            detail={"finding_id": finding_id, "updated_fields": sorted(update_data.keys())},
        )
        logger.info("Assessment finding updated: chart_id=%s finding_id=%s", chart_id, finding.id)
        return finding

    @staticmethod
    async def record_visual_overlay(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        overlay_data: dict,
    ) -> VisualOverlay:
        """Create a governed visual overlay linked to an assessment finding."""
        required_fields = {
            "finding_id",
            "patient_model",
            "anatomical_view",
            "overlay_type",
            "anchor_region",
            "geometry_reference",
            "severity",
        }
        missing = sorted(field for field in required_fields if not overlay_data.get(field))
        if missing:
            raise ValueError(f"Missing required overlay fields: {', '.join(missing)}")

        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        finding_result = await session.execute(
            select(AssessmentFinding).where(
                and_(
                    AssessmentFinding.id == overlay_data["finding_id"],
                    AssessmentFinding.chart_id == chart_id,
                    AssessmentFinding.tenant_id == tenant_id,
                )
            )
        )
        finding = finding_result.scalars().first()
        if not finding:
            raise ValueError(f"Finding {overlay_data['finding_id']} not found for chart {chart_id}")

        overlay = VisualOverlay(
            id=overlay_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            finding_id=finding.id,
            tenant_id=tenant_id,
            patient_model=overlay_data["patient_model"],
            anatomical_view=overlay_data["anatomical_view"],
            overlay_type=overlay_data["overlay_type"],
            anchor_region=overlay_data["anchor_region"],
            geometry_reference=overlay_data["geometry_reference"],
            severity=overlay_data["severity"],
            evolution=FindingEvolution(overlay_data.get("evolution", FindingEvolution.NEW.value)),
            review_state=ReviewState(overlay_data.get("review_state", ReviewState.DIRECT_CONFIRMED.value)),
            provider_id=provider_id,
            evidence_artifact_ids_json=json.dumps(overlay_data.get("evidence_artifact_ids", [])),
            rendered_at=overlay_data.get("rendered_at", datetime.now(UTC)),
        )
        session.add(overlay)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_visual_overlay_created",
            detail={
                "overlay_id": overlay.id,
                "finding_id": overlay.finding_id,
                "overlay_type": overlay.overlay_type,
            },
        )
        logger.info("Visual overlay recorded: chart_id=%s overlay_id=%s", chart_id, overlay.id)
        return overlay

    @staticmethod
    async def update_visual_overlay(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        overlay_id: str,
        provider_id: str,
        update_data: dict,
    ) -> VisualOverlay:
        """Update a governed VAS overlay for review/correction workflows."""
        result = await session.execute(
            select(VisualOverlay).where(
                and_(
                    VisualOverlay.id == overlay_id,
                    VisualOverlay.chart_id == chart_id,
                    VisualOverlay.tenant_id == tenant_id,
                )
            )
        )
        overlay = result.scalars().first()
        if not overlay:
            raise ValueError(f"Visual overlay {overlay_id} not found for chart {chart_id}")

        allowed_fields = {
            "geometry_reference",
            "severity",
            "evolution",
            "review_state",
            "evidence_artifact_ids",
        }
        for key, value in update_data.items():
            if key not in allowed_fields or value is None:
                continue
            if key == "evolution":
                overlay.evolution = FindingEvolution(value)
            elif key == "review_state":
                overlay.review_state = ReviewState(value)
            elif key == "evidence_artifact_ids":
                overlay.evidence_artifact_ids_json = json.dumps(value)
            else:
                setattr(overlay, key, value)

        overlay.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_visual_overlay_updated",
            detail={"overlay_id": overlay_id, "updated_fields": sorted(update_data.keys())},
        )
        logger.info("Visual overlay updated: chart_id=%s overlay_id=%s", chart_id, overlay.id)
        return overlay

    @staticmethod
    async def start_ar_session(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        started_by_user_id: str,
        patient_model: str,
        mode: str,
        client_reference_id: str | None = None,
    ) -> ArSession:
        """Start an ARCOS session for a chart."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        ar_session = ArSession(
            id=client_reference_id or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            patient_model=patient_model,
            mode=mode,
            status=ArSessionStatus.ACTIVE,
            started_by_user_id=started_by_user_id,
            started_at=datetime.now(UTC),
        )
        session.add(ar_session)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=started_by_user_id,
            action="clinical_visual_ar_session_started",
            detail={"session_id": ar_session.id, "patient_model": patient_model, "mode": mode},
        )
        logger.info("AR session started: chart_id=%s session_id=%s", chart_id, ar_session.id)
        return ar_session

    @staticmethod
    async def record_ar_anchor(
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        anchored_by_user_id: str,
        anatomy: str,
        anatomical_view: str,
        confidence: float,
        client_reference_id: str | None = None,
    ) -> ArAnchor:
        """Record an anatomical anchor for an existing ARCOS session."""
        session_result = await session.execute(
            select(ArSession).where(
                and_(
                    ArSession.id == session_id,
                    ArSession.tenant_id == tenant_id,
                )
            )
        )
        ar_session = session_result.scalars().first()
        if not ar_session:
            raise ValueError(f"AR session {session_id} not found")

        anchor = ArAnchor(
            id=client_reference_id or str(uuid.uuid4()),
            session_id=session_id,
            tenant_id=tenant_id,
            anatomy=anatomy,
            anatomical_view=anatomical_view,
            confidence=confidence,
            anchored_by_user_id=anchored_by_user_id,
            anchored_at=datetime.now(UTC),
        )
        session.add(anchor)
        ar_session.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=ar_session.chart_id,
            user_id=anchored_by_user_id,
            action="clinical_visual_ar_anchor_recorded",
            detail={"session_id": session_id, "anchor_id": anchor.id, "anatomy": anatomy},
        )
        logger.info("AR anchor recorded: session_id=%s anchor_id=%s", session_id, anchor.id)
        return anchor

    @staticmethod
    async def complete_ar_session(
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        completed_by_user_id: str,
    ) -> ArSession:
        """Complete an active ARCOS session and lock its lifecycle state."""
        result = await session.execute(
            select(ArSession).where(
                and_(
                    ArSession.id == session_id,
                    ArSession.tenant_id == tenant_id,
                )
            )
        )
        ar_session = result.scalars().first()
        if not ar_session:
            raise ValueError(f"AR session {session_id} not found")

        ar_session.status = ArSessionStatus.COMPLETED
        ar_session.ended_at = datetime.now(UTC)
        ar_session.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=ar_session.chart_id,
            user_id=completed_by_user_id,
            action="clinical_visual_ar_session_completed",
            detail={"session_id": session_id},
        )
        logger.info("AR session completed: session_id=%s chart_id=%s", session_id, ar_session.chart_id)
        return ar_session

    @staticmethod
    async def upsert_chart_address(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        address_data: dict,
    ) -> ChartAddress:
        """Create or update structured address intelligence for a chart."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        if not address_data.get("raw_text"):
            raise ValueError("raw_text is required for address intelligence")

        result = await session.execute(
            select(ChartAddress).where(
                and_(ChartAddress.chart_id == chart_id, ChartAddress.tenant_id == tenant_id)
            )
        )
        address = result.scalars().first()
        validation_state = address_data.get("validation_state")
        if validation_state is None:
            validation_state = (
                AddressValidationState.VALIDATED.value
                if address_data.get("latitude") is not None and address_data.get("longitude") is not None
                else AddressValidationState.MANUAL_VERIFIED.value
            )
        if address is None:
            address = ChartAddress(
                id=str(uuid.uuid4()),
                chart_id=chart_id,
                tenant_id=tenant_id,
                raw_text=address_data["raw_text"],
                street_line_one=address_data.get("street_line_one"),
                street_line_two=address_data.get("street_line_two"),
                city=address_data.get("city"),
                state=address_data.get("state"),
                postal_code=address_data.get("postal_code"),
                county=address_data.get("county"),
                latitude=address_data.get("latitude"),
                longitude=address_data.get("longitude"),
                validation_state=AddressValidationState(validation_state),
                intelligence_source=address_data.get("intelligence_source", "manual_entry"),
                intelligence_detail=address_data.get("intelligence_detail"),
                updated_at=datetime.now(UTC),
            )
            session.add(address)
            action = "chart_address_created"
        else:
            for field in (
                "raw_text",
                "street_line_one",
                "street_line_two",
                "city",
                "state",
                "postal_code",
                "county",
                "latitude",
                "longitude",
                "intelligence_source",
                "intelligence_detail",
            ):
                if field in address_data:
                    setattr(address, field, address_data.get(field))
            address.validation_state = AddressValidationState(validation_state)
            address.updated_at = datetime.now(UTC)
            action = "chart_address_updated"

        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action=action,
            detail={"validation_state": address.validation_state.value, "source": address.intelligence_source},
        )
        return address

    @staticmethod
    async def record_intervention(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        intervention_data: dict,
    ) -> ClinicalIntervention:
        """Create a structured intervention with protocol and terminology binding."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        required = {"category", "name", "indication", "intent", "expected_response", "protocol_family"}
        missing = sorted(field for field in required if not intervention_data.get(field))
        if missing:
            raise ValueError(f"Missing required intervention fields: {', '.join(missing)}")

        intervention = ClinicalIntervention(
            id=intervention_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            category=intervention_data["category"],
            name=intervention_data["name"],
            indication=intervention_data["indication"],
            intent=intervention_data["intent"],
            expected_response=intervention_data["expected_response"],
            actual_response=intervention_data.get("actual_response"),
            reassessment_due_at=intervention_data.get("reassessment_due_at"),
            protocol_family=ProtocolFamily(intervention_data["protocol_family"]),
            snomed_code=intervention_data.get("snomed_code"),
            icd10_code=intervention_data.get("icd10_code"),
            rxnorm_code=intervention_data.get("rxnorm_code"),
            export_state=InterventionExportState(intervention_data.get("export_state", InterventionExportState.PENDING_MAPPING.value)),
            performed_at=intervention_data.get("performed_at", datetime.now(UTC)),
            updated_at=datetime.now(UTC),
            provider_id=provider_id,
        )
        session.add(intervention)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="intervention_created",
            detail={"intervention_id": intervention.id, "protocol_family": intervention.protocol_family.value, "name": intervention.name},
        )
        return intervention

    @staticmethod
    async def update_intervention(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        intervention_id: str,
        provider_id: str,
        update_data: dict,
    ) -> ClinicalIntervention:
        """Update a structured intervention response and export state."""
        result = await session.execute(
            select(ClinicalIntervention).where(
                and_(
                    ClinicalIntervention.id == intervention_id,
                    ClinicalIntervention.chart_id == chart_id,
                    ClinicalIntervention.tenant_id == tenant_id,
                )
            )
        )
        intervention = result.scalars().first()
        if not intervention:
            raise ValueError(f"Intervention {intervention_id} not found for chart {chart_id}")

        for key, value in update_data.items():
            if value is None:
                continue
            if key == "protocol_family":
                intervention.protocol_family = ProtocolFamily(value)
            elif key == "export_state":
                intervention.export_state = InterventionExportState(value)
            else:
                setattr(intervention, key, value)
        intervention.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="intervention_updated",
            detail={"intervention_id": intervention_id, "updated_fields": sorted(update_data.keys())},
        )
        return intervention

    @staticmethod
    def _summarize_note(raw_text: str) -> str:
        cleaned = " ".join(raw_text.split())
        if len(cleaned) <= 180:
            return cleaned
        return cleaned[:177] + "..."

    @staticmethod
    async def record_clinical_note(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        provider_id: str,
        note_data: dict,
    ) -> ClinicalNote:
        """Capture smart clinical text with deterministic derived summary."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        raw_text = note_data.get("raw_text", "").strip()
        if not raw_text:
            raise ValueError("raw_text is required for clinical note capture")

        note = ClinicalNote(
            id=note_data.get("client_reference_id") or str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            raw_text=raw_text,
            source=note_data.get("source", "manual_entry"),
            provenance_json=json.dumps(note_data.get("provenance", {})),
            derived_summary=ChartService._summarize_note(raw_text),
            review_state=ClinicalNoteReviewState(note_data.get("review_state", ClinicalNoteReviewState.PENDING_REVIEW.value)),
            captured_at=note_data.get("captured_at", datetime.now(UTC)),
            updated_at=datetime.now(UTC),
            provider_id=provider_id,
        )
        session.add(note)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_note_created",
            detail={"note_id": note.id, "source": note.source, "review_state": note.review_state.value},
        )
        return note

    @staticmethod
    async def update_clinical_note(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        note_id: str,
        provider_id: str,
        update_data: dict,
    ) -> ClinicalNote:
        """Review or correct a captured clinical note."""
        result = await session.execute(
            select(ClinicalNote).where(
                and_(ClinicalNote.id == note_id, ClinicalNote.chart_id == chart_id, ClinicalNote.tenant_id == tenant_id)
            )
        )
        note = result.scalars().first()
        if not note:
            raise ValueError(f"Clinical note {note_id} not found for chart {chart_id}")

        if update_data.get("raw_text"):
            note.raw_text = update_data["raw_text"]
            note.derived_summary = ChartService._summarize_note(note.raw_text)
        if update_data.get("review_state"):
            note.review_state = ClinicalNoteReviewState(update_data["review_state"])
        note.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=provider_id,
            action="clinical_note_updated",
            detail={"note_id": note_id, "updated_fields": sorted(update_data.keys())},
        )
        return note

    @staticmethod
    def _recommendation_specs(chart: Chart, findings: list[AssessmentFinding], interventions: list[ClinicalIntervention], patient_model: str) -> list[dict]:
        specs: list[dict] = []
        severe_findings = [finding for finding in findings if finding.severity in {"severe", "critical"}]
        respiratory = any(f.system == "respiratory" for f in severe_findings)
        trauma = chart.incident_type == "trauma"
        neuro = any(f.system == "neurological" for f in severe_findings)

        if patient_model == "adult" and respiratory:
            specs.append({
                "protocol_family": ProtocolFamily.ACLS.value,
                "title": "ACLS airway and ventilation escalation",
                "rationale": "Adult chart contains severe respiratory findings requiring ACLS airway assessment and response planning.",
                "action_priority": 1,
                "evidence": {"severe_findings": [f.finding_type for f in severe_findings]},
            })
        if patient_model == "pediatric" and respiratory:
            specs.append({
                "protocol_family": ProtocolFamily.PALS.value,
                "title": "PALS respiratory stabilization review",
                "rationale": "Pediatric respiratory severity requires PALS dosing, airway, and reassessment cadence review.",
                "action_priority": 1,
                "evidence": {"severe_findings": [f.finding_type for f in severe_findings]},
            })
        if patient_model == "neonatal":
            specs.append({
                "protocol_family": ProtocolFamily.NRP.value,
                "title": "NRP neonatal support pathway",
                "rationale": "Neonatal patient model requires NRP-aligned airway, thermoregulation, and reassessment workflow.",
                "action_priority": 1,
                "evidence": {"patient_model": patient_model},
            })
        if trauma:
            specs.append({
                "protocol_family": ProtocolFamily.TPATC.value,
                "title": "TPATC trauma transport and hemorrhage review",
                "rationale": "Trauma chart requires transport-priority and hemorrhage-control review under TPATC workflow.",
                "action_priority": 2,
                "evidence": {"incident_type": chart.incident_type},
            })
        if neuro and not any(intervention.category == "monitoring" for intervention in interventions):
            specs.append({
                "protocol_family": ProtocolFamily.GENERAL.value,
                "title": "Neurologic monitoring gap",
                "rationale": "Critical neurologic findings exist without a documented monitoring intervention.",
                "action_priority": 2,
                "evidence": {"severe_findings": [f.finding_type for f in severe_findings]},
            })
        if not specs:
            specs.append({
                "protocol_family": ProtocolFamily.GENERAL.value,
                "title": "Continue structured reassessment cadence",
                "rationale": "No high-acuity blockers detected; continue CareGraph reassessment and document response to interventions.",
                "action_priority": 3,
                "evidence": {"finding_count": len(findings), "intervention_count": len(interventions)},
            })
        return specs

    @staticmethod
    async def generate_protocol_recommendations(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        generated_by_user_id: str,
        patient_model: str,
    ) -> list[ProtocolRecommendation]:
        """Generate deterministic protocol guidance from current chart truth."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        findings_result = await session.execute(
            select(AssessmentFinding).where(
                and_(AssessmentFinding.chart_id == chart_id, AssessmentFinding.tenant_id == tenant_id)
            )
        )
        interventions_result = await session.execute(
            select(ClinicalIntervention).where(
                and_(ClinicalIntervention.chart_id == chart_id, ClinicalIntervention.tenant_id == tenant_id)
            )
        )
        findings = findings_result.scalars().all()
        interventions = interventions_result.scalars().all()
        recommendations: list[ProtocolRecommendation] = []
        for spec in ChartService._recommendation_specs(chart, findings, interventions, patient_model):
            recommendation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chart_id}:{spec['protocol_family']}:{spec['title']}"))
            result = await session.execute(
                select(ProtocolRecommendation).where(
                    and_(ProtocolRecommendation.id == recommendation_id, ProtocolRecommendation.tenant_id == tenant_id)
                )
            )
            recommendation = result.scalars().first()
            if recommendation is None:
                recommendation = ProtocolRecommendation(
                    id=recommendation_id,
                    chart_id=chart_id,
                    tenant_id=tenant_id,
                    protocol_family=ProtocolFamily(spec["protocol_family"]),
                    title=spec["title"],
                    rationale=spec["rationale"],
                    action_priority=spec["action_priority"],
                    evidence_json=json.dumps(spec["evidence"]),
                    state=ProtocolRecommendationState.OPEN,
                    generated_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(recommendation)
            else:
                recommendation.rationale = spec["rationale"]
                recommendation.action_priority = spec["action_priority"]
                recommendation.evidence_json = json.dumps(spec["evidence"])
                recommendation.generated_at = datetime.now(UTC)
                recommendation.updated_at = datetime.now(UTC)
            recommendations.append(recommendation)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=generated_by_user_id,
            action="protocol_recommendations_generated",
            detail={"count": len(recommendations), "patient_model": patient_model},
        )
        return recommendations

    @staticmethod
    async def update_protocol_recommendation_state(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        recommendation_id: str,
        user_id: str,
        state: str,
    ) -> ProtocolRecommendation:
        """Accept or dismiss a deterministic protocol recommendation."""
        result = await session.execute(
            select(ProtocolRecommendation).where(
                and_(
                    ProtocolRecommendation.id == recommendation_id,
                    ProtocolRecommendation.chart_id == chart_id,
                    ProtocolRecommendation.tenant_id == tenant_id,
                )
            )
        )
        recommendation = result.scalars().first()
        if not recommendation:
            raise ValueError(f"Protocol recommendation {recommendation_id} not found for chart {chart_id}")
        recommendation.state = ProtocolRecommendationState(state)
        recommendation.updated_at = datetime.now(UTC)
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=user_id,
            action="protocol_recommendation_updated",
            detail={"recommendation_id": recommendation_id, "state": state},
        )
        return recommendation

    @staticmethod
    async def generate_derived_output(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        generated_by_user_id: str,
        output_type: str,
    ) -> DerivedChartOutput:
        """Generate and persist a CareGraph-derived narrative or handoff output."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        findings_result = await session.execute(
            select(AssessmentFinding).where(
                and_(AssessmentFinding.chart_id == chart_id, AssessmentFinding.tenant_id == tenant_id)
            )
        )
        vitals_result = await session.execute(
            select(Vitals).where(and_(Vitals.chart_id == chart_id, Vitals.tenant_id == tenant_id, Vitals.deleted_at.is_(None)))
        )
        patient_result = await session.execute(
            select(PatientProfile).where(and_(PatientProfile.chart_id == chart_id, PatientProfile.tenant_id == tenant_id))
        )
        assessment_result = await session.execute(
            select(Assessment).where(and_(Assessment.chart_id == chart_id, Assessment.tenant_id == tenant_id, Assessment.deleted_at.is_(None)))
        )
        medications_result = await session.execute(
            select(MedicationAdministration).where(
                and_(MedicationAdministration.chart_id == chart_id, MedicationAdministration.tenant_id == tenant_id)
            )
        )
        signatures_result = await session.execute(
            select(EpcrSignatureArtifact).where(
                and_(EpcrSignatureArtifact.chart_id == chart_id, EpcrSignatureArtifact.tenant_id == tenant_id)
            )
        )
        interventions_result = await session.execute(
            select(ClinicalIntervention).where(
                and_(ClinicalIntervention.chart_id == chart_id, ClinicalIntervention.tenant_id == tenant_id)
            )
        )
        notes_result = await session.execute(
            select(ClinicalNote).where(and_(ClinicalNote.chart_id == chart_id, ClinicalNote.tenant_id == tenant_id))
        )
        address_result = await session.execute(
            select(ChartAddress).where(and_(ChartAddress.chart_id == chart_id, ChartAddress.tenant_id == tenant_id))
        )
        findings_list = findings_result.scalars().all()
        vitals_list = vitals_result.scalars().all()
        patient_profile = patient_result.scalars().first()
        assessment = assessment_result.scalars().first()
        medications_list = medications_result.scalars().all()
        signatures_list = signatures_result.scalars().all()
        interventions_list = interventions_result.scalars().all()
        notes_list = notes_result.scalars().all()
        address_record = address_result.scalars().first()

        findings = ", ".join(f"{finding.finding_type} ({finding.severity})" for finding in findings_list) or "no structured findings recorded"
        latest_vitals = vitals_list[0] if vitals_list else None
        vitals_summary = (
            f"HR {latest_vitals.hr or 'n/a'}, RR {latest_vitals.rr or 'n/a'}, SpO2 {latest_vitals.spo2 or 'n/a'}"
            if latest_vitals
            else "no vitals documented"
        )
        patient_name = " ".join(filter(None, [patient_profile.first_name if patient_profile else None, patient_profile.last_name if patient_profile else None])) or "patient identity pending"
        impression = assessment.primary_impression if assessment and assessment.primary_impression else "impression pending"
        medications = ", ".join(
            f"{med.medication_name} {med.dose_value or ''}{(' ' + med.dose_unit) if med.dose_unit else ''}".strip()
            for med in medications_list
        ) or "no medications documented"
        signatures = ", ".join(
            f"{signature.signature_class}:{signature.compliance_decision}"
            for signature in signatures_list
        ) or "no signatures documented"
        interventions = ", ".join(intervention.name for intervention in interventions_list) or "no interventions documented"
        note_summaries = "; ".join(note.derived_summary for note in notes_list[-2:]) or "no clinical notes captured"
        address = address_record.raw_text if address_record else "address unavailable"

        if output_type == DerivedOutputType.NARRATIVE.value:
            content = f"CareGraph narrative for {chart.call_number}: {patient_name}; impression {impression}; vitals {vitals_summary}; findings {findings}; medications {medications}; signatures {signatures}; interventions {interventions}; notes {note_summaries}; scene {address}."
        elif output_type == DerivedOutputType.HANDOFF.value:
            content = f"Handoff summary: incident {chart.incident_type}; patient {patient_name}; impression {impression}; vitals {vitals_summary}; medications {medications}; signatures {signatures}; active interventions {interventions}; scene {address}."
        else:
            content = f"Clinical summary: chart {chart.call_number}; patient {patient_name}; impression {impression}; vitals {vitals_summary}; findings {findings}; medications {medications}; signatures {signatures}; interventions {interventions}; notes {note_summaries}."

        derived_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chart_id}:{output_type}"))
        result = await session.execute(
            select(DerivedChartOutput).where(
                and_(DerivedChartOutput.id == derived_id, DerivedChartOutput.tenant_id == tenant_id)
            )
        )
        derived = result.scalars().first()
        if derived is None:
            derived = DerivedChartOutput(
                id=derived_id,
                chart_id=chart_id,
                tenant_id=tenant_id,
                output_type=DerivedOutputType(output_type),
                content_text=content,
                source_revision=str(int(datetime.now(UTC).timestamp())),
                generated_at=datetime.now(UTC),
                generated_by_user_id=generated_by_user_id,
            )
            session.add(derived)
        else:
            derived.content_text = content
            derived.source_revision = str(int(datetime.now(UTC).timestamp()))
            derived.generated_at = datetime.now(UTC)
            derived.generated_by_user_id = generated_by_user_id
        await session.commit()
        await ChartService.audit(
            session=session,
            tenant_id=tenant_id,
            chart_id=chart_id,
            user_id=generated_by_user_id,
            action="derived_output_generated",
            detail={"output_type": output_type, "derived_output_id": derived.id},
        )
        return derived

    @staticmethod
    async def get_dashboard_summary(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
    ) -> dict:
        """Compute a truthful dashboard summary for field and command surfaces."""
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")
        compliance = await ChartService.check_nemsis_compliance(session, tenant_id, chart_id)
        findings_result = await session.execute(
            select(AssessmentFinding).where(
                and_(AssessmentFinding.chart_id == chart_id, AssessmentFinding.tenant_id == tenant_id)
            )
        )
        vitals_result = await session.execute(
            select(Vitals).where(and_(Vitals.chart_id == chart_id, Vitals.tenant_id == tenant_id, Vitals.deleted_at.is_(None)))
        )
        patient_result = await session.execute(
            select(PatientProfile).where(and_(PatientProfile.chart_id == chart_id, PatientProfile.tenant_id == tenant_id))
        )
        assessment_result = await session.execute(
            select(Assessment).where(and_(Assessment.chart_id == chart_id, Assessment.tenant_id == tenant_id, Assessment.deleted_at.is_(None)))
        )
        medications_result = await session.execute(
            select(MedicationAdministration).where(
                and_(MedicationAdministration.chart_id == chart_id, MedicationAdministration.tenant_id == tenant_id)
            )
        )
        signatures_result = await session.execute(
            select(EpcrSignatureArtifact).where(
                and_(EpcrSignatureArtifact.chart_id == chart_id, EpcrSignatureArtifact.tenant_id == tenant_id)
            )
        )
        interventions_result = await session.execute(
            select(ClinicalIntervention).where(
                and_(ClinicalIntervention.chart_id == chart_id, ClinicalIntervention.tenant_id == tenant_id)
            )
        )
        notes_result = await session.execute(
            select(ClinicalNote).where(and_(ClinicalNote.chart_id == chart_id, ClinicalNote.tenant_id == tenant_id))
        )
        protocol_result = await session.execute(
            select(ProtocolRecommendation).where(
                and_(ProtocolRecommendation.chart_id == chart_id, ProtocolRecommendation.tenant_id == tenant_id)
            )
        )
        outputs_result = await session.execute(
            select(DerivedChartOutput).where(
                and_(DerivedChartOutput.chart_id == chart_id, DerivedChartOutput.tenant_id == tenant_id)
            )
        )
        address_result = await session.execute(
            select(ChartAddress).where(and_(ChartAddress.chart_id == chart_id, ChartAddress.tenant_id == tenant_id))
        )
        findings = findings_result.scalars().all()
        vitals = vitals_result.scalars().all()
        patient_profile = patient_result.scalars().first()
        assessment = assessment_result.scalars().first()
        medications = medications_result.scalars().all()
        signatures = signatures_result.scalars().all()
        interventions = interventions_result.scalars().all()
        notes = notes_result.scalars().all()
        protocols = protocol_result.scalars().all()
        outputs = outputs_result.scalars().all()
        address = address_result.scalars().first()
        accepted_notes = sum(1 for note in notes if note.review_state == ClinicalNoteReviewState.ACCEPTED)
        return {
            "chart_id": chart_id,
            "chart_status": chart.status.value,
            "patient_profile_present": patient_profile is not None,
            "vitals_count": len(vitals),
            "finding_count": len(findings),
            "medication_count": len(medications),
            "signature_count": len(signatures),
            "intervention_count": len(interventions),
            "impression_documented": bool(assessment and (assessment.primary_impression or assessment.field_diagnosis or assessment.chief_complaint)),
            "chart_completion_blocked_by_signature": any(signature.chart_completion_effect != "complete" for signature in signatures),
            "pending_note_review_count": sum(1 for note in notes if note.review_state == ClinicalNoteReviewState.PENDING_REVIEW),
            "accepted_note_count": accepted_notes,
            "protocol_recommendation_count": len(protocols),
            "derived_output_count": len(outputs),
            "address_validation_state": address.validation_state.value if address else AddressValidationState.NEEDS_REVIEW.value,
            "ready_for_nemsis_export": compliance["is_fully_compliant"],
            "nemsis_missing_fields": compliance["missing_mandatory_fields"],
        }

    @staticmethod
    async def record_nemsis_field(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        nemsis_field: str,
        nemsis_value: str,
        source: str = "manual"
    ) -> "NemsisMappingRecord":
        """Record or update a single NEMSIS field value for a chart.

        Creates a new NemsisMappingRecord if the field does not exist for this
        chart, or updates the existing record if it does. Updates compliance
        status after recording. Raises ValueError if chart not found.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier (enforces tenant isolation).
            chart_id: Chart identifier.
            nemsis_field: NEMSIS field identifier (e.g. 'eRecord.01').
            nemsis_value: Value to record for this field.
            source: Source of value: manual, ocr, device, or system.

        Returns:
            NemsisMappingRecord: Created or updated mapping record.

        Raises:
            ValueError: If chart not found or source is invalid.
            SQLAlchemyError: If database operation fails.
        """
        valid_sources = {"manual", "ocr", "device", "system"}
        if source not in valid_sources:
            raise ValueError(f"source must be one of: {', '.join(sorted(valid_sources))}")

        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ValueError(f"Chart {chart_id} not found")

        try:
            existing = await session.execute(
                select(NemsisMappingRecord).where(
                    and_(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.nemsis_field == nemsis_field
                    )
                )
            )
            record = existing.scalars().first()

            if record:
                record.nemsis_value = nemsis_value
                record.source = FieldSource(source)
                record.updated_at = datetime.now(UTC)
            else:
                record = NemsisMappingRecord(
                    id=str(uuid.uuid4()),
                    chart_id=chart_id,
                    tenant_id=tenant_id.strip(),
                    nemsis_field=nemsis_field,
                    nemsis_value=nemsis_value,
                    source=FieldSource(source)
                )
                session.add(record)

            await session.commit()
            logger.info(
                f"NEMSIS field recorded: chart_id={chart_id}, field={nemsis_field}, source={source}"
            )
            return record
        except SQLAlchemyError as e:
            logger.error(f"Database error recording NEMSIS field for chart {chart_id}: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def record_export(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        exported_by_user_id: str,
        export_status: str,
        export_payload: dict,
        error_message: str = None,
    ) -> "NemsisExportHistory":
        """Record a NEMSIS export attempt in the export history table.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier.
            chart_id: Chart identifier.
            exported_by_user_id: User who triggered the export.
            export_status: 'success' or 'failed'.
            export_payload: Dict of NEMSIS fields at time of export.
            error_message: Error detail if export failed (optional).

        Returns:
            NemsisExportHistory: Created export history record.

        Raises:
            SQLAlchemyError: If database operation fails.
        """
        import json as _json
        from epcr_app.models import NemsisExportHistory
        record = NemsisExportHistory(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            exported_by_user_id=exported_by_user_id,
            export_status=export_status,
            export_payload_json=_json.dumps(export_payload) if export_payload else None,
            error_message=error_message,
        )
        session.add(record)
        await session.commit()
        logger.info(
            f"Export recorded: chart_id={chart_id}, status={export_status}, "
            f"user={exported_by_user_id}"
        )
        return record

    @staticmethod
    async def audit(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        user_id: str,
        action: str,
        detail: dict = None,
    ) -> None:
        """Write an audit log entry for an ePCR chart action.

        Args:
            session: AsyncSession for database operations.
            tenant_id: Tenant identifier.
            chart_id: Chart identifier.
            user_id: User performing the action.
            action: Action type (create, update, finalize, export, compliance_check).
            detail: Optional dict with additional context.
        """
        import json as _json
        from epcr_app.models import EpcrAuditLog
        entry = EpcrAuditLog(
            id=str(uuid.uuid4()),
            chart_id=chart_id,
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            detail_json=_json.dumps(detail) if detail else None,
        )
        session.add(entry)
        await session.commit()
        logger.info(f"Audit: chart_id={chart_id}, action={action}, user={user_id}")
