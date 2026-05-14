# Coordinator Handoff — LockReadinessService

This pillar is AGGREGATION-only. No new model, no migration, no Alembic head
change. It composes signals from canonical surfaces already on this SHA:

- `ChartService.check_nemsis_compliance` — mandatory-field gate (existing).
- `nemsis_finalization_gate.SchematronFinalizationGate` — schematron
  evaluation contract (existing; consumed indirectly through the same
  blocker semantics, not re-implemented).
- `EpcrAuditLog` rows whose `action` contains the substring `anomaly`.
- The canonical workspace `UNMAPPED_SECTIONS` list (mirrored, not
  imported, to avoid an import cycle).

Return shape (transport-only dict):

```python
{
    "score": float,           # 0.0 .. 1.0; floored to 0.0 by any blocker
    "blockers": [
        {"kind": "missing_mandatory_field", "field": str,
         "message": str, "source": "nemsis_finalization_gate"},
        ...
    ],
    "warnings": [
        {"kind": "readiness_partial", "required_present": int,
         "required_total": int, "message": str},
        {"kind": "audit_anomaly", "audit_id": str, "action": str,
         "user_id": str, "detail": str | None,
         "performed_at": str | None, "message": str},
        ...
    ],
    "advisories": [
        {"kind": "unmapped_field", "section": str,
         "reason": "field_not_mapped", "message": str},
        {"kind": "nemsis_compliance_unavailable",
         "message": str, "detail": str},
        ...
    ],
    "generated_at": str,       # ISO-8601 UTC
}
```

## 1. Capability registry change

In `chart_workspace_service.ChartWorkspaceService._load_workspace`, the
existing `capabilities["readiness"]` entry currently reads:

```python
"readiness": {
    "capability": "live",
    "source": "nemsis_finalization_gate",
},
```

This pillar ENRICHES that entry. Replace its `source` to credit the
aggregator, while keeping `capability: "live"`:

```python
"readiness": {
    "capability": "live",
    "source": "lock_readiness_service",
},
```

The capability stays `live` because the aggregator depends only on
already-live surfaces.

## 2. Endpoint suggestion

No new HTTP endpoint is required. The aggregator is consumed via the
`_load_workspace` augmentation below. If a dedicated probe is later
desired, the natural shape is:

- `GET /api/v1/epcr/charts/{chart_id}/lock-readiness` →
  `LockReadinessService.get_for_chart(...)`

but the current consumer (the workspace payload) covers the UI need.

## 3. `chart_workspace_service.py` edit (NOT performed here)

The handoff change to `_load_workspace` is **deliberately not committed by
this pillar** to respect the collision rules. The coordinator should
apply:

```python
from epcr_app.services.lock_readiness_service import LockReadinessService
# ...
# Replace the existing readiness block:
try:
    readiness = await ChartService.check_nemsis_compliance(
        session, tenant_id, chart_id
    )
except Exception as exc:
    logger.warning("Workspace readiness load failed: %s", exc)
    readiness = {
        "compliance_status": "unavailable",
        # ...
    }
```

with:

```python
readiness = await ChartService.check_nemsis_compliance(
    session, tenant_id, chart_id
)
lock_readiness = await LockReadinessService.get_for_chart(
    session, tenant_id, chart_id
)
```

and add `"lock_readiness": lock_readiness` to the returned dict.

**Backwards compatibility:** the new payload shape
(`score / blockers / warnings / advisories / generated_at`) is NOT
backwards-compatible with the existing `nemsis_readiness` shape
(`compliance_status / compliance_percentage / missing_mandatory_fields /
is_fully_compliant`). Therefore the aggregator must be added as a new
top-level `lock_readiness` envelope key — do NOT overwrite the existing
`nemsis_readiness` key. Existing consumers of `nemsis_readiness` keep
their contract; new consumers read `lock_readiness`.

Also bump the capability:

```python
capabilities["readiness"]["source"] = "lock_readiness_service"
```

## 4. Frontend type (`src/lib/epcr-clinical.ts`)

Add (the coordinator owns this file; this pillar does not edit it):

```ts
export interface LockReadinessBlocker {
  kind: "missing_mandatory_field";
  field: string;
  message: string;
  source: "nemsis_finalization_gate";
}

export interface LockReadinessReadinessPartialWarning {
  kind: "readiness_partial";
  required_present: number;
  required_total: number;
  message: string;
}

export interface LockReadinessAuditAnomalyWarning {
  kind: "audit_anomaly";
  audit_id: string;
  action: string;
  user_id: string;
  detail: string | null;
  performed_at: string | null;
  message: string;
}

export type LockReadinessWarning =
  | LockReadinessReadinessPartialWarning
  | LockReadinessAuditAnomalyWarning;

export interface LockReadinessUnmappedAdvisory {
  kind: "unmapped_field";
  section: string;
  reason: "field_not_mapped";
  message: string;
}

export interface LockReadinessUnavailableAdvisory {
  kind: "nemsis_compliance_unavailable";
  message: string;
  detail: string;
}

export type LockReadinessAdvisory =
  | LockReadinessUnmappedAdvisory
  | LockReadinessUnavailableAdvisory;

export interface LockReadiness {
  score: number; // 0.0 .. 1.0
  blockers: LockReadinessBlocker[];
  warnings: LockReadinessWarning[];
  advisories: LockReadinessAdvisory[];
  generated_at: string; // ISO-8601 UTC
}
```

## Scoring summary (for reviewers)

- Any `blockers` → `score` floored to `0.0`.
- `score = (required_present / required_total) − 0.05 × len(warnings)`,
  clamped to `[0.0, 1.0]`, with the warning penalty capped at `0.5`.
- `required_total == 0` and no signals → `score = 1.0`.
- Compliance check raised → score collapses to `0.0` with a single
  `nemsis_compliance_unavailable` advisory. Never fabricates passing.

## Tests

`backend/tests/test_lock_readiness_service.py` — five cases:
1. Empty / fully compliant — score 1.0.
2. Missing mandatory fields — score floored to 0.0.
3. Audit anomalies + unmapped advisories — score 0.9.
4. Partial fill score math — score 0.45.
5. Compliance failure honesty — score 0.0 + advisory.

Run: `pytest backend/tests/test_lock_readiness_service.py -v` — 5 passed.
