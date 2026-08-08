<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()

const usedPorts = ref([])
const availablePorts = ref([])
const firewallRules = ref([])
const firewallTool = ref('')
const loading = ref(false)
const activeTab = ref('used')
const filterProtocol = ref('')
const filterSource = ref('')
const searchQuery = ref('')

// Firewall form
const fwPort = ref('')
const fwProtocol = ref('both')
const fwAction = ref('allow')
const fwComment = ref('')

const protocols = computed(() => [...new Set(usedPorts.value.map(p => p.protocol))])
const sources = computed(() => [...new Set(usedPorts.value.map(p => p.source))])

const stats = computed(() => {
  const listening = usedPorts.value.filter(p => p.state === 'LISTEN' || p.state === 'MANAGED').length
  const established = usedPorts.value.filter(p => p.state === 'ESTABLISHED').length
  const system = usedPorts.value.filter(p => p.source === 'system').length
  return { total: usedPorts.value.length, listening, established, system }
})

onMounted(async () => {
  await loadPorts()
  await loadFirewallRules()
})

async function loadPorts() {
  loading.value = true
  try {
    const [used, available] = await Promise.all([
      api.get('/api/ports/used'),
      api.get('/api/ports/available', { params: { start: 1024, end: 65535, count: 100 } })
    ])
    usedPorts.value = used || []
    availablePorts.value = available || []
  } catch (e) {
    notify(e.message, false)
    usedPorts.value = []
    availablePorts.value = []
  } finally {
    loading.value = false
  }
}

async function loadFirewallRules() {
  try {
    const r = await api.get('/api/ports/firewall/rules')
    firewallRules.value = r.rules || []
    firewallTool.value = r.tool || 'unknown'
  } catch (e) {
    notify(e.message, false)
  }
}

const filteredUsedPorts = computed(() => {
  return usedPorts.value.filter(p => {
    if (filterProtocol.value && p.protocol !== filterProtocol.value) return false
    if (filterSource.value && p.source !== filterSource.value) return false
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      return (
        String(p.port).includes(q) ||
        p.process.toLowerCase().includes(q) ||
        String(p.pid).includes(q) ||
        p.state.toLowerCase().includes(q)
      )
    }
    return true
  })
})

function getStateClass(state) {
  if (state === 'LISTEN' || state === 'MANAGED') return 'on'
  if (state === 'ESTABLISHED') return 'established'
  return 'off'
}

function getSourceBadgeClass(source) {
  const classes = {
    'system': 'source-system',
    'ccpanel-project': 'source-project',
    'ccpanel-site-app': 'source-site-app',
    'ccpanel-site': 'source-site',
    'docker': 'source-docker',
  }
  return classes[source] || ''
}

async function checkPort(port) {
  try {
    const r = await api.get(`/api/ports/check/${port}`)
    notify(`Port ${port}: ${r.free ? 'BEBAS' : 'DIGUNAKAN oleh ' + r.used_by}`, r.free)
  } catch (e) {
    notify(e.message, false)
  }
}

async function reservePort(port) {
  if (!confirm(`Reservasi port ${port}?`)) return
  try {
    await api.post('/api/ports/reserve', { port, description: 'Manual reserve' })
    notify(`Port ${port} direservasi`)
    await loadPorts()
  } catch (e) {
    notify(e.message, false)
  }
}

async function firewallAction(action) {
  if (!fwPort.value) {
    notify('Masukkan port', false)
    return
  }
  const port = Number(fwPort.value)
  if (port < 1 || port > 65535) {
    notify('Port tidak valid (1-65535)', false)
    return
  }

  try {
    const rule = { port, protocol: fwProtocol.value, action, comment: fwComment.value }
    const endpoint = action === 'allow' ? '/api/ports/firewall/allow' : '/api/ports/firewall/deny'
    const r = await api.post(endpoint, rule)

    const success = r.results?.every(x => x.success) ?? false
    notify(`Port ${port} ${action === 'allow' ? 'dibuka' : 'ditutup'} di firewall (${fwProtocol.value.toUpperCase()})`, success)

    if (success) {
      fwPort.value = ''
      fwComment.value = ''
      await loadFirewallRules()
    }
  } catch (e) {
    notify(e.message, false)
  }
}

async function firewallToggle(port, protocol) {
  try {
    const rule = { port, protocol, action: 'toggle' }
    const r = await api.post('/api/ports/firewall/toggle', rule)
    const success = r.results?.every(x => x.success) ?? false
    notify(`Port ${port} firewall toggled`, success)
    if (success) await loadFirewallRules()
  } catch (e) {
    notify(e.message, false)
  }
}

