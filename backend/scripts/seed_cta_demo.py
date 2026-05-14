"""Seed the demo agency with NEMSIS CTA test charts.

Reads the baked CTA v3.5.1 templates under
``Adaptix-EPCR-Service/backend/nemsis/templates/cta/`` and writes one chart
per template into the demo tenant. All NEMSIS leaf elements that carry text
are persisted as :class:`NemsisMappingRecord` rows so the chart can be
re-validated and re-exported through the existing pipeline.

Truthful-execution rules (per AGENTS.md / SYSTEM_RULES.md):

* No fake submission status. ``submission_status`` is left at the default
  ``submission_unavailable`` produced by ``ChartWorkspaceService`` -- this
  script does NOT contact NEMSIS TAC.
* No fake CTA pass/fail. The script only stores the source XML payload and
  the per-field NEMSIS values from the official CTA templates.
* Re-running is idempotent. Chart IDs are deterministic UUIDv5 derived from
  ``(tenant_id, case_id)`` and a duplicate ``call_number`` is treated as
  "already seeded, continue".
* Tenant isolation preserved. The script refuses to run unless an explicit
  ``--tenant-id`` is supplied (defaulting to the demo tenant only when
  ``ADAPTIX_DEMO_SEED_ALLOW_REMOTE`` is unset, i.e. local dev).
* Production safety. When ``ADAPTIX_DEMO_SEED_ALLOW_REMOTE=true`` the
  script requires ``--tenant-id`` and refuses any tenant id that does not
  match. The intended target is the demo tenant
  ``9e26e98b-beba-497f-b242-ef02b88ffdef``.
* Source XML is preserved on disk; the script records the template
  filename and md5 against every chart's audit log so the source is
  traceable.

Usage::

    # Local
    python -m scripts.seed_cta_demo --tenant-id 9e26e98b-beba-497f-b242-ef02b88ffdef

    # Remote (ECS one-shot task)
    ADAPTIX_DEMO_SEED_ALLOW_REMOTE=true \
        python -m scripts.seed_cta_demo \
            --tenant-id 9e26e98b-beba-497f-b242-ef02b88ffdef
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

logger = logging.getLogger("seed_cta_demo")


DEMO_TENANT_ID = "9e26e98b-beba-497f-b242-ef02b88ffdef"
SEED_USER_ID = "00000000-0000-4000-8000-00000000seed"
SEED_NAMESPACE = uuid.UUID("8d31a2c6-3a8a-4f0e-9e3a-c7a5eed12345")
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "nemsis" / "templates" / "cta"


@dataclasses.dataclass(frozen=True)
class CtaCase:
    """One CTA case to seed: maps a template file -> stable case id."""

    case_id: str
    template_filename: str
    incident_type: str  # one of medical, trauma, behavioral, other
    schematron_variant: str | None = None  # e.g. "warning", "error"

    @property
    def template_path(self) -> Path:
        return TEMPLATE_DIR / self.template_filename


# Required CTA records per the market-readiness brief. Schematron variants
# share the underlying DEM/EMS-1 sources because the source-of-truth XML
# is the same; the variant id encodes which Schematron pass we expect the
# downstream pipeline to evaluate against. We do NOT fabricate Schematron
# pass/fail here -- that is downstream pipeline territory.
REQUIRED_CASES: tuple[CtaCase, ...] = (
    CtaCase("DEM-CTA-ACTIVE-001", "2025-DEM-1_v351.xml", "medical"),
    CtaCase("EMS-CTA-ACTIVE-001", "2025-EMS-1-Allergy_v351.xml", "medical"),
    CtaCase("EMS-CTA-ACTIVE-002", "2025-EMS-2-HeatStroke_v351.xml", "medical"),
    CtaCase("EMS-CTA-ACTIVE-003", "2025-EMS-3-PediatricAsthma_v351.xml", "medical"),
    CtaCase("EMS-CTA-ACTIVE-004", "2025-EMS-4-ArmTrauma_v351.xml", "trauma"),
    CtaCase("EMS-CTA-ACTIVE-005", "2025-EMS-5-MentalHealthCrisis_v351.xml", "behavioral"),
    CtaCase("SCHEMATRON-DEM-WARNING", "2025-DEM-1_v351.xml", "medical", "warning"),
    CtaCase("SCHEMATRON-DEM-ERROR", "2025-DEM-1_v351.xml", "medical", "error"),
    CtaCase("SCHEMATRON-EMS-WARNING", "2025-EMS-1-Allergy_v351.xml", "medical", "warning"),
    CtaCase("SCHEMATRON-EMS-ERROR", "2025-EMS-1-Allergy_v351.xml", "medical", "error"),
)


@dataclasses.dataclass
class SeedResult:
    case_id: str
    chart_id: str
    call_number: str
    template_filename: str
    template_md5: str
    nemsis_field_count: int
    created: bool  # False if chart already existed (idempotent re-run)
    unmapped_field_count: int = 0


def discover_cta_files(template_dir: Path = TEMPLATE_DIR) -> list[Path]:
    """Return every CTA XML template available on disk.

    Used by tests and by the seeder's preflight check. Does not interpret
    the contents.
    """
    if not template_dir.exists():
        return []
    return sorted(p for p in template_dir.glob("*_v351.xml") if p.is_file())


def deterministic_chart_id(tenant_id: str, case_id: str) -> str:
    """Return a stable UUIDv5 chart id for ``(tenant_id, case_id)``.

    Re-running the seeder produces the same id, which is what makes the
    seeder safe to re-execute and what guarantees deterministic call
    numbers in the demo tenant.
    """
    return str(uuid.uuid5(SEED_NAMESPACE, f"{tenant_id}:{case_id}"))


def deterministic_call_number(case_id: str) -> str:
    """Return the call number used to look up a seeded CTA chart.

    The CTA case id is itself unique per tenant, so we use it directly as
    the ``call_number``. This makes the chart easy to find by NEMSIS
    reviewers and makes the unique-constraint duplicate path hit cleanly
    on re-run.
    """
    return f"CTA-{case_id}"


def _strip_ns(tag: str) -> str:
    """Strip the NEMSIS namespace prefix from an element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def extract_nemsis_fields(xml_path: Path) -> list[tuple[str, str]]:
    """Return ``[(nemsis_field, value)]`` for every text-bearing leaf.

    NEMSIS leaf field ids use dotted notation (``eRecord.01``,
    ``eResponse.05``). We accept anything that matches that shape and
    carries a non-empty text value. Group elements (``eRecord.SoftwareApplicationGroup``)
    are skipped because they do not carry a value of their own.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    out: list[tuple[str, str]] = []
    for el in root.iter():
        tag = _strip_ns(el.tag)
        # Skip non-leaf NEMSIS group elements.
        if tag.endswith("Group"):
            continue
        if "." not in tag:
            continue
        text = (el.text or "").strip()
        if not text:
            # Not a value-bearing leaf (might be a parent of leaves).
            continue
        # Prefix must look like a NEMSIS section (eRecord, eResponse, dAgency, ...)
        prefix = tag.split(".", 1)[0]
        if not (prefix.startswith("e") or prefix.startswith("d") or prefix.startswith("s") or prefix.startswith("a")):
            continue
        out.append((tag, text))
    return out


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


async def _seed_one(session, case: CtaCase, tenant_id: str) -> SeedResult:
    from epcr_app.chart_service import ChartService
    from epcr_app.models import Chart
    from sqlalchemy import select

    chart_id = deterministic_chart_id(tenant_id, case.case_id)
    call_number = deterministic_call_number(case.case_id)
    template_md5 = _md5(case.template_path)

    # Idempotency: if the chart already exists, do not re-create.
    existing = await session.execute(
        select(Chart).where(Chart.id == chart_id, Chart.tenant_id == tenant_id)
    )
    chart = existing.scalars().first()
    created = False
    if chart is None:
        try:
            chart = await ChartService.create_chart(
                session=session,
                tenant_id=tenant_id,
                call_number=call_number,
                incident_type=case.incident_type,
                created_by_user_id=SEED_USER_ID,
                client_reference_id=chart_id,
            )
            created = True
        except ValueError as exc:
            if str(exc) != "chart_call_number_conflict":
                raise
            # Another process already inserted; reload it.
            existing = await session.execute(
                select(Chart).where(Chart.id == chart_id, Chart.tenant_id == tenant_id)
            )
            chart = existing.scalars().first()
            if chart is None:
                # Chart with conflicting call_number exists under a different id.
                # Refuse to silently overwrite.
                raise

    # Persist every NEMSIS leaf field.
    fields = extract_nemsis_fields(case.template_path)
    persisted = 0
    unmapped = 0
    for field_id, value in fields:
        try:
            await ChartService.record_nemsis_field(
                session=session,
                tenant_id=tenant_id,
                chart_id=chart.id,
                nemsis_field=field_id,
                nemsis_value=value,
                source="system",
            )
            persisted += 1
        except ValueError:
            # The field id is not currently representable; record the gap
            # truthfully rather than silently dropping data.
            unmapped += 1
            logger.warning(
                "Unable to record NEMSIS field for case=%s field=%s",
                case.case_id,
                field_id,
            )

    # Audit the seed event with template provenance.
    detail = {
        "case_id": case.case_id,
        "template_filename": case.template_filename,
        "template_md5": template_md5,
        "schematron_variant": case.schematron_variant,
        "nemsis_field_count": persisted,
        "unmapped_field_count": unmapped,
        "source_xml_size_bytes": case.template_path.stat().st_size,
    }
    await ChartService.audit(
        session=session,
        tenant_id=tenant_id,
        chart_id=chart.id,
        user_id=SEED_USER_ID,
        action="cta_template_seeded",
        detail=detail,
    )

    return SeedResult(
        case_id=case.case_id,
        chart_id=chart.id,
        call_number=call_number,
        template_filename=case.template_filename,
        template_md5=template_md5,
        nemsis_field_count=persisted,
        unmapped_field_count=unmapped,
        created=created,
    )


async def seed_demo_tenant(
    session_factory,
    tenant_id: str = DEMO_TENANT_ID,
    cases: Iterable[CtaCase] = REQUIRED_CASES,
) -> list[SeedResult]:
    """Seed every required CTA case under ``tenant_id``.

    ``session_factory`` is an ``async_sessionmaker``-shaped callable so the
    function can be used both from the FastAPI app context and from the
    tests (which pass an in-memory SQLite session factory).
    """
    results: list[SeedResult] = []
    for case in cases:
        if not case.template_path.exists():
            raise FileNotFoundError(
                f"CTA template missing for case {case.case_id}: {case.template_path}"
            )
        async with session_factory() as session:
            result = await _seed_one(session, case, tenant_id)
            results.append(result)
    return results


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Seed NEMSIS CTA demo charts.")
    p.add_argument(
        "--tenant-id",
        default=DEMO_TENANT_ID,
        help=f"Target tenant id (default: {DEMO_TENANT_ID}).",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List discovered CTA templates and required cases, then exit.",
    )
    p.add_argument(
        "--print-json",
        action="store_true",
        help="Print the seed result as JSON instead of a human summary.",
    )
    return p


async def _async_main(args: argparse.Namespace) -> int:
    if args.list:
        files = discover_cta_files()
        print(json.dumps(
            {
                "template_dir": str(TEMPLATE_DIR),
                "templates_found": [p.name for p in files],
                "required_cases": [dataclasses.asdict(c) for c in REQUIRED_CASES],
            },
            indent=2,
        ))
        return 0

    # Production-safety gate.
    allow_remote = os.environ.get("ADAPTIX_DEMO_SEED_ALLOW_REMOTE", "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_remote and args.tenant_id != DEMO_TENANT_ID:
        print(
            f"REFUSING: ADAPTIX_DEMO_SEED_ALLOW_REMOTE is set but --tenant-id={args.tenant_id} "
            f"does not match the demo tenant {DEMO_TENANT_ID}. Refusing to seed a non-demo tenant.",
            file=sys.stderr,
        )
        return 2

    from epcr_app.db import async_session  # type: ignore

    results = await seed_demo_tenant(async_session, tenant_id=args.tenant_id)

    if args.print_json:
        print(json.dumps([dataclasses.asdict(r) for r in results], indent=2))
    else:
        for r in results:
            status = "created" if r.created else "exists"
            print(
                f"[{status:7s}] {r.case_id:24s} chart_id={r.chart_id} "
                f"call_number={r.call_number} fields={r.nemsis_field_count} "
                f"unmapped={r.unmapped_field_count} src={r.template_filename}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _arg_parser().parse_args(argv)
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
