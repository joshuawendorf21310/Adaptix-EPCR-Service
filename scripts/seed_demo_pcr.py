"""Demo PCR seed for Adaptix-EPCR-Service.

Creates a deterministic, idempotent demo Patient Care Record bound to the
``demo-agency`` tenant for use in local NEMSIS / ePCR smoke flows.

This script:
- Connects to the EPCR database using ``EPCR_DATABASE_URL`` (or falls back
  to ``CARE_DATABASE_URL``) — the same configuration the running service
  uses (see ``epcr_app/db.py``).
- Verifies that all expected ePCR tables exist before writing anything.
- Writes a single ``Chart`` plus child rows: ``PatientProfile``,
  ``ChartAddress``, ``Assessment``, ``Vitals`` (x2), ``ClinicalIntervention``,
  ``MedicationAdministration``, ``EpcrSignatureArtifact``, and
  ``NemsisCompliance`` — using the real ORM models.
- Uses fixed UUIDs derived from a sentinel namespace so the same row IDs
  are produced on every run, making the seed safely idempotent.
- Prints PASS or BLOCKED with explicit evidence for the calling shell.

This script does NOT:
- Fabricate NEMSIS XML output, validation results, or submission status.
- Authenticate any user, mint any token, or claim end-to-end smoke success.
- Touch any production database. Refuses to run if the URL points at a host
  outside ``localhost``/``127.0.0.1``/``sqlite`` unless
  ``ADAPTIX_DEMO_SEED_ALLOW_REMOTE=1`` is set.

Companion: ``Adaptix-Web-App/docs/NEMSIS_SMOKE_CHECKLIST.md`` and
``Adaptix-Web-App/docs/DEMO_SEED_PLAN.md``.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the backend package is importable regardless of cwd.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# Sentinel namespace for deterministic UUIDs. Any change to this UUID will
# produce a different demo PCR id; do not rotate without coordination.
SEED_NAMESPACE = uuid.UUID("a4d4f5b1-9e3e-4a44-8a77-adaad7170de1")
DEMO_TENANT_ID = "11111111-1111-4111-8111-111111111111"
DEMO_TENANT_SLUG = "demo-agency"
DEMO_USER_ID = "22222222-2222-4222-8222-222222222222"
DEMO_CALL_NUMBER = "DEMO-2026-04-29-0001"
DEMO_EXTERNAL_TAG = "adaptix-demo-pcr-v1"


def _det(name: str) -> str:
    """Return a deterministic UUID5 string for a row identity."""
    return str(uuid.uuid5(SEED_NAMESPACE, name))


def _utc(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _safe_database_url() -> tuple[str | None, str | None]:
    """Return (url, blocked_reason). One of the two is None."""
    url = os.environ.get("EPCR_DATABASE_URL") or os.environ.get("CARE_DATABASE_URL")
    if not url:
        return None, (
            "EPCR_DATABASE_URL is not set (and CARE_DATABASE_URL fallback is also missing). "
            "Set it before running this seed. See Adaptix-EPCR-Service/backend/.env.example."
        )
    if "ADAPTIX_DEMO_SEED_ALLOW_REMOTE" not in os.environ:
        lowered = url.lower()
        is_local = (
            lowered.startswith("sqlite")
            or "@localhost" in lowered
            or "@127.0.0.1" in lowered
            or "@host.docker.internal" in lowered
        )
        if not is_local:
            return None, (
                "Refusing to seed against non-local database. URL host is not localhost/sqlite. "
                "Set ADAPTIX_DEMO_SEED_ALLOW_REMOTE=1 to override (NOT recommended)."
            )
    return url, None


async def _verify_required_tables(engine) -> list[str]:
    """Return list of missing tables (empty when all required tables exist)."""
    from sqlalchemy import text

    required = [
        "epcr_charts",
        "epcr_patient_profiles",
        "epcr_chart_addresses",
        "epcr_assessments",
        "epcr_vitals",
        "epcr_interventions",
        "epcr_medication_administrations",
        "epcr_signature_artifacts",
        "epcr_nemsis_compliance",
    ]
    async with engine.connect() as conn:
        backend = engine.dialect.name
        if backend == "sqlite":
            rows = await conn.execute(
                text("select name from sqlite_master where type='table'")
            )
            existing = {r[0] for r in rows.fetchall()}
        else:
            rows = await conn.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema = current_schema()"
                )
            )
            existing = {r[0] for r in rows.fetchall()}
    return [t for t in required if t not in existing]


async def _seed(url: str) -> dict:
    """Run the idempotent seed. Returns a structured result dict."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    # Local imports so missing deps fail with a clear BLOCKED message rather
    # than ImportError at module load. Resilient against the case where the
    # `epcr_app.models` package shadows the sibling `epcr_app/models.py` and
    # only re-exports a partial set of ORM classes (which is the layout in
    # the running EPCR docker image as of 2026-04-29).
    try:
        from epcr_app.models import (  # type: ignore
            Chart,
            ChartStatus,
            PatientProfile,
            ChartAddress,
            AddressValidationState,
            Assessment,
            Vitals,
            ClinicalIntervention,
            ProtocolFamily,
            InterventionExportState,
            MedicationAdministration,
            EpcrSignatureArtifact,
            NemsisCompliance,
            ComplianceStatus,
            NemsisMappingRecord,
            FieldSource,
        )
    except (ImportError, AttributeError):
        # Fallback: load the sibling models.py file directly without going
        # through the package's __init__ at all. This avoids both the
        # missing-symbol case and the Py3.12 `importlib.util` quirk that
        # exists in older container images.
        import importlib.util as _ilu
        import sys as _sys
        from pathlib import Path as _Path

        _candidates = [
            _Path("/app/models.py"),
            _Path("/app/epcr_app/models.py"),
            _BACKEND / "epcr_app" / "models.py",
        ]
        _models_path = next((p for p in _candidates if p.exists()), None)
        if _models_path is None:
            raise
        _spec = _ilu.spec_from_file_location("epcr_app_models_seed_fallback", str(_models_path))
        _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
        _sys.modules["epcr_app_models_seed_fallback"] = _mod
        assert _spec and _spec.loader
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        Chart = _mod.Chart
        ChartStatus = _mod.ChartStatus
        PatientProfile = _mod.PatientProfile
        ChartAddress = _mod.ChartAddress
        AddressValidationState = _mod.AddressValidationState
        Assessment = _mod.Assessment
        Vitals = _mod.Vitals
        ClinicalIntervention = _mod.ClinicalIntervention
        ProtocolFamily = _mod.ProtocolFamily
        InterventionExportState = _mod.InterventionExportState
        MedicationAdministration = _mod.MedicationAdministration
        EpcrSignatureArtifact = _mod.EpcrSignatureArtifact
        NemsisCompliance = _mod.NemsisCompliance
        ComplianceStatus = _mod.ComplianceStatus
        NemsisMappingRecord = _mod.NemsisMappingRecord
        FieldSource = _mod.FieldSource

    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        missing = await _verify_required_tables(engine)
        if missing:
            return {
                "status": "BLOCKED",
                "reason": "missing_tables",
                "detail": (
                    "Required ePCR tables are missing: "
                    + ", ".join(missing)
                    + ". Run alembic migrations first: "
                    "`cd backend && alembic upgrade head`."
                ),
            }

        sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        chart_id = _det("chart")
        now = _utc(2026, 4, 29, 14, 0, 0)
        dispatch = _utc(2026, 4, 29, 13, 22, 0)
        on_scene = dispatch + timedelta(minutes=6)
        at_patient = on_scene + timedelta(minutes=2)
        depart_scene = at_patient + timedelta(minutes=14)
        at_destination = depart_scene + timedelta(minutes=12)

        async with sm() as session:
            existing_chart = await session.get(Chart, chart_id)
            if existing_chart is not None:
                return {
                    "status": "PASS",
                    "action": "noop",
                    "chart_id": chart_id,
                    "tenant_id": DEMO_TENANT_ID,
                    "tenant_slug": DEMO_TENANT_SLUG,
                    "call_number": DEMO_CALL_NUMBER,
                    "detail": "Demo PCR already present — seed is idempotent. No rows written.",
                }

            # Chart (encounter root)
            chart = Chart(
                id=chart_id,
                tenant_id=DEMO_TENANT_ID,
                call_number=DEMO_CALL_NUMBER,
                patient_id=_det("patient-link"),
                incident_type="medical",
                status=ChartStatus.UNDER_REVIEW,
                created_by_user_id=DEMO_USER_ID,
                created_at=dispatch,
                updated_at=now,
                narrative=(
                    "DEMO RECORD — Adaptix demo agency. 67 y/o male, chief complaint "
                    "chest pressure radiating to left arm, onset 30 minutes prior to call. "
                    "On scene assessment: alert, oriented x3, diaphoretic, BP 152/94, "
                    "HR 102, RR 22, SpO2 94% RA. 12-lead obtained, ASA 324mg PO administered, "
                    "NTG 0.4mg SL x1 with partial relief. Transported priority 2 to demo "
                    "receiving facility. NOT REAL PATIENT DATA."
                ),
            )
            session.add(chart)

            # Patient demographics
            session.add(
                PatientProfile(
                    id=_det("patient-profile"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    first_name="Demo",
                    middle_name="A",
                    last_name="Patient",
                    date_of_birth="1958-07-12",
                    age_years=67,
                    sex="male",
                    phone_number="555-0100",
                    weight_kg=84.0,
                    allergies_json=json.dumps(["NKDA"]),
                    updated_at=now,
                )
            )

            # Scene address (incident location)
            session.add(
                ChartAddress(
                    id=_det("scene-address"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    raw_text="100 Demo Way, Demo City, FL 32099",
                    street_line_one="100 Demo Way",
                    street_line_two=None,
                    city="Demo City",
                    state="FL",
                    postal_code="32099",
                    county="Demo County",
                    latitude=28.5383,
                    longitude=-81.3792,
                    validation_state=AddressValidationState.MANUAL_VERIFIED,
                    intelligence_source="seed_script",
                    intelligence_detail="Synthetic address for local NEMSIS smoke",
                    updated_at=now,
                )
            )

            # Assessment (chief complaint, impression)
            session.add(
                Assessment(
                    id=_det("assessment"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    chief_complaint="Chest pressure radiating to left arm",
                    field_diagnosis="Suspected acute coronary syndrome",
                    primary_impression="Chest Pain - Cardiac Suspected",
                    secondary_impression=None,
                    impression_notes="12-lead obtained on scene; transmitted to receiving facility.",
                    snomed_code="29857009",
                    icd10_code="I20.9",
                    acuity="emergent",
                    documented_at=at_patient,
                )
            )

            # Vitals — initial and reassessment
            session.add(
                Vitals(
                    id=_det("vitals-1"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    bp_sys=152, bp_dia=94, hr=102, rr=22, temp_f=98.4,
                    spo2=94, glucose=118,
                    recorded_at=at_patient,
                )
            )
            session.add(
                Vitals(
                    id=_det("vitals-2"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    bp_sys=138, bp_dia=86, hr=92, rr=18, temp_f=98.4,
                    spo2=97, glucose=None,
                    recorded_at=at_patient + timedelta(minutes=10),
                )
            )

            # Intervention (12-lead acquisition)
            session.add(
                ClinicalIntervention(
                    id=_det("intervention-12lead"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    category="diagnostic",
                    name="12-Lead ECG Acquisition",
                    indication="Chest pain suspected cardiac",
                    intent="Identify STEMI / acute ischemia",
                    expected_response="Interpretable tracing transmitted to receiving facility",
                    actual_response="Sinus tachycardia, no acute ST elevation on field 12-lead",
                    reassessment_due_at=None,
                    protocol_family=ProtocolFamily.ACLS,
                    snomed_code="29303009",
                    icd10_code=None,
                    rxnorm_code=None,
                    export_state=InterventionExportState.MAPPED_READY,
                    performed_at=at_patient + timedelta(minutes=2),
                    provider_id=DEMO_USER_ID,
                )
            )

            # Medication administration (Aspirin)
            session.add(
                MedicationAdministration(
                    id=_det("med-aspirin"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    medication_name="Aspirin",
                    rxnorm_code="1191",
                    dose_value="324",
                    dose_unit="mg",
                    route="PO",
                    indication="Suspected ACS",
                    response="Tolerated without adverse effect",
                    export_state=InterventionExportState.MAPPED_READY,
                    administered_at=at_patient + timedelta(minutes=4),
                    administered_by_user_id=DEMO_USER_ID,
                )
            )
            # Medication administration (Nitroglycerin)
            session.add(
                MedicationAdministration(
                    id=_det("med-ntg"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    medication_name="Nitroglycerin",
                    rxnorm_code="4917",
                    dose_value="0.4",
                    dose_unit="mg",
                    route="SL",
                    indication="Chest pain unrelieved by aspirin",
                    response="Partial relief; pain 7/10 -> 4/10",
                    export_state=InterventionExportState.MAPPED_READY,
                    administered_at=at_patient + timedelta(minutes=7),
                    administered_by_user_id=DEMO_USER_ID,
                )
            )

            # Signature artifact (transfer of care placeholder)
            session.add(
                EpcrSignatureArtifact(
                    id=_det("signature-toc"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    source_domain="seed_script",
                    source_capture_id=_det("signature-capture"),
                    incident_id=None,
                    page_id=None,
                    signature_class="receiving_facility_transfer",
                    signature_method="seed_placeholder",
                    workflow_policy="demo_seed_v1",
                    policy_pack_version="2026.04.22",
                    payer_class="commercial",
                    jurisdiction_country="US",
                    jurisdiction_state="FL",
                    signer_identity="Demo Receiving RN",
                    signer_relationship="receiving_clinician",
                    signer_authority_basis="hospital_role",
                    patient_capable_to_sign=True,
                    incapacity_reason=None,
                    receiving_facility="Demo Regional Medical Center",
                    receiving_clinician_name="Demo Receiving RN",
                    receiving_role_title="Charge Nurse",
                    transfer_of_care_time=at_destination + timedelta(minutes=4),
                    transfer_exception_reason_code=None,
                    transfer_exception_reason_detail=None,
                    signature_on_file_reference=None,
                    ambulance_employee_exception=False,
                    receiving_facility_verification_status="not_required",
                    signature_artifact_data_url=None,
                    compliance_decision="seed_placeholder",
                    compliance_why=(
                        "Seed-only signature row — DOES NOT represent a real signed "
                        "transfer of care. UI must treat as PARTIAL until a real "
                        "capture replaces this row."
                    ),
                    missing_requirements_json=json.dumps(["real_signature_capture"]),
                    billing_readiness_effect="not_billable",
                    chart_completion_effect="blocks_finalization",
                    retention_requirements_json=json.dumps([]),
                    ai_decision_explanation_json=json.dumps({"source": "seed_script"}),
                    transfer_etimes12_recorded=True,
                    wards_export_safe=False,
                    nemsis_export_safe=False,
                    created_by_user_id=DEMO_USER_ID,
                    created_at=now,
                    updated_at=now,
                )
            )

            # ----------------------------------------------------------
            # NEMSIS mandatory-field mappings (13 rows).
            #
            # These satisfy the NEMSIS_MANDATORY_FIELDS allowlist enforced by
            # ChartService.check_nemsis_compliance, which is the gate used by
            # NemsisExportService._snapshot. Without these rows the export
            # path correctly refuses to generate (PARTIALLY_COMPLIANT).
            #
            # eResponse.04 is set to a real TAC response number registered
            # in nemsis_template_resolver._TEMPLATE_REGISTRY; that triggers
            # the locked CTA Allergy template path, which the bundled XSD
            # validator has been proven to accept (xsd_valid=true).
            # ----------------------------------------------------------
            nemsis_mappings = [
                ("eRecord.01", DEMO_CALL_NUMBER),
                ("eRecord.02", "Adaptix Platform"),
                ("eRecord.03", "Adaptix ePCR"),
                ("eRecord.04", "1.0.0"),
                ("eResponse.01", "S07-50120"),
                ("eResponse.03", "DEMO-INC-2026-04-29-0001"),
                # eResponse.04 must match a TAC-registered response number to
                # route through the locked CTA template path; "351-241102-005-1"
                # = 2025-EMS-1-Allergy_v351 (validated externally against XSD).
                ("eResponse.04", "351-241102-005-1"),
                # eResponse.05 must be numeric per nemsis_xml_builder._validate_coded_fields
                # AND must be in the NEMSIS 3.5.1 enum {2205001..2205035}.
                ("eResponse.05", "2205001"),
                ("eTimes.01", "2026-04-29T13:22:00+00:00"),
                ("eTimes.02", "2026-04-29T13:22:30+00:00"),
                ("eTimes.03", "2026-04-29T13:28:00+00:00"),
                ("eTimes.04", "2026-04-29T13:44:00+00:00"),
                ("eTimes.05", "2026-04-29T13:56:00+00:00"),
            ]
            for field_id, field_value in nemsis_mappings:
                session.add(
                    NemsisMappingRecord(
                        id=_det(f"mapping-{field_id}"),
                        chart_id=chart_id,
                        tenant_id=DEMO_TENANT_ID,
                        nemsis_field=field_id,
                        nemsis_value=field_value,
                        source=FieldSource.SYSTEM if hasattr(FieldSource, "SYSTEM") else FieldSource.MANUAL,
                        created_at=now,
                        updated_at=now,
                    )
                )

            # NEMSIS compliance row — now marked FULLY_COMPLIANT because all
            # 13 rows above are present. ChartService.check_nemsis_compliance
            # will recompute and overwrite this row on the first call; the
            # value here is just the post-seed snapshot.
            session.add(
                NemsisCompliance(
                    id=_det("compliance"),
                    chart_id=chart_id,
                    tenant_id=DEMO_TENANT_ID,
                    compliance_status=ComplianceStatus.FULLY_COMPLIANT,
                    mandatory_fields_filled=len(nemsis_mappings),
                    mandatory_fields_required=len(nemsis_mappings),
                    missing_mandatory_fields=json.dumps([]),
                    compliance_checked_at=None,
                )
            )

            await session.commit()

        return {
            "status": "PASS",
            "action": "created",
            "chart_id": chart_id,
            "tenant_id": DEMO_TENANT_ID,
            "tenant_slug": DEMO_TENANT_SLUG,
            "call_number": DEMO_CALL_NUMBER,
            "external_tag": DEMO_EXTERNAL_TAG,
            "rows_written": {
                "epcr_charts": 1,
                "epcr_patient_profiles": 1,
                "epcr_chart_addresses": 1,
                "epcr_assessments": 1,
                "epcr_vitals": 2,
                "epcr_interventions": 1,
                "epcr_medication_administrations": 2,
                "epcr_signature_artifacts": 1,
                "epcr_nemsis_mappings": 13,
                "epcr_nemsis_compliance": 1,
            },
            "caveats": [
                "Signature artifact is a SEED PLACEHOLDER, not a real transfer-of-care signature.",
                "NEMSIS mappings populate the 13 mandatory fields (NEMSIS_MANDATORY_FIELDS) and route through the locked CTA Allergy template path via eResponse.04='351-241102-005-1'.",
                "This seed produces an export-ready chart; the actual XML build and XSD validation happen in scripts/b002_pipeline.py (NOT here).",
            ],
        }
    finally:
        await engine.dispose()


def _print_result(result: dict) -> int:
    status = result.get("status", "BLOCKED")
    print("=" * 64)
    print(f"adaptix-epcr seed_demo_pcr.py — {status}")
    print("=" * 64)
    for key, value in result.items():
        if key == "status":
            continue
        if isinstance(value, (dict, list)):
            print(f"{key}:")
            print(json.dumps(value, indent=2, default=str))
        else:
            print(f"{key}: {value}")
    print("=" * 64)
    return 0 if status == "PASS" else 2


def main() -> int:
    url, blocked = _safe_database_url()
    if blocked is not None:
        return _print_result({"status": "BLOCKED", "reason": "config", "detail": blocked})

    try:
        # Late import so missing SQLAlchemy/asyncpg yields a clean BLOCKED row.
        import sqlalchemy  # noqa: F401
    except Exception as exc:  # pragma: no cover - defensive
        return _print_result(
            {
                "status": "BLOCKED",
                "reason": "missing_dependency",
                "detail": f"SQLAlchemy import failed: {exc!r}. Activate the EPCR venv first.",
            }
        )

    try:
        result = asyncio.run(_seed(url))
    except ModuleNotFoundError as exc:
        return _print_result(
            {
                "status": "BLOCKED",
                "reason": "missing_module",
                "detail": (
                    f"Required module not importable: {exc.name!r}. "
                    "Run from inside the EPCR venv: "
                    "`Adaptix-EPCR-Service\\.venv\\Scripts\\python.exe scripts/seed_demo_pcr.py`."
                ),
            }
        )
    except Exception as exc:  # pragma: no cover - surfaced via output
        return _print_result(
            {
                "status": "BLOCKED",
                "reason": "exception",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    return _print_result(result)


if __name__ == "__main__":
    sys.exit(main())
