"""NEMSIS ePayment (chart payment / insurance / PCS) ORM models.

Backs the ``epcr_chart_payment`` 1:1 table and the
``epcr_chart_payment_supply_items`` 1:M child table created by
migration ``034``. Represents the NEMSIS v3.5.1 ePayment section as a
child aggregate of :class:`Chart`. The chart-finalization gate enforces
the Required-at-National subsets (ePayment.01 Primary Method of Payment;
ePayment.55/.56 paired Supply Used groups when present) via the
registry-driven validator, not in the ORM layer.

NEMSIS element bindings (handled by :mod:`projection_chart_payment`):

    primary_method_of_payment_code                -> ePayment.01 (Required)
    physician_certification_statement_code        -> ePayment.02
    pcs_signed_date                               -> ePayment.03
    reason_for_pcs_codes_json                     -> ePayment.04 (1:M)
    pcs_provider_type_code                        -> ePayment.05
    pcs_last_name                                 -> ePayment.06
    pcs_first_name                                -> ePayment.07
    patient_resides_in_service_area_code          -> ePayment.08
    insurance_company_id                          -> ePayment.09
    insurance_company_name                        -> ePayment.10
    insurance_billing_priority_code               -> ePayment.11
    insurance_company_address                     -> ePayment.12
    insurance_company_city                        -> ePayment.13
    insurance_company_state                       -> ePayment.14
    insurance_company_zip                         -> ePayment.15
    insurance_company_country                     -> ePayment.16
    insurance_group_id                            -> ePayment.17
    insurance_policy_id_number                    -> ePayment.18
    insured_last_name                             -> ePayment.19
    insured_first_name                            -> ePayment.20
    insured_middle_name                           -> ePayment.21
    relationship_to_insured_code                  -> ePayment.22
    closest_relative_last_name                    -> ePayment.23
    closest_relative_first_name                   -> ePayment.24
    closest_relative_middle_name                  -> ePayment.25
    closest_relative_street_address               -> ePayment.26
    closest_relative_city                         -> ePayment.27
    closest_relative_state                        -> ePayment.28
    closest_relative_zip                          -> ePayment.29
    closest_relative_country                      -> ePayment.30
    closest_relative_phone                        -> ePayment.31
    closest_relative_relationship_code            -> ePayment.32
    patient_employer_name                         -> ePayment.33
    patient_employer_address                      -> ePayment.34
    patient_employer_city                         -> ePayment.35
    patient_employer_state                        -> ePayment.36
    patient_employer_zip                          -> ePayment.37
    patient_employer_country                      -> ePayment.38
    patient_employer_phone                        -> ePayment.39
    response_urgency_code                         -> ePayment.40
    patient_transport_assessment_code             -> ePayment.41
    specialty_care_transport_provider_code        -> ePayment.42
    ambulance_transport_reason_code               -> ePayment.44
    round_trip_purpose_description                -> ePayment.45
    stretcher_purpose_description                 -> ePayment.46
    ambulance_conditions_indicator_codes_json     -> ePayment.47 (1:M)
    mileage_to_closest_hospital                   -> ePayment.48
    als_assessment_performed_warranted_code       -> ePayment.49
    cms_service_level_code                        -> ePayment.50
    ems_condition_codes_json                      -> ePayment.51 (1:M)
    cms_transportation_indicator_codes_json       -> ePayment.52 (1:M)
    transport_authorization_code                  -> ePayment.53
    prior_authorization_code_payer                -> ePayment.54
    supply_item_name (child table)                -> ePayment.55 (Required, 1:M)
    supply_item_quantity (child table)            -> ePayment.56 (Required, paired)
    payer_type_code                               -> ePayment.57
    insurance_group_name                          -> ePayment.58
    insurance_company_phone                       -> ePayment.59
    insured_date_of_birth                         -> ePayment.60

(ePayment.43 + .55/.56 — Supply Used repeating group — live in the
1:M child :class:`ChartPaymentSupplyItem` table.)
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class ChartPayment(Base):
    """NEMSIS ePayment 1:1 aggregate for a chart.

    All columns are nullable in the ORM except the audit envelope. The
    chart-finalization gate enforces NEMSIS Required-at-National subsets
    via the registry-driven validator. The ``*_codes_json`` columns
    hold JSON arrays of NEMSIS code values that the projection layer
    expands into separate repeating-group ledger rows. The Supply Used
    repeating group (ePayment.55/.56) lives in the 1:M child table
    :class:`ChartPaymentSupplyItem`.
    """

    __tablename__ = "epcr_chart_payment"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_payment_tenant_chart",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ePayment.01 — Primary Method of Payment (Required)
    primary_method_of_payment_code = Column(String(16), nullable=False)

    # ePayment.02..03 — PCS scalar block
    physician_certification_statement_code = Column(String(16), nullable=True)
    pcs_signed_date = Column(Date, nullable=True)

    # ePayment.04 (1:M) — Reason for PCS
    reason_for_pcs_codes_json = Column(JSON, nullable=True)

    # ePayment.05..07 — PCS provider identification
    pcs_provider_type_code = Column(String(16), nullable=True)
    pcs_last_name = Column(String(120), nullable=True)
    pcs_first_name = Column(String(120), nullable=True)

    # ePayment.08 — Patient resides in service area
    patient_resides_in_service_area_code = Column(String(16), nullable=True)

    # ePayment.09..18 — Insurance company / policy block
    insurance_company_id = Column(String(64), nullable=True)
    insurance_company_name = Column(String(255), nullable=True)
    insurance_billing_priority_code = Column(String(16), nullable=True)
    insurance_company_address = Column(String(255), nullable=True)
    insurance_company_city = Column(String(120), nullable=True)
    insurance_company_state = Column(String(8), nullable=True)
    insurance_company_zip = Column(String(16), nullable=True)
    insurance_company_country = Column(String(8), nullable=True)
    insurance_group_id = Column(String(64), nullable=True)
    insurance_policy_id_number = Column(String(64), nullable=True)

    # ePayment.19..22 — Insured identification + relationship to patient
    insured_last_name = Column(String(120), nullable=True)
    insured_first_name = Column(String(120), nullable=True)
    insured_middle_name = Column(String(120), nullable=True)
    relationship_to_insured_code = Column(String(16), nullable=True)

    # ePayment.23..32 — Closest relative / guardian block
    closest_relative_last_name = Column(String(120), nullable=True)
    closest_relative_first_name = Column(String(120), nullable=True)
    closest_relative_middle_name = Column(String(120), nullable=True)
    closest_relative_street_address = Column(String(255), nullable=True)
    closest_relative_city = Column(String(120), nullable=True)
    closest_relative_state = Column(String(8), nullable=True)
    closest_relative_zip = Column(String(16), nullable=True)
    closest_relative_country = Column(String(8), nullable=True)
    closest_relative_phone = Column(String(32), nullable=True)
    closest_relative_relationship_code = Column(String(16), nullable=True)

    # ePayment.33..39 — Patient employer block
    patient_employer_name = Column(String(255), nullable=True)
    patient_employer_address = Column(String(255), nullable=True)
    patient_employer_city = Column(String(120), nullable=True)
    patient_employer_state = Column(String(8), nullable=True)
    patient_employer_zip = Column(String(16), nullable=True)
    patient_employer_country = Column(String(8), nullable=True)
    patient_employer_phone = Column(String(32), nullable=True)

    # ePayment.40..42 — Response urgency / transport assessment / SCT provider
    response_urgency_code = Column(String(16), nullable=True)
    patient_transport_assessment_code = Column(String(16), nullable=True)
    specialty_care_transport_provider_code = Column(String(16), nullable=True)

    # ePayment.44..46 — Ambulance transport reason + round-trip / stretcher
    ambulance_transport_reason_code = Column(String(16), nullable=True)
    round_trip_purpose_description = Column(Text, nullable=True)
    stretcher_purpose_description = Column(Text, nullable=True)

    # ePayment.47 (1:M) — Ambulance conditions indicator
    ambulance_conditions_indicator_codes_json = Column(JSON, nullable=True)

    # ePayment.48..50 — Mileage / ALS assessment / CMS service level
    mileage_to_closest_hospital = Column(Float, nullable=True)
    als_assessment_performed_warranted_code = Column(String(16), nullable=True)
    cms_service_level_code = Column(String(16), nullable=True)

    # ePayment.51..52 (1:M) — EMS condition codes / CMS transportation
    # indicator codes
    ems_condition_codes_json = Column(JSON, nullable=True)
    cms_transportation_indicator_codes_json = Column(JSON, nullable=True)

    # ePayment.53..54 — Transport / prior authorization codes
    transport_authorization_code = Column(String(64), nullable=True)
    prior_authorization_code_payer = Column(String(64), nullable=True)

    # ePayment.57..60 — Payer type, insurance group name/phone, insured DOB
    payer_type_code = Column(String(16), nullable=True)
    insurance_group_name = Column(String(255), nullable=True)
    insurance_company_phone = Column(String(32), nullable=True)
    insured_date_of_birth = Column(Date, nullable=True)

    created_by_user_id = Column(String(64), nullable=True)
    updated_by_user_id = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    chart = relationship("Chart", foreign_keys=[chart_id])


class ChartPaymentSupplyItem(Base):
    """NEMSIS ePayment Supply Used repeating-group child row.

    Each row pairs ``supply_item_name`` (ePayment.55) with
    ``supply_item_quantity`` (ePayment.56). The projection layer emits
    two ledger entries per row (one per element) sharing the row's UUID
    as ``occurrence_id`` so the paired Supply Used group rebuilds
    correctly on export.
    """

    __tablename__ = "epcr_chart_payment_supply_items"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "supply_item_name",
            name="uq_epcr_chart_payment_supply_items_tenant_chart_name",
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    chart_id = Column(
        String(36),
        ForeignKey("epcr_charts.id"),
        nullable=False,
        index=True,
    )

    supply_item_name = Column(String(255), nullable=False)
    supply_item_quantity = Column(Integer, nullable=False)
    sequence_index = Column(Integer, nullable=False, server_default=text("0"), default=0)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    version = Column(Integer, nullable=False, server_default=text("1"))
    deleted_at = Column(DateTime(timezone=True), nullable=True)


__all__ = ["ChartPayment", "ChartPaymentSupplyItem"]
