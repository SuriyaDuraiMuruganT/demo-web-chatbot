"""
tests/integration/test_admin.py — Admin Operations and Authentication Tests
"""
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.database import get_db
from app.models.tenant import Tenant


def test_admin_endpoints_require_authentication(client: TestClient):
    """GET /admin/tenants without credentials returns 401."""
    response = client.get("/admin/tenants")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_admin_endpoints_reject_invalid_credentials(client: TestClient):
    """GET /admin/tenants with wrong password returns 401."""
    import base64
    wrong_creds = base64.b64encode(b"admin:wrong-password").decode("utf-8")
    response = client.get("/admin/tenants", headers={"Authorization": f"Basic {wrong_creds}"})
    assert response.status_code == 401


def test_list_tenants_success(client: TestClient, admin_auth_header: dict, app):
    """GET /admin/tenants with valid credentials returns tenant list."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/admin/tenants", headers=admin_auth_header)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_tenant_success(client: TestClient, admin_auth_header: dict, app):
    """POST /admin/tenants creates new company tenant."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # No existing slug collision
    mock_db.execute.return_value = mock_result
    mock_db.flush = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/admin/tenants",
        headers=admin_auth_header,
        data={
            "name": "New Enterprise Inc",
            "slug": "new-enterprise",
            "description": "Global enterprise partner",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "new-enterprise"
    assert "created successfully" in data["message"].lower()
