# NEMSIS CTA agent directive

NEMSIS CTA gravity-level agent directive

Objective

Deliver a fully compliant, production-grade NEMSIS CTA Receive and Process implementation through the live Adaptix export path only. The system must generate, validate, persist, retrieve, and prove authoritative StateDataSet artifacts using the uploaded CTA package as the active scenario reference set and the official NEMSIS XSD and Schematron assets as the only validation authority.

Operating standard

This work is gravity-level platform work. The implementation must be complete, deterministic, clean, and production-safe. No temporary logic, no partial behaviors, no fallback shortcuts, no test-only XML paths, no bypasses around validation, no schema invention, no synthetic endpoint behavior, and no hand-authored final XML outside the live export pipeline are allowed.

Non-negotiable rules

1. Use only the official NEMSIS schema bundle and official Schematron assets for the active bundle version under test.
2. Do not invent, modify, patch, trim, or override XSDs, imports, or Schematron files.
3. Do not hand-author final XML outside the live export pipeline.
4. Do not use incomplete-submission paths, shortcut exports, mock payloads, or scenario-only generators as the source of truth.
5. Do not bypass XSD validation failures.
6. Do not bypass Schematron validation failures.
7. Do not treat NOT_RECORDED sentinels as acceptable where the CTA scenario requires actual values.
8. Do not emit structurally valid but semantically noncompliant XML.
9. Do not ship partial compliance, best-effort compliance, warning-only compliance, or patch-layer compliance.
10. Every exported artifact must be generated from live chart data and explicit NEMSIS mappings through supported endpoints and services only.

Authoritative runtime path

Chart creation and updates
then mapping creation and updates
then readiness evaluation
then export lifecycle generation
then XML build
then XSD validation
then Schematron validation
then artifact persistence
then artifact retrieval
then CTA submission readiness decision

The authoritative flow is:

Chart and mapping records -> readiness API -> export lifecycle service -> XML builder -> XSD validation -> Schematron validation -> artifact persistence -> artifact retrieval -> CTA submission readiness

Authoritative code source of truth

The following files are the required implementation source of truth:

- backend/epcr_app/services_export.py
- backend/epcr_app/api_export.py
- backend/epcr_app/api_nemsis.py
- backend/epcr_app/nemsis_xml_builder.py
- backend/epcr_app/nemsis_xsd_validator.py

No alternate source of truth is permitted for final export generation or validation behavior.

Active CTA reference set

Use the uploaded CTA package as the active scenario reference set for all execution, structural comparison, and submission-readiness decisions:

- 2025-DEM-1_v351.html
- 2025-EMS-1-Allergy_v351.html
- 2025-EMS-2-HeatStroke_v351.html
- 2025-EMS-3-PediatricAsthma_v351.html
- 2025-EMS-4-ArmTrauma_v351.html
- 2025-EMS-5-MentalHealthCrisis_v351.html
- 2025-STATE-1_v351.html
- 2025-STATE-1_v351.xml

These uploaded references are the active scenario truth for CTA structure and required content expectations. They are not optional, not advisory, and not secondary to older scenario harnesses.

Required endpoint contract

The live endpoint contract must be authoritative and complete.

Generation endpoint

All export generation must be locked to:

POST /api/v1/epcr/nemsis/export-generate

Artifact retrieval endpoint

The platform must expose:

GET /api/v1/epcr/nemsis/export/{export_id}/artifact

Artifact retrieval response requirements

The artifact endpoint must return the generated XML artifact itself, not metadata only. It must provide:

- raw XML bytes as the response body
- correct XML MIME type
- file name
- content size
- checksum_sha256
- storage identifier or storage key when persisted
- direct traceability to the exact generated export record

No scenario-specific generate endpoint, no scenario shortcut, and no alternate artifact path may be treated as authoritative.

Chart and mapping requirements

1. Charts must be created through the actual live create contract only.
2. The harness must not assume vitals or any unsupported fields can be injected into create-chart if the live contract does not accept them.
3. After creation, chart fields must be populated through supported update endpoints only.
4. NEMSIS mappings must be created and updated through supported mapping APIs only.
5. Export generation must consume live persisted chart state and persisted explicit mapping state.
6. The export path must never depend on hidden defaults, test seeding shortcuts, or side-loaded scenario state.

StateDataSet output requirements

The generated document for CTA must be a StateDataSet artifact that is fully aligned to the active official NEMSIS bundle and the uploaded CTA reference structure.

Required root and namespace contract

- root element must be StateDataSet
- default namespace must be http://www.nemsis.org
- xsi namespace must be http://www.w3.org/2001/XMLSchema-instance
- schemaLocation must point to StateDataSet_v3.xsd from the official NEMSIS schema bundle used for the active run

Required root attributes

- timestamp
- effectiveDate

Required visible sections

The generated XML must contain the required top-level visible sections present in the uploaded CTA reference:

- sState
- seCustomConfiguration
- sdCustomConfiguration
- sSoftware
- sElement

XML builder requirements

The XML builder must satisfy all of the following:

1. Build XML in the exact order required by the official schema.
2. Serialize as UTF-8 with XML declaration.
3. Use the active official schema bundle for the run, never a custom schema.
4. Use official NEMSIS codes only.
5. Emit exact structure required by StateDataSet, not EMSDataSet or any alternate export shape.
6. Emit required sections, required attributes, correct namespace declarations, and correct schemaLocation.
7. Only use NOT_RECORDED when the specific CTA scenario and NEMSIS rules permit absence.
8. Never use placeholders where the scenario requires real values.
9. Never reorder elements in a way that differs from schema-required sequence.
10. Never produce XML that is structurally shaped for convenience instead of compliance.