function formatPid(pid) {
  return pid > 0 ? String(pid) : '—'
}
</script>

<template>
  <section class="max-w-7xl mx-auto p-4">
    <div class="head">
        <div>
          <h3>Manajemen Port</h3>
          <p class="dim">Deteksi, cek, dan kelola port server</p>
        </div>
        <button class="secondary" @click="loadPorts" :disabled="loading">
          <span class="spin" :class="{ spinning: loading }">⟳</span> Refresh
        </button>
      </div>

      <!-- Stat cards -->
      <div class="stats">
        <div class="stat">
          <span class="stat-label">Total Port</span>
          <span class="stat-value">{{ stats.total }}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Listening</span>
          <span class="stat-value accent">{{ stats.listening }}</span>
        </div>
        <div class="stat">
          <span class="stat-label">Established</span>
          <span class="stat-value blue">{{ stats.established }}</span>
        </div>
        <div class="stat">
          <span class="stat-label">System</span>
          <span class="stat-value muted">{{ stats.system }}</span>
        </div>
      </div>

      <div class="tabs">
        <button class="tab" :class="{ active: activeTab === 'used' }" @click="activeTab = 'used'">
          Port Digunakan <span class="tab-count">{{ filteredUsedPorts.length }}</span>
        </button>
        <button class="tab" :class="{ active: activeTab === 'available' }" @click="activeTab = 'available'">
          Port Tersedia <span class="tab-count">{{ availablePorts.length }}</span>
        </button>
      </div>

      <!-- Filters for Used Ports -->
      <div v-if="activeTab === 'used'" class="filters">
        <div class="search-wrap">
          <span class="search-icon">⌕</span>
          <input type="text" v-model="searchQuery" placeholder="Cari port, proses, PID, state..."
            class="search-input" />
        </div>
        <select v-model="filterProtocol" class="filter-select">
          <option value="">Semua Protokol</option>
          <option v-for="p in protocols" :key="p" :value="p">{{ p }}</option>
        </select>
        <select v-model="filterSource" class="filter-select">
          <option value="">Semua Sumber</option>
          <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
        </select>
      </div>

      <!-- Used Ports Table -->
      <div v-if="activeTab === 'used'">
        <div v-if="loading" class="loading">
          <span class="spinner"></span> Memuat data port...
        </div>
        <div v-else class="table-wrapper">
          <table class="port-table">
            <thead>
              <tr>
                <th>Port</th>
                <th>Protokol</th>
                <th>Proses</th>
                <th>PID</th>
                <th>State</th>
                <th>Sumber</th>
                <th>Aksi</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in filteredUsedPorts" :key="p.port">
                <td><span class="port-num">{{ p.port }}</span></td>
                <td><span class="proto">{{ p.protocol }}</span></td>
                <td class="process-cell" :title="p.process">{{ p.process }}</td>
                <td class="mono">{{ formatPid(p.pid) }}</td>
                <td><span class="badge" :class="getStateClass(p.state)">{{ p.state }}</span></td>
                <td><span class="source-badge" :class="getSourceBadgeClass(p.source)">{{ p.source }}</span></td>
                <td class="actions">
                  <button class="small" @click="checkPort(p.port)">Cek</button>
                  <button v-if="p.source === 'system'" class="small secondary"
                    @click="reservePort(p.port)">Reservasi</button>
                </td>
              </tr>
              <tr v-if="!filteredUsedPorts.length">
                <td colspan="7" class="empty">Tidak ada port terdeteksi</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Available Ports Grid -->
      <div v-if="activeTab === 'available'">
        <div v-if="loading" class="loading">
          <span class="spinner"></span> Memuat data port...
        </div>
        <div v-else class="port-grid-section">
          <div class="port-grid">
            <button v-for="p in availablePorts" :key="p.port" class="port-btn" :class="{
              'port-suggested': p.reason === 'suggested range',
              'port-common': p.reason === 'commonly used',
              'port-free': p.reason === 'free'
            }" @click="checkPort(p.port)" :title="p.reason">
              <span class="port-num">{{ p.port }}</span>
              <span class="port-reason">{{ p.reason }}</span>
            </button>
          </div>
          <p v-if="!availablePorts.length" class="empty">Tidak ada port tersedia di range 1024-65535</p>
        </div>
      </div>

      <!-- Legend -->
      <div class="legend">
        <h4>Keterangan</h4>
        <div class="legend-items">
          <span class="legend-item"><span class="badge on"></span> LISTEN / MANAGED</span>
          <span class="legend-item"><span class="badge established"></span> ESTABLISHED</span>
          <span class="legend-item"><span class="badge off"></span> CLOSED / OTHER</span>
          <span class="legend-item"><span class="source-badge source-system"></span> System</span>
          <span class="legend-item"><span class="source-badge source-project"></span> CCpanel Project</span>
          <span class="legend-item"><span class="source-badge source-site-app"></span> CCpanel Site App</span>
          <span class="legend-item"><span class="source-badge source-site"></span> CCpanel Site (nginx)</span>
          <span class="legend-item"><span class="source-badge source-docker"></span> Docker</span>
          <span class="legend-item port-suggested">Suggested Range (8000-8999)</span>
          <span class="legend-item port-common">Commonly Used</span>
          <span class="legend-item port-free">Free</span>
        </div>
      </div>

      <!-- Firewall Management -->
      <div class="firewall-section">
        <div class="fw-head">
          <h4>Firewall Management</h4>
          <span class="fw-tool">{{ firewallTool }}</span>
        </div>
        <div class="firewall-form">
          <div class="fw-row">
            <input type="number" v-model="fwPort" placeholder="Port (1-65535)" min="1" max="65535" class="fw-input" />
            <select v-model="fwProtocol" class="fw-select">
              <option value="both">TCP + UDP</option>
              <option value="tcp">TCP Only</option>
              <option value="udp">UDP Only</option>
            </select>
            <input type="text" v-model="fwComment" placeholder="Komentar (opsional)" class="fw-input grow" />
            <button class="primary" @click="firewallAction('allow')">Buka Port</button>
            <button class="danger" @click="firewallAction('deny')">Tutup Port</button>
          </div>
        </div>

        <div v-if="firewallRules.length > 0" class="firewall-rules">
          <h5>Aturan Firewall Aktif</h5>
          <div class="fw-rules-list">
            <div v-for="(rule, idx) in firewallRules" :key="idx" class="fw-rule">
              <span class="fw-rule-text">{{ rule.raw }}</span>
            </div>
          </div>
        </div>
        <p v-else class="dim">Tidak ada aturan port firewall terdeteksi</p>
      </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.head h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.head .dim {
  margin-top: 2px;
  font-size: 13px;
}

