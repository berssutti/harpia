from loguru import logger
import redis
import json
import threading
import os
import asyncio
import time
import urllib.request
import urllib.error
from telethon import TelegramClient, events, errors
from opensearchpy import OpenSearch
from datetime import datetime, timezone
from contextlib import suppress
from pathlib import Path
import uuid

VERSION = "0.1.0"
watchlist = {} # Stores: { value.lower(): target_type }
monitored_groups = set() # Stores normalized group names/ids

# Use REDIS_URL from env if available (docker-compose sets this)
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.from_url(REDIS_URL)

OPENSEARCH_URL = os.getenv('OPENSEARCH_URL', 'http://localhost:9200')
os_client = OpenSearch(hosts=[OPENSEARCH_URL], use_ssl=False)

BACKEND_URL = os.getenv('BACKEND_URL', 'http://harpia-backend:8000')
BACKEND_API_KEY = os.getenv('HARPIA_API_KEY', '').strip()

# The worker is the only client allowed to read the plaintext Telegram secret.
CREDENTIALS_ENDPOINT = '/internal/credentials/telegram'
SESSION_PATH = Path('session/harpia_session.session')


def remove_session_file():
    try:
        SESSION_PATH.unlink(missing_ok=True)
        logger.info("Arquivo de sessão local removido.")
    except OSError as e:
        logger.error(f"Falha ao remover arquivo de sessão: {e}")


async def end_current_session(client):
    """Ends the worker session so the next client must request a fresh code."""
    logger.info("Nova sessão solicitada. Encerrando a sessão atual do Telegram...")
    try:
        logged_out = await client.log_out()
        if logged_out:
            logger.info("Sessão encerrada no Telegram.")
        else:
            logger.warning("O Telegram não confirmou o encerramento; removendo apenas a sessão local.")
    except Exception as e:
        logger.error(f"Falha ao encerrar a sessão no Telegram: {e}")
    finally:
        # log_out() deletes the file on success; removing it again is harmless
        # and guarantees the next client starts unauthenticated.
        remove_session_file()
        if client.is_connected():
            try:
                await client.disconnect()
            except Exception:
                pass
        try:
            redis_client.delete('worker:telegram:status')
        except Exception as e:
            logger.error(f"Falha ao limpar status do worker no Redis: {e}")


async def listen_for_session_commands(client, session_ending):
    """Listens for reset requests coming from the backend (UI action)."""
    pubsub = redis_client.pubsub()
    pubsub.subscribe('telegram_session')
    logger.info("Listening for Telegram session commands on Redis.")
    try:
        while not session_ending.is_set():
            message = pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                try:
                    data = json.loads(message['data'].decode('utf-8'))
                except Exception as e:
                    logger.error(f"Error parsing session command: {e}")
                    data = {}
                if data.get('action') == 'reset':
                    session_ending.set()
                    await end_current_session(client)
                    return
            await asyncio.sleep(1)
    finally:
        pubsub.close()

def listen_to_redis():
    pubsub = redis_client.pubsub()
    pubsub.subscribe('watchlist_updates', 'group_updates')
    logger.info("Subscribed to Redis for watchlist and group updates.")
    for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                data = json.loads(message['data'])
                channel = message['channel'].decode('utf-8')
                if channel == 'watchlist_updates':
                    val = data['value'].lower()
                    if data['action'] == 'add':
                        watchlist[val] = data.get('target_type', 'unknown')
                        logger.info("Watchlist target added in memory.")
                    elif data['action'] == 'remove':
                        watchlist.pop(val, None)
                        logger.info("Watchlist target removed from memory.")
                elif channel == 'group_updates':
                    name = str(data['name']).lower().replace('@', '')
                    if data['action'] == 'add':
                        monitored_groups.add(name)
                        logger.info("Monitored group added.")
                    elif data['action'] == 'remove':
                        monitored_groups.discard(name)
                        logger.info("Monitored group removed.")
            except Exception as e:
                logger.error(f"Error processing Redis message: {e}")

def get_config_from_api(endpoint):
    try:
        req = urllib.request.Request(f"{BACKEND_URL}{endpoint}")
        if BACKEND_API_KEY:
            req.add_header('X-API-Key', BACKEND_API_KEY)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logger.debug(f"Falha ao buscar config em {endpoint}: {e}")
        return None

