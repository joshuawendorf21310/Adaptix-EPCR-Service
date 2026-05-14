# Coordinator Handoff — SentenceEvidenceService (AI-evidence-link pillar)

This pillar wires the existing `ai_narrative_service.py` output into a
deterministic per-sentence evidence-link layer backed by two new tables.
The wrapping service performs **no LLM calls** (enforced by
`tests/test_sentence_evidence_no_ai.py`).

Status: backend models, migration, service, and tests landed. **No
commits have been made.** Files added or extended:

- `backend/migrations/versions/047_add_sentence_evidence.py`
  (`down_revision='043'`, reversible)
- `backend/epcr_app/models.py` (append-only): added
  `EpcrSentenceEvidence`, `EpcrAiAuditEvent`
- `backend/epcr_app/models/__init__.py` (re-export shim): added the two
  symbols above (additive only)
- `backend/epcr_app/services/sentence_evidence_service.py`
- `backend/tests/test_sentence_evidence_model.py`
- `backend/tests/test_sentence_evidence_service.py`
- `backend/tests/test_sentence_evidence_no_ai.py`

Alembic upgrade/downgrade verified on an isolated SQLite DB; all 12
tests pass.

---

## 1. Capability flips (coordinator service registry)

Add or flip the following capability entry in the chart workspace
capability table (the structure used by `_load_workspace` /
`chart_workspace_service`):

```json
{
  "sentence_evidence": {
    "capability": "live",
    "source": "sentence_evidence_service"
  }
}
```

No other capability rows need to change. The pillar is read-and-mutate
only on its own tables and never blocks other workspace sections.

---

## 2. New endpoints to register (coordinator API layer)

All three endpoints are tenant- and chart-scoped; the coordinator owns
auth, tenant resolution, and `session.commit()`. The service never
commits.

| Method | Path                                                                                   | Service entry-point                                  |
|-------:|----------------------------------------------------------------------------------------|------------------------------------------------------|
| GET    | `/api/v1/epcr/charts/{chart_id}/narrative/{narrative_id}/evidence`                     | `SentenceEvidenceService.list_for_chart`             |
| POST   | `/api/v1/epcr/charts/{chart_id}/narrative/{narrative_id}/evidence/{evidence_id}/confirm` | `SentenceEvidenceService.confirm`                    |
| POST   | `/api/v1/epcr/charts/{chart_id}/narrative/{narrative_id}/evidence/{evidence_id}/unlink`  | `SentenceEvidenceService.unlink`                     |

Request/response shape:

- `GET …/evidence` → list of `EpcrSentenceEvidence` rows ordered by
  `sentence_index`. Each row includes `id, sentence_index,
  sentence_text, evidence_kind, evidence_ref_id, confidence,
  provider_confirmed`.
- `POST …/confirm` → returns the updated row with
  `provider_confirmed=true`.
- `POST …/unlink` → returns the updated row downgraded to
  `evidence_kind="provider_note"`, `evidence_ref_id=null`,
  `provider_confirmed=false`, `confidence=0.00`.

Both write endpoints emit an `EpcrAiAuditEvent` (`sentence.evidence_added`
with `confirmed: true`, or `sentence.evidence_unlinked`).

The mapping step (`map_sentences` + `persist`) is intentionally not
exposed yet as a public endpoint; it should be invoked by the existing
narrative-generation hook in the coordinator once the narrative text is
available. Suggested integration point: immediately after the existing
`AdaptixNarrativeService.generate_narrative` call, the coordinator
should:

```python
rows = SentenceEvidenceService.map_sentences(
    session,
    tenant_id=tenant_id,
    chart_id=chart_id,
    narrative_id=narrative.generation_id,
    narrative_text=narrative.narrative_text,
    workspace=workspace,  # the same dict built by _load_workspace
)
SentenceEvidenceService.persist(session, rows, user_id=actor_id)
await session.commit()
```

---

## 3. `_load_workspace` injection

