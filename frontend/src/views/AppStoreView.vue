<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()

const CATEGORIES = [
  { key: 'php', label: 'PHP' },
  { key: 'node', label: 'Node.js' },
  { key: 'go', label: 'Go' },
  { key: 'app', label: 'Aplikasi' },
]
const activeTab = ref('php')
const items = ref([])
const busyId = ref(null)
const showPhpConfig = ref(null)
const activeConfigTab = ref('ini')
const phpConfig = reactive({
  version: '',
  ini: {},
  pool: {},
  extensions: [],
  commonIniKeys: [],
  commonPoolKeys: [],
  loading: false,
  saving: false,
})
const newExtName = ref('')

const commonExtensions = [
  'gd', 'curl', 'mbstring', 'xml', 'zip', 'mysql', 'pgsql',
  'redis', 'imagick', 'intl', 'bcmath', 'soap', 'xdebug',
  'igbinary', 'msgpack'
]

const visibleItems = computed(() => items.value.filter(i => i.category === activeTab.value))
const installedPhpVersions = computed(() => 
  items.value.filter(i => i.category === 'php' && i.installed).map(i => i.id)
)

onMounted(refresh)

async function refresh() {
  try {
    const r = await api.get('/api/appstore')
    items.value = r.items || []
  } catch (e) { notify(e.message, false) }
}

async function act(item, action) {
  busyId.value = item.id
  try {
    await api.post(`/api/appstore/${item.id}/${action}`)
    notify(`${item.name} ${action === 'install' ? 'terinstall' : 'dihapus'}`, true)
    await refresh()
  } catch (e) { notify(e.message, false) }
  finally { busyId.value = null }
}

async function openPhpConfig(versionId) {
  showPhpConfig.value = versionId
  activeConfigTab.value = 'ini'
  phpConfig.loading = true
  try {
    const sites = await api.get('/api/sites')
    const phpSite = sites.find(s => s.php_version === versionId)
    if (!phpSite) {
      notify('Tidak ada site yang menggunakan PHP versi ini', false)
      showPhpConfig.value = null
      return
    }
    const cfg = await api.get(`/api/sites/${phpSite.id}/php-config`)
    phpConfig.version = cfg.php_version
    phpConfig.ini = { ...cfg.ini }
    phpConfig.pool = { ...cfg.pool }
    phpConfig.extensions = cfg.extensions
    phpConfig.commonIniKeys = cfg.common_ini_keys
    phpConfig.commonPoolKeys = cfg.common_pool_keys
  } catch (e) { notify(e.message, false) }
  finally { phpConfig.loading = false }
}

function closePhpConfig() {
  showPhpConfig.value = null
  phpConfig.ini = {}
  phpConfig.pool = {}
  phpConfig.extensions = []
}

async function saveIni() {
  phpConfig.saving = true
  try {
    const sites = await api.get('/api/sites')
    const phpSite = sites.find(s => s.php_version === phpConfig.version)
    if (!phpSite) return
    await api.put(`/api/sites/${phpSite.id}/php-config`, { ini: phpConfig.ini })
    notify('php.ini disimpan', true)
  } catch (e) { notify(e.message, false) }
  finally { phpConfig.saving = false }
}

async function savePool() {
  phpConfig.saving = true
  try {
    const sites = await api.get('/api/sites')
    const phpSite = sites.find(s => s.php_version === phpConfig.version)
    if (!phpSite) return
    await api.put(`/api/sites/${phpSite.id}/php-pool`, { pool: phpConfig.pool })
    notify('Pool options disimpan', true)
  } catch (e) { notify(e.message, false) }
  finally { phpConfig.saving = false }
}

async function toggleExtension(ext, enable) {
  try {
    const sites = await api.get('/api/sites')
    const phpSite = sites.find(s => s.php_version === phpConfig.version)
    if (!phpSite) return
    await api.post(`/api/sites/${phpSite.id}/php-extensions/${enable ? 'enable' : 'disable'}`, { extension: ext })
    notify(`Extension ${ext} ${enable ? 'diaktifkan' : 'dinonaktifkan'}`, true)
    const cfg = await api.get(`/api/sites/${phpSite.id}/php-config`)
    phpConfig.extensions = cfg.extensions
  } catch (e) { notify(e.message, false) }
}

async function installExtension(ext) {
  try {
    const sites = await api.get('/api/sites')
    const phpSite = sites.find(s => s.php_version === phpConfig.version)
    if (!phpSite) return
    await api.post(`/api/sites/${phpSite.id}/php-extensions/install`, { extension: ext })
    notify(`Extension ${ext} terinstall`, true)
    const cfg = await api.get(`/api/sites/${phpSite.id}/php-config`)
    phpConfig.extensions = cfg.extensions
  } catch (e) { notify(e.message, false) }
}
</script>

