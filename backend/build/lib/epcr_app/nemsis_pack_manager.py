"""NEMSIS resource pack manager for the epcr domain.

Manages the lifecycle of NEMSIS resource packs including creation, file ingest,
activation, staging, and archival. Packs contain XSD schemas, Schematron rules,
state datasets, compliance studio scenario bundles, or combinations thereof.

Pack files are stored in S3. Pack and file metadata are persisted in
nemsis_resource_packs and nemsis_pack_files tables.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_S3_BUCKET = os.environ.get("NEMSIS_PACK_S3_BUCKET") or os.environ.get("FILES_S3_BUCKET", "")
_S3_PREFIX = os.environ.get("NEMSIS_PACK_S3_PREFIX", "nemsis/packs")

_VALID_PACK_TYPES = frozenset({
    "national_xsd",
    "national_schematron",
    "wi_state_dataset",
    "wi_schematron",
    "cs_scenarios",
    "bundle",
})

_VALID_STATUSES = frozenset({"pending", "staged", "active", "archived"})

_ROLE_HINTS: dict[str, str] = {
    ".xsd": "xsd",
    ".sch": "schematron",
    ".xsl": "schematron",
    ".wsdl": "wsdl",
    ".xml": "sample",
    ".json": "scenario",
    ".zip": "bundle",
    ".rnc": "schematron",
}


def _detect_role(file_name: str, content_prefix: bytes | None = None) -> str:
    """Infer a pack file role from its filename extension.

    Args:
        file_name: Original file name including extension.
        content_prefix: First bytes of file content for sniffing (optional).

    Returns:
        Role string such as 'xsd', 'schematron', 'scenario', 'sample', or 'unknown'.
    """
    ext = os.path.splitext(file_name.lower())[1]
    if ext in _ROLE_HINTS:
        return _ROLE_HINTS[ext]
    if content_prefix:
        text = content_prefix[:512].decode("utf-8", errors="ignore")
        if "<xs:schema" in text or "<xsd:schema" in text:
            return "xsd"
        if "<sch:schema" in text or "schematron" in text.lower():
            return "schematron"
        if "<definitions" in text or "wsdl" in text.lower():
            return "wsdl"
    return "unknown"


class PackManager:
    """Manages NEMSIS resource pack lifecycle with async SQLAlchemy and S3.

    Provides create, ingest, activate, stage, archive, and query operations
    for NEMSIS resource packs. S3 upload is performed on file ingest when
    S3 is configured. If S3 is unconfigured, the file metadata is stored
    without a remote key and the caller receives an explicit warning.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the PackManager with an async database session.

        Args:
            session: Async SQLAlchemy session for all database operations.
        """
        self._session = session

    async def create_pack(
        self,
        *,
        tenant_id: str,
        name: str,
        pack_type: str,
        nemsis_version: str = "3.5.1",
        created_by_user_id: str,
    ) -> dict[str, Any]:
        """Create a new resource pack in pending status.

        Args:
            tenant_id: Owning tenant identifier.
            name: Human-readable pack name.
            pack_type: One of the valid pack type identifiers.
            nemsis_version: NEMSIS version this pack targets.
            created_by_user_id: User who created the pack.

        Returns:
            Serialized pack dict.

        Raises:
            ValueError: If pack_type is not valid.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        if pack_type not in _VALID_PACK_TYPES:
            raise ValueError(
                f"Invalid pack_type '{pack_type}'. Must be one of: {sorted(_VALID_PACK_TYPES)}"
            )

        pack = NemsisPack(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name,
            pack_type=pack_type,
            nemsis_version=nemsis_version,
            status="pending",
            file_count=0,
            size_bytes=0,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            created_by_user_id=created_by_user_id,
        )
        self._session.add(pack)
        await self._session.flush()
        await self._session.refresh(pack)
        logger.info("PackManager.create_pack: pack_id=%s type=%s", pack.id, pack_type)
        return self._serialize_pack(pack)

    async def ingest_file(
        self,
        *,
        pack_id: str,
        tenant_id: str,
        file_name: str,
        file_content: bytes,
        file_role: str | None = None,
    ) -> dict[str, Any]:
        """Ingest a file into a resource pack, uploading to S3 if configured.

        Args:
            pack_id: Target pack identifier.
            tenant_id: Tenant identifier for authorization.
            file_name: Original filename.
            file_content: Raw file bytes.
            file_role: Optional role override; auto-detected from extension if None.

        Returns:
            Serialized pack file dict.

        Raises:
            ValueError: If pack not found or belongs to different tenant.
        """
        from epcr_app.models_nemsis_core import NemsisPack, NemsisPackFile

        result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        pack = result.scalars().first()
        if not pack:
            raise ValueError(f"Pack {pack_id} not found for tenant {tenant_id}")

        detected_role = file_role or _detect_role(file_name, file_content[:512])
        sha256 = hashlib.sha256(file_content).hexdigest()
        size = len(file_content)

        s3_key: str | None = None
        if _S3_BUCKET:
            s3_key = f"{_S3_PREFIX}/{pack_id}/{file_name}"
            try:
                import boto3
                s3 = boto3.client("s3")
                s3.put_object(Bucket=_S3_BUCKET, Key=s3_key, Body=file_content)
                logger.info("PackManager.ingest_file: uploaded s3://%s/%s", _S3_BUCKET, s3_key)
            except Exception as exc:
                logger.error(
                    "PackManager.ingest_file: S3 upload failed for pack %s file %s: %s",
                    pack_id, file_name, exc,
                )
                s3_key = None
        else:
            logger.warning(
                "PackManager.ingest_file: NEMSIS_PACK_S3_BUCKET not configured — "
                "file %s stored as metadata only (no remote copy)", file_name,
            )

        pack_file = NemsisPackFile(
            id=str(uuid.uuid4()),
            pack_id=pack_id,
            file_name=file_name,
            file_role=detected_role,
            s3_key=s3_key,
            size_bytes=size,
            sha256=sha256,
            uploaded_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self._session.add(pack_file)

        pack.file_count = (pack.file_count or 0) + 1
        pack.size_bytes = (pack.size_bytes or 0) + size
        if _S3_BUCKET and s3_key:
            pack.s3_bucket = _S3_BUCKET
            pack.s3_prefix = f"{_S3_PREFIX}/{pack_id}"

        await self._session.flush()
        await self._session.refresh(pack_file)
        logger.info(
            "PackManager.ingest_file: pack_id=%s file_id=%s role=%s sha256=%s...",
            pack_id, pack_file.id, detected_role, sha256[:8],
        )
        return self._serialize_file(pack_file)

    async def activate_pack(
        self, *, pack_id: str, tenant_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Activate a resource pack, archiving any currently active pack of the same type.

        Args:
            pack_id: Pack to activate.
            tenant_id: Tenant identifier for authorization.
            actor_user_id: User performing the action.

        Returns:
            Serialized updated pack dict.

        Raises:
            ValueError: If pack not found or has no files.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        pack = result.scalars().first()
        if not pack:
            raise ValueError(f"Pack {pack_id} not found for tenant {tenant_id}")

        if (pack.file_count or 0) == 0:
            raise ValueError(f"Pack {pack_id} has no files and cannot be activated")

        existing_result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.tenant_id == tenant_id,
                NemsisPack.pack_type == pack.pack_type,
                NemsisPack.status == "active",
                NemsisPack.id != pack_id,
            )
        )
        for existing in existing_result.scalars().all():
            existing.status = "archived"
            logger.info(
                "PackManager.activate_pack: archived old pack_id=%s type=%s",
                existing.id, existing.pack_type,
            )

        pack.status = "active"
        pack.activated_at = datetime.now(UTC).replace(tzinfo=None)
        await self._session.flush()
        await self._session.refresh(pack)
        logger.info(
            "PackManager.activate_pack: activated pack_id=%s actor=%s",
            pack_id, actor_user_id,
        )
        return self._serialize_pack(pack)

    async def stage_pack(
        self, *, pack_id: str, tenant_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Stage a pending pack for review before activation.

        Args:
            pack_id: Pack to stage.
            tenant_id: Tenant identifier.
            actor_user_id: User performing the action.

        Returns:
            Serialized updated pack dict.

        Raises:
            ValueError: If pack not found or not in pending status.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        pack = result.scalars().first()
        if not pack:
            raise ValueError(f"Pack {pack_id} not found for tenant {tenant_id}")

        if pack.status not in ("pending", "staged"):
            raise ValueError(
                f"Pack {pack_id} is in status '{pack.status}' and cannot be staged"
            )

        pack.status = "staged"
        await self._session.flush()
        await self._session.refresh(pack)
        logger.info("PackManager.stage_pack: staged pack_id=%s actor=%s", pack_id, actor_user_id)
        return self._serialize_pack(pack)

    async def archive_pack(
        self, *, pack_id: str, tenant_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Archive a resource pack, preventing further use.

        Args:
            pack_id: Pack to archive.
            tenant_id: Tenant identifier.
            actor_user_id: User performing the action.

        Returns:
            Serialized updated pack dict.

        Raises:
            ValueError: If pack not found.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        pack = result.scalars().first()
        if not pack:
            raise ValueError(f"Pack {pack_id} not found for tenant {tenant_id}")

        pack.status = "archived"
        await self._session.flush()
        await self._session.refresh(pack)
        logger.info("PackManager.archive_pack: archived pack_id=%s actor=%s", pack_id, actor_user_id)
        return self._serialize_pack(pack)

    async def get_active_pack(
        self, *, tenant_id: str, pack_type: str | None = None
    ) -> dict[str, Any] | None:
        """Return the currently active pack, optionally filtered by type.

        Args:
            tenant_id: Tenant identifier.
            pack_type: Optional pack type filter.

        Returns:
            Serialized pack dict or None if no active pack found.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        stmt = select(NemsisPack).where(
            NemsisPack.tenant_id == tenant_id,
            NemsisPack.status == "active",
        )
        if pack_type:
            stmt = stmt.where(NemsisPack.pack_type == pack_type)
        stmt = stmt.order_by(NemsisPack.activated_at.desc()).limit(1)

        result = await self._session.execute(stmt)
        pack = result.scalars().first()
        return self._serialize_pack(pack) if pack else None

    async def list_packs(self, *, tenant_id: str) -> list[dict[str, Any]]:
        """List all resource packs for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            List of serialized pack dicts ordered by creation time descending.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        result = await self._session.execute(
            select(NemsisPack)
            .where(NemsisPack.tenant_id == tenant_id)
            .order_by(NemsisPack.created_at.desc())
        )
        return [self._serialize_pack(p) for p in result.scalars().all()]

    async def get_pack(self, *, pack_id: str, tenant_id: str) -> dict[str, Any]:
        """Return a single pack by ID.

        Args:
            pack_id: Pack identifier.
            tenant_id: Tenant identifier.

        Returns:
            Serialized pack dict.

        Raises:
            ValueError: If pack not found.
        """
        from epcr_app.models_nemsis_core import NemsisPack

        result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        pack = result.scalars().first()
        if not pack:
            raise ValueError(f"Pack {pack_id} not found")
        return self._serialize_pack(pack)

    async def list_pack_files(
        self, *, pack_id: str, tenant_id: str
    ) -> list[dict[str, Any]]:
        """Return all files attached to a pack.

        Args:
            pack_id: Pack identifier.
            tenant_id: Tenant identifier.

        Returns:
            List of serialized pack file dicts.

        Raises:
            ValueError: If pack not found.
        """
        from epcr_app.models_nemsis_core import NemsisPack, NemsisPackFile

        pack_result = await self._session.execute(
            select(NemsisPack).where(
                NemsisPack.id == pack_id,
                NemsisPack.tenant_id == tenant_id,
            )
        )
        if not pack_result.scalars().first():
            raise ValueError(f"Pack {pack_id} not found")

        result = await self._session.execute(
            select(NemsisPackFile).where(NemsisPackFile.pack_id == pack_id)
        )
        return [self._serialize_file(f) for f in result.scalars().all()]

    async def get_pack_completeness(
        self, *, pack_id: str, tenant_id: str
    ) -> dict[str, Any]:
        """Return completeness analysis for a pack based on its files.

        Args:
            pack_id: Pack identifier.
            tenant_id: Tenant identifier.

        Returns:
            Dict with files_by_role, missing_roles, is_complete boolean.

        Raises:
            ValueError: If pack not found.
        """
        pack = await self.get_pack(pack_id=pack_id, tenant_id=tenant_id)
        files = await self.list_pack_files(pack_id=pack_id, tenant_id=tenant_id)

        roles_present = {f["file_role"] for f in files if f.get("file_role")}
        required_by_type: dict[str, set[str]] = {
            "national_xsd": {"xsd"},
            "national_schematron": {"schematron"},
            "wi_state_dataset": {"xsd", "schematron"},
            "wi_schematron": {"schematron"},
            "cs_scenarios": {"scenario"},
            "bundle": {"xsd", "schematron"},
        }
        required = required_by_type.get(pack.get("pack_type", ""), set())
        missing = sorted(required - roles_present)

        return {
            "pack_id": pack_id,
            "pack_type": pack.get("pack_type"),
            "file_count": len(files),
            "files_by_role": {
                role: sum(1 for f in files if f.get("file_role") == role)
                for role in roles_present
            },
            "required_roles": sorted(required),
            "missing_roles": missing,
            "is_complete": not missing,
        }

    @staticmethod
    def _serialize_pack(pack: Any) -> dict[str, Any]:
        """Serialize a NemsisPack ORM object to a plain dict.

        Args:
            pack: NemsisPack ORM instance.

        Returns:
            Dict representation of the pack.
        """
        return {
            "id": pack.id,
            "tenant_id": pack.tenant_id,
            "name": pack.name,
            "pack_type": pack.pack_type,
            "nemsis_version": pack.nemsis_version,
            "status": pack.status,
            "s3_bucket": pack.s3_bucket,
            "s3_prefix": pack.s3_prefix,
            "file_count": pack.file_count,
            "size_bytes": pack.size_bytes,
            "activated_at": pack.activated_at.isoformat() if pack.activated_at else None,
            "created_at": pack.created_at.isoformat() if pack.created_at else None,
            "created_by_user_id": pack.created_by_user_id,
        }

    @staticmethod
    def _serialize_file(f: Any) -> dict[str, Any]:
        """Serialize a NemsisPackFile ORM object to a plain dict.

        Args:
            f: NemsisPackFile ORM instance.

        Returns:
            Dict representation of the file.
        """
        return {
            "id": f.id,
            "pack_id": f.pack_id,
            "file_name": f.file_name,
            "file_role": f.file_role,
            "s3_key": f.s3_key,
            "size_bytes": f.size_bytes,
            "sha256": f.sha256,
            "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
        }
