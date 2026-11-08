# Documento de Arquitetura de Software (HLD)
**Projeto:** Harpia
**Versão:** 2.0 (MVP - arquitetura simplificada)
**Padrão Arquitetural:** Edge Filtering com comunicação HTTP entre worker e API

## 1. Visão Geral do Sistema
O Harpia é uma ferramenta de Threat Intelligence *open-source* focada no monitoramento de ecossistemas cibercriminosos no Telegram. O sistema opera como um "Radar": aplica filtragem na borda (*Edge Filtering*) e persiste **apenas** mensagens que contenham alvos previamente cadastrados na *Watchlist* (e-mails, CPFs, domínios corporativos).

O MVP não depende de Redis nem de OpenSearch. A API é a fonte de verdade das configurações e a única responsável por escrever no SQLite; o worker se comunica com a API por HTTP.

## 2. Stack Tecnológico Principal

* **Linguagem Core:** Python 3.12
* **Frontend (Interface Web):** Nuxt.js (Vue.js)
* **Backend (API REST):** FastAPI (Python)
* **Ingestão de Dados (Worker):** Telethon (Python - Cliente Telegram)
* **Comunicação worker/API:** HTTP com timeouts, retentativas e heartbeat
* **Armazenamento:** SQLite (configurações, credenciais, alertas e estado do worker)
* **Infraestrutura:** Docker e Docker Compose

## 3. Topologia de Componentes

O sistema é dividido em três aplicações e um arquivo de banco:

1. **UI (`harpia-web`):** dashboard Nuxt.js servindo o painel de Radar (Watchlist + Feed de Alertas). O navegador usa apenas o proxy same-origin `/api`.
2. **API (`harpia-backend`):** FastAPI responsável pelo CRUD, snapshot de configuração do worker, heartbeat, comandos transitórios de autenticação, ingestão de alertas, consultas e SSE. É o único processo que acessa o SQLite.
3. **Worker (`harpia-worker`):** processo Python com Telethon, que mantém a conexão com o Telegram, atualiza a configuração em memória periodicamente e envia ocorrências e heartbeat para a API.
4. **Persistência (`harpia-backend/db/harpia.db`):** arquivo SQLite montado como volume, com WAL habilitado.

## 4. Fluxos de Dados e Execução

### Fluxo A: Ingestão e Filtragem na Borda (*Edge Filtering*)
1. O **Worker** recebe uma nova mensagem de um grupo monitorado do Telegram.
2. O **Worker** compara o texto com a *Watchlist* que mantém em memória.
3. Se nenhum alvo for encontrado, a mensagem é descartada imediatamente.
4. Se houver um *Match* (Hit), o Worker envia o payload para `POST /internal/alerts` na API.
5. A API valida, deduplica e persiste o alerta no SQLite **antes** de publicar o evento no SSE.
6. O envio é idempotente: a chave única `(telegram_group_id, telegram_message_id)` evita duplicatas quando o Worker repete uma requisição.

### Fluxo B: Atualização da Watchlist e dos Grupos
1. O usuário altera a Watchlist ou os grupos no painel; a UI chama a FastAPI.
2. A FastAPI persiste a alteração no SQLite.
3. O Worker consulta `GET /internal/monitoring-config` a cada 30 segundos e recebe um snapshot completo (apenas alvos ativos).
4. O Worker substitui a configuração em memória somente após uma resposta válida. Se a API estiver indisponível, mantém a última configuração e tenta novamente com backoff.
5. A alteração passa a valer sem reiniciar o container.

### Fluxo C: Consumo do Feed de Alertas (Real-Time Push)
1. A API mantém clientes SSE em um broker em memória (uma única instância do uvicorn).
2. Após o commit de um novo alerta, a API publica o payload no broker.
3. O dashboard recebe o evento em `/feed/stream` e atualiza o feed imediatamente.
4. O carregamento inicial usa `GET /feed/history`, com paginação e filtros por data, alvo, tipo, grupo e texto.
5. Heartbeats também publicam o contador acumulado de mensagens analisadas no mesmo SSE.

### Fluxo D: Estado, Estatísticas e Autenticação do Telegram
1. O Worker envia `POST /internal/worker/heartbeat` a cada 15 segundos com estado, versão, tamanho da configuração e contador local de mensagens analisadas.
2. A API persiste o último estado em `worker_state`, acumula o contador entre reinícios e considera o Worker offline após 90 segundos sem heartbeat.
3. Códigos de verificação e senhas 2FA são enviados pela UI para `/telegram/auth-code` e ficam somente em memória, com TTL de 10 minutos.
4. O Worker consome os comandos por `GET /internal/worker/commands`. O endpoint também transporta a solicitação de nova sessão.
5. Códigos e senhas temporários nunca são gravados no SQLite nem nos logs.

## 5. Modelagem de Dados

### 5.1. SQLite (Esquema Relacional)
* **Tabela `watchlist`:** `id` (PK), `target_type` (cpf, email, domain), `value`, `added_at`, `is_active`.
* **Tabela `monitored_groups`:** `id` (PK), `telegram_chat_id`, `name`.
* **Tabela `credentials`:** `id` (PK), `service`, `api_id`, `api_hash`, `phone`.
* **Tabela `alerts`:** `id` (UUID, PK), `target_value`, `target_type`, `telegram_group_id`, `telegram_group_name`, `telegram_message_id`, `message_text`, `timestamp`, `received_at`.
  * Índices por data, alvo, tipo e grupo.
  * Restrição única em `(telegram_group_id, telegram_message_id)` para idempotência.
* **Tabela `worker_state`:** linha única (`id = 1`) com status, versão, instância, último heartbeat, contadores e tamanho da configuração.

A pesquisa textual usa `LIKE` com filtros indexados nos campos mais seletivos. O SQLite FTS5 pode ser adicionado se o volume de alertas justificar; não é necessário para o MVP.

### 5.2. Retenção
O Harpia persiste exclusivamente mensagens que deram match na Watchlist. Mensagens sem match não são gravadas. Alertas históricos permanecem no SQLite mesmo se o alvo for removido da Watchlist.

## 6. Segurança e Operação
* Endpoints de dados e `/internal/*` exigem `X-API-Key`; `/system/health` é público.
* O proxy Nuxt injeta a API key no servidor e bloqueia `/internal/*`.
* Credenciais do Telegram ficam em texto plano no SQLite (limitação atual do MVP), mas o hash é mascarado nas respostas públicas.
* A sessão do Telethon é um segredo e fica em `harpia-worker/session/`.
* Healthcheck do backend valida o SQLite; o healthcheck do worker consulta `/internal/worker/status` e só passa após a autenticação no Telegram.
* Backup do SQLite deve considerar WAL ou usar a API de backup do próprio SQLite. Não há migrations (Alembic) implementadas neste MVP.