.dim {
  color: var(--muted);
  font-weight: normal;
}

/* Stats */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.stat {
  background: var(--panel);
  border: 1px solid var(--panel-2);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color .2s;
}

.stat:hover {
  border-color: var(--accent);
}

.stat-label {
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: .04em;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
}

.stat-value.accent {
  color: var(--ok);
}

.stat-value.blue {
  color: var(--accent);
}

.stat-value.muted {
  color: var(--muted);
}

/* Tabs */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.tab {
  background: var(--panel);
  border: 1px solid var(--panel-2);
  color: var(--muted);
  padding: 8px 16px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: all .2s;
}

.tab:hover {
  border-color: var(--accent);
  color: var(--text);
}

.tab.active {
  background: var(--accent);
  color: #0f172a;
  font-weight: 700;
  border-color: var(--accent);
}

.tab-count {
  background: var(--panel-2);
  color: var(--muted);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 600;
}

.tab.active .tab-count {
  background: rgba(15, 23, 42, .18);
  color: #0f172a;
}

/* Filters */
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}

.search-wrap {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  font-size: 14px;
  pointer-events: none;
}

.search-input {
  padding-left: 30px;
}

.filter-select {
  width: auto;
  min-width: 140px;
}

/* Table */
.table-wrapper {
  overflow-x: auto;
  background: var(--panel);
  border: 1px solid var(--panel-2);
  border-radius: 12px;
}

.port-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.port-table th,
.port-table td {
  padding: 11px 14px;
  text-align: left;
  border-bottom: 1px solid var(--panel-2);
}

.port-table th {
  background: rgba(51, 65, 85, .25);
  font-weight: 600;
  color: var(--muted);
  white-space: nowrap;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .05em;
}

.port-table tbody tr {
  transition: background .15s;
}

.port-table tbody tr:hover {
  background: rgba(56, 189, 248, .05);
}

.port-table tbody tr:last-child td {
  border-bottom: none;
}

.port-table .empty {
  text-align: center;
  color: var(--muted);
  padding: 30px;
}

.port-num {
  font-weight: 700;
  color: var(--accent);
  font-family: ui-monospace, monospace;
  font-size: 13px;
}

