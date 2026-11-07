from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import unittest.mock as mock
import pytest

from .main import app
from .database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@mock.patch('harpia-backend.main.redis_client.publish')
def test_create_watchlist_item(mock_publish):
    # Mocking publish as it's an async call in the code (await redis_client.publish)
    # But in the test it might be different depending on how redis-py async works with mock
    mock_publish.return_value = mock.AsyncMock()
    
    response = client.post("/watchlist/", json={"target_type": "email", "value": "ceo@empresa.com", "is_active": True})
    assert response.status_code == 200
    assert response.json()["value"] == "ceo@empresa.com"

def test_read_watchlist():
    response = client.get("/watchlist/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@mock.patch('harpia-backend.main.redis_client.publish')
def test_delete_watchlist_item(mock_publish):
    # Create item first
    item = client.post("/watchlist/", json={"target_type": "phone", "value": "123456789"})
    item_id = item.json()["id"]
    
    response = client.delete(f"/watchlist/{item_id}")
    assert response.status_code == 200
    assert response.json()["ok"] is True

def test_read_groups():
    response = client.get("/groups/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@mock.patch('harpia-backend.main.redis_client.publish')
def test_create_group(mock_publish):
    response = client.post("/groups/", json={"name": "@testgroup", "description": "Test Group"})
    assert response.status_code == 200
    assert response.json()["name"] == "@testgroup"

def test_credentials_flow():
    # Save
    response = client.post("/credentials/", json={"service": "telegram", "api_id": "12345", "api_hash": "hash", "phone": "+123456"})
    assert response.status_code == 200
    
    # Get
    response = client.get("/credentials/telegram")
    assert response.status_code == 200
    assert response.json()["api_id"] == "12345"

def test_get_credentials_not_found():
    response = client.get("/credentials/nonexistent")
    assert response.status_code == 404
