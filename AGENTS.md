# AGENTS.md

Harpia is a self-hosted Telegram threat-intelligence "radar". It monitors only configured groups and persists only messages that match a watchlist target (edge filtering); unmatched messages are discarded.

## Services and data flow (`docker-compose.yml`)

- `harpia-web` — Nuxt 4 dashboard on `:3000`. Source lives in `harpia-web/app/` (Nuxt 4 layout), not a root `pages/`. The browser talks only to the same-origin Nitro proxy under `/api` (`harpia-web/server/api/[...path].ts`), which injects the server-side API key; `runtimeConfig.public.apiBase` is `/api`.
- `harpia-backend` — FastAPI on `:8000`. CRUD for watchlist/groups/credentials, internal worker endpoints, health, SQLite queries and the SSE feed. SQLite is `harpia-backend/db/harpia.db`, created on startup and volume-mounted; there are no migrations.
- `harpia-worker` — Telethon ingestor. Polls the API for a full monitoring snapshot, sends hits and heartbeats over HTTP, and polls transient UI commands. It never opens SQLite.

There is no Redis or OpenSearch. The worker/backend contract is HTTP only:

- `GET /internal/monitoring-config` — full watchlist/groups snapshot (worker polls every 30s).
- `POST /internal/worker/heartbeat` — worker state and analyzed-message counter (every 15s).
- `GET /internal/worker/commands` — consumes transient auth/reset commands (polled every 2s).
- `POST /internal/alerts` — idempotent hit ingestion.
- `GET /system/status`, `GET /internal/worker/status`, `GET /feed/history`, `GET /feed/stream` — dashboard/health views.
- `/internal/*` requires `X-API-Key` and is deliberately blocked by the Nuxt proxy.

Alerts are persisted in SQLite with a unique `(telegram_group_id, telegram_message_id)` key, so a worker retry is safe. The backend publishes to the in-process SSE broker only after commit. Uvicorn runs one process in Compose; a multi-process deployment would need a shared broker.

Worker state is a single `worker_state` row (`id == 1`). The backend accumulates `analyzed_messages` across worker process restarts using the `instance_id` plus the worker-local counter. A heartbeat older than `WORKER_STALE_AFTER_SECONDS` (default 90) is reported as offline.

Telegram auth codes and 2FA passwords are never persisted. They are queued in backend memory, expire after `TELEGRAM_COMMAND_TTL_SECONDS` (default 600), and are consumed by the worker's command polling. Do not add logging that prints their values.

## Commands

- Start/rebuild everything: `docker compose up --build`
- Start in background: `docker compose up -d --build`
- Rebuild one service after changes: `docker compose up -d --build harpia-backend` (or `harpia-worker`, `harpia-web`)
- One-off command without starting dependencies: `docker compose run --rm --no-deps harpia-backend <command>`
- Backend tests (currently pass): `docker compose run --rm --no-deps harpia-backend pytest -q`
- Worker tests (currently pass): `docker compose run --rm --no-deps harpia-worker pytest -q`
- Follow logs: `docker compose logs -f harpia-worker`
- Health checks: `curl http://localhost:8000/system/health` (readiness, public) and `/system/status` (UI status payload, requires `X-API-Key`).
- Frontend production build check (currently passes): `docker compose build harpia-web`
- Stop: `docker compose down`

The compose `harpia-web` service runs the built Nitro server, not `nuxt dev`; there is no live-reload service configured. Rebuild `harpia-web` to see frontend changes.

## Docker and environment rules

