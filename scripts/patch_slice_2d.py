"""Slice #2D in-container patches: defaults for NEMSIS asset paths,
auth on /validate and /readiness, and GET /export/{id}/artifact route.

Idempotent. Safe to re-run.
"""
from __future__ import annotations

import pathlib


def patch_validator() -> None:
    p = pathlib.Path("/app/epcr_app/nemsis_xsd_validator.py")
    s = p.read_text()
    a = 'os.environ.get("NEMSIS_XSD_PATH", "")'
    b = 'os.environ.get("NEMSIS_XSD_PATH", "/app/nemsis/xsd")'
    if a in s:
        s = s.replace(a, b)
    c = 'os.environ.get("NEMSIS_SCHEMATRON_PATH", "")'
    d = 'os.environ.get("NEMSIS_SCHEMATRON_PATH", "/app/nemsis/schematron")'
    if c in s:
        s = s.replace(c, d)
    p.write_text(s)
    print("[OK] validator defaults patched")


def patch_api_nemsis_auth() -> None:
    p = pathlib.Path("/app/epcr_app/api_nemsis.py")
    s = p.read_text()

    if "from epcr_app.dependencies import get_current_user, CurrentUser" not in s:
        # Insert import after the existing fastapi import block
        marker = "from epcr_app.services import"
        if marker in s:
            s = s.replace(
                marker,
                "from epcr_app.dependencies import get_current_user, CurrentUser\nfrom epcr_app.services import",
                1,
            )
        else:
            # Fallback: add at top
            s = "from epcr_app.dependencies import get_current_user, CurrentUser\n" + s
        print("[OK] auth import added to api_nemsis.py")
    else:
        print("[skip] auth import already present in api_nemsis.py")

    # Patch validate handler signature
    old_validate = (
        "async def validate_chart(\n"
        "    chart_id: str = Query(..., description=\"Chart identifier to validate\"),\n"
        "    x_tenant_id: str | None = Header(default=None, alias=\"X-Tenant-ID\"),\n"
        "    session: AsyncSession = Depends(get_session),\n"
        ") -> ValidationResponse:"
    )
    new_validate = (
        "async def validate_chart(\n"
        "    chart_id: str = Query(..., description=\"Chart identifier to validate\"),\n"
        "    x_tenant_id: str | None = Header(default=None, alias=\"X-Tenant-ID\"),\n"
        "    session: AsyncSession = Depends(get_session),\n"
        "    current_user: CurrentUser = Depends(get_current_user),\n"
        ") -> ValidationResponse:"
    )
    if old_validate in s:
        s = s.replace(old_validate, new_validate)
        print("[OK] validate handler now requires Authorization")
    elif "current_user: CurrentUser = Depends(get_current_user)" in s:
        print("[skip] validate handler already auth-gated")
    else:
        print("[WARN] validate handler signature did not match expected form")

    # Patch readiness handler signature
    old_ready = (
        "async def get_readiness(\n"
        "    chart_id: str = Query(..., description=\"Chart identifier\"),\n"
        "    x_tenant_id: str | None = Header(default=None, alias=\"X-Tenant-ID\"),\n"
        "    session: AsyncSession = Depends(get_session),\n"
        ") -> ReadinessResponse:"
    )
    new_ready = (
        "async def get_readiness(\n"
        "    chart_id: str = Query(..., description=\"Chart identifier\"),\n"
        "    x_tenant_id: str | None = Header(default=None, alias=\"X-Tenant-ID\"),\n"
        "    session: AsyncSession = Depends(get_session),\n"
        "    current_user: CurrentUser = Depends(get_current_user),\n"
        ") -> ReadinessResponse:"
    )
    if old_ready in s:
        s = s.replace(old_ready, new_ready)
        print("[OK] readiness handler now requires Authorization")
    elif s.count("current_user: CurrentUser = Depends(get_current_user)") >= 2:
        print("[skip] readiness handler already auth-gated")
    else:
        print("[WARN] readiness handler signature did not match expected form")

    p.write_text(s)


