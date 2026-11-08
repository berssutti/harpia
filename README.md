# Harpia

Radar de threat intelligence auto-hospedado que monitora grupos do Telegram
configurados e persiste apenas mensagens que batem com a watchlist.

## Arquitetura

O Harpia roda com três aplicações e um arquivo SQLite:

- `harpia-web`: dashboard Nuxt na porta `3000`. O navegador fala apenas com o
  proxy same-origin em `/api`, que injeta a API key no servidor.
- `harpia-backend`: API FastAPI na porta `8000`. É a fonte de verdade das
  configurações, o único processo que escreve no SQLite e o distribuidor do SSE.
- `harpia-worker`: processo Telethon que mantém a conexão com o Telegram,
  consulta a configuração periodicamente e envia as ocorrências para a API.
- `SQLite`: banco em `harpia-backend/db/harpia.db`, montado como volume.

```text
Telegram <-> harpia-worker --HTTP--> harpia-backend <--> SQLite
                                          ^
                                          | /api (proxy + Basic auth)
                                       harpia-web
```

### Fluxo de ingestão

1. O worker busca um snapshot completo de `/internal/monitoring-config` a cada
   30 segundos. Uma resposta válida substitui a watchlist e os grupos em
   memória; em caso de falha, a última configuração válida é mantida.
2. Mensagens de grupos monitorados são comparadas com a watchlist
   (substring case-insensitive). Mensagens sem match são descartadas.
3. A primeira ocorrência encontrada em cada mensagem é enviada para
   `POST /internal/alerts`.
4. O backend valida, deduplica por `(telegram_group_id, telegram_message_id)` e
   persiste no SQLite antes de publicar o alerta no SSE.
5. O dashboard carrega `/feed/history` e recebe novos alertas por
   `/feed/stream`.

### Worker, heartbeat e autenticação

- O worker envia heartbeat a cada 15 segundos com estado, versão, tamanho da
  configuração e contador de mensagens analisadas.
- O backend acumula o contador entre reinícios do worker e considera o worker
  offline quando o último heartbeat tem mais de 90 segundos.
- Códigos e senhas 2FA são comandos transitórios mantidos somente em memória no
  backend, com validade de 10 minutos. O worker os consome por polling e eles
  nunca são gravados no banco ou nos logs.
- A sessão do Telethon fica em `harpia-worker/session/`.

## Subir a stack

1. Crie o arquivo de ambiente e troque todos os segredos:

   ```bash
   cp .env.example .env
   # gere valores fortes, por exemplo: openssl rand -hex 32
   ```

2. Suba os serviços:

   ```bash
   docker compose up -d --build
   ```

3. Abra `http://localhost:3000`. O navegador pedirá as credenciais definidas em
   `HARPIA_UI_USER` / `HARPIA_UI_PASSWORD`.

## Configurar o Telegram

Na tela de **Configurações** do Harpia é preciso informar o **API ID**, o
**API Hash** e o **telefone** da conta que o worker vai usar. Esses dados são
obtidos em <https://my.telegram.org>:

1. Acesse <https://my.telegram.org> e faça login com o número da conta que o
   Harpia vai usar (o código de confirmação chega no aplicativo do Telegram).
2. Abra **API development tools** e preencha os dados do aplicativo (nome,
   plataforma, descrição e URL).
3. Copie o **App api_id** e o **App api_hash** exibidos.
4. No Harpia, abra **Configurações**, preencha API ID, API Hash e o telefone no
   formato internacional (ex.: `+5511999999999`) e salve.
5. O worker vai solicitar o login: insira na própria tela de Configurações o
   código recebido no Telegram (e a senha de dois fatores, se houver).

Essas credenciais dão acesso à conta do Telegram; trate-as como segredo e não
compartilhe a sessão gerada em `harpia-worker/session/`.

## Dados e backup

O SQLite guarda watchlist, grupos monitorados, credenciais, alertas e o último
estado do worker. O banco usa WAL, então também podem existir os arquivos
`harpia.db-wal` e `harpia.db-shm`.

Para um backup consistente, pare o backend ou use a API de backup do SQLite:

```bash
docker compose exec harpia-backend python -c "import sqlite3; src=sqlite3.connect('/app/db/harpia.db'); dst=sqlite3.connect('/app/db/harpia-backup.db'); src.backup(dst); dst.close(); src.close()"
```

Depois copie `harpia-backend/db/harpia-backup.db`. Para restaurar, pare a stack,
substitua `harpia.db` pelo backup e suba novamente. A sessão do Telegram é um
segredo separado e deve ser protegida ou descartada (o próximo login pedirá um
novo código).

O schema é criado de forma idempotente na inicialização (`create_all`). Ainda
não há Alembic; alterações em tabelas existentes exigem uma estratégia de
migração antes de serem aplicadas. A pesquisa textual usa SQLite `LIKE`; FTS5
pode ser avaliado se o volume de alertas justificar.

## Operação

- Saúde/readiness pública: `curl http://localhost:8000/system/health`
- Status usado pela UI (requer `X-API-Key`): `GET /system/status`
- Estado do worker (requer `X-API-Key`): `GET /internal/worker/status`
- Logs: `docker compose logs -f harpia-worker`
- Parar: `docker compose down`

Endpoints do worker exigem `X-API-Key`: configuração, heartbeat, comandos e
ingestão de alertas. O proxy Nuxt bloqueia `/internal/*`; somente a API é
acessível pelo dashboard.

## Desenvolvimento e testes

Valide sempre em Docker:

```bash
docker compose run --rm --no-deps harpia-backend pytest -q
docker compose run --rm --no-deps harpia-worker pytest -q
docker compose build harpia-web
```

O build do frontend é o check de compilação disponível hoje. O teste Vitest do
dashboard continua sem harness configurado na imagem de runtime.
