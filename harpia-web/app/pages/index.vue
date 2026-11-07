<template>
  <div class="dashboard">
    <div class="dashboard-header-container">
      <h1 class="page-title">Painel</h1>
      
      <div class="dashboard-tabs">
        <button 
          :class="['tab-btn', { active: activeTab === 'feed' }]" 
          @click="activeTab = 'feed'"
        >
          Feed
        </button>
        <button 
          :class="['tab-btn', { active: activeTab === 'watchlist' }]" 
          @click="activeTab = 'watchlist'"
        >
          Watchlist
        </button>
      </div>
    </div>
    
    <div class="dashboard-grid">
      <!-- Left Column: Feed de Alertas -->
      <div :class="['col-feed', { 'active-tab': activeTab === 'feed' }]">
        <div class="metrics">
          <div class="metric-card">
            <span class="metric-value data-mono">{{ analyzedMessages }}</span>
            <span class="metric-label label-caps">Mensagens Analisadas</span>
          </div>
          <div class="metric-card">
            <span class="metric-value highlight data-mono">{{ alerts.length }}</span>
            <span class="metric-label label-caps">Hits Encontrados</span>
          </div>
          <div class="metric-card">
            <span class="metric-value data-mono">{{ monitoredGroups }}</span>
            <span class="metric-label label-caps">Grupos Ativos</span>
          </div>
        </div>

        <!-- Feed Filters -->
        <div class="feed-filters">
          <div class="search-box">
            <span class="search-icon">🔍</span>
            <input 
              type="text" 
              v-model="searchQuery" 
              class="filter-input label-caps" 
              placeholder="Filtrar telemetria por conteúdo ou alvo..."
            />
            <button v-if="searchQuery" class="clear-search" @click="searchQuery = ''" type="button">×</button>
          </div>
          <div class="filter-chips">
            <button 
              type="button"
              :class="['chip-btn', { active: selectedType === 'all' }]"
              @click="selectedType = 'all'"
            >
              Todos <span class="count-badge">{{ alerts.length }}</span>
            </button>
            <button 
              type="button"
              :class="['chip-btn', { active: selectedType === 'email' }]"
              @click="selectedType = 'email'"
            >
              E-mail <span class="count-badge">{{ getAlertCountByType('email') }}</span>
            </button>
            <button 
              type="button"
              :class="['chip-btn', { active: selectedType === 'domain' }]"
              @click="selectedType = 'domain'"
            >
              Domínio <span class="count-badge">{{ getAlertCountByType('domain') }}</span>
            </button>
            <button 
              type="button"
              :class="['chip-btn', { active: selectedType === 'cpf' }]"
              @click="selectedType = 'cpf'"
            >
              CPF <span class="count-badge">{{ getAlertCountByType('cpf') }}</span>
            </button>
          </div>
        </div>

        <div class="card feed-container">
          <div class="feed">
            <div class="alert-item" v-for="alert in filteredAlerts" :key="alert.id">
              <div class="alert-header">
                <div class="alert-meta">
                  <span :class="['tag', `tag-${alert.target_type}`]">{{ alert.target_value }}</span>
                  <span class="time data-mono">{{ alert.timestamp }}</span>
                </div>
                <div class="group-info label-caps">
                  // {{ alert.telegram_group_name }}
                </div>
              </div>
              <div class="alert-body">
                <p class="message-text">
                  <template
                    v-for="(part, partIndex) in highlightTarget(alert.message_text, alert.target_value)"
                    :key="partIndex"
                  >
                    <mark v-if="part.match">{{ part.text }}</mark>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </p>
              </div>
              <div class="alert-footer">
                <button class="btn btn-secondary" @click="openContextModal(alert)">Contexto Completo</button>
              </div>
            </div>

            <div v-if="alerts.length === 0" class="empty-state">
              <span class="icon">📡</span>
              <h3>RADAR LIMPO</h3>
              <p class="data-mono">AGUARDANDO INTERCEPTAÇÕES...</p>
            </div>
            <div v-else-if="filteredAlerts.length === 0" class="empty-state">
              <span class="icon">🔍</span>
              <h3>FILTRO SEM HITS</h3>
              <p class="data-mono">NENHUM ALERTA CORRESPONDE AOS CRITÉRIOS.</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Watchlist & Groups -->
      <div :class="['col-watchlist', { 'active-tab': activeTab === 'watchlist' }]">
        <div class="watchlist-section">
          <div class="header-actions">
            <div class="section-title-tabs">
              <button 
                type="button"
                :class="['section-tab-btn', 'label-caps', { active: watchlistSubTab === 'targets' }]" 
                @click="switchWatchlistSubTab('targets')"
              >
                Alvos Monitorados
              </button>
              <button 
                type="button"
                :class="['section-tab-btn', 'label-caps', { active: watchlistSubTab === 'groups' }]" 
                @click="switchWatchlistSubTab('groups')"
              >
                Grupos Monitorados
              </button>
            </div>
            <div class="header-buttons">
              <template v-if="watchlistSubTab === 'targets'">
                <button
                  type="button"
                  class="btn btn-secondary"
                  title="Arquivo .txt com um alvo por linha; o tipo é detectado automaticamente"
                  @click="triggerTargetImport"
                >
                  [↑] Importar
                </button>
                <button
                  type="button"
                  class="btn btn-primary"
                  @click="showAddModal = true"
                >
                  [+] Adicionar Alvo
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="btn btn-secondary"
                  title="Arquivo .txt com um grupo/canal por linha"
                  @click="triggerGroupImport"
                >
                  [↑] Importar
                </button>
                <button
                  type="button"
                  class="btn btn-primary"
                  @click="showAddGroupModal = true"
                >
                  [+] Adicionar Grupo
                </button>
              </template>
            </div>
          </div>

          <div v-if="importFeedback" :class="['import-feedback', importFeedback.type]">
            <span>{{ importFeedback.message }}</span>
            <button type="button" class="btn-close" @click="clearImportFeedback">×</button>
          </div>

          <input ref="targetFileInput" type="file" accept=".txt,.csv" class="hidden-file-input" @change="handleTargetFile" />
          <input ref="groupFileInput" type="file" accept=".txt,.csv" class="hidden-file-input" @change="handleGroupFile" />

          <!-- Watchlist (Targets) Tab Content -->
          <div v-if="watchlistSubTab === 'targets'" class="card table-container">
            <table class="target-table">
              <thead>
                <tr class="label-caps">
                  <th>Alvo</th>
                  <th>Tipo</th>
                  <th>Inserção</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="target in targets" :key="target.id">
                  <td class="data-mono">{{ target.value }}</td>
                  <td>
                    <span :class="['tag', `tag-${target.type}`]">{{ target.type }}</span>
                  </td>
                  <td class="data-mono text-muted">{{ target.added_at }}</td>
                  <td>
                    <span class="status-indicator">
                      <span class="dot" :style="{ backgroundColor: target.is_active ? 'var(--success)' : 'var(--text-muted)' }"></span>
                      <span class="label-caps">{{ target.is_active ? 'Ativo' : 'Inativo' }}</span>
                    </span>
                  </td>
                  <td class="actions">
                    <button class="btn-icon text-danger data-mono" @click="removeTarget(target.id)">[X]</button>
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="targets.length === 0" class="empty-state">
              <span class="icon">📋</span>
              <h3 class="label-caps">WATCHLIST VAZIA</h3>
              <p class="data-mono">INSIRA ALVOS PARA INICIAR A TELEMETRIA.</p>
            </div>
          </div>

          <!-- Monitored Groups Tab Content -->
          <div v-else-if="watchlistSubTab === 'groups'" class="card table-container">
            <table class="target-table">
              <thead>
                <tr class="label-caps">
                  <th>Grupo/Canal</th>
                  <th>Telegram Chat ID</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="group in groups" :key="group.id">
                  <td class="data-mono">{{ group.name }}</td>
                  <td class="data-mono text-muted">{{ group.telegram_chat_id || '-' }}</td>
                  <td class="actions">
                    <button class="btn-icon text-danger data-mono" @click="removeGroup(group.id)">[X]</button>
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="groups.length === 0" class="empty-state">
              <span class="icon">💬</span>
              <h3 class="label-caps">SEM GRUPOS ATIVOS</h3>
              <p class="data-mono">INSIRA GRUPOS PARA INICIAR O MONITORAMENTO.</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Target Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal-content">
        <h3 class="modal-title label-caps">Novo Alvo</h3>
        <form @submit.prevent="addTarget">
          <div class="form-group">
            <label class="form-label">Tipo</label>
            <select v-model="newTarget.type" class="form-input">
              <option value="email">E-mail</option>
              <option value="domain">Domínio</option>
              <option value="cpf">CPF</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Valor (Target)</label>
            <input 
              type="text" 
              v-model="newTarget.value" 
              class="form-input" 
              :placeholder="getPlaceholder()"
              required
            />
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary">Salvar</button>
            <button type="button" class="btn btn-secondary" @click="showAddModal = false">Cancelar</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Add Group Modal -->
    <div v-if="showAddGroupModal" class="modal-overlay" @click.self="showAddGroupModal = false">
      <div class="modal-content">
        <h3 class="modal-title label-caps">Novo Grupo</h3>
        <form @submit.prevent="addGroup">
          <div class="form-group">
            <label class="form-label">Nome do Canal/Grupo ou Chat ID</label>
            <input 
              type="text" 
              v-model="newGroupName" 
              class="form-input" 
              placeholder="@nomedogrupo ou Chat ID"
              required
            />
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary">Salvar</button>
            <button type="button" class="btn btn-secondary" @click="showAddGroupModal = false">Cancelar</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Full Context Modal -->
    <div v-if="showContextModal && selectedAlert" class="modal-overlay" @click.self="closeContextModal">
      <div class="modal-content context-modal">
        <div class="modal-header">
          <h3 class="modal-title label-caps">Detalhes do Alerta</h3>
          <button class="btn-close" @click="closeContextModal">×</button>
        </div>
        
        <div class="modal-meta-grid">
          <div class="meta-item">
            <span class="meta-label label-caps">Grupo Telegram</span>
            <span class="meta-value data-mono">{{ selectedAlert.telegram_group_name }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label label-caps">Alvo Detectado</span>
            <div>
              <span :class="['tag', `tag-${selectedAlert.target_type}`]">{{ selectedAlert.target_value }}</span>
            </div>
          </div>
          <div class="meta-item">
            <span class="meta-label label-caps">Data/Hora Interceptação</span>
            <span class="meta-value data-mono">{{ selectedAlert.timestamp }}</span>
          </div>
        </div>

        <div class="modal-body-content">
          <span class="meta-label label-caps">Mensagem Interceptada</span>
          <div class="message-content-wrapper">
            <pre class="message-pre"><code><template v-for="(part, partIndex) in highlightTarget(selectedAlert.message_text, selectedAlert.target_value)" :key="partIndex"><mark v-if="part.match">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></code></pre>
          </div>
        </div>

        <div class="form-actions">
          <button type="button" class="btn btn-secondary" @click="copyAlertText">
            {{ copySuccess ? 'Copiado!' : 'Copiar Mensagem' }}
          </button>
          <button type="button" class="btn btn-primary" @click="closeContextModal">Fechar</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'

const config = useRuntimeConfig()

// Tab state for mobile
const activeTab = ref('feed')

// Feed de Alertas state
const alerts = ref([])
const analyzedMessages = ref(0)
const monitoredGroups = ref(0)
let eventSource = null

// Feed Filters state
const searchQuery = ref('')
const selectedType = ref('all')

// Context Modal state
const showContextModal = ref(false)
const selectedAlert = ref(null)
const copySuccess = ref(false)

const getAlertCountByType = (type) => {
  return alerts.value.filter(alert => alert.target_type === type).length
}

const filteredAlerts = computed(() => {
  return alerts.value.filter(alert => {
    const q = searchQuery.value.trim().toLowerCase()
    const matchesSearch = !q || 
      (alert.message_text && alert.message_text.toLowerCase().includes(q)) ||
      (alert.target_value && alert.target_value.toLowerCase().includes(q)) ||
      (alert.telegram_group_name && alert.telegram_group_name.toLowerCase().includes(q))
      
    const matchesType = selectedType.value === 'all' || alert.target_type === selectedType.value
    
    return matchesSearch && matchesType
  })
})

const openContextModal = (alert) => {
  selectedAlert.value = alert
  showContextModal.value = true
  copySuccess.value = false
}

const closeContextModal = () => {
  showContextModal.value = false
  selectedAlert.value = null
  copySuccess.value = false
}

const copyAlertText = async () => {
  if (!selectedAlert.value) return
  try {
    await navigator.clipboard.writeText(selectedAlert.value.message_text)
    copySuccess.value = true
    setTimeout(() => {
      copySuccess.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy text: ', err)
  }
}

// Watchlist state
const showAddModal = ref(false)
const newTarget = ref({
  type: 'email',
  value: ''
})
const targets = ref([])

// Watchlist sub-tab state
const watchlistSubTab = ref('targets')

// Groups management state
const showAddGroupModal = ref(false)
const newGroupName = ref('')
const groups = ref([])

// Bulk import state
const targetFileInput = ref(null)
const groupFileInput = ref(null)
const importFeedback = ref(null)

onMounted(async () => {
  // Load dashboard status, groups, feed history, and watchlist targets
  try {
    const status = await $fetch(`${config.public.apiBase}/system/status`)
    if (status && status.stats) {
      analyzedMessages.value = status.stats.analyzed_messages || 0
    }

    await loadGroups()
    
    const history = await $fetch(`${config.public.apiBase}/feed/history`)
    if (history && history.length > 0) {
      alerts.value = history
    }
  } catch(e) {
    console.error("Error loading metrics/feed:", e)
  }

  await loadWatchlist()

  // Connect to SSE stream
  eventSource = new EventSource(`${config.public.apiBase}/feed/stream`)
  
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      
      if (data.analyzed_messages !== undefined) {
        analyzedMessages.value = data.analyzed_messages
      } else {
        alerts.value.unshift(data)
      }
    } catch(e) {
      console.error("Error parsing feed event:", e)
    }
  }
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
  }
})

