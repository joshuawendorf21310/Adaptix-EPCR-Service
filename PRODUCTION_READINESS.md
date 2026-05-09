# Adaptix-EPCR-Service Production Readiness

Date: 2026-05-09
Classification: READY

## Service Purpose
ePCR charting, clinical encounter documentation, chart validation, chart lifecycle, and NEMSIS 3.5.1 export truth.

## Exposed Routes
Prefix: `/api/v1/epcr/*`. Full route inventory includes chart CRUD, export, NEMSIS validation/registry/submissions/packs/field-graph/scenarios, timeline, workspace, clinical extensions, and CTA testing.

## Dependencies
PostgreSQL, Adaptix auth/tenant context (JWT), NEMSIS 3.5.1 schemas/code sets, S3 for file and export storage.

## Secrets Required
- `EPCR_DATABASE_URL` — PostgreSQL asyncpg connection string
- `ADAPTIX_JWT_PUBLIC_KEY` — PEM-encoded RSA/EC public key for JWT verification
- `FILES_S3_BUCKET` — S3 bucket for attachments and export artifacts
- `NEMSIS_STATE_ENDPOINT_URL` / `NEMSIS_SOAP_USERNAME` / `NEMSIS_SOAP_PASSWORD` — for state submissions (per-customer)

## Database/Migration State
Database-backed via Alembic. Migrations run automatically on container startup (`alembic upgrade head`). Production migrations are executed as a one-shot Fargate task before service deploy.

## Health/Readiness Endpoint Status
- `GET /healthz` — returns `{"status": "ok", "service": "epcr"}`
- Docker HEALTHCHECK configured with 30s interval

## Test Status
516 tests passing. 22 skipped (environment-specific — require live CTA/XSD assets not present in CI). Zero test warnings.

## Deployment Status
CI/CD pipeline deploys to staging and production via GitHub Actions → ECR → ECS Fargate. Production deploy includes migration gate.

## Remaining Items
- NEMSIS state agency submission endpoint wiring is per-customer configuration, not a code blocker.

## Final Verdict
READY — service is functionally complete, tested, documented, and deployable.