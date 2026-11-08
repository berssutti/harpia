from fastapi import FastAPI, Depends, HTTPException, Request, Query, Response
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text, or_
from loguru import logger
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from collections import deque
from contextlib import asynccontextmanager
from typing import Optional
import asyncio
import json
import os
import re
import secrets
import time
import uuid

import models
import schemas
import database

@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting Harpia Backend API")
    yield


app = FastAPI(title="Harpia API", lifespan=lifespan)
VERSION = "0.2.0"

# Shared secret required by every data/mutation endpoint. The web app and the
# worker send it in the X-API-Key header. Without it the API fails closed.
API_KEY = os.getenv("HARPIA_API_KEY", "").strip()
PUBLIC_PATHS = {"/system/health"}

# No CORS by default: the browser talks to the Nuxt same-origin proxy, never to
# this API directly. Set HARPIA_CORS_ORIGINS only for trusted extra origins.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("HARPIA_CORS_ORIGINS", "").split(",")
    if origin.strip()
]


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


WORKER_STALE_AFTER_SECONDS = _positive_int_env("WORKER_STALE_AFTER_SECONDS", 90)
TELEGRAM_COMMAND_TTL_SECONDS = _positive_int_env("TELEGRAM_COMMAND_TTL_SECONDS", 600)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    if not API_KEY:
        logger.error("HARPIA_API_KEY is not configured; refusing requests.")
        return JSONResponse(
            status_code=503,
            content={"detail": "API key not configured on the server"},
        )

    provided = request.headers.get("x-api-key", "")
    if not provided or not secrets.compare_digest(provided, API_KEY):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


# Added after the auth middleware so CORS remains the outermost layer and can
# decorate 401 responses.
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

models.Base.metadata.create_all(bind=database.engine)

VALID_TARGET_TYPES = {"email", "domain", "cpf"}


def normalize_group_key(name: str) -> str:
    return name.strip().lower().lstrip("@")


def is_valid_target(target_type: str, value: str) -> bool:
    if target_type not in VALID_TARGET_TYPES or not value or any(ch.isspace() for ch in value):
        return False
    if target_type == "email":
        return re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value) is not None
    if target_type == "cpf":
        return re.fullmatch(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", value) is not None
    if target_type == "domain":
        return "." in value and "@" not in value
    return False


class EventBroker:
    """In-process fan-out for SSE clients.

    Uvicorn runs a single process in this Compose setup, so an in-memory broker
    is enough. Alerts are always committed before they are published here.
    """

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, payload: dict) -> None:
        message = json.dumps(payload, ensure_ascii=False)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("SSE client queue is full; dropping an event.")


event_broker = EventBroker()


@dataclass
class WorkerCommand:
    type: str
    payload: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


class CommandQueue:
    """Transient UI -> worker commands.

    Authentication codes and 2FA passwords are intentionally kept in memory
    only. They expire and are never written to SQLite or application logs.
    """

    def __init__(self, ttl_seconds: int, max_items: int = 20):
        self._ttl_seconds = ttl_seconds
        self._max_items = max_items
        self._commands: deque[WorkerCommand] = deque()
        self._lock = Lock()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._ttl_seconds
        while self._commands and self._commands[0].created_at < cutoff:
            self._commands.popleft()

    def add(self, command_type: str, **payload) -> None:
        with self._lock:
            self._prune()
            self._commands.append(WorkerCommand(type=command_type, payload=payload))
            while len(self._commands) > self._max_items:
                self._commands.popleft()

    def consume_all(self) -> list[dict]:
        with self._lock:
            self._prune()
            commands = [
                {"type": command.type, **command.payload}
                for command in self._commands
            ]
            self._commands.clear()
            return commands


worker_commands = CommandQueue(TELEGRAM_COMMAND_TTL_SECONDS)


def check_database(db: Session):
    try:
        db.execute(text("SELECT 1"))
        return "UP"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return "DOWN"


def get_worker_state(db: Session) -> Optional[models.WorkerState]:
    return db.get(models.WorkerState, 1)


def worker_heartbeat_age(state: Optional[models.WorkerState]) -> Optional[int]:
    if not state or not state.last_heartbeat:
        return None
    last = _as_utc(state.last_heartbeat)
    return max(0, int((utcnow() - last).total_seconds()))


def worker_is_fresh(state: Optional[models.WorkerState]) -> bool:
    age = worker_heartbeat_age(state)
    return age is not None and age <= WORKER_STALE_AFTER_SECONDS


