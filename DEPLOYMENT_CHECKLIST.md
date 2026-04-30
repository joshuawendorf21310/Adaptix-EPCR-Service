# Adaptix-EPCR-Service Deployment Checklist

## Preflight
- [ ] Confirm production image tag.
- [ ] Confirm database secret.
- [ ] Confirm NEMSIS schema/code set artifacts.
- [ ] Confirm CTA/state credentials where needed.
- [ ] Confirm migrations applied.

## Deployment
- [ ] Build image.
- [ ] Push image.
- [ ] Apply migrations.
- [ ] Deploy ECS service.
- [ ] Verify stable service and logs.

## Runtime Verification
- [ ] `/healthz` passes.
- [ ] `/readyz` passes.
- [ ] Chart lifecycle test passes.
- [ ] Required NEMSIS field test passes.
- [ ] XML generation test passes.
- [ ] XSD validation passes.
- [ ] CTA/state validation passes where applicable.
- [ ] Export audit evidence persists.

## Verdict
SETUP_REQUIRED until NEMSIS production export is proven.