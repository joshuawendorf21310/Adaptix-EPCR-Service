"""Tests for ``NemsisDatasetXmlBuilder``.

Asserts that the dataset-aware builder reads from
``epcr_nemsis_field_values`` (not legacy NemsisMappingRecord) and emits
one XML artifact per dataset that actually has rows. Validates EMS,
DEM, and StateDataSet emission, repeating-group occurrence preservation,
and NV/PN/xsi:nil sidecar emission as XML attributes.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from epcr_app.models import Base
from epcr_app.models_nemsis_field_values import NemsisFieldValue  # noqa: F401
from epcr_app.nemsis_dataset_xml_builder import (
    DATASET_ROOT_ELEMENT,
    DatasetBuildError,
    NemsisDatasetXmlBuilder,
)
from epcr_app.services_nemsis_field_values import (
    FieldValuePayload,
    NemsisFieldValueService,
)

NEMSIS_NS = "http://www.nemsis.org"
NS = {"n": NEMSIS_NS}


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker
    await engine.dispose()


def _payload(
    *,
    section: str,
    element_number: str,
    element_name: str,
    value=None,
    occurrence_id: str = "",
    sequence_index: int = 0,
    attributes=None,
    group_path: str = "",
) -> FieldValuePayload:
    return FieldValuePayload(
        section=section,
        element_number=element_number,
        element_name=element_name,
        value=value,
        group_path=group_path or section,
        occurrence_id=occurrence_id,
        sequence_index=sequence_index,
        attributes=attributes or {},
        source="manual",
        validation_status="unvalidated",
        validation_issues=[],
        user_id="user-1",
    )


async def _seed(session, payloads):
    for p in payloads:
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=p,
        )


@pytest.mark.asyncio
async def test_builds_only_datasets_with_rows(db) -> None:
    """No DEM rows -> no DEMDataSet artifact. No State rows -> no State."""
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="eRecord",
                    element_number="eRecord.01",
                    element_name="Patient Care Report Number",
                    value="PCR-123",
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )

    assert result.datasets() == ["EMSDataSet"]
    assert result.get("DEMDataSet") is None
    assert result.get("StateDataSet") is None


@pytest.mark.asyncio
async def test_emits_all_three_datasets_when_all_present(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="eRecord",
                    element_number="eRecord.01",
                    element_name="Patient Care Report Number",
                    value="PCR-123",
                ),
                _payload(
                    section="dPersonnel",
                    element_number="dPersonnel.01",
                    element_name="EMS Personnel ID",
                    value="P-001",
                ),
                _payload(
                    section="sState",
                    element_number="sState.01",
                    element_name="State",
                    value="CA",
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )

    datasets = sorted(result.datasets())
    assert datasets == ["DEMDataSet", "EMSDataSet", "StateDataSet"]

    for dataset, expected_element, expected_value in [
        ("EMSDataSet", "eRecord.01", "PCR-123"),
        ("DEMDataSet", "dPersonnel.01", "P-001"),
        ("StateDataSet", "sState.01", "CA"),
    ]:
        artifact = result.get(dataset)
        assert artifact is not None
        root = ET.fromstring(artifact.xml_bytes)
        assert root.tag == f"{{{NEMSIS_NS}}}{DATASET_ROOT_ELEMENT[dataset]}"
        found = root.findall(f".//n:{expected_element}", NS)
        assert len(found) == 1
        assert found[0].text == expected_value


@pytest.mark.asyncio
async def test_repeating_group_occurrences_emit_separate_elements(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="eVitals",
                    element_number="eVitals.06",
                    element_name="Systolic BP",
                    value=120,
                    occurrence_id="vital-1",
                    sequence_index=0,
                    group_path="eVitals.VitalSignsGroup",
                ),
                _payload(
                    section="eVitals",
                    element_number="eVitals.06",
                    element_name="Systolic BP",
                    value=130,
                    occurrence_id="vital-2",
                    sequence_index=1,
                    group_path="eVitals.VitalSignsGroup",
                ),
                _payload(
                    section="eVitals",
                    element_number="eVitals.06",
                    element_name="Systolic BP",
                    value=140,
                    occurrence_id="vital-3",
                    sequence_index=2,
                    group_path="eVitals.VitalSignsGroup",
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )

    artifact = result.get("EMSDataSet")
    assert artifact is not None
    root = ET.fromstring(artifact.xml_bytes)
    found = root.findall(".//n:eVitals.06", NS)
    assert [el.text for el in found] == ["120", "130", "140"]
    # Repeating-group container should be present under eVitals.
    groups = root.findall(".//n:eVitals/n:VitalSignsGroup", NS)
    assert len(groups) >= 1


@pytest.mark.asyncio
async def test_nv_pn_xsinil_sidecars_emit_as_attributes(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="ePatient",
                    element_number="ePatient.13",
                    element_name="Date of Birth",
                    value=None,
                    attributes={"NV": "7701003"},
                ),
                _payload(
                    section="eMedications",
                    element_number="eMedications.03",
                    element_name="Medication Administered",
                    value=None,
                    attributes={"PN": "8801007"},
                ),
                _payload(
                    section="eHistory",
                    element_number="eHistory.08",
                    element_name="Medication Allergies",
                    value=None,
                    attributes={"xsiNil": True},
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )

    artifact = result.get("EMSDataSet")
    assert artifact is not None
    xml = artifact.xml_bytes.decode("utf-8")

    nv_el = ET.fromstring(xml).find(".//n:ePatient.13", NS)
    assert nv_el is not None
    assert nv_el.get("NV") == "7701003"

    pn_el = ET.fromstring(xml).find(".//n:eMedications.03", NS)
    assert pn_el is not None
    assert pn_el.get("PN") == "8801007"

    nil_el = ET.fromstring(xml).find(".//n:eHistory.08", NS)
    assert nil_el is not None
    assert nil_el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"
    # xsi:nil elements must not carry a value text.
    assert (nil_el.text or "") == ""


@pytest.mark.asyncio
async def test_sha256_and_size_recorded_per_artifact(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="eRecord",
                    element_number="eRecord.01",
                    element_name="PCR Number",
                    value="PCR-1",
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
    artifact = result.get("EMSDataSet")
    assert artifact is not None
    assert re.fullmatch(r"[0-9a-f]{64}", artifact.sha256)
    assert artifact.row_count == 1
    assert len(artifact.xml_bytes) > 0


@pytest.mark.asyncio
async def test_tenant_isolation_prevents_cross_tenant_emission(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-A",
            chart_id="chart-1",
            payload=_payload(
                section="eRecord",
                element_number="eRecord.01",
                element_name="PCR Number",
                value="PCR-A",
            ),
        )
        await NemsisFieldValueService.upsert(
            session,
            tenant_id="tenant-B",
            chart_id="chart-1",
            payload=_payload(
                section="eRecord",
                element_number="eRecord.01",
                element_name="PCR Number",
                value="PCR-B",
            ),
        )

        result_a = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )
        result_b = await builder.build_for_chart(
            session, tenant_id="tenant-B", chart_id="chart-1"
        )

    a_xml = result_a.get("EMSDataSet").xml_bytes.decode("utf-8")
    b_xml = result_b.get("EMSDataSet").xml_bytes.decode("utf-8")
    assert "PCR-A" in a_xml
    assert "PCR-B" not in a_xml
    assert "PCR-B" in b_xml
    assert "PCR-A" not in b_xml


@pytest.mark.asyncio
async def test_unknown_element_skipped_with_warning(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        await _seed(
            session,
            [
                _payload(
                    section="eRecord",
                    element_number="eRecord.01",
                    element_name="PCR Number",
                    value="PCR-1",
                ),
                _payload(
                    section="eMystery",
                    element_number="eMystery.99",
                    element_name="Not a NEMSIS element",
                    value="garbage",
                ),
            ],
        )
        result = await builder.build_for_chart(
            session, tenant_id="tenant-A", chart_id="chart-1"
        )

    assert any(
        r.get("element_number") == "eMystery.99"
        for r in result.skipped_rows
    )
    artifact = result.get("EMSDataSet")
    assert "eMystery.99" not in artifact.xml_bytes.decode("utf-8")


@pytest.mark.asyncio
async def test_required_args_validated(db) -> None:
    builder = NemsisDatasetXmlBuilder()
    async with db() as session:
        with pytest.raises(DatasetBuildError):
            await builder.build_for_chart(session, tenant_id="", chart_id="x")
        with pytest.raises(DatasetBuildError):
            await builder.build_for_chart(session, tenant_id="t", chart_id="")