def worker_connected(state: Optional[models.WorkerState]) -> bool:
    return bool(
        state
        and worker_is_fresh(state)
        and state.status == "connected"
    )


TELEGRAM_STATE_LABELS = {
    "connected": ("online", "Conectado"),
    "waiting_for_code": ("waiting_for_code", "Aguardando Código"),
    "waiting_for_password": ("waiting_for_password", "Aguardando Senha 2FA"),
    "restarting": ("restarting", "Aguardando Telegram"),
    "error": ("error", "Erro de Autenticação"),
    "starting": ("offline", "Worker iniciando"),
}


def telegram_status_payload(state: Optional[models.WorkerState]) -> dict:
    if not worker_is_fresh(state):
        return {"status": "offline", "detail": "Desconectado (sem heartbeat)"}
    status, detail = TELEGRAM_STATE_LABELS.get(
        state.status, ("offline", "Estado desconhecido")
    )
    return {"status": status, "detail": detail}


def worker_status_payload(state: Optional[models.WorkerState]) -> dict:
    age = worker_heartbeat_age(state)
    fresh = worker_is_fresh(state)

    if age is None:
        detail = "Nenhum heartbeat recebido"
    elif fresh:
        detail = f"Heartbeat há {age}s"
    else:
        detail = f"Sem heartbeat há {age}s"

    last_heartbeat = _as_utc(state.last_heartbeat) if state else None
    return {
        "status": "online" if fresh else "offline",
        "detail": detail,
        "last_heartbeat": last_heartbeat.isoformat() if last_heartbeat else None,
        "version": state.version if state else None,
        "watchlist_size": state.watchlist_size if state else 0,
        "monitored_groups_count": state.monitored_groups_count if state else 0,
    }


@app.get("/system/health")
def get_health(db: Session = Depends(database.get_db)):
    db_status = check_database(db)
    state = get_worker_state(db)
    fresh = worker_is_fresh(state)
    age = worker_heartbeat_age(state)

    overall_status = "UP"
    if db_status != "UP":
        overall_status = "DOWN"
    elif not fresh:
        overall_status = "DEGRADED"

    return {
        "status": overall_status,
        "version": VERSION,
        "components": {
            "database": {"status": db_status},
            "worker": {
                "status": "UP" if fresh else "DOWN",
                "telegram_status": state.status if state else "offline",
                "last_heartbeat": (
                    _as_utc(state.last_heartbeat).isoformat()
                    if state and state.last_heartbeat
                    else None
                ),
                "heartbeat_age_seconds": age,
            },
        },
    }


@app.get("/system/status")
def get_system_status(db: Session = Depends(database.get_db)):
    state = get_worker_state(db)
    analyzed_total = state.analyzed_total if state else 0
    alerts_count = db.query(models.Alert).count()

    return {
        "telegram": telegram_status_payload(state),
        "worker": worker_status_payload(state),
        "database": {"status": "online", "detail": "SQLite"},
        "stats": {
            "analyzed_messages": analyzed_total,
            "alerts": alerts_count,
        },
    }


@app.get("/watchlist/", response_model=list[schemas.WatchlistResponse])
def read_watchlist(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(database.get_db),
):
    return db.query(models.Watchlist).offset(skip).limit(limit).all()


@app.post("/watchlist/", response_model=schemas.WatchlistResponse)
def create_watchlist_item(item: schemas.WatchlistCreate, db: Session = Depends(database.get_db)):
    value = item.value.strip()
    target_type = item.target_type.strip().lower()

    if not is_valid_target(target_type, value):
        raise HTTPException(status_code=422, detail="Invalid target value")

    db_item = db.query(models.Watchlist).filter(models.Watchlist.value == value).first()
    if db_item:
        logger.warning("Tentativa de adicionar target já registrado.")
        raise HTTPException(status_code=400, detail="Target already registered")

    db_item = models.Watchlist(target_type=target_type, value=value)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    logger.info("Watchlist item adicionado.")

    return db_item


