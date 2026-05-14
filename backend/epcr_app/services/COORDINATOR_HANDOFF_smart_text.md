# Coordinator handoff — SmartTextService pillar

This pillar is **collision-free**: it owns its model, migration, service
module, and tests. Wiring the pillar into the workspace + API + web
client requires changes in files owned by other agents — listed below
as concrete action items.

## 1. Workspace capability flip (`chart_workspace_service.py`)

Owner: workspace agent.

In `ChartWorkspaceService._load_workspace` capability block, replace
the existing `smart_text` entry:

```python
"smart_text": {
    "capability": "unavailable",
    "reason": "smart_text_service_not_wired",
},
```

with:

```python
"smart_text": {
    "capability": "live",
    "source": "smart_text_service",
},
```

## 2. New API endpoints (new module — does not touch existing chart-workspace API)

Owner: API agent. Create a new router module
`epcr_app/api_chart_smart_text.py` (or extend
`api_chart_workspace.py`) exposing:

- `POST /api/v1/epcr/chart-workspaces/{chart_id}/smart-text/resolve`
  Body: `{ "section": str, "fieldKey": str }`.
  Calls `smart_text_service.resolve_for_field` and returns the list.
- `POST /api/v1/epcr/chart-workspaces/{chart_id}/smart-text/accept`
  Body: `{ "suggestionId": str }`. Calls `smart_text_service.accept`.
- `POST /api/v1/epcr/chart-workspaces/{chart_id}/smart-text/reject`
  Body: `{ "suggestionId": str }`. Calls `smart_text_service.reject`.

All three must enforce `tenant_id` from the auth context and pass
`user_id` from the JWT subject. The router must commit after each
successful call (the service deliberately does not).

## 3. Optional injection into `_load_workspace`

Owner: workspace agent. After the capability flip, optionally enrich
the workspace payload with a small `smartTextSuggestions` block per
active editable field. Example shape:

```python
workspace["smartTextSuggestions"] = {
    "narrative.chief_complaint": await smart_text_service.resolve_for_field(
        session, tenant_id, chart_id, "narrative", "chief_complaint"
    ),
    # ... other slots
}
```

This is **not** required for the pillar to function — the resolve
endpoint is sufficient — but it removes a round-trip for the
workspace's initial render.

## 4. Web client wiring (`src/lib/epcr-clinical.ts`)

Owner: frontend agent. Add:

```ts
export interface EpcrSmartTextSuggestion {
  id: string;
  chartId: string;
  tenantId: string;
  section: string;
  fieldKey: string;
  phrase: string;
  source: 'agency_library' | 'provider_favorite' | 'protocol' | 'ai';
  confidence: number;            // [0, 1]
  complianceState: 'approved' | 'pending' | 'risk';
  evidenceLinkId: string | null;
  accepted: boolean | null;
  acceptedAt: string | null;     // ISO-8601, UTC
  performedBy: string | null;
}

export async function resolveSmartText(
  chartId: string,
  section: string,
  fieldKey: string,
): Promise<EpcrSmartTextSuggestion[]> { /* POST .../smart-text/resolve */ }

export async function acceptSmartText(
  chartId: string,
  suggestionId: string,
): Promise<EpcrSmartTextSuggestion> { /* POST .../smart-text/accept */ }

export async function rejectSmartText(
  chartId: string,
  suggestionId: string,
): Promise<EpcrSmartTextSuggestion> { /* POST .../smart-text/reject */ }
```

## 5. Contract guarantees from this pillar

- Every returned suggestion carries `source`, `confidence`,
  `complianceState`. Never silently fabricated — when no upstream
  library is present the resolver returns `[]` honestly.
- `accept` and `reject` always write one `EpcrAuditLog` row with
  action `smart_text.accepted` or `smart_text.rejected` and a JSON
  `detail` payload including `suggestion_id`, `section`, `field_key`,
  `source`, `confidence`, `compliance_state`, `evidence_link_id`.
- `evidence_link_id` is a soft reference to
  `epcr_sentence_evidence.id`. The hard FK will be wired in a later
  slice — until then it is a free-form string.
- This pillar does **not** call the AI engine. AI-sourced suggestions
  are written into `epcr_smart_text_suggestion` by
  `ai_clinical_engine.py` (or its successors) with `source='ai'`.

## 6. Migration

`migrations/versions/046_add_smart_text.py` — `down_revision='043'`,
reversible. Apply with `alembic upgrade head` against the target
deployment after merge.
