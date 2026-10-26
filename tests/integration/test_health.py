"""
tests/integration/test_health.py — Health and Readiness Endpoint Tests
"""
from fastapi.testclient import TestClient


def test_health_check_returns_ok(client: TestClient):
    """GET /health must return 200 with status ok and valid metadata."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "timestamp" in data


def test_readiness_check_structure(client: TestClient):
    """GET /ready returns JSON with status and checks dictionary."""
    response = client.get("/ready")
    # Returns 200 or 503 depending on database connection
    assert response.status_code in (200, 503)

    data = response.json()
    assert "status" in data
    assert "checks" in data
    assert "database" in data["checks"]
    assert "pgvector" in data["checks"]
