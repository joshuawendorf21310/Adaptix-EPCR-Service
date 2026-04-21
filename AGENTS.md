<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# Adaptix Governance Root Contract

This repository participates in the Adaptix platform governance contract at version `2026.04.21`.

## Root execution order

Every agent runtime for this repository must:

1. Load this root `AGENTS.md` first.
2. Load the nearest applicable local `AGENTS.md` second.
3. Enforce root-law inheritance.
4. Block contradictory or forbidden actions truthfully.
5. Record audit evidence for rule loading and execution decisions.

## Repo authority

- **Repository:** `Adaptix-EPCR-Service`
- **Role:** `service`
- **Runtime:** `Python/FastAPI`
- **Owned truth:** ePCR charting and NEMSIS truth

## Shared platform law

- Shared foundations live in Adaptix Core and must not be reimplemented here.
- Billing and entitlements remain separated from commercial packaging names.
- Cross-domain integration must use contracts, APIs, or events.
- Domain systems must stand alone without forcing suite dependencies.

## Required governance companions

- `SYSTEM_RULES.md`
- `DOMAIN_BOUNDARIES.md`
- `MODULE_ENTITLEMENTS.md`
- `ARCHITECTURE_TRUTH.md`
- `BILLING_AND_PACKAGING_RULES.md`

## Local subsystem agents

- `backend/AGENTS.md`

## Enforcement runtime

- Hook config: `.github/hooks/agent-governance.json`
- Manifest: `.github/governance/governance.manifest.json`
- Runtime script: `scripts/agent_governance_runtime.py`
- Audit log: `.github/governance/audit/agent_runtime_audit.jsonl`

## Forbidden root-level behavior

- Do not duplicate identity, auth, RBAC, tenant, entitlement, or audit foundations.
- Do not hardcode pricing plans or package names into domain runtime behavior.
- Do not write private cross-domain imports against sibling repos.
- Do not override local subsystem governance with weaker root guidance.