const escapeRegExp = (value) => String(value).replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')

// Returns inert text segments plus the matched target, so the template can
// render <mark> without ever injecting message content as HTML.
const highlightTarget = (text, target) => {
  const source = text == null ? '' : String(text)
  if (!source) return [{ text: '', match: false }]
  if (!target) return [{ text: source, match: false }]

  const regex = new RegExp(`(${escapeRegExp(target)})`, 'gi')
  const parts = []
  let lastIndex = 0

  for (const match of source.matchAll(regex)) {
    if (match.index > lastIndex) {
      parts.push({ text: source.slice(lastIndex, match.index), match: false })
    }
    parts.push({ text: match[0], match: true })
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < source.length) {
    parts.push({ text: source.slice(lastIndex), match: false })
  }

  return parts.length ? parts : [{ text: source, match: false }]
}

// Watchlist methods
const loadWatchlist = async () => {
  try {
    const data = await $fetch(`${config.public.apiBase}/watchlist/`)
    targets.value = data.map(item => ({
      ...item,
      type: item.target_type,
      added_at: new Date(item.added_at).toISOString().split('T')[0]
    })).reverse()
  } catch (e) {
    console.error('Failed to load watchlist', e)
  }
}

const loadGroups = async () => {
  try {
    const data = await $fetch(`${config.public.apiBase}/groups/`)
    groups.value = data
    monitoredGroups.value = data.length
  } catch (e) {
    console.error('Failed to load groups', e)
  }
}

