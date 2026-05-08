from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from epcr_app.db import get_session
from epcr_app.dependencies import CurrentUser, get_current_user
from epcr_app.tac_schematron_package_service import TacSchematronPackageError, TacSchematronPackageService

router = APIRouter(prefix="/api/v1/epcr/nemsis/schematron-packages", tags=["tac-schematron-packages"])


class DeleteRequest(BaseModel):
    reason: str | None = None


def _translate(exc: TacSchematronPackageError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_schematron_package(
    package_label: str = Form(...),
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    service = TacSchematronPackageService(session)
    try:
        return await service.upload_package(
            tenant_id=str(current_user.tenant_id),
            user_id=str(current_user.user_id),
            package_label=package_label,
            files=[(file.filename or "unknown.sch", await file.read()) for file in files],
        )
    except TacSchematronPackageError as exc:
        await session.rollback()
        raise _translate(exc) from exc


@router.get("")
async def list_schematron_packages(
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return await TacSchematronPackageService(session).list_packages(str(current_user.tenant_id))


@router.get("/{package_id}")
async def get_schematron_package(
    package_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await TacSchematronPackageService(session).get_package(str(current_user.tenant_id), package_id)
    except TacSchematronPackageError as exc:
        raise _translate(exc) from exc


@router.post("/{package_id}/activate")
async def activate_schematron_package(
    package_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await TacSchematronPackageService(session).activate_package(
            tenant_id=str(current_user.tenant_id),
            package_id=package_id,
            user_id=str(current_user.user_id),
        )
    except TacSchematronPackageError as exc:
        await session.rollback()
        raise _translate(exc) from exc


@router.post("/{package_id}/deactivate")
async def deactivate_schematron_package(
    package_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await TacSchematronPackageService(session).deactivate_package(
            tenant_id=str(current_user.tenant_id),
            package_id=package_id,
            user_id=str(current_user.user_id),
        )
    except TacSchematronPackageError as exc:
        await session.rollback()
        raise _translate(exc) from exc


@router.delete("/{package_id}")
async def delete_schematron_package(
    package_id: str,
    body: DeleteRequest | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await TacSchematronPackageService(session).delete_package(
            tenant_id=str(current_user.tenant_id),
            package_id=package_id,
            user_id=str(current_user.user_id),
            roles=list(current_user.roles),
            reason=body.reason if body else None,
        )
    except TacSchematronPackageError as exc:
        await session.rollback()
        raise _translate(exc) from exc


@router.delete("/{package_id}/assets/{asset_id}")
async def delete_schematron_asset(
    package_id: str,
    asset_id: str,
    body: DeleteRequest | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await TacSchematronPackageService(session).delete_asset(
            tenant_id=str(current_user.tenant_id),
            package_id=package_id,
            asset_id=asset_id,
            user_id=str(current_user.user_id),
            roles=list(current_user.roles),
            reason=body.reason if body else None,
        )
    except TacSchematronPackageError as exc:
        await session.rollback()
        raise _translate(exc) from exc
