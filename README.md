# Adaptix ePCR Service

Electronic Patient Care Report service for the Adaptix platform.

**Status:** MARKET-READINESS EXECUTION IN PROGRESS — see [MARKET_READY.md](MARKET_READY.md)

## Scope

- Chart lifecycle: create, edit, autosave, sign, lock, admin unlock (with audit)
- Clinical data: vitals, assessment, narrative, medications, procedures
- Attachments: file upload with S3 storage
- NEMSIS 3.5.1 XML export with XSD and Schematron validation
- Chart-to-billing handoff via outbox event
- Tenant-scoped, audited, idempotent operations

## Stack

- Python 3.11 / FastAPI
- PostgreSQL + SQLAlchemy 2 + Alembic
- AWS S3 (attachments)
- AWS ECS Fargate deployment

## Local Development

```bash
cp .env.example .env
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn epcr_app.main:app --reload --port 8006
```

## Testing

```bash
cd backend
pytest
# Local result (2026-04-30): 207 passed, 0 skipped, 0 warnings
```

## Known Blockers

See [MARKET_READY.md](MARKET_READY.md). NEMSIS state submission endpoint not wired; staging steady state not confirmed after image rebuild.
