"""Chart workspace orchestration service.

Thin façade over existing chart, NEMSIS, finalization-gate, export, and
submission services. This module does NOT implement a parallel chart
engine. Every persistence, validation, finalization, export, and
submission action is delegated to the already-canonical service that owns
that truth. The workspace contract aggregates the same data into a single
shape so the EPCR charting UI can consume one consistent payload.

No fake success. Unsupported sections are honestly reported as
``field_not_mapped``. Export and submission paths return ``unavailable``
status when the underlying capability is not configured rather than
fabricating completion.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.dependencies import CurrentUser
from epcr_app.chart_finalization_service import (
    ChartFinalizationError,
    ChartFinalizationService,
)
from epcr_app.models import (
    AssessmentFinding,
    Chart,
    ChartAddress,
    ClinicalIntervention,
    ClinicalNote,
    EpcrAuditLog,
    EpcrSignatureArtifact,
    MedicationAdministration,
    NemsisExportHistory,
    NemsisMappingRecord,
    PatientProfile,
    Vitals,
)
from epcr_app.services import ChartService
from epcr_app.services.anatomical_finding_service import (
    AnatomicalFindingService,
)
from epcr_app.services.anatomical_finding_validation import (
    AnatomicalFindingValidationError,
)
from epcr_app.services.audit_trail_query_service import AuditTrailQueryService
from epcr_app.services.ecustom_field_service import ECustomFieldService
from epcr_app.services.icd10_service import (
    list_for_chart as icd10_list_for_chart,
    serialize as icd10_serialize,
    specificity_score as icd10_specificity_score,
)
from epcr_app.services.lock_readiness_service import LockReadinessService
from epcr_app.services.map_location_service import MapLocationService
from epcr_app.services.multi_patient_service import MultiPatientService
from epcr_app.services.prior_ecg_service import (
    list_prior_for_chart as prior_ecg_list_for_chart,
)
from epcr_app.services.protocol_context_service import ProtocolContextService
from epcr_app.services.repeat_patient_service import RepeatPatientService
from epcr_app.services.rxnorm_service import RxNormService
from epcr_app.services.sentence_evidence_service import SentenceEvidenceService
import os as _os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section routing — declarative mapping of workspace sections to backing
# ChartService methods. Sections that have no canonical backend owner today
# are mapped to ``None`` and surfaced as ``field_not_mapped`` rather than
# silently swallowed.
# ---------------------------------------------------------------------------

SUPPORTED_SECTIONS: set[str] = {
    "patient",
    "incident",
    "scene",
    "assessment",
    "complaint",
    "vitals",
    "treatment",
    "procedures",
    "medications_administered",
    "narrative",
    "signatures",
    "nemsis",
}

UNMAPPED_SECTIONS: set[str] = {
    "response",
    "crew",
    "history",
    "allergies",
    "home_medications",
    "disposition",
    "destination",
    "attachments",
    "export",
}

ALL_SECTIONS: set[str] = SUPPORTED_SECTIONS | UNMAPPED_SECTIONS


class ChartWorkspaceError(Exception):
    """Raised for client-visible workspace orchestration errors.

    Carries an optional ``detail`` payload that the API layer surfaces as
    structured JSON so the frontend can render natural-language reasons.
    """

    def __init__(self, message: str, *, status_code: int = 400, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or {"message": message}


class ChartWorkspaceService:
    """Workspace orchestrator over canonical chart services.

    All methods are static. They take an ``AsyncSession`` and the
    authenticated ``CurrentUser`` so tenant isolation is preserved end to
    end with no shortcut.
    """

    # ----------------------------------------------------------------- #
    # Internal helpers                                                  #
    # ----------------------------------------------------------------- #

    @staticmethod
    def _tenant(current_user: CurrentUser) -> str:
        return str(current_user.tenant_id)

    @staticmethod
    def _user(current_user: CurrentUser) -> str:
        return str(current_user.user_id)

    @staticmethod
    def _serialize_chart(chart: Chart) -> dict:
        return {
            "id": chart.id,
            "call_number": chart.call_number,
            "agency_code": chart.agency_code,
            "incident_year": chart.incident_year,
            "incident_sequence": chart.incident_sequence,
            "response_sequence": chart.response_sequence,
            "pcr_sequence": chart.pcr_sequence,
            "billing_sequence": chart.billing_sequence,
            "incident_number": chart.incident_number,
            "response_number": chart.response_number,
            "pcr_number": chart.pcr_number,
            "billing_case_number": chart.billing_case_number,
            "cad_incident_number": chart.cad_incident_number,
            "external_incident_number": chart.external_incident_number,
            "incident_type": chart.incident_type,
            "status": chart.status.value if chart.status else None,
            "patient_id": chart.patient_id,
            "created_at": chart.created_at.isoformat() if chart.created_at else None,
            "updated_at": chart.updated_at.isoformat() if chart.updated_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None,
        }

    @staticmethod
    def _serialize_patient(profile: PatientProfile | None) -> dict | None:
        if profile is None:
            return None
        try:
            allergies = json.loads(profile.allergies_json) if profile.allergies_json else []
        except (TypeError, ValueError):
            allergies = []
        return {
            "id": profile.id,
            "first_name": profile.first_name,
            "middle_name": profile.middle_name,
            "last_name": profile.last_name,
            "date_of_birth": profile.date_of_birth,
            "age_years": profile.age_years,
            "sex": profile.sex,
            "phone_number": profile.phone_number,
            "weight_kg": profile.weight_kg,
            "allergies": allergies,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    @staticmethod
    def _serialize_vitals(vital: Vitals) -> dict:
        return {
            "id": vital.id,
            "bp_sys": vital.bp_sys,
            "bp_dia": vital.bp_dia,
            "hr": vital.hr,
            "rr": vital.rr,
            "temp_f": vital.temp_f,
            "spo2": vital.spo2,
            "glucose": vital.glucose,
            "recorded_at": vital.recorded_at.isoformat() if vital.recorded_at else None,
        }

    @staticmethod
    def _serialize_intervention(item: ClinicalIntervention) -> dict:
        return {
            "id": item.id,
            "category": item.category,
            "name": item.name,
            "indication": item.indication,
            "intent": item.intent,
            "expected_response": item.expected_response,
            "actual_response": item.actual_response,
            "protocol_family": item.protocol_family.value if item.protocol_family else None,
            "export_state": item.export_state.value if item.export_state else None,
            "snomed_code": item.snomed_code,
            "icd10_code": item.icd10_code,
            "rxnorm_code": item.rxnorm_code,
            "performed_at": item.performed_at.isoformat() if item.performed_at else None,
        }

    @staticmethod
    def _serialize_medication(med: MedicationAdministration) -> dict:
        return {
            "id": med.id,
            "medication_name": med.medication_name,
            "rxnorm_code": med.rxnorm_code,
            "dose_value": med.dose_value,
            "dose_unit": med.dose_unit,
            "route": med.route,
            "indication": med.indication,
            "response": med.response,
            "export_state": med.export_state.value if med.export_state else None,
            "administered_at": med.administered_at.isoformat() if med.administered_at else None,
        }

    @staticmethod
    def _serialize_signature(sig: EpcrSignatureArtifact) -> dict:
        return {
            "id": sig.id,
            "signature_method": sig.signature_method,
            "signature_class": sig.signature_class,
            "signer_identity": sig.signer_identity,
            "receiving_facility": sig.receiving_facility,
            "transfer_of_care_time": (
                sig.transfer_of_care_time.isoformat() if sig.transfer_of_care_time else None
            ),
            "ambulance_employee_exception": sig.ambulance_employee_exception,
            "compliance_decision": sig.compliance_decision,
            "created_at": sig.created_at.isoformat() if sig.created_at else None,
        }

    @staticmethod
    def _serialize_note(note: ClinicalNote) -> dict:
        return {
            "id": note.id,
            "raw_text": note.raw_text,
            "derived_summary": note.derived_summary,
            "source": note.source,
            "review_state": note.review_state.value if note.review_state else None,
            "captured_at": note.captured_at.isoformat() if note.captured_at else None,
        }

    @staticmethod
    def _serialize_address(addr: ChartAddress) -> dict:
        return {
            "id": addr.id,
            "raw_text": addr.raw_text,
            "street_line_one": addr.street_line_one,
            "street_line_two": addr.street_line_two,
            "city": addr.city,
            "state": addr.state,
            "postal_code": addr.postal_code,
            "county": addr.county,
            "latitude": addr.latitude,
            "longitude": addr.longitude,
            "validation_state": addr.validation_state.value if addr.validation_state else None,
        }

    @staticmethod
    def _serialize_assessment_finding(finding: AssessmentFinding) -> dict:
        return {
            "id": finding.id,
            "anatomy": finding.anatomy,
            "system": finding.system,
            "finding_type": finding.finding_type,
            "severity": finding.severity,
            "detection_method": finding.detection_method,
        }

    # ----------------------------------------------------------------- #
    # Aggregate workspace builder                                       #
    # ----------------------------------------------------------------- #

    @staticmethod
    async def _load_workspace(
        session: AsyncSession,
        tenant_id: str,
        chart_id: str,
        *,
        schematron_payload: dict[str, Any] | None = None,
    ) -> dict:
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if not chart:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )

        # Patient profile
        patient = await ChartService.get_patient_profile(session, tenant_id, chart_id)

        # Vitals
        vitals_rows = (
            await session.execute(
                select(Vitals).where(
                    and_(
                        Vitals.chart_id == chart_id,
                        Vitals.tenant_id == tenant_id,
                        Vitals.deleted_at.is_(None),
                    )
                )
            )
        ).scalars().all()

        # Procedures / interventions
        intervention_rows = (
            await session.execute(
                select(ClinicalIntervention).where(
                    and_(
                        ClinicalIntervention.chart_id == chart_id,
                        ClinicalIntervention.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()

        # Medications administered
        medication_rows = (
            await session.execute(
                select(MedicationAdministration).where(
                    and_(
                        MedicationAdministration.chart_id == chart_id,
                        MedicationAdministration.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()

        # Signatures
        signature_rows = (
            await session.execute(
                select(EpcrSignatureArtifact).where(
                    and_(
                        EpcrSignatureArtifact.chart_id == chart_id,
                        EpcrSignatureArtifact.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()

        # Narrative notes
        note_rows = (
            await session.execute(
                select(ClinicalNote).where(
                    and_(
                        ClinicalNote.chart_id == chart_id,
                        ClinicalNote.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()

        # Scene addresses
        address_rows = (
            await session.execute(
                select(ChartAddress).where(
                    and_(
                        ChartAddress.chart_id == chart_id,
                        ChartAddress.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()
        scene_addresses = [
            ChartWorkspaceService._serialize_address(a) for a in address_rows
        ]

        # Assessment findings (CPAE)
        finding_rows = (
            await session.execute(
                select(AssessmentFinding).where(
                    and_(
                        AssessmentFinding.chart_id == chart_id,
                        AssessmentFinding.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()

        # 3D Physical Assessment anatomical findings (region-level)
        anatomical_findings = await AnatomicalFindingService.list_for_chart(
            session, tenant_id, chart_id
        )

        # NEMSIS readiness via canonical compliance check
        try:
            readiness = await ChartService.check_nemsis_compliance(
                session, tenant_id, chart_id
            )
        except Exception as exc:
            logger.warning("Workspace readiness load failed: %s", exc)
            readiness = {
                "compliance_status": "unavailable",
                "compliance_percentage": 0,
                "missing_mandatory_fields": [],
                "is_fully_compliant": False,
                "error": str(exc),
            }

        # NEMSIS field mappings recorded so far
        mapping_rows = (
            await session.execute(
                select(NemsisMappingRecord).where(
                    and_(
                        NemsisMappingRecord.chart_id == chart_id,
                        NemsisMappingRecord.tenant_id == tenant_id,
                    )
                )
            )
        ).scalars().all()
        field_mappings = [
            {
                "nemsis_field": m.nemsis_field,
                "nemsis_value": m.nemsis_value,
                "source": m.source.value if m.source is not None else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in mapping_rows
        ]

        # Most recent export history row (truthful, may be empty)
        export_row = (
            await session.execute(
                select(NemsisExportHistory)
                .where(
                    and_(
                        NemsisExportHistory.chart_id == chart_id,
                        NemsisExportHistory.tenant_id == tenant_id,
                    )
                )
                .order_by(NemsisExportHistory.exported_at.desc())
            )
        ).scalars().first()
        export_status: dict[str, Any] = {
            "status": (export_row.export_status if export_row else "not_generated"),
            "last_export_id": export_row.id if export_row else None,
            "last_attempted_at": (
                export_row.exported_at.isoformat()
                if export_row and export_row.exported_at
                else None
            ),
        }

        # Recent audit trail (most recent 50 entries)
        audit_rows = (
            await session.execute(
                select(EpcrAuditLog)
                .where(
                    and_(
                        EpcrAuditLog.chart_id == chart_id,
                        EpcrAuditLog.tenant_id == tenant_id,
                    )
                )
                .order_by(EpcrAuditLog.performed_at.desc())
                .limit(50)
            )
        ).scalars().all()
        audit = [
            {
                "id": a.id,
                "action": a.action,
                "user_id": a.user_id,
                "detail_json": a.detail_json,
                "performed_at": a.performed_at.isoformat() if a.performed_at else None,
            }
            for a in audit_rows
        ]

        unmapped_fields = [
            {"section": s, "reason": "field_not_mapped"} for s in sorted(UNMAPPED_SECTIONS)
        ]

        # ----------------------------------------------------------------- #
        # Pillar payload injections. Each is wrapped in try/except so a     #
        # transient pillar failure surfaces as an empty/null block rather   #
        # than collapsing the entire workspace payload. Honest fallback —   #
        # NEVER fabricate success.                                          #
        # ----------------------------------------------------------------- #

        # lock_readiness aggregator
        try:
            lock_readiness = await LockReadinessService.get_for_chart(
                session,
                tenant_id,
                chart_id,
                unmapped_sections=tuple(sorted(UNMAPPED_SECTIONS)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("lock_readiness load failed: %s", exc)
            lock_readiness = None

        # ecustom definitions + values
        try:
            agency_scope = chart.agency_code or ""
            ecustom_defs = await ECustomFieldService.list_definitions(
                session, tenant_id, agency_scope
            )
            ecustom_values = await ECustomFieldService.list_values_for_chart(
                session, tenant_id, chart_id
            )
            ecustom_payload = {
                "definitions": [
                    ECustomFieldService.serialize_definition(d) for d in ecustom_defs
                ],
                "values": [
                    ECustomFieldService.serialize_value(v) for v in ecustom_values
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("ecustom load failed: %s", exc)
            ecustom_payload = {"definitions": [], "values": []}

        # sentence evidence
        try:
            sentence_evidence_rows = await SentenceEvidenceService.list_for_chart(
                session, tenant_id, chart_id
            )
            sentence_evidence_payload = [
                {
                    "id": r.id,
                    "tenantId": r.tenant_id,
                    "chartId": r.chart_id,
                    "narrativeId": r.narrative_id,
                    "sentenceIndex": r.sentence_index,
                    "sentenceText": r.sentence_text,
                    "evidenceKind": r.evidence_kind,
                    "evidenceRefId": r.evidence_ref_id,
                    "confidence": float(r.confidence) if r.confidence is not None else 0.0,
                    "providerConfirmed": bool(r.provider_confirmed),
                    "createdAt": r.created_at.isoformat() if r.created_at else None,
                    "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in sentence_evidence_rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("sentence_evidence load failed: %s", exc)
            sentence_evidence_payload = []

        # repeat patient — read existing match rows only (no re-discovery
        # at workspace-load time; discovery is an explicit endpoint).
        try:
            from sqlalchemy import select as _select
            from epcr_app.models import (
                EpcrRepeatPatientMatch,
            )
            match_rows = (
                await session.execute(
                    _select(EpcrRepeatPatientMatch).where(
                        and_(
                            EpcrRepeatPatientMatch.chart_id == chart_id,
                            EpcrRepeatPatientMatch.tenant_id == tenant_id,
                        )
                    ).order_by(EpcrRepeatPatientMatch.confidence.desc())
                )
            ).scalars().all()
            prior_chart_rows: list = []
            seen_profiles: set[str] = set()
            for m in match_rows:
                if m.matched_profile_id in seen_profiles:
                    continue
                seen_profiles.add(m.matched_profile_id)
                prior_chart_rows.extend(
                    await RepeatPatientService.list_prior_charts(
                        session, tenant_id, m.matched_profile_id
                    )
                )
            repeat_patient_payload = {
                "matches": [
                    {
                        "id": m.id,
                        "matchedProfileId": m.matched_profile_id,
                        "confidence": float(m.confidence) if m.confidence is not None else 0.0,
                        "matchReasons": json.loads(m.match_reason_json) if m.match_reason_json else [],
                        "reviewed": bool(m.reviewed),
                        "reviewedBy": m.reviewed_by,
                        "reviewedAt": m.reviewed_at.isoformat() if m.reviewed_at else None,
                        "carryForwardAllowed": bool(m.carry_forward_allowed),
                        "createdAt": m.created_at.isoformat() if m.created_at else None,
                        "updatedAt": m.updated_at.isoformat() if m.updated_at else None,
                    }
                    for m in match_rows
                ],
                "priorCharts": [
                    {
                        "id": r.id,
                        "priorChartId": r.prior_chart_id,
                        "encounterAt": r.encounter_at.isoformat() if r.encounter_at else None,
                        "chiefComplaint": r.chief_complaint,
                        "disposition": r.disposition,
                    }
                    for r in prior_chart_rows
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("repeat_patient load failed: %s", exc)
            repeat_patient_payload = {"matches": [], "priorCharts": []}

        # prior ECG references (+ best-effort comparison list)
        try:
            from epcr_app.models import EpcrEcgComparisonResult as _EcgCmp
            prior_ecg_rows = await prior_ecg_list_for_chart(
                session, tenant_id, chart_id
            )
            prior_ecg_refs = [
                {
                    "id": r.id,
                    "capturedAt": r.captured_at.isoformat() if r.captured_at else None,
                    "encounterContext": r.encounter_context,
                    "imageStorageUri": r.image_storage_uri,
                    "monitorImported": bool(r.monitor_imported),
                    "quality": r.quality,
                    "notes": r.notes,
                }
                for r in prior_ecg_rows
            ]
            cmp_rows = (
                await session.execute(
                    select(_EcgCmp).where(
                        and_(
                            _EcgCmp.chart_id == chart_id,
                            _EcgCmp.tenant_id == tenant_id,
                        )
                    )
                )
            ).scalars().all()
            prior_ecg_payload = {
                "references": prior_ecg_refs,
                "comparisons": [
                    {
                        "id": c.id,
                        "priorEcgId": c.prior_ecg_id,
                        "comparisonState": c.comparison_state,
                        "providerConfirmed": bool(c.provider_confirmed),
                        "providerId": c.provider_id,
                        "confirmedAt": c.confirmed_at.isoformat() if c.confirmed_at else None,
                        "notes": c.notes,
                    }
                    for c in cmp_rows
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("prior_ecg load failed: %s", exc)
            prior_ecg_payload = {"references": [], "comparisons": []}

        # rxnorm matches
        try:
            rxnorm_matches = await RxNormService.list_for_chart(
                session, tenant_id=tenant_id, chart_id=chart_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("rxnorm load failed: %s", exc)
            rxnorm_matches = []

        # ICD-10 documentation prompts
        try:
            icd10_rows = await icd10_list_for_chart(session, tenant_id, chart_id)
            icd10_suggestions_payload = [icd10_serialize(r) for r in icd10_rows]
            icd10_score = icd10_specificity_score(icd10_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("icd10 load failed: %s", exc)
            icd10_suggestions_payload = []
            icd10_score = 0.0

        # map locations
        try:
            map_locations = await MapLocationService.list_for_chart(
                session, tenant_id=tenant_id, chart_id=chart_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("map_location load failed: %s", exc)
            map_locations = []

        # multi-patient context
        try:
            multi_patient_payload = await MultiPatientService.list_for_chart(
                session, tenant_id, chart_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("multi_patient load failed: %s", exc)
            multi_patient_payload = {"incident": None, "self": None, "siblings": []}

        # protocol context (active row, if any)
        try:
            active_protocol = await ProtocolContextService.list_active(
                session, tenant_id, chart_id
            )
            if active_protocol is not None:
                try:
                    sat = json.loads(active_protocol.required_field_satisfaction_json) \
                        if active_protocol.required_field_satisfaction_json else None
                except (TypeError, ValueError):
                    sat = None
                protocol_context_payload = {
                    "id": active_protocol.id,
                    "tenantId": active_protocol.tenant_id,
                    "chartId": active_protocol.chart_id,
                    "activePack": active_protocol.active_pack,
                    "engagedAt": active_protocol.engaged_at.isoformat()
                    if active_protocol.engaged_at else None,
                    "engagedBy": active_protocol.engaged_by,
                    "disengagedAt": active_protocol.disengaged_at.isoformat()
                    if active_protocol.disengaged_at else None,
                    "packVersion": active_protocol.pack_version,
                    "requiredFieldSatisfaction": sat,
                }
            else:
                protocol_context_payload = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("protocol_context load failed: %s", exc)
            protocol_context_payload = None

        # audit trail (additive — preserves existing `audit` key untouched).
        try:
            audit_trail = await AuditTrailQueryService.list_for_chart(
                session, tenant_id=tenant_id, chart_id=chart_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("audit_trail load failed: %s", exc)
            audit_trail = []

        # ----------------------------------------------------------------- #
        # Capability envelope (Five-Artifact Rule).                         #
        # A capability may only declare ``live`` if the service, model,     #
        # endpoint, contract test, and audit path all exist on this SHA.   #
        # Anything missing → ``unavailable`` + explicit reason. No fake     #
        # completion. Read by EpcrUnavailableState on web + android.        #
        # ----------------------------------------------------------------- #
        # Environment-gated capabilities (Mapbox + RxNav).
        _mapbox_token = (_os.environ.get("MAPBOX_TOKEN") or "").strip()
        _rxnav_url = (_os.environ.get("RXNAV_URL") or "").strip()

        if _rxnav_url:
            _rxnorm_cap: dict[str, Any] = {
                "capability": "live",
                "source": "rxnorm_service",
            }
        else:
            _rxnorm_cap = {
                "capability": "read_only_cache",
                "reason": "RXNAV_URL not configured",
            }
        if _mapbox_token:
            _map_location_cap: dict[str, Any] = {
                "capability": "live",
                "source": "map_location_service",
            }
        else:
            _map_location_cap = {
                "capability": "read_only",
                "reason": "MAPBOX_TOKEN not configured",
            }

        capabilities: dict[str, dict[str, Any]] = {
            "readiness": {
                "capability": "live",
                "source": "nemsis_finalization_gate",
            },
            # Additive aggregator for the lock-readiness pillar. Does NOT
            # replace `readiness`; both are surfaced so existing consumers
            # of `nemsis_readiness` keep their contract while new consumers
            # can read the score/blockers/warnings/advisories envelope.
            "lock_readiness": {
                "capability": "live",
                "source": "lock_readiness_service",
            },
            "timeline": {
                "capability": "live",
                "source": "chart_workspace_aggregate",
            },
            "protocol_context": {
                "capability": "live",
                "source": "protocol_context_service",
            },
            "smart_text": {
                "capability": "live",
                "source": "smart_text_service",
            },
            "sentence_evidence": {
                "capability": "live",
                "source": "sentence_evidence_service",
            },
            "repeat_patient": {
                "capability": "live",
                "source": "repeat_patient_service",
            },
            "prior_ecg": {
                "capability": "live",
                "source": "prior_ecg_service",
            },
            "rxnorm": _rxnorm_cap,
            "icd10": {
                "capability": "live",
                "source": "icd10_service",
            },
            "map_location": _map_location_cap,
            "multi_patient": {
                "capability": "live",
                "source": "multi_patient_service",
            },
            "audit_trail": {
                "capability": "live",
                "source": "audit_trail_query_service",
            },
            "ecustom": {
                "capability": "live",
                "source": "ecustom_field_service",
            },
            "assessment_anatomical": {
                "capability": "live",
                "source": "anatomical_finding_service",
            },
        }

        # Submission CTA truth: the submission router exists but live CTA
        # endpoints require credentials and integration enablement. Until a
        # submission row exists for this chart we honestly report
        # ``submission_unavailable`` rather than fabricating staged status.
        submission_status: dict[str, Any] = {
            "status": "submission_unavailable",
            "reason": "CTA submission endpoint not configured for this chart",
            "last_submission_id": None,
        }

        # Schematron status: only known when finalize is exercised. Present
        # as ``unknown`` here so the UI does not infer a passing verdict.
        schematron: dict[str, Any] = schematron_payload or {
            "status": "unknown",
            "evaluated_at": None,
        }

        return {
            "chart": ChartWorkspaceService._serialize_chart(chart),
            "chart_id": chart.id,
            "tenant_id": chart.tenant_id,
            "status": chart.status.value if chart.status else None,
            "call_number": chart.call_number,
            "agency_code": chart.agency_code,
            "incident_number": chart.incident_number,
            "response_number": chart.response_number,
            "pcr_number": chart.pcr_number,
            "billing_case_number": chart.billing_case_number,
            "cad_incident_number": chart.cad_incident_number,
            "incident_datetime": chart.created_at.isoformat() if chart.created_at else None,
            "created_at": chart.created_at.isoformat() if chart.created_at else None,
            "updated_at": chart.updated_at.isoformat() if chart.updated_at else None,
            "finalized_at": chart.finalized_at.isoformat() if chart.finalized_at else None,
            "patient": ChartWorkspaceService._serialize_patient(patient),
            "incident": {
                "incident_type": chart.incident_type,
                "call_number": chart.call_number,
                "agency_code": chart.agency_code,
                "incident_number": chart.incident_number,
                "response_number": chart.response_number,
                "pcr_number": chart.pcr_number,
                "billing_case_number": chart.billing_case_number,
                "cad_incident_number": chart.cad_incident_number,
            },
            "response": {"status": "field_not_mapped"},
            "crew": {"status": "field_not_mapped"},
            "scene": {
                "addresses": scene_addresses,
            },
            "complaint": {
                "status": "delegated_to_assessment",
            },
            "history": {"status": "field_not_mapped"},
            "allergies": {
                "status": "delegated_to_patient_profile",
                "allergies": (
                    ChartWorkspaceService._serialize_patient(patient) or {}
                ).get("allergies", [])
                if patient is not None
                else [],
            },
            "home_medications": {"status": "field_not_mapped"},
            "assessment": {
                "findings": [
                    ChartWorkspaceService._serialize_assessment_finding(f)
                    for f in finding_rows
                ],
                "anatomical_findings": anatomical_findings,
            },
            "vitals": [
                ChartWorkspaceService._serialize_vitals(v) for v in vitals_rows
            ],
            "procedures": [
                ChartWorkspaceService._serialize_intervention(i)
                for i in intervention_rows
            ],
            "medications_administered": [
                ChartWorkspaceService._serialize_medication(m) for m in medication_rows
            ],
            "narrative": [
                ChartWorkspaceService._serialize_note(n) for n in note_rows
            ],
            "disposition": {"status": "field_not_mapped"},
            "destination": {"status": "field_not_mapped"},
            "signatures": [
                ChartWorkspaceService._serialize_signature(s) for s in signature_rows
            ],
            "attachments": {"status": "field_not_mapped"},
            "nemsis_readiness": readiness,
            "schematron": schematron,
            "export_status": export_status,
            "submission_status": submission_status,
            "field_mappings": field_mappings,
            "unmapped_fields": unmapped_fields,
            "registry": {"source": "/api/v1/epcr/nemsis-registry"},
            "defined_lists": {"source": "/api/v1/epcr/nemsis/defined-lists"},
            "custom_elements": {"source": "/api/v1/epcr/nemsis/custom-elements"},
            "audit": audit,
            "audit_trail": audit_trail,
            "lock_readiness": lock_readiness,
            "ecustom": ecustom_payload,
            "sentence_evidence": sentence_evidence_payload,
            "repeat_patient": repeat_patient_payload,
            "prior_ecg": prior_ecg_payload,
            "rxnorm_matches": rxnorm_matches,
            "icd10Suggestions": icd10_suggestions_payload,
            "icd10SpecificityScore": icd10_score,
            "map_locations": map_locations,
            "multi_patient": multi_patient_payload,
            "protocol_context": protocol_context_payload,
            "capabilities": capabilities,
        }

    # ----------------------------------------------------------------- #
    # Public orchestration API (matches router contract)                #
    # ----------------------------------------------------------------- #

    @staticmethod
    async def create_workspace_chart(
        session: AsyncSession, current_user: CurrentUser, payload: dict
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        user_id = ChartWorkspaceService._user(current_user)
        call_number = (payload.get("call_number") or "").strip()
        incident_type = (payload.get("incident_type") or "").strip()
        if not incident_type:
            raise ChartWorkspaceError(
                "incident_type is required",
                status_code=400,
                detail={
                    "message": "incident_type is required",
                    "missing_fields": [
                        f for f, v in (("incident_type", incident_type),) if not v
                    ],
                },
            )
        try:
            chart = await ChartService.create_chart(
                session=session,
                tenant_id=tenant_id,
                call_number=call_number or None,
                incident_type=incident_type,
                created_by_user_id=user_id,
                client_reference_id=payload.get("client_reference_id"),
                patient_id=payload.get("patient_id"),
                agency_id=payload.get("agency_id"),
                agency_code=payload.get("agency_code"),
                incident_datetime=ChartService._parse_optional_datetime(payload.get("incident_datetime")),
                cad_incident_number=payload.get("cad_incident_number"),
            )
        except ValueError as exc:
            if str(exc) == "chart_call_number_conflict":
                raise ChartWorkspaceError(
                    "Chart call_number already exists for this tenant",
                    status_code=409,
                    detail={
                        "message": "Chart call_number already exists for this tenant",
                        "code": "chart_call_number_conflict",
                        "call_number": call_number,
                    },
                ) from exc
            raise ChartWorkspaceError(str(exc), status_code=400) from exc
        return await ChartWorkspaceService._load_workspace(session, tenant_id, chart.id)

    @staticmethod
    async def get_workspace(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        return await ChartWorkspaceService._load_workspace(session, tenant_id, chart_id)

    @staticmethod
    async def update_workspace_section(
        session: AsyncSession,
        current_user: CurrentUser,
        chart_id: str,
        section: str,
        payload: dict,
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        user_id = ChartWorkspaceService._user(current_user)

        if section not in ALL_SECTIONS:
            raise ChartWorkspaceError(
                f"Unknown workspace section '{section}'",
                status_code=400,
                detail={"message": f"Unknown workspace section '{section}'", "section": section},
            )
        if section in UNMAPPED_SECTIONS:
            raise ChartWorkspaceError(
                f"Section '{section}' is not yet mapped to a backend owner",
                status_code=422,
                detail={
                    "message": f"Section '{section}' is not yet mapped to a backend owner",
                    "section": section,
                    "field_not_mapped": [section],
                },
            )

        # Confirm chart exists for tenant before any write
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )

        try:
            if section == "patient":
                await ChartService.upsert_patient_profile(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, profile_data=payload,
                )
            elif section == "incident":
                # Limited safe fields routed through update_chart
                allowed = {k: payload[k] for k in ("incident_type", "patient_id") if k in payload}
                if allowed:
                    await ChartService.update_chart(
                        session=session, tenant_id=tenant_id, chart_id=chart_id,
                        update_data=allowed,
                    )
            elif section == "scene":
                await ChartService.upsert_chart_address(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, address_data=payload,
                )
            elif section in ("assessment", "complaint"):
                if section == "assessment" and "anatomical_findings" in payload:
                    try:
                        await AnatomicalFindingService.replace_for_chart(
                            session=session,
                            tenant_id=tenant_id,
                            chart_id=chart_id,
                            user_id=user_id,
                            findings=payload.get("anatomical_findings") or [],
                        )
                        await session.commit()
                    except AnatomicalFindingValidationError as vexc:
                        await session.rollback()
                        raise ChartWorkspaceError(
                            "Invalid anatomical findings payload",
                            status_code=400,
                            detail={
                                "message": "Invalid anatomical findings payload",
                                "errors": vexc.errors,
                            },
                        ) from vexc
                elif payload.get("finding"):
                    await ChartService.record_assessment_finding(
                        session=session, tenant_id=tenant_id, chart_id=chart_id,
                        provider_id=user_id, finding_data=payload["finding"],
                    )
                else:
                    await ChartService.upsert_clinical_impression(
                        session=session, tenant_id=tenant_id, chart_id=chart_id,
                        provider_id=user_id, impression_data=payload,
                    )
            elif section == "vitals":
                await ChartService.record_vital_set(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, vitals_data=payload,
                )
            elif section in ("treatment", "procedures"):
                await ChartService.record_intervention(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, intervention_data=payload,
                )
            elif section == "medications_administered":
                await ChartService.record_medication_administration(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, medication_data=payload,
                )
            elif section == "narrative":
                await ChartService.record_clinical_note(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    provider_id=user_id, note_data=payload,
                )
            elif section == "signatures":
                await ChartService.create_signature_artifact(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    created_by_user_id=user_id, payload=payload,
                )
            elif section == "nemsis":
                if not payload.get("nemsis_field"):
                    raise ValueError("nemsis_field is required for nemsis section updates")
                await ChartService.record_nemsis_field(
                    session=session, tenant_id=tenant_id, chart_id=chart_id,
                    nemsis_field=payload["nemsis_field"],
                    nemsis_value=payload.get("nemsis_value"),
                    source=payload.get("source", "manual"),
                )
                if "ecustom_values" in payload:
                    try:
                        await ECustomFieldService.replace_for_chart(
                            session,
                            tenant_id=tenant_id,
                            chart_id=chart_id,
                            user_id=user_id,
                            agency_id=chart.agency_code or "",
                            values=payload["ecustom_values"],
                        )
                    except Exception as _ecustom_exc:  # noqa: BLE001
                        raise ChartWorkspaceError(
                            "ecustom_values validation failed",
                            status_code=400,
                            detail={"message": str(_ecustom_exc)},
                        ) from _ecustom_exc
        except ValueError as exc:
            raise ChartWorkspaceError(str(exc), status_code=400) from exc

        return await ChartWorkspaceService._load_workspace(session, tenant_id, chart_id)

    @staticmethod
    async def update_workspace_field(
        session: AsyncSession,
        current_user: CurrentUser,
        chart_id: str,
        section: str,
        field_key: str,
        value: Any,
    ) -> dict:
        # Field-level updates are routed through section-level update with
        # a single-field payload so the same validation applies. NEMSIS
        # field updates carry both ``nemsis_field`` and ``nemsis_value``.
        if section == "nemsis":
            payload = {"nemsis_field": field_key, "nemsis_value": value, "source": "manual"}
        else:
            payload = {field_key: value}
        return await ChartWorkspaceService.update_workspace_section(
            session, current_user, chart_id, section, payload
        )

    @staticmethod
    async def get_workspace_readiness(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )
        readiness = await ChartService.check_nemsis_compliance(
            session, tenant_id, chart_id
        )
        return {
            "chart_id": chart_id,
            "readiness": readiness,
            "schematron": {"status": "unknown", "evaluated_at": None},
        }

    @staticmethod
    async def validate_workspace(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        # Validation today is the canonical NEMSIS mandatory-field
        # compliance check. Schematron evaluation only runs at finalize
        # because it requires building the chart XML, which is an
        # expensive operation. The validate path honestly reports the
        # current readiness without claiming schematron has been
        # exercised.
        return await ChartWorkspaceService.get_workspace_readiness(
            session, current_user, chart_id
        )

    @staticmethod
    async def finalize_workspace(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        user_id = ChartWorkspaceService._user(current_user)
        try:
            result = await ChartFinalizationService.finalize_chart(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                chart_id=chart_id,
            )
        except ChartFinalizationError as exc:
            raise ChartWorkspaceError(
                str(exc),
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc
        return await ChartWorkspaceService._load_workspace(
            session,
            tenant_id,
            chart_id,
            schematron_payload=result.schematron.to_payload(),
        )

    @staticmethod
    async def export_workspace(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )
        # The canonical export router lives at /api/v1/epcr/nemsis. The
        # workspace export endpoint surfaces the most-recent export row
        # truthfully and points the caller at the canonical generator.
        # We do not fabricate a successful export here.
        export_row = (
            await session.execute(
                select(NemsisExportHistory)
                .where(
                    and_(
                        NemsisExportHistory.chart_id == chart_id,
                        NemsisExportHistory.tenant_id == tenant_id,
                    )
                )
                .order_by(NemsisExportHistory.exported_at.desc())
            )
        ).scalars().first()
        if export_row is None:
            return {
                "status": "export_not_generated",
                "reason": "Use POST /api/v1/epcr/nemsis/export-generate to produce an artifact",
                "last_export_id": None,
            }
        return {
            "status": export_row.export_status,
            "last_export_id": export_row.id,
            "last_attempted_at": (
                export_row.exported_at.isoformat() if export_row.exported_at else None
            ),
        }

    @staticmethod
    async def submit_workspace(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )
        # Submission requires a configured CTA endpoint and credentials.
        # The workspace endpoint does not fabricate a submission and
        # instead reports the honest ``submission_unavailable`` status.
        return {
            "status": "submission_unavailable",
            "reason": "CTA submission endpoint not configured for this workspace",
            "last_submission_id": None,
        }

    @staticmethod
    async def get_workspace_status(
        session: AsyncSession, current_user: CurrentUser, chart_id: str
    ) -> dict:
        tenant_id = ChartWorkspaceService._tenant(current_user)
        chart = await ChartService.get_chart(session, tenant_id, chart_id)
        if chart is None:
            raise ChartWorkspaceError(
                f"Chart {chart_id} not found", status_code=404,
                detail={"message": f"Chart {chart_id} not found"},
            )
        readiness = await ChartService.check_nemsis_compliance(
            session, tenant_id, chart_id
        )
        return {
            "chart_id": chart.id,
            "status": chart.status.value if chart.status else None,
            "readiness": readiness,
            "schematron": {"status": "unknown"},
            "export_status": (await ChartWorkspaceService.export_workspace(session, current_user, chart_id))["status"],
            "submission_status": "submission_unavailable",
        }
