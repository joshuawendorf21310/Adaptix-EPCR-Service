<!-- GOVERNANCE_VERSION: 2026.04.21 -->
# BILLING_AND_PACKAGING_RULES

## Packaging law

Commercial packaging is modular; architecture remains shared.

## Rules enforced here

- Do not embed pricing catalog logic in non-billing runtime code.
- Do not use Stripe as operational state.
- Do not force unrelated subsystem dependencies to unlock one module.
- Do not duplicate entitlement resolution outside the shared platform foundation.

## Runtime consequence

The governance runtime denies edits that introduce hardcoded pricing logic in repos that are not permitted to hold it.
