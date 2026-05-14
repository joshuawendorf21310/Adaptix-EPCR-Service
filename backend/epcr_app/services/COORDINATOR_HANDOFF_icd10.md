# Coordinator Handoff — ICD-10 Documentation Specificity Pillar

Pillar: `icd10` (documentation specificity prompts).
Implementation: `backend/epcr_app/services/icd10_service.py`.
Model: `epcr_app.models.EpcrIcd10DocumentationSuggestion` (table
`epcr_icd10_documentation_suggestion`).
Migration: `backend/migrations/versions/051_add_icd10_suggestion.py`
(`revision="051"`, `down_revision="043"`).

This service **prompts** the clinician for documentation specificity.
It **never** assigns a diagnosis code. `candidate_codes_json` is a
suggestion list only; `provider_selected_code` is set exclusively by
the clinician's explicit acknowledgement.

---

## 1. Capability advertisement

Add the following entry to the workspace capability map (consumed by
the frontend `epcrCapability` resolver):

```json
"icd10": { "capability": "live", "source": "icd10_service" }
```

The capability is `live` once migration `051` is applied and the
service module imports cleanly.

---

## 2. New endpoints

Two new HTTP endpoints must be wired by the coordinator (this agent
does **not** touch the API layer).

### `POST /charts/{chart_id}/icd10/generate`

- Auth: standard chart-scoped auth (same dependency stack as
  `chart_workspace`).
- Body: none (or `{}`).
- Behavior:
  1. Call `icd10_service.generate_prompts_for_chart(session, tenant_id, chart_id)`.
  2. Call `icd10_service.persist_prompts(session, prompts, user_id=user_id)`.
  3. Commit and return
     `{ "suggestions": [icd10_service.serialize(r) for r in persisted] }`.
- Audit: emitted by the service as `icd10.prompts_generated`.

### `POST /charts/{chart_id}/icd10/{suggestion_id}/acknowledge`

- Body (JSON):
  - `selected_code` (string or `null`) — `null` means the provider
    explicitly rejected the prompt; non-empty string means the
    provider chose that code as their response.
- Behavior:
  1. Call `icd10_service.acknowledge(session, tenant_id, chart_id,
     user_id, suggestion_id, selected_code_or_null=body["selected_code"])`.
  2. Commit and return `icd10_service.serialize(row)`.
- Audit: emitted by the service as `icd10.acknowledged` with the
  selected code (or `null`) in `detail_json`.

Errors:
- `LookupError` from `acknowledge` -> HTTP 404.
- `ValueError` from `persist_prompts` (provider_selected_code preset)
  -> HTTP 400.

---

## 3. `_load_workspace` injection

In `chart_workspace_service.py` (owned by another agent), the
coordinator should inject the ICD-10 documentation prompt list into
the workspace payload under a new key:

```python
# inside _load_workspace (coordinator edits this file, not us)
from epcr_app.services import icd10_service as _icd10
...
workspace["icd10Suggestions"] = [
    _icd10.serialize(r)
    for r in await _icd10.list_for_chart(session, tenant_id, chart_id)
]
workspace["icd10SpecificityScore"] = _icd10.specificity_score(
    await _icd10.list_for_chart(session, tenant_id, chart_id)
)
```

The injection is read-only; `_load_workspace` must not call
`generate_prompts_for_chart` (generation is an explicit user action).

---

## 4. Frontend types (`src/lib/epcr-clinical.ts`)

The coordinator extends the client types and helpers (this agent does
not touch the file). Recommended additions:

```ts
export type Icd10PromptKind =
  | "laterality"
  | "body_region"
  | "encounter_context"
  | "mechanism"
  | "specificity"
  | "symptom_vs_diagnosis";

export interface Icd10CandidateCode {
  code: string;
  description: string;
}

export interface Icd10DocumentationSuggestion {
  id: string;
  chartId: string;
  complaintText: string | null;
  promptKind: Icd10PromptKind;
  promptText: string;
  candidateCodes: Icd10CandidateCode[];
  providerAcknowledged: boolean;
  providerSelectedCode: string | null;
  providerSelectedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export function icd10SpecificityScore(
  suggestions: Icd10DocumentationSuggestion[],
): number {
  if (suggestions.length === 0) return 0;
  return (
    suggestions.filter((s) => s.providerAcknowledged).length /
    suggestions.length
  );
}

// IMPORTANT: never auto-bind candidateCodes to the chart's diagnosis.
// The provider must explicitly call POST .../icd10/{id}/acknowledge.
```

---

## 5. Audit actions emitted

| Action                      | Emitted by             | `detail_json` keys                                         |
| --------------------------- | ---------------------- | ---------------------------------------------------------- |
| `icd10.prompts_generated`   | `persist_prompts`      | `count`, `prompt_kinds`, `suggestion_ids`                  |
| `icd10.acknowledged`        | `acknowledge`          | `suggestion_id`, `prompt_kind`, `selected_code` (nullable) |

---

## 6. Collision boundary (re-stated)

This agent owns ONLY:

- `backend/epcr_app/services/icd10_service.py`
- `backend/tests/test_icd10_*.py`
- `backend/migrations/versions/051_add_icd10_suggestion.py`
- append-only addition to `backend/epcr_app/models.py`
  (`EpcrIcd10DocumentationSuggestion`)
- this handoff file

This agent did NOT modify:
- `chart_workspace_service.py`
- `src/lib/epcr-clinical.ts`
- alembic head merger
- TAC files

The migration uses `down_revision="043"` per the task spec; the
coordinator is responsible for merging it with any sibling heads
introduced by parallel pillar agents.
