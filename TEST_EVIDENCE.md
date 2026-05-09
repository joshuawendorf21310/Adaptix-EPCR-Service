# Adaptix-EPCR-Service Test Evidence

Date: 2026-04-28

## Evidence Available
- Repo memory records local NEMSIS/CTA XML validation work and blocker evidence.
- Local EMS vertical slice was previously green for generated XML/XSD/Schematron/fidelity.

## Evidence Missing
- Current full test rerun.
- Production chart lifecycle smoke.
- Production NEMSIS export smoke.
- Production CTA/state validation pass for required cases.
- Production audit persistence proof.

## Verdict
SETUP_REQUIRED.

---

## EPCR Health/Readiness and NEMSIS Evidence — 2026-05-08

### Live Production Probe
- `GET https://api.adaptixcore.com/api/v1/epcr/healthz` -> `200 {"status":"ok","service":"epcr"}`
- `GET https://api.adaptixcore.com/api/v1/epcr/readyz` -> `404 {"detail":"Not Found"}` before redeploy

### Source Remediation
- File updated: `backend/epcr_app/main.py`
- Change: added `/readyz` and `/api/v1/epcr/readyz` to match existing health routes
- Regression test added: `backend/tests/test_health_routes.py`

### Local Validation
- Command: `cd Adaptix-EPCR-Service/backend && c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe -m pytest tests/test_health_routes.py -q`
- Result: `1 passed`
- Command: `cd Adaptix-EPCR-Service/backend && c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe -m pytest tests/test_nemsis_routes.py tests/test_nemsis_allergy_vertical_slice.py -q`
- Result: `12 passed`

### Remaining Gaps
- Live production readiness route still requires redeploy proof.
- Certified CTA EMS validation remains externally blocked by the NEMSIS provisioning/account issue already evidenced in repo artifacts and memory.