@app.post("/watchlist/bulk", response_model=schemas.WatchlistBulkResult)
def bulk_create_watchlist_items(
    payload: schemas.WatchlistBulkCreate,
    db: Session = Depends(database.get_db),
):
    added = []
    skipped_duplicates = []
    invalid = []
    seen = {
        value.strip().lower()
        for (value,) in db.query(models.Watchlist.value).all()
        if value
    }

    for item in payload.items:
        value = (item.value or "").strip()
        target_type = (item.target_type or "").strip().lower()

        if not is_valid_target(target_type, value):
            invalid.append(value or item.value or "")
            continue

        key = value.lower()
        if key in seen:
            skipped_duplicates.append(value)
            continue

        db_item = models.Watchlist(target_type=target_type, value=value)
        db.add(db_item)
        added.append(db_item)
        seen.add(key)

    if added:
        db.commit()
        for db_item in added:
            db.refresh(db_item)

    logger.info(
        f"Importação de watchlist: {len(added)} adicionados, "
        f"{len(skipped_duplicates)} duplicados, {len(invalid)} inválidos."
    )

    return {
        "added": [schemas.WatchlistResponse.model_validate(item) for item in added],
        "added_count": len(added),
        "skipped_duplicates": skipped_duplicates,
        "skipped_duplicates_count": len(skipped_duplicates),
        "invalid": invalid,
        "invalid_count": len(invalid),
    }


@app.delete("/watchlist/{item_id}")
def delete_watchlist_item(item_id: int, db: Session = Depends(database.get_db)):
    db_item = db.query(models.Watchlist).filter(models.Watchlist.id == item_id).first()
    if not db_item:
        logger.warning(f"Tentativa de deletar target não encontrado: {item_id}")
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(db_item)
    db.commit()
    logger.info("Watchlist item removido.")

    return {"ok": True}


@app.get("/groups/", response_model=list[schemas.MonitoredGroupResponse])
def read_groups(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(database.get_db),
):
    return db.query(models.MonitoredGroup).offset(skip).limit(limit).all()


@app.post("/groups/", response_model=schemas.MonitoredGroupResponse)
def create_group(group: schemas.MonitoredGroupCreate, db: Session = Depends(database.get_db)):
    name = group.name.strip()
    if not name or any(ch.isspace() for ch in name):
        raise HTTPException(status_code=422, detail="Invalid group name")

    db_group = models.MonitoredGroup(
        name=name,
        telegram_chat_id=group.telegram_chat_id,
    )
    db.add(db_group)
    db.commit()
    db.refresh(db_group)
    logger.info("Grupo monitorado adicionado.")

    return db_group


@app.post("/groups/bulk", response_model=schemas.GroupBulkResult)
def bulk_create_groups(
    payload: schemas.GroupBulkCreate,
    db: Session = Depends(database.get_db),
):
    added = []
    skipped_duplicates = []
    invalid = []
    seen = {
        normalize_group_key(name)
        for (name,) in db.query(models.MonitoredGroup.name).all()
        if name
    }

    for raw_name in payload.items:
        name = (raw_name or "").strip()

        if not name or len(name) > 255 or any(ch.isspace() for ch in name):
            invalid.append(name or raw_name or "")
            continue

        key = normalize_group_key(name)
        if key in seen:
            skipped_duplicates.append(name)
            continue

        db_group = models.MonitoredGroup(name=name)
        db.add(db_group)
        added.append(db_group)
        seen.add(key)

    if added:
        db.commit()
        for db_group in added:
            db.refresh(db_group)

    logger.info(
        f"Importação de grupos: {len(added)} adicionados, "
        f"{len(skipped_duplicates)} duplicados, {len(invalid)} inválidos."
    )

    return {
        "added": [schemas.MonitoredGroupResponse.model_validate(group) for group in added],
        "added_count": len(added),
        "skipped_duplicates": skipped_duplicates,
        "skipped_duplicates_count": len(skipped_duplicates),
        "invalid": invalid,
        "invalid_count": len(invalid),
    }


@app.delete("/groups/{group_id}")
def delete_group(group_id: int, db: Session = Depends(database.get_db)):
    db_group = db.query(models.MonitoredGroup).filter(models.MonitoredGroup.id == group_id).first()
    if not db_group:
        logger.warning(f"Tentativa de deletar grupo não encontrado: {group_id}")
        raise HTTPException(status_code=404, detail="Group not found")

    name = db_group.name
    db.delete(db_group)
    db.commit()
    logger.info(f"Grupo monitorado removido: {name}")

    return {"ok": True}


def _credentials_response(creds: models.Credentials, reveal_secret: bool = False):
    if reveal_secret:
        api_hash = creds.api_hash
    else:
        api_hash = "********" if creds.api_hash else None

    return schemas.CredentialsResponse(
        id=creds.id,
        service=creds.service,
        api_id=creds.api_id,
        api_hash=api_hash,
        phone=creds.phone,
    )


