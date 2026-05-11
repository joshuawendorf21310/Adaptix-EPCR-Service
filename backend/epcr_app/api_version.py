"""Deployed build/version proof endpoint for the EPCR service.

Exposes a small, non-sensitive metadata document that allows external
validators (CI, deployment smoke tests, the Layer 11 live workflow check)
to confirm exactly which commit of Adaptix-EPCR-Service is running in a
given environment, plus the pinned NEMSIS dictionary version and asset
version the running image will produce/validate against.

Security contract (must hold):

* This endpoint is intentionally unauthenticated. It reports only
  build-time metadata and pinned constants. It MUST NOT report secrets,
  environment variables, tokens, tenant identifiers, user identifiers,
  database URLs, or anything derived from request-time state.
* All values are resolved at process start from a build-time artifact
  (``/app/.build_info.json``) or, as a fallback, from explicit
  build-time environment variables baked into the image. There is no
  request-time mutation path.
* The endpoint is read-only (HTTP GET).

Sources of truth, in order:

1. ``BUILD_INFO_PATH`` env var (default ``/app/.build_info.json``).
2. Individual env vars: ``BUILD_COMMIT_SHA``, ``BUILD_BRANCH``,
   ``BUILD_TIME``.
3. Hard-coded ``"unknown"`` fallback. The endpoint always returns 200
   so that the absence of build metadata is itself observable instead
   of silently 5xx-ing.

NEMSIS pinning (do not drift): version 3.5.1, asset version
3.5.1.251001CP2. These are constants of the EPCR contract and live
here next to the version endpoint so a single GET surfaces both the
deployed code identity and the deployed NEMSIS contract identity.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# NEMSIS contract pins. Source of truth: the NEMSIS 3.5.1 release imported
# at commit 9bff090cbf95db614529bdff5e1e988a93f89717, asset version
# 3.5.1.251001CP2. These values are referenced by builder/exporter/validator
# and asserted in the live XSD validation tests.
_NEMSIS_VERSION = "3.5.1"
_NEMSIS_ASSET_VERSION = "3.5.1.251001CP2"

_DEFAULT_BUILD_INFO_PATH = "/app/.build_info.json"


class VersionResponse(BaseModel):
    """Public, non-sensitive build identity for the running EPCR service."""

    service: str = Field(..., description="Service name; always 'Adaptix-EPCR-Service'.")
    commit_sha: str = Field(..., description="Full git SHA of the deployed commit, or 'unknown'.")
    short_commit: str = Field(..., description="First 8 characters of commit_sha.")
    branch: str = Field(..., description="Git branch the image was built from, or 'unknown'.")
    build_time: str = Field(..., description="ISO-8601 build timestamp, or 'unknown'.")
    nemsis_version: str = Field(..., description="Pinned NEMSIS dictionary version.")
    nemsis_asset_version: str = Field(
        ..., description="Pinned NEMSIS asset version (e.g. 3.5.1.251001CP2)."
    )


def _load_build_info_from_disk() -> dict[str, Any]:
    """Read ``/app/.build_info.json`` if present; return empty dict otherwise."""
    path_str = os.environ.get("BUILD_INFO_PATH", _DEFAULT_BUILD_INFO_PATH)
    path = Path(path_str)
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("EPCR /version could not read build info at %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("EPCR /version build info at %s is not a JSON object", path)
        return {}
    return data


@lru_cache(maxsize=1)
def _resolve_build_metadata() -> dict[str, str]:
    """Resolve commit_sha/branch/build_time from disk + env, once per process."""
    on_disk = _load_build_info_from_disk()
    commit = (
        str(on_disk.get("commit_sha") or "").strip()
        or os.environ.get("BUILD_COMMIT_SHA", "").strip()
        or "unknown"
    )
    branch = (
        str(on_disk.get("branch") or "").strip()
        or os.environ.get("BUILD_BRANCH", "").strip()
        or "unknown"
    )
    build_time = (
        str(on_disk.get("build_time") or "").strip()
        or os.environ.get("BUILD_TIME", "").strip()
        or "unknown"
    )
    return {"commit_sha": commit, "branch": branch, "build_time": build_time}


def _build_response() -> VersionResponse:
    meta = _resolve_build_metadata()
    commit = meta["commit_sha"]
    short = commit[:8] if commit and commit != "unknown" else "unknown"
    return VersionResponse(
        service="Adaptix-EPCR-Service",
        commit_sha=commit,
        short_commit=short,
        branch=meta["branch"],
        build_time=meta["build_time"],
        nemsis_version=_NEMSIS_VERSION,
        nemsis_asset_version=_NEMSIS_ASSET_VERSION,
    )


# Mounted at both the gateway-prefixed path (used through the public ALB)
# and a non-prefixed convenience path. Both return the same payload.
router = APIRouter(tags=["version"])


@router.get(
    "/api/v1/epcr/version",
    response_model=VersionResponse,
    summary="Deployed EPCR build identity (public, non-sensitive)",
)
async def get_epcr_version() -> VersionResponse:
    """Return deployed commit, branch, build time, and NEMSIS pin."""
    return _build_response()


@router.get(
    "/version",
    response_model=VersionResponse,
    include_in_schema=False,
)
async def get_root_version() -> VersionResponse:
    """Convenience alias for environments that don't go through the gateway."""
    return _build_response()
