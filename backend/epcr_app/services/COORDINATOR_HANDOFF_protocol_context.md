# Coordinator Handoff — ProtocolContextService Pillar

Pillar owner: `epcr_app/services/protocol_context_service.py`
Migration: `migrations/versions/054_add_protocol_context.py`
   `revision = "054"`, `down_revision = "043"`.
Model: `epcr_app.models.EpcrProtocolContext` (table `epcr_protocol_context`).

This document is the integration contract between this pillar and the
coordinator (chart workspace + clinical AI orchestrator). It enumerates
the exact changes the coordinator must make. Nothing in this pillar
mutates coordinator-owned modules; the coordinator wires the new
service in itself.

---

## 1. Workspace capability flag

Replace the existing `read_only` placeholder entry for
`protocol_context` in the workspace capability map with:

```python
"protocol_context": {
    "capability": "live",
    "source": "protocol_context_service",
}
```

Surface: `epcr_app/api_chart_workspace.py` (and any internal capability
manifest the coordinator consumes for the workspace `capabilities`
envelope). The string `"live"` indicates the pillar accepts writes, not
just reads.

---

## 2. New endpoints

The coordinator owns the FastAPI router that exposes these endpoints;
the service layer below is pillar-owned and must not be inlined.

### POST `/charts/{chart_id}/protocol/engage`

Request body:

```json
{ "pack": "ACLS" }
```

Behaviour:

```python
from epcr_app.services.protocol_context_service import ProtocolContextService

row = await ProtocolContextService.engage(
    session,
    tenant_id=user.tenant_id,
    chart_id=chart_id,
    user_id=user.user_id,
    pack=body.pack,
)
await session.commit()
```

Response (`201 Created`):

```json
{
  "id": "<uuid>",
  "active_pack": "ACLS",
  "engaged_at": "<iso-8601>",
  "engaged_by": "<user_id>",
  "pack_version": "engine:<n>:<sorted,keys>",
  "satisfaction": { ...lock-readiness-compatible payload... }
}
```

Errors:

* `400` if `pack` is empty / not a string (service raises `ValueError`).

### POST `/charts/{chart_id}/protocol/disengage`

Request body:

```json
{ "reason": "patient_handoff" }
```

Behaviour:

```python
closed = await ProtocolContextService.disengage(
    session,
    tenant_id=user.tenant_id,
    chart_id=chart_id,
    user_id=user.user_id,
    reason=body.reason,
)
await session.commit()
```

Response (`200`):

* When a context was active: the closed `EpcrProtocolContext` row in
  the same envelope shape as `engage`, with `disengaged_at` populated.
* When no context was active: `{"active_pack": null, "noop": true}`.
  An audit row is still emitted (`protocol.disengaged`, `noop: true`).

Errors:

* `400` if `reason` is empty (service raises `ValueError`).

### GET `/charts/{chart_id}/protocol/satisfaction`

Behaviour:

```python
payload = await ProtocolContextService.evaluate_required_field_satisfaction(
    session,
    user.tenant_id,
    chart_id,
)
```

Response (`200`): a JSON object with the keys

| key | type | notes |
| --- | --- | --- |
| `score` | float in `[0.0, 1.0]` | 1.0 when no pack engaged, 0.0 if any required field missing or audit log unavailable |
| `blockers` | list[dict] | one entry per missing required NEMSIS field |
| `warnings` | list[dict] | `protocol_partial` row when 0 < populated < total |
| `advisories` | list[dict] | `no_active_pack` / `pack_unknown` / `audit_unavailable` |
| `generated_at` | ISO-8601 UTC | |
| `active_pack` | str \| null | |
| `pack_known` | bool | true iff present in `ai_clinical_engine.PROTOCOL_PACKS` |
| `satisfied_fields` | list[str] | required NEMSIS elements found in chart-field audit |
| `missing_fields` | list[str] | complement |
| `required_total` | int | |
| `required_present` | int | |

The shape is compatible with `LockReadinessService.get_for_chart` —
the workspace UI can render it through the same component contract.

---

## 3. `_load_workspace` injection

Inside `chart_workspace_service._load_workspace` (coordinator-owned,
do **not** edit from this pillar), after the existing workspace dict is
assembled, inject the active context:

