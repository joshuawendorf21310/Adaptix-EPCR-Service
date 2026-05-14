# RxNormMedicationService — Coordinator Handoff

This pillar adds live RxNorm normalization for medication administrations
captured on an ePCR chart. The service owns its own match table (which
doubles as the local cache); raw text is always preserved on
`MedicationAdministration.medication_name`. **The service never
fabricates an `rxcui`.**

Files owned by this pillar:

- `epcr_app/services/rxnorm_service.py` — `RxNavClient` + `RxNormService`
- `epcr_app/models.py` — appended class `EpcrRxNormMedicationMatch`
- `migrations/versions/050_add_rxnorm_match.py` — table `epcr_rxnorm_medication_match`, `down_revision = '043'`
- `tests/test_rxnorm_model.py`, `tests/test_rxnorm_service.py`, `tests/test_rxnorm_no_fabrication.py`

Coordinator changes still required (this pillar does NOT touch these
files — DO NOT edit them from inside this PR):

---

## 1. Workspace `capabilities` map

In `chart_workspace_service.py` (or wherever the workspace
`capabilities` block is assembled), add the rxnorm entry by calling the
service's capability reporter. The value is environment-sensitive:

```python
from epcr_app.services.rxnorm_service import RxNormService

capabilities["rxnorm"] = RxNormService.capability()
# When RXNAV_URL is set:
#   {"capability": "live", "source": "rxnorm_service"}
# When RXNAV_URL is unset:
#   {"capability": "read_only_cache", "reason": "RXNAV_URL not configured"}
```

The "live" form is required by the contract whenever `RXNAV_URL` is
configured. The "read_only_cache" form is the honest fallback: prior
matches still serve through `list_for_chart`, but new lookups will
report `unavailable` per medication.

## 2. New API endpoints

Add two endpoints to the chart medications router:

- `POST /charts/{chart_id}/medications/{med_id}/normalize`
  - Constructs an `RxNavClient` via `RxNormService.build_client()`.
  - If the client is `None`, calls `normalize_for_chart` anyway so the
    response includes the honest `capability: "unavailable"` outcome
    per medication.
  - Else, calls `normalize_for_chart` and returns the outcomes.
  - The caller owns `await client.aclose()` (service does not close
    the client it didn't construct).

- `POST /charts/{chart_id}/medications/{med_id}/confirm-rxnorm`
  - Body: `{ "matchId": str, "normalizedName": str, "rxcui": str, "tty": "IN"|"BN"|"SCD"|"SBD"|null, "doseForm": str|null, "strength": str|null }`
  - Calls `RxNormService.confirm(..., provider_id=current_user.id)`.
  - This marks the match `source = "provider_confirmed"`, sets
    `provider_confirmed = True`, and stamps `confirmed_at`.

Both endpoints require chart-tenant authorization (same as the existing
medication endpoints).

## 3. `_load_workspace` injection

In `ChartWorkspaceService._load_workspace` (or its equivalent), inject:

```python
from epcr_app.services.rxnorm_service import RxNormService

workspace["rxnorm_matches"] = await RxNormService.list_for_chart(
    session, tenant_id=tenant_id, chart_id=chart_id
)
```

Place it after `medications_administered` so consumers can correlate
matches to medication rows by `medicationAdminId`.

## 4. `src/lib/epcr-clinical.ts` types + helpers

Add to the EPCR clinical types module:

```ts
export type RxNormTty = "IN" | "BN" | "SCD" | "SBD";

export type RxNormSource =
  | "rxnav_api"
  | "local_cache"
  | "provider_confirmed";

export interface RxNormMatch {
  id: string;
  tenantId: string;
  chartId: string;
  medicationAdminId: string;
  rawText: string;
  normalizedName: string | null;
  rxcui: string | null;
  tty: RxNormTty | null;
  doseForm: string | null;
  strength: string | null;
  confidence: number | null;        // 0..1
  source: RxNormSource;
  providerConfirmed: boolean;
  providerId: string | null;
  confirmedAt: string | null;       // ISO-8601
  createdAt: string;
  updatedAt: string;
}

export type RxNormCapability =
  | { capability: "live"; source: "rxnorm_service" }
  | { capability: "read_only_cache"; reason: string };

export interface RxNormNormalizeOutcome {
  medicationAdminId: string;
  capability: "live_match" | "cache_hit" | "no_match" | "unavailable";
  matchId: string | null;
  rxcui: string | null;
  reason?: string;
}

/** Match lookup helper for UI rendering. */
export function findRxNormMatch(
  matches: RxNormMatch[] | undefined,
  medicationAdminId: string,
): RxNormMatch | undefined {
  return matches?.find((m) => m.medicationAdminId === medicationAdminId);
}

/** A match is authoritative when a provider has confirmed it. */
export function isRxNormAuthoritative(match: RxNormMatch | undefined): boolean {
  return Boolean(match?.providerConfirmed);
}
```

## 5. Environment

- `RXNAV_URL` (optional): full base URL of the RxNav REST API. The public
  endpoint is `https://rxnav.nlm.nih.gov/REST`. When unset, the service
  operates read-only against the cache.

## 6. Contract guarantees (for downstream agents)

- Raw text is never lost. `MedicationAdministration.medication_name`
  remains the source of truth even when normalization fails.
- The service never writes a fabricated `rxcui`. A NULL `rxcui` is
  always an honest "we could not resolve this", never a sentinel.
- Provider-confirmed matches always win and are not overwritten by
  subsequent automated normalization passes — `normalize_for_chart`
  treats any persisted row as a cache hit.
