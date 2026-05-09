# Changelog

All notable changes to Adaptix-EPCR-Service are documented here.

## [1.0.0] — 2026-05-09

### Added
- Full chart lifecycle: create, edit, autosave, sign, lock, admin unlock with audit
- Clinical data management: vitals, assessments, narratives, medications, procedures, allergies, injuries, dispositions
- S3-backed file attachments
- NEMSIS 3.5.1 XML export with XSD and Schematron validation
- NEMSIS field graph, code-set registry, resource pack management
- CTA scenario testing workbench and TAC Schematron package support
- NEMSIS state submission pipeline (SOAP)
- Chart-to-billing readiness handoff via domain event outbox
- Multi-tenant JWT-authenticated API with CORS support
- Chart workspace API with 10 routes
- CAD handoff ingestion service
- Build identity endpoint at `/api/v1/epcr/version`
- Docker HEALTHCHECK and `/healthz` endpoint
- CI/CD pipeline: GitHub Actions → ECR → ECS Fargate (staging + production)
- Database migrations via Alembic with production migration gate
- 500+ automated tests

### Fixed
- asyncpg SSL context for self-signed RDS certificate chains
- DATABASE_URL fallback and normalization to asyncpg
- Alembic migration chain (merged heads, widened version column, isolated version table)
- JWT signature verification in auth context
- Tenant-scoped chart workspace creation enforcement
- CORS headers for gateway identity propagation

### Changed
- Repository cleaned of development scratch files and debug artifacts
- README rewritten for market-facing clarity
- Production readiness documentation updated to READY status
