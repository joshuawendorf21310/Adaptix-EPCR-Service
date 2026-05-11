import sys
sys.path.insert(0, ".")
from epcr_app.nemsis_xsd_validator import NemsisXSDValidator

v = NemsisXSDValidator()
xml = '<EMSDataSet xmlns="http://www.nemsis.org"/>'
r = v.validate_xml(xml)
print("valid:", r["valid"])
print("xsd_valid:", r["xsd_valid"])
print("schematron_skipped:", r.get("schematron_skipped"))
print("xsd_errors[:2]:", r["xsd_errors"][:2])
print("execution_ms:", r["execution_ms"])
