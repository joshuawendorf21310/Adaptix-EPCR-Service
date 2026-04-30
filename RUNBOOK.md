# Adaptix-EPCR-Service Runbook

## Validate
Run chart lifecycle tests, migration checks, required field validation, NEMSIS code set tests, XML generation tests, XSD/Schematron tests, and export audit tests.

## Deploy
Build a production image, push to ECR, apply migrations, deploy ECS, verify health/readiness/logs/target health, and run a production export smoke with safe test data.

## Rollback
Revert ECS to the prior known-good task definition. Do not retry export submissions blindly; preserve export attempt records and retry only idempotent or explicitly safe operations.