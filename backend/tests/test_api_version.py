"""Tests for the deployed build/version proof endpoint.

Asserts the security and correctness contract of
``epcr_app.api_version`` / ``GET /api/v1/epcr/version``:

* Endpoint is unauthenticated and returns HTTP 200.
* Reports commit_sha from /app/.build_info.json when present,
  falling back to BUILD_COMMIT_SHA env, falling back to 'unknown'.
* Reports the pinned NEMSIS version (3.5.1) and asset version
  (3.5.1.251001CP2) regardless of build identity.
* Does not leak secrets, env vars, tenant ids, or request state.
* Both the gateway-prefixed path (/api/v1/epcr/version) and the
  non-prefixed convenience path (/version) return identical payloads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epcr_app import api_version
from epcr_app.main import app


@pytest.fixture(autouse=True)
def _reset_version_cache():
    """Each test sees freshly resolved build metadata."""
    api_version._resolve_build_metadata.cache_clear()
    yield
    api_version._resolve_build_metadata.cache_clear()


def _client() -> TestClient:
    return TestClient(app)


def test_version_endpoint_returns_200_with_required_shape(monkeypatch):
    monkeypatch.delenv("BUILD_INFO_PATH", raising=False)
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_BRANCH", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)
    monkeypatch.setenv("BUILD_INFO_PATH", "/nonexistent/.build_info.json")

    with _client() as client:
        resp = client.get("/api/v1/epcr/version")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    expected_keys = {
        "service",
        "commit_sha",
        "short_commit",
        "branch",
        "build_time",
        "nemsis_version",
        "nemsis_asset_version",
    }
    assert set(body.keys()) == expected_keys
    assert body["service"] == "Adaptix-EPCR-Service"
    assert body["nemsis_version"] == "3.5.1"
    assert body["nemsis_asset_version"] == "3.5.1.251001CP2"


def test_version_endpoint_reads_commit_sha_from_build_info_file(
    monkeypatch, tmp_path: Path
):
    info = tmp_path / ".build_info.json"
    info.write_text(
        json.dumps(
            {
                "commit_sha": "c6cfe4d83325e3375961e04642e8b7801c3e4f9f",
                "branch": "main",
                "build_time": "2026-05-06T15:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUILD_INFO_PATH", str(info))
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)

    with _client() as client:
        resp = client.get("/api/v1/epcr/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["commit_sha"] == "c6cfe4d83325e3375961e04642e8b7801c3e4f9f"
    assert body["short_commit"] == "c6cfe4d8"
    assert body["branch"] == "main"
    assert body["build_time"] == "2026-05-06T15:00:00Z"


def test_version_endpoint_falls_back_to_env_when_no_disk_file(monkeypatch):
    monkeypatch.setenv("BUILD_INFO_PATH", "/nonexistent/.build_info.json")
    monkeypatch.setenv("BUILD_COMMIT_SHA", "deadbeefcafebabe1111222233334444aaaaaaaa")
    monkeypatch.setenv("BUILD_BRANCH", "feature/x")
    monkeypatch.setenv("BUILD_TIME", "2026-01-02T03:04:05Z")

    with _client() as client:
        resp = client.get("/api/v1/epcr/version")
    body = resp.json()
    assert body["commit_sha"] == "deadbeefcafebabe1111222233334444aaaaaaaa"
    assert body["short_commit"] == "deadbeef"
    assert body["branch"] == "feature/x"
    assert body["build_time"] == "2026-01-02T03:04:05Z"


def test_version_endpoint_returns_unknown_when_no_metadata(monkeypatch):
    monkeypatch.setenv("BUILD_INFO_PATH", "/nonexistent/.build_info.json")
    monkeypatch.delenv("BUILD_COMMIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_BRANCH", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)

    with _client() as client:
        resp = client.get("/api/v1/epcr/version")
    body = resp.json()
    assert body["commit_sha"] == "unknown"
    assert body["short_commit"] == "unknown"
    assert body["branch"] == "unknown"
    assert body["build_time"] == "unknown"
    # NEMSIS pin is independent of build identity.
    assert body["nemsis_version"] == "3.5.1"
    assert body["nemsis_asset_version"] == "3.5.1.251001CP2"


def test_version_endpoint_does_not_leak_environment(monkeypatch):
    """Regression: the response must contain only the documented keys.

    No env var values, no DB URL, no tenant id, no request headers.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://leak:leak@leak/leak")
    monkeypatch.setenv("CORE_PROVISIONING_TOKEN", "super-secret-token")
    monkeypatch.setenv("BUILD_COMMIT_SHA", "abcdef0123456789abcdef0123456789abcdef01")

    with _client() as client:
        resp = client.get(
            "/api/v1/epcr/version",
            headers={
                "X-Tenant-ID": "leak-tenant",
                "X-User-Email": "leak@example.com",
                "Authorization": "Bearer leak-token",
            },
        )
    body_text = resp.text
    body = resp.json()

    # No secret material in the body, in any form.
    for forbidden in (
        "leak",
        "super-secret-token",
        "Bearer",
        "DATABASE_URL",
        "CORE_PROVISIONING_TOKEN",
    ):
        assert forbidden not in body_text, f"version endpoint leaked: {forbidden}"

    assert set(body.keys()) == {
        "service",
        "commit_sha",
        "short_commit",
        "branch",
        "build_time",
        "nemsis_version",
        "nemsis_asset_version",
    }


def test_version_endpoint_unprefixed_alias_matches(monkeypatch):
    monkeypatch.setenv("BUILD_INFO_PATH", "/nonexistent/.build_info.json")
    monkeypatch.setenv("BUILD_COMMIT_SHA", "1234567890abcdef1234567890abcdef12345678")
    monkeypatch.setenv("BUILD_BRANCH", "main")
    monkeypatch.setenv("BUILD_TIME", "2026-05-06T16:00:00Z")

    with _client() as client:
        a = client.get("/api/v1/epcr/version").json()
        b = client.get("/version").json()
    assert a == b
