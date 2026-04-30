<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xsl:stylesheet xmlns:iso="http://purl.oclc.org/dsdl/schematron"
                xmlns:nem="http://www.nemsis.org"
                xmlns:saxon="http://saxon.sf.net/"
                xmlns:schold="http://www.ascc.net/xml/schematron"
                xmlns:xhtml="http://www.w3.org/1999/xhtml"
                xmlns:xs="http://www.w3.org/2001/XMLSchema"
                xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                version="2.0"><!--Implementers: please note that overriding process-prolog or process-root is 
    the preferred method for meta-stylesheets to use where possible. -->
   <xsl:param name="archiveDirParameter"/>
   <xsl:param name="archiveNameParameter"/>
   <xsl:param name="fileNameParameter"/>
   <xsl:param name="fileDirParameter"/>
   <xsl:variable name="document-uri">
      <xsl:value-of select="document-uri(/)"/>
   </xsl:variable>
   <!--PHASES-->

   <!--PROLOG-->
   <xsl:output xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
               method="xml"
               omit-xml-declaration="no"
               standalone="yes"
               indent="yes"/>
   <!--XSD TYPES FOR XSLT2-->

   <!--KEYS AND FUNCTIONS-->

   <!--DEFAULT RULES-->

   <!--MODE: SCHEMATRON-SELECT-FULL-PATH-->
   <!--This mode can be used to generate an ugly though full XPath for locators-->
   <xsl:template match="*" mode="schematron-select-full-path">
      <xsl:apply-templates select="." mode="schematron-get-full-path"/>
   </xsl:template>
   <!--MODE: SCHEMATRON-FULL-PATH-->
   <!--This mode can be used to generate an ugly though full XPath for locators-->
   <xsl:template match="*" mode="schematron-get-full-path">
      <xsl:apply-templates select="parent::*" mode="schematron-get-full-path"/>
      <xsl:text>/</xsl:text>
      <xsl:choose>
         <xsl:when test="namespace-uri()=''">
            <xsl:value-of select="name()"/>
         </xsl:when>
         <xsl:otherwise>
            <xsl:text>*:</xsl:text>
            <xsl:value-of select="local-name()"/>
            <xsl:text>[namespace-uri()='</xsl:text>
            <xsl:value-of select="namespace-uri()"/>
            <xsl:text>']</xsl:text>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:variable name="preceding"
                    select="count(preceding-sibling::*[local-name()=local-name(current())                                   and namespace-uri() = namespace-uri(current())])"/>
      <xsl:text>[</xsl:text>
      <xsl:value-of select="1+ $preceding"/>
      <xsl:text>]</xsl:text>
   </xsl:template>
   <xsl:template match="@*" mode="schematron-get-full-path">
      <xsl:apply-templates select="parent::*" mode="schematron-get-full-path"/>
      <xsl:text>/</xsl:text>
      <xsl:choose>
         <xsl:when test="namespace-uri()=''">@<xsl:value-of select="name()"/>
         </xsl:when>
         <xsl:otherwise>
            <xsl:text>@*[local-name()='</xsl:text>
            <xsl:value-of select="local-name()"/>
            <xsl:text>' and namespace-uri()='</xsl:text>
            <xsl:value-of select="namespace-uri()"/>
            <xsl:text>']</xsl:text>
         </xsl:otherwise>
      </xsl:choose>
   </xsl:template>
   <!--MODE: SCHEMATRON-FULL-PATH-2-->
   <!--This mode can be used to generate prefixed XPath for humans-->
   <xsl:template match="node() | @*" mode="schematron-get-full-path-2">
      <xsl:for-each select="ancestor-or-self::*">
         <xsl:text>/</xsl:text>
         <xsl:value-of select="name(.)"/>
         <xsl:if test="preceding-sibling::*[name(.)=name(current())]">
            <xsl:text>[</xsl:text>
            <xsl:value-of select="count(preceding-sibling::*[name(.)=name(current())])+1"/>
            <xsl:text>]</xsl:text>
         </xsl:if>
      </xsl:for-each>
      <xsl:if test="not(self::*)">
         <xsl:text/>/@<xsl:value-of select="name(.)"/>
      </xsl:if>
   </xsl:template>
   <!--MODE: SCHEMATRON-FULL-PATH-3-->
   <!--This mode can be used to generate prefixed XPath for humans 
	(Top-level element has index)-->
   <xsl:template match="node() | @*" mode="schematron-get-full-path-3">
      <xsl:for-each select="ancestor-or-self::*">
         <xsl:text>/</xsl:text>
         <xsl:value-of select="name(.)"/>
         <xsl:if test="parent::*">
            <xsl:text>[</xsl:text>
            <xsl:value-of select="count(preceding-sibling::*[name(.)=name(current())])+1"/>
            <xsl:text>]</xsl:text>
         </xsl:if>
      </xsl:for-each>
      <xsl:if test="not(self::*)">
         <xsl:text/>/@<xsl:value-of select="name(.)"/>
      </xsl:if>
   </xsl:template>
   <!--MODE: GENERATE-ID-FROM-PATH -->
   <xsl:template match="/" mode="generate-id-from-path"/>
   <xsl:template match="text()" mode="generate-id-from-path">
      <xsl:apply-templates select="parent::*" mode="generate-id-from-path"/>
      <xsl:value-of select="concat('.text-', 1+count(preceding-sibling::text()), '-')"/>
   </xsl:template>
   <xsl:template match="comment()" mode="generate-id-from-path">
      <xsl:apply-templates select="parent::*" mode="generate-id-from-path"/>
      <xsl:value-of select="concat('.comment-', 1+count(preceding-sibling::comment()), '-')"/>
   </xsl:template>
   <xsl:template match="processing-instruction()" mode="generate-id-from-path">
      <xsl:apply-templates select="parent::*" mode="generate-id-from-path"/>
      <xsl:value-of select="concat('.processing-instruction-', 1+count(preceding-sibling::processing-instruction()), '-')"/>
   </xsl:template>
   <xsl:template match="@*" mode="generate-id-from-path">
      <xsl:apply-templates select="parent::*" mode="generate-id-from-path"/>
      <xsl:value-of select="concat('.@', name())"/>
   </xsl:template>
   <xsl:template match="*" mode="generate-id-from-path" priority="-0.5">
      <xsl:apply-templates select="parent::*" mode="generate-id-from-path"/>
      <xsl:text>.</xsl:text>
      <xsl:value-of select="concat('.',name(),'-',1+count(preceding-sibling::*[name()=name(current())]),'-')"/>
   </xsl:template>
   <!--MODE: GENERATE-ID-2 -->
   <xsl:template match="/" mode="generate-id-2">U</xsl:template>
   <xsl:template match="*" mode="generate-id-2" priority="2">
      <xsl:text>U</xsl:text>
      <xsl:number level="multiple" count="*"/>
   </xsl:template>
   <xsl:template match="node()" mode="generate-id-2">
      <xsl:text>U.</xsl:text>
      <xsl:number level="multiple" count="*"/>
      <xsl:text>n</xsl:text>
      <xsl:number count="node()"/>
   </xsl:template>
   <xsl:template match="@*" mode="generate-id-2">
      <xsl:text>U.</xsl:text>
      <xsl:number level="multiple" count="*"/>
      <xsl:text>_</xsl:text>
      <xsl:value-of select="string-length(local-name(.))"/>
      <xsl:text>_</xsl:text>
      <xsl:value-of select="translate(name(),':','.')"/>
   </xsl:template>
   <!--Strip characters-->
   <xsl:template match="text()" priority="-1"/>
   <!--SCHEMA SETUP-->
   <xsl:template match="/">
      <svrl:schematron-output xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                              title="NEMSIS Sample ISO Schematron file for EMSDataSet"
                              schemaVersion="3.5.1.251001CP2">
         <xsl:comment>
            <xsl:value-of select="$archiveDirParameter"/>   
		 <xsl:value-of select="$archiveNameParameter"/>  
		 <xsl:value-of select="$fileNameParameter"/>  
		 <xsl:value-of select="$fileDirParameter"/>
         </xsl:comment>
         <svrl:ns-prefix-in-attribute-values uri="http://www.nemsis.org" prefix="nem"/>
         <svrl:ns-prefix-in-attribute-values uri="http://www.w3.org/2001/XMLSchema-instance" prefix="xsi"/>
         <svrl:active-pattern>
            <xsl:attribute name="document">
               <xsl:value-of select="document-uri(/)"/>
            </xsl:attribute>
            <xsl:attribute name="id">sample_eNilNvPn</xsl:attribute>
            <xsl:attribute name="name">EMSDataSet / Nil/Not Value/Pertinent Negative Attributes</xsl:attribute>
            <xsl:apply-templates/>
         </svrl:active-pattern>
         <xsl:apply-templates select="/" mode="M6"/>
      </svrl:schematron-output>
   </xsl:template>
   <!--SCHEMATRON PATTERNS-->
   <svrl:text xmlns:svrl="http://purl.oclc.org/dsdl/svrl">NEMSIS Sample ISO Schematron file for EMSDataSet</svrl:text>
   <xsl:param name="nemsisElements" select="()"/>
   <xsl:param name="nemsisElementsMissing" select="''"/>
   <xsl:param name="nemsisElementsMissingContext" select="()"/>
   <!--PATTERN sample_eNilNvPnEMSDataSet / Nil/Not Value/Pertinent Negative Attributes-->
   <svrl:text xmlns:svrl="http://purl.oclc.org/dsdl/svrl">EMSDataSet / Nil/Not Value/Pertinent Negative Attributes</svrl:text>
   <!--RULE sample_eNilNvPn_rule_1-->
   <xsl:template match="nem:eCustomResults.01" priority="1010" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eCustomResults.01"
                       id="sample_eNilNvPn_rule_1"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--REPORT [WARNING]-->
      <xsl:if test="false()">
         <svrl:successful-report xmlns:svrl="http://purl.oclc.org/dsdl/svrl" test="false()">
            <xsl:attribute name="role">[WARNING]</xsl:attribute>
            <xsl:attribute name="location">
               <xsl:apply-templates select="." mode="schematron-select-full-path"/>
            </xsl:attribute>
            <svrl:text>
        This rule enforces no constraints on the combination of xsi:nil, Not Value, and Pertinent Negative attributes on eCustomResults.01.
      </svrl:text>
            <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

               <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                  <record>
                     <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                     <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                     <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                     <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                  </record>
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
            </svrl:diagnostic-reference>
         </svrl:successful-report>
      </xsl:if>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_2-->
   <xsl:template match="nem:eExam.AssessmentGroup//*[@PN]" priority="1009" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eExam.AssessmentGroup//*[@PN]"
                       id="sample_eNilNvPn_rule_2"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--REPORT [WARNING]-->
      <xsl:if test="false()">
         <svrl:successful-report xmlns:svrl="http://purl.oclc.org/dsdl/svrl" test="false()">
            <xsl:attribute name="role">[WARNING]</xsl:attribute>
            <xsl:attribute name="location">
               <xsl:apply-templates select="." mode="schematron-select-full-path"/>
            </xsl:attribute>
            <svrl:text>
        This rule enforces no constraints on the Pertinent Negative attribute on elements in eExam.AssessmentGroup.
      </svrl:text>
            <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

               <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                  <record>
                     <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                     <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                     <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                     <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                  </record>
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
            </svrl:diagnostic-reference>
         </svrl:successful-report>
      </xsl:if>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_3-->
   <xsl:template match="nem:eHistory.10[@PN]" priority="1008" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eHistory.10[@PN]"
                       id="sample_eNilNvPn_rule_3"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--REPORT [WARNING]-->
      <xsl:if test="false()">
         <svrl:successful-report xmlns:svrl="http://purl.oclc.org/dsdl/svrl" test="false()">
            <xsl:attribute name="role">[WARNING]</xsl:attribute>
            <xsl:attribute name="location">
               <xsl:apply-templates select="." mode="schematron-select-full-path"/>
            </xsl:attribute>
            <svrl:text>
        This rule enforces no constraints on the Pertinent Negative attribute on eHistory.10.
      </svrl:text>
            <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

               <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                  <record>
                     <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                     <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                     <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                     <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                  </record>
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
            </svrl:diagnostic-reference>
         </svrl:successful-report>
      </xsl:if>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_4-->
   <xsl:template match="nem:eSituation.01[@PN = '8801023']"
                 priority="1007"
                 mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eSituation.01[@PN = '8801023']"
                       id="sample_eNilNvPn_rule_4"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="@xsi:nil = 'true' and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="@xsi:nil = 'true' and not(@NV)">
               <xsl:attribute name="id">sample_e003</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When Date/Time of Symptom Onset has a Pertinent Negative of "Unable to Complete", it should be empty and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_5-->
   <xsl:template match="nem:eSituation.01[@PN = '8801029']"
                 priority="1006"
                 mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eSituation.01[@PN = '8801029']"
                       id="sample_eNilNvPn_rule_5"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="not(@xsi:nil = 'true') and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="not(@xsi:nil = 'true') and not(@NV)">
               <xsl:attribute name="id">sample_e004</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When Date/Time of Symptom Onset has a Pertinent Negative of "Approximate", it should have a value and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_6-->
   <xsl:template match="nem:eSituation.10[@PN]" priority="1005" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eSituation.10[@PN]"
                       id="sample_eNilNvPn_rule_6"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="not(@xsi:nil = 'true') and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="not(@xsi:nil = 'true') and not(@NV)">
               <xsl:attribute name="id">sample_e005</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When Other Associated Symptoms has a Pertinent Negative, it should have a value and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_7-->
   <xsl:template match="nem:eMedications.03[@PN]" priority="1004" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eMedications.03[@PN]"
                       id="sample_eNilNvPn_rule_7"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="not(@xsi:nil = 'true') and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="not(@xsi:nil = 'true') and not(@NV)">
               <xsl:attribute name="id">sample_e006</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When Medication Administered has a Pertinent Negative, it should have a value and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_8-->
   <xsl:template match="nem:eProcedures.03[@PN]" priority="1003" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="nem:eProcedures.03[@PN]"
                       id="sample_eNilNvPn_rule_8"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="not(@xsi:nil = 'true') and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="not(@xsi:nil = 'true') and not(@NV)">
               <xsl:attribute name="id">sample_e007</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When Procedure has a Pertinent Negative, it should have a value and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_9-->
   <xsl:template match="*[@PN]" priority="1002" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="*[@PN]"
                       id="sample_eNilNvPn_rule_9"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="@xsi:nil = 'true' and not(@NV)"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                                test="@xsi:nil = 'true' and not(@NV)">
               <xsl:attribute name="id">sample_e008</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When an element has a Pertinent Negative, it should be empty and it should not have a Not Value (Not Applicable, Not Recorded, or Not Reporting).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_10-->
   <xsl:template match="*[@xsi:nil = 'true']" priority="1001" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="*[@xsi:nil = 'true']"
                       id="sample_eNilNvPn_rule_10"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="@NV or @PN"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl" test="@NV or @PN">
               <xsl:attribute name="id">sample_e001</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When an element is empty, it should have a Not Value (Not Applicable, Not Recorded, or Not Reporting, if allowed for the element) or a Pertinent Negative (if allowed for the element), or it should be omitted (if the element is optional).
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <!--RULE sample_eNilNvPn_rule_11-->
   <xsl:template match="*[@NV]" priority="1000" mode="M6">
      <svrl:fired-rule xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
                       context="*[@NV]"
                       id="sample_eNilNvPn_rule_11"/>
      <xsl:variable name="nemsisElements" select="."/>
      <!--ASSERT [ERROR]-->
      <xsl:choose>
         <xsl:when test="@xsi:nil='true'"/>
         <xsl:otherwise>
            <svrl:failed-assert xmlns:svrl="http://purl.oclc.org/dsdl/svrl" test="@xsi:nil='true'">
               <xsl:attribute name="id">sample_e002</xsl:attribute>
               <xsl:attribute name="role">[ERROR]</xsl:attribute>
               <xsl:attribute name="location">
                  <xsl:apply-templates select="." mode="schematron-select-full-path"/>
               </xsl:attribute>
               <svrl:text>
        When an element has a Not Value (Not Applicable, Not Recorded, or Not Reporting), it should be empty.
      </svrl:text>
               <svrl:diagnostic-reference diagnostic="nemsisDiagnostic">

                  <nemsisDiagnostic xmlns="http://www.nemsis.org" xmlns:sch="http://purl.oclc.org/dsdl/schematron">
                     <record>
                        <xsl:copy-of select="ancestor-or-self::*:StateDataSet/*:sState/*:sState.01"/>
                        <xsl:copy-of select="ancestor-or-self::*:DemographicReport/*:dAgency/(*:dAgency.01 | *:dAgency.02 | *:dAgency.04)"/>
                        <xsl:copy-of select="ancestor-or-self::*:Header/*:DemographicGroup/*"/>
                        <xsl:copy-of select="ancestor-or-self::*:PatientCareReport/*:eRecord/*:eRecord.01"/>
                     </record>
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
               </svrl:diagnostic-reference>
            </svrl:failed-assert>
         </xsl:otherwise>
      </xsl:choose>
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
   <xsl:template match="text()" priority="-1" mode="M6"/>
   <xsl:template match="@*|node()" priority="-2" mode="M6">
      <xsl:apply-templates select="*|comment()|processing-instruction()" mode="M6"/>
   </xsl:template>
</xsl:stylesheet>
