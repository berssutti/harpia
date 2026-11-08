import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["HARPIA_API_KEY"] = "test-api-key"

import database  # noqa: E402
import main  # noqa: E402
import models  # noqa: E402

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


main.app.dependency_overrides[database.get_db] = override_get_db
client = TestClient(main.app)
AUTH = {"X-API-Key": "test-api-key"}


@pytest.fixture(autouse=True)
def clean_database():
    database.Base.metadata.drop_all(bind=engine)
    database.Base.metadata.create_all(bind=engine)
    main.worker_commands.consume_all()
    yield


def heartbeat_payload(**overrides):
    payload = {
        "status": "connected",
        "version": "0.2.0",
        "instance_id": "worker-instance-1",
        "analyzed_messages": 0,
        "watchlist_size": 0,
        "monitored_groups_count": 0,
    }
    payload.update(overrides)
    return payload


def alert_payload(**overrides):
    payload = {
        "target_value": "ceo@empresa.com",
        "target_type": "email",
        "telegram_group_id": "123456",
        "telegram_group_name": "Grupo Teste",
        "telegram_message_id": "42",
        "message_text": "Vazamento do ceo@empresa.com em grupo",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_health_is_public_and_reports_only_real_dependencies():
    response = client.get("/system/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DEGRADED"
    assert data["components"]["database"]["status"] == "UP"
    assert "redis" not in data["components"]
    assert "opensearch" not in data["components"]


def test_watchlist_crud():
    created = client.post(
        "/watchlist/",
        json={"target_type": "email", "value": "ceo@empresa.com"},
        headers=AUTH,
    )
    assert created.status_code == 200
    item = created.json()
    assert item["value"] == "ceo@empresa.com"

    listed = client.get("/watchlist/", headers=AUTH)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    deleted = client.delete(f"/watchlist/{item['id']}", headers=AUTH)
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}


def test_invalid_watchlist_target_is_rejected():
    response = client.post(
        "/watchlist/",
        json={"target_type": "email", "value": "not-an-email"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_groups_crud():
    created = client.post(
        "/groups/",
        json={"name": "@testgroup"},
        headers=AUTH,
    )
    assert created.status_code == 200
    group = created.json()

    listed = client.get("/groups/", headers=AUTH)
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "@testgroup"

    deleted = client.delete(f"/groups/{group['id']}", headers=AUTH)
    assert deleted.status_code == 200


def test_credentials_keep_secret_when_blank_and_mask_public_value():
    created = client.post(
        "/credentials/",
        json={
            "service": "telegram",
            "api_id": "12345",
            "api_hash": "real-secret",
            "phone": "+5511999999999",
        },
        headers=AUTH,
    )
    assert created.status_code == 200
    assert created.json()["api_hash"] == "********"

    updated = client.post(
        "/credentials/",
        json={
            "service": "telegram",
            "api_id": "12345",
            "api_hash": "",
            "phone": "+5511888888888",
        },
        headers=AUTH,
    )
    assert updated.status_code == 200
    assert updated.json()["api_hash"] == "********"

    internal = client.get("/internal/credentials/telegram", headers=AUTH)
    assert internal.status_code == 200
    assert internal.json()["api_hash"] == "real-secret"
    assert internal.json()["phone"] == "+5511888888888"


def test_internal_monitoring_config_snapshot():
    client.post(
        "/watchlist/",
        json={"target_type": "domain", "value": "empresa.com"},
        headers=AUTH,
    )
    client.post("/groups/", json={"name": "@canal"}, headers=AUTH)

    response = client.get("/internal/monitoring-config", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["watchlist"] == [
        {"value": "empresa.com", "target_type": "domain"}
    ]
    assert data["groups"] == [{"name": "@canal"}]


def test_heartbeat_accumulates_stats_across_worker_instances():
    first = client.post(
        "/internal/worker/heartbeat",
        json=heartbeat_payload(analyzed_messages=5),
        headers=AUTH,
    )
    assert first.status_code == 200
    assert first.json()["analyzed_messages"] == 5

    repeated = client.post(
        "/internal/worker/heartbeat",
        json=heartbeat_payload(analyzed_messages=8),
        headers=AUTH,
    )
    assert repeated.json()["analyzed_messages"] == 8

    restarted = client.post(
        "/internal/worker/heartbeat",
        json=heartbeat_payload(
            instance_id="worker-instance-2",
            analyzed_messages=2,
        ),
        headers=AUTH,
    )
    assert restarted.json()["analyzed_messages"] == 10

    status = client.get("/system/status", headers=AUTH)
    assert status.status_code == 200
    data = status.json()
    assert data["telegram"]["status"] == "online"
    assert data["worker"]["status"] == "online"
    assert data["stats"]["analyzed_messages"] == 10


def test_worker_can_be_reported_as_disconnected_after_stale_heartbeat():
    # No heartbeat in this test database.
    response = client.get("/internal/worker/status", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["connected"] is False

    status = client.get("/system/status", headers=AUTH)
    assert status.json()["telegram"]["status"] == "offline"

    client.post(
        "/internal/worker/heartbeat",
        json=heartbeat_payload(),
        headers=AUTH,
    )
    db = TestingSessionLocal()
    try:
        state = db.get(models.WorkerState, 1)
        state.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=main.WORKER_STALE_AFTER_SECONDS + 1
        )
        db.commit()
    finally:
        db.close()

    status = client.get("/system/status", headers=AUTH)
    assert status.json()["telegram"]["status"] == "offline"
    assert status.json()["worker"]["status"] == "offline"
    assert client.get("/internal/worker/status", headers=AUTH).json()["connected"] is False


def test_alert_ingestion_is_idempotent_and_filterable():
    created = client.post(
        "/internal/alerts",
        json=alert_payload(),
        headers=AUTH,
    )
    assert created.status_code == 201
    assert created.json()["status"] == "created"

    duplicate = client.post(
        "/internal/alerts",
        json=alert_payload(message_text="Retry do worker"),
        headers=AUTH,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"

    history = client.get("/feed/history", headers=AUTH)
    assert history.status_code == 200
    alerts = history.json()
    assert len(alerts) == 1
    assert alerts[0]["telegram_message_id"] == "42"

    by_text = client.get("/feed/history", params={"q": "vazamento"}, headers=AUTH)
    assert len(by_text.json()) == 1

    by_type = client.get(
        "/feed/history", params={"target_type": "email"}, headers=AUTH
    )
    assert len(by_type.json()) == 1

    by_group = client.get(
        "/feed/history", params={"group": "Grupo Teste"}, headers=AUTH
    )
    assert len(by_group.json()) == 1

    other_type = client.get(
        "/feed/history", params={"target_type": "cpf"}, headers=AUTH
    )
    assert other_type.json() == []


def test_feed_is_ordered_by_event_timestamp():
    older = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    newer = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc).isoformat()

    client.post(
        "/internal/alerts",
        json=alert_payload(
            telegram_message_id="1",
            timestamp=older,
            message_text="alerta antigo",
        ),
        headers=AUTH,
    )
    client.post(
        "/internal/alerts",
        json=alert_payload(
            telegram_message_id="2",
            timestamp=newer,
            message_text="alerta novo",
        ),
        headers=AUTH,
    )

    response = client.get("/feed/history", headers=AUTH)
    assert [item["telegram_message_id"] for item in response.json()] == ["2", "1"]


def test_telegram_commands_are_transient_and_consumed_once():
    response = client.post(
        "/telegram/auth-code",
        json={"code": "12345"},
        headers=AUTH,
    )
    assert response.status_code == 200

    first = client.get("/internal/worker/commands", headers=AUTH)
    assert first.json()["commands"] == [{"type": "auth_code", "code": "12345"}]

    second = client.get("/internal/worker/commands", headers=AUTH)
    assert second.json()["commands"] == []


def test_new_session_requires_connected_worker_and_enqueues_reset():
    rejected = client.post("/telegram/new-session", headers=AUTH)
    assert rejected.status_code == 409

    client.post(
        "/internal/worker/heartbeat",
        json=heartbeat_payload(),
        headers=AUTH,
    )
    accepted = client.post("/telegram/new-session", headers=AUTH)
    assert accepted.status_code == 200

    commands = client.get("/internal/worker/commands", headers=AUTH)
    assert {"type": "reset_session"} in commands.json()["commands"]


def test_internal_endpoints_require_api_key():
    assert client.get("/internal/worker/status").status_code == 401
    assert client.get("/system/status").status_code == 401
    assert client.get("/system/health").status_code == 200


def test_event_broker_serializes_sse_payloads():
    async def scenario():
        queue = main.event_broker.subscribe()
        try:
            main.event_broker.publish({"analyzed_messages": 7})
            return await asyncio.wait_for(queue.get(), timeout=1)
        finally:
            main.event_broker.unsubscribe(queue)

    message = asyncio.run(scenario())
    assert json.loads(message) == {"analyzed_messages": 7}
