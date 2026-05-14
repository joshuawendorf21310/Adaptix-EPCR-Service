# Coordinator handoff — PriorEcgService pillar

Owner: PriorEcgService (epcr_app/services/prior_ecg_service.py)
Migration: 049_add_prior_ecg.py (down_revision = "043")
Tables: `epcr_prior_ecg_reference`, `epcr_ecg_comparison_result`

This pillar is metadata-only. It NEVER produces a diagnosis. The
service code is guarded by `tests/test_prior_ecg_no_diagnosis.py`,
which fails the build if forbidden substrings (`STEMI`, `arrhythmia`,
`interpretation`, `detect`) appear in the service module.

---

## 1. Capability flip

When the new tables are migrated and the API endpoints are wired,
flip the workspace capability row:

```jsonc
{
  "prior_ecg": { "capability": "live", "source": "prior_ecg_service" }
}
```

This is what unblocks the dashboard's `EcgSnapshotCard` from rendering
its "unavailable" state. **Note for whoever wires the live UI:** the
existing `EcgSnapshotCard` test enforces no rendering of
`STEMI / diagnosis / interpretation / detected`. The new live view
must keep that contract. The backend will never hand you those
strings; do not introduce them in the frontend either.

## 2. New endpoints (to be added by the coordinator on the API layer)

Owner of the API file is **not** this pillar. The coordinator must
register the following routes pointing at the service functions:

- `GET  /charts/{id}/prior-ecg`
    -> `prior_ecg_service.list_prior_for_chart(session, tenant_id, id)`
- `POST /charts/{id}/prior-ecg/attach`
    -> `prior_ecg_service.attach_prior(...)`
    Body fields: `prior_chart_id?`, `image_storage_uri?`,
    `encounter_context`, `monitor_imported`, `quality`,
    `captured_at?`, `notes?`.
- `POST /charts/{id}/prior-ecg/{prior_id}/comparison`
    -> `prior_ecg_service.record_comparison(...)`
    Body fields: `comparison_state` (one of `similar`, `different`,
    `unable_to_compare`, `not_relevant`), `notes?`.

Auth: same provider-scoped auth as the rest of the chart-workspace
write endpoints. Calling the comparison POST is itself the provider's
attestation; the service stamps `provider_confirmed=true`,
`provider_id`, and `confirmed_at` automatically.

## 3. `_load_workspace` injection

In `chart_workspace_service.py::_load_workspace`, after the other
section fetches, add:

```python
from epcr_app.services import prior_ecg_service as _prior_ecg

prior_refs = await _prior_ecg.list_prior_for_chart(
    session, tenant_id, chart_id
)
# Load comparisons in a single query keyed by chart_id; serialize
# refs/comparisons to camelCase dicts (id, capturedAt, encounterContext,
# imageStorageUri, monitorImported, quality, notes; and for comparisons
# id, priorEcgId, comparisonState, providerConfirmed, providerId,
# confirmedAt, notes).
workspace["prior_ecg"] = {
    "references": [...],
    "comparisons": [...],
}
```

The coordinator owns `chart_workspace_service.py`; this pillar does
not edit it.

## 4. Frontend `src/lib/epcr-clinical.ts`

The capability name `"prior_ecg"` is already in the capability union.
The coordinator adds the corresponding types + helper shape:

```ts
export interface PriorEcgReference {
  id: string;
  capturedAt: string;
  encounterContext: string;
  imageStorageUri: string | null;
  monitorImported: boolean;
  quality: "good" | "acceptable" | "poor" | "unable_to_compare";
  notes: string | null;
}

export interface EcgComparisonResult {
  id: string;
  priorEcgId: string;
  comparisonState:
    | "similar"
    | "different"
    | "unable_to_compare"
    | "not_relevant";
  providerConfirmed: boolean;
  providerId: string | null;
  confirmedAt: string | null;
  notes: string | null;
}

export interface PriorEcgSection {
  references: PriorEcgReference[];
  comparisons: EcgComparisonResult[];
}
```

## 5. NEMSIS export gate

When the NEMSIS exporter eventually consumes ECG comparisons, it MUST
call `prior_ecg_service.is_comparison_ready_for_export(row)` and skip
any row where it returns False. `provider_confirmed=true` is a hard
prerequisite; this is contract-tested in
`tests/test_prior_ecg_provider_gate.py`.

## 6. Audit verbs emitted

- `ecg.prior_attached` — emitted by `attach_prior`.
- `ecg.comparison_recorded` — emitted by `record_comparison`.

Both rows land in `epcr_audit_log` with a JSON detail payload
identifying the affected entity ids and key fields.
