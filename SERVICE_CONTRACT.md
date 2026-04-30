# Adaptix-EPCR-Service Service Contract

## Purpose
Own clinical chart truth, ePCR lifecycle, NEMSIS mapping, validation, XML generation, export status, and export audit evidence.

## API Contract
- Chart creation/update/finalization must be authenticated and tenant-scoped.
- Chart finalization must use an explicit state machine.
- NEMSIS required fields and code sets must be validated before export.
- XML generation must be deterministic and audit-backed.
- Failed validation must return user-safe correction guidance.

## Data Ownership
ePCR owns charts, chart status, validation results, NEMSIS export attempts/events, and export audit evidence.

## Failure Contract
Invalid chart data, failed XML validation, CTA/state failure, and storage failure must not be reported as successful export.