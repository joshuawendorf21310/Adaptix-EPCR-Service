# CTA EMS Collect Data blocker evidence — 2026-04-23

## Scope

This report preserves the current proof state for the locked vertical slice:

- `2025-EMS-1-Allergy_v351`
- `eResponse.04 = 351-241102-005-1`
- flow: EPCR -> NEMSIS 3.5.1 XML -> XSD -> Schematron -> CTA submission

User directive in force:

> Do not keep rewriting local EPCR XML or SOAP code unless CTA returns a new validation error. The current evidence shows DEM passes and untouched official EMS cases return `-16`, so the remaining action is CTA portal/configuration resolution for EMS Collect Data case recognition. Preserve all artifacts, responses, and regression results as evidence.

## Local validation proof

The generated Allergy EMS artifact is locally green:

- XSD: `PASS`
- Schematron: `PASS`
- official structural fidelity: `PASS`
- tactical key: `351-241102-005-1`
- placeholder cleanup: `PASS`
- repeated-group preservation: `PASS`

## Live CTA proof already established in this session

### Proven good

- Official DEM submit using schema `62`: `statusCode = 1`
- Official DEM submit using schema `62` with password variant `Addyson123456!`: `statusCode = 1`
- Username `fusion_quant2` with password `Addyson123456!` on official DEM returns `statusCode = 1`
- CTA authentication and organization values are valid because earlier bad-org behavior returned `-3`, while current live EMS submissions authenticate and return `-16`

### Proven invalid credentials

- Username `fusion_quant2` with password `Addyson12345!` on official DEM returns `statusCode = -1`
- Username `fusion_quant2` with password `Addyson21310%` on official DEM returns `statusCode = -1`
- Username `joshua.j.wendorf@fusionemsquantum.com` with password `Addyson12345!` on official DEM returns `statusCode = -1`
- Username `joshua.j.wendorf@fusionemsquantum.com` with password `Addyson123456!` on official DEM returns `statusCode = -1`
- CTA error message for all invalid combinations above: `Login credentials are invalid.`

### Proven blocker

- Untouched official EMS Allergy file using schema `61`: `statusCode = -16`
- Untouched official EMS Allergy file using username `fusion_quant2` and password `Addyson123456!`: `statusCode = -16`
- Untouched official EMS Allergy file using schema `61` with password variant `Addyson123456!`: `statusCode = -16`
- Untouched official EMS HeatStroke file using schema `61`: `statusCode = -16`
- DEM -> EMS submission sequence still results in EMS `-16`
- CTA response body for EMS Allergy contains:
  - `statusCode = -16`
  - `serverErrorMessage = Incorrect test case provided. Key data elements must match a test case.`
  - `xmlValidationErrorReport.totalErrorCount = 0`

### New portal/dashboard evidence provided by user

- Authenticated Okta dashboard HTML shows `Joshua Wendorf` signed in as `joshua.j.wendorf@fusionemsquantum.com`
- Dashboard contains a visible `NEMSIS CTA` application tile for that user
- Dashboard status table shows:
  - organization: `FusionEMSQuantum`
  - software capability: `Collect Data`
  - NEMSIS version: `3.5.1`
  - application received date: `02/11/2026`
  - status: `In Progress`
- Public fetches of the CTA and Tableau app URLs expose only the Okta sign-in shell; the provisioning signal comes from the authenticated dashboard HTML supplied by the user, not from a public endpoint

### Ticket-thread evidence provided by user

- NEMSIS support thread states Joshua's Okta user account is `joshua.j.wendorf@fusionemsquantum.com`
- Support states the CTA organization is `FusionEMSQuantum`
- Support states the 2025 required submissions are limited to:
  - `2025 - DEM 1`
  - `2025 - EMS 1 - Allergy`
  - `2025 - EMS 2 - Heat Stroke`
  - `2025 - EMS 3 - Pediatric Asthma`
  - `2025 - EMS 4 - Arm Trauma`
  - `2025 - EMS 5 - Mental Health Crisis`
- Support explicitly says the following are **not required** and can be ignored for this vendor cycle:
  - `2025 - DEM 2 - Critical Patch 1`
  - `2025 - EMS 6 - Critical Patch 1`
  - 2026 cases
- Support further states that portal submissions for the listed 2025 cases were already successful through the CTA portal UI
- Most importantly, Josh Nation states the vendor service account (VSA) for SOAP/test-case submission is `FusionEMSQuantum`, while the portal login to view results remains `joshua.j.wendorf@fusionemsquantum.com`

### Live contradiction to support-provided VSA username

- Live CTA test performed on `2026-04-23` using official DEM with:
  - username: `FusionEMSQuantum`
  - organization: `FusionEMSQuantum`
  - password: `Addyson123456!`
  - result: `statusCode = -1`, `Login credentials are invalid.`
- Follow-up auth matrix on the same day using username `FusionEMSQuantum` with both known password variants:
  - `Addyson12345!` -> `statusCode = -1`
  - `Addyson123456!` -> `statusCode = -1`
- This directly conflicts with the ticket guidance that `FusionEMSQuantum` is the active VSA credential for SOAP submissions
- Operationally, `fusion_quant2` remains the only username proven in live SOAP testing to authenticate for official DEM submissions

### User-directed single-identity auth check

