# NEMSIS CTA agent directive

Objective:
Make the Adaptix ePCR/export path pass NEMSIS CTA Receive and Process testing using the uploaded CTA package as the active reference set and the official NEMSIS XSD/Schematron assets as the only validation authority.

Hard rules:
1. Do not invent or modify XSDs.
2. Do not hand-author final XML outside the export pipeline.
3. Do not use the incomplete submission shortcut as the source of truth.
4. Do not bypass XSD or Schematron failures.
5. Do not treat NOT_RECORDED sentinels as acceptable for elements that CTA scenarios actually require.

Authoritative runtime path:
Chart and mapping records -> readiness API -> export lifecycle service -> XML builder -> XSD validation -> Schematron validation -> artifact persistence -> artifact retrieval -> CTA submission.

Required code source of truth:
- backend/epcr_app/services_export.py
- backend/epcr_app/api_export.py
- backend/epcr_app/api_nemsis.py
- backend/epcr_app/nemsis_xml_builder.py
- backend/epcr_app/nemsis_xsd_validator.py

Mandatory corrections:
1. Lock all test generation to POST /api/v1/epcr/nemsis/export-generate.
2. Add GET /api/v1/epcr/nemsis/export/{export_id}/artifact.
3. Make artifact retrieval return raw XML bytes and checksum.
4. Remove any harness assumptions that charts can be created with vitals in create-chart.
5. Create chart with the live create contract, then populate chart fields and explicit NEMSIS mappings, then export.
6. Ensure validation is deterministic:
   - xsd_valid
   - schematron_valid
   - errors
   - warnings
   - checksum_sha256
   - validator_asset_version
7. Run XSD validation before Schematron validation.
8. Fail export if either validator fails.
9. Persist export attempt state and audit event for every transition.
10. Use the uploaded CTA package as the active scenario source:
   - 2025-DEM-1_v351.html
   - 2025-EMS-1-Allergy_v351.html
   - 2025-EMS-2-HeatStroke_v351.html
   - 2025-EMS-3-PediatricAsthma_v351.html
   - 2025-EMS-4-ArmTrauma_v351.html
   - 2025-EMS-5-MentalHealthCrisis_v351.html
   - 2025-STATE-1_v351.html
   - 2025-STATE-1_v351.xml

StateDataSet XML requirements from uploaded reference:
- Root element: StateDataSet
- Default namespace: http://www.nemsis.org
- xsi namespace: http://www.w3.org/2001/XMLSchema-instance
- schemaLocation must point at StateDataSet_v3.xsd from the official NEMSIS schema bundle used for the test run
- required attributes:
  - timestamp
  - effectiveDate
- required sections visible in uploaded reference:
  - sState
  - seCustomConfiguration
  - sdCustomConfiguration
  - sSoftware
  - sElement

Implementation requirements:
A. XML builder
- Build XML in the exact NEMSIS order required by the schema.
- Serialize UTF-8 with XML declaration.
- Use the active official schema bundle for the run, not a custom schema.
- Use official NEMSIS codes only.
- Only use NOT_RECORDED when the scenario permits absence.

B. Validator
- Accept xml_bytes.
- Validate against the official StateDataSet_v3.xsd and imported schemas from the same bundle.
- Validate against the official national Schematron files for the same bundle version.
- Return structured results and block on failure.

C. Artifact handling
- Save XML artifact with file name, MIME type, size, storage key, checksum.
- Allow direct retrieval for diffing against CTA references.

D. Harness alignment
- Create chart through the actual create endpoint.
- Populate mappings through supported APIs.
- Trigger export through export-generate.
- Retrieve artifact through the new artifact endpoint.
- Validate artifact.
- Diff artifact against CTA reference shape.

E. Diff rules for CTA
The agent must compare generated XML to the CTA reference for:
- root element name
- namespace
- schemaLocation
- element ordering
- cardinality
- presence of mandatory sections
- code-system usage
- custom element structure
Allow differences only where the scenario itself requires different patient/event values.

F. Submission readiness
A scenario is ready for CTA submission only when:
- export lifecycle status is generation_succeeded
- checksum exists
- XSD passed
- Schematron passed
- diff against CTA structure has no structural deviations

Stop conditions:
- Any schema failure
- Any Schematron failure
- Any missing required section
- Any mismatch between harness request body and live API contract
- Any export artifact path that does not resolve to the generated XML

Definition of done:
- Every uploaded CTA scenario can be executed through the live export path
- Each generated XML artifact validates
- StateDataSet artifact matches CTA structural expectations
- The system exposes artifact retrieval and audit trail end to end
