### Lean Inception

#### A Visão do Produto (Elevator Pitch)
* **Para:** Analistas de SOC, pesquisadores de segurança e times de Threat Intel.
* **Cujo:** Precisam monitorar ecossistemas de cibercrime (grupos de Telegram) em busca de vazamentos focados nos ativos corporativos da sua empresa (e-mails, domínios, CPFs).
* **O Harpia:** É uma plataforma de *Threat Intelligence* direcional e *open source*.
* **Que:** Realiza a ingestão contínua de mensagens, aplicando um filtro em tempo real (Edge Filtering) para capturar e alertar **apenas** quando os alvos cadastrados na ferramenta são mencionados pelos criminosos.
* **Diferente de:** Soluções genéricas que armazenam gigabytes de "lixo" cibercriminoso e exigem buscas manuais exaustivas.
* **Nosso produto:** Foca na redução de ruído, armazenando apenas os "Hits" (alertas confirmados) e fornecendo um painel minimalista de resposta rápida, economizando tempo cognitivo e recursos de infraestrutura.

#### A Matriz É / Não É / Faz / Não Faz
* **É:** Open source, orientado a eventos (Event-Driven), focado em monitoramento de alvos (Watchlist), conteinerizado (Docker).
* **Não É:** Um motor de busca global de todo o cibercrime brasileiro, um bot de interação no Telegram, uma ferramenta de *takedown*.
* **Faz:** Mantém uma Watchlist em memória para filtragem ultra-rápida, persiste apenas os alertas positivos (Hits) no SQLite e sincroniza a lista de alvos por polling HTTP periódico.
* **Não Faz (No MVP):** Não armazena mensagens que não dão *match* com a Watchlist, **não envia notificações (Webhook, Slack, E-mail)**.

#### Personas
* **O Analista de Defesa (SOC):** Quer proteção passiva. Seu fluxo de trabalho é abrir o Harpia, cadastrar os e-mails dos diretores e o domínio da empresa na Watchlist, e deixar a aba de "Alertas (Hits)" aberta para ver se o sistema captura algo durante seu turno.