In the coordinator's workspace builder (currently
`chart_workspace_service.py::_load_workspace` — **do not edit from this
pillar**), append after the existing structured sections are loaded:

```python
workspace["sentence_evidence"] = await SentenceEvidenceService.list_for_chart(
    session, tenant_id=tenant_id, chart_id=chart_id
)
```

This makes the (already-persisted) sentence-evidence rows available to
every workspace consumer with no additional query. If only the rows for
the latest narrative are desired, pass `narrative_id=latest_id` to
`list_for_chart`.

The structured-evidence shape the linker expects from `workspace` (when
`map_sentences` is called) is the same dict the coordinator already
builds. Recognised top-level keys:

- `vitals` — iterable of `Vitals` rows
- `medications` — iterable of `MedicationAdministration` rows
- `anatomical_findings` — iterable of `EpcrAnatomicalFinding` rows
- `treatments` — iterable of any row with `name`/`procedure_name`/
  `intervention_name` and `id`
- `procedures` — same shape as `treatments`; emitted as
  `evidence_kind="procedure"`
- `fields` — flat `dict[str, Any]` of structured chart fields (chief
  complaint, primary impression, etc.)

Unknown keys are ignored.

---

## 4. Web-app contract (`src/lib/epcr-clinical.ts`)

The web-app (`Adaptix-Web-App`) needs new TypeScript types and helpers.
Suggested additions to `src/lib/epcr-clinical.ts`:

```ts
export type EpcrEvidenceKind =
  | "field"
  | "vital"
  | "treatment"
  | "medication"
  | "procedure"
  | "anatomical_finding"
  | "prior_chart"
  | "prior_ecg"
  | "ocr"
  | "map"
  | "protocol"
  | "provider_note";

export type EpcrAiAuditEventKind =
  | "narrative.draft"
  | "narrative.accepted"
  | "narrative.rejected"
  | "sentence.evidence_added"
  | "sentence.evidence_unlinked"
  | "phrase.inserted"
  | "phrase.edited"
  | "phrase.removed";

export interface EpcrSentenceEvidence {
  id: string;
  tenantId: string;
  chartId: string;
  narrativeId: string | null;
  sentenceIndex: number;
  sentenceText: string;
  evidenceKind: EpcrEvidenceKind;
  evidenceRefId: string | null;
  confidence: number;          // 0.00–0.99
  providerConfirmed: boolean;
  createdAt: string;           // ISO-8601 UTC
  updatedAt: string;           // ISO-8601 UTC
}

export interface EpcrAiAuditEvent {
  id: string;
  tenantId: string;
  chartId: string;
  eventKind: EpcrAiAuditEventKind;
  userId: string | null;
  payload: Record<string, unknown> | null;
  performedAt: string;
}

export async function listSentenceEvidence(
  chartId: string,
  narrativeId: string,
): Promise<EpcrSentenceEvidence[]>;

export async function confirmSentenceEvidence(
  chartId: string,
  evidenceId: string,
): Promise<EpcrSentenceEvidence>;

export async function unlinkSentenceEvidence(
  chartId: string,
  evidenceId: string,
): Promise<EpcrSentenceEvidence>;
```

These helpers should hit the three endpoints defined in section 2 and
return camelCase-mapped versions of the backend rows. The web app must
**not** call `map_sentences` directly — that step is a backend
side-effect of narrative generation.

---

## 5. Collision-rule attestation

This pillar touched **only** the files listed in its scope:

- Owned: migration 047, `sentence_evidence_service.py`, three
  `test_sentence_evidence_*` files, this handoff.
- Append-only: `models.py` (two new classes appended) and
  `models/__init__.py` re-export shim (two new symbols appended).
- Read-only references: `ai_narrative_service.py` was read, never
  modified. `chart_workspace_service.py`, `ai_clinical_engine.py`, the
  TAC files, and `src/lib/epcr-clinical.ts` were **not** edited — all
  changes there are deferred to the coordinator and web-app teams per
  the sections above.

No commits have been created.
