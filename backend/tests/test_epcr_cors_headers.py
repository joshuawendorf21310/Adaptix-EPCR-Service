from fastapi.testclient import TestClient

from epcr_app.main import app


def test_epcr_cors_allows_clinical_identity_headers() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/epcr/charts",
            headers={
                "Origin": "https://app.adaptixcore.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type,x-tenant-id,x-user-id",
            },
        )

    assert response.status_code == 200
    allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "x-tenant-id" in allowed_headers
    assert "x-user-id" in allowed_headers