<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# SYSTEM_RULES

## Authority

This file is part of the Adaptix platform-standard governance contract for `Adaptix-EPCR-Service`.

## Mandatory system rules

- Reuse shared platform foundations from Adaptix Core.
- Enforce tenant, auth, RBAC, audit, gateway, and contract reuse rather than reimplementation.
- Surface failures truthfully; never simulate production readiness.
- Keep rules executable and auditable through the governance runtime hooks.

## Runtime enforcement expectations

- `SessionStart` must log root/local rule loading.
- `PreToolUse` must deny forbidden actions.
- `PostToolUse` must record decision evidence.
- Validation failures must be blocking, not informational only.
