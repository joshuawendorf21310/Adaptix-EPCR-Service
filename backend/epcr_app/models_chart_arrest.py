"""NEMSIS eArrest (chart cardiac arrest) ORM model.

Backs the ``epcr_chart_arrest`` table created by migration ``032``.
Represents the NEMSIS v3.5.1 eArrest section as a 1:1 child aggregate
of :class:`Chart`. The row is only populated when cardiac arrest is
indicated; absence is acceptable for non-arrest calls. The chart-
finalization gate enforces the Mandatory subset (eArrest.01) and any
conditionally-required subsequent elements via the registry-driven
validator, not in the ORM layer.

NEMSIS element bindings (handled by :mod:`projection_chart_arrest`):

    cardiac_arrest_code               -> eArrest.01 (Mandatory)
    etiology_code                     -> eArrest.02
    resuscitation_attempted_codes_json -> eArrest.03 (1:M list)
    witnessed_by_codes_json           -> eArrest.04 (1:M list)
    aed_use_prior_code                -> eArrest.07
    cpr_type_codes_json               -> eArrest.09 (1:M list)
    hypothermia_indicator_code        -> eArrest.10
    first_monitored_rhythm_code       -> eArrest.11
    rosc_codes_json                   -> eArrest.12 (1:M list)
    neurological_outcome_code         -> eArrest.13
    arrest_at                         -> eArrest.14
    resuscitation_discontinued_at     -> eArrest.15
    reason_discontinued_code          -> eArrest.16
    rhythm_on_arrival_code            -> eArrest.17
    end_of_event_code                 -> eArrest.18
    initial_cpr_at                    -> eArrest.19
    who_first_cpr_code                -> eArrest.20
    who_first_aed_code                -> eArrest.21
    who_first_defib_code              -> eArrest.22

The four 1:M JSON list columns are projected as repeating-group
occurrences (one ledger row per list entry) so the NEMSIS dataset XML
builder can emit each element occurrence separately.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from epcr_app.models import Base


class ChartArrest(Base):
    """NEMSIS eArrest 1:1 aggregate for a chart.

    Only the ``cardiac_arrest_code`` column (eArrest.01) is conceptually
    Mandatory at NEMSIS finalization; all other columns are nullable
    because not every arrest captures every element and many elements
    are only conditionally required. The chart-finalization gate
    enforces NEMSIS Mandatory/Required-at-National subsets via the
    registry-driven validator.

    The four ``*_codes_json`` columns hold JSON arrays of NEMSIS code
    values (1:M repeating-group lists). The projection layer expands
    each list entry into one ledger row.
    """

    __tablename__ = "epcr_chart_arrest"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "chart_id",
            name="uq_epcr_chart_arrest_tenant_chart",
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

    # eArrest.01..22 in NEMSIS-canonical order
    cardiac_arrest_code = Column(String(16), nullable=False)
    etiology_code = Column(String(16), nullable=True)
    resuscitation_attempted_codes_json = Column(JSON, nullable=True)
    witnessed_by_codes_json = Column(JSON, nullable=True)
    aed_use_prior_code = Column(String(16), nullable=True)
    cpr_type_codes_json = Column(JSON, nullable=True)
    hypothermia_indicator_code = Column(String(16), nullable=True)
    first_monitored_rhythm_code = Column(String(16), nullable=True)
    rosc_codes_json = Column(JSON, nullable=True)
    neurological_outcome_code = Column(String(16), nullable=True)
    arrest_at = Column(DateTime(timezone=True), nullable=True)
    resuscitation_discontinued_at = Column(DateTime(timezone=True), nullable=True)
    reason_discontinued_code = Column(String(16), nullable=True)
    rhythm_on_arrival_code = Column(String(16), nullable=True)
    end_of_event_code = Column(String(16), nullable=True)
    initial_cpr_at = Column(DateTime(timezone=True), nullable=True)
    who_first_cpr_code = Column(String(16), nullable=True)
    who_first_aed_code = Column(String(16), nullable=True)
    who_first_defib_code = Column(String(16), nullable=True)

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


__all__ = ["ChartArrest"]
