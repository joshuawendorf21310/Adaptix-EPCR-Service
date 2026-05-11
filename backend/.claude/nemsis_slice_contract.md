# Canonical NEMSIS v3.5.1 Vertical-Slice Contract

This file is the **stable prompt prefix** every sub-agent receives verbatim
when implementing a NEMSIS section. Embed it once at the top of the agent
prompt; the per-slice delta (table name, migration revision, NEMSIS
element list) goes after.

The Anthropic API caches identical prefixes for 5 minutes. Keeping this
file unedited across a dispatch wave maximizes cache hits and minimizes
per-cycle token cost. Edit only between waves, not within them.

## Working directory

`c:\Users\fusio\Desktop\workspace\Adaptix-EPCR-Service`

## Canonical reference implementation (read before writing anything)

The eTimes slice is the line-for-line pattern every other slice mimics:

- [models_chart_times.py](../epcr_app/models_chart_times.py)
- [024_add_chart_times.py](../migrations/versions/024_add_chart_times.py)
- [services_chart_times.py](../epcr_app/services_chart_times.py)
- [projection_chart_times.py](../epcr_app/projection_chart_times.py)
- [api_chart_times.py](../epcr_app/api_chart_times.py)
- [test_model_chart_times.py](../tests/test_model_chart_times.py)
- [test_services_chart_times.py](../tests/test_services_chart_times.py)
- [test_projection_chart_times.py](../tests/test_projection_chart_times.py)
- [test_api_chart_times.py](../tests/test_api_chart_times.py)

## Absolute prohibitions (NO EXCEPTIONS)

- Do not modify any existing file. Specifically:
  `models.py`, `db.py`, `main.py`, `alembic.ini`, `dependencies.py`,
  any other `models_*.py` / `services_*.py` / `api_*.py` already present,
  or any existing migration under `backend/migrations/versions/`.
- Do not add a `relationship()` declaration to the `Chart` class.
- Do not touch another slice's files.
- Do not weaken tenant isolation, the binding-drift assertion, or the
  test-run verification step.
- Do not introduce mock-only paths, fake completion, or pytest skips.

## 9-file output set per slice

1. `backend/epcr_app/models_<slice>.py`
2. `backend/migrations/versions/<NNN>_add_<slice>.py` — reserved revision
   `NNN`, `down_revision = "023"` (parallel-branch pattern), idempotent
   `insp.has_table` / `insp.get_indexes` guards, complete `downgrade()`.
3. `backend/epcr_app/services_<slice>.py` — async, tenant-scoped at the
   SQL layer, partial-update semantics, explicit `clear_field`,
   soft delete.
4. `backend/epcr_app/projection_<slice>.py` — domain → ledger via
   `NemsisFieldValueService.bulk_save`, honoring repeating-group
   `occurrence_id` / `sequence_index` / `group_path`, with module-level
   binding-drift `assert`.
5. `backend/epcr_app/api_<slice>.py` — FastAPI router prefixed
   `/api/v1/epcr/charts/{chart_id}/<slice>`, `get_current_user` +
   `get_session` deps, Pydantic `extra="forbid"` request models,
   commit-on-success / rollback-on-error.
6. `backend/tests/test_model_<slice>.py`
7. `backend/tests/test_services_<slice>.py`
8. `backend/tests/test_projection_<slice>.py`
9. `backend/tests/test_api_<slice>.py`

## Test-contract invariants

- In-memory SQLite (`sqlite+aiosqlite:///:memory:`) per fixture.
- `pytest_asyncio` auto mode (already configured in `pytest.ini`).
- API tests use FastAPI `TestClient` with `app.dependency_overrides`
  for both `get_session` and `get_current_user`.
- SQLite strips timezone info on `DateTime(timezone=True)` columns —
  compare ISO strings with `.startswith(...)` for the naive prefix.
- Every test must really run; no skip markers, no xfail.
- A binding-drift test asserting every model column is bound to a
  NEMSIS element.
- A tenant-isolation test asserting cross-tenant reads return `None`.

## Mandatory verification step

```
cd c:/Users/fusio/Desktop/workspace/Adaptix-EPCR-Service
EPCR_DATABASE_URL="sqlite+aiosqlite:///$(mktemp -u).db" python -m pytest \
    backend/tests/test_model_<slice>.py \
    backend/tests/test_services_<slice>.py \
    backend/tests/test_projection_<slice>.py \
    backend/tests/test_api_<slice>.py \
    -x -q --no-header 2>&1 | tail -40
```

Re-run after every fix. Stop only when zero failures. Reporting "tests
pass" without running them is a falsified completion claim and is
prohibited.

## Required final report from each sub-agent

- 9 absolute file paths.
- Migration revision number.
- Router prefix.
- Final pytest tail showing `N passed in M.Ms` (no failures).
- Total LOC across the 9 files.
- Any unresolved blocker (or the literal word `None`).