def patch_artifact_route() -> None:
    services_path = pathlib.Path("/app/epcr_app/services_export.py")
    api_path = pathlib.Path("/app/epcr_app/api_export.py")
    services_src = services_path.read_text()
    api_src = api_path.read_text()

    # Add get_export_artifact to NemsisExportService if missing
    if "async def get_export_artifact" not in services_src:
        # Locate end of class — append before the last line that is module-level (no class re-entry).
        # Simpler: append directly before the line that says retry_export's final return path closes.
        # We append a new staticmethod at the end of file inside NemsisExportService class.
        # Find class start and inject before the final dedent.
        method = '''
    @staticmethod
    async def get_export_artifact(
        session: AsyncSession,
        *,
        tenant_id: str,
        export_id: int,
    ) -> tuple[bytes, str, str]:
        """Fetch a previously generated NEMSIS export artifact from S3.

        Returns:
            (xml_bytes, storage_key, sha256_hex)

        Raises:
            HTTPException 404 if export not found, 409 if no artifact stored,
            500 if S3 fetch fails.
        """
        result = await session.execute(
            select(NemsisExportAttempt).where(
                NemsisExportAttempt.id == export_id,
                NemsisExportAttempt.tenant_id == tenant_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Export attempt {export_id} not found",
            )
        storage_key = getattr(row, "artifact_storage_key", None)
        sha256 = getattr(row, "artifact_sha256", None) or ""
        if not storage_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Export attempt {export_id} has no stored artifact (status={row.attempt_status})",
            )
        bucket = _get_s3_bucket()
        s3_client = boto3.client("s3")
        try:
            obj = s3_client.get_object(Bucket=bucket, Key=storage_key)
            xml_bytes = obj["Body"].read()
        except ClientError as exc:
            logger.error(
                "S3 get_object failed bucket=%s key=%s err=%s",
                bucket, storage_key, exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch artifact from S3: {exc.response.get('Error', {}).get('Code', 'Unknown')}",
            ) from exc
        return xml_bytes, storage_key, sha256
'''
        # Append the method at end of file (it will be at module level — that's wrong).
        # Instead inject just before the last top-level non-method line. Safer: find the very last
        # method definition in NemsisExportService and append after it. We'll detect 'async def retry_export'
        # block and append after it.
        anchor = "    async def retry_export("
        if anchor in services_src:
            # Find the next class-level boundary (a line not starting with whitespace) after the anchor.
            idx = services_src.index(anchor)
            # Walk forward to find end of method: a line that is non-empty and starts with non-space.
            tail = services_src[idx:]
            lines = tail.splitlines(keepends=True)
            consumed = 0
            inside = True
            collected = []
            for i, ln in enumerate(lines):
                collected.append(ln)
                consumed += len(ln)
                if i == 0:
                    continue
                if ln.strip() == "":
                    continue
                # If line starts with no leading space and is non-empty => method ended.
                if not ln.startswith(" ") and not ln.startswith("\t"):
                    # Method ended at this line; back off this line from collected.
                    collected.pop()
                    consumed -= len(ln)
                    break
            insert_at = idx + consumed
            services_src = services_src[:insert_at] + method + services_src[insert_at:]
            services_path.write_text(services_src)
            print("[OK] get_export_artifact appended to NemsisExportService")
        else:
            print("[WARN] retry_export anchor not found; cannot append get_export_artifact")
    else:
        print("[skip] get_export_artifact already present")

    # Add the GET /export/{export_id}/artifact route to api_export.py if missing
    if '"/export/{export_id}/artifact"' not in api_src:
        # Need import for Response and the dependencies pattern
        if "from fastapi.responses import Response" not in api_src:
            api_src = api_src.replace(
                "from fastapi import APIRouter, Depends, Header, HTTPException, Query, status",
                "from fastapi import APIRouter, Depends, Header, HTTPException, Query, status\n"
                "from fastapi.responses import Response",
                1,
            )
        if "from epcr_app.dependencies import get_current_user, CurrentUser" not in api_src:
            api_src = api_src.replace(
                "from epcr_app.db import get_session",
                "from epcr_app.db import get_session\n"
                "from epcr_app.dependencies import get_current_user, CurrentUser",
                1,
            )
        route_block = '''

@router.get("/export/{export_id}/artifact", status_code=200)
async def get_export_artifact(
    export_id: int,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Stream the stored NEMSIS XML artifact for a completed export attempt.

    Returns 404 if the export does not exist, 409 if no artifact was stored
    (e.g. the export was BLOCKED or failed), 500 if the S3 fetch fails.
    """
    tenant_id = require_header(x_tenant_id, "X-Tenant-ID")
    xml_bytes, storage_key, sha256 = await NemsisExportService.get_export_artifact(
        session=session,
        tenant_id=tenant_id,
        export_id=export_id,
    )
    headers = {
        "Content-Disposition": f'attachment; filename="export_{export_id}.xml"',
        "X-Artifact-Storage-Key": storage_key,
        "X-Artifact-SHA256": sha256,
    }
    return Response(content=xml_bytes, media_type="application/xml", headers=headers)
'''
        api_src = api_src.rstrip() + route_block
        api_path.write_text(api_src)
        print("[OK] GET /export/{export_id}/artifact route added")
    else:
        print("[skip] artifact route already present")


if __name__ == "__main__":
    patch_validator()
    patch_api_nemsis_auth()
    patch_artifact_route()
    print("=== Slice #2D patches complete ===")
