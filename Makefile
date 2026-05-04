# Adaptix EPCR Service — Build and Validation Commands
# Equivalent to the pnpm commands specified in the architecture.
# This repo uses Python/pytest as the native build system.
# Run from: c:\Users\fusio\Desktop\workspace\Adaptix-EPCR-Service\backend

PYTHON := python
PYTEST := python -m pytest
ALEMBIC := python -m alembic
PYTEST_OPTS := --override-ini="asyncio_default_fixture_loop_scope=function" --override-ini="filterwarnings=ignore::DeprecationWarning" --rootdir=backend

# ---------------------------------------------------------------------------
# Core commands
# ---------------------------------------------------------------------------

install:
	cd backend && pip install -e ".[dev]"

lint:
	cd backend && python -m compileall epcr_app -q

typecheck:
	cd backend && python -m compileall epcr_app migrations -q

test:
	cd backend && $(PYTEST) tests/ $(PYTEST_OPTS) -q

test-integration:
	cd backend && $(PYTEST) tests/ $(PYTEST_OPTS) -v --tb=short

test-e2e:
	cd backend && python verify_endpoints.py

build:
	cd backend && pip install -e .

# ---------------------------------------------------------------------------
# Database commands
# ---------------------------------------------------------------------------

db-migrate:
	cd backend && $(ALEMBIC) upgrade head

db-validate:
	cd backend && python -m compileall migrations -q

# ---------------------------------------------------------------------------
# Contracts commands
# ---------------------------------------------------------------------------

contracts-generate:
	python -m compileall ../Adaptix-Contracts/adaptix_contracts/epcr -q

contracts-check:
	python -m compileall ../Adaptix-Contracts/adaptix_contracts -q

# ---------------------------------------------------------------------------
# NEMSIS commands
# ---------------------------------------------------------------------------

nemsis-ingest:
	cd backend && python scripts/extract_xsd_enums.py

nemsis-generate:
	cd backend && python scripts/_deployed_nemsis_xml_builder.py

nemsis-validate:
	cd backend && python -m pytest tests/test_nemsis_xml_builder_conformance.py tests/test_schematron_validator.py $(PYTEST_OPTS) -v

nemsis-diff:
	cd backend && python scripts/_drift_audit.py

# ---------------------------------------------------------------------------
# EPCR-specific test commands
# ---------------------------------------------------------------------------

epcr-test:
	cd backend && $(PYTEST) tests/ $(PYTEST_OPTS) -q

vision-test:
	cd backend && $(PYTEST) tests/test_caregraph_cpae_vas_vision.py $(PYTEST_OPTS) -v

# ---------------------------------------------------------------------------
# Android commands (run from Adaptix-Field-App/android)
# ---------------------------------------------------------------------------

android-test:
	cd ../Adaptix-Field-App/android && gradlew.bat :app-epcr:test --no-daemon

android-lint:
	cd ../Adaptix-Field-App/android && gradlew.bat :app-epcr:lint --no-daemon

android-assemble-debug:
	cd ../Adaptix-Field-App/android && gradlew.bat :app-epcr:assembleDebug --no-daemon

android-assemble-release:
	cd ../Adaptix-Field-App/android && gradlew.bat :app-epcr:assembleRelease --no-daemon

# ---------------------------------------------------------------------------
# Freeze verification
# ---------------------------------------------------------------------------

freeze-verify:
	python -m compileall backend/epcr_app -q
	python -m compileall backend/migrations -q
	python -m compileall ../Adaptix-Contracts/adaptix_contracts/epcr -q
	cd backend && $(PYTEST) tests/ $(PYTEST_OPTS) -q

.PHONY: install lint typecheck test test-integration test-e2e build \
        db-migrate db-validate contracts-generate contracts-check \
        nemsis-ingest nemsis-generate nemsis-validate nemsis-diff \
        epcr-test vision-test android-test android-lint \
        android-assemble-debug android-assemble-release freeze-verify
