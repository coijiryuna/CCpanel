<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const router = useRouter()

const APP_TYPES = ['node', 'python', 'go', 'docker']
const DEFAULT_ENTRY = { node: 'index.js', python: 'app:app', go: 'app', docker: 'docker-compose.yml' }
const activeTab = ref('node')
const projects = ref([])
const nodeVersions = ref([])
const showAdd = ref(false)
const editId = ref(null)
const logFor = ref(null) // { name, text }
const domainFor = ref(null) // { project, domain }
const busy = ref(false)

const form = ref({
  name: '', app_type: 'node', port: 8000, entry: '', run_opt: '',
  user: 'www', node_version: '', pm2: false, remark: '', domain: '',
  root_path: '',
})

const visibleProjects = computed(() => projects.value.filter(p => p.app_type === activeTab.value))

onMounted(async () => {
  await refresh()
  try {
    const r = await api.get('/api/node/versions')
    nodeVersions.value = r.versions || []
  } catch { nodeVersions.value = [] }
})

async function refresh() {
  try {
    projects.value = await api.get('/api/projects')
  } catch (e) { notify(e.message, false) }
}

function resetForm() {
  form.value = {
    name: '', app_type: activeTab.value, port: 8000, entry: '', run_opt: '',
    user: 'www', node_version: '', pm2: false, remark: '', domain: '',
  }
}

function openAdd() {
  resetForm()
  editId.value = null
  showAdd.value = true
}

function openEdit(p) {
  editId.value = p.id
  form.value = {
    name: p.name, app_type: p.app_type, port: p.port, entry: p.entry || '',
    run_opt: p.run_opt || '', user: p.user || 'www', node_version: p.node_version || '',
    pm2: !!p.pm2, remark: p.remark || '', domain: p.domain || '',
  }
  showAdd.value = true
}

function openFileManager(p) {
  // Determine which root to use based on the project's root_path
  const rootPath = p.root_path || ''
  let rootKey = 'project'
  let relativePath = ''

  if (rootPath.startsWith('/www/wwwroot/') || rootPath.startsWith('/www/wwwroot')) {
    rootKey = 'wwwroot'
    // Extract relative path from WWW_ROOT
    const wwwRoot = '/www/wwwroot'
    if (rootPath.startsWith(wwwRoot + '/')) {
      relativePath = rootPath.slice(wwwRoot.length + 1)
    }
  } else if (rootPath.startsWith('/www/project/') || rootPath.startsWith('/www/project')) {
    // Extract relative path from PROJECT_ROOT
    const projectRoot = '/www/project'
    if (rootPath.startsWith(projectRoot + '/')) {
      relativePath = rootPath.slice(projectRoot.length + 1)
    }
  } else {
    // For custom paths (like /tmp/ccp-demo/project/...), try to extract relative to PROJECT_ROOT
    const projectRoot = '/www/project'
    if (rootPath.startsWith(projectRoot + '/')) {
      relativePath = rootPath.slice(projectRoot.length + 1)
    } else {
      // Fallback: use the last path component
      relativePath = rootPath.split('/').pop() || ''
    }
  }

  router.push({ name: 'files-generic', params: { rootKey }, query: { path: relativePath } })
}

