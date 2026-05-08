from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from lxml import etree
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.models_tac_schematron import (
    TacSchematronAsset,
    TacSchematronAuditLog,
    TacSchematronPackage,
)
from epcr_app.nemsis.schematron_validator import OfficialSchematronValidator

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STORAGE = _ROOT / "artifact" / "tac_schematron_packages"
_LOCAL_CACHE = _ROOT / "artifact" / "tac_schematron_cache"
_FILES_BUCKET = os.environ.get("FILES_S3_BUCKET", "").strip()
_FILES_PREFIX = os.environ.get("TAC_SCHEMATRON_S3_PREFIX", "nemsis/tac-schematron").strip()

PACKAGE_SOURCE = "NEMSIS_TAC_WEB_CONFERENCE"
STATUS_UPLOADED = "uploaded"
STATUS_INACTIVE = "inactive"
STATUS_ACTIVE = "active"
STATUS_REJECTED = "rejected"
STATUS_DELETED = "deleted"

DATASET_DEM = "DEMDataSet"
DATASET_EMS = "EMSDataSet"
DATASET_UNKNOWN = "UNKNOWN"

ALLOWED_DELETE_ROLES = {
    "admin",
    "superadmin",
    "owner",
    "developer",
    "qa",
    "tac_examiner",
    "examiner",
    "product",
    "paramedic",
}


class TacSchematronPackageError(Exception):
    def __init__(self, message: str, *, status_code: int, detail: dict[str, Any]) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class SchematronValidatorProvenance:
    validator_source: str
    package_id: str | None = None
    package_label: str | None = None
    dataset_type: str | None = None
    asset_checksum: str | None = None
    original_filename: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "validator_source": self.validator_source,
            "package_id": self.package_id,
            "package_label": self.package_label,
            "dataset_type": self.dataset_type,
            "asset_checksum": self.asset_checksum,
            "original_filename": self.original_filename,
        }


@dataclass(frozen=True)
class ResolvedSchematronValidator:
    validator: Any | None
    provenance: SchematronValidatorProvenance


class TenantScopedSchematronValidator:
    def __init__(self, *, schema_path: Path, compile_root: Path) -> None:
        self._validator = OfficialSchematronValidator(
            schema_path=schema_path,
            compile_root=compile_root,
        )

    def validate(self, xml_bytes: bytes) -> Any:
        return self._validator.validate(xml_bytes)


class TacSchematronPackageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_packages(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = (
            await self._session.execute(
                select(TacSchematronPackage)
                .where(
                    TacSchematronPackage.tenant_id == tenant_id,
                    TacSchematronPackage.deleted_at.is_(None),
                )
                .order_by(TacSchematronPackage.created_at.desc())
            )
        ).scalars().all()
        return [await self._serialize_package(row) for row in rows]

    async def get_package(self, tenant_id: str, package_id: str) -> dict[str, Any]:
        package = await self._get_package(tenant_id, package_id)
        return await self._serialize_package(package)

    async def upload_package(
        self,
        *,
        tenant_id: str,
        user_id: str,
        package_label: str,
        files: Iterable[tuple[str, bytes]],
    ) -> dict[str, Any]:
        package = TacSchematronPackage(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            package_label=package_label.strip() or f"TAC package {datetime.now(UTC).isoformat()}",
            source=PACKAGE_SOURCE,
            status=STATUS_UPLOADED,
            created_by_user_id=user_id,
        )
        self._session.add(package)
        await self._session.flush()

        assets: list[TacSchematronAsset] = []
        rejected = False
        for original_filename, content in files:
            asset = await self._create_asset(
                package_id=package.id,
                tenant_id=tenant_id,
                original_filename=original_filename,
                content=content,
            )
            assets.append(asset)
            self._session.add(asset)
            if asset.dataset_type == DATASET_UNKNOWN:
                rejected = True

        package.status = STATUS_REJECTED if rejected else STATUS_INACTIVE
        await self._session.flush()
        await self._write_audit(
            tenant_id=tenant_id,
            package_id=package.id,
            user_id=user_id,
            action="tac_schematron_package_uploaded",
            detail={
                "tenant_id": tenant_id,
                "package_id": package.id,
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "asset_count": len(assets),
            },
        )
        await self._session.commit()
        return await self._serialize_package(package)

    async def activate_package(self, *, tenant_id: str, package_id: str, user_id: str) -> dict[str, Any]:
        package = await self._get_package(tenant_id, package_id)
        if package.status == STATUS_DELETED:
            raise TacSchematronPackageError(
                "Deleted package cannot be activated",
                status_code=409,
                detail={"message": "Deleted package cannot be activated"},
            )
        assets = await self._get_assets(package.id, include_deleted=False)
        dataset_types = {asset.dataset_type for asset in assets}
        if DATASET_UNKNOWN in dataset_types or DATASET_DEM not in dataset_types or DATASET_EMS not in dataset_types:
            raise TacSchematronPackageError(
                "Package must contain both DEM and EMS Schematron assets with known dataset types",
                status_code=422,
                detail={
                    "message": "Package must contain both DEM and EMS Schematron assets with known dataset types",
                    "dataset_types": sorted(dataset_types),
                },
            )
        active_exists = (
            await self._session.execute(
                select(TacSchematronPackage).where(
                    TacSchematronPackage.tenant_id == tenant_id,
                    TacSchematronPackage.id != package_id,
                    TacSchematronPackage.status == STATUS_ACTIVE,
                    TacSchematronPackage.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active_exists is not None:
            raise TacSchematronPackageError(
                "Another active TAC Schematron package already exists for this tenant",
                status_code=409,
                detail={
                    "message": "Another active TAC Schematron package already exists for this tenant",
                    "active_package_id": active_exists.id,
                    "active_package_label": active_exists.package_label,
                },
            )
        package.status = STATUS_ACTIVE
        package.activated_at = datetime.now(UTC)
        await self._write_audit(
            tenant_id=tenant_id,
            package_id=package.id,
            user_id=user_id,
            action="tac_schematron_package_activated",
            detail={
                "tenant_id": tenant_id,
                "package_id": package.id,
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await self._session.commit()
        return await self._serialize_package(package)

    async def deactivate_package(self, *, tenant_id: str, package_id: str, user_id: str) -> dict[str, Any]:
        package = await self._get_package(tenant_id, package_id)
        package.status = STATUS_INACTIVE
        package.deactivated_at = datetime.now(UTC)
        await self._write_audit(
            tenant_id=tenant_id,
            package_id=package.id,
            user_id=user_id,
            action="tac_schematron_package_deactivated",
            detail={
                "tenant_id": tenant_id,
                "package_id": package.id,
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        await self._session.commit()
        return await self._serialize_package(package)

    async def delete_package(
        self,
        *,
        tenant_id: str,
        package_id: str,
        user_id: str,
        roles: list[str],
        reason: str | None,
    ) -> dict[str, Any]:
        self._require_delete_role(roles)
        package = await self._get_package(tenant_id, package_id)
        if package.status == STATUS_ACTIVE:
            raise TacSchematronPackageError(
                "Active package must be deactivated before deletion",
                status_code=409,
                detail={"message": "Active package must be deactivated before deletion"},
            )
        package.status = STATUS_DELETED
        package.deleted_at = datetime.now(UTC)
        package.deleted_by_user_id = user_id
        package.delete_reason = reason
        assets = await self._get_assets(package.id, include_deleted=False)
        for asset in assets:
            asset.deleted_at = datetime.now(UTC)
            asset.deleted_by_user_id = user_id
            asset.delete_reason = reason or "package_deleted"
        await self._write_audit(
            tenant_id=tenant_id,
            package_id=package.id,
            user_id=user_id,
            action="tac_schematron_package_deleted",
            detail={
                "tenant_id": tenant_id,
                "package_id": package.id,
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "reason": reason,
            },
        )
        await self._session.commit()
        return await self._serialize_package(package, include_deleted_assets=True)

    async def delete_asset(
        self,
        *,
        tenant_id: str,
        package_id: str,
        asset_id: str,
        user_id: str,
        roles: list[str],
        reason: str | None,
    ) -> dict[str, Any]:
        self._require_delete_role(roles)
        package = await self._get_package(tenant_id, package_id)
        if package.status == STATUS_ACTIVE:
            raise TacSchematronPackageError(
                "Active package must be deactivated before deleting assets",
                status_code=409,
                detail={"message": "Active package must be deactivated before deleting assets"},
            )
        asset = await self._get_asset(tenant_id, package_id, asset_id)
        asset.deleted_at = datetime.now(UTC)
        asset.deleted_by_user_id = user_id
        asset.delete_reason = reason
        await self._write_audit(
            tenant_id=tenant_id,
            package_id=package.id,
            asset_id=asset.id,
            user_id=user_id,
            action="tac_schematron_asset_deleted",
            detail={
                "tenant_id": tenant_id,
                "package_id": package.id,
                "asset_id": asset.id,
                "original_filename": asset.original_filename,
                "sha256": asset.sha256,
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "reason": reason,
            },
        )
        await self._session.commit()
        return await self._serialize_package(package)

    async def resolve_validator_for_xml(
        self,
        *,
        tenant_id: str,
        xml_bytes: bytes | None,
    ) -> ResolvedSchematronValidator:
        dataset_type = self.detect_chart_dataset_type(xml_bytes)
        if xml_bytes is None:
            return ResolvedSchematronValidator(
                validator=None,
                provenance=SchematronValidatorProvenance(
                    validator_source="no_xml",
                    dataset_type=dataset_type,
                ),
            )
        active_package = (
            await self._session.execute(
                select(TacSchematronPackage).where(
                    TacSchematronPackage.tenant_id == tenant_id,
                    TacSchematronPackage.status == STATUS_ACTIVE,
                    TacSchematronPackage.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active_package is None:
            return ResolvedSchematronValidator(
                validator=OfficialSchematronValidator(),
                provenance=SchematronValidatorProvenance(
                    validator_source="baked_default",
                    dataset_type=dataset_type,
                ),
            )
        asset = (
            await self._session.execute(
                select(TacSchematronAsset).where(
                    TacSchematronAsset.package_id == active_package.id,
                    TacSchematronAsset.dataset_type == dataset_type,
                    TacSchematronAsset.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if asset is None:
            return ResolvedSchematronValidator(
                validator=None,
                provenance=SchematronValidatorProvenance(
                    validator_source="tenant_active_package_missing_dataset",
                    package_id=active_package.id,
                    package_label=active_package.package_label,
                    dataset_type=dataset_type,
                ),
            )
        schema_path = await self._materialize_asset(asset)
        compile_root = _LOCAL_CACHE / active_package.id / dataset_type
        compile_root.mkdir(parents=True, exist_ok=True)
        return ResolvedSchematronValidator(
            validator=TenantScopedSchematronValidator(schema_path=schema_path, compile_root=compile_root),
            provenance=SchematronValidatorProvenance(
                validator_source="tenant_active_package",
                package_id=active_package.id,
                package_label=active_package.package_label,
                dataset_type=asset.dataset_type,
                asset_checksum=asset.sha256,
                original_filename=asset.original_filename,
            ),
        )

    @staticmethod
    def detect_chart_dataset_type(xml_bytes: bytes | None) -> str:
        if not xml_bytes:
            return DATASET_UNKNOWN
        try:
            root = etree.fromstring(xml_bytes)
        except Exception:
            return DATASET_UNKNOWN
        local = etree.QName(root).localname
        if local == DATASET_DEM:
            return DATASET_DEM
        if local == DATASET_EMS:
            return DATASET_EMS
        return DATASET_UNKNOWN

    async def _materialize_asset(self, asset: TacSchematronAsset) -> Path:
        if asset.storage_path and Path(asset.storage_path).exists():
            return Path(asset.storage_path)
        if not asset.storage_path:
            raise TacSchematronPackageError(
                "Schematron asset storage path is unavailable",
                status_code=503,
                detail={"message": "Schematron asset storage path is unavailable"},
            )
        return Path(asset.storage_path)

    async def _create_asset(
        self,
        *,
        package_id: str,
        tenant_id: str,
        original_filename: str,
        content: bytes,
    ) -> TacSchematronAsset:
        parsed = self.inspect_schematron(content, original_filename)
        file_id = str(uuid.uuid4())
        storage_path, storage_key = self._store_asset(package_id, file_id, original_filename, content)
        return TacSchematronAsset(
            id=file_id,
            package_id=package_id,
            tenant_id=tenant_id,
            dataset_type=parsed["dataset_type"],
            original_filename=original_filename,
            storage_path=str(storage_path) if storage_path else None,
            storage_key=storage_key,
            sha256=parsed["sha256"],
            xml_root=parsed["xml_root"],
            schematron_namespace=parsed["schematron_namespace"],
            assertion_count=parsed["assertion_count"],
            warning_count=parsed["warning_count"],
            error_count=parsed["error_count"],
            natural_language_messages_json=json.dumps(parsed["natural_language_messages"]),
        )

    def inspect_schematron(self, content: bytes, original_filename: str) -> dict[str, Any]:
        try:
            root = etree.fromstring(content)
        except Exception as exc:
            raise TacSchematronPackageError(
                "Invalid XML uploaded for TAC Schematron package",
                status_code=422,
                detail={
                    "message": "Invalid XML uploaded for TAC Schematron package",
                    "original_filename": original_filename,
                    "error": str(exc),
                },
            ) from exc
        xml_root = etree.QName(root).localname
        namespace = etree.QName(root).namespace
        text_blob = content.decode("utf-8", errors="ignore")
        file_name = original_filename.lower()
        if "DEMDataSet" in text_blob:
            dataset_type = DATASET_DEM
        elif "EMSDataSet" in text_blob:
            dataset_type = DATASET_EMS
        elif re.search(r"(^|[^a-z])dem([^a-z]|$)", file_name):
            dataset_type = DATASET_DEM
        elif re.search(r"(^|[^a-z])ems([^a-z]|$)", file_name):
            dataset_type = DATASET_EMS
        else:
            dataset_type = DATASET_UNKNOWN
        assertion_nodes = root.xpath("//*[local-name()='assert' or local-name()='report']")
        messages = []
        warning_count = 0
        error_count = 0
        for node in assertion_nodes:
            role = (node.get("role") or "").strip().lower()
            message = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
            if message:
                messages.append(message)
            if role == "warning":
                warning_count += 1
            elif role in {"error", "fatal"}:
                error_count += 1
        return {
            "dataset_type": dataset_type,
            "sha256": hashlib.sha256(content).hexdigest(),
            "xml_root": xml_root,
            "schematron_namespace": namespace,
            "assertion_count": len(assertion_nodes),
            "warning_count": warning_count,
            "error_count": error_count,
            "natural_language_messages": list(dict.fromkeys(messages))[:50],
        }

    def _store_asset(self, package_id: str, asset_id: str, original_filename: str, content: bytes) -> tuple[Path | None, str | None]:
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_filename) or f"{asset_id}.sch"
        local_dir = _DEFAULT_STORAGE / package_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"{asset_id}-{safe_name}"
        local_path.write_bytes(content)
        storage_key = None
        if _FILES_BUCKET:
            try:
                import boto3

                storage_key = f"{_FILES_PREFIX}/{package_id}/{asset_id}-{safe_name}"
                boto3.client("s3").put_object(Bucket=_FILES_BUCKET, Key=storage_key, Body=content)
            except Exception:
                storage_key = None
        return local_path, storage_key

    async def _serialize_package(
        self,
        package: TacSchematronPackage,
        *,
        include_deleted_assets: bool = False,
    ) -> dict[str, Any]:
        assets = await self._get_assets(package.id, include_deleted=include_deleted_assets)
        return {
            "id": package.id,
            "tenant_id": package.tenant_id,
            "package_label": package.package_label,
            "source": package.source,
            "status": package.status,
            "created_by_user_id": package.created_by_user_id,
            "created_at": package.created_at.isoformat() if package.created_at else None,
            "activated_at": package.activated_at.isoformat() if package.activated_at else None,
            "deactivated_at": package.deactivated_at.isoformat() if package.deactivated_at else None,
            "deleted_at": package.deleted_at.isoformat() if package.deleted_at else None,
            "deleted_by_user_id": package.deleted_by_user_id,
            "delete_reason": package.delete_reason,
            "assets": [self._serialize_asset(asset) for asset in assets],
        }

    def _serialize_asset(self, asset: TacSchematronAsset) -> dict[str, Any]:
        try:
            messages = json.loads(asset.natural_language_messages_json or "[]")
        except Exception:
            messages = []
        return {
            "id": asset.id,
            "package_id": asset.package_id,
            "tenant_id": asset.tenant_id,
            "dataset_type": asset.dataset_type,
            "original_filename": asset.original_filename,
            "storage_path": asset.storage_path,
            "storage_key": asset.storage_key,
            "sha256": asset.sha256,
            "xml_root": asset.xml_root,
            "schematron_namespace": asset.schematron_namespace,
            "assertion_count": asset.assertion_count,
            "warning_count": asset.warning_count,
            "error_count": asset.error_count,
            "natural_language_messages": messages,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
            "deleted_by_user_id": asset.deleted_by_user_id,
            "delete_reason": asset.delete_reason,
        }

    async def _get_package(self, tenant_id: str, package_id: str) -> TacSchematronPackage:
        package = (
            await self._session.execute(
                select(TacSchematronPackage).where(
                    TacSchematronPackage.id == package_id,
                    TacSchematronPackage.tenant_id == tenant_id,
                    TacSchematronPackage.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if package is None:
            raise TacSchematronPackageError(
                "TAC Schematron package not found",
                status_code=404,
                detail={"message": "TAC Schematron package not found", "package_id": package_id},
            )
        return package

    async def _get_asset(self, tenant_id: str, package_id: str, asset_id: str) -> TacSchematronAsset:
        asset = (
            await self._session.execute(
                select(TacSchematronAsset).where(
                    TacSchematronAsset.id == asset_id,
                    TacSchematronAsset.package_id == package_id,
                    TacSchematronAsset.tenant_id == tenant_id,
                    TacSchematronAsset.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if asset is None:
            raise TacSchematronPackageError(
                "TAC Schematron asset not found",
                status_code=404,
                detail={"message": "TAC Schematron asset not found", "asset_id": asset_id},
            )
        return asset

    async def _get_assets(self, package_id: str, *, include_deleted: bool) -> list[TacSchematronAsset]:
        clauses = [TacSchematronAsset.package_id == package_id]
        if not include_deleted:
            clauses.append(TacSchematronAsset.deleted_at.is_(None))
        return list((await self._session.execute(select(TacSchematronAsset).where(and_(*clauses)).order_by(TacSchematronAsset.created_at.asc()))).scalars().all())

    async def _write_audit(
        self,
        *,
        tenant_id: str,
        package_id: str,
        user_id: str,
        action: str,
        detail: dict[str, Any],
        asset_id: str | None = None,
    ) -> None:
        self._session.add(
            TacSchematronAuditLog(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                package_id=package_id,
                asset_id=asset_id,
                user_id=user_id,
                action=action,
                detail_json=json.dumps(detail),
            )
        )
        await self._session.flush()

    def _require_delete_role(self, roles: list[str]) -> None:
        normalized = {role.lower() for role in roles}
        if normalized and normalized.isdisjoint(ALLOWED_DELETE_ROLES):
            raise TacSchematronPackageError(
                "Current user is not authorized to delete TAC Schematron packages",
                status_code=403,
                detail={"message": "Current user is not authorized to delete TAC Schematron packages"},
            )
