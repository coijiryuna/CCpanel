<script setup>
import { ref, onMounted } from 'vue'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const emit = defineEmits(['changed'])

const APP_TYPES = ['node', 'python', 'go', 'docker']
const DEFAULT_ENTRY = { node: 'index.js', python: 'app:app', go: 'app', docker: 'docker-compose.yml' }
const NODE_VERSIONS = ref([])

const showModal = ref(false)
const site = ref(null)
const app = ref(null)
const busy = ref(false)
const log = ref('')
const showLog = ref(false)
const deployMode = ref('default') // 'default' | 'pm2'
const form = ref({
  app_type: 'node', port: 8000, entry: '', subpath: '',
  name: '', run_opt: '', user: 'www', node_version: '', pm2: false, remark: '',
})

onMounted(async () => {
  try {
    const r = await api.get('/api/node/versions')
    NODE_VERSIONS.value = r.versions || []
  } catch { NODE_VERSIONS.value = [] }
})

function open(s) {
  site.value = s
  app.value = s.app || null
  if (app.value) {
    form.value = {
      app_type: app.value.app_type, port: app.value.port, entry: app.value.entry,
      subpath: app.value.subpath, name: app.value.name || '', run_opt: app.value.run_opt || '',
      user: app.value.user || 'www', node_version: app.value.node_version || '',
      pm2: !!app.value.pm2, remark: app.value.remark || '',
    }
    deployMode.value = app.value.pm2 ? 'pm2' : 'default'
  } else {
    form.value = {
      app_type: 'node', port: 8000, entry: '', subpath: '',
      name: '', run_opt: '', user: 'www', node_version: '', pm2: false, remark: '',
    }
    deployMode.value = 'default'
  }
  log.value = ''
  showLog.value = false
  showModal.value = true
}