const getPlaceholder = () => {
  if (newTarget.value.type === 'email') return 'exemplo@empresa.com.br'
  if (newTarget.value.type === 'domain') return 'empresa.com.br'
  if (newTarget.value.type === 'cpf') return '000.000.000-00'
  return ''
}

const addTarget = async () => {
  try {
    await $fetch(`${config.public.apiBase}/watchlist/`, {
      method: 'POST',
      body: {
        target_type: newTarget.value.type,
        value: newTarget.value.value
      }
    })
    await loadWatchlist()
    newTarget.value.value = ''
    showAddModal.value = false
  } catch (e) {
    console.error('Failed to add target', e)
    alert(e.data?.detail || 'Erro ao adicionar alvo')
  }
}

const removeTarget = async (id) => {
  try {
    await $fetch(`${config.public.apiBase}/watchlist/${id}`, {
      method: 'DELETE'
    })
    targets.value = targets.value.filter(t => t.id !== id)
  } catch (e) {
    console.error('Failed to delete target', e)
    alert('Erro ao deletar alvo')
  }
}

const addGroup = async () => {
  if (!newGroupName.value) return
  try {
    const created = await $fetch(`${config.public.apiBase}/groups/`, {
      method: 'POST',
      body: { name: newGroupName.value }
    })
    groups.value.push(created)
    monitoredGroups.value = groups.value.length
    newGroupName.value = ''
    showAddGroupModal.value = false
  } catch (e) {
    console.error('Failed to add group', e)
    alert(e.data?.detail || 'Erro ao adicionar grupo')
  }
}

