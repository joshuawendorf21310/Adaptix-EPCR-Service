import asyncio, json, sys, os
os.environ["NEMSIS_XSD_PATH"]="/app/nemsis/xsd"
os.environ["NEMSIS_SCHEMATRON_PATH"]="/app/nemsis/schematron"
sys.path.insert(0,"/app")
from sqlalchemy import select
from epcr_app.db import _get_session_maker, _require_database_url
from epcr_app.models import Chart, NemsisMappingRecord
from epcr_app.nemsis_xml_builder import NemsisXmlBuilder
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator
async def main():
    Maker = _get_session_maker(_require_database_url())
    async with Maker() as s:
        chart=(await s.execute(select(Chart).where(Chart.id=="0deda819-ea1e-5524-9920-1c5c49cebfbb"))).scalar_one_or_none()
        m=list((await s.execute(select(NemsisMappingRecord).where(NemsisMappingRecord.chart_id==chart.id))).scalars())
        xml,_=NemsisXmlBuilder(chart=chart,mapping_records=m).build()
        v=NemsisXSDValidator().validate_xml(xml)
        print("VALID:",v.get("valid"),"XSD:",v.get("xsd_valid"),"SKIP:",v.get("validation_skipped"))
        print("BLOCK:",v.get("blocking_reason"))
        print("XSD_ERRS:",json.dumps(v.get("xsd_errors",[])[:8],indent=1)[:1500])
        print("SCH_ERRS:",json.dumps(v.get("schematron_errors",[])[:4],indent=1)[:600])
asyncio.run(main())