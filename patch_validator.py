import re, pathlib
p = pathlib.Path("/app/epcr_app/nemsis_xsd_validator.py")
s = p.read_text()
s = s.replace('os.environ.get("NEMSIS_XSD_PATH", "")', 'os.environ.get("NEMSIS_XSD_PATH", "/app/nemsis/xsd")')
s = s.replace('os.environ.get("NEMSIS_SCHEMATRON_PATH", "")', 'os.environ.get("NEMSIS_SCHEMATRON_PATH", "/app/nemsis/schematron")')
p.write_text(s)
print("OK validator patched")