# MARKET READY LEDGER

## 2026-05-10 — EPCR local lifecycle proof and storage-failure truth

- Repo: Adaptix-EPCR-Service
- Workflow: Local seeded chart workspace update and NEMSIS export lifecycle proof
- Final status: WARN
- Reason: The real local EPCR save/export path is now proven through the backend workspace and export services, but live artifact persistence remains blocked by invalid AWS credentials for the configured export bucket.

### Files changed

- `backend/tests/conftest.py`
- `backend/tests/test_epcr_local_lifecycle.py`
- `backend/epcr_app/services_export.py`

### Migrations added

- None

### Tests added

- `backend/tests/test_epcr_local_lifecycle.py`

### Commands run

- `cd Adaptix-EPCR-Service/backend && pytest tests/test_chart_workspace_service.py -k test_create_workspace_chart_creates_real_chart -q`
- `cd Adaptix-EPCR-Service/backend && pytest tests/test_epcr_local_lifecycle.py -q`
- `cd Adaptix-EPCR-Service/backend && pytest tests/test_chart_workspace_service.py::test_create_workspace_chart_creates_real_chart tests/test_epcr_local_lifecycle.py::test_seeded_chart_updates_and_exports_locally -q`
- `cd Adaptix-EPCR-Service && python - <manual seeded export probe with real S3 client>`

### Results observed

- Backend SQLite harness now starts from a clean database file instead of reusing stale temp schema state
- New local lifecycle regression passed: `1 passed`
- Combined focused backend validation passed: `2 passed`
- Deterministic seed chart loaded through `ChartWorkspaceService`, accepted a real narrative update, and generated a retrievable XML export through `NemsisExportService` when artifact storage was stubbed
- Unstubbed seeded export returned `status='persistence_failed'` and `failure_type='persistence_error'` with the real AWS `InvalidAccessKeyId` message instead of a generic generation failure

### Known limitations

- Live export artifact persistence is still blocked until valid AWS credentials exist for `NEMSIS_EXPORT_S3_BUCKET`
- This slice proves the backend workflow locally; no authenticated browser-level `/clinical/epcr` smoke was recorded in this session
- `pytest-asyncio` still emits the pre-existing `asyncio_default_fixture_loop_scope` deprecation warning during focused test runs

### Rollback instructions

- Revert `backend/tests/conftest.py` if shared temp-database reset is intentionally replaced by another test isolation strategy
- Remove `backend/tests/test_epcr_local_lifecycle.py` if the deterministic seed script is retired and replaced with another local proof fixture
- Revert the `ClientError` persistence classification change in `backend/epcr_app/services_export.py` if storage failures are intentionally remapped to another export failure contract

### Evidence pointers

- `backend/tests/test_epcr_local_lifecycle.py`
- `backend/tests/test_chart_workspace_service.py`
- `backend/epcr_app/services_export.py`

## 2026-05-08 — EPCR health/readiness parity and local NEMSIS revalidation

- Repo: Adaptix-EPCR-Service
- Workflow: Root and prefixed EPCR readiness route parity plus local NEMSIS proof refresh
- Final status: WARN
- Reason: Source parity and local NEMSIS evidence are now current, but live `/api/v1/epcr/readyz` remains 404 until redeploy and EMS CTA certification remains externally blocked by NEMSIS provisioning/account scope.

### Files changed

- `backend/epcr_app/main.py`
- `backend/tests/test_health_routes.py`

### Migrations added

- None

### Tests added

- `backend/tests/test_health_routes.py`

### Commands run

- `cd Adaptix-EPCR-Service/backend && c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe -m pytest tests/test_health_routes.py -q`
- `cd Adaptix-EPCR-Service/backend && c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe -m pytest tests/test_nemsis_routes.py tests/test_nemsis_allergy_vertical_slice.py -q`
- `GET https://api.adaptixcore.com/api/v1/epcr/healthz`
- `GET https://api.adaptixcore.com/api/v1/epcr/readyz`

### Results observed

- New readiness-route regression passed: `1 passed`
- Focused NEMSIS regression suite passed: `12 passed`
- Live production EPCR health probe returned `200 {"status":"ok","service":"epcr"}`
- Live production EPCR readiness probe returned `404 {"detail":"Not Found"}` before redeploy

### Known limitations

- Production route parity is not proven until the updated EPCR image is deployed and `GET /api/v1/epcr/readyz` returns `200`
- CTA EMS certification remains externally blocked by the existing NEMSIS `statusCode=-16` account/provisioning issue recorded in prior proof artifacts
- No authenticated production chart/export smoke was executed in this session

### Rollback instructions

- Revert the added readiness routes in `backend/epcr_app/main.py`
- Remove `backend/tests/test_health_routes.py` if the route contract changes intentionally

### Evidence pointers

- `backend/tests/test_health_routes.py`
- `backend/tests/test_nemsis_routes.py`
- `backend/tests/test_nemsis_allergy_vertical_slice.py`

## 2026-05-08 — EPCR CTA proof-chain repair

- Repo: Adaptix-EPCR-Service
- Workflow: NEMSIS local proof and CTA EMS certification path
- Final status: WARN
- Reason: Internal EPCR code path is validated; live EMS CTA submissions remain externally blocked by NEMSIS `statusCode=-16` provisioning/account scope.

### Files changed

- `scripts/run_nemsis_final_proof.py`

### Migrations added

- None

### Tests added

- None

### Commands run

- `pytest tests/test_ems_cta_scenario_payloads.py tests/test_cta_tac_dem_exact_match.py tests/test_api_cta_testing.py -q`
- `c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe scripts/run_nemsis_final_proof.py`
- `CTA_PROBE_LIVE=1 c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service/.venv/Scripts/python.exe scripts/cta_ems_collect_data_probe.py`
- `Invoke-WebRequest https://api.adaptixcore.com/api/v1/epcr/healthz`
- `Invoke-WebRequest https://api.adaptixcore.com/api/v1/epcr/desktop/qa/queue`
- `Invoke-WebRequest https://app.adaptixcore.com/epcr`

### Results observed

- CTA regression tests passed: `77 passed`
- Live production EPCR health check returned `200 {"status":"ok","service":"epcr"}`
- Protected EPCR API queue returned `401` without auth, confirming auth enforcement instead of route failure
- Web `/epcr` returned `307` redirect to `/access`, confirming protected frontend route behavior
- Local proof returned `PASS` after repairing the proof script to use `OfficialSchematronValidator`
- Live EMS CTA probe returned `statusCode=-16` with message `Incorrect test case provided. Key data elements must match a test case.`
- Live EMS probe final status remained `PASS_OPERATOR_ACTION_REQUIRED`

### Known limitations

- EMS CTA certification is not fully completable from this repository while the NEMSIS account remains externally blocked for EMS Collect Data scope/provisioning
- No authenticated browser proof was recorded in this slice because production operator credentials were not supplied in-session

### Rollback instructions

- Revert `scripts/run_nemsis_final_proof.py` to the previous import path if the `OfficialSchematronValidator` API is intentionally removed and replaced with a compatibility wrapper

### Evidence pointers

- `artifacts/nemsis-local-proof.json`
- `artifacts/cta-ems-status-minus-16-request.json`
- `artifacts/cta-ems-status-minus-16-response.json`
- `artifact/generated/2025-EMS-1-Allergy_v351.xml`