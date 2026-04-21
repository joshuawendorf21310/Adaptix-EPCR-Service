<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# ARCHITECTURE_TRUTH

## Repo role

- **Repo:** `Adaptix-EPCR-Service`
- **Role:** `service`
- **Runtime:** `Python/FastAPI`
- **Owned truth:** ePCR charting and NEMSIS truth

## Architecture law

- Shared platform foundation reuse is mandatory.
- Domain-specific workflow logic belongs in local subsystem areas only.
- Integration points must be explicit and typed.
- Governance enforcement hooks are part of the executable architecture.

## Explicit inheritance path

Root rules: `AGENTS.md` and companion governance files.
Local rules: nearest subsystem `AGENTS.md` selected by path.
Runtime enforcement: `.github/hooks/agent-governance.json` -> `scripts/agent_governance_runtime.py`.
