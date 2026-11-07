# Harpia

Radar de threat intelligence auto-hospedado que monitora grupos do Telegram
configurados e persiste apenas mensagens que batem com a watchlist.

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
