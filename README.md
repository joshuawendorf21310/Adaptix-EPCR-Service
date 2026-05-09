# Adaptix ePCR Service

Electronic Patient Care Report (ePCR) microservice for the [Adaptix](https://adaptixcore.com) EMS platform. Manages the full clinical charting lifecycle — from chart creation through NEMSIS 3.5.1 XML export and state submission.

Built for EMS agencies that need a reliable, standards-compliant charting backend. Every chart operation is tenant-scoped, audited, and idempotent — with built-in NEMSIS 3.5.1 validation so exports pass state acceptance on the first submission.

## Features

| Area | Capabilities |
|---|---|
| **Chart Lifecycle** | Create, edit, autosave, sign, lock, admin unlock — all audited and idempotent |
| **Clinical Data** | Vitals, assessments, narratives, medications, procedures, allergies, injuries, dispositions |
| **Attachments** | File upload/download with S3-backed storage |
| **NEMSIS 3.5.1** | Full XML export with XSD and Schematron validation, field graph, code-set registry, pack management |
| **Compliance** | CTA scenario testing, TAC Schematron packages, state submission pipeline |
| **Billing** | Chart-to-billing readiness handoff via domain event outbox |
| **Multi-Tenant** | All operations are tenant-scoped with JWT-authenticated user context |

## Tech Stack

- **Runtime:** Python 3.11 / FastAPI
- **Database:** PostgreSQL via SQLAlchemy 2 (async) + Alembic migrations
- **Storage:** AWS S3 (attachments, NEMSIS exports, resource packs)
- **Deployment:** AWS ECS Fargate with Docker
- **CI/CD:** GitHub Actions → ECR → ECS (staging & production)

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or use SQLite for local testing)
- An `.env` file based on the provided template

### Setup

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your database URL, JWT public key, etc.

# 2. Install dependencies
cd backend
pip install -e ".[dev]"

# 3. Run database migrations
alembic upgrade head

# 4. Start the development server
uvicorn epcr_app.main:app --reload --port 8006
```

The API is available at `http://localhost:8006`. Interactive docs are at `http://localhost:8006/docs`.

### Docker

```bash
docker build -t adaptix-epcr-service .
docker run -p 8000:8000 --env-file .env adaptix-epcr-service
```

## API Overview

All endpoints are prefixed with `/api/v1/epcr`. Authentication is via RS256 JWT Bearer token issued by the Adaptix Core auth service.

| Route Group | Description |
|---|---|
| `/api/v1/epcr/charts` | Chart CRUD, finalization, and workspace |
| `/api/v1/epcr/export` | NEMSIS XML generation and download |
| `/api/v1/epcr/nemsis/*` | Validation, field graph, code sets, registry, scenarios, packs |
| `/api/v1/epcr/submissions` | State submission lifecycle |
| `/api/v1/epcr/timeline` | Patient state timeline |
| `/api/v1/epcr/version` | Build identity and version info |
| `/healthz` | Health check |

## Testing

```bash
cd backend
pytest
```

The test suite includes 500+ tests covering chart lifecycle, NEMSIS export conformance, clinical validation, CTA scenario alignment, and API contract enforcement.

## Configuration

All configuration is via environment variables. See [`.env.example`](.env.example) for the full list with descriptions. Key variables:

| Variable | Required | Description |
|---|---|---|
| `EPCR_DATABASE_URL` | ✅ | PostgreSQL asyncpg connection string |
| `ADAPTIX_JWT_PUBLIC_KEY` | ✅ | PEM public key for JWT verification |
| `FILES_S3_BUCKET` | ✅ | S3 bucket for attachments and exports |
| `NEMSIS_XSD_PATH` | For validation | Path to NEMSIS 3.5.1 XSD schema |
| `NEMSIS_SCHEMATRON_PATH` | For validation | Path to NEMSIS Schematron rules |
| `NEMSIS_STATE_ENDPOINT_URL` | For submission | SOAP endpoint for state NEMSIS submission |

## Project Structure

```
backend/
├── epcr_app/           # Application source
│   ├── main.py         # FastAPI app factory and lifespan
│   ├── api*.py         # Route handlers
│   ├── models*.py      # SQLAlchemy models and Pydantic schemas
│   ├── *_service.py    # Domain services
│   ├── nemsis/          # NEMSIS-specific logic
│   └── auth/           # Authentication utilities
├── migrations/         # Alembic database migrations
├── tests/              # Test suite (500+ tests)
└── compliance/         # NEMSIS compliance schemas
```

## Deployment

The service deploys to AWS ECS Fargate via GitHub Actions. On push to `main`:

1. **Build** — Docker image built and pushed to ECR
2. **Deploy Staging** — Task definition updated, ECS service redeployed
3. **Deploy Production** — Migrations run via one-shot Fargate task, then service redeployed

See [`DEPLOYMENT_CHECKLIST.md`](DEPLOYMENT_CHECKLIST.md) and [`RUNBOOK.md`](RUNBOOK.md) for operational guidance.

## Documentation

- [`SERVICE_CONTRACT.md`](SERVICE_CONTRACT.md) — API and data ownership contracts
- [`ARCHITECTURE_TRUTH.md`](ARCHITECTURE_TRUTH.md) — Architecture decisions and boundaries
- [`DOMAIN_BOUNDARIES.md`](DOMAIN_BOUNDARIES.md) — Domain ownership rules
- [`RUNBOOK.md`](RUNBOOK.md) — Operational runbook
- [`CHANGELOG.md`](CHANGELOG.md) — Release history

## License

Proprietary — © Adaptix. All rights reserved.