const removeGroup = async (id) => {
  try {
    await $fetch(`${config.public.apiBase}/groups/${id}`, {
      method: 'DELETE'
    })
    groups.value = groups.value.filter(g => g.id !== id)
    monitoredGroups.value = groups.value.length
  } catch (e) {
    console.error('Failed to delete group', e)
    alert('Erro ao deletar grupo')
  }
}

const clearImportFeedback = () => {
  importFeedback.value = null
}

const switchWatchlistSubTab = (tab) => {
  watchlistSubTab.value = tab
  clearImportFeedback()
}

const triggerTargetImport = () => {
  clearImportFeedback()
  targetFileInput.value?.click()
}

const triggerGroupImport = () => {
  clearImportFeedback()
  groupFileInput.value?.click()
}

const readFileAsText = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(String(reader.result || '').replace(/^\uFEFF/, ''))
  reader.onerror = () => reject(reader.error)
  reader.readAsText(file)
})

const inferTargetType = (value) => {
  if (!value || /\s/.test(value)) return null
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return 'email'
  if (/^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$/.test(value)) return 'cpf'
  return 'domain'
}

const buildImportSummary = (label, result, extraInvalid = 0) => {
  const parts = [`${result.added_count} ${label}(s) adicionado(s)`]
  if (result.skipped_duplicates_count) {
    parts.push(`${result.skipped_duplicates_count} duplicado(s) ignorado(s)`)
  }
  const invalidCount = (result.invalid_count || 0) + extraInvalid
  if (invalidCount) {
    parts.push(`${invalidCount} inválido(s) ignorado(s)`)
  }
  return parts.join(', ') + '.'
}

