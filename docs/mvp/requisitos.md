### Requisitos Funcionais (RF)

| ID | Requisito |
| :--- | :--- |
| **RF01** | O sistema deve autenticar na API do Telegram utilizando credenciais fornecidas via interface web. |
| **RF02** | O sistema deve fornecer uma interface web (Nuxt.js) permitindo ao usuário criar, listar e deletar alvos (E-mails, CPFs, Domínios) em uma "Watchlist". |
| **RF03** | O backend (FastAPI) deve armazenar os itens da Watchlist em um banco de dados relacional leve (SQLite). |
| **RF04** | O sistema deve disparar um evento interno (via Redis Pub/Sub) instantaneamente sempre que um novo alvo for adicionado ou removido da Watchlist na interface. |
| **RF05** | O Worker de ingestão deve atualizar sua lista de alvos em memória em tempo real ao receber o evento do Redis (RF04), sem necessidade de reinicialização. |
| **RF06** | O Worker deve capturar mensagens do Telegram em tempo real e descartar imediatamente qualquer texto que não contenha pelo menos um dos alvos da Watchlist ativa (*Edge Filtering*). |
| **RF07** | Caso uma mensagem contenha um alvo monitorado (Hit), o sistema deve enfileirar o payload e indexar os metadados (alvo atingido, grupo, data, texto) em um índice do OpenSearch. |
| **RF08** | A interface web deve exibir um "Feed de Alertas (Hits)", consumindo os registros do OpenSearch ordenados cronologicamente (do mais recente para o mais antigo). |
| **RF09** | O sistema deve permitir o gerenciamento (CRUD) via interface dos grupos/canais do Telegram que o Worker deve monitorar. |
| **RF10** | O sistema deve permitir cadastrar credenciais de API do Telegram via interface web e armazenar de forma segura. |

### Requisitos Não Funcionais (RNF)

| Categoria | ID | Requisito |
| :--- | :--- | :--- |
| **Arquitetura & Deploy** | **RNF01** | O sistema deve ser integralmente conteinerizado via Docker/Docker Compose, encapsulando os serviços: Worker (Telethon), API (FastAPI), UI (Nuxt.js), Redis e OpenSearch. |
| **Mensageria & Estado** | **RNF02** | O Redis deve ser utilizado com dupla responsabilidade: atuar como canal *Pub/Sub* (para atualização instantânea da Watchlist no Worker) e como *Buffer* de mensagens (para absorver picos de tráfego do Telegram). |
| **Eficiência / Armazenamento** | **RNF03** | O sistema deve otimizar o uso de disco e memória retendo no OpenSearch **exclusivamente** mensagens caracterizadas como *Hits* de alvos cadastrados, evitando o armazenamento massivo de tráfego irrelevante. |
| **Desempenho** | **RNF04** | O carregamento inicial da interface e do Feed de Alertas deve ocorrer em menos de 1 segundo, realizando consultas limitadas e paginadas na API do backend. |
| **Segurança** | **RNF05** | As credenciais de acesso às APIs de fontes e ferramentas de enriquecimento salvas no SQLite não devem estar em texto plano. |
| **Resiliência** | **RNF06** | O Worker deve implementar mecanismos de reconexão e tratamento de limites de taxa (*Rate Limits*) do Telegram, garantindo que o processo em *background* não sofra falhas catastróficas. |
