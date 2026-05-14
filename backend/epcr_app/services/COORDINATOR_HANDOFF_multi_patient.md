# Coordinator Handoff — MultiPatientIncidentService Pillar

Status: live (DB-backed). Owns `epcr_multi_patient_incident` +
`epcr_multi_patient_link` tables (migration `053`).

## 1. Capability registry

Register in the capability map exposed by the chart workspace
service (the coordinator owns
`epcr_app/chart_workspace_service.py`):

```python
"multi_patient": {
    "capability": "live",
    "source": "multi_patient_service",
}
```

## 2. New API endpoints (coordinator owns the routers)

| Method | Path                                          | Purpose                                                        |
|--------|-----------------------------------------------|----------------------------------------------------------------|
| POST   | `/multi-patient-incidents`                    | Create a parent incident from a JSON payload.                  |
| POST   | `/charts/{chart_id}/multi-patient/attach`     | Attach this chart to an incident with a patient label.         |
| DELETE | `/multi-patient-links/{link_id}`              | Soft-delete (detach) a multi-patient link row.                 |

### POST /multi-patient-incidents

Request body (camelCase):

```json
{
  "parentIncidentNumber": "INC-2026-0001",
  "sceneAddress": { "street": "1 Main St" },
  "mciFlag": true,
  "patientCount": 4,
  "mechanism": "MVC-multi-vehicle",
  "hazardsText": "fuel spill",
  "seedChartId": "<chart-uuid|optional>"
}
```

Handler should call:

```python
from epcr_app.services.multi_patient_service import MultiPatientService

await MultiPatientService.create_incident(
    session, tenant_id, user_id, payload,
    seed_chart_id=payload.get("seedChartId"),
)
```

### POST /charts/{chart_id}/multi-patient/attach

Request body:

```json
{
  "incidentId": "<incident-uuid>",
  "patientLabel": "A",
  "triageCategory": "red",            // 'green'|'yellow'|'red'|'black'|null
  "acuity": "critical",                // optional
  "transportPriority": "emergent",     // optional
  "destinationId": "HOSP-1"            // optional
}
```

Handler should call:

```python
await MultiPatientService.attach_chart(
    session,
    tenant_id=tenant_id,
    user_id=user_id,
    incident_id=body["incidentId"],
    chart_id=chart_id,
    patient_label=body["patientLabel"],
    triage_category=body.get("triageCategory"),
    acuity=body.get("acuity"),
    transport_priority=body.get("transportPriority"),
    destination_id=body.get("destinationId"),
)
```

### DELETE /multi-patient-links/{link_id}

Soft-deletes the named link. Body unused. Handler:

```python
await MultiPatientService.detach_chart(
    session, tenant_id, user_id, link_id
)
```

All three endpoints MUST require the standard auth + tenant scoping
middleware already used by other ePCR endpoints. None of them
fabricates clinical data; the service layer raises
`MultiPatientServiceError` for invalid payloads — map to 4xx.

## 3. Workspace projection injection

`ChartWorkspaceService._load_workspace` (coordinator-owned) must
include the multi-patient context block for the currently-viewed
chart:

```python
from epcr_app.services.multi_patient_service import MultiPatientService

workspace["multi_patient"] = await MultiPatientService.list_for_chart(
    session, tenant_id, chart.id
)
```

Returned shape:

```jsonc
{
  "incident": { /* MultiPatientIncident or null */ },
  "self":     { /* MultiPatientLink for this chart or null */ },
  "siblings": [ /* MultiPatientLink rows for other patients */ ]
}
```

Sibling rows expose only the link metadata (label, triage, acuity,
transport, destination, chart_id). No chart clinical data is leaked
through this projection.

## 4. Frontend types + helpers — `src/lib/epcr-clinical.ts`

The web-app owner of `src/lib/epcr-clinical.ts` must add:

```ts
export type TriageCategory = 'green' | 'yellow' | 'red' | 'black';

export interface MultiPatientIncident {
  id: string;
  tenantId: string;
  parentIncidentNumber: string;
  sceneAddress: Record<string, unknown> | unknown[] | null;
  mciFlag: boolean;
  patientCount: number;
  mechanism: string | null;
  hazardsText: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface MultiPatientLink {
  id: string;
  tenantId: string;
  multiIncidentId: string;
  chartId: string;
  patientLabel: string;        // 'A'|'B'|... | 'unknown_1'
  triageCategory: TriageCategory | null;
  acuity: string | null;
  transportPriority: string | null;
  destinationId: string | null;
  createdAt: string;
  updatedAt: string;
  removedAt: string | null;
}

export interface MultiPatientWorkspace {
  incident: MultiPatientIncident | null;
  self: MultiPatientLink | null;
  siblings: MultiPatientLink[];
}

export function isMultiPatientChart(ws: MultiPatientWorkspace): boolean {
  return ws.incident !== null && ws.siblings.length > 0;
}

export function siblingByLabel(
  ws: MultiPatientWorkspace,
  label: string,
): MultiPatientLink | undefined {
  return ws.siblings.find((s) => s.patientLabel === label);
}
```

Place these alongside the other clinical type modules; do not modify
the existing exports.

## 5. Provider-confirmation rule for cross-chart copies

`merge_incidents` and `split_incident` re-point link rows ONLY; they
NEVER copy chart-level clinical data between charts. Any UI flow that
offers "carry forward to sibling chart" semantics must route through
the existing chart-workspace `update_workspace_section` path with the
provider explicitly confirming each section, mirroring the pattern
used by `RepeatPatientService`.

## 6. Audit actions emitted

| Action                              | Emitted by                       |
|-------------------------------------|----------------------------------|
| `multi_patient.incident_created`    | `create_incident` (seed chart)   |
| `multi_patient.chart_attached`      | `attach_chart`                   |
| `multi_patient.chart_detached`      | `detach_chart`                   |
| `multi_patient.link_merged`         | `merge_incidents` (per link)     |
| `multi_patient.link_split`          | `split_incident` (per link)      |

All actions write `EpcrAuditLog` rows; the coordinator's downstream
audit exporter requires no changes.

## 7. Migration

`migrations/versions/053_add_multi_patient.py`
(revision=`053`, down_revision=`043`). Reversible. Idempotent via
`if_not_exists=True`. Will become one of several siblings on `043`
that the next merge migration will combine.
