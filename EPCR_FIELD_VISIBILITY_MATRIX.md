# EPCR Field Visibility Matrix

## Inventory

- EPCR frontend route: `/epcr` now resolves to the real chart workspace via `Adaptix-Web-App/app/epcr/page.tsx` re-exporting `src/app/clinical/epcr/page.tsx`.
- EPCR API client file: `Adaptix-Web-App/src/lib/epcr-clinical.ts`
- EPCR form components: `Adaptix-Web-App/src/components/clinical/charting/EpcrChartWorkspace.tsx` and section editors under `src/components/clinical/charting/sections/`
- EPCR field sections currently rendered in the left rail: patient, incident, response, crew, scene, complaint, history, allergies, home_medications, assessment, vitals, treatment, procedures, medications_administered, narrative, disposition, destination, attachments, signatures, nemsis, export
- Newly exposed truth-only placeholder sections: crew, allergies, home_medications, procedures, medications_administered, destination, attachments
- Auth/session source: `Adaptix-Web-App/src/middleware.ts`, `src/lib/auth-store.ts`, `src/providers/AuthProvider.tsx`
- Save/reload behavior: `performSectionSave()` in `src/components/clinical/charting/sectionSaveHelpers.ts` calling chart-workspace PATCH routes from `src/lib/epcr-clinical.ts`, followed by workspace reload

## Current Verdict

- EPCR FIELD COMPLETENESS: NOT PROVEN
- EPCR FIELD VISIBILITY: PARTIAL
- CORE CHART WORKSPACE: PRESENT
- FULL UI FIELD COVERAGE: NOT CONFIRMED
- UNMAPPED SECTIONS EXIST

## Status meaning in this matrix

- `BLOCKED_BY_AUTH_PROOF`: code path exists, but authenticated browser save/reload proof is still missing
- `PASS_VISIBLE_READONLY`: field or state is visibly rendered and intentionally read-only
- `FIELD_NOT_MAPPED`: UI explicitly labels the field as not mapped or unavailable
- `BACKEND_ONLY_NOT_VISIBLE`: backend section exists or is disclosed in backend payloads, but no dedicated visible UI section exists today
- `FRONTEND_ONLY_NOT_BACKED`: UI renders an input, but the current backend route contract does not persist that field as rendered

## Matrix source

The machine-readable source of truth for this audit is in `epcr_field_visibility_matrix.json` beside this file.

## Gravity-level answer

Not all ePCR fields are proven present and visible. Core sections exist, but several sections are explicitly unmapped, and the visible UI evidence only shows a subset of fields plus truthful readiness/export/submission state. The current matrix is intentionally conservative: it does not claim browser persistence or production visibility unless that proof exists.