<template>
  <div class="settings">
    <header class="page-header">
      <h1 class="page-title">Configurações</h1>
      <p class="page-subtitle text-muted">Gerencie a conexão do Harpia com o Telegram e acompanhe a saúde dos serviços.</p>
    </header>

    <div class="settings-grid">
      <!-- Telegram Auth Banner (shown when the modal is dismissed) -->
      <div class="card settings-section full-width auth-banner" v-if="authMode">
        <div class="auth-banner-body">
          <div class="auth-banner-copy">
            <span class="auth-banner-icon" aria-hidden="true">!</span>
            <div>
              <h2 class="label-caps auth-banner-title">Ação necessária: autenticação do Telegram</h2>
              <p class="text-muted auth-banner-text" aria-live="polite">{{ authDescription }}</p>
            </div>
          </div>
          <button type="button" class="btn btn-primary" @click="openAuthModal">
            Informar {{ authMode === 'code' ? 'Código' : 'Senha' }}
          </button>
        </div>
      </div>

      <!-- System Status Section -->
      <div class="card settings-section status-card">
        <div class="section-header">
          <div>
            <h2 class="label-caps section-title">Status do Sistema</h2>
            <p class="section-subtitle text-muted">Serviços conectados e saúde do monitoramento.</p>
          </div>
          <span v-if="systemStatus" class="auto-refresh data-mono">Atualiza a cada 10 segundos</span>
        </div>

        <div class="status-list" v-if="systemStatus" aria-live="polite">
          <div class="status-item" v-for="service in serviceStatuses" :key="service.key">
            <div class="status-info">
              <h4 class="label-caps">{{ service.label }}</h4>
              <span class="status-desc data-mono text-muted">{{ service.detail }}</span>
            </div>
            <span class="status-pill" :class="service.online ? 'is-online' : 'is-offline'">
              <span class="dot"></span>
              <span class="label-caps">{{ service.online ? service.onlineLabel : service.offlineLabel }}</span>
            </span>
          </div>
        </div>

        <div v-else-if="statusError" class="status-error" role="alert">
          <p class="text-muted">Não foi possível carregar o status dos serviços.</p>
          <button type="button" class="btn btn-secondary btn-sm" @click="loadSystemStatus">Tentar novamente</button>
        </div>

        <div v-else class="status-loading" aria-hidden="true">
          <div class="skeleton-row" v-for="n in 3" :key="n"></div>
        </div>

        <p v-if="systemStatus && statusError" class="stale-warning data-mono" role="status">
          Falha ao atualizar; exibindo os últimos dados conhecidos.
        </p>

        <div class="session-actions" v-if="systemStatus && systemStatus.telegram.status === 'online'">
          <div class="session-info">
            <h4 class="label-caps">Sessão do Telegram</h4>
            <span class="status-desc data-mono text-muted">Encerra esta sessão e solicita um novo código de acesso.</span>
          </div>
          <button type="button" class="btn btn-secondary" :disabled="sessionResetting" @click="showResetModal = true">
            {{ sessionResetting ? 'Encerrando...' : 'Iniciar nova sessão' }}
          </button>
        </div>
      </div>

      <!-- Telegram API Credentials -->
      <div class="card settings-section credentials-card">
        <div class="section-header">
          <div>
            <h2 class="label-caps section-title">Credenciais da API do Telegram</h2>
            <p class="section-subtitle text-muted">Configure o App ID e Hash para permitir que o Worker se conecte ao Telegram.</p>
          </div>
        </div>

        <form class="credentials-form" @submit.prevent="saveCredentials">
          <div class="form-grid">
            <div class="form-group">
              <label class="form-label" for="api-id">
                API ID <span class="label-hint">obrigatório</span>
              </label>
              <input
                id="api-id"
                type="text"
                v-model="credentials.apiId"
                class="form-input"
                placeholder="ex: 1234567"
                inputmode="numeric"
                autocomplete="off"
                required
              />
            </div>
            <div class="form-group">
              <label class="form-label" for="api-hash">
                API Hash <span class="label-hint">{{ hasApiHash ? 'já configurado' : 'obrigatório' }}</span>
              </label>
              <input
                id="api-hash"
                type="password"
                v-model="credentials.apiHash"
                class="form-input"
                :placeholder="hasApiHash ? 'Deixe em branco para manter o hash atual' : '••••••••••••••••'"
                autocomplete="new-password"
              />
              <p class="field-hint">
                {{ hasApiHash ? 'Preencha apenas se quiser substituir o hash salvo.' : 'Informe o hash gerado em my.telegram.org.' }}
              </p>
            </div>
            <div class="form-group full-span">
              <label class="form-label" for="telegram-phone">
                Número de Telefone <span class="label-hint">obrigatório</span>
              </label>
              <input
                id="telegram-phone"
                type="tel"
                v-model="credentials.phone"
                class="form-input data-mono"
                placeholder="+55 11 99999-9999"
                autocomplete="tel"
                required
              />
              <p class="field-hint">Usado pelo Worker para autenticar a sessão no Telegram.</p>
            </div>
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary" :disabled="savingCredentials">
              {{ savingCredentials ? 'Salvando...' : 'Salvar Credenciais' }}
            </button>
            <span class="form-message success" v-if="showSaved" role="status">OK // SALVO ✓</span>
            <span class="form-message error" v-if="credentialsError" role="alert">{{ credentialsError }}</span>
          </div>
        </form>
      </div>
    </div>

    <!-- Reset Telegram Session Confirmation Modal -->
    <div v-if="showResetModal" class="modal-overlay" @click.self="closeResetModal">
      <div class="modal-content reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-modal-title">
        <button type="button" class="modal-close" aria-label="Fechar" @click="closeResetModal">×</button>
        <h3 id="reset-modal-title" class="modal-title label-caps">Iniciar nova sessão?</h3>
        <p class="text-muted reset-modal-description">
          A sessão atual do Harpia será encerrada no Telegram. O monitoramento ficará pausado até você inserir o
          novo código de acesso (e a senha 2FA, se necessário). As demais sessões da sua conta não serão afetadas.
        </p>

        <p v-if="resetError" class="auth-error data-mono">{{ resetError }}</p>

        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" @click="closeResetModal">Cancelar</button>
          <button type="button" class="btn btn-danger" :disabled="sessionResetting" @click="requestNewSession">
            {{ sessionResetting ? 'Encerrando...' : 'Encerrar sessão' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Telegram Auth Modal -->
    <div v-if="authMode && showAuthModal" class="modal-overlay" @click.self="closeAuthModal">
      <div class="modal-content auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
        <button type="button" class="modal-close" aria-label="Fechar" @click="closeAuthModal">×</button>
        <h3 id="auth-modal-title" class="modal-title label-caps">Autenticação do Telegram</h3>
        <p class="text-muted auth-modal-description">{{ authDescription }}</p>

        <form @submit.prevent="submitAuthCode">
          <div class="form-group">
            <label class="form-label" for="auth-input">{{ authMode === 'code' ? 'Código de verificação' : 'Senha do Telegram' }}</label>
            <input
              id="auth-input"
              ref="authInputEl"
              v-model="authInput"
              :type="authMode === 'password' ? 'password' : 'text'"
              class="form-input data-mono"
              :placeholder="authMode === 'code' ? 'Código de 5 dígitos' : 'Senha do Telegram'"
              :inputmode="authMode === 'code' ? 'numeric' : undefined"
              :autocomplete="authMode === 'code' ? 'one-time-code' : 'current-password'"
              required
            />
          </div>

          <p v-if="authError" class="auth-error data-mono">{{ authError }}</p>

          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" @click="closeAuthModal">Cancelar</button>
            <button type="submit" class="btn btn-primary" :disabled="authSubmitting">
              {{ authSubmitting ? 'Enviando...' : 'Autenticar' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'

const config = useRuntimeConfig()

const systemStatus = ref(null)
const authInput = ref('')
const authError = ref('')
const authSubmitting = ref(false)
const showAuthModal = ref(false)
const authInputEl = ref(null)
const showResetModal = ref(false)
const sessionResetting = ref(false)
const resetError = ref('')
const hasApiHash = ref(false)
const statusError = ref(false)
const savingCredentials = ref(false)
const credentialsError = ref('')

const credentials = ref({
  apiId: '',
  apiHash: '',
  phone: ''
})

const showSaved = ref(false)
let statusInterval = null
let savedTimeout = null

const authMode = computed(() => {
  const status = systemStatus.value?.telegram?.status
  if (status === 'waiting_for_code') return 'code'
  if (status === 'waiting_for_password') return 'password'
  return null
})

const authDescription = computed(() =>
  authMode.value === 'password'
    ? 'Sua conta possui Verificação em Duas Etapas (2FA). Insira a senha da sua conta do Telegram.'
    : 'O Harpia precisa ser autenticado. Insira o código de 5 dígitos enviado para o seu aplicativo do Telegram.'
)

const serviceStatuses = computed(() => {
  const status = systemStatus.value
  if (!status) return []

  return [
    {
      key: 'telegram',
      label: 'Conexão Telegram',
      detail: status.telegram?.detail || 'Sem detalhes',
      online: status.telegram?.status === 'online',
      onlineLabel: 'Conectado',
      offlineLabel: 'Desconectado'
    },
    {
      key: 'opensearch',
      label: 'OpenSearch',
      detail: status.opensearch?.detail || 'Sem detalhes',
      online: status.opensearch?.status === 'online',
      onlineLabel: 'Online',
      offlineLabel: 'Offline'
    },
    {
      key: 'redis',
      label: 'Redis Pub/Sub',
      detail: status.redis?.detail || 'Sem detalhes',
      online: status.redis?.status === 'online',
      onlineLabel: 'Online',
      offlineLabel: 'Offline'
    }
  ]
})

const openAuthModal = async () => {
  authError.value = ''
  showAuthModal.value = true
  await nextTick()
  authInputEl.value?.focus()
}

const closeAuthModal = () => {
  showAuthModal.value = false
  authError.value = ''
}

const closeResetModal = () => {
  if (sessionResetting.value) return
  showResetModal.value = false
  resetError.value = ''
}

const waitForAuthPrompt = async () => {
  // The worker needs a moment to log out and request a new code.
  for (let attempt = 0; attempt < 10; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
    await loadSystemStatus()
    if (authMode.value) return
  }
}

const requestNewSession = async () => {
  if (sessionResetting.value) return

  sessionResetting.value = true
  resetError.value = ''

  try {
    await $fetch(`${config.public.apiBase}/telegram/new-session`, { method: 'POST' })
    showResetModal.value = false
    await loadSystemStatus()
    await waitForAuthPrompt()
  } catch (e) {
    console.error('Failed to start a new Telegram session', e)
    resetError.value = e?.data?.detail || 'Não foi possível iniciar uma nova sessão. Tente novamente.'
  } finally {
    sessionResetting.value = false
  }
}

const handleKeydown = (event) => {
  if (event.key !== 'Escape') return
  if (showResetModal.value) {
    closeResetModal()
  } else if (showAuthModal.value) {
    closeAuthModal()
  }
}

// Open the modal automatically when the worker starts waiting for credentials,
// and close it once authentication finishes.
watch(authMode, (mode) => {
  if (mode) {
    showResetModal.value = false
    openAuthModal()
  } else {
    showAuthModal.value = false
    authInput.value = ''
    authError.value = ''
  }
})

onMounted(async () => {
  await loadCredentials()
  await loadSystemStatus()

  // Refresh system status every 10 seconds
  statusInterval = setInterval(loadSystemStatus, 10000)
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  if (statusInterval) clearInterval(statusInterval)
  if (savedTimeout) clearTimeout(savedTimeout)
  window.removeEventListener('keydown', handleKeydown)
})

const submitAuthCode = async () => {
  if (!authInput.value || !authMode.value) return

  authSubmitting.value = true
  authError.value = ''

  const payload = authMode.value === 'code'
    ? { code: authInput.value }
    : { password: authInput.value }

  try {
    await $fetch(`${config.public.apiBase}/telegram/auth-code`, {
      method: 'POST',
      body: payload
    })
    authInput.value = ''
    setTimeout(loadSystemStatus, 1000)
  } catch (e) {
    console.error('Failed to submit auth info', e)
    authError.value = 'Não foi possível enviar o código/senha. Verifique e tente novamente.'
  } finally {
    authSubmitting.value = false
  }
}

const loadSystemStatus = async () => {
  try {
    systemStatus.value = await $fetch(`${config.public.apiBase}/system/status`)
    statusError.value = false
  } catch (e) {
    console.error('Failed to load system status', e)
    statusError.value = true
  }
}



const loadCredentials = async () => {
  try {
    const data = await $fetch(`${config.public.apiBase}/credentials/telegram`)
    if (data) {
      credentials.value.apiId = data.api_id || ''
      // The API only returns a masked hash; never prefill the secret field.
      credentials.value.apiHash = ''
      credentials.value.phone = data.phone || ''
      hasApiHash.value = Boolean(data.api_hash)
    }
  } catch (e) {
    if (e.status !== 404) {
      console.error('Failed to load credentials', e)
    }
  }
}



const saveCredentials = async () => {
  if (savingCredentials.value) return

  const apiId = credentials.value.apiId.trim()
  const apiHash = credentials.value.apiHash.trim()
  const phone = credentials.value.phone.trim()

  if (!apiId) {
    credentialsError.value = 'Informe o API ID antes de salvar.'
    return
  }

  if (!hasApiHash.value && !apiHash) {
    credentialsError.value = 'Informe o API Hash antes de salvar.'
    return
  }

  if (!phone) {
    credentialsError.value = 'Informe o número de telefone antes de salvar.'
    return
  }

  savingCredentials.value = true
  credentialsError.value = ''
  showSaved.value = false

  try {
    const body = {
      service: 'telegram',
      api_id: apiId,
      phone
    }
    if (apiHash) {
      body.api_hash = apiHash
    }

    await $fetch(`${config.public.apiBase}/credentials/`, {
      method: 'POST',
      body
    })

    credentials.value.apiHash = ''
    hasApiHash.value = true
    showSaved.value = true
    if (savedTimeout) clearTimeout(savedTimeout)
    savedTimeout = setTimeout(() => {
      showSaved.value = false
    }, 3000)
  } catch (e) {
    console.error('Failed to save credentials', e)
    credentialsError.value = e?.data?.detail || 'Não foi possível salvar as credenciais. Tente novamente.'
  } finally {
    savingCredentials.value = false
  }
}
</script>

<style scoped>
.settings {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.btn {
  font-size: var(--fs-control);
}

.page-header {
  margin-bottom: 24px;
}

.page-header .page-title {
  margin-bottom: 8px;
}

.page-subtitle {
  max-width: 72ch;
  margin: 0;
  font-size: 17px;
  line-height: 1.5;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  gap: 24px;
}

.settings-grid > .settings-section {
  margin-bottom: 0;
}

.settings-section.full-width {
  grid-column: 1 / -1;
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 24px;
}

.section-title {
  margin: 0;
  color: var(--primary);
  font-size: 16px;
}

.section-subtitle {
  max-width: 56ch;
  margin: 8px 0 0;
  font-size: 16px;
  line-height: 1.5;
}

.text-muted {
  color: var(--text-muted);
}

.auto-refresh {
  flex-shrink: 0;
  padding: 4px 8px;
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: 14px;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

/* Telegram Auth Banner */
.auth-banner {
  border-left: 2px solid var(--warning);
}

.auth-banner-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 20px 24px;
}

.auth-banner-copy {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  min-width: 0;
}

.auth-banner-icon {
  display: grid;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid var(--warning);
  color: var(--warning);
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}

.auth-banner-title {
  margin: 2px 0 0;
  color: var(--warning);
  font-size: 16px;
}

.auth-banner-text {
  max-width: 72ch;
  margin: 8px 0 0;
  font-size: 16px;
  line-height: 1.5;
}

/* System Status */
.status-card {
  display: flex;
  flex-direction: column;
}

.status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  transition: border-color 0.2s ease;
}

.status-item:hover {
  border-color: #333333;
}

.status-info {
  min-width: 0;
}

.status-info h4 {
  margin: 0 0 4px;
  color: var(--text-main);
  font-size: 15px;
}

.status-desc {
  display: block;
  overflow-wrap: anywhere;
  color: var(--text-muted);
  font-size: 16px;
  line-height: 1.45;
}

.status-pill {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid currentColor;
  border-radius: 2px;
}

.status-pill .label-caps {
  font-size: var(--fs-label);
}

.status-pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background-color: currentColor;
}

.status-pill.is-online {
  border-color: rgba(34, 197, 94, 0.35);
  background-color: rgba(34, 197, 94, 0.08);
  color: var(--success);
}

.status-pill.is-offline {
  border-color: rgba(239, 68, 68, 0.35);
  background-color: rgba(239, 68, 68, 0.08);
  color: var(--danger);
}

.status-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 16px;
  padding: 16px;
  border: 1px dashed var(--border-color);
}

.status-error p {
  margin: 0;
  font-size: 16px;
}

.btn-sm {
  padding: 6px 12px;
  font-size: 14px;
}

.status-loading {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-row {
  height: 64px;
  border: 1px solid var(--border-color);
  background: linear-gradient(90deg, var(--surface-2) 25%, #232323 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: skeletonShimmer 1.4s linear infinite;
}

@keyframes skeletonShimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

.stale-warning {
  margin: 12px 0 0;
  color: var(--warning);
  font-size: 14px;
}

.session-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: auto;
  padding-top: 20px;
  border-top: 1px solid var(--border-color);
}

.status-card .session-actions {
  margin-top: auto;
}

.status-card .status-list + .session-actions,
.status-card .status-error + .session-actions,
.status-card .status-loading + .session-actions {
  margin-top: 24px;
}

.session-info h4 {
  margin: 0 0 4px;
  color: var(--text-main);
  font-size: 15px;
}

/* Credentials */
.credentials-card {
  display: flex;
  flex-direction: column;
}

.credentials-form {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 20px;
}

.form-grid .form-group {
  margin-bottom: 0;
}

.form-group.full-span {
  grid-column: 1 / -1;
}

.form-label {
  font-size: 15px;
}

.form-input {
  font-size: 17px;
}

.label-hint {
  margin-left: 6px;
  color: var(--text-muted);
  font-size: var(--fs-label);
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: none;
}

.field-hint {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 15px;
  line-height: 1.4;
}

.form-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-top: 24px;
}

.form-message {
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.form-message.success {
  color: var(--success);
  animation: fadeInOut 3s ease forwards;
}

.form-message.error {
  color: var(--danger);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  box-shadow: none;
}

.btn:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

@keyframes fadeInOut {
  0% { opacity: 0; }
  10% { opacity: 1; }
  90% { opacity: 1; }
  100% { opacity: 0; }
}

/* Modals */
.auth-modal-description,
.reset-modal-description {
  margin-bottom: 24px;
}

.modal-content {
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}

.modal-close {
  position: absolute;
  top: 12px;
  right: 16px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  transition: color 0.2s;
}

.modal-close:hover {
  color: var(--primary);
}

.modal-title {
  font-size: var(--fs-h4);
}

.auth-error {
  margin: 0 0 16px;
  color: var(--danger);
  font-size: 15px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.modal-actions .btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  box-shadow: none;
}

/* Responsive */
@media (max-width: 900px) {
  .settings-grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
}

@media (max-width: 600px) {
  .page-header {
    margin-bottom: 16px;
  }

  .page-header .page-title {
    font-size: 28px;
  }

  .settings-section {
    padding: 18px;
  }

  .section-header {
    margin-bottom: 18px;
  }

  .auth-banner-body {
    align-items: stretch;
    flex-direction: column;
  }

  .auth-banner-body .btn {
    width: 100%;
  }

  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .form-group.full-span {
    grid-column: auto;
  }

  .form-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .form-actions .btn {
    width: 100%;
  }

  .session-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .session-actions .btn {
    width: 100%;
  }

  .modal-content {
    padding: 24px;
  }

  .modal-actions {
    flex-direction: column-reverse;
  }

  .modal-actions .btn {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .status-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-row,
  .form-message.success {
    animation: none;
  }
}
</style>