Mapping requirements

Mappings must be explicit, deterministic, and authoritative.

1. Every mapped NEMSIS element must originate from live persisted chart data or approved structured extraction data through supported mapping logic.
2. Mapping records must identify the NEMSIS element, source field, source value, mapped value, mapping status, and confidence or review state where applicable.
3. Required CTA elements must resolve to valid NEMSIS-compliant values.
4. No fabricated mappings are permitted.
5. No unreviewed placeholder mappings are permitted for CTA-required elements.
6. Mapping logic must produce exportable values that are valid for both XSD and Schematron evaluation.

Validation requirements

Validation must be deterministic, structured, and blocking.

Validator input

- xml_bytes

Validation order

1. XSD validation
2. Schematron validation

If XSD fails, export fails.
If Schematron fails, export fails.
If either validator fails, artifact generation does not succeed.

Required validation result structure

Every validation result must include:

- xsd_valid
- schematron_valid
- errors
- warnings
- checksum_sha256
- validator_asset_version

Validation authority rules

1. Official StateDataSet_v3.xsd and its imported schemas from the same official bundle are the only XSD authority.
2. Official national Schematron files for the same bundle version are the only Schematron authority.
3. Validation behavior must be reproducible for the same inputs and same asset bundle.
4. No validator bypass, fallback acceptance, partial pass, or warning-only pass is allowed.

Export lifecycle and persistence requirements

Every export attempt must be lifecycle-managed and auditable end to end.

Required lifecycle behavior

1. Create an export attempt record for every generation request.
2. Persist every state transition.
3. Persist validator outputs.
4. Persist artifact metadata.
5. Persist audit events for every transition.
6. Persist failure details when generation or validation fails.
7. Persist success details only after both validations pass.

Required persisted export data

- export identifier
- chart identifier
- tenant identifier
- lifecycle status
- artifact file name
- MIME type
- size in bytes
- storage key
- checksum_sha256
- validator_asset_version
- xsd_valid
- schematron_valid
- warnings
- errors
- created timestamp
- updated timestamp
- audit event trail

Artifact handling requirements

1. Save the exact generated XML artifact.
2. Save the exact checksum for that artifact.
3. Make the saved artifact retrievable without transformation.
4. Artifact retrieval must resolve to the exact XML bytes generated by the export pipeline.
5. Returned bytes, metadata, and checksum must correspond to the persisted artifact record exactly.
6. The artifact must be directly usable for diffing against CTA references.

Harness requirements

The CTA harness must align to the live system, not the other way around.

Harness execution rules

1. Create the chart through the live create endpoint only.
2. Populate chart data through supported update endpoints only.
3. Populate explicit NEMSIS mappings through supported mapping endpoints only.
4. Trigger export through POST /api/v1/epcr/nemsis/export-generate only.
5. Retrieve the generated artifact through GET /api/v1/epcr/nemsis/export/{export_id}/artifact only.
6. Validate the retrieved artifact using the live validator result.
7. Diff the retrieved artifact against the CTA reference structure.
8. Reject any harness request body that does not match the live API contract exactly.
9. Do not assume create-chart accepts vitals or any unsupported payload shape.
10. Do not seed around the live API contract.

CTA diff requirements

The generated XML must be compared against the CTA reference for all structural compliance dimensions below:

- root element name
- namespace
- schemaLocation
- element ordering
- cardinality
- presence of mandatory sections
- code-system usage
- custom element structure

Allowed differences

Differences are allowed only where the CTA scenario itself requires different patient or event values. Structural deviations are not allowed.

Submission readiness requirements

A scenario is ready for CTA submission only when all of the following are true:

1. export lifecycle status is generation_succeeded
2. checksum exists
3. xsd_valid is true
4. schematron_valid is true
5. diff against CTA structure has no structural deviations
6. artifact retrieval resolves to the exact generated XML
7. required mappings are present and valid for the scenario

Stop conditions

Immediate stop is required on any of the following:

- any XSD failure
- any Schematron failure
- any missing required section
- any mismatch between harness request body and live API contract
- any export artifact path that does not resolve to the generated XML
- any structurally invalid StateDataSet output
- any missing required mapping for CTA-required elements
- any use of unauthorized placeholder or sentinel values where real data is required

Implementation quality standard

This directive requires clean-code completion, not patch completion.

Required quality bar

1. No partial implementations
2. No temporary adapters
3. No compatibility shims as final behavior
4. No dead code
5. No duplicate validation paths
6. No scenario-specific hacks in the production export pipeline
7. No ambiguous endpoint ownership
8. No silent fallback behavior
9. No hidden mutation of schemas or validation assets
10. No mixed source of truth for generation, validation, artifact persistence, or retrieval

Definition of done

The implementation is done only when all of the following are true:

1. Every uploaded CTA scenario can be executed through the live export path.
2. Each generated XML artifact is a StateDataSet artifact.
3. Each generated XML artifact validates successfully against the official XSD assets.
4. Each generated XML artifact validates successfully against the official Schematron assets.
5. Each generated XML artifact matches CTA structural expectations with no structural deviations.
6. The system exposes export generation, artifact retrieval, and audit trail end to end.
7. The system uses live mappings, live endpoints, and authoritative validation only.
8. The result is clean, production-grade, fully NEMSIS-compliant code with no errors, no partials, and no patches.