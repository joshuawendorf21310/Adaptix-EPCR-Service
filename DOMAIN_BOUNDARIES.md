<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# DOMAIN_BOUNDARIES

## Repo boundary

`Adaptix-EPCR-Service` owns: ePCR.

## Boundary law

- Own only the truth explicitly assigned to this repository and its local subsystem agents.
- Consume cross-domain data only through contracts, APIs, events, or gateway paths.
- Never perform direct cross-domain database writes.
- Never store operational truth in UI-only state, logs, exports, or commercial systems.

## Enforcement consequence

The governance runtime denies new private cross-domain imports and logs the blocked action.