const handleTargetFile = async (event) => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return

  clearImportFeedback()
  try {
    const text = await readFileAsText(file)
    const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    const items = []
    let ignored = 0

    for (const line of lines) {
      const target_type = inferTargetType(line)
      if (!target_type) {
        ignored += 1
        continue
      }
      items.push({ target_type, value: line })
    }

    if (!items.length) {
      importFeedback.value = {
        type: 'error',
        message: ignored
          ? `Nenhum alvo válido encontrado (${ignored} linha(s) inválida(s)).`
          : 'O arquivo está vazio.'
      }
      return
    }

    const result = await $fetch(`${config.public.apiBase}/watchlist/bulk`, {
      method: 'POST',
      body: { items }
    })

    await loadWatchlist()
    importFeedback.value = {
      type: (result.invalid_count || ignored) ? 'warning' : 'success',
      message: buildImportSummary('alvo', result, ignored)
    }
  } catch (e) {
    console.error('Failed to import targets', e)
    importFeedback.value = {
      type: 'error',
      message: e.data?.detail || 'Erro ao importar alvos.'
    }
  }
}

const handleGroupFile = async (event) => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return

  clearImportFeedback()
  try {
    const text = await readFileAsText(file)
    const items = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean)

    if (!items.length) {
      importFeedback.value = { type: 'error', message: 'O arquivo está vazio.' }
      return
    }

    const result = await $fetch(`${config.public.apiBase}/groups/bulk`, {
      method: 'POST',
      body: { items }
    })

    await loadGroups()
    importFeedback.value = {
      type: result.invalid_count ? 'warning' : 'success',
      message: buildImportSummary('grupo', result)
    }
  } catch (e) {
    console.error('Failed to import groups', e)
    importFeedback.value = {
      type: 'error',
      message: e.data?.detail || 'Erro ao importar grupos.'
    }
  }
}
</script>

