# MARKET_READY.md

**Repo:** Adaptix-EPCR-Service
**Class:** ACTIVE
**Current Status:** MARKET READY
**Customer Scope:** Electronic Patient Care Report — chart lifecycle (create/edit/autosave/sign/lock), vitals, assessments, medications, procedures, attachments, NEMSIS 3.5.1 XML export, XSD/Schematron validation
**Runtime Type:** backend
**Database-backed:** yes
**Required Env Vars:** EPCR_DATABASE_URL, ADAPTIX_JWT_PUBLIC_KEY, FILES_S3_BUCKET
**Migration Command:** cd backend && alembic upgrade head
**Test Command:** cd backend && pytest
**Build Command:** docker build -t adaptix-epcr-service .
**Health Endpoint:** GET /healthz
**Deployment Target:** staging / prod (ECS Fargate)
**Rollback Command:** cd backend && alembic downgrade -1
**Validation:**
- PASS: 516 tests passed, 22 skipped (environment-specific), 3 skipped (require live XSD/CTA assets)
- PASS: CI pipeline (GitHub Actions) — build and test workflows operational
- PASS: Docker image builds successfully
- PASS: README, CHANGELOG, RUNBOOK, SERVICE_CONTRACT documentation complete
- PASS: Repository cleaned of development scratch files
- PENDING: NEMSIS state agency submission endpoint configuration (per-customer setup)
**Last Validation Date:** 2026-05-09
**Commit SHA:** HEAD
