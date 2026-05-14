# Coordinator Handoff — RepeatPatientService

This pillar lives in the EPCR service and is fully test-covered. It is
ready for wiring into the chart workspace, the HTTP surface, and the
shared TypeScript contract.

## 1. Capability Manifest

Register the new capability alongside the existing chart-workspace pillars:

```python
"repeat_patient": {
    "capability": "live",
    "source": "repeat_patient_service",
}
```

Source module: `epcr_app.services.repeat_patient_service`
Service class: `RepeatPatientService` (static; no `session.commit()` —
caller owns the transaction)

## 2. New Endpoints

Wire these three endpoints under the existing chart router. All routes
are tenant-scoped via the standard auth dependency.

| Method | Path                                                              | Service Call                                                                          |
| ------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| GET    | `/charts/{id}/repeat-patient/matches`                             | `RepeatPatientService.find_matches(session, tenant_id, chart_id, current_patient)` (idempotent re-discovery) and read of existing matches |
| POST   | `/charts/{id}/repeat-patient/matches/{match_id}/review`           | `RepeatPatientService.review(session, tenant_id, chart_id, user_id, match_id, carry_forward_allowed)` |
| POST   | `/charts/{id}/repeat-patient/matches/{match_id}/carry-forward`    | `RepeatPatientService.carry_forward(session, tenant_id, chart_id, user_id, source_field, target_field, match_id=match_id)` |

Error mapping:
- `RepeatPatientReviewRequiredError` -> HTTP 409 (`carry_forward_required_review`)
- `RepeatPatientMatchNotFoundError` -> HTTP 404
- `ValueError` (carry-forward ineligible field) -> HTTP 400

## 3. Workspace Injection

In `chart_workspace_service.py`'s `_load_workspace` injection point, add:

```python
workspace["repeat_patient"] = {
    "matches": [_serialize_match(m) for m in matches],
    "prior_charts": [
        _serialize_prior_chart(r)
        for r in await RepeatPatientService.list_prior_charts(
            session, tenant_id, matched_profile_id
        )
    ],
}
```

The serializers should emit camelCase, mirroring the existing pillars:

`_serialize_match(match) -> dict`:
- `id` (str)
- `matchedProfileId` (str)
- `confidence` (float, 0..1)
- `matchReasons` (list of `{field, equality}`)
- `reviewed` (bool)
- `reviewedBy` (str | null)
- `reviewedAt` (ISO8601 | null)
- `carryForwardAllowed` (bool)
- `createdAt` / `updatedAt`

`_serialize_prior_chart(ref) -> dict`:
- `id` (str)
- `priorChartId` (str)
- `encounterAt` (ISO8601 | null)
- `chiefComplaint` (str | null)
- `disposition` (str | null)

## 4. Shared TypeScript Contract

In `src/lib/epcr-clinical.ts` (web-app repo) add:

```ts
export interface EpcrRepeatPatientMatchReason {
  field: "date_of_birth" | "last_name" | "phone_last4";
  equality: "exact" | "case_insensitive";
}

export interface EpcrRepeatPatientMatch {
  id: string;
  matchedProfileId: string;
  confidence: number; // 0..1
  matchReasons: EpcrRepeatPatientMatchReason[];
  reviewed: boolean;
  reviewedBy: string | null;
  reviewedAt: string | null;
  carryForwardAllowed: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface EpcrPriorChartReference {
  id: string;
  priorChartId: string;
  encounterAt: string | null;
  chiefComplaint: string | null;
  disposition: string | null;
}

export function isRepeatPatientMatchActionable(
  m: EpcrRepeatPatientMatch
): boolean {
  return m.reviewed && m.carryForwardAllowed;
}

export function summarizeMatchReasons(
  m: EpcrRepeatPatientMatch
): string {
  return m.matchReasons.map((r) => r.field).sort().join(", ");
}
```

## 5. Hard Rule (must remain enforced on the boundary)

`carry_forward` MUST refuse on any match that has not been explicitly
reviewed AND approved (`reviewed=true && carry_forward_allowed=true`).
This is unit-pinned in `tests/test_repeat_patient_no_overwrite.py`.

## 6. Files Owned

- `backend/migrations/versions/048_add_repeat_patient.py`
  (down_revision='043', reversible)
- `backend/epcr_app/services/repeat_patient_service.py`
- `backend/tests/test_repeat_patient_model.py`
- `backend/tests/test_repeat_patient_service.py`
- `backend/tests/test_repeat_patient_no_overwrite.py`
- `backend/epcr_app/models.py` (append-only: `EpcrRepeatPatientMatch`,
  `EpcrPriorChartReference`)
- `backend/epcr_app/models/__init__.py` (re-export shim updated to expose
  the two new ORM symbols)

## 7. Verification

```
alembic isolated upgrade 048 -> OK
alembic isolated downgrade 048 -> 043 -> OK
pytest tests/test_repeat_patient_*.py -> 12 passed
```
