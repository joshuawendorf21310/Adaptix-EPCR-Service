"""Regression tests for NEMSIS export route tenant scoping."""
from __future__ import annotations

from uuid import uuid4

import pytest

from epcr_app.api_export import generate_export, get_export_history, retry_export
from epcr_app.dependencies import CurrentUser


@pytest.mark.asyncio
async def test_generate_export_uses_jwt_current_user_not_raw_headers(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_generate_export(*, session, tenant_id, user_id, request):
        captured["session"] = session
        captured["tenant_id"] = tenant_id
        captured["user_id"] = user_id
        captured["request"] = request
        return {"status": "captured"}

    monkeypatch.setattr("epcr_app.api_export.NemsisExportService.generate_export", fake_generate_export)

    current_user = CurrentUser(user_id=user_id, tenant_id=tenant_id, email="ems@example.test")
    request = object()
    session = object()

    response = await generate_export(request=request, current_user=current_user, session=session)

    assert response == {"status": "captured"}
    assert captured["tenant_id"] == str(tenant_id)
    assert captured["user_id"] == str(user_id)
    assert captured["request"] is request
    assert captured["session"] is session


@pytest.mark.asyncio
async def test_export_history_uses_jwt_current_user_tenant(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_get_export_history(*, session, tenant_id, chart_id, limit, offset):
        captured["tenant_id"] = tenant_id
        captured["chart_id"] = chart_id
        captured["limit"] = limit
        captured["offset"] = offset
        return {"status": "captured"}

    monkeypatch.setattr("epcr_app.api_export.NemsisExportService.get_export_history", fake_get_export_history)

    response = await get_export_history(
        chart_id="chart-1",
        limit=10,
        offset=2,
        current_user=CurrentUser(user_id=user_id, tenant_id=tenant_id),
        session=object(),
    )

    assert response == {"status": "captured"}
    assert captured["tenant_id"] == str(tenant_id)
    assert captured["chart_id"] == "chart-1"
    assert captured["limit"] == 10
    assert captured["offset"] == 2


@pytest.mark.asyncio
async def test_retry_export_uses_jwt_current_user_not_raw_headers(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_retry_export(*, session, tenant_id, user_id, export_id, request):
        captured["tenant_id"] = tenant_id
        captured["user_id"] = user_id
        captured["export_id"] = export_id
        captured["request"] = request
        return {"status": "captured"}

    monkeypatch.setattr("epcr_app.api_export.NemsisExportService.retry_export", fake_retry_export)

    request = object()
    response = await retry_export(
        export_id=42,
        request=request,
        current_user=CurrentUser(user_id=user_id, tenant_id=tenant_id),
        session=object(),
    )

    assert response == {"status": "captured"}
    assert captured["tenant_id"] == str(tenant_id)
    assert captured["user_id"] == str(user_id)
    assert captured["export_id"] == 42
    assert captured["request"] is request