@app.post("/credentials/", response_model=schemas.CredentialsResponse)
def save_credentials(creds: schemas.CredentialsCreate, db: Session = Depends(database.get_db)):
    service = creds.service.strip().lower()
    db_creds = db.query(models.Credentials).filter(models.Credentials.service == service).first()
    if db_creds:
        db_creds.api_id = creds.api_id
        # An empty api_hash means "keep the stored secret" so the UI never has
        # to receive the plaintext value back.
        if creds.api_hash:
            db_creds.api_hash = creds.api_hash
        db_creds.phone = creds.phone
        logger.info(f"Credenciais atualizadas para o serviço: {service}")
    else:
        if not creds.api_hash:
            raise HTTPException(status_code=422, detail="api_hash is required")
        db_creds = models.Credentials(
            service=service,
            api_id=creds.api_id,
            api_hash=creds.api_hash,
            phone=creds.phone,
        )
        db.add(db_creds)
        logger.info(f"Novas credenciais salvas para o serviço: {service}")
    db.commit()
    db.refresh(db_creds)
    return _credentials_response(db_creds)


@app.get("/credentials/{service}", response_model=schemas.CredentialsResponse)
def get_credentials(service: str, db: Session = Depends(database.get_db)):
    db_creds = db.query(models.Credentials).filter(models.Credentials.service == service).first()
    if not db_creds:
        raise HTTPException(status_code=404, detail="Credentials not found")
    return _credentials_response(db_creds)


@app.get(
    "/internal/credentials/{service}",
    response_model=schemas.CredentialsResponse,
    include_in_schema=False,
)
def get_credentials_for_worker(service: str, db: Session = Depends(database.get_db)):
    """Full credentials for the ingestion worker. Never exposed through the web proxy."""
    db_creds = db.query(models.Credentials).filter(models.Credentials.service == service).first()
    if not db_creds:
        raise HTTPException(status_code=404, detail="Credentials not found")
    return _credentials_response(db_creds, reveal_secret=True)


@app.post("/telegram/auth-code")
def submit_telegram_auth_code(data: schemas.TelegramAuthCode):
    if not data.code and not data.password:
        raise HTTPException(status_code=422, detail="code or password is required")

    if data.code:
        worker_commands.add("auth_code", code=data.code)
    if data.password:
        worker_commands.add("auth_password", password=data.password)

    logger.info("Informação temporária de autenticação do Telegram recebida.")
    return {"ok": True}


@app.post("/telegram/new-session")
def start_new_telegram_session(db: Session = Depends(database.get_db)):
    """Asks the worker to log out so a fresh code/2FA login is required."""
    state = get_worker_state(db)
    if not worker_connected(state):
        raise HTTPException(status_code=409, detail="O Telegram não está conectado")

    worker_commands.add("reset_session")
    logger.info("Nova sessão do Telegram solicitada pela UI.")
    return {"ok": True}


@app.get("/internal/monitoring-config", response_model=schemas.MonitoringConfigResponse, include_in_schema=False)
def get_monitoring_config(db: Session = Depends(database.get_db)):
    """Full configuration snapshot consumed periodically by the worker."""
    watchlist = (
        db.query(models.Watchlist)
        .filter(models.Watchlist.is_active.is_(True))
        .all()
    )
    groups = db.query(models.MonitoredGroup).all()

    return {
        "watchlist": [
            {"value": item.value, "target_type": item.target_type}
            for item in watchlist
        ],
        "groups": [{"name": group.name} for group in groups],
        "generated_at": utcnow(),
    }


@app.get("/internal/worker/commands", include_in_schema=False)
def consume_worker_commands():
    """Consumes transient UI commands. Values are never persisted."""
    return {"commands": worker_commands.consume_all()}


@app.get("/internal/worker/status", include_in_schema=False)
def get_worker_status(db: Session = Depends(database.get_db)):
    state = get_worker_state(db)
    return {
        "connected": worker_connected(state),
        "fresh": worker_is_fresh(state),
        "telegram_status": state.status if state else "offline",
        "last_heartbeat": (
            _as_utc(state.last_heartbeat).isoformat()
            if state and state.last_heartbeat
            else None
        ),
        "heartbeat_age_seconds": worker_heartbeat_age(state),
    }