async function save() {
  busy.value = true
  try {
    const isNode = form.value.app_type === 'node'
    const payload = {
      app_type: form.value.app_type,
      port: Number(form.value.port),
      entry: form.value.entry || DEFAULT_ENTRY[form.value.app_type],
      run_opt: isNode ? form.value.run_opt : '',
      user: form.value.user || 'www',
      node_version: isNode ? form.value.node_version : '',
      pm2: isNode && form.value.pm2,
      remark: form.value.remark,
    }
    if (editId.value) {
      await api.put(`/api/projects/${editId.value}`, payload)
      notify('Project diupdate')
    } else {
      payload.name = form.value.name
      payload.domain = form.value.domain
      if (form.value.root_path) {
        payload.root_path = form.value.root_path
      }
      await api.post('/api/projects', payload)
      notify('Project ditambahkan')
    }
    showAdd.value = false
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function action(p, a) {
  try {
    const r = await api.post(`/api/projects/${p.id}/action`, { action: a })
    p.state = r.state
    p.pid = r.pid
    notify(`Project ${a}`)
  } catch (e) { notify(e.message, false) }
}

async function remove(p) {
  if (!confirm(`Hapus project ${p.name}? Unit dihentikan (folder project tetap ada).`)) return
  try {
    await api.delete(`/api/projects/${p.id}`)
    notify('Project dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function tailLog(p) {
  try {
    const r = await api.get(`/api/projects/${p.id}/log`)
    logFor.value = { name: p.name, text: r.log }
  } catch (e) { notify(e.message, false) }
}

function openDomain(p) {
  domainFor.value = { project: p, domain: '' }
}

async function saveDomain() {
  const d = domainFor.value
  busy.value = true
  try {
    const r = await api.post(`/api/projects/${d.project.id}/domain`, { domain: d.domain })
    notify(`Domain ${r.domain} terpasang`)
    domainFor.value = null
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function detachDomain(p) {
  if (!confirm(`Lepas domain ${p.domain} dari project ${p.name}? Vhost proxy dihapus.`)) return
  try {
    await api.delete(`/api/projects/${p.id}/domain`)
    notify('Domain dilepas')
    await refresh()
  } catch (e) { notify(e.message, false) }
}
</script>

<template>
  <section>
    <div class="head">
      <h3>Projects <span class="dim">— backend tanpa domain (localhost:port), bisa dikaitkan domain langsung</span></h3>
      <button class="primary" @click="openAdd">+ Tambah Project</button>
    </div>

    <div class="tabs">
      <button v-for="t in APP_TYPES" :key="t" class="tab" :class="{ active: activeTab === t }" @click="activeTab = t">
        {{ t }}
      </button>
    </div>

    <table>
      <thead>
        <tr><th>Nama</th><th>Status</th><th>PID</th><th>Port</th><th>Root</th><th>Domain</th><th>Node</th><th>Remark</th><th>Aksi</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in visibleProjects" :key="p.id">
          <td>{{ p.name }}</td>
          <td><span class="badge" :class="p.state === 'running' ? 'on' : 'off'">{{ p.state }}</span></td>
          <td class="dim">{{ p.pid || '—' }}</td>
          <td><span class="badge" :class="p.domain ? 'on' : ''">{{ p.port }}</span></td>
          <td class="dim" :title="p.root_path">{{ p.root_path }}</td>
          <td>
            <span v-if="p.domain" class="alias" :title="'Klik untuk lepas ' + p.domain" @click="detachDomain(p)">{{ p.domain }}</span>
            <button v-else class="link" @click="openDomain(p)">+ domain</button>
          </td>
          <td class="dim">{{ p.node_version || '—' }}</td>
          <td class="dim">{{ p.remark || '—' }}</td>
          <td class="actions">
            <button @click="action(p, 'start')" :disabled="p.state === 'running'">Start</button>
            <button @click="action(p, 'stop')" :disabled="p.state !== 'running'">Stop</button>
            <button @click="action(p, 'restart')">Restart</button>
            <button @click="tailLog(p)">Log</button>
            <button @click="openFileManager(p)">📁 FileManager</button>
            <button @click="openEdit(p)">Ubah</button>
            <button class="danger" @click="remove(p)">Hapus</button>
          </td>
        </tr>
        <tr v-if="!visibleProjects.length"><td colspan="9" class="empty">Tidak ada project {{ activeTab }} — klik "+ Tambah Project"</td></tr>
      </tbody>
    </table>

    <!-- Tambah/Ubah -->
    <div v-if="showAdd" class="modal-backdrop" @click.self="showAdd = false">
      <form class="modal" @submit.prevent="save">
        <h3>{{ editId ? 'Ubah Project — ' + form.name : 'Tambah Project' }}</h3>
        <div class="field">
          <label>Tipe</label>
          <select v-model="form.app_type" :disabled="!!editId">
            <option v-for="t in APP_TYPES" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div v-if="!editId" class="field">
          <label>Nama project (folder di PROJECT_ROOT, unit ccpanel-proj-&lt;nama&gt;)</label>
          <input v-model="form.name" placeholder="api-gateway" required />
        </div>
        <div class="field">
          <label>Path (entry; kosong = default {{ DEFAULT_ENTRY[form.app_type] }})</label>
          <input v-model="form.entry" :placeholder="DEFAULT_ENTRY[form.app_type]" />
        </div>
        <div v-if="form.app_type === 'node'" class="field">
          <label>Run opt (startup command; kosong = default)</label>
          <input v-model="form.run_opt" placeholder="npm start" />
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
            <option v-for="v in nodeVersions" :key="v" :value="v">{{ v }}</option>
          </select>
        </div>
        <div v-if="form.app_type === 'node'" class="field">
          <label><input type="checkbox" v-model="form.pm2" /> Pakai PM2</label>
        </div>
        <div class="field">
          <label>Remark (opsional)</label>
          <input v-model="form.remark" placeholder="Catatan" />
        </div>
        <div v-if="!editId" class="field">
          <label>Root path (opsional - kosong = auto PROJECT_ROOT/&lt;nama&gt;, isi = folder existing)</label>
          <input v-model="form.root_path" placeholder="/www/wwwroot/my-project" />
        </div>
        <div v-if="!editId" class="field">
          <label>Domain langsung (opsional - kosong = backend localhost:port saja)</label>
          <input v-model="form.domain" placeholder="api.example.com" />
        </div>
        <div class="modal-actions">
          <button type="button" @click="showAdd = false">Batal</button>
          <button class="primary" type="submit" :disabled="busy">{{ editId ? 'Simpan' : 'Tambah' }}</button>
        </div>
      </form>
    </div>

    <!-- Pasang domain -->
    <div v-if="domainFor" class="modal-backdrop" @click.self="domainFor = null">
      <form class="modal" @submit.prevent="saveDomain">
        <h3>Domain - {{ domainFor.project.name }}</h3>
        <p class="dim">Vhost proxy nginx: domain → http://127.0.0.1:{{ domainFor.project.port }}. Butuh DNS A record.</p>
        <div class="field">
          <label>Domain</label>
          <input v-model="domainFor.domain" placeholder="api.example.com" required />
        </div>
        <div class="modal-actions">
          <button type="button" @click="domainFor = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">Pasang</button>
        </div>
      </form>
    </div>

    <!-- Log -->
    <div v-if="logFor" class="modal-backdrop" @click.self="logFor = null">
      <div class="modal">
        <h3>Log — {{ logFor.name }}</h3>
        <div class="log-box"><pre>{{ logFor.text }}</pre></div>
        <div class="modal-actions">
          <button class="primary" @click="logFor = null">Tutup</button>
        </div>
      </div>
    </div>
  </section>
</template>
