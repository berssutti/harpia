from loguru import logger
import asyncio
import os
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from telethon import TelegramClient, events, errors

VERSION = "0.2.0"

# In-memory configuration. The API is the source of truth; this copy is only
# replaced after a complete snapshot is fetched successfully.
watchlist: dict[str, tuple[str, str]] = {}  # lower(value) -> (original value, type)
monitored_groups: set[str] = set()  # normalized names/ids

BACKEND_URL = os.getenv("BACKEND_URL", "http://harpia-backend:8000").rstrip("/")
BACKEND_API_KEY = os.getenv("HARPIA_API_KEY", "").strip()
CREDENTIALS_ENDPOINT = "/internal/credentials/telegram"
SESSION_PATH = Path("session/harpia_session.session")
INSTANCE_ID = uuid.uuid4().hex


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


CONFIG_POLL_SECONDS = _positive_int_env("WORKER_CONFIG_POLL_SECONDS", 30)
HEARTBEAT_SECONDS = _positive_int_env("WORKER_HEARTBEAT_SECONDS", 15)
COMMAND_POLL_SECONDS = _positive_int_env("WORKER_COMMAND_POLL_SECONDS", 2)
ALERT_QUEUE_SIZE = _positive_int_env("WORKER_ALERT_QUEUE_SIZE", 1000)

http_client: Optional[httpx.AsyncClient] = None

worker_status = {
    "status": "starting",
    "analyzed_messages": 0,
}
heartbeat_wakeup = asyncio.Event()


def set_worker_status(status: str) -> None:
    worker_status["status"] = status
    heartbeat_wakeup.set()

# Guards against duplicated Telethon event deliveries during a short window.
recent_processed: dict[str, float] = {}
analyzed_messages = 0
alert_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=ALERT_QUEUE_SIZE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_monitoring_config(data: dict) -> bool:
    """Replace the in-memory snapshot only after a full payload is parsed."""
    new_watchlist: dict[str, tuple[str, str]] = {}
    for item in data.get("watchlist") or []:
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        target_type = str(item.get("target_type") or "unknown")
        new_watchlist[value.lower()] = (value, target_type)

    new_groups: set[str] = set()
    for group in data.get("groups") or []:
        name = str(group.get("name") or "").strip()
        if not name:
            continue
        new_groups.add(name.lower().replace("@", ""))

    changed = new_watchlist != watchlist or new_groups != monitored_groups
    watchlist.clear()
    watchlist.update(new_watchlist)
    monitored_groups.clear()
    monitored_groups.update(new_groups)

    if changed:
        logger.info(
            f"Monitoramento atualizado: {len(watchlist)} alvos e "
            f"{len(monitored_groups)} grupos."
        )
    return changed