@app.post("/internal/worker/heartbeat")
async def receive_worker_heartbeat(
    heartbeat: schemas.WorkerHeartbeat,
    db: Session = Depends(database.get_db),
):
    state = get_worker_state(db)
    if state is None:
        state = models.WorkerState(id=1)
        db.add(state)

    previous_instance = state.instance_id
    previous_count = state.last_analyzed_count or 0

    if previous_instance == heartbeat.instance_id and heartbeat.analyzed_messages >= previous_count:
        delta = heartbeat.analyzed_messages - previous_count
    else:
        # A new worker process reports its local counter from zero.
        delta = heartbeat.analyzed_messages

    state.status = heartbeat.status
    state.version = heartbeat.version
    state.instance_id = heartbeat.instance_id
    state.last_heartbeat = utcnow()
    state.last_analyzed_count = heartbeat.analyzed_messages
    state.analyzed_total = (state.analyzed_total or 0) + delta
    state.watchlist_size = heartbeat.watchlist_size
    state.monitored_groups_count = heartbeat.monitored_groups_count

    db.commit()

    if delta > 0:
        event_broker.publish({"analyzed_messages": state.analyzed_total})

    return {"ok": True, "analyzed_messages": state.analyzed_total}


@app.post("/internal/alerts", response_model=schemas.AlertIngestResult)
async def ingest_alert(
    data: schemas.AlertCreate,
    response: Response,
    db: Session = Depends(database.get_db),
):
    """Persist a hit from the worker. Idempotent by Telegram message identity."""
    existing = (
        db.query(models.Alert)
        .filter(
            models.Alert.telegram_group_id == data.telegram_group_id,
            models.Alert.telegram_message_id == data.telegram_message_id,
        )
        .first()
    )
    if existing:
        response.status_code = 200
        return {
            "status": "duplicate",
            "alert": schemas.AlertResponse.model_validate(existing),
        }

    alert = models.Alert(
        id=str(uuid.uuid4()),
        target_value=data.target_value,
        target_type=data.target_type,
        telegram_group_id=data.telegram_group_id,
        telegram_group_name=data.telegram_group_name,
        telegram_message_id=data.telegram_message_id,
        message_text=data.message_text,
        timestamp=_as_utc(data.timestamp) or utcnow(),
        received_at=utcnow(),
    )
    db.add(alert)

    try:
        db.commit()
        db.refresh(alert)
    except IntegrityError:
        # Another concurrent retry inserted the same message first.
        db.rollback()
        existing = (
            db.query(models.Alert)
            .filter(
                models.Alert.telegram_group_id == data.telegram_group_id,
                models.Alert.telegram_message_id == data.telegram_message_id,
            )
            .first()
        )
        if not existing:
            raise
        response.status_code = 200
        return {
            "status": "duplicate",
            "alert": schemas.AlertResponse.model_validate(existing),
        }

    response.status_code = 201
    serialized = schemas.AlertResponse.model_validate(alert).model_dump(mode="json")
    # Notify the dashboard only after the alert is safely persisted.
    event_broker.publish(serialized)
    logger.info("Novo alerta persistido.")

    return {"status": "created", "alert": serialized}


def _like_pattern(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


@app.get("/feed/history", response_model=list[schemas.AlertResponse])
def get_feed_history(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    q: Optional[str] = Query(None, max_length=200),
    target: Optional[str] = Query(None, max_length=320),
    target_type: Optional[str] = Query(None, max_length=16),
    group: Optional[str] = Query(None, max_length=255),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    db: Session = Depends(database.get_db),
):
    query = db.query(models.Alert)

    if q and q.strip():
        pattern = _like_pattern(q.strip())
        query = query.filter(
            or_(
                models.Alert.message_text.ilike(pattern, escape="\\"),
                models.Alert.target_value.ilike(pattern, escape="\\"),
                models.Alert.telegram_group_name.ilike(pattern, escape="\\"),
            )
        )

    if target and target.strip():
        query = query.filter(
            models.Alert.target_value.ilike(
                _like_pattern(target.strip()), escape="\\"
            )
        )

    if target_type and target_type.strip():
        query = query.filter(models.Alert.target_type == target_type.strip().lower())

    if group and group.strip():
        group_value = group.strip()
        query = query.filter(
            or_(
                models.Alert.telegram_group_name.ilike(
                    _like_pattern(group_value), escape="\\"
                ),
                models.Alert.telegram_group_id == group_value,
            )
        )

    if start:
        query = query.filter(models.Alert.timestamp >= (_as_utc(start) or start))
    if end:
        query = query.filter(models.Alert.timestamp <= (_as_utc(end) or end))

    return (
        query.order_by(models.Alert.timestamp.desc(), models.Alert.received_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


async def event_stream(request: Request):
    queue = event_broker.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break

            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue

            yield f"data: {message}\n\n"
    finally:
        event_broker.unsubscribe(queue)


@app.get("/feed/stream")
async def stream_feed(request: Request):
    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
