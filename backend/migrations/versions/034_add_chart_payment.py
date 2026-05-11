"""034 add epcr_chart_payment + epcr_chart_payment_supply_items.

Revision ID: 034
Revises: 023
Create Date: 2026-05-10

Adds the NEMSIS v3.5.1 ePayment 1:1 child table for charts plus its
Supply Used (ePayment.55/.56) 1:M child table. ePayment.01 (Primary
Method of Payment) is the only NOT NULL scalar; all other columns are
nullable in the schema and the chart-finalization gate enforces
Required-at-National subsets via the registry-driven validator.

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "023"
branch_labels = None
depends_on = None


PAYMENT_TABLE = "epcr_chart_payment"
SUPPLY_TABLE = "epcr_chart_payment_supply_items"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_unique(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    constraints = insp.get_unique_constraints(table)
    return any(c["name"] == name for c in constraints)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, PAYMENT_TABLE):
        op.create_table(
            PAYMENT_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            # ePayment.01 (Required)
            sa.Column(
                "primary_method_of_payment_code", sa.String(16), nullable=False
            ),
            # ePayment.02..03
            sa.Column(
                "physician_certification_statement_code",
                sa.String(16),
                nullable=True,
            ),
            sa.Column("pcs_signed_date", sa.Date(), nullable=True),
            # ePayment.04 (1:M)
            sa.Column("reason_for_pcs_codes_json", sa.JSON(), nullable=True),
            # ePayment.05..07
            sa.Column("pcs_provider_type_code", sa.String(16), nullable=True),
            sa.Column("pcs_last_name", sa.String(120), nullable=True),
            sa.Column("pcs_first_name", sa.String(120), nullable=True),
            # ePayment.08
            sa.Column(
                "patient_resides_in_service_area_code",
                sa.String(16),
                nullable=True,
            ),
            # ePayment.09..18 — insurance company / policy
            sa.Column("insurance_company_id", sa.String(64), nullable=True),
            sa.Column("insurance_company_name", sa.String(255), nullable=True),
            sa.Column(
                "insurance_billing_priority_code", sa.String(16), nullable=True
            ),
            sa.Column(
                "insurance_company_address", sa.String(255), nullable=True
            ),
            sa.Column("insurance_company_city", sa.String(120), nullable=True),
            sa.Column("insurance_company_state", sa.String(8), nullable=True),
            sa.Column("insurance_company_zip", sa.String(16), nullable=True),
            sa.Column("insurance_company_country", sa.String(8), nullable=True),
            sa.Column("insurance_group_id", sa.String(64), nullable=True),
            sa.Column(
                "insurance_policy_id_number", sa.String(64), nullable=True
            ),
            # ePayment.19..22 — insured + relationship
            sa.Column("insured_last_name", sa.String(120), nullable=True),
            sa.Column("insured_first_name", sa.String(120), nullable=True),
            sa.Column("insured_middle_name", sa.String(120), nullable=True),
            sa.Column(
                "relationship_to_insured_code", sa.String(16), nullable=True
            ),
            # ePayment.23..32 — closest relative
            sa.Column(
                "closest_relative_last_name", sa.String(120), nullable=True
            ),
            sa.Column(
                "closest_relative_first_name", sa.String(120), nullable=True
            ),
            sa.Column(
                "closest_relative_middle_name", sa.String(120), nullable=True
            ),
            sa.Column(
                "closest_relative_street_address",
                sa.String(255),
                nullable=True,
            ),
            sa.Column("closest_relative_city", sa.String(120), nullable=True),
            sa.Column("closest_relative_state", sa.String(8), nullable=True),
            sa.Column("closest_relative_zip", sa.String(16), nullable=True),
            sa.Column("closest_relative_country", sa.String(8), nullable=True),
            sa.Column("closest_relative_phone", sa.String(32), nullable=True),
            sa.Column(
                "closest_relative_relationship_code",
                sa.String(16),
                nullable=True,
            ),
            # ePayment.33..39 — employer
            sa.Column("patient_employer_name", sa.String(255), nullable=True),
            sa.Column(
                "patient_employer_address", sa.String(255), nullable=True
            ),
            sa.Column("patient_employer_city", sa.String(120), nullable=True),
            sa.Column("patient_employer_state", sa.String(8), nullable=True),
            sa.Column("patient_employer_zip", sa.String(16), nullable=True),
            sa.Column("patient_employer_country", sa.String(8), nullable=True),
            sa.Column("patient_employer_phone", sa.String(32), nullable=True),
            # ePayment.40..42
            sa.Column("response_urgency_code", sa.String(16), nullable=True),
            sa.Column(
                "patient_transport_assessment_code",
                sa.String(16),
                nullable=True,
            ),
            sa.Column(
                "specialty_care_transport_provider_code",
                sa.String(16),
                nullable=True,
            ),
            # ePayment.44..46
            sa.Column(
                "ambulance_transport_reason_code", sa.String(16), nullable=True
            ),
            sa.Column(
                "round_trip_purpose_description", sa.Text(), nullable=True
            ),
            sa.Column(
                "stretcher_purpose_description", sa.Text(), nullable=True
            ),
            # ePayment.47 (1:M)
            sa.Column(
                "ambulance_conditions_indicator_codes_json",
                sa.JSON(),
                nullable=True,
            ),
            # ePayment.48..50
            sa.Column(
                "mileage_to_closest_hospital", sa.Float(), nullable=True
            ),
            sa.Column(
                "als_assessment_performed_warranted_code",
                sa.String(16),
                nullable=True,
            ),
            sa.Column("cms_service_level_code", sa.String(16), nullable=True),
            # ePayment.51..52 (1:M)
            sa.Column("ems_condition_codes_json", sa.JSON(), nullable=True),
            sa.Column(
                "cms_transportation_indicator_codes_json",
                sa.JSON(),
                nullable=True,
            ),
            # ePayment.53..54
            sa.Column(
                "transport_authorization_code", sa.String(64), nullable=True
            ),
            sa.Column(
                "prior_authorization_code_payer", sa.String(64), nullable=True
            ),
            # ePayment.57..60
            sa.Column("payer_type_code", sa.String(16), nullable=True),
            sa.Column("insurance_group_name", sa.String(255), nullable=True),
            sa.Column("insurance_company_phone", sa.String(32), nullable=True),
            sa.Column("insured_date_of_birth", sa.Date(), nullable=True),
            sa.Column("created_by_user_id", sa.String(64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "version", sa.Integer(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_chart_payment_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, PAYMENT_TABLE, "ix_epcr_chart_payment_tenant_id"):
        op.create_index(
            "ix_epcr_chart_payment_tenant_id",
            PAYMENT_TABLE,
            ["tenant_id"],
        )
    if not _has_index(insp, PAYMENT_TABLE, "ix_epcr_chart_payment_chart_id"):
        op.create_index(
            "ix_epcr_chart_payment_chart_id",
            PAYMENT_TABLE,
            ["chart_id"],
        )

    if not _has_table(insp, SUPPLY_TABLE):
        op.create_table(
            SUPPLY_TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("supply_item_name", sa.String(255), nullable=False),
            sa.Column("supply_item_quantity", sa.Integer(), nullable=False),
            sa.Column(
                "sequence_index",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "version", sa.Integer(), nullable=False, server_default=sa.text("1")
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "supply_item_name",
                name="uq_epcr_chart_payment_supply_items_tenant_chart_name",
            ),
        if_not_exists=True)

    if not _has_index(
        insp, SUPPLY_TABLE, "ix_epcr_chart_payment_supply_items_tenant_id"
    ):
        op.create_index(
            "ix_epcr_chart_payment_supply_items_tenant_id",
            SUPPLY_TABLE,
            ["tenant_id"],
        )
    if not _has_index(
        insp, SUPPLY_TABLE, "ix_epcr_chart_payment_supply_items_chart_id"
    ):
        op.create_index(
            "ix_epcr_chart_payment_supply_items_chart_id",
            SUPPLY_TABLE,
            ["chart_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_index(
        insp, SUPPLY_TABLE, "ix_epcr_chart_payment_supply_items_chart_id"
    ):
        op.drop_index(
            "ix_epcr_chart_payment_supply_items_chart_id", table_name=SUPPLY_TABLE
        )
    if _has_index(
        insp, SUPPLY_TABLE, "ix_epcr_chart_payment_supply_items_tenant_id"
    ):
        op.drop_index(
            "ix_epcr_chart_payment_supply_items_tenant_id", table_name=SUPPLY_TABLE
        )
    if _has_table(insp, SUPPLY_TABLE):
        op.drop_table(SUPPLY_TABLE)

    if _has_index(insp, PAYMENT_TABLE, "ix_epcr_chart_payment_chart_id"):
        op.drop_index("ix_epcr_chart_payment_chart_id", table_name=PAYMENT_TABLE)
    if _has_index(insp, PAYMENT_TABLE, "ix_epcr_chart_payment_tenant_id"):
        op.drop_index("ix_epcr_chart_payment_tenant_id", table_name=PAYMENT_TABLE)
    if _has_table(insp, PAYMENT_TABLE):
        op.drop_table(PAYMENT_TABLE)
