from fastapi.testclient import TestClient
from .main import app, VERSION
import unittest.mock as mock
import pytest

client = TestClient(app)

def test_get_health_endpoint_exists():
    with mock.patch("harpia-backend.main.check_redis", return_value="UP"):
        with mock.patch("harpia-backend.main.check_opensearch", return_value="UP"):
            with mock.patch("harpia-backend.main.check_database", return_value="UP"):
                response = client.get("/system/health")
                assert response.status_code == 200

def test_health_detailed_metrics_up():
    with mock.patch("harpia-backend.main.check_redis", return_value="UP"):
        with mock.patch("harpia-backend.main.check_opensearch", return_value="UP"):
            with mock.patch("harpia-backend.main.check_database", return_value="UP"):
                response = client.get("/system/health")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "UP"
                assert data["version"] == VERSION
                assert data["components"]["redis"]["status"] == "UP"
                assert data["components"]["opensearch"]["status"] == "UP"
                assert data["components"]["database"]["status"] == "UP"

def test_health_degraded():
    with mock.patch("harpia-backend.main.check_redis", return_value="DOWN"):
        with mock.patch("harpia-backend.main.check_opensearch", return_value="UP"):
            with mock.patch("harpia-backend.main.check_database", return_value="UP"):
                response = client.get("/system/health")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "DEGRADED"
                assert data["components"]["redis"]["status"] == "DOWN"
