# Coordinator Handoff — ECustomFieldService Pillar

This pillar is delivered self-contained. It owns:

- Models `EpcrECustomFieldDefinition` and `EpcrECustomFieldValue`
  (appended at end of `backend/epcr_app/models.py`).
- Migration `backend/migrations/versions/045_add_ecustom_field.py`
  (`down_revision='043'` — see note 5 below).
- Service `backend/epcr_app/services/ecustom_field_service.py` exposing
  `ECustomFieldService` and `validate_against_definition`.
- Validator `backend/epcr_app/services/ecustom_field_validation.py`
  exposing `validate_field_value` and `ValidationError`.
- Tests `backend/tests/test_ecustom_field_{model,service,validation}.py`.

The coordinator must perform the following integration edits in a
follow-up patch. None of these were performed here — they touch shared
or out-of-scope files that the pillar contract forbids.

## 1. `chart_workspace_service.py` — capability dict

Replace the existing `"ecustom"` entry (currently
`"unavailable"`) with the live wiring:

```python
"ecustom": {"capability": "live", "source": "ecustom_field_service"},
```

## 2. `chart_workspace_service.py` — `_load_workspace`

Inject the ECustom payload into the workspace mapping. After the
existing section loaders, add:

```python
from epcr_app.services.ecustom_field_service import ECustomFieldService

defs = await ECustomFieldService.list_definitions(
    session, tenant_id, agency_id
)
values = await ECustomFieldService.list_values_for_chart(
    session, tenant_id, chart_id
)
workspace["ecustom"] = {
    "definitions": [
        ECustomFieldService.serialize_definition(d) for d in defs
    ],
    "values": [
        ECustomFieldService.serialize_value(v) for v in values
    ],
}
```

## 3. `chart_workspace_service.py` — `update_workspace_section`

When `section == "nemsis"` or `section == "ecustom"` and the payload
carries `ecustom_values` (mapping or list), route to the service:

```python
if section in ("nemsis", "ecustom") and "ecustom_values" in payload:
    await ECustomFieldService.replace_for_chart(
        session,
        tenant_id=tenant_id,
        chart_id=chart_id,
        user_id=user_id,
        agency_id=agency_id,
        values=payload["ecustom_values"],
    )
```

`ECustomFieldService.replace_for_chart` aggregates validation errors and
raises `epcr_app.services.ecustom_field_validation.ValidationError`. The
API layer should translate that to a 400 with the structured
`errors: list[{field, message}]` body.

## 4. `src/lib/epcr-clinical.ts` — frontend types + helper

Add (in `Adaptix-EPCR-Service/src/lib/epcr-clinical.ts`):

```ts
export type ECustomDataType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'date'
  | 'select'
  | 'multi_select';

export interface EpcrECustomFieldDefinition {
  id: string;
  tenantId: string;
  agencyId: string;
  fieldKey: string;
  label: string;
  dataType: ECustomDataType;
  allowedValues: unknown[] | null;
  required: boolean;
  conditionalRule: Record<string, unknown> | null;
  nemsisRelationship: string | null;
  stateProfile: string | null;
  version: number;
  retired: boolean;
}

export interface EpcrECustomFieldValue {
  id: string;
  chartId: string;
  fieldDefinitionId: string;
  value: unknown;
  validationResult: { ok: boolean; errors: Array<{field: string; message: string}> } | null;
}

export async function saveECustomValues(
  chartId: string,
  values: Record<string, unknown>,
): Promise<EpcrECustomFieldValue[]> {
  const resp = await fetch(`/api/epcr/charts/${chartId}/workspace/ecustom`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ecustom_values: values }),
  });
  if (!resp.ok) {
    throw new Error(`saveECustomValues failed: ${resp.status}`);
  }
  return resp.json();
}
```

## 5. Migration head

Migration `045` declares `down_revision = '043'`. If another pillar in
the same coordination cycle also targets `043` as its parent, the
coordinator must renumber to keep a single linear head. The migration is
otherwise drift-safe (`if_not_exists=True` on `create_table`).

## Forbidden files (untouched, per contract)

- `chart_workspace_service.py`
- `src/lib/epcr-clinical.ts`
- alembic head pointer
- any TAC file
- `BodyAssessmentMap.tsx`
- `TacExaminerDashboard.tsx`

## Test evidence

See the pytest run captured in the pillar delivery report.
