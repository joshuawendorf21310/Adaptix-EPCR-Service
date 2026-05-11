from __future__ import annotations

import xml.etree.ElementTree as ET

from epcr_app.nemsis_exporter import NEMSISExporter


def test_nemsis_export_uses_incident_response_and_pcr_numbers() -> None:
    exporter = NEMSISExporter()
    xml_bytes = exporter.export_chart(
        chart_dict={
            "id": "chart-001",
            "incident_number": "2026-MADISONEMS-000001",
            "response_number": "2026-MADISONEMS-000001-R01",
            "pcr_number": "2026-MADISONEMS-000001-PCR01",
            "billing_case_number": "2026-MADISONEMS-000001-BILL01",
            "priority": "2305001",
        },
        agency_info={
            "state_code": "55",
            "agency_number": "123456",
            "agency_name": "Madison EMS",
        },
    )

    root = ET.fromstring(xml_bytes)
    ns = {"n": "http://www.nemsis.org"}
    assert root.find(".//n:eRecord/n:eRecord.01", ns).text == "2026-MADISONEMS-000001-PCR01"
    assert root.find(".//n:eResponse/n:eResponse.03", ns).text == "2026-MADISONEMS-000001"
    assert root.find(".//n:eResponse/n:eResponse.04", ns).text == "2026-MADISONEMS-000001-R01"
    xml_text = xml_bytes.decode("utf-8")
    assert "2026-MADISONEMS-000001-BILL01" not in xml_text