<style scoped>
.dashboard {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dashboard-header-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.dashboard-header-container .page-title {
  margin-bottom: 0;
}

.dashboard-grid {
  flex: 1;
  min-height: 0;
  align-items: stretch;
}

.col-feed {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}

.col-watchlist {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.metric-card {
  background-color: var(--surface-1);
  border: 1px solid var(--border-color);
  padding: 24px;
  display: flex;
  flex-direction: column;
}

.metric-value {
  font-size: var(--fs-h1);
  color: var(--text-main);
  margin-bottom: 8px;
}

.metric-value.highlight {
  color: var(--primary);
  text-shadow: 0 0 10px rgba(255, 184, 0, 0.3);
}

.metric-label {
  color: var(--text-muted);
}

/* Feed Filters styles */
.feed-filters {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
  background-color: var(--surface-1);
  border: 1px solid var(--border-color);
  padding: 16px;
}

.search-box {
  display: flex;
  align-items: center;
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  padding: 0 12px;
  position: relative;
}

.search-icon {
  color: var(--text-muted);
  font-size: var(--fs-body);
  margin-right: 8px;
}

.filter-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-main);
  font-family: var(--font-mono);
  font-size: var(--fs-control);
  padding: 10px 0;
  outline: none;
}

.clear-search {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  padding: 0 4px;
}

.clear-search:hover {
  color: var(--primary);
}

.filter-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip-btn {
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  padding: 6px 12px;
  font-family: var(--font-sans);
  font-size: var(--fs-label);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.chip-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.chip-btn.active {
  border-color: var(--primary);
  color: var(--primary);
  background-color: rgba(255, 184, 0, 0.05);
}

.count-badge {
  background-color: var(--surface-2);
  color: var(--text-muted);
  padding: 2px 6px;
  font-size: var(--fs-label);
  font-family: var(--font-mono);
}

.chip-btn.active .count-badge {
  background-color: var(--primary);
  color: var(--on-primary);
}

.feed-container {
  padding: 0;
  overflow: hidden;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--border-color);
  background-color: var(--surface-1);
  display: flex;
  flex-direction: column;
}

.feed {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}

.alert-item {
  border-bottom: 1px solid var(--border-color);
  background-color: var(--surface-1);
  position: relative;
  overflow: hidden;
  padding: 20px 24px;
  transition: background-color 0.2s ease;
}

.alert-item:last-child {
  border-bottom: none;
}

.alert-item:hover {
  background-color: var(--surface-2);
}

