from __future__ import annotations

import argparse
import json
from pathlib import Path

from epcr_app.nemsis_registry_importer import (
    DEFAULT_OFFICIAL_DIR,
    DICTIONARY_VERSION_351,
    NemsisRegistryNormalizer,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic NEMSIS registry artifacts.")
    parser.add_argument("--dictionary-version", required=True)
    parser.add_argument("--source", type=Path, required=False, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--source-branch", default="master")
    parser.add_argument("--retrieved-at", default=None)
    return parser.parse_args()


def _resolve_normalizer_inputs(source: Path | None) -> tuple[Path | None, Path | None]:
    if source is None:
        return DEFAULT_OFFICIAL_DIR, None
    source = source.resolve()
    if (source / "raw").exists():
        return source, None
    return DEFAULT_OFFICIAL_DIR, source


def _render_ts_fields(fields: list[dict[str, object]]) -> str:
    payload = json.dumps(fields, indent=2, ensure_ascii=True)
    return (
        f'export const NEMSIS_DICTIONARY_VERSION = "{DICTIONARY_VERSION_351}" as const;\n\n'
        f"export const NEMSIS_FIELD_CONTRACTS = {payload} as const;\n"
    )


def _render_py_fields(fields: list[dict[str, object]]) -> str:
    payload = json.dumps(fields, indent=2, ensure_ascii=True)
    return (
        f'DICTIONARY_VERSION = "{DICTIONARY_VERSION_351}"\n\n'
        f"NEMSIS_FIELD_CONTRACTS = {payload}\n"
    )


def main() -> int:
    args = _parse_args()
    if args.dictionary_version != DICTIONARY_VERSION_351:
        raise SystemExit(
            f"Only dictionary version {DICTIONARY_VERSION_351} is supported by this generator."
        )

    official_dir, source_clone = _resolve_normalizer_inputs(args.source)
    normalizer = NemsisRegistryNormalizer(
        official_dir=official_dir,
        source_clone=source_clone,
        source_commit=args.source_commit,
        source_branch=args.source_branch,
        retrieved_at=args.retrieved_at,
    )
    result = normalizer.run(local_seed_fallback_count=0)
    normalizer.write_normalized_outputs(result)

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        out_dir / "fields.json": result.fields,
        out_dir / "code_sets.json": result.code_sets,
        out_dir / "validation_rules.json": result.validation_rules,
        out_dir / "sections.json": result.sections,
        out_dir / "field_contracts.ts": _render_ts_fields(result.fields),
        out_dir / "field_contracts.py": _render_py_fields(result.fields),
    }
    for path, payload in outputs.items():
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "dictionary_version": DICTIONARY_VERSION_351,
                "field_count": result.snapshot["field_count"],
                "baseline_counts_match": result.snapshot["baseline_counts_match"],
                "out_dir": str(out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())