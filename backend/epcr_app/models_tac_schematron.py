from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship

from epcr_app.models import Base


class TacSchematronPackage(Base):
    __tablename__ = "tac_schematron_packages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "package_label", "deleted_at", name="uq_tac_schematron_package_label_per_tenant"),
    )

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    package_label = Column(String(255), nullable=False)
    source = Column(String(64), nullable=False, default="NEMSIS_TAC_WEB_CONFERENCE")
    status = Column(String(32), nullable=False, default="uploaded", index=True)
    created_by_user_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by_user_id = Column(String(255), nullable=True)
    delete_reason = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))

    assets = relationship("TacSchematronAsset", back_populates="package", cascade="all, delete-orphan")
    audit_entries = relationship("TacSchematronAuditLog", back_populates="package", cascade="all, delete-orphan")


class TacSchematronAsset(Base):
    __tablename__ = "tac_schematron_assets"

    id = Column(String(36), primary_key=True, index=True)
    package_id = Column(String(36), ForeignKey("tac_schematron_packages.id"), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    dataset_type = Column(String(32), nullable=False, default="UNKNOWN", index=True)
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(Text, nullable=True)
    storage_key = Column(Text, nullable=True)
    sha256 = Column(String(64), nullable=False, index=True)
    xml_root = Column(String(128), nullable=True)
    schematron_namespace = Column(String(255), nullable=True)
    assertion_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    natural_language_messages_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by_user_id = Column(String(255), nullable=True)
    delete_reason = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, server_default=text("1"))

    package = relationship("TacSchematronPackage", back_populates="assets")
    audit_entries = relationship("TacSchematronAuditLog", back_populates="asset")


class TacSchematronAuditLog(Base):
    __tablename__ = "tac_schematron_audit_log"

    id = Column(String(36), primary_key=True, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    package_id = Column(String(36), ForeignKey("tac_schematron_packages.id"), nullable=False, index=True)
    asset_id = Column(String(36), ForeignKey("tac_schematron_assets.id"), nullable=True, index=True)
    user_id = Column(String(255), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    detail_json = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))

    package = relationship("TacSchematronPackage", back_populates="audit_entries")
    asset = relationship("TacSchematronAsset", back_populates="audit_entries")