def fetch_initial_watchlist():
    logger.info("Fetching initial watchlist from API...")
    data = get_config_from_api('/watchlist/')
    if data:
        for item in data:
            if item.get('is_active'):
                watchlist[item['value'].lower()] = item.get('target_type', 'unknown')
        logger.info(f"Loaded {len(watchlist)} targets into memory.")
    else:
        logger.warning("Could not fetch initial watchlist or it is empty.")

def fetch_initial_groups():
    logger.info("Fetching initial groups from API...")
    data = get_config_from_api('/groups/')
    if data:
        for g in data:
            name = str(g['name']).lower().replace('@', '')
            monitored_groups.add(name)
        logger.info(f"Loaded {len(monitored_groups)} groups into memory.")
    else:
        logger.warning("Could not fetch initial groups or it is empty.")

def wait_for_credentials():
    logger.info("Waiting for Telegram credentials to be configured in the UI...")
    while True:
        creds = get_config_from_api(CREDENTIALS_ENDPOINT)
        if creds and creds.get('api_id') and creds.get('api_hash') and creds.get('phone'):
            logger.info("Credentials found in the database!")
            return creds['api_id'], creds['api_hash'], creds['phone']
        time.sleep(5)

async def main():
    # Load initial watchlist and groups
    fetch_initial_watchlist()
    fetch_initial_groups()

    # Start Redis listener thread
    threading.Thread(target=listen_to_redis, daemon=True).start()

    while True:
        # Wait for user to configure API credentials in the backend
        api_id, api_hash, phone = wait_for_credentials()

        try:
            api_id_int = int(api_id)
        except ValueError:
            logger.error(f"Invalid API ID: '{api_id}'. API ID must be an integer.")
            logger.info("Waiting for credentials to be updated in the database...")
            last_api_id, last_api_hash = api_id, api_hash
            while True:
                await asyncio.sleep(5)
                creds = get_config_from_api(CREDENTIALS_ENDPOINT)
                if creds and (creds.get('api_id') != last_api_id or creds.get('api_hash') != last_api_hash):
                    logger.info("Credentials updated, restarting client...")
                    break
            continue

        client = TelegramClient('session/harpia_session', api_id_int, api_hash)

        @client.on(events.NewMessage(outgoing=True, incoming=True))
        async def handler(event):
            try:
                chat = await event.get_chat()
                chat_username = getattr(chat, 'username', None)
                chat_id = str(event.chat_id)
                
                is_monitored = False
                
                # If monitored_groups is empty, we don't monitor anything to save resources
                if not monitored_groups:
                    return

                # Check ID
                if chat_id in monitored_groups:
                    is_monitored = True
                # Check Username
                if chat_username and chat_username.lower() in monitored_groups:
                    is_monitored = True
                    
                if not is_monitored:
                    return
            except Exception:
                return

            # Increment and publish analyzed messages count with deduplication
            try:
                msg_id = f"processed:{event.chat_id}:{event.id}"
                # Only increment if this message ID hasn't been processed in the last 60s
                if redis_client.set(msg_id, "1", ex=60, nx=True):
                    analyzed_count = redis_client.incr('stats:analyzed_messages')
                    redis_client.publish('stats_updates', json.dumps({"analyzed_messages": analyzed_count}))
            except Exception as e:
                logger.error(f"Error updating analyzed messages count: {e}")

            message_text = event.raw_text.lower()
            for target_value, target_type in watchlist.items():
                if target_value in message_text:
                    # Hit!
                    try:
                        chat = await event.get_chat()
                        chat_name = getattr(chat, 'title', str(event.chat_id))
                    except Exception:
                        chat_name = str(event.chat_id)
                    
                    hit_data = {
                        "id": str(uuid.uuid4()),
                        "target_value": target_value,
                        "target_type": target_type,
                        "telegram_group_id": str(event.chat_id),
                        "telegram_group_name": chat_name,
                        "message_text": event.raw_text,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    logger.info("Hit found for a monitored target!")
                    
                    try:
                        # Index to OpenSearch
                        await asyncio.to_thread(os_client.index, index="hits", body=hit_data)
                        # Notify UI via Redis
                        await asyncio.to_thread(redis_client.publish, 'new_alert', json.dumps(hit_data))
                    except Exception as e:
                        logger.error(f"Error pushing to external services: {e}")
                    
                    # Break after the first match to avoid duplicate indexing for the same message
                    break

        logger.info("Starting Telegram Client...")
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                logger.info("Sessão não autorizada. Solicitando código ao Telegram...")
                send_code_result = await client.send_code_request(phone)
                phone_code_hash = send_code_result.phone_code_hash

                # Subscribe to telegram_auth channel
                auth_pubsub = redis_client.pubsub()
                auth_pubsub.subscribe('telegram_auth')

                async def wait_for_auth_value(key):
                    while True:
                        message = auth_pubsub.get_message(ignore_subscribe_messages=True)
                        if message:
                            try:
                                data = json.loads(message['data'].decode('utf-8'))
                                if data.get(key):
                                    return data[key]
                            except Exception as e:
                                logger.error(f"Error parsing auth message: {e}")
                        await asyncio.sleep(1)

                try:
                    while True:
                        # Update status
                        redis_client.set('worker:telegram:status', 'waiting_for_code')
                        logger.info("Waiting for auth code from UI...")
                        auth_code = await wait_for_auth_value('code')
                        logger.info("Got code, trying to sign in...")

                        try:
                            await client.sign_in(phone=phone, code=auth_code, phone_code_hash=phone_code_hash)
                            logger.info("Login realizado com sucesso!")
                            break
                        except errors.SessionPasswordNeededError:
                            logger.warning("2FA Password needed!")
                            while True:
                                redis_client.set('worker:telegram:status', 'waiting_for_password')
                                password = await wait_for_auth_value('password')
                                logger.info("Got 2FA password, trying to sign in...")
                                try:
                                    await client.sign_in(password=password)
                                    logger.info("Login 2FA realizado com sucesso!")
                                    break
                                except errors.PasswordHashInvalidError:
                                    logger.warning("Senha 2FA inválida. Aguardando nova senha...")
                            break
                        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
                            logger.warning("Código inválido. Aguardando novo código...")
                        except errors.PhoneCodeExpiredError:
                            logger.warning("Código expirado. Solicitando um novo código...")
                            send_code_result = await client.send_code_request(phone)
                            phone_code_hash = send_code_result.phone_code_hash
                finally:
                    auth_pubsub.close()

            logger.info("Worker is connected to Telegram and monitoring!")

            session_ending = asyncio.Event()

            # Start heartbeat loop in background
            async def heartbeat():
                while client.is_connected() and not session_ending.is_set():
                    try:
                        status_data = {
                            "status": "connected",
                            "version": VERSION,
                            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                            "watchlist_size": len(watchlist),
                            "monitored_groups_count": len(monitored_groups)
                        }
                        await asyncio.to_thread(redis_client.set, 'worker:telegram:status', 'connected', ex=60)
                        await asyncio.to_thread(redis_client.set, 'worker:telegram:health', json.dumps(status_data), ex=60)
                    except Exception as e:
                        logger.error(f"Heartbeat failed: {e}")
                    await asyncio.sleep(30)
            
            asyncio.create_task(heartbeat())
            session_listener = asyncio.create_task(listen_for_session_commands(client, session_ending))

            await client.run_until_disconnected()

            unexpected_disconnect = not session_ending.is_set()
            session_ending.set()
            if unexpected_disconnect:
                session_listener.cancel()
            with suppress(asyncio.CancelledError):
                await session_listener

            logger.info("Sessão do Telegram encerrada; reiniciando autenticação...")
            try:
                redis_client.delete('worker:telegram:status')
            except Exception as e:
                logger.error(f"Falha ao limpar status do worker no Redis: {e}")
            await asyncio.sleep(2)
            continue
        except errors.FloodWaitError as e:
            wait_seconds = max(int(getattr(e, 'seconds', 0)) + 5, 60)
            logger.warning(
                f"Telegram limitou novas tentativas. Aguardando {wait_seconds}s antes de solicitar outro código."
            )
            try:
                redis_client.set('worker:telegram:status', 'restarting', ex=wait_seconds + 60)
            except Exception:
                pass
            if client.is_connected():
                await client.disconnect()
            await asyncio.sleep(wait_seconds)
            continue
        except Exception as e:
            if type(e).__name__ == 'ApiIdInvalidError':
                logger.error("Invalid API ID/Hash combination. Please check your credentials in the UI.")
            else:
                logger.error(f"Error starting Telegram Client: {e}")
            
            if client.is_connected():
                await client.disconnect()
                
            logger.info("Waiting for credentials to be updated in the database...")
            last_api_id, last_api_hash = api_id, api_hash
            while True:
                await asyncio.sleep(5)
                creds = get_config_from_api(CREDENTIALS_ENDPOINT)
                if creds and (creds.get('api_id') != last_api_id or creds.get('api_hash') != last_api_hash):
                    logger.info("Credentials updated, restarting client...")
                    break

if __name__ == "__main__":
    asyncio.run(main())
