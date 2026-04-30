"""Postgres-direct demo PCR seed (Slice #2B compatibility variant).

Why this script exists in addition to ``seed_demo_pcr.py``:

The workspace ORM in ``epcr_app/models.py`` has drifted ahead of the
schema actually deployed in the running ``epcr_db`` Postgres container
(no ``narrative`` / ``version`` columns on ``epcr_charts``, and ORM
classes like ``PatientProfile`` are missing from the container image's
``epcr_app.models`` package). Rather than mutate the running container's
ORM or apply unscoped migrations, this script performs idempotent raw
``INSERT`` statements that match the EXACT columns currently present in
the container database (verified against ``\\d`` output 2026-04-29).

It uses the same deterministic UUID5 namespace as ``seed_demo_pcr.py``,
so the resulting ``chart_id`` matches: ``0deda819-ea1e-5524-9920-1c5c49cebfbb``.

Like the sibling script, this:
- writes a SEED PLACEHOLDER signature artifact (``nemsis_export_safe=False``)
- writes a PARTIALLY_COMPLIANT NEMSIS row with ``compliance_checked_at=NULL``
- refuses to run unless the URL is local OR ``ADAPTIX_DEMO_SEED_ALLOW_REMOTE=1``
- prints a structured PASS/BLOCKED block

It does NOT generate NEMSIS XML or claim NEMSIS readiness.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone


SEED_NAMESPACE = uuid.UUID("a4d4f5b1-9e3e-4a44-8a77-adaad7170de1")
# Tenant / user IDs default to the deterministic demo IDs but MUST be
# overridden via env when seeding into a deployed core_db so that the
# chart is actually reachable through tenant-scoped auth APIs.
DEMO_TENANT_ID = os.environ.get(
    "ADAPTIX_DEMO_TENANT_ID", "11111111-1111-4111-8111-111111111111"
)
DEMO_TENANT_SLUG = os.environ.get("ADAPTIX_DEMO_TENANT_SLUG", "demo-agency")
DEMO_USER_ID = os.environ.get(
    "ADAPTIX_DEMO_USER_ID", "22222222-2222-4222-8222-222222222222"
)
DEMO_CALL_NUMBER = os.environ.get(
    "ADAPTIX_DEMO_CALL_NUMBER", "DEMO-2026-04-29-0001"
)


def _det(name: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, name))


def _utc(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def _resolve_url() -> tuple[str | None, str | None]:
    url = os.environ.get("EPCR_DATABASE_URL") or os.environ.get("CARE_DATABASE_URL")
    if not url:
        return None, "EPCR_DATABASE_URL is not set."
    if "ADAPTIX_DEMO_SEED_ALLOW_REMOTE" not in os.environ:
        lowered = url.lower()
        is_local = (
            lowered.startswith("sqlite")
            or "@localhost" in lowered
            or "@127.0.0.1" in lowered
            or "@host.docker.internal" in lowered
            or "@postgres:" in lowered  # docker-compose internal hostname
        )
        if not is_local:
            return None, (
                "Refusing to seed against non-local database. "
                "Set ADAPTIX_DEMO_SEED_ALLOW_REMOTE=1 to override."
            )
    # Strip SQLAlchemy driver prefix to get bare DSN for asyncpg.
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://") or url.startswith("postgresql+psycopg2://"):
        url = "postgresql://" + url.split("://", 1)[1]
    if not url.startswith("postgresql://"):
        return None, f"This script only supports postgres URLs (got prefix {url[:24]!r})."
    return url, None


async def _seed(dsn: str) -> dict:
    import asyncpg  # type: ignore

    chart_id = _det("chart")
    dispatch = _utc(2026, 4, 29, 13, 22, 0)
    on_scene = dispatch + timedelta(minutes=6)
    at_patient = on_scene + timedelta(minutes=2)
    depart_scene = at_patient + timedelta(minutes=14)
    at_destination = depart_scene + timedelta(minutes=12)
    now = _utc(2026, 4, 29, 14, 0, 0)

    conn = await asyncpg.connect(dsn=dsn)
    try:
        existing = await conn.fetchrow(
            "select id from epcr_charts where id = $1", chart_id
        )
        if existing:
            return {
                "status": "PASS",
                "action": "noop",
                "chart_id": chart_id,
                "tenant_id": DEMO_TENANT_ID,
                "tenant_slug": DEMO_TENANT_SLUG,
                "call_number": DEMO_CALL_NUMBER,
                "detail": "Demo PCR already present — raw-SQL seed is idempotent.",
            }

        async with conn.transaction():
            # Chart
            await conn.execute(
                """
                insert into epcr_charts (
                    id, tenant_id, call_number, patient_id, incident_type,
                    status, created_by_user_id, created_at, updated_at
                ) values ($1,$2,$3,$4,$5,$6::chartstatus,$7,$8,$9)
                """,
                chart_id, DEMO_TENANT_ID, DEMO_CALL_NUMBER, _det("patient-link"),
                "medical", "UNDER_REVIEW", DEMO_USER_ID, dispatch, now,
            )

            # Patient profile
            await conn.execute(
                """
                insert into epcr_patient_profiles (
                    id, chart_id, tenant_id, first_name, middle_name, last_name,
                    date_of_birth, age_years, sex, phone_number, weight_kg,
                    allergies_json, updated_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                """,
                _det("patient-profile"), chart_id, DEMO_TENANT_ID,
                "Demo", "A", "Patient",
                "1958-07-12", 67, "male", "555-0100", 84.0,
                json.dumps(["NKDA"]), now,
            )

            # Chart address (incident scene)
            await conn.execute(
                """
                insert into epcr_chart_addresses (
                    id, chart_id, tenant_id, raw_text, street_line_one,
                    street_line_two, city, state, postal_code, county,
                    latitude, longitude, validation_state, intelligence_source,
                    intelligence_detail, updated_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                """,
                _det("scene-address"), chart_id, DEMO_TENANT_ID,
                "100 Demo Way, Demo City, FL 32099",
                "100 Demo Way", None, "Demo City", "FL", "32099", "Demo County",
                28.5383, -81.3792, "manual_verified", "seed_script",
                "Synthetic address for local NEMSIS smoke", now,
            )

            # Assessment
            await conn.execute(
                """
                insert into epcr_assessments (
                    id, chart_id, tenant_id, chief_complaint, field_diagnosis,
                    documented_at, primary_impression, secondary_impression,
                    impression_notes, snomed_code, icd10_code, acuity
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                """,
                _det("assessment"), chart_id, DEMO_TENANT_ID,
                "Chest pressure radiating to left arm",
                "Suspected acute coronary syndrome",
                at_patient,
                "Chest Pain - Cardiac Suspected", None,
                "12-lead obtained on scene; transmitted to receiving facility.",
                "29857009", "I20.9", "emergent",
            )

            # Vitals x2
            await conn.execute(
                """
                insert into epcr_vitals (
                    id, chart_id, tenant_id, bp_sys, bp_dia, hr, rr, temp_f,
                    spo2, glucose, recorded_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                _det("vitals-1"), chart_id, DEMO_TENANT_ID,
                152, 94, 102, 22, 98.4, 94, 118, at_patient,
            )
            await conn.execute(
                """
                insert into epcr_vitals (
                    id, chart_id, tenant_id, bp_sys, bp_dia, hr, rr, temp_f,
                    spo2, glucose, recorded_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                _det("vitals-2"), chart_id, DEMO_TENANT_ID,
                138, 86, 92, 18, 98.4, 97, None,
                at_patient + timedelta(minutes=10),
            )

            # Intervention (12-lead)
            await conn.execute(
                """
                insert into epcr_interventions (
                    id, chart_id, tenant_id, category, name, indication, intent,
                    expected_response, actual_response, reassessment_due_at,
                    protocol_family, snomed_code, icd10_code, rxnorm_code,
                    export_state, performed_at, updated_at, provider_id
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                """,
                _det("intervention-12lead"), chart_id, DEMO_TENANT_ID,
                "diagnostic", "12-Lead ECG Acquisition",
                "Chest pain suspected cardiac",
                "Identify STEMI / acute ischemia",
                "Interpretable tracing transmitted to receiving facility",
                "Sinus tachycardia, no acute ST elevation on field 12-lead",
                None, "acls", "29303009", None, None, "mapped_ready",
                at_patient + timedelta(minutes=2), now, DEMO_USER_ID,
            )

            # Medications x2
            await conn.execute(
                """
                insert into epcr_medication_administrations (
                    id, chart_id, tenant_id, medication_name, rxnorm_code,
                    dose_value, dose_unit, route, indication, response,
                    export_state, administered_at, administered_by_user_id, updated_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """,
                _det("med-aspirin"), chart_id, DEMO_TENANT_ID,
                "Aspirin", "1191", "324", "mg", "PO", "Suspected ACS",
                "Tolerated without adverse effect", "mapped_ready",
                at_patient + timedelta(minutes=4), DEMO_USER_ID, now,
            )
            await conn.execute(
                """
                insert into epcr_medication_administrations (
                    id, chart_id, tenant_id, medication_name, rxnorm_code,
                    dose_value, dose_unit, route, indication, response,
                    export_state, administered_at, administered_by_user_id, updated_at
                ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                """,
                _det("med-ntg"), chart_id, DEMO_TENANT_ID,
                "Nitroglycerin", "4917", "0.4", "mg", "SL",
                "Chest pain unrelieved by aspirin",
                "Partial relief; pain 7/10 -> 4/10", "mapped_ready",
                at_patient + timedelta(minutes=7), DEMO_USER_ID, now,
            )

            # Signature artifact (PLACEHOLDER — explicitly marked unsafe)
            await conn.execute(
                """
                insert into epcr_signature_artifacts (
                    id, chart_id, tenant_id, source_domain, source_capture_id,
                    incident_id, page_id, signature_class, signature_method,
                    workflow_policy, policy_pack_version, payer_class,
                    jurisdiction_country, jurisdiction_state, signer_identity,
                    signer_relationship, signer_authority_basis,
                    patient_capable_to_sign, incapacity_reason,
                    receiving_facility, receiving_clinician_name, receiving_role_title,
                    transfer_of_care_time, transfer_exception_reason_code,
                    transfer_exception_reason_detail, signature_on_file_reference,
                    ambulance_employee_exception, receiving_facility_verification_status,
                    signature_artifact_data_url, compliance_decision, compliance_why,
                    missing_requirements_json, billing_readiness_effect,
                    chart_completion_effect, retention_requirements_json,
                    ai_decision_explanation_json, transfer_etimes12_recorded,
                    wards_export_safe, nemsis_export_safe, created_by_user_id,
                    created_at, updated_at
                ) values (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                    $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,
                    $41,$42
                )
                """,
                _det("signature-toc"), chart_id, DEMO_TENANT_ID,
                "seed_script", _det("signature-capture"), None, None,
                "receiving_facility_transfer", "seed_placeholder",
                "demo_seed_v1", "2026.04.22", "commercial",
                "US", "FL", "Demo Receiving RN", "receiving_clinician",
                "hospital_role", True, None,
                "Demo Regional Medical Center", "Demo Receiving RN", "Charge Nurse",
                at_destination + timedelta(minutes=4), None, None, None,
                False, "not_required", None,
                "seed_placeholder",
                "Seed-only signature row — NOT a real signed transfer of care.",
                json.dumps(["real_signature_capture"]),
                "not_billable", "blocks_finalization",
                json.dumps([]), json.dumps({"source": "seed_script"}),
                True, False, False, DEMO_USER_ID, now, now,
            )

            # NEMSIS compliance (PARTIALLY_COMPLIANT, NOT validated)
            missing = [
                "eDispatch.01_validated",
                "eResponse.05_validated",
                "eScene.06_validated",
                "eVitals.full_set_count",
                "eDisposition.27_validated",
                "ePayment.01",
            ]
            await conn.execute(
                """
                insert into epcr_nemsis_compliance (
                    id, chart_id, tenant_id, compliance_status,
                    mandatory_fields_filled, mandatory_fields_required,
                    missing_mandatory_fields, compliance_checked_at,
                    created_at, updated_at
                ) values ($1,$2,$3,$4::compliancestatus,$5,$6,$7,$8,$9,$10)
                """,
                _det("compliance"), chart_id, DEMO_TENANT_ID,
                "PARTIALLY_COMPLIANT", 18, 24, json.dumps(missing),
                None, now, now,
            )

        return {
            "status": "PASS",
            "action": "created",
            "chart_id": chart_id,
            "tenant_id": DEMO_TENANT_ID,
            "tenant_slug": DEMO_TENANT_SLUG,
            "call_number": DEMO_CALL_NUMBER,
            "rows_written": {
                "epcr_charts": 1,
                "epcr_patient_profiles": 1,
                "epcr_chart_addresses": 1,
                "epcr_assessments": 1,
                "epcr_vitals": 2,
                "epcr_interventions": 1,
                "epcr_medication_administrations": 2,
                "epcr_signature_artifacts": 1,
                "epcr_nemsis_compliance": 1,
            },
            "caveats": [
                "Signature artifact is a SEED PLACEHOLDER (nemsis_export_safe=false).",
                "NEMSIS compliance row is PARTIALLY_COMPLIANT; XSD validation has NOT run.",
                "This script does NOT generate or submit NEMSIS XML.",
            ],
        }
    finally:
        await conn.close()


def _print(result: dict) -> int:
    status = result.get("status", "BLOCKED")
    print("=" * 64)
    print(f"adaptix-epcr seed_demo_pcr_pg_raw.py — {status}")
    print("=" * 64)
    for k, v in result.items():
        if k == "status":
            continue
        if isinstance(v, (dict, list)):
            print(f"{k}:")
            print(json.dumps(v, indent=2, default=str))
        else:
            print(f"{k}: {v}")
    print("=" * 64)
    return 0 if status == "PASS" else 2


def main() -> int:
    dsn, blocked = _resolve_url()
    if blocked:
        return _print({"status": "BLOCKED", "reason": "config", "detail": blocked})
    try:
        result = asyncio.run(_seed(dsn))
    except ModuleNotFoundError as exc:
        return _print({
            "status": "BLOCKED",
            "reason": "missing_module",
            "detail": f"asyncpg required: {exc.name!r}",
        })
    except Exception as exc:
        return _print({
            "status": "BLOCKED",
            "reason": "exception",
            "detail": f"{type(exc).__name__}: {exc}",
        })
    return _print(result)


if __name__ == "__main__":
    sys.exit(main())
