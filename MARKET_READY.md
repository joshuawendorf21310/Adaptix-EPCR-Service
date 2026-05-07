# MARKET_READY.md

**Repo:** Adaptix-EPCR-Service
**Class:** ACTIVE
**Current Status:** PARTIAL
**Customer Scope:** Electronic Patient Care Report — chart lifecycle (create/edit/autosave/sign/lock), vitals, assessments, medications, procedures, attachments, NEMSIS 3.5.1 XML export, XSD/Schematron validation
**Runtime Type:** backend
**Database-backed:** yes
**Required Env Vars:** EPCR_DATABASE_URL, JWT_PUBLIC_KEY_PEM, ADAPTIX_GATEWAY_SHARED_SECRET, AWS_S3_BUCKET (for attachments)
**Migration Command:** cd backend && alembic upgrade head
**Test Command:** cd backend && pytest
**Build Command:** docker build -t adaptix-epcr-service ./backend
**Health Endpoint:** GET /healthz
**Deployment Target:** staging / prod (ECS Fargate)
**Rollback Command:** cd backend && alembic downgrade -1
**Known Blockers:**
- PARTIAL: Local lifecycle PASS (Slice A — 207 tests, 0 skipped, 0 warnings, 2026-04-30)
- NOT VERIFIED: Staging steady state after image rebuild (git + contracts fix applied; not confirmed)
- NOT CONNECTED: NEMSIS state agency submission endpoint not wired
- FAIL: No README.md in this repo
**Last Validation Command:** pytest (local Docker, 2026-04-30)
**Last Validation Result:** PARTIAL — local PASS; staging deployment not confirmed
**Commit SHA:** NOT RECORDED