- Follow `.gemini/skills/harpia-dev-standards/`: do not install dependencies or run services on the host; validate changes in Docker.
- `.env` is required before `docker compose up`: `HARPIA_API_KEY`, `HARPIA_UI_USER`, `HARPIA_UI_PASSWORD` (see `.env.example`). Compose fails closed when a secret is missing. Redis is gone, so `REDIS_PASSWORD` is no longer used.
- Inside containers, use the compose service name `http://harpia-backend:8000`. `localhost` refers to the container itself.
- Data/mutation endpoints on `harpia-backend` require `X-API-Key` (`/system/health` is the only public route). The dashboard reaches them through the Nuxt proxy, which is gated by HTTP Basic auth. There is no user database; the single UI credential lives in `.env`.
- Telegram login is interactive and UI-driven: save API ID/hash/phone in Settings; the worker reports `waiting_for_code` or `waiting_for_password`, and the UI posts the code/password to `/telegram/auth-code`. The worker consumes it via `/internal/worker/commands`. The session lives in `harpia-worker/session/`.
- The worker Docker healthcheck only passes after Telegram auth (`/internal/worker/status` reports `connected: true`); it stays unhealthy until then.
- If the backend is unavailable at worker startup, the worker starts with an empty snapshot and keeps retrying. Configuration is refreshed automatically when the API returns; a restart is not required.
- `.env`, `*.session`, and `harpia-backend/db/*.db` are gitignored. `harpia-worker/.dockerignore` keeps sessions out of the image; treat the file on disk as a secret.
- SQLite enables WAL, `busy_timeout`, and foreign keys. A backup must account for `harpia.db`, `harpia.db-wal`, and `harpia.db-shm`; use the backup API or stop the backend. See README.

## Test harness status (verified)

- Backend: 14 tests pass with the command above. Tests replace the API's DB dependency with an in-memory SQLite database and set their own `HARPIA_API_KEY` before import.
- Worker: 3 tests pass with the command above. They cover configuration snapshot replacement and analyzed-message deduplication.
- Web: `docker compose build harpia-web` is the valid compile check. The runtime image contains only `.output` (no `package.json` or `node_modules`), and `vitest.config.ts` imports `@vitejs/plugin-vue`, which is not declared, so the Vitest suite still has no working harness.

Test files are included in backend/worker images so `docker compose run` can execute them; `.dockerignore` still excludes databases and Telegram sessions.

## Behavior that is easy to assume incorrectly

- Python services use top-level imports (`import models`, `from database import Base`); run them from the service directory (`/app` in Docker), not as packages.
- The worker does not write to SQLite and the frontend never talks to SQLite. All persistence goes through the backend.
- Watchlist matching is case-insensitive substring matching on the raw text. Only the first matched target per message is persisted. There is no CPF normalization or regex matching.
- Group matching uses `MonitoredGroup.name` only (lowercased, `@` removed), compared against chat ID or username. `telegram_chat_id` is stored but ignored by the worker.
- Only active watchlist rows (`is_active == true`) are included in the worker snapshot. The UI has no deactivate action today, so all rows are normally active.
- Credentials are stored in plaintext in SQLite, but the public API returns a masked `api_hash` (`********`); only `/internal/credentials/{service}` returns the real value to the worker. A blank `api_hash` on update keeps the stored secret.
- The API is authenticated with `X-API-Key` and fails closed (503) when `HARPIA_API_KEY` is unset. CORS allows no origins unless `HARPIA_CORS_ORIGINS` lists them.
- Alert ingestion returns `201` for a new alert and `200` with `status: "duplicate"` for a retry. The alert is committed before the SSE event fires.
- `feed/history` filters server-side with `q`, `target`, `target_type`, `group`, `start`, `end`, `limit`, and `skip`. Text search is SQLite `LIKE`; FTS5 has not been added.
- A worker heartbeat is fresh for 90 seconds. The compose healthcheck intentionally fails until Telegram auth succeeds, so an unhealthy worker container can still be running normally during first-time login.
- The feed renders message text as inert Vue text nodes (`highlightTarget()` returns `{text, match}` parts). Do not reintroduce `v-html`; message content is attacker-controlled.
- `docs/mvp/` describes the current architecture after the Redis/OpenSearch removal. Migrations and credential encryption are still not implemented.

## Frontend conventions

- UI copy is Brazilian Portuguese. Use the "Minimalismo Tátil" design system: amber `#FFB800`, near-black surfaces, 0px border radius (2px only for small indicators), Space Grotesk + Inter, 4px spacing.
- Reuse global classes from `harpia-web/app/assets/css/main.css` (`card`, `btn`, `label-caps`, `data-mono`) instead of duplicating styles.
- Feed: initial `/feed/history`, then SSE `/feed/stream`. Settings polls `/system/status` every 10 seconds. All requests go through the same-origin `/api` proxy.
- The Settings status list shows Telegram, the worker heartbeat, and SQLite. There are no Redis/OpenSearch indicators anymore.

No CI, linter, formatter, typecheck, or migration tooling is configured.