.proto {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--text);
  background: var(--panel-2);
  padding: 2px 8px;
  border-radius: 6px;
}

.process-cell {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: ui-monospace, monospace;
  color: var(--muted);
}

/* Badges */
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .03em;
}

.badge.on {
  background: rgba(74, 222, 128, .12);
  color: var(--ok);
  border: 1px solid rgba(74, 222, 128, .3);
}

.badge.established {
  background: rgba(56, 189, 248, .12);
  color: var(--accent);
  border: 1px solid rgba(56, 189, 248, .3);
}

.badge.off {
  background: rgba(248, 113, 113, .1);
  color: var(--danger);
  border: 1px solid rgba(248, 113, 113, .25);
}

.source-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  text-transform: capitalize;
}

.source-badge.source-system {
  background: rgba(148, 163, 184, .15);
  color: var(--muted);
}

.source-badge.source-project {
  background: rgba(74, 222, 128, .12);
  color: var(--ok);
}

.source-badge.source-site-app {
  background: rgba(56, 189, 248, .12);
  color: var(--accent);
}

.source-badge.source-site {
  background: rgba(251, 191, 36, .12);
  color: #fbbf24;
}

.source-badge.source-docker {
  background: rgba(167, 139, 250, .15);
  color: #a78bfa;
}

.actions {
  display: flex;
  gap: 6px;
}

.actions button {
  padding: 4px 10px;
  font-size: 12px;
}

/* Port grid */
.port-grid-section {
  margin-top: 8px;
}

.port-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.port-btn {
  padding: 10px 14px;
  border: 1px solid var(--panel-2);
  border-radius: 10px;
  background: var(--panel);
  cursor: pointer;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all .2s;
  min-width: 80px;
  justify-content: center;
}

.port-btn:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(56, 189, 248, .15);
}

.port-btn .port-num {
  color: var(--text);
}

.port-btn.port-suggested {
  border-color: rgba(74, 222, 128, .4);
  background: rgba(74, 222, 128, .08);
}

.port-btn.port-suggested .port-num {
  color: var(--ok);
}

.port-btn.port-common {
  border-color: rgba(251, 191, 36, .4);
  background: rgba(251, 191, 36, .08);
}

.port-btn.port-common .port-num {
  color: #fbbf24;
}

.port-reason {
  font-size: 10px;
  color: var(--muted);
  background: var(--panel-2);
  padding: 1px 6px;
  border-radius: 4px;
  text-transform: capitalize;
  white-space: nowrap;
}

/* Legend */
.legend {
  margin-top: 24px;
  padding: 16px;
  background: var(--panel);
  border-radius: 12px;
  border: 1px solid var(--panel-2);
}

.legend h4 {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
}

.legend-items {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  font-size: 12px;
  color: var(--muted);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-item.port-suggested {
  color: var(--ok);
  font-weight: 500;
}

.legend-item.port-common {
  color: #fbbf24;
  font-weight: 500;
}

.legend-item.port-free {
  color: var(--muted);
  font-weight: 500;
}

/* Loading */
.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: var(--muted);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--panel-2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

button.small {
  padding: 4px 10px;
  font-size: 12px;
}

button.secondary {
  background: var(--panel);
  border: 1px solid var(--panel-2);
  color: var(--muted);
}

button.secondary:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.spin {
  display: inline-block;
  font-size: 14px;
}

.spin.spinning {
  animation: spin .8s linear infinite;
}

/* Firewall Section */
.firewall-section {
  margin-top: 24px;
  padding: 20px;
  background: var(--panel);
  border-radius: 12px;
  border: 1px solid var(--panel-2);
}

.fw-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.firewall-section h4 {
  margin: 0;
  font-size: 14px;
  color: var(--text);
  font-weight: 600;
}

.fw-tool {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--accent);
  background: rgba(56, 189, 248, .1);
  border: 1px solid rgba(56, 189, 248, .25);
  padding: 2px 10px;
  border-radius: 999px;
  text-transform: capitalize;
}

.firewall-form {
  margin-bottom: 16px;
}

.fw-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.fw-input {
  min-width: 120px;
}

.fw-input.grow {
  flex: 1;
  min-width: 160px;
}

.fw-input[type="number"] {
  width: 110px;
}

.fw-select {
  width: auto;
  min-width: 130px;
}

.firewall-rules h5 {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
}

.fw-rules-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.fw-rule {
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--panel-2);
  border-radius: 8px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--text);
}

.fw-rule-text {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>