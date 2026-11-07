from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from loguru import logger
import models
import schemas
import database
import asyncio
import redis.asyncio as redis
import json
import os
import re
import secrets
import httpx
from sqlalchemy import text

app = FastAPI(title="Harpia API")
VERSION = "0.1.0"

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

# Use REDIS_URL from env if available (docker-compose sets this), otherwise fallback to localhost
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.from_url(redis_url)

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

async def check_redis():
    try:
        if await redis_client.ping():
            return "UP"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
    return "DOWN"

async def check_opensearch():
    opensearch_url = os.getenv('OPENSEARCH_URL', 'http://localhost:9200')
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(opensearch_url)
            if response.status_code == 200:
                return "UP"
    except Exception as e:
        logger.error(f"OpenSearch health check failed: {e}")
    return "DOWN"

def check_database(db: Session):
    try:
        db.execute(text("SELECT 1"))
        return "UP"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
    return "DOWN"

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Harpia Backend API")

@app.get("/system/health")
async def get_health(db: Session = Depends(database.get_db)):
    redis_status = await check_redis()
    os_status = await check_opensearch()
    db_status = check_database(db)
    
    worker_health = None
    try:
        worker_health_raw = await redis_client.get('worker:telegram:health')
        if worker_health_raw:
            worker_health = json.loads(worker_health_raw.decode())
    except Exception as e:
        logger.warning(f"Failed to fetch worker health from Redis: {e}")

    overall_status = "UP"
    if redis_status == "DOWN" or os_status == "DOWN" or db_status == "DOWN":
        overall_status = "DEGRADED"
    if redis_status == "DOWN" and os_status == "DOWN" and db_status == "DOWN":
        overall_status = "DOWN"

    return {
        "status": overall_status,
        "version": VERSION,
        "components": {
            "redis": {"status": redis_status},
            "opensearch": {"status": os_status},
            "database": {"status": db_status},
            "worker": worker_health
        }
    }

@app.get("/system/status")
async def get_system_status():
    status = {
        "telegram": {"status": "offline", "detail": "Desconectado"},
        "opensearch": {"status": "offline", "detail": "Indisponível"},
        "redis": {"status": "offline", "detail": "Indisponível"},
        "stats": {"analyzed_messages": 0}
    }
    
    # Check Redis
    try:
        if await redis_client.ping():
            status["redis"]["status"] = "online"
            status["redis"]["detail"] = "Conectado"
            
            # Get analyzed messages count
            analyzed_messages = await redis_client.get('stats:analyzed_messages')
            if analyzed_messages:
                status["stats"]["analyzed_messages"] = int(analyzed_messages)
    except Exception as e:
        logger.warning(f"Falha ao conectar no Redis (status ping): {e}")
        
    # Check Telegram Worker (via Redis key)
    try:
        worker_status = await redis_client.get('worker:telegram:status')
        if worker_status:
            status_str = worker_status.decode()
            if status_str == 'connected':
                status["telegram"]["status"] = "online"
                status["telegram"]["detail"] = "Conectado"
            elif status_str == 'waiting_for_code':
                status["telegram"]["status"] = "waiting_for_code"
                status["telegram"]["detail"] = "Aguardando Código"
            elif status_str == 'waiting_for_password':
                status["telegram"]["status"] = "waiting_for_password"
                status["telegram"]["detail"] = "Aguardando Senha 2FA"
            elif status_str == 'restarting':
                status["telegram"]["status"] = "restarting"
                status["telegram"]["detail"] = "Aguardando Telegram"
            elif status_str == 'error':
                status["telegram"]["status"] = "error"
                status["telegram"]["detail"] = "Erro de Autenticação"
    except Exception as e:
        logger.warning(f"Falha ao checar status do worker no Redis: {e}")
        
    # Check OpenSearch
    opensearch_url = os.getenv('OPENSEARCH_URL', 'http://localhost:9200')
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(opensearch_url)
            if response.status_code == 200:
                stats_response = await client.get(f"{opensearch_url}/_stats/docs")
                if stats_response.status_code == 200:
                    stats_data = stats_response.json()
                    indices_count = len(stats_data.get('indices', {}))
                    status["opensearch"]["status"] = "online"
                    status["opensearch"]["detail"] = f"{indices_count} índices"
                else:
                    status["opensearch"]["status"] = "online"
                    status["opensearch"]["detail"] = "Conectado"
    except Exception as e:
        logger.warning(f"Falha ao conectar no OpenSearch (status): {e}")
        
    return status

@app.get("/watchlist/", response_model=list[schemas.WatchlistResponse])
def read_watchlist(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(database.get_db),
):
    return db.query(models.Watchlist).offset(skip).limit(limit).all()

@app.post("/watchlist/", response_model=schemas.WatchlistResponse)
async def create_watchlist_item(item: schemas.WatchlistCreate, db: Session = Depends(database.get_db)):
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

    # Publish to Redis for Worker
    message = {"action": "add", "value": value, "target_type": target_type}
    await redis_client.publish("watchlist_updates", json.dumps(message))
    logger.info("Watchlist item adicionado.")

    return db_item

