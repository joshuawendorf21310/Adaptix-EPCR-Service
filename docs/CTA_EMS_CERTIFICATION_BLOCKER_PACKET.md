# CTA EMS CERTIFICATION BLOCKER PACKET

**Date:** 2026-04-23  
**Service:** Adaptix-EPCR-Service  
**Status:** `PASS_OPERATOR_ACTION_REQUIRED`  
**Blocker Class:** External / Account Provisioning (NOT a code defect)

---

## 1. LOCAL PIPELINE EVIDENCE — ALL PASS

| Check | Result | Detail |
|---|---|---|
| XML generation | **PASS** | `artifact/generated/2025-EMS-1-Allergy_v351.xml` |
| XSD validation | **PASS** | 0 errors against official NEMSIS 3.5.1 EMSDataSet.xsd |
| Schematron validation | **PASS** | 0 violations against official EMSDataSet.sch |
| No placeholder tokens | **PASS** | Zero `[Your ...]` or `[Value from ...]` tokens |
| Artifact checksum | **PASS** | SHA-256 verified at generation time |

**Artifact path:** `artifact/generated/2025-EMS-1-Allergy_v351.xml`  
**Evidence file:** `artifacts/cta-ems-local-validation-proof.json`

---

## 2. DEM SUBMISSION PATH — VERIFIED WORKING

- **Endpoint:** `https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/`
- **Dataset:** DEMDataSet (2025-DEM-1)
- **Credentials:** `fusion_quant2` + current NEMSIS_CTA_PASSWORD
- **Result:** `statusCode = 1` (accepted)
- **Verification date:** 2026-04-23

DEM submissions with the same credentials and same SOAP envelope structure succeed. This proves credentials, endpoint, SOAP format, and HTTP connectivity are all correct.

---

## 3. EMS COLLECT DATA RETURNS -16

- **Endpoint:** `https://cta.nemsis.org:443/ComplianceTestingWs/endpoints/`
- **Dataset:** EMSDataSet (EMS-1 through EMS-5)
- **Credentials:** `fusion_quant2` + NEMSIS_CTA_PASSWORD
- **Result:** `statusCode = -16`
- **Timestamp:** 2026-04-23

### Cross-Validation Evidence

| Submission | Result |
|---|---|
| Adaptix EMS-1 Allergy (XSD+SCH valid) | **-16** |
| Official NEMSIS TAC EMS Allergy (untouched) | **-16** |
| Official NEMSIS TAC EMS HeatStroke (untouched) | **-16** |
| DEM-1 with same credentials | **+1** |

**Conclusion:** The -16 is NOT caused by XML content, credentials, or network connectivity. The untouched official NEMSIS TAC EMS test files also return -16 with the same credentials. This is an account enrollment/provisioning issue.

---

## 4. REQUEST PAYLOAD ID

- **Request handle:** `PROBE-2026-04-23-EMS-1`  
- **Submission label:** `EMS-1-Allergy-v351-probe`  
- **Evidence file:** `artifacts/cta-ems-status-minus-16-request.json`

---

## 5. RESPONSE BODY

```
statusCode=-16
```

Full structured response: `artifacts/cta-ems-status-minus-16-response.json`

---

## 6. ACCOUNT / ENVIRONMENT

- **Username:** `fusion_quant2`
- **Organization:** `FusionEMSQuantum`
- **Portal login:** `joshua.j.wendorf@fusionemsquantum.com`
- **Portal app tile:** NEMSIS CTA (visible in Okta dashboard)
- **Collect Data scope:** NEMSIS 3.5.1 (application received 02/11/2026)
- **Portal status:** `In Progress`

The `In Progress` portal status aligns with -16. EMS Collect Data scope has not been fully provisioned/activated for this account.

---

## 7. EXACT QUESTION FOR NEMSIS SUPPORT

> "Is the account `FusionEMSQuantum` (login: `fusion_quant2`, portal user: `joshua.j.wendorf@fusionemsquantum.com`) provisioned and enrolled for **EMS Collect Data** submissions for **EMS-1 through EMS-5** under NEMSIS 3.5.1? Our account status shows `In Progress` and all EMS submissions return `statusCode=-16`, including untouched official NEMSIS TAC test files. DEM submissions with the same credentials return `statusCode=1`. Please confirm if the EMS Collect Data scope needs to be activated and advise on the activation timeline."

---

## 8. CODE STATUS

- **No code changes required** to the XML builder, XSD validator, or Schematron validator.
- **No fake EMS submission success** in any code path.
- **No EMS-1 through EMS-5 marked cleared** in any status file or code.
- The probe script (`scripts/cta_ems_collect_data_probe.py`) returns `PASS_OPERATOR_ACTION_REQUIRED` when -16 is received — not success.

---

## 9. REPRODUCIBILITY

```bash
# Verify local pipeline
cd Adaptix-EPCR-Service
pytest -q
python scripts/run_nemsis_final_proof.py

# Run live CTA EMS probe (captures -16 evidence)
CTA_PROBE_LIVE=1 python scripts/cta_ems_collect_data_probe.py
```

---

## 10. FINAL STATUS

```
PASS_OPERATOR_ACTION_REQUIRED

Local NEMSIS pipeline: PASS
CTA DEM path: PASS
CTA EMS path: BLOCKED (statusCode=-16, external provisioning issue)

Required operator action:
Contact NEMSIS support and request EMS Collect Data scope activation
for account FusionEMSQuantum.
```

No further code changes should be made to the NEMSIS pipeline until NEMSIS support confirms a data defect. The current codebase is correct.
