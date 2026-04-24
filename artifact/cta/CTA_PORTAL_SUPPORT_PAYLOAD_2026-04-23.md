# CTA portal support payload — 2026-04-23

This note packages the current vendor-account blocker into a support/provisioning-ready format for CTA/NEMSIS portal follow-up.

## Contact / identity details provided

- first name: `Joshua`
- last name: `Wendorf`
- Okta username: `joshua.j.wendorf@fusionemsquantum.com`
- primary email: `joshua.j.wendorf@fusionemsquantum.com`
- mobile phone: `71554066269`

## Organization under test

- organization: `FusionEMSQuantum`

## Dashboard evidence provided by user

- authenticated Okta dashboard shows `Joshua Wendorf <joshua.j.wendorf@fusionemsquantum.com>` with a visible `NEMSIS CTA` tile
- software capability row shows:
	- organization: `FusionEMSQuantum`
	- capability: `Collect Data`
	- NEMSIS version: `3.5.1`
	- application received: `02/11/2026`
	- status: `In Progress`

## Ticket-thread statements from NEMSIS support

- user account for portal access: `joshua.j.wendorf@fusionemsquantum.com`
- organization: `FusionEMSQuantum`
- support statement: vendor service account used to submit test cases is `FusionEMSQuantum`
- support statement: 2025 required cases are only `DEM 1` and `EMS 1-5`
- support statement: critical patch and 2026 cases are not required for this testing cycle
- support statement: the listed 2025 portal submissions already exist and can be reviewed for feedback

## Proven current CTA behavior

### Authenticated successfully

- CTA username `fusion_quant2` authenticates successfully for official DEM submissions
- DEM with schema `62` returns `statusCode = 1`

### Did not authenticate with tested password variants

- `joshua.j.wendorf@fusionemsquantum.com` returned `statusCode = -1` for the tested CTA password variants already exercised in this session

### Remaining blocker

- untouched official EMS files still return `statusCode = -16`
- message: `Incorrect test case provided. Key data elements must match a test case.`
- `xmlValidationErrorReport.totalErrorCount = 0`

## Interpretation

The current problem is consistent with CTA-side EMS Collect Data case-recognition, activation, or account-to-organization provisioning — not local XML/XSD/Schematron generation.

The newly supplied dashboard state makes the leading explanation stronger: the FusionEMS Quantum Collect Data enrollment appears to exist, but is still not fully activated because the application remains `In Progress`.

However, there is now a second contradiction to resolve: support says the SOAP submission VSA username is `FusionEMSQuantum`, but live DEM auth on `2026-04-23` returns `Login credentials are invalid.` for that username with both tested password variants.

At the same time, `fusion_quant2` remains the only username proven to authenticate live for SOAP DEM submissions.

Most recent directive-driven validation:

- local runtime env values were switched to `FusionEMSQuantum` for CTA/TAC/SOAP username fields
- one direct DEM auth check was executed using:
	- username: `FusionEMSQuantum`
	- organization: `FusionEMSQuantum`
	- password: `Addyson123456!`
- result: `statusCode = -1`, `Login credentials are invalid.`
- no alternate identities were retried after that failure

Follow-up password validation:

- user later supplied `Addyson12345!` as the password to use
- one direct DEM auth check was executed with:
	- username: `FusionEMSQuantum`
	- organization: `FusionEMSQuantum`
	- password: `Addyson12345!`
- result: `statusCode = -1`, `Login credentials are invalid.`

So, for the support-stated VSA username `FusionEMSQuantum`, both known password variants currently fail in live SOAP auth.

## Additional official EMS case metadata provided by user

- case identifier: `2025-EMS-3-PediatricAsthma_v351-REC`
- tactical case key: `351-241140-004-1`
- organization in payload: `FusionEMSQuantum`

This indicates the organization is working from official EMS Collect Data case material beyond the locked Allergy case.

## Support request

Please verify the following for `FusionEMSQuantum`:

1. EMS Collect Data test cases for schema `61` are assigned and active
2. the organization is enabled for vendor EMS test-case recognition
3. whether `Joshua Wendorf` / `joshua.j.wendorf@fusionemsquantum.com` should be provisioned as a CTA user
4. whether `fusion_quant2` is the correct long-lived CTA login for this organization, or whether the email identity should replace it after provisioning
5. what remaining provisioning task keeps the Collect Data 3.5.1 application in `In Progress` status
6. why support identifies `FusionEMSQuantum` as the SOAP VSA username when live SOAP auth rejects it with both tested password variants
7. whether `fusion_quant2` should remain the operational SOAP credential until NEMSIS resets/reissues the `FusionEMSQuantum` VSA password

## Related evidence

- `artifact/cta/CTA_EMS_COLLECT_DATA_BLOCKER_EVIDENCE_2026-04-23.md`
- `artifact/cta/2025-EMS-1-Allergy_v351-response.xml`
- `artifact/cta/parsed-result.json`