@app.post("/watchlist/bulk", response_model=schemas.WatchlistBulkResult)
async def bulk_create_watchlist_items(payload: schemas.WatchlistBulkCreate, db: Session = Depends(database.get_db)):
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
            try:
                message = {"action": "add", "value": db_item.value, "target_type": db_item.target_type}
                await redis_client.publish("watchlist_updates", json.dumps(message))
            except Exception as e:
                logger.warning(f"Falha ao publicar atualização da watchlist no Redis: {e}")

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
async def delete_watchlist_item(item_id: int, db: Session = Depends(database.get_db)):
    db_item = db.query(models.Watchlist).filter(models.Watchlist.id == item_id).first()
    if not db_item:
        logger.warning(f"Tentativa de deletar target não encontrado: {item_id}")
        raise HTTPException(status_code=404, detail="Item not found")
    
    value = db_item.value
    db.delete(db_item)
    db.commit()

    message = {"action": "remove", "value": value}
    await redis_client.publish("watchlist_updates", json.dumps(message))
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
async def create_group(group: schemas.MonitoredGroupCreate, db: Session = Depends(database.get_db)):
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

    message = {"action": "add", "name": db_group.name}
    await redis_client.publish("group_updates", json.dumps(message))
    logger.info("Grupo monitorado adicionado.")

    return db_group

@app.post("/groups/bulk", response_model=schemas.GroupBulkResult)
async def bulk_create_groups(payload: schemas.GroupBulkCreate, db: Session = Depends(database.get_db)):
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
            try:
                message = {"action": "add", "name": db_group.name}
                await redis_client.publish("group_updates", json.dumps(message))
            except Exception as e:
                logger.warning(f"Falha ao publicar atualização de grupos no Redis: {e}")

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
async def delete_group(group_id: int, db: Session = Depends(database.get_db)):
    db_group = db.query(models.MonitoredGroup).filter(models.MonitoredGroup.id == group_id).first()
    if not db_group:
        logger.warning(f"Tentativa de deletar grupo não encontrado: {group_id}")
        raise HTTPException(status_code=404, detail="Group not found")
    
    name = db_group.name
    db.delete(db_group)
    db.commit()
    
    message = {"action": "remove", "name": name}
    await redis_client.publish("group_updates", json.dumps(message))
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
async def submit_telegram_auth_code(data: schemas.TelegramAuthCode):
    await redis_client.publish("telegram_auth", data.model_dump_json())
    logger.info("Código de autenticação do Telegram enviado via Redis.")
    return {"ok": True}


@app.post("/telegram/new-session")
async def start_new_telegram_session():
    """Asks the worker to log out so a fresh code/2FA login is required."""
    try:
        worker_status = await redis_client.get('worker:telegram:status')
    except Exception as e:
        logger.error(f"Falha ao consultar o status do worker no Redis: {e}")
        raise HTTPException(status_code=503, detail="Não foi possível consultar o worker")

    if worker_status != b'connected':
        raise HTTPException(status_code=409, detail="O Telegram não está conectado")

    await redis_client.publish("telegram_session", json.dumps({"action": "reset"}))
    logger.info("Nova sessão do Telegram solicitada pela UI.")
    return {"ok": True}


async def redis_listener(request: Request):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe('new_alert', 'stats_updates')
    try:
        ping_counter = 0
        while True:
            if await request.is_disconnected():
                break
                
            message = await pubsub.get_message(ignore_subscribe_messages=True)
            if message and message['type'] == 'message':
                yield f"data: {message['data'].decode('utf-8')}\n\n"
            else:
                ping_counter += 1
                if ping_counter >= 150: # ping every 15 seconds
                    yield ": ping\n\n"
                    ping_counter = 0
                    
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Erro no listener do Redis: {e}")
    finally:
        await pubsub.unsubscribe('new_alert', 'stats_updates')
        await pubsub.close()

@app.get("/feed/history")
async def get_feed_history(limit: int = Query(50, ge=1, le=200)):
    opensearch_url = os.getenv('OPENSEARCH_URL', 'http://localhost:9200')
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            query = {
                "size": limit,
                "sort": [
                    {"timestamp": {"order": "desc"}}
                ]
            }
            response = await client.post(f"{opensearch_url}/hits/_search", json=query)
            if response.status_code == 200:
                data = response.json()
                hits = [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
                return hits
            elif response.status_code == 404:
                return []
            else:
                logger.error(f"Erro ao buscar histórico do OpenSearch: {response.text}")
                return []
    except Exception as e:
        logger.error(f"Falha ao conectar no OpenSearch (history): {e}")
        return []

@app.get("/feed/stream")
async def stream_feed(request: Request):
    return StreamingResponse(
        redis_listener(request), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
