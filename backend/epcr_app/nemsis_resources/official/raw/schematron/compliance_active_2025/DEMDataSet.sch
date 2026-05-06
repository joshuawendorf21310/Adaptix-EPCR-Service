<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="../utilities/html/schematronHtml.xsl"?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt2"
            id="DEMDataSet"
            schemaVersion="3.5.1.250403CP1_compliance_active_2025">
   <sch:title>NEMSIS ISO Schematron file for DEMDataSet for Compliance Active Testing (2025, v3.5.1)</sch:title>
   <sch:ns prefix="nem" uri="http://www.nemsis.org"/>
   <sch:ns prefix="xsi" uri="http://www.w3.org/2001/XMLSchema-instance"/>
   <!-- "Initialize" variables used by nemsisDiagnostic. -->
   <sch:let name="nemsisElements" value="()"/>
   <sch:let name="nemsisElementsMissing" value="''"/>
   <sch:let name="nemsisElementsMissingContext" value="()"/>
   <!-- PHASES -->
   <!-- No phases used. -->
   <!-- PATTERNS -->
   <sch:pattern id="compliance_statistical_year">
      <sch:title>There should be a set of agency annual statistics where Statistical Calendar Year is 2023 or later.</sch:title>
      <sch:rule id="compliance_statistical_year_rule" context="nem:dAgency">
         <sch:let name="nemsisElements"
                  value="nem:dAgency.AgencyYearGroup/nem:dAgency.15"/>
         <sch:let name="nemsisElementsMissing"
                  value=".[not(nem:dAgency.AgencyYearGroup)]/'dAgency.15'"/>
         <!-- To test: Change Statistical Calendar Year on the 2023 agency year group to an earlier year or remove it.  -->
         <sch:assert id="compliance_statistical_year_assert"
                     role="[WARNING]"
                     diagnostics="nemsisDiagnostic"
                     test="nem:dAgency.AgencyYearGroup/nem:dAgency.15[. != '' and xs:integer(.) ge 2023] ">
        There should be a set of agency annual statistics where Statistical Calendar Year is 2023 or later. This is a validation message for compliance active testing for 2025 for NEMSIS v3.5.1.
      </sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="compliance_personnel_license">
      <sch:title>EMS Personnel's State's Licensure ID Number should be the letters "EMT" followed by 5 to 7 digits when Licensure Level is Emergency Medical Technician (EMT) and State of Licensure is Florida.</sch:title>
      <sch:rule id="compliance_personnel_license_rule"
                context="nem:dPersonnel.LicensureGroup[nem:dPersonnel.22 = '12' and nem:dPersonnel.24 = '9925005']">
         <sch:let name="nemsisElements"
                  value="(nem:dPersonnel.22, nem:dPersonnel.23, nem:dPersonnel.24)"/>
         <sch:let name="nemsisElementsMissing"
                  value=".[not(nem:dPersonnel.23)]/'dPersonnel.23'"/>
         <!-- To test: On a personnel license at the EMT level in Florida, remove "EMT" from the license number. -->
         <sch:assert id="compliance_personnel_license_assert"
                     role="[ERROR]"
                     diagnostics="nemsisDiagnostic"
                     test="matches(nem:dPersonnel.23, '^EMT\d{5,7}$')">
        EMS Personnel's State's Licensure ID Number should be the letters "EMT" followed by at 5 to 7 digits when Licensure Level is Emergency Medical Technician (EMT) and State of Licensure is Florida. This is a validation message for compliance active testing for 2025 for NEMSIS v3.5.1.
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
