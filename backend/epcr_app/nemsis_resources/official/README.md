# Official NEMSIS Public Source Artifacts

These artifacts are normalized copies of files from the official NEMSIS public
Git repository at:

    https://git.nemsis.org/scm/nep/nemsis_public.git

The exact source commit, branch, retrieval timestamp, and per-artifact SHA-256
are recorded in `manifest.json`.

## Layout

```
official/
  manifest.json                  -- Source repo + commit + per-artifact SHA-256.
  raw/
    xsd_ems/, xsd_dem/, xsd_state/   -- Per-dataset NEMSIS XSDs (verbatim).
    schematron/                       -- Sample Schematron rules (verbatim).
    data_dictionary/                  -- Pipe-delimited element/attribute dictionaries.
    sample_custom_elements/           -- Sample eCustom XML fragments (NOT configured eCustom).
  normalized/
    fields.json                       -- Field metadata derived from data_dictionary.
    element_enumerations.json         -- Element enumeration codes/displays.
    attribute_enumerations.json       -- Attribute enumeration codes/displays.
    defined_lists.json                -- Defined-list catalog (envelopes from defined_lists/).
    required_elements.json            -- National/State required-level summary.
    registry_snapshot.json            -- Top-level coverage snapshot.
```

## Critical no-drift rules

- Runtime services NEVER fetch from `git.nemsis.org`. They read the
  pre-normalized files in `normalized/` only.
- The importer is a developer/CI artifact that reads `raw/` (or a fresh clone)
  and writes `normalized/` deterministically.
- Sample custom-element XML is recorded as evidence ONLY. It is NOT promoted
  into the configured eCustom catalog. Slice 4 (`nemsis_custom_elements`) stays
  empty / `not_configured` until an agency publishes its own eCustom
  configuration.
- `source_mode` is reported honestly: the importer never claims `official_full`
  unless every required artifact class is present and parsed.