.alert-item::before {
  content: '';
  position: absolute;
  top: 0; left: 0; bottom: 0; width: 4px;
  background: repeating-linear-gradient(
    45deg,
    var(--primary),
    var(--primary) 10px,
    #000000 10px,
    #000000 20px
  );
}

.alert-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--surface-2);
}

.alert-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.time {
  color: var(--text-muted);
  font-size: var(--fs-label);
}

.group-info {
  color: var(--text-muted);
}

.message-text {
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  line-height: 1.6;
  color: var(--text-main);
}

:deep(mark) {
  background-color: rgba(255, 184, 0, 0.2);
  color: var(--primary);
  padding: 0 4px;
  font-weight: 600;
  border: 1px solid var(--primary);
}

.alert-footer {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

/* Watchlist Column Styles */
.watchlist-section {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  min-width: 0;
  width: 100%;
}

.watchlist-section .header-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 24px;
}

.header-buttons {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hidden-file-input {
  display: none;
}

.import-feedback {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
  background-color: var(--surface-1);
  color: var(--text-main);
  font-family: var(--font-mono);
  font-size: var(--fs-label);
}

.import-feedback.success {
  border-color: var(--success);
  color: var(--success);
}

.import-feedback.warning {
  border-color: var(--warning);
  color: var(--warning);
}

.import-feedback.error {
  border-color: var(--danger);
  color: var(--danger);
}

.watchlist-section .section-title {
  font-size: var(--fs-h3);
  font-weight: 700;
  letter-spacing: 0.05em;
  margin-bottom: 0;
}

.section-title-tabs {
  display: flex;
  gap: 20px;
}

.section-tab-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-family: var(--font-display);
  font-size: var(--fs-h3);
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 0 0 6px 0;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  text-transform: uppercase;
  transition: all 0.2s ease;
}

.section-tab-btn:hover {
  color: var(--text-main);
}

.section-tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
}

.table-container {
  padding: 0;
  overflow: auto;
  flex: 1;
  min-height: 0;
  min-width: 0;
  width: 100%;
  border: 1px solid var(--border-color);
  background-color: var(--surface-1);
}

.target-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.target-table th, .target-table td {
  padding: 16px 24px;
  border-bottom: 1px solid var(--surface-2);
  white-space: nowrap;
}

.target-table th {
  color: var(--text-muted);
  background-color: #0A0A0A;
  position: sticky;
  top: 0;
  z-index: 1;
  box-shadow: inset 0 -1px 0 var(--border-color);
}

.target-table tbody tr:hover {
  background-color: var(--surface-2);
}

.text-muted {
  color: var(--text-muted);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
}

.actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  transition: color 0.2s;
}

.btn-icon:hover {
  color: var(--danger);
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  justify-content: flex-end;
}

/* Context Modal custom styles */
.context-modal {
  max-width: 680px;
  width: 95%;
  display: flex;
  flex-direction: column;
  max-height: 85vh;
}

.context-modal .modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 12px;
}

.context-modal .modal-title {
  margin-bottom: 0;
}

.btn-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 24px;
  cursor: pointer;
  line-height: 1;
}

.btn-close:hover {
  color: var(--danger);
}

.modal-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  background-color: var(--surface-2);
  border: 1px solid var(--border-color);
  padding: 16px;
  margin-bottom: 20px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-label {
  font-size: var(--fs-label);
  color: var(--text-muted);
}

.meta-value {
  font-size: var(--fs-body);
  color: var(--text-main);
  word-break: break-all;
}

.modal-body-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  min-height: 0;
  margin-bottom: 20px;
}

.message-content-wrapper {
  flex: 1;
  background-color: var(--bg-color);
  border: 1px solid var(--border-color);
  padding: 16px;
  overflow-y: auto;
  min-height: 150px;
  max-height: 350px;
}

.message-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-sans);
  font-size: var(--fs-body);
  line-height: 1.5;
  color: var(--text-main);
}

.message-pre code {
  font-family: inherit;
}
</style>
