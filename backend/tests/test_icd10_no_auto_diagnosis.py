"""Hard contract test: the ICD-10 documentation specificity service
must NEVER auto-assign a diagnosis.

This test enforces the pillar's central invariant from two angles:

1. Behavioral: ``generate_prompts_for_chart`` produces rows whose
   ``provider_selected_code`` is ``None`` and ``provider_acknowledged``
   is ``False``. Only the explicit ``acknowledge`` flow can change those
   fields.

2. Source-level: the implementation file must not contain forbidden
   phrases that would imply the system reaches a clinical conclusion
   on its own (``auto-assign``, ``auto-select``, ``diagnose``). The
   only exception is the documented prohibition itself, which we
   detect by allowing those words only inside lines that also contain
   the words ``must never``, ``never``, ``NEVER``, ``do not``,
   ``forbidden``, ``refuses``, or the prompt-kind constant
   ``symptom_vs_diagnosis`` (which is a vocabulary token, not an
   action).
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import (
    Assessment,
    Base,
    Chart,
    ChartStatus,
)
from epcr_app.services import icd10_service


@pytest_asyncio.fixture
async def session_with_chart():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessionmaker() as session:
        chart = Chart(
            id=str(uuid4()),
            tenant_id="t1",
            call_number="CALL-1",
            incident_type="medical",
            status=ChartStatus.NEW,
            created_by_user_id="user-1",
        )
        session.add(chart)
        a = Assessment(
            id=str(uuid4()),
            chart_id=chart.id,
            tenant_id="t1",
            chief_complaint="chest pain radiating",
            field_diagnosis="possible MVC injury, fall from height",
            impression_notes="abdominal tenderness",
            documented_at=datetime.now(UTC),
        )
        session.add(a)
        await session.commit()
        yield session, chart
    await engine.dispose()


async def test_generate_never_sets_provider_selected_code(session_with_chart):
    session, chart = session_with_chart
    prompts = await icd10_service.generate_prompts_for_chart(
        session, "t1", chart.id
    )
    assert prompts, "expected heuristics to fire for this complaint"
    for p in prompts:
        assert p.provider_selected_code is None, (
            "ICD-10 service must NEVER set provider_selected_code at "
            "generate time; only candidate_codes_json is allowed"
        )
        assert p.provider_acknowledged is False
        assert p.provider_selected_at is None
        # candidate_codes_json may or may not be present, but must never
        # be interpreted as a selection.
        if p.candidate_codes_json is not None:
            assert "code" in p.candidate_codes_json
            assert "description" in p.candidate_codes_json


def test_source_has_no_forbidden_auto_diagnosis_phrases():
    """Scan icd10_service.py for forbidden phrases.

    A line is forbidden if it contains one of ``auto-assign``,
    ``auto-select``, or ``diagnose`` AND does NOT also contain a
    prohibition/disclaimer marker.
    """
    source_path = Path(inspect.getsourcefile(icd10_service))
    text = source_path.read_text(encoding="utf-8")
    forbidden = re.compile(r"auto-assign|auto-select|diagnose", re.IGNORECASE)
    disclaimer = re.compile(
        r"must never|never|NEVER|do not|forbidden|refuses|symptom_vs_diagnosis|"
        r"field_diagnosis|prohibition",
        re.IGNORECASE,
    )

    offending: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if forbidden.search(line) and not disclaimer.search(line):
            offending.append(f"{line_no}: {line.strip()}")

    assert not offending, (
        "icd10_service.py contains forbidden auto-diagnosis phrasing:\n"
        + "\n".join(offending)
    )