<template>
  <div class="page">
    <h1>App Store</h1>
    <p class="muted">Pasang runtime & aplikasi pendukung server.</p>

    <div class="tabs">
      <button v-for="c in CATEGORIES" :key="c.key"
        :class="['tab', { active: activeTab === c.key }]"
        @click="activeTab = c.key">{{ c.label }}</button>
    </div>

    <!-- PHP Config Panel -->
    <div v-if="showPhpConfig" class="php-config-panel">
      <div class="panel-header">
        <h2>Konfigurasi PHP: {{ phpConfig.version }}</h2>
        <button class="btn btn-secondary" @click="closePhpConfig">Tutup</button>
      </div>
      
      <div v-if="phpConfig.loading" class="loading">Memuat konfigurasi...</div>
      
      <div v-else class="config-tabs">
        <div class="config-tab-buttons">
          <button :class="['config-tab-btn', { active: activeConfigTab === 'ini' }]" @click="activeConfigTab = 'ini'">php.ini</button>
          <button :class="['config-tab-btn', { active: activeConfigTab === 'pool' }]" @click="activeConfigTab = 'pool'">Pool Options</button>
          <button :class="['config-tab-btn', { active: activeConfigTab === 'ext' }]" @click="activeConfigTab = 'ext'">Extensions</button>
        </div>
        
        <!-- php.ini tab -->
        <div v-if="activeConfigTab === 'ini'" class="config-tab-content">
          <table class="table">
            <thead><tr><th>Key</th><th>Value</th><th>Aksi</th></tr></thead>
            <tbody>
              <tr v-for="key in phpConfig.commonIniKeys" :key="key">
                <td>{{ key }}</td>
                <td>
                  <input v-model="phpConfig.ini[key]" class="input" :placeholder="phpConfig.ini[key] || '(default)'">
                </td>
                <td></td>
              </tr>
            </tbody>
          </table>
          <button class="btn btn-primary" @click="saveIni" :disabled="phpConfig.saving">
            {{ phpConfig.saving ? 'Menyimpan...' : 'Simpan php.ini' }}
          </button>
        </div>
        
        <!-- Pool Options tab -->
        <div v-if="activeConfigTab === 'pool'" class="config-tab-content">
          <table class="table">
            <thead><tr><th>Key</th><th>Value</th><th>Aksi</th></tr></thead>
            <tbody>
              <tr v-for="key in phpConfig.commonPoolKeys" :key="key">
                <td>{{ key }}</td>
                <td>
                  <input v-model="phpConfig.pool[key]" class="input" :placeholder="phpConfig.pool[key] || '(default)'">
                </td>
                <td></td>
              </tr>
            </tbody>
          </table>
          <button class="btn btn-primary" @click="savePool" :disabled="phpConfig.saving">
            {{ phpConfig.saving ? 'Menyimpan...' : 'Simpan Pool Options' }}
          </button>
        </div>
        
        <!-- Extensions tab -->
        <div v-if="activeConfigTab === 'ext'" class="config-tab-content">
          <table class="table">
            <thead><tr><th>Extension</th><th>Status</th><th>Aksi</th></tr></thead>
            <tbody>
              <tr v-for="ext in phpConfig.extensions" :key="ext.name">
                <td>{{ ext.name }}</td>
                <td>
                  <span :class="['badge', ext.enabled ? 'ok' : 'muted']">
                    {{ ext.enabled ? 'Aktif' : 'Nonaktif' }}
                  </span>
                </td>
                <td>
                  <button v-if="ext.enabled" class="btn btn-sm btn-danger" @click="toggleExtension(ext.name, false)">Disable</button>
                  <button v-else class="btn btn-sm btn-primary" @click="toggleExtension(ext.name, true)">Enable</button>
                </td>
              </tr>
            </tbody>
          </table>
          <hr>
          <h4>Install Extension Baru</h4>
          <div class="extension-install">
            <select v-model="newExtName" class="input">
              <option value="">Pilih extension...</option>
              <option v-for="ext in commonExtensions" :key="ext" :value="ext">{{ ext }}</option>
            </select>
            <button class="btn btn-primary" @click="installExtension(newExtName)" :disabled="!newExtName">Install</button>
          </div>
        </div>
      </div>
    </div>

    <table class="table">
      <thead>
        <tr><th>Nama</th><th>Deskripsi</th><th>Status</th><th>Aksi</th></tr>
      </thead>
      <tbody>
        <tr v-for="i in visibleItems" :key="i.id">
          <td>{{ i.name }}</td>
          <td>{{ i.desc }}</td>
          <td>
            <span :class="['badge', i.installed ? 'ok' : 'muted']">
              {{ i.installed ? 'Terinstall' : 'Belum' }}
            </span>
          </td>
          <td>
            <button v-if="!i.installed" class="btn btn-primary"
              :disabled="busyId === i.id" @click="act(i, 'install')">Install</button>
            <button v-else class="btn btn-danger"
              :disabled="busyId === i.id" @click="act(i, 'uninstall')">Uninstall</button>
            <!-- Config button for installed PHP -->
            <button v-if="i.installed && i.category === 'php'" class="btn btn-secondary" @click="openPhpConfig(i.id)">Konfigurasi</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>