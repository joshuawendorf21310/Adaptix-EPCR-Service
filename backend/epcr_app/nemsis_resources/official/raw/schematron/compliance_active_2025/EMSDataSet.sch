<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="../utilities/html/schematronHtml.xsl"?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt2"
            id="EMSDataSet"
            schemaVersion="3.5.1.250403CP1_compliance_active_2025">
   <sch:title>NEMSIS ISO Schematron file for EMSDataSet for Compliance Active Testing (2025, v3.5.1)</sch:title>
   <sch:ns prefix="nem" uri="http://www.nemsis.org"/>
   <sch:ns prefix="xsi" uri="http://www.w3.org/2001/XMLSchema-instance"/>
   <!-- "Initialize" variables used by nemsisDiagnostic. -->
   <sch:let name="nemsisElements" value="()"/>
   <sch:let name="nemsisElementsMissing" value="''"/>
   <sch:let name="nemsisElementsMissingContext" value="()"/>
   <!-- PHASES -->
   <!-- No phases used. -->
   <!-- PATTERNS -->
   <sch:pattern id="compliance_blood">
      <sch:title>There should be a medication administration where Medication Administered is a blood product when Procedure is "Administration of blood product".</sch:title>
      <sch:rule id="compliance_blood_rule"
                context="nem:PatientCareReport[nem:eProcedures/nem:eProcedures.ProcedureGroup/nem:eProcedures.03[not(@PN)] = '116859006']">
         <sch:let name="nemsisElements"
                  value="nem:eMedications/nem:eMedications.MedicationGroup/nem:eMedications.03"/>
         <!-- To test: On case 2025-EMS-4-ArmTrauma, remove the "Transfusion of whole blood" medication administration. -->
         <sch:assert id="compliance_blood_assert"
                     role="[WARNING]"
                     diagnostics="nemsisDiagnostic"
                     test="nem:eMedications/nem:eMedications.MedicationGroup/nem:eMedications.03 = ('116762002', '116795008', '116861002', '116865006', '180208003', '33389009', '71493000')">
      There should be a medication administration where Medication Administered is a blood product when Procedure is "Transfusion of blood product". This is a validation message for compliance active testing for 2025 for NEMSIS v3.5.1.
      </sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="compliance_insured">
      <sch:title>Last Name of the Insured should match the patient's Last Name when Relationship to the Insured is Self.</sch:title>
      <sch:rule id="compliance_insured_rule"
                context="nem:ePayment.InsuranceGroup[nem:ePayment.22 = '2622001']">
         <sch:let name="nemsisElements"
                  value="(nem:ePayment.22, nem:ePayment.19, ancestor::nem:PatientCareReport/nem:ePatient/nem:ePatient.PatientNameGroup/nem:ePatient.02)"/>
         <sch:let name="nemsisElementsMissing"
                  value=".[not(nem:ePayment.19)]/'ePayment.19'"/>
         <!-- To test: On case 2025-EMS-2-HeatStroke or EMS-4-ArmTrauma, change the patient's Last Name or change Last Name of the Insured. -->
         <sch:assert id="compliance_insured_assert"
                     role="[ERROR]"
                     diagnostics="nemsisDiagnostic"
                     test="nem:ePayment.19 = ancestor::nem:PatientCareReport/nem:ePatient/nem:ePatient.PatientNameGroup/nem:ePatient.02">
        Last Name of the Insured should match the patient's Last Name when Relationship to the Insured is Self. This is a validation message for compliance active testing for 2025 for NEMSIS v3.5.1.
      </sch:assert>
      </sch:rule>
   </sch:pattern>
   <!-- DIAGNOSTICS -->
   <sch:diagnostics>

    <?DSDL_INCLUDE_START includes/diagnostic_nemsisDiagnostic.xml?>
      <sch:diagnostic id="nemsisDiagnostic">

      <!-- This is the NEMSIS national diagnostic. It must exist in every NEMSIS Schematron document, 
          and it should be referenced by every assert and report. It provides nationally-
          standardized, structured data to communicate which data elements are of interest in a 
          failed assert or successful report. -->
         <nemsisDiagnostic xmlns="http://www.nemsis.org"
                           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    
        <!-- Elements that uniquely identify the record where the problem happened. -->
            <record>
               <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
               <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
               <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
               <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
               <xsl:if test="ancestor-or-self::*[@UUID]">
                  <UUID>
                     <xsl:value-of select="ancestor-or-self::*[@UUID][1]/@UUID"/>
                  </UUID>
               </xsl:if>
            </record>
            <!-- Elements that the user may want to revisit to resolve the problem, along with their values. -->
            <elements>
               <xsl:for-each select="$nemsisElements">
                  <xsl:element name="element">
                     <xsl:attribute name="location">
                        <xsl:apply-templates select="." mode="schematron-get-full-path"/>
                     </xsl:attribute>
                     <xsl:for-each select="@*">
                        <xsl:attribute name="{name()}">
                           <xsl:value-of select="."/>
                        </xsl:attribute>
                     </xsl:for-each>
                     <xsl:if test="not(*)">
                        <xsl:value-of select="."/>
                     </xsl:if>
                  </xsl:element>
               </xsl:for-each>
            </elements>
            <!-- Elements that were missing, that the user may want to visit to resolve the problem. -->
            <elementsMissing>
               <xsl:variable name="default_context" select="."/>
               <xsl:for-each select="tokenize($nemsisElementsMissing, ' ')">
                  <xsl:variable name="parent"
                                select="$nemsisElementsMissingContext[contains(local-name(), substring-before(current(), '.'))][1]"/>
                  <element>
                     <xsl:attribute name="parentLocation">
                        <xsl:choose>
                           <xsl:when test="$parent">
                              <xsl:apply-templates select="$parent" mode="schematron-get-full-path"/>
                           </xsl:when>
                           <xsl:otherwise>
                              <xsl:apply-templates select="$default_context" mode="schematron-get-full-path"/>
                           </xsl:otherwise>
                        </xsl:choose>
                     </xsl:attribute>
                     <xsl:attribute name="name">
                        <xsl:value-of select="."/>
                     </xsl:attribute>
                  </element>
               </xsl:for-each>
            </elementsMissing>
         </nemsisDiagnostic>
      </sch:diagnostic>
      <?DSDL_INCLUDE_END includes/diagnostic_nemsisDiagnostic.xml?>
   </sch:diagnostics>
   <!-- PROPERTIES -->
   <sch:properties/>
</sch:schema>
