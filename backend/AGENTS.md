<!-- GOVERNANCE_VERSION: 2026.04.21 -->
<!-- INHERITS_ROOT_GOVERNANCE: true -->
<!-- ROOT_GOVERNANCE_PATH: AGENTS.md -->
<!-- SUBSYSTEM_KEY: epcr -->
# ePCR Subsystem Agent Contract

## Inheritance

This local contract inherits and may only strengthen the root governance law in `/AGENTS.md`.

## Truth ownership

- **Subsystem:** ePCR
- **Truth owner:** patient care, charting, narrative, and NEMSIS export truth
- **Repo:** `Adaptix-EPCR-Service`
- **Owned path:** `backend/AGENTS.md` and descendants

## Engines

- clinical-charting
- nemsis-mapping
- export
- autosave

## Workflows

- incident charting
- review locking
- export readiness
- submission recovery

## Validations

- clinical completeness
- NEMSIS required elements
- chart state transitions

## Integrations

- CAD dispatch context
- Billing claim consumption
- Fire incident signals

## Forbidden patterns

- Do not let billing or analytics mutate locked chart truth.
- Do not hide clinical validation failures in logs only.
