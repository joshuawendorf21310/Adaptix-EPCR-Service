<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="//nemsis.org/media/nemsis_v3/release-3.5.1/Schematron/utilities/html/schematronHtml.xsl"?>
<sch:schema xmlns:sch="http://purl.oclc.org/dsdl/schematron"
            xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
            queryBinding="xslt2"
            id="DEMDataSet"
            schemaVersion="3.5.1.251001CP2_compliance_pretesting_2026">
   <sch:title>NEMSIS ISO Schematron file for DEMDataSet for Compliance Pre-testing (2026, v3.5.1)</sch:title>
   <sch:ns prefix="nem" uri="http://www.nemsis.org"/>
   <sch:ns prefix="xsi" uri="http://www.w3.org/2001/XMLSchema-instance"/>
   <!-- "Initialize" variables used by nemsisDiagnostic. -->
   <sch:let name="nemsisElements" value="()"/>
   <sch:let name="nemsisElementsMissing" value="''"/>
   <sch:let name="nemsisElementsMissingContext" value="()"/>
   <!-- PHASES -->
   <!-- No phases used. -->
   <!-- PATTERNS -->
   <sch:pattern id="compliance_ambulance_cost">
      <sch:title>Initial Vehicle Cost should be between $100,000 and $300,000 when Vehicle Type is "Ambulance".</sch:title>
      <sch:rule id="compliance_ambulance_cost_rule"
                context="nem:dVehicle.09[../nem:dVehicle.04 = '1404001']">
         <sch:let name="nemsisElements" value="., ../nem:dVehicle.04"/>
         <!-- To test: Change Initial Vehicle Cost to more than $300,000 on a vehicle that is an ambulance. -->
         <sch:assert id="compliance_ambulance_cost_assert"
                     role="[WARNING]"
                     diagnostics="nemsisDiagnostic"
                     test="xs:integer(.) ge 100000 and xs:integer(.) le 300000">
      Initial Vehicle Cost should be between $100,000 and $300,000 when Vehicle Type is "Ambulance". This is a validation message for compliance pre-testing for 2026 for NEMSIS v3.5.1.
      </sch:assert>
      </sch:rule>
   </sch:pattern>
   <sch:pattern id="compliance_contact_phone">
      <sch:title>The Agency Contact Phone Number list should include a mobile phone number.</sch:title>
      <sch:rule id="compliance_contact_phone_rule"
                context="nem:dContact.ContactInfoGroup">
         <sch:let name="nemsisElements" value="nem:dContact.10"/>
         <sch:let name="nemsisElementsMissing"
                  value=".[not(nem:dContact.10)]/'dContact.10'"/>
         <!-- To test: On an agency contact, remove the mobile phone number or change its type to something other than "mobile". -->
         <sch:assert id="compliance_contact_phone_assert"
                     role="[ERROR]"
                     diagnostics="nemsisDiagnostic"
                     test="nem:dContact.10/@PhoneNumberType = '9913005'">
      The Agency Contact Phone Number list should include a mobile phone number. This is a validation message for compliance pre-testing for 2026 for NEMSIS v3.5.1.
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