```python
from epcr_app.services.protocol_context_service import ProtocolContextService

workspace["protocol_context"] = await ProtocolContextService.list_active(
    session, tenant_id, chart_id
)
```

The injection result is either an ORM `EpcrProtocolContext` instance
(coordinator will serialize it via its existing Pydantic adapter) or
`None`. When non-`None`, the coordinator should also inline the most
recent satisfaction snapshot from
`required_field_satisfaction_json` so the workspace payload remains a
single round-trip.

---

## 4. Frontend types & helpers (`src/lib/epcr-clinical.ts`)

Coordinator-owned. Add (do **not** edit from this pillar):

```ts
export type ProtocolPack = "ACLS" | "PALS" | "NRP" | "CCT" | string;

export interface ProtocolContext {
  id: string;
  tenant_id: string;
  chart_id: string;
  active_pack: ProtocolPack | null;
  engaged_at: string;     // ISO-8601 UTC
  engaged_by: string;
  disengaged_at: string | null;
  pack_version: string;
  required_field_satisfaction: ProtocolSatisfaction | null;
}

export interface ProtocolSatisfactionBlocker {
  kind: "missing_protocol_required_field";
  field: string;
  active_pack: string;
  message: string;
  source: "protocol_context_service";
}

export interface ProtocolSatisfaction {
  score: number;                       // [0.0, 1.0]
  blockers: ProtocolSatisfactionBlocker[];
  warnings: { kind: string; message: string; [k: string]: unknown }[];
  advisories: { kind: string; message: string; [k: string]: unknown }[];
  generated_at: string;
  active_pack: string | null;
  pack_known: boolean;
  satisfied_fields: string[];
  missing_fields: string[];
  required_total: number;
  required_present: number;
}

export async function engageProtocolPack(
  chartId: string, pack: ProtocolPack,
): Promise<ProtocolContext> {
  const res = await fetch(`/api/epcr/charts/${chartId}/protocol/engage`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ pack }),
  });
  if (!res.ok) throw new Error(`engage failed: ${res.status}`);
  return res.json();
}

export async function disengageProtocolPack(
  chartId: string, reason: string,
): Promise<ProtocolContext | { active_pack: null; noop: true }> {
  const res = await fetch(`/api/epcr/charts/${chartId}/protocol/disengage`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error(`disengage failed: ${res.status}`);
  return res.json();
}

export async function getProtocolSatisfaction(
  chartId: string,
): Promise<ProtocolSatisfaction> {
  const res = await fetch(`/api/epcr/charts/${chartId}/protocol/satisfaction`);
  if (!res.ok) throw new Error(`satisfaction failed: ${res.status}`);
  return res.json();
}

export function isProtocolReady(s: ProtocolSatisfaction): boolean {
  return s.score >= 1.0 && s.blockers.length === 0;
}
```

The coordinator is responsible for re-exporting these from the
`epcr-clinical` barrel.

---

## Audit actions emitted by this pillar

| action | when |
| --- | --- |
| `protocol.engaged` | every successful `engage` call |
| `protocol.disengaged` | every `disengage` call (including no-op) AND when an existing context is superseded by a fresh `engage` |

Both rows are appended to the canonical `epcr_audit_log` table
(`EpcrAuditLog`). `detail_json` carries `context_id`, `active_pack`,
and pillar-specific keys (`reason`, `superseded_by_pack`,
`pack_known`, `required_field_count`, `noop`).

---

## Engine coupling

The service reads `PROTOCOL_PACKS` from `ai_clinical_engine` directly
and **never** mutates that module. Pack keys not in the engine
registry (e.g. `"NRP"`, `"CCT"` at the current engine pin) are still
accepted at the model layer; the satisfaction payload then carries a
`pack_unknown` advisory and a 0.0 score so the UI never claims
readiness for a pack it cannot evaluate.

---

## Test evidence

```
backend $ alembic upgrade 054 && alembic downgrade 043 && alembic upgrade 054
... OK (reversible)

backend $ pytest tests/test_protocol_context_model.py tests/test_protocol_context_service.py
14 passed.
```
