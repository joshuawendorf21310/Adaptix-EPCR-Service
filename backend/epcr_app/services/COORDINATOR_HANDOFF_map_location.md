# Coordinator Handoff — Mapbox ePCR Location Pillar

Owner: `epcr_app.services.map_location_service`
Migration: `052_add_map_location.py` (down_revision = `043`)
Model: `EpcrMapLocationContext` (table `epcr_map_location_context`)
Status: live behind capability flag — Mapbox network calls gated by
`MAPBOX_TOKEN`.

This document is the hand-off contract for the coordinator agent that
owns `chart_workspace_service.py`, the chart router, and the
`src/lib/epcr-clinical.ts` typing surface. The map-location pillar
does NOT modify those files; it expects the coordinator to wire the
items below.

---

## 1. Workspace capability map

In `ChartWorkspaceService._capabilities` (or its equivalent), replace
the current placeholder

```python
"map_location": {
    "capability": "unavailable",
    "reason": "mapbox_location_service_not_wired",
},
```

with the token-aware live/read-only decision:

```python
import os

if (os.environ.get("MAPBOX_TOKEN") or "").strip():
    map_location_cap = {
        "capability": "live",
        "source": "map_location_service",
    }
else:
    map_location_cap = {
        "capability": "read_only",
        "reason": "MAPBOX_TOKEN not configured",
    }

capabilities["map_location"] = map_location_cap
```

`read_only` means: persisted rows for this chart are returned, but
reverse-geocode and Directions enrichment are inert and the service
honestly advertises that — never fabricated.

---

## 2. New HTTP endpoints

The coordinator's chart router should expose three endpoints. The
underlying service is `MapLocationService` from
`epcr_app.services.map_location_service`.

### POST `/charts/{id}/map-locations`

Records a location capture. Request body (camelCase):

```json
{
  "kind": "scene | destination | staging | breadcrumb",
  "latitude": 47.6062,
  "longitude": -122.3321,
  "accuracyMeters": 5.5,
  "capturedAt": "2026-05-12T10:00:00Z",
  "facilityType":
    "stroke_center | stemi_center | trauma_center | pediatric | burn | behavioral_health | null"
}
```

Handler responsibility:

```python
result = await MapLocationService.record_location(
    session,
    tenant_id=ctx.tenant_id,
    chart_id=chart_id,
    kind=body.kind,
    lat=body.latitude,
    lng=body.longitude,
    accuracy=body.accuracyMeters,
    captured_at=body.capturedAt,
    user_id=ctx.user_id,
    facility_type=body.facilityType,
)
await session.commit()
return result
```

Returns the serialized row, including a truthful `reverseGeocoded`
flag.

### GET `/charts/{id}/map-locations`

Returns all rows for the chart in capture order:

```python
return await MapLocationService.list_for_chart(
    session, tenant_id=ctx.tenant_id, chart_id=chart_id
)
```

### POST `/charts/{id}/route`

Body:

```json
{
  "scene":       { "latitude": 47.6062, "longitude": -122.3321 },
  "destination": { "latitude": 47.6031, "longitude": -122.3233 }
}
```

Handler:

```python
return await MapLocationService.compute_route(body.scene, body.destination)
```

Without a token the response is the canonical
`{"available": false, "reason": "MAPBOX_TOKEN not configured"}` shape;
clients must check `available` before reading `distance_meters` /
`duration_seconds`.

---

## 3. `_load_workspace` injection

The coordinator's `ChartWorkspaceService._load_workspace` (or the
equivalent assembler) should include map locations in the workspace
payload so the field tablet can render scene/destination/breadcrumbs
without a second round-trip:

```python
from epcr_app.services.map_location_service import MapLocationService

workspace["map_locations"] = await MapLocationService.list_for_chart(
    session, tenant_id=tenant_id, chart_id=chart_id
)
```

Capability flag in the same payload already reflects live/read-only
truth (see section 1), so the client can disable enrichment-only UI
when `MAPBOX_TOKEN` is unset.

---

## 4. Frontend types & helpers (`src/lib/epcr-clinical.ts`)

The coordinator owns this file. Add the following types and helpers
(camelCase to match the service serializer):

```ts
export type MapLocationKind =
  | "scene"
  | "destination"
  | "staging"
  | "breadcrumb";

export type EpcrFacilityType =
  | "stroke_center"
  | "stemi_center"
  | "trauma_center"
  | "pediatric"
  | "burn"
  | "behavioral_health";

export interface EpcrMapLocation {
  id: string;
  tenantId: string;
  chartId: string;
  kind: MapLocationKind;
  addressText: string | null;
  latitude: number;
  longitude: number;
  accuracyMeters: number | null;
  reverseGeocoded: boolean;
  facilityType: EpcrFacilityType | null;
  distanceMeters: number | null;
  capturedAt: string;
  createdAt: string;
  updatedAt: string;
}

export type EpcrRouteResult =
  | {
      available: true;
      distance_meters: number;
      duration_seconds: number;
      source: "mapbox_directions";
    }
  | {
      available: false;
      reason: string;
      detail?: string;
    };

export function isMapLocationLive(
  cap: { capability: string },
): boolean {
  return cap.capability === "live";
}

export function hasRouteDistance(
  r: EpcrRouteResult,
): r is Extract<EpcrRouteResult, { available: true }> {
  return r.available === true;
}
```

UI must NOT display `addressText` as a fallback string when
`reverseGeocoded` is `false` — that field is intentionally `null` in
honesty-mode. Likewise, route distance/duration may only be rendered
when `hasRouteDistance(r)` is true.

---

## Files owned by this pillar

- `backend/epcr_app/services/map_location_service.py`
- `backend/migrations/versions/052_add_map_location.py`
- `backend/epcr_app/models.py` (append-only — `EpcrMapLocationContext`)
- `backend/tests/test_map_location_model.py`
- `backend/tests/test_map_location_service.py`
- `backend/tests/test_map_location_honest_unavailable.py`
- `backend/epcr_app/services/COORDINATOR_HANDOFF_map_location.md`

NOT modified by this pillar (coordinator territory):
`chart_workspace_service.py`, `src/lib/epcr-clinical.ts`, the Alembic
merge head, and any TAC files.
