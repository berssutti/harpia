### Requisitos Funcionais (RF)

| ID | Requisito |
| :--- | :--- |
| **RF01** | O sistema deve autenticar na API do Telegram utilizando credenciais fornecidas via interface web. |
| **RF02** | O sistema deve fornecer uma interface web (Nuxt.js) permitindo ao usuário criar, listar e deletar alvos (E-mails, CPFs, Domínios) em uma "Watchlist". |
| **RF03** | O backend (FastAPI) deve armazenar os itens da Watchlist em um banco de dados relacional leve (SQLite). |
| **RF04** | O sistema deve disponibilizar um snapshot periódico da Watchlist e dos grupos monitorados para o Worker, sem necessidade de reinicialização. |
| **RF05** | O Worker de ingestão deve atualizar sua lista de alvos em memória ao buscar o snapshot da API, mantendo a última configuração válida em caso de falha. |
| **RF06** | O Worker deve capturar mensagens do Telegram em tempo real e descartar imediatamente qualquer texto que não contenha pelo menos um dos alvos da Watchlist ativa (*Edge Filtering*). |
| **RF07** | Caso uma mensagem contenha um alvo monitorado (Hit), o Worker deve enviar o payload à API, que valida, deduplica e persiste os metadados (alvo atingido, grupo, data, texto) no SQLite. |
| **RF08** | A interface web deve exibir um "Feed de Alertas (Hits)", consultando os registros do SQLite ordenados cronologicamente (do mais recente para o mais antigo) e recebendo novas ocorrências por SSE. |
| **RF09** | O sistema deve permitir o gerenciamento (CRUD) via interface dos grupos/canais do Telegram que o Worker deve monitorar. |
| **RF10** | O sistema deve permitir cadastrar credenciais de API do Telegram via interface web. |
| **RF11** | O Worker deve informar seu estado periodicamente por heartbeat, e a API deve expor a conexão com o Telegram, a última atividade e as estatísticas operacionais. |
| **RF12** | A autenticação do Telegram deve aceitar código e senha 2FA por comando transitório, sem persistir esses valores. |

### Requisitos Não Funcionais (RNF)

| Categoria | ID | Requisito |
| :--- | :--- | :--- |
| **Arquitetura & Deploy** | **RNF01** | O sistema deve ser integralmente conteinerizado via Docker/Docker Compose, encapsulando os serviços: Worker (Telethon), API (FastAPI) e UI (Nuxt.js), com SQLite como persistência. |
| **Comunicação** | **RNF02** | A comunicação entre Worker e API deve ocorrer por HTTP, com timeouts, tentativas de reconexão e heartbeat; não deve depender de Redis ou OpenSearch. |
| **Eficiência / Armazenamento** | **RNF03** | O sistema deve otimizar o uso de disco e memória retendo no SQLite **exclusivamente** mensagens caracterizadas como *Hits* de alvos cadastrados, evitando o armazenamento massivo de tráfego irrelevante. |
| **Desempenho** | **RNF04** | O carregamento inicial da interface e do Feed de Alertas deve ocorrer em menos de 1 segundo, realizando consultas limitadas e paginadas na API do backend. |
| **Segurança** | **RNF05** | As credenciais de acesso às APIs de fontes e ferramentas de enriquecimento salvas no SQLite não devem estar em texto plano. *(Limitação conhecida: ainda não implementado no MVP.)* |
| **Resiliência** | **RNF06** | O Worker deve implementar mecanismos de reconexão e tratamento de limites de taxa (*Rate Limits*) do Telegram, garantindo que o processo em *background* não sofra falhas catastróficas. |
| **Idempotência** | **RNF07** | O envio de ocorrências deve ser idempotente; repetições após falha de comunicação não podem gerar alertas duplicados. |
| **Persistência** | **RNF08** | Configurações, grupos, indicadores, credenciais e ocorrências devem permanecer disponíveis após reinicializações dos containers. |
