#!/usr/bin/env bash
set -eu

OUT_DIR="${1:-./nemsis-official-assets}"
mkdir -p "$OUT_DIR"

curl -L "https://nemsis.org/media/nemsis_v3/release-3.5.1/XSDs/NEMSIS_XSDs.zip" -o "$OUT_DIR/NEMSIS_XSDs.zip"
curl -L "https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/DevelopmentKit/Schematron.zip" -o "$OUT_DIR/Schematron.zip"
curl -L "https://nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/rules/StateDataSet.sch" -o "$OUT_DIR/StateDataSet.sch"
curl -L "https://cta.nemsis.org/ComplianceTestingWs/endpoints/compliancetestingws.wsdl" -o "$OUT_DIR/cta_compliance_testing.wsdl"
curl -L "https://compliance.nemsis.org/nemsisWs.wsdl" -o "$OUT_DIR/nemsis_pretest.wsdl"

echo "Downloaded official NEMSIS assets into $OUT_DIR"
