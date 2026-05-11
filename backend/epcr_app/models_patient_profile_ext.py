"""NEMSIS ePatient extension ORM models.

Five sibling tables that add the ePatient elements not covered by the
existing :class:`PatientProfile` (which is OFF-LIMITS). The existing
``PatientProfile`` already supplies 9 of the 24 v3.5.1 ePatient
elements; these extension tables supply the remaining ones without
modifying it.

Tables created by migration ``036``:

* ``epcr_patient_profile_nemsis_ext``  (1:1 with Chart) — scalar
  ePatient fields NOT covered by ``PatientProfile``.

* ``epcr_patient_home_address``  (1:1 with Chart) — ePatient.05..09 +
  county (.07) + state (.08), the Patient's Home Address group.

* ``epcr_patient_races``  (1:M with Chart) — ePatient.14 Race (1:M).

* ``epcr_patient_languages``  (1:M with Chart) — ePatient.24 Preferred
  Language(s) (1:M).

* ``epcr_patient_phone_numbers``  (1:M with Chart) — ePatient.18
  Patient's Phone Number (1:M, with optional phone-type code).

NEMSIS scalar bindings carried by :class:`PatientProfileNemsisExt`
(handled by :mod:`projection_patient_profile_ext`):

    ems_patient_id                  -> ePatient.01
    country_of_residence_code       -> ePatient.10
    patient_home_census_tract       -> ePatient.11
    ssn_hash                        -> ePatient.12  (HASHED for privacy)
    age_units_code                  -> ePatient.16
    email_address                   -> ePatient.19
    driver_license_state            -> ePatient.20
    driver_license_number           -> ePatient.21
    alternate_home_residence_code   -> ePatient.22
    name_suffix                     -> ePatient.23
    sex_nemsis_code                 -> ePatient.25
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from epcr_app.models import Base


class PatientProfileNemsisExt(Base):
    """NEMSIS ePatient 1:1 scalar-extension aggregate for a chart.

    Holds ePatient scalars NOT already covered by :class:`PatientProfile`.
    Every column is nullable; the chart-finalization gate enforces the
    Required-at-National subset via the registry-driven validator.
    """

    __tablename__ = "epcr_patient_profile_nemsis_ext"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_patient_profile_nemsis_ext_tenant_chart",
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

    # NEMSIS ePatient scalars not in PatientProfile (in canonical order)
    ems_patient_id = Column(String(64), nullable=True)                  # ePatient.01
    country_of_residence_code = Column(String(8), nullable=True)        # ePatient.10
    patient_home_census_tract = Column(String(32), nullable=True)       # ePatient.11
    ssn_hash = Column(String(64), nullable=True)                        # ePatient.12 (hashed)
    age_units_code = Column(String(16), nullable=True)                  # ePatient.16
    email_address = Column(String(255), nullable=True)                  # ePatient.19
    driver_license_state = Column(String(8), nullable=True)             # ePatient.20
    driver_license_number = Column(String(64), nullable=True)           # ePatient.21
    alternate_home_residence_code = Column(String(16), nullable=True)   # ePatient.22
    name_suffix = Column(String(16), nullable=True)                     # ePatient.23
    sex_nemsis_code = Column(String(16), nullable=True)                 # ePatient.25

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


class PatientHomeAddress(Base):
    """NEMSIS Patient's Home Address group (ePatient.05..09), 1:1 per chart."""

    __tablename__ = "epcr_patient_home_address"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_patient_home_address_tenant_chart",
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

    home_street_address = Column(String(255), nullable=True)  # ePatient.05
    home_city = Column(String(120), nullable=True)            # ePatient.06
    home_county = Column(String(120), nullable=True)          # ePatient.07
    home_state = Column(String(8), nullable=True)             # ePatient.08
    home_zip = Column(String(16), nullable=True)              # ePatient.09

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


class PatientRace(Base):
    """NEMSIS ePatient.14 Race (1:M)."""

    __tablename__ = "epcr_patient_races"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "race_code",
            name="uq_epcr_patient_races_tenant_chart_race",
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
    race_code = Column(String(16), nullable=False)
    sequence_index = Column(Integer, nullable=False, default=0)

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


class PatientLanguage(Base):
    """NEMSIS ePatient.24 Preferred Language(s) (1:M)."""

    __tablename__ = "epcr_patient_languages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "language_code",
            name="uq_epcr_patient_languages_tenant_chart_lang",
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
    language_code = Column(String(16), nullable=False)
    sequence_index = Column(Integer, nullable=False, default=0)

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


class PatientPhoneNumber(Base):
    """NEMSIS ePatient.18 Patient's Phone Number (1:M, with type code)."""

    __tablename__ = "epcr_patient_phone_numbers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            "phone_number",
            name="uq_epcr_patient_phone_numbers_tenant_chart_phone",
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
    phone_number = Column(String(32), nullable=False)
    phone_type_code = Column(String(16), nullable=True)
    sequence_index = Column(Integer, nullable=False, default=0)

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


__all__ = [
    "PatientProfileNemsisExt",
    "PatientHomeAddress",
    "PatientRace",
    "PatientLanguage",
    "PatientPhoneNumber",
]
