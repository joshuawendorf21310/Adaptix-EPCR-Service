"""036 add NEMSIS ePatient extension tables.

Revision ID: 036
Revises: 023
Create Date: 2026-05-10

Adds five sibling tables that supply NEMSIS v3.5.1 ePatient elements
not already covered by the existing ``PatientProfile`` aggregate:

* ``epcr_patient_profile_nemsis_ext``  — 1:1 scalar extension
* ``epcr_patient_home_address``        — 1:1 Patient's Home Address group
* ``epcr_patient_races``               — 1:M ePatient.14 Race
* ``epcr_patient_languages``           — 1:M ePatient.24 Preferred Language(s)
* ``epcr_patient_phone_numbers``       — 1:M ePatient.18 Patient's Phone Number

Idempotent + drift-safe: every step is gated on inspector state so
re-running the migration on a partially-applied schema is safe. The
chart-finalization gate enforces NEMSIS Required/Mandatory subsets via
the registry-driven validator; nothing is enforced at the ORM layer.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "036"
down_revision = "023"
branch_labels = None
depends_on = None


TABLE_EXT = "epcr_patient_profile_nemsis_ext"
TABLE_ADDR = "epcr_patient_home_address"
TABLE_RACE = "epcr_patient_races"
TABLE_LANG = "epcr_patient_languages"
TABLE_PHONE = "epcr_patient_phone_numbers"


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)


def _has_index(insp, table: str, name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # -------- scalar extension table (1:1) --------
    if not _has_table(insp, TABLE_EXT):
        op.create_table(
            TABLE_EXT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("ems_patient_id", sa.String(64), nullable=True),
            sa.Column("country_of_residence_code", sa.String(8), nullable=True),
            sa.Column("patient_home_census_tract", sa.String(32), nullable=True),
            sa.Column("ssn_hash", sa.String(64), nullable=True),
            sa.Column("age_units_code", sa.String(16), nullable=True),
            sa.Column("email_address", sa.String(255), nullable=True),
            sa.Column("driver_license_state", sa.String(8), nullable=True),
            sa.Column("driver_license_number", sa.String(64), nullable=True),
            sa.Column("alternate_home_residence_code", sa.String(16), nullable=True),
            sa.Column("name_suffix", sa.String(16), nullable=True),
            sa.Column("sex_nemsis_code", sa.String(16), nullable=True),
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
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_patient_profile_nemsis_ext_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE_EXT, "ix_epcr_patient_profile_nemsis_ext_tenant_id"):
        op.create_index(
            "ix_epcr_patient_profile_nemsis_ext_tenant_id",
            TABLE_EXT,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE_EXT, "ix_epcr_patient_profile_nemsis_ext_chart_id"):
        op.create_index(
            "ix_epcr_patient_profile_nemsis_ext_chart_id",
            TABLE_EXT,
            ["chart_id"],
        )

    # -------- home address (1:1) --------
    if not _has_table(insp, TABLE_ADDR):
        op.create_table(
            TABLE_ADDR,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("home_street_address", sa.String(255), nullable=True),
            sa.Column("home_city", sa.String(120), nullable=True),
            sa.Column("home_county", sa.String(120), nullable=True),
            sa.Column("home_state", sa.String(8), nullable=True),
            sa.Column("home_zip", sa.String(16), nullable=True),
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
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                name="uq_epcr_patient_home_address_tenant_chart",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE_ADDR, "ix_epcr_patient_home_address_tenant_id"):
        op.create_index(
            "ix_epcr_patient_home_address_tenant_id",
            TABLE_ADDR,
            ["tenant_id"],
        )
    if not _has_index(insp, TABLE_ADDR, "ix_epcr_patient_home_address_chart_id"):
        op.create_index(
            "ix_epcr_patient_home_address_chart_id",
            TABLE_ADDR,
            ["chart_id"],
        )

    # -------- races (1:M) --------
    if not _has_table(insp, TABLE_RACE):
        op.create_table(
            TABLE_RACE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("race_code", sa.String(16), nullable=False),
            sa.Column("sequence_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "race_code",
                name="uq_epcr_patient_races_tenant_chart_race",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE_RACE, "ix_epcr_patient_races_tenant_id"):
        op.create_index("ix_epcr_patient_races_tenant_id", TABLE_RACE, ["tenant_id"])
    if not _has_index(insp, TABLE_RACE, "ix_epcr_patient_races_chart_id"):
        op.create_index("ix_epcr_patient_races_chart_id", TABLE_RACE, ["chart_id"])

    # -------- languages (1:M) --------
    if not _has_table(insp, TABLE_LANG):
        op.create_table(
            TABLE_LANG,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("language_code", sa.String(16), nullable=False),
            sa.Column("sequence_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "language_code",
                name="uq_epcr_patient_languages_tenant_chart_lang",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE_LANG, "ix_epcr_patient_languages_tenant_id"):
        op.create_index("ix_epcr_patient_languages_tenant_id", TABLE_LANG, ["tenant_id"])
    if not _has_index(insp, TABLE_LANG, "ix_epcr_patient_languages_chart_id"):
        op.create_index("ix_epcr_patient_languages_chart_id", TABLE_LANG, ["chart_id"])

    # -------- phone numbers (1:M) --------
    if not _has_table(insp, TABLE_PHONE):
        op.create_table(
            TABLE_PHONE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "chart_id",
                sa.String(36),
                sa.ForeignKey("epcr_charts.id"),
                nullable=False,
            ),
            sa.Column("phone_number", sa.String(32), nullable=False),
            sa.Column("phone_type_code", sa.String(16), nullable=True),
            sa.Column("sequence_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "chart_id",
                "phone_number",
                name="uq_epcr_patient_phone_numbers_tenant_chart_phone",
            ),
        if_not_exists=True)

    if not _has_index(insp, TABLE_PHONE, "ix_epcr_patient_phone_numbers_tenant_id"):
        op.create_index(
            "ix_epcr_patient_phone_numbers_tenant_id", TABLE_PHONE, ["tenant_id"]
        )
    if not _has_index(insp, TABLE_PHONE, "ix_epcr_patient_phone_numbers_chart_id"):
        op.create_index(
            "ix_epcr_patient_phone_numbers_chart_id", TABLE_PHONE, ["chart_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, indexes in (
        (
            TABLE_PHONE,
            (
                "ix_epcr_patient_phone_numbers_chart_id",
                "ix_epcr_patient_phone_numbers_tenant_id",
            ),
        ),
        (
            TABLE_LANG,
            (
                "ix_epcr_patient_languages_chart_id",
                "ix_epcr_patient_languages_tenant_id",
            ),
        ),
        (
            TABLE_RACE,
            (
                "ix_epcr_patient_races_chart_id",
                "ix_epcr_patient_races_tenant_id",
            ),
        ),
        (
            TABLE_ADDR,
            (
                "ix_epcr_patient_home_address_chart_id",
                "ix_epcr_patient_home_address_tenant_id",
            ),
        ),
        (
            TABLE_EXT,
            (
                "ix_epcr_patient_profile_nemsis_ext_chart_id",
                "ix_epcr_patient_profile_nemsis_ext_tenant_id",
            ),
        ),
    ):
        for ix in indexes:
            if _has_index(insp, table, ix):
                op.drop_index(ix, table_name=table)
        if _has_table(insp, table):
            op.drop_table(table)
