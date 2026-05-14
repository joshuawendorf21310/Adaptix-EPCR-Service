# Coordinator handoff: AuditTrail + ProviderOverride pillar (PR-13)

This pillar adds:

- `EpcrProviderOverride` model + migration `055` (table
  `epcr_provider_override`, `down_revision='043'`).
- `epcr_app.services.provider_override_service.ProviderOverrideService`
  — `record` / `request_supervisor` / `supervisor_confirm` /
  `list_for_chart`, each writing an `EpcrAuditLog` row.
- `epcr_app.services.audit_trail_query_service.AuditTrailQueryService`
  — chronological merge of `EpcrAuditLog`, `EpcrAiAuditEvent`, and
  `EpcrProviderOverride`.

The coordinator (chart-workspace API + frontend) needs to perform the
four integrations below. Each integration is owned by the coordinator
PR; this pillar deliberately does NOT touch `chart_workspace_service.py`,
the alembic head, the `EpcrAuditLog` model, or
`src/lib/epcr-clinical.ts`.

---

## 1. Capability advertisement

Add to the workspace capability map:

```python
workspace["capabilities"]["audit_trail"] = {
    "capability": "live",
    "source": "audit_trail_query_service",
}
```

The shape mirrors the other pillar capability entries already produced
by `ChartWorkspaceService`.

---

## 2. New HTTP endpoints

Register the following endpoints on the chart-workspace API surface.
All require the standard tenant/agency authentication context; the
service layer does not re-check auth.

| Method | Path                                            | Body / Query                                                                          | Maps to                                                |
|--------|-------------------------------------------------|---------------------------------------------------------------------------------------|--------------------------------------------------------|
| POST   | `/charts/{id}/overrides`                        | `{ "section", "fieldKey", "kind", "reasonText" }`                                     | `ProviderOverrideService.record`                       |
| POST   | `/overrides/{id}/request-supervisor`            | `{ "supervisorId" }`                                                                  | `ProviderOverrideService.request_supervisor`           |
| POST   | `/overrides/{id}/supervisor-confirm`            | `{ "supervisorId" }`                                                                  | `ProviderOverrideService.supervisor_confirm`           |
| GET    | `/charts/{id}/audit-trail`                      | `?since=<ISO-8601>&limit=<int>` (optional)                                            | `AuditTrailQueryService.list_for_chart`                |

`ProviderOverrideValidationError` should be translated to HTTP 422
with `{ field, message }`.

Canonical `kind` values (enforced server-side):

- `validation_warning`
- `lock_blocker`
- `state_required`
- `agency_required`
- `ai_suggestion_rejected`

`reasonText` is REQUIRED and must be at least 8 characters after
whitespace stripping; the same minimum is enforced by a portable CHECK
constraint on the table.

---

## 3. `_load_workspace` injection

Inside `ChartWorkspaceService._load_workspace` (or whatever the
coordinator's workspace assembly function is named), REPLACE the
existing `workspace["audit"]` slice — which today reads only
`EpcrAuditLog` — with the merged trail:

```python
from epcr_app.services.audit_trail_query_service import (
    AuditTrailQueryService,
)

workspace["audit_trail"] = await AuditTrailQueryService.list_for_chart(
    session,
    tenant_id=tenant_id,
    chart_id=chart_id,
)
```

The merged entries have the schema:

```jsonc
{
  "id":         "string",
  "kind":       "string",                  // canonical event kind
  "source":     "audit_log" | "ai_audit_event" | "provider_override",
  "occurredAt": "2026-05-12T12:34:56Z",     // ISO-8601 UTC
  "userId":     "string | null",
  "payload":    { /* source-specific */ }
}
```

The query service tolerates the absence of the `EpcrAiAuditEvent`
table (degrades to an empty AI slice), so this injection is safe to
ship even before the AI-evidence migration lands in every environment.

---

## 4. `src/lib/epcr-clinical.ts` types + helpers

Add the following exports to `src/lib/epcr-clinical.ts` (or the
equivalent shared types module):

```ts
export type ProviderOverrideKind =
  | 'validation_warning'
  | 'lock_blocker'
  | 'state_required'
  | 'agency_required'
  | 'ai_suggestion_rejected';

export interface ProviderOverride {
  id: string;
  tenantId: string;
  chartId: string;
  section: string;
  fieldKey: string;
  kind: ProviderOverrideKind;
  reasonText: string;
  overrodeAt: string;     // ISO-8601 UTC
  overrodeBy: string;
  supervisorId: string | null;
  supervisorConfirmedAt: string | null;
  createdAt: string;
}

export type AuditTrailSource =
  | 'audit_log'
  | 'ai_audit_event'
  | 'provider_override';

export interface AuditTrailEntry {
  id: string;
  kind: string;
  source: AuditTrailSource;
  occurredAt: string;          // ISO-8601 UTC
  userId: string | null;
  payload: unknown;
}

export const PROVIDER_OVERRIDE_KINDS: ProviderOverrideKind[] = [
  'validation_warning',
  'lock_blocker',
  'state_required',
  'agency_required',
  'ai_suggestion_rejected',
];

export const PROVIDER_OVERRIDE_REASON_MIN_LENGTH = 8;

export function isProviderOverrideEntry(
  entry: AuditTrailEntry,
): entry is AuditTrailEntry & { payload: ProviderOverridePayload } {
  return entry.source === 'provider_override';
}

export interface ProviderOverridePayload {
  overrideId: string;
  section: string;
  fieldKey: string;
  kind: ProviderOverrideKind;
  reasonText: string;
  supervisorId: string | null;
  supervisorConfirmedAt: string | null;
}
```

The coordinator PR may freely add additional UI-layer helpers (e.g.
filter by source, group by section) on top of these primitives.
