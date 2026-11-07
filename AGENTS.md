# AGENTS.md

Harpia is a self-hosted Telegram threat-intelligence "radar". It monitors only configured groups and persists only messages that match a watchlist target (edge filtering); unmatched messages are discarded.

## Services and data flow (`docker-compose.yml`)

- `harpia-web` — Nuxt 4 dashboard on `:3000`. Source lives in `harpia-web/app/` (Nuxt 4 layout), not a root `pages/`. The browser talks only to the same-origin Nitro proxy under `/api` (`harpia-web/server/api/[...path].ts`), which injects the server-side API key; `runtimeConfig.public.apiBase` is `/api`.
- `harpia-backend` — FastAPI on `:8000`. CRUD for watchlist/groups/credentials, health, SSE feed, OpenSearch queries. SQLite is `harpia-backend/db/harpia.db`, created on startup and volume-mounted; there are no migrations.
- `harpia-worker` — Telethon ingestor. Loads watchlist/groups from the API once at startup, then stays in sync via Redis. Writes hits to OpenSearch index `hits`.
- `redis` (`:6379`) and `opensearch` (`:9200`).

Redis channels: `watchlist_updates` and `group_updates` (API → worker), `telegram_auth` (API → worker login), `new_alert` and `stats_updates` (worker → API → SSE). Worker status keys: `worker:telegram:status`, `worker:telegram:health`, `stats:analyzed_messages`.

## Commands

- Start/rebuild everything: `docker compose up --build`
- Start in background: `docker compose up -d`
- Rebuild one service after changes: `docker compose up -d --build harpia-backend` (or `harpia-worker`, `harpia-web`)
- One-off command without starting dependencies: `docker compose run --rm --no-deps harpia-backend <command>`
- Follow logs: `docker compose logs -f harpia-worker`
- Health checks: `curl http://localhost:8000/system/health` (readiness, public) and `/system/status` (UI status payload, requires `X-API-Key`).
- Frontend production build check (currently passes): `docker compose build harpia-web`
- Stop: `docker compose down`

The compose `harpia-web` service runs the built Nitro server, not `nuxt dev`; there is no live-reload service configured. Rebuild `harpia-web` to see frontend changes.

## Docker and environment rules

- Follow `.gemini/skills/harpia-dev-standards/`: do not install dependencies or run services on the host; validate changes in Docker.
- `.env` is required before `docker compose up`: `HARPIA_API_KEY`, `REDIS_PASSWORD`, `HARPIA_UI_USER`, `HARPIA_UI_PASSWORD` (see `.env.example`). Compose fails closed when a secret is missing.
- Inside containers, use compose service names: `http://harpia-backend:8000`, `redis://:PASSWORD@redis:6379/0`, `http://opensearch:9200`. `localhost` refers to the container itself.
- Redis and OpenSearch publish no host ports; they are reachable only on the compose network. Redis requires a password.
- Data/mutation endpoints on `harpia-backend` require `X-API-Key` (`/system/health` is the only public route). The dashboard reaches them through the Nuxt proxy, which is gated by HTTP Basic auth. There is no user database; the single UI credential lives in `.env`.
- Telegram login is interactive and UI-driven: save API ID/hash/phone in Settings; the worker publishes `waiting_for_code` or `waiting_for_password`, and the UI posts the code/password to `/telegram/auth-code`. The session lives in `harpia-worker/session/`.
- The worker Docker healthcheck only passes after Telegram auth (`worker:telegram:status == connected`); it stays unhealthy until then.
- The worker fetches the initial watchlist/groups only once at startup. If the backend was unavailable, it starts empty; restart the worker after the backend is ready.
- `.env`, `*.session`, and `harpia-backend/db/*.db` are gitignored. The Telegram session is no longer tracked in Git and `harpia-worker/.dockerignore` keeps it out of the image; treat the file on disk as a secret.

## Test harness status (verified)

Test files exist (`harpia-backend/test_*.py`, `harpia-worker/test_worker.py`, `harpia-web/app/app.spec.ts`), but the obvious container commands do not work today:

- Backend: `pytest` fails collection because tests use relative imports (`from .main`) with no package/`__init__.py`.
- Worker: the image does not install `pytest`, and `pytest-asyncio` is missing.
- Web: the runtime image contains only `.output` (no `package.json` or `node_modules`), and `vitest.config.ts` imports `@vitejs/plugin-vue`, which is not declared.

Fix the harness before relying on those commands. `docker compose build harpia-web` is a valid compile check.

## Behavior that is easy to assume incorrectly

- Python services use top-level imports (`import models`, `from database import Base`); run them from the service directory (`/app` in Docker), not as packages.
- Watchlist matching is case-insensitive substring matching on the raw text. Only the first matched target per message is indexed. There is no CPF normalization or regex matching.
- Group matching uses `MonitoredGroup.name` only (lowercased, `@` removed), compared against chat ID or username. `telegram_chat_id` is stored but ignored by the worker.
- Credentials are stored in plaintext in SQLite, but the public API returns a masked `api_hash` (`********`); only `/internal/credentials/{service}` returns the real value to the worker. A blank `api_hash` on update keeps the stored secret.
- The API is authenticated with `X-API-Key` and fails closed (503) when `HARPIA_API_KEY` is unset. CORS allows no origins unless `HARPIA_CORS_ORIGINS` lists them.
- OpenSearch index `hits` has no explicit mapping or setup; the first indexed document creates it. OpenSearch has no auth/TLS and relies on being reachable only inside the compose network.
- The feed renders message text as inert Vue text nodes (`highlightTarget()` returns `{text, match}` parts). Do not reintroduce `v-html`; message content is attacker-controlled.
- `docs/mvp/` describes the intended architecture; verify claims against code (for example, migrations and credential encryption are not implemented).

## Frontend conventions

- UI copy is Brazilian Portuguese. Use the "Minimalismo Tátil" design system: amber `#FFB800`, near-black surfaces, 0px border radius (2px only for small indicators), Space Grotesk + Inter, 4px spacing.
- Reuse global classes from `harpia-web/app/assets/css/main.css` (`card`, `btn`, `label-caps`, `data-mono`) instead of duplicating styles.
- Feed: initial `/feed/history`, then SSE `/feed/stream`. Settings polls `/system/status` every 10 seconds. All requests go through the same-origin `/api` proxy.

No CI, linter, formatter, typecheck, or migration tooling is configured.