Per latest user directive, runtime `.env` values were switched to:

- username: `FusionEMSQuantum`
- organization: `FusionEMSQuantum`
- password under test: `Addyson123456!`

One direct DEM auth check was then executed and returned:

- `statusCode = -1`
- `Login credentials are invalid.`

After that result, no alternate identities were retried in order to comply with the stop-on-auth-failure instruction.

### Follow-up password claim validation

User later explicitly stated the password is `Addyson12345!`.

Using the already-mandated identity:

- username: `FusionEMSQuantum`
- organization: `FusionEMSQuantum`
- password under test: `Addyson12345!`

One direct DEM auth check returned:

- `statusCode = -1`
- `Login credentials are invalid.`

This means both tested password variants now fail for `FusionEMSQuantum` in live SOAP auth:

- `Addyson123456!` -> invalid credentials
- `Addyson12345!` -> invalid credentials

### Additional official EMS case metadata supplied by user

- User provided another official-looking EMS case payload with:
  - `eRecord.01 = 2025-EMS-3-PediatricAsthma_v351-REC`
  - `eResponse.03 = 351-241140-004`
  - `eResponse.04 = 351-241140-004-1`
  - organization name in payload: `FusionEMSQuantum`
- This strengthens the interpretation that FusionEMS Quantum is operating against official EMS Collect Data vendor cases, but CTA enrollment/case activation is still not fully complete for live EMS recognition

### Additional observation

- State submit using schema `65` returned HTTP `500`

## Conclusion

The remaining blocker is not local XML generation, not local XSD conformance, not local Schematron conformance, and not SOAP authentication formatting.

The evidence currently supports this conclusion:

**CTA is not recognizing EMS Collect Data test-case key data for this account and organization, even when submitted from untouched official EMS reference cases.**

With the newly supplied dashboard status, the most likely explanation is now even narrower:

**FusionEMSQuantum has a Collect Data 3.5.1 CTA application on file, but the enrollment/provisioning remains `In Progress`, so EMS vendor-case recognition is not fully activated yet.**

There is now an additional identity-layer inconsistency to preserve:

**Support says the active SOAP VSA username is `FusionEMSQuantum`, but live CTA auth rejects that username with both known password variants.**

So the remaining problem space is now best described as a combination of:

1. incomplete or inconsistent CTA Collect Data provisioning / activation, and/or
2. mismatched or unpublished SOAP VSA credential state

That makes the next action a CTA portal/configuration or vendor-account case-activation resolution, not another local EPCR/XML/SOAP rewrite.

## Portal provisioning/contact details received

The following identity details were provided for the FusionEMS Quantum user/contact who may need CTA portal/account review:

- first name: `Joshua`
- last name: `Wendorf`
- Okta username: `joshua.j.wendorf@fusionemsquantum.com`
- primary email: `joshua.j.wendorf@fusionemsquantum.com`
- mobile phone: `71554066269`

Important interpretation:

- This identity is useful for CTA support/provisioning escalation.
- It should **not** replace the currently proven CTA login username in runtime configuration by itself.
- Live CTA auth tests in this session already proved `joshua.j.wendorf@fusionemsquantum.com` returns `statusCode = -1` with the tested password variants, while `fusion_quant2` successfully authenticates for DEM.

## Recommended CTA support ask

Provide CTA/NEMSIS support or portal administration with:

- organization: `FusionEMSQuantum`
- validated CTA login username already authenticating for DEM: `fusion_quant2`
- user/contact identity for provisioning review: `Joshua Wendorf <joshua.j.wendorf@fusionemsquantum.com>`
- evidence that untouched official EMS cases still return `-16`

Requested resolution:

1. confirm whether EMS Collect Data vendor test cases are assigned/activated for the `FusionEMSQuantum` organization
2. confirm whether the Fusion account is permitted for EMS schema `61` Collect Data testing
3. confirm whether `Joshua Wendorf` should be separately provisioned/mapped for CTA access, or whether `fusion_quant2` remains the expected CTA login identity
4. explain why the Collect Data 3.5.1 application still shows `In Progress` after the `02/11/2026` application received date, and what remaining step blocks EMS case recognition
5. reconcile the support statement that the SOAP VSA username is `FusionEMSQuantum` with live CTA results showing `FusionEMSQuantum` returns `Login credentials are invalid.` for both known password variants
6. confirm whether `fusion_quant2` is the still-active SOAP service credential despite support describing it as a different VSA name

## Preserved evidence files

### Generated artifact

- `artifact/generated/2025-EMS-1-Allergy_v351.xml`

### Local validation

- `artifact/validation/xsd-result.json`
- `artifact/validation/schematron-result.json`

### Fidelity proof

- `artifact/fidelity/official-diff.json`

### CTA request/response evidence

- `artifact/cta/2025-EMS-1-Allergy_v351-request.xml` *(sanitized: password redacted)*
- `artifact/cta/2025-EMS-1-Allergy_v351-response.xml`
- `artifact/cta/parsed-result.json` *(sanitized: password redacted)*
- `artifact/cta/CTA_PORTAL_SUPPORT_PAYLOAD_2026-04-23.md`

## Frozen interpretation

Unless CTA returns a new validation signal beyond the current `-16` business-rule response, local runtime XML and SOAP logic should be treated as frozen for this vertical slice.
