# Documento de Arquitetura de Software (HLD)
**Projeto:** Harpia
**Versão:** 1.0 (MVP - Onda 1)
**Padrão Arquitetural:** Event-Driven (Orientada a Eventos) com Edge Filtering

## 1. Visão Geral do Sistema
O Harpia é uma ferramenta de Threat Intelligence *open-source* focada no monitoramento de ecossistemas cibercriminosos no Telegram. Diferente de plataformas de arquivamento em massa, o Harpia opera como um "Radar", utilizando uma arquitetura de filtragem na borda (*Edge Filtering*) para capturar, alertar e indexar **apenas** mensagens que contenham alvos previamente cadastrados na *Watchlist* do usuário (E-mails, CPFs, Domínios Corporativos).

## 2. Stack Tecnológico Principal
A seleção das tecnologias prioriza facilidade de auto-hospedagem (*self-hosting*), alta performance de processamento de texto e um ecossistema sólido.

* **Linguagem Core:** Python 3.12
* **Frontend (Interface Web):** Nuxt.js (Vue.js)
* **Backend (API Rest):** FastAPI (Python)
* **Ingestão de Dados (Worker):** Telethon (Python - Cliente Telegram)
* **Mensageria e Sincronização:** Redis
* **Armazenamento de Configurações:** SQLite
* **Armazenamento de Alertas (Hits):** OpenSearch
* **Infraestrutura:** Docker e Docker Compose

## 3. Topologia de Componentes

O sistema é dividido em quatro containers principais e isolados, orquestrados via rede interna do Docker:

1.  **UI Component (`harpia-web`):** Aplicação frontend em Nuxt.js servindo o painel de Radar (Watchlist + Feed de Alertas).
2.  **API Server (`harpia-api`):** Servidor FastAPI responsável pelo CRUD da Watchlist no SQLite e pelas queries no OpenSearch para popular o frontend.
3.  **Worker de Ingestão (`harpia-worker`):** Processo Python em *background* rodando o Telethon. Mantém conexão WebSockets com o Telegram e escuta o Redis para atualizações.
4.  **Camada de Dados (`opensearch-node` e `redis-cache`):** Instâncias de banco de dados rodando nativamente para persistência e mensageria.

## 4. Fluxos de Dados e Execução

A arquitetura resolve dois grandes desafios de forma assíncrona: a captura massiva de dados e a atualização de configurações em tempo real.

### Fluxo A: Ingestão e Filtragem na Borda (*Edge Filtering*)
1.  O **Worker** recebe uma nova mensagem de um grupo monitorado do Telegram.
2.  O **Worker** compara a mensagem crua com os alvos que estão na sua memória RAM (a *Watchlist* atual).
3.  Se nenhum alvo for encontrado, a mensagem é **descartada** da memória imediatamente.
4.  Se houver um *Match* (Hit), o Worker enriquece o payload com metadados (Data, Grupo, Alvo Atingido) e envia o documento diretamente para o **OpenSearch**.

### Fluxo B: Atualização da Watchlist em Tempo Real (*Pub/Sub*)
Para garantir que o Worker comece a monitorar um novo alvo no mesmo segundo em que o usuário o cadastra, sem precisar reiniciar o container:
1.  O usuário adiciona `ceo@empresa.com.br` no painel (Nuxt.js).
2.  A UI faz um POST para a **FastAPI**.
3.  A **FastAPI** salva o registro no **SQLite** para persistência física.
4.  No mesmo instante, a **FastAPI** atua como *Publisher* e publica uma mensagem no canal `watchlist_updates` do **Redis** (ex: `{"action": "add", "value": "ceo@empresa.com.br"}`).
5.  O **Worker** (que atua como *Subscriber* nesse canal) recebe a mensagem e insere o novo e-mail na sua lista em memória RAM. A próxima mensagem do Telegram já será testada contra esse novo alvo.

### Fluxo C: Consumo do Feed de Alertas (Real-Time Push)
Para garantir que o painel funcione como um verdadeiro "Radar" em tempo real, o *polling* tradicional é substituído por um fluxo reativo:
1.  Quando o **Worker** encontra um alvo e salva o documento no **OpenSearch**, ele também publica um evento de notificação em um canal do **Redis** (ex: `new_alert`).
2.  A **FastAPI** mantém uma conexão persistente (via WebSockets ou Server-Sent Events - SSE) com a UI (Nuxt.js) e atua como *Subscriber* desse canal no Redis.
3.  Assim que a **FastAPI** recebe o sinal do Redis, ela faz o *Push* automático do novo alerta para a interface.
4.  A UI (Nuxt.js) atualiza o feed instantaneamente sem precisar fazer requisições periódicas. *(Nota: O GET HTTP tradicional no OpenSearch é feito apenas no primeiro carregamento da página para trazer o histórico dos últimos 50 alertas).*

## 5. Modelagem de Dados

### 5.1. SQLite (Esquema Relacional)
Focado no estado da aplicação e configurações da ferramenta.
* **Tabela `Watchlist`:** `id` (PK), `type` (enum: cpf, email, domain), `value` (string), `added_at` (timestamp), `is_active` (boolean).
* **Tabela `Monitored_Groups`:** `id` (PK), `telegram_chat_id` (string), `name` (string).
* **Tabela `Credentials`:** `id` (PK), `service` (string), `api_key` (hash/ofuscada).

### 5.2. OpenSearch (Esquema NoSQL / Índices)
Focado no armazenamento de longo prazo e busca de texto dos eventos de detecção (Hits).
* **Índice `hits`:** Armazena os documentos gerados quando um alvo da Watchlist é encontrado em uma mensagem.
    * **Campos Principais:** `id` (UUID), `target_value` (string - o alvo atingido), `target_type` (string - cpf, email, domain), `telegram_group_id` (string), `telegram_group_name` (string), `message_text` (text - conteúdo bruto da mensagem), `timestamp` (date - data e hora da captura).

### 5.3. Redis (Pub/Sub e Mensageria)
Focado na comunicação assíncrona entre os serviços e orquestração em tempo real.
* **Canal `watchlist_updates`:** Utilizado pela API para notificar o Worker instantaneamente sobre adições ou remoções de alvos, permitindo atualização da Watchlist em memória (RAM) sem reinício do container.
* **Canal `new_alert`:** Utilizado pelo Worker para notificar a API (que repassa à UI via WebSocket/SSE) de que um novo Hit foi indexado no OpenSearch, atualizando o Feed de Alertas do usuário em tempo real.

