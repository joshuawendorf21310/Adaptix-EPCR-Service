# Adaptix-EPCR-Service Production Readiness

Date: 2026-04-28
Classification: SETUP_REQUIRED

## Service Purpose
ePCR charting, clinical encounter documentation, chart validation, chart lifecycle, and NEMSIS 3.5.1 export truth.

## Exposed Routes
Expected prefix: `/api/v1/epcr/*`. Exact production route inventory must be generated from the backend router before readiness closure.

## Dependencies
PostgreSQL, Adaptix auth/tenant context, NEMSIS schemas/code sets, CTA/state validation path where applicable, file/export storage, audit/event infrastructure.

## Secrets Required
- Database URL
- JWT/auth validation settings
- NEMSIS/CTA credentials where required
- Export storage credentials if external storage is used

## Database/Migration State
Database-backed. Migration state must be verified in production. Prior notes flag SQLite compatibility fixes and CTA validation evidence.

## Integration Dependencies
NEMSIS validation/export, state/CTA endpoint where applicable, Web-App ePCR workspace, CAD linkage, field app sync.

## Health/Readiness Endpoint Status
Health/readiness must be verified in deployed production. Current full production proof is missing.

## Test Status
Local CTA/XML evidence exists in repo memory. Live CTA EMS case-recognition remains externally blocked or unresolved in the current evidence set.

## Deployment Status
Production deployment and production export smoke are not fully proven.

## Production Blockers
- NEMSIS 3.5.1 production export is not fully verified.
- CTA/state validation production pass is not complete for all required cases.
- Chart lifecycle, finalization, and export audit proof must be verified in deployed runtime.

## Remediation Completed
- NEMSIS ownership and CTA blocker evidence are documented in repo memory.

## Final Verdict
SETUP_REQUIRED.