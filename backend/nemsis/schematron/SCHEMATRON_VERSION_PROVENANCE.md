# NEMSIS Schematron Pack — Source-of-Truth Provenance

This document records the provenance of the schematron pack bundled with
the Adaptix-EPCR-Service image so CI / ops can prove the in-tree copy
matches the current public NEMSIS release.

## Expected NEMSIS build

- **Build identifier:** `3.5.1.251001CP2`
- **Release line:** NEMSIS v3.5.1 — Build 251001, Critical Patch 2
- **As-of date:** 2026-05-10

All version-string constants in `epcr_app/` (`nemsis_exporter.py`,
`nemsis_dataset_xml_builder.py`, `nemsis_xml_builder.py`,
`api_version.py`, `api_cta_testing.py`, `nemsis/cta_html_to_xml.py`,
`nemsis/nemsis_coded_values.py`) are pinned to this build.

## Currently bundled schematron files

Bundled artifacts live at
`backend/compliance/nemsis/schematron/`:

| Filename                  | SHA-256                                                            | Size (bytes) |
|---------------------------|--------------------------------------------------------------------|--------------|
| `nemsis-schematron.sch`   | `b9a98568fa16edf809f73d7bc8fd28620dfef4a15614c07b884eda88b1804afd` | 6972         |
| `nemsis-schematron.xsl`   | `27be75ef318728c2534da5e428d767a7885a323ce790eba5958c5ef7bdcf3239` | 22641        |

> WARNING: As of 2026-05-10 these bundled files PRE-DATE Build
> `3.5.1.251001CP2`. They were inherited from the earlier `250403CP1`
> pack and have NOT yet been re-downloaded from the public NEMSIS
> mirror. The Python module constants have been bumped to the current
> build; the schematron artefacts must follow before this service is
> claimed conformant. Use the refresh runbook below.

## Expected source URLs (public NEMSIS mirror)

The authoritative public copies for Build `3.5.1.251001CP2` are
published under the NEMSIS v3.5.1 release tree:

- **Sample EMS dataset:**
  `https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/SampleEMSDataSet.sch`
- **Sample DEM dataset:**
  `https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/SampleDEMDataSet.sch`
- **Sample State dataset:**
  `https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/SampleStateDataSet.sch`

Per-build hosted copies (Build-pinned URLs) live under
`https://nemsis.org/media/nemsis_v3/3.5.1.251001CP2/Schematron/` and
are the preferred source for reproducible CI pinning.

## To-refresh runbook (one-line shell)

CI / ops should run the following from the repository root to confirm
that the bundled `.sch` file is byte-identical to the current public
release of `SampleEMSDataSet.sch`:

```bash
curl -fsSL https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/SampleEMSDataSet.sch | sha256sum - && sha256sum backend/compliance/nemsis/schematron/nemsis-schematron.sch
```

If the two sha256 sums diverge, replace the bundled file with the
upstream download and update the SHA-256 table above:

```bash
curl -fsSL https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/SampleEMSDataSet.sch -o backend/compliance/nemsis/schematron/nemsis-schematron.sch && sha256sum backend/compliance/nemsis/schematron/nemsis-schematron.sch
```

For the DEM and State variants, swap `SampleEMSDataSet.sch` for
`SampleDEMDataSet.sch` / `SampleStateDataSet.sch` and update the
matching pair of bundled `.sch` files (currently only the EMS variant
is bundled — DEM and State variants ship via the
`backend/epcr_app/nemsis_resources/official/raw/schematron/` tree).

## Audit log

| Date       | Action                                                                  | Author            |
|------------|-------------------------------------------------------------------------|-------------------|
| 2026-05-10 | Recorded current bundled SHA-256, pinned Python constants to 251001CP2  | Adaptix EPCR team |
