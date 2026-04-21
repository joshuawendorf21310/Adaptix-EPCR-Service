<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# MODULE_ENTITLEMENTS

## Commercial separation

Adaptix sells modular subsystem access, but operational runtime must enforce capabilities rather than package names.

## Rules

- Map subscriptions to capabilities or entitlements.
- Never branch domain runtime behavior on plan names like Basic/Pro/Enterprise.
- Billing may process commercial events, but operational domains must stay capability-driven.
- `Adaptix-EPCR-Service` must remain runnable as an independent subsystem where applicable.