async def api_request(
    method: str,
    path: str,
    *,
    json_body: Optional[dict] = None,
    retries: int = 3,
    timeout: float = 10.0,
) -> httpx.Response:
    if http_client is None:
        raise RuntimeError("HTTP client is not initialized")

    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            response = await http_client.request(
                method,
                path,
                json=json_body,
                timeout=timeout,
            )
            if response.status_code >= 500 or response.status_code == 429:
                last_error = httpx.HTTPStatusError(
                    f"Backend returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            else:
                return response
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc

        if attempt + 1 < retries:
            await asyncio.sleep(min(2 ** attempt, 5))

    if last_error:
        raise last_error
    raise RuntimeError("HTTP request failed without a response")


async def refresh_monitoring_config() -> bool:
    try:
        response = await api_request("GET", "/internal/monitoring-config", retries=2)
        if response.status_code != 200:
            logger.warning(
                f"Backend returned {response.status_code} when fetching configuration."
            )
            return False
        apply_monitoring_config(response.json())
        return True
    except Exception as exc:
        logger.warning(f"Failed to fetch monitoring configuration: {exc}")
        return False


async def config_poll_loop():
    delay = CONFIG_POLL_SECONDS
    while True:
        ok = await refresh_monitoring_config()
        if ok:
            delay = CONFIG_POLL_SECONDS
        else:
            delay = min(delay * 2, 60)
        await asyncio.sleep(delay)


async def heartbeat_loop():
    last_error_log = 0.0
    while True:
        payload = {
            "status": worker_status["status"],
            "version": VERSION,
            "instance_id": INSTANCE_ID,
            "analyzed_messages": analyzed_messages,
            "watchlist_size": len(watchlist),
            "monitored_groups_count": len(monitored_groups),
        }
        try:
            response = await api_request(
                "POST",
                "/internal/worker/heartbeat",
                json_body=payload,
                retries=2,
            )
            if response.status_code not in (200, 201):
                raise RuntimeError(f"Backend returned {response.status_code}")
        except Exception as exc:
            now = time.monotonic()
            if now - last_error_log >= 60:
                logger.warning(f"Failed to send worker heartbeat: {exc}")
                last_error_log = now

        try:
            await asyncio.wait_for(heartbeat_wakeup.wait(), timeout=HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            pass
        heartbeat_wakeup.clear()


async def fetch_worker_commands() -> list[dict]:
    try:
        response = await api_request(
            "GET",
            "/internal/worker/commands",
            retries=2,
            timeout=10.0,
        )
        if response.status_code != 200:
            logger.warning(
                f"Backend returned {response.status_code} when fetching commands."
            )
            return []
        return response.json().get("commands", [])
    except Exception as exc:
        logger.debug(f"Failed to fetch worker commands: {exc}")
        return []


async def wait_for_credentials() -> tuple[str, str, str]:
    logger.info("Waiting for Telegram credentials to be configured in the UI...")
    while True:
        try:
            response = await api_request("GET", CREDENTIALS_ENDPOINT, retries=2)
            if response.status_code == 200:
                creds = response.json()
                if creds.get("api_id") and creds.get("api_hash") and creds.get("phone"):
                    logger.info("Telegram credentials found in the database.")
                    return creds["api_id"], creds["api_hash"], creds["phone"]
        except Exception as exc:
            logger.debug(f"Failed to fetch Telegram credentials: {exc}")
        await asyncio.sleep(5)


async def wait_for_credentials_change(last_api_id: str, last_api_hash: str):
    while True:
        await asyncio.sleep(5)
        try:
            response = await api_request("GET", CREDENTIALS_ENDPOINT, retries=1)
            if response.status_code != 200:
                continue
            creds = response.json()
            if creds.get("api_id") != last_api_id or creds.get("api_hash") != last_api_hash:
                logger.info("Credentials updated, restarting client...")
                return
        except Exception:
            continue


def remove_session_file():
    try:
        SESSION_PATH.unlink(missing_ok=True)
        logger.info("Arquivo de sessão local removido.")
    except OSError as exc:
        logger.error(f"Falha ao remover arquivo de sessão: {exc}")


async def end_current_session(client: TelegramClient):
    """Ends the worker session so the next client must request a fresh code."""
    logger.info("Nova sessão solicitada. Encerrando a sessão atual do Telegram...")
    set_worker_status("restarting")
    try:
        logged_out = await client.log_out()
        if logged_out:
            logger.info("Sessão encerrada no Telegram.")
        else:
            logger.warning(
                "O Telegram não confirmou o encerramento; removendo apenas a sessão local."
            )
    except Exception as exc:
        logger.error(f"Falha ao encerrar a sessão no Telegram: {exc}")
    finally:
        # log_out() deletes the file on success; removing it again is harmless
        # and guarantees the next client starts unauthenticated.
        remove_session_file()
        if client.is_connected():
            try:
                await client.disconnect()
            except Exception:
                pass


async def monitor_session_commands(client: TelegramClient, session_ending: asyncio.Event):
    """Listens for a reset request coming from the backend (UI action)."""
    while not session_ending.is_set():
        commands = await fetch_worker_commands()
        if any(command.get("type") == "reset_session" for command in commands):
            session_ending.set()
            await end_current_session(client)
            return
        await asyncio.sleep(COMMAND_POLL_SECONDS)


async def wait_for_auth_value(expected_key: str):
    """Polls transient commands until the expected value or a reset arrives."""
    while True:
        commands = await fetch_worker_commands()
        for command in commands:
            if command.get("type") == "reset_session":
                return None
            if expected_key == "code" and command.get("type") == "auth_code":
                if command.get("code"):
                    return command["code"]
            if expected_key == "password" and command.get("type") == "auth_password":
                if command.get("password"):
                    return command["password"]
        await asyncio.sleep(COMMAND_POLL_SECONDS)


async def authenticate(client: TelegramClient, phone: str) -> bool:
    """Drives the interactive login. Returns False when a reset was requested."""
    if await client.is_user_authorized():
        return True

    logger.info("Sessão não autorizada. Solicitando código ao Telegram...")
    send_code_result = await client.send_code_request(phone)
    phone_code_hash = send_code_result.phone_code_hash

    while True:
        set_worker_status("waiting_for_code")
        logger.info("Waiting for auth code from UI...")
        auth_code = await wait_for_auth_value("code")
        if auth_code is None:
            return False

        logger.info("Got code, trying to sign in...")
        try:
            await client.sign_in(
                phone=phone,
                code=auth_code,
                phone_code_hash=phone_code_hash,
            )
            logger.info("Login realizado com sucesso!")
            return True
        except errors.SessionPasswordNeededError:
            logger.warning("2FA Password needed!")
            while True:
                set_worker_status("waiting_for_password")
                password = await wait_for_auth_value("password")
                if password is None:
                    return False
                logger.info("Got 2FA password, trying to sign in...")
                try:
                    await client.sign_in(password=password)
                    logger.info("Login 2FA realizado com sucesso!")
                    return True
                except errors.PasswordHashInvalidError:
                    logger.warning("Senha 2FA inválida. Aguardando nova senha...")
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
            logger.warning("Código inválido. Aguardando novo código...")
        except errors.PhoneCodeExpiredError:
            logger.warning("Código expirado. Solicitando um novo código...")
            send_code_result = await client.send_code_request(phone)
            phone_code_hash = send_code_result.phone_code_hash


def mark_message_analyzed(chat_id: int, message_id: int) -> None:
    global analyzed_messages

    key = f"{chat_id}:{message_id}"
    now = time.monotonic()
    if key in recent_processed:
        return

    recent_processed[key] = now
    analyzed_messages += 1
    worker_status["analyzed_messages"] = analyzed_messages

    if len(recent_processed) > 2000:
        cutoff = now - 120
        for old_key, seen_at in list(recent_processed.items()):
            if seen_at < cutoff:
                del recent_processed[old_key]


def queue_alert(payload: dict) -> None:
    try:
        alert_queue.put_nowait(payload)
    except asyncio.QueueFull:
        logger.error("Alert queue is full; dropping a hit.")


async def alert_sender_loop():
    """Sends hits to the API and retries until the backend accepts them."""
    while True:
        payload = await alert_queue.get()
        try:
            delay = 2
            while True:
                try:
                    response = await api_request(
                        "POST",
                        "/internal/alerts",
                        json_body=payload,
                        retries=1,
                        timeout=15.0,
                    )
                    if response.status_code in (200, 201):
                        result = response.json()
                        logger.info(
                            f"Alerta enviado ao backend ({result.get('status', 'ok')})."
                        )
                        break
                    if 400 <= response.status_code < 500:
                        logger.error(
                            "Backend rejected an alert "
                            f"({response.status_code}): {response.text[:200]}"
                        )
                        break
                except Exception as exc:
                    logger.warning(f"Failed to send alert to backend: {exc}")

                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        finally:
            alert_queue.task_done()


def build_event_handler():
    async def handler(event):
        try:
            if not monitored_groups:
                return

            chat = await event.get_chat()
            chat_username = getattr(chat, "username", None)
            chat_id = str(event.chat_id)

            is_monitored = chat_id in monitored_groups
            if chat_username:
                normalized_username = chat_username.lower().replace("@", "")
                is_monitored = is_monitored or normalized_username in monitored_groups
            if not is_monitored:
                return

            mark_message_analyzed(event.chat_id, event.id)

            text = event.raw_text or ""
            lowered = text.lower()
            for target_key, (target_value, target_type) in list(watchlist.items()):
                if not target_key or target_key not in lowered:
                    continue

                chat_name = (
                    getattr(chat, "title", None)
                    or chat_username
                    or chat_id
                )
                queue_alert(
                    {
                        "target_value": target_value,
                        "target_type": target_type,
                        "telegram_group_id": chat_id,
                        "telegram_group_name": str(chat_name),
                        "telegram_message_id": str(event.id),
                        "message_text": text,
                        "timestamp": now_iso(),
                    }
                )
                logger.info("Hit found for a monitored target!")
                # Match the previous behavior: only the first target per message.
                break
        except Exception as exc:
            logger.error(f"Error processing Telegram message: {exc}")

    return handler


async def telegram_loop():
    while True:
        api_id, api_hash, phone = await wait_for_credentials()

        try:
            api_id_int = int(api_id)
        except ValueError:
            logger.error(f"Invalid API ID: '{api_id}'. API ID must be an integer.")
            await wait_for_credentials_change(api_id, api_hash)
            continue

        client = TelegramClient("session/harpia_session", api_id_int, api_hash)
        client.add_event_handler(
            build_event_handler(),
            events.NewMessage(outgoing=True, incoming=True),
        )

        command_task: Optional[asyncio.Task] = None
        session_ending = asyncio.Event()

        try:
            logger.info("Starting Telegram Client...")
            await client.connect()

            authenticated = await authenticate(client, phone)
            if not authenticated:
                logger.info("Autenticação reiniciada; solicitando novo código.")
                continue

            set_worker_status("connected")
            logger.info("Worker is connected to Telegram and monitoring!")

            command_task = asyncio.create_task(
                monitor_session_commands(client, session_ending)
            )

            await client.run_until_disconnected()

            if not session_ending.is_set():
                logger.warning("Sessão do Telegram encerrada inesperadamente.")
            set_worker_status("restarting")
            await asyncio.sleep(2)
        except errors.FloodWaitError as exc:
            wait_seconds = max(int(getattr(exc, "seconds", 0)) + 5, 60)
            logger.warning(
                "Telegram limitou novas tentativas. "
                f"Aguardando {wait_seconds}s antes de solicitar outro código."
            )
            set_worker_status("restarting")
            await asyncio.sleep(wait_seconds)
        except Exception as exc:
            if type(exc).__name__ == "ApiIdInvalidError":
                logger.error(
                    "Invalid API ID/Hash combination. "
                    "Please check your credentials in the UI."
                )
                await wait_for_credentials_change(api_id, api_hash)
            else:
                logger.error(f"Error starting Telegram Client: {exc}")
                set_worker_status("restarting")
                await asyncio.sleep(5)
        finally:
            if command_task:
                command_task.cancel()
                with suppress(asyncio.CancelledError):
                    await command_task
            if client.is_connected():
                try:
                    await client.disconnect()
                except Exception:
                    pass


async def run():
    global http_client

    if not BACKEND_API_KEY:
        logger.error("HARPIA_API_KEY is not configured; the worker cannot reach the API.")

    http_client = httpx.AsyncClient(
        base_url=BACKEND_URL,
        headers={"X-API-Key": BACKEND_API_KEY},
        timeout=httpx.Timeout(10.0, connect=5.0),
    )

    background_tasks: list[asyncio.Task] = []
    try:
        await refresh_monitoring_config()
        background_tasks = [
            asyncio.create_task(heartbeat_loop()),
            asyncio.create_task(config_poll_loop()),
            asyncio.create_task(alert_sender_loop()),
        ]
        await telegram_loop()
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task
        await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(run())
