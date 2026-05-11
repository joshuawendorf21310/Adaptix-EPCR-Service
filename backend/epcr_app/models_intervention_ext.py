"""NEMSIS eProcedures extension ORM models.

Backs the ``epcr_intervention_nemsis_ext`` and
``epcr_intervention_complications`` tables created by migration ``039``.
The extension table is a 1:1 child of :class:`ClinicalIntervention` and
carries the NEMSIS v3.5.1 eProcedures fields that the existing
intervention model does not cover. Complications are a 1:M child of the
same intervention because eProcedures.07 is a repeating element.

Why a side-car instead of widening ``ClinicalIntervention``: the
existing model is off-limits per the EPCR domain contract; the
intervention row is the source-of-truth for procedure execution while
the side-car carries NEMSIS-specific export attributes that are not part
of the operational workflow.

NEMSIS element bindings (handled by :mod:`projection_intervention_ext`):

    prior_to_ems_indicator_code        -> eProcedures.02
    number_of_attempts                 -> eProcedures.05
    procedure_successful_code          -> eProcedures.06
    ems_professional_type_code         -> eProcedures.10
    authorization_code                 -> eProcedures.11
    authorizing_physician (last,first) -> eProcedures.12 (composite)
    by_another_unit_indicator_code     -> eProcedures.13
    pre_existing_indicator_code        -> eProcedures.14
    complication_code                  -> eProcedures.07 (1:M)
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
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class InterventionNemsisExt(Base):
    """NEMSIS eProcedures 1:1 extension for a clinical intervention.

    Every column is nullable because not every intervention captures
    every eProcedures attribute; the chart-finalization gate enforces
    the Required-at-National subset via the registry-driven validator.
    """

    __tablename__ = "epcr_intervention_nemsis_ext"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "intervention_id",
            name="uq_epcr_intervention_nemsis_ext_tenant_intervention",
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
    intervention_id = Column(
        String(36),
        ForeignKey("epcr_interventions.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    prior_to_ems_indicator_code = Column(String(16), nullable=True)
    number_of_attempts = Column(Integer, nullable=True)
    procedure_successful_code = Column(String(16), nullable=True)
    ems_professional_type_code = Column(String(16), nullable=True)
    authorization_code = Column(String(16), nullable=True)
    authorizing_physician_last_name = Column(String(120), nullable=True)
    authorizing_physician_first_name = Column(String(120), nullable=True)
    by_another_unit_indicator_code = Column(String(16), nullable=True)
    pre_existing_indicator_code = Column(String(16), nullable=True)

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
    intervention = relationship(
        "ClinicalIntervention", foreign_keys=[intervention_id]
    )


class InterventionComplication(Base):
    """NEMSIS eProcedures.07 Procedure Complication (1:M)."""

    __tablename__ = "epcr_intervention_complications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "intervention_id",
            "complication_code",
            name="uq_epcr_intervention_complications_tenant_intervention_code",
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
    intervention_id = Column(
        String(36),
        ForeignKey("epcr_interventions.id"),
        nullable=False,
        index=True,
    )

    complication_code = Column(String(16), nullable=False)
    sequence_index = Column(Integer, nullable=False, server_default=text("0"))

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
    intervention = relationship(
        "ClinicalIntervention", foreign_keys=[intervention_id]
    )


__all__ = ["InterventionNemsisExt", "InterventionComplication"]