async function save() {
  busy.value = true
  try {
    const isNode = form.value.app_type === 'node'
    const payload = {
      app_type: form.value.app_type,
      port: Number(form.value.port),
      entry: form.value.entry || DEFAULT_ENTRY[form.value.app_type],
      subpath: form.value.subpath,
      name: isNode ? form.value.name : '',
      run_opt: isNode ? form.value.run_opt : '',
      user: form.value.user || 'www',
      node_version: isNode ? form.value.node_version : '',
      pm2: isNode && deployMode.value === 'pm2',
      remark: form.value.remark,
    }
    if (app.value) {
      await api.put(`/api/sites/${site.value.id}/apps`, payload)
    } else {
      await api.post(`/api/sites/${site.value.id}/apps`, payload)
    }
    notify(app.value ? 'Aplikasi diupdate' : 'Aplikasi dipasang')
    showModal.value = false
    emit('changed')
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function action(a) {
  try {
    const r = await api.post(`/api/sites/${site.value.id}/apps/action`, { action: a })
    if (app.value) app.value.state = r.state
    notify(`Aplikasi ${a}`)
  } catch (e) { notify(e.message, false) }
}

async function remove() {
  if (!confirm(`Hapus aplikasi ${site.value.domain}? Unit systemd/compose dihentikan (file project tetap ada).`)) return
  try {
    await api.delete(`/api/sites/${site.value.id}/apps`)
    notify('Aplikasi dihapus')
    showModal.value = false
    emit('changed')
  } catch (e) { notify(e.message, false) }
}

async function tailLog() {
  try {
    const r = await api.get(`/api/sites/${site.value.id}/apps/log`)
    log.value = r.log
    showLog.value = true
  } catch (e) { notify(e.message, false) }
}

defineExpose({ open })
</script>

<template>
  <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
    <div class="modal">
      <h3>Aplikasi — {{ site.domain }}</h3>

      <template v-if="app">
        <p>Status: <span class="badge" :class="app.state === 'running' ? 'on' : 'off'">{{ app.state }}</span></p>
        <div class="field"><label>Jenis</label><input :value="app.app_type" disabled /></div>
        <div class="field"><label>Port</label><input :value="app.port" disabled /></div>
        <div class="field"><label>Entry</label><input :value="app.entry" disabled /></div>
        <div v-if="app.name" class="field"><label>Nama</label><input :value="app.name" disabled /></div>
        <div v-if="app.run_opt" class="field"><label>Run opt</label><input :value="app.run_opt" disabled /></div>
        <div class="field"><label>User</label><input :value="app.user || 'www'" disabled /></div>
        <div v-if="app.node_version" class="field"><label>Node</label><input :value="app.node_version" disabled /></div>
        <div v-if="app.remark" class="field"><label>Remark</label><input :value="app.remark" disabled /></div>
        <div class="field"><label>Subpath</label><input :value="app.subpath || '(root)'" disabled /></div>
        <div class="modal-actions">
          <button @click="action('start')" :disabled="app.state === 'running'">Start</button>
          <button @click="action('stop')" :disabled="app.state !== 'running'">Stop</button>
          <button @click="action('restart')">Restart</button>
          <button @click="action('status')">Status</button>
          <button @click="tailLog">Log</button>
        </div>
        <div v-if="showLog" class="log-box"><pre>{{ log }}</pre></div>
        <div class="modal-actions">
          <button class="danger" @click="remove">Hapus Aplikasi</button>
          <button class="primary" @click="save">Ubah Konfigurasi</button>
          <button @click="showModal = false">Tutup</button>
        </div>
      </template>

      <template v-else>
        <form @submit.prevent="save">
          <div class="field">
            <label>Tipe Aplikasi</label>
            <select v-model="form.app_type">
              <option v-for="t in APP_TYPES" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>

          <!-- Tab mode deploy khusus Node -->
          <div v-if="form.app_type === 'node'" class="tabs">
            <button type="button" class="tab" :class="{ active: deployMode === 'default' }" @click="deployMode = 'default'">Default Project</button>
            <button type="button" class="tab" :class="{ active: deployMode === 'pm2' }" @click="deployMode = 'pm2'">PM2 Project</button>
          </div>

          <div class="field">
            <label>Path (entry; kosong = default {{ DEFAULT_ENTRY[form.app_type] }})</label>
            <input v-model="form.entry" :placeholder="DEFAULT_ENTRY[form.app_type]" />
          </div>

          <div v-if="form.app_type === 'node'" class="field">
            <label>Nama project</label>
            <input v-model="form.name" placeholder="nama-app" />
          </div>

          <div v-if="form.app_type === 'node'" class="field">
            <label>Run opt (startup command; kosong = default)</label>
            <input v-model="form.run_opt" :placeholder="deployMode === 'pm2' ? 'npm start' : 'index.js'" />
          </div>

          <div class="field">
            <label>Port (localhost)</label>
            <input v-model.number="form.port" type="number" min="1" max="65535" required />
          </div>

          <div class="field">
            <label>User</label>
            <input v-model="form.user" placeholder="www" />
          </div>

          <div v-if="form.app_type === 'node'" class="field">
            <label>Versi Node</label>
            <select v-model="form.node_version">
              <option value="">(default)</option>
              <option v-for="v in NODE_VERSIONS" :key="v" :value="v">{{ v }}</option>
            </select>
          </div>

          <div class="field">
            <label>Remark (opsional)</label>
            <input v-model="form.remark" placeholder="Catatan" />
          </div>

          <div class="field">
            <label>Subpath proxy (kosong = root)</label>
            <input v-model="form.subpath" placeholder="/app" />
          </div>

          <div class="modal-actions">
            <button type="button" @click="showModal = false">Batal</button>
            <button class="primary" type="submit" :disabled="busy">Pasang</button>
          </div>
        </form>
      </template>
    </div>
  </div>
</template>

<style scoped>
.modal.wide { width: min(560px, 92vw); max-height: 90vh; overflow-y: auto; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tab { padding: 6px 14px; border: 1px solid #d0d7de; border-radius: 6px; background: #f6f8fa; cursor: pointer; }
.tab.active { background: #0969da; color: #fff; border-color: #0969da; }
</style>
