import asyncio
from epcr_app.db import _get_session_maker, _require_database_url
from epcr_app.models import Chart, NemsisMappingRecord
from sqlalchemy import select


async def main():
    async with _get_session_maker(_require_database_url())() as s:
        chart = (await s.execute(select(Chart).where(Chart.id == "0deda819-ea1e-5524-9920-1c5c49cebfbb"))).scalar_one()
        mappings = list(
            (
                await s.execute(
                    select(NemsisMappingRecord).where(
                        NemsisMappingRecord.chart_id == "0deda819-ea1e-5524-9920-1c5c49cebfbb"
                    )
                )
            ).scalars()
        )
    fv = {}
    for r in mappings:
        fv.setdefault(r.nemsis_field, []).append(r.nemsis_value)
    print("eResponse.04 in DB ->", fv.get("eResponse.04"))
    print("eResponse.05 in DB ->", fv.get("eResponse.05"))
    print("eTimes.01 in DB ->", fv.get("eTimes.01"))
    print(
        "chart attrs:",
        getattr(chart, "nemsis_template_id", None),
        getattr(chart, "nemsis_test_case_id", None),
        getattr(chart, "test_case_id", None),
        getattr(chart, "scenario_code", None),
    )
    # Now run the actual builder and inspect the produced eResponse.05/eTimes.01.
    from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
    builder = NemsisXmlBuilder(chart=chart, mapping_records=mappings)
    xml_bytes, _w = builder.build()
    from lxml import etree as LET
    root = LET.fromstring(xml_bytes)
    ns = {"n": "http://www.nemsis.org", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    for elem_path in ("n:eResponse.05", "n:eTimes.01"):
        for found in root.iterfind(f".//{elem_path}", ns):
            print(elem_path, "text=", repr(found.text), "nil=", found.get(f"{{{ns['xsi']}}}nil"))
    print("ROOT TAG:", root.tag)


asyncio.run(main())
