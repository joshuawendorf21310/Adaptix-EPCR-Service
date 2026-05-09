from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _build_app():
    if "epcr_app.main" in sys.modules:
        del sys.modules["epcr_app.main"]
    return importlib.import_module("epcr_app.main").app


def test_epcr_health_and_ready_routes_exist_with_prefixed_aliases() -> None:
    app = _build_app()
    client = TestClient(app)

    for path in ("/healthz", "/readyz", "/api/v1/epcr/healthz", "/api/v1/epcr/readyz"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "epcr"}