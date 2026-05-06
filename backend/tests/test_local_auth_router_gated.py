"""Regression: the local CTA portal auth router (``epcr_app.api_auth``)
MUST NOT be mounted unless ``EPCR_ENABLE_LOCAL_AUTH`` is explicitly set.

Historic defect: the local CTA portal HS256 login router was mounted
unconditionally in production at ``/api/v1/auth/*`` and the gateway
prefix ``/api/v1/epcr/api/v1/auth/*``. This exposed a hardcoded local
testing credential as a production token-issuance endpoint.

The corrected behavior:

* When ``EPCR_ENABLE_LOCAL_AUTH`` is unset/false -> route is absent (404).
* When ``EPCR_ENABLE_LOCAL_AUTH=true``           -> route is mounted.
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _build_app(monkeypatch, enable_local_auth: str | None):
    """(Re)build the FastAPI app with the desired env state."""
    if enable_local_auth is None:
        monkeypatch.delenv("EPCR_ENABLE_LOCAL_AUTH", raising=False)
    else:
        monkeypatch.setenv("EPCR_ENABLE_LOCAL_AUTH", enable_local_auth)

    # Force a reload so module-level ``include_router`` decisions re-evaluate.
    for module_name in [
        "epcr_app.main",
    ]:
        if module_name in sys.modules:
            del sys.modules[module_name]
    main_module = importlib.import_module("epcr_app.main")
    return main_module.app


def _has_route(app, path: str) -> bool:
    return any(getattr(r, "path", "") == path for r in app.routes)


def test_local_auth_router_absent_by_default(monkeypatch):
    app = _build_app(monkeypatch, enable_local_auth=None)
    assert not _has_route(app, "/api/v1/auth/login"), (
        "Local CTA portal /api/v1/auth/login MUST NOT be mounted unless "
        "EPCR_ENABLE_LOCAL_AUTH is explicitly enabled."
    )
    assert not _has_route(app, "/api/v1/auth/local-config")
    # Real ePCR routes remain mounted.
    assert _has_route(app, "/healthz")


def test_local_auth_router_absent_when_explicitly_disabled(monkeypatch):
    app = _build_app(monkeypatch, enable_local_auth="false")
    assert not _has_route(app, "/api/v1/auth/login")
    assert not _has_route(app, "/api/v1/auth/local-config")


def test_local_auth_router_mounted_when_explicitly_enabled(monkeypatch):
    app = _build_app(monkeypatch, enable_local_auth="true")
    assert _has_route(app, "/api/v1/auth/login")
    assert _has_route(app, "/api/v1/auth/local-config")
    # The gateway-prefixed mirror is also enabled.
    assert _has_route(app, "/api/v1/epcr/api/v1/auth/login")


@pytest.fixture(autouse=True)
def _restore_default_module(monkeypatch):
    """After each test, drop the cached main module so other tests get a
    deterministic ``EPCR_ENABLE_LOCAL_AUTH`` resolution."""
    yield
    if "epcr_app.main" in sys.modules:
        del sys.modules["epcr_app.main"]
