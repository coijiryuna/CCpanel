<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const route = useRoute()
const router = useRouter()

const ROOT_OPTIONS = [
  { key: 'wwwroot', label: 'WWW Root (/www/wwwroot)' },
  { key: 'project', label: 'Project Root (/www/project)' },
]
const selectedRoot = ref(route.params.rootKey || 'wwwroot')
const filePath = ref(route.query.path || '')
const files = ref([])
const loading = ref(false)

const showMkdir = ref(false)
const newFolderName = ref('')
const editor = ref(null)
const editorBusy = ref(false)
const chmodTarget = ref(null)
const chownTarget = ref(null)
const renameTarget = ref(null)
const busy = ref(false)

function notifyErr(e) { notify(e.message, false) }

async function loadFiles() {
  loading.value = true
  try {
    files.value = await api.get(`/api/files/${selectedRoot.value}`, { params: { path: filePath.value } })
  } catch (e) { notifyErr(e) } finally { loading.value = false }
}

function changeRoot(key) {
  selectedRoot.value = key
  filePath.value = ''
  router.replace({ name: 'files-generic', params: { rootKey: key } })
  loadFiles()
}

async function enterDir(entry) {
  if (!entry.is_dir) return
  filePath.value = filePath.value ? `${filePath.value}/${entry.name}` : entry.name
  await loadFiles()
}

function goUp() {
  const parts = filePath.value.split('/').filter(Boolean)
  parts.pop()
  filePath.value = parts.join('/')
  loadFiles()
}

async function uploadFile(e) {
  const file = e.target.files[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    await api.post(`/api/files/${selectedRoot.value}`, fd, {
      params: { path: filePath.value },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    notify('File diupload')
    await loadFiles()
  } catch (e) { notifyErr(e) }
  e.target.value = ''
}

async function deleteFile(entry) {
  if (!confirm(`Hapus ${entry.name}?`)) return
  try {
    await api.delete(`/api/files/${selectedRoot.value}`, { params: { path: entry.path } })
    notify('Dihapus')
    await loadFiles()
  } catch (e) { notifyErr(e) }
}

async function createFolder() {
  busy.value = true
  try {
    await api.post(`/api/files/${selectedRoot.value}/mkdir`, { path: filePath.value, name: newFolderName.value })
    newFolderName.value = ''
    showMkdir.value = false
    notify('Folder dibuat')
    await loadFiles()
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function openEditor(entry) {
  try {
    const r = await api.get(`/api/files/${selectedRoot.value}/content`, { params: { path: entry.path } })
    editor.value = { path: entry.path, name: entry.name, content: r.content }
  } catch (e) { notifyErr(e) }
}

async function saveEditor() {
  editorBusy.value = true
  try {
    await api.put(`/api/files/${selectedRoot.value}/content`, {
      path: editor.value.path,
      content: editor.value.content,
    })
    notify('File disimpan')
    editor.value = null
    await loadFiles()
  } catch (e) { notifyErr(e) } finally { editorBusy.value = false }
}

async function extractFile(entry) {
  if (!confirm(`Ekstrak ${entry.name} ke folder saat ini?`)) return
  try {
    await api.post(`/api/files/${selectedRoot.value}/extract`, null, { params: { path: entry.path } })
    notify('Diekstrak')
    await loadFiles()
  } catch (e) { notifyErr(e) }
}

async function saveChmod() {
  busy.value = true
  try {
    await api.post(`/api/files/${selectedRoot.value}/chmod`, { path: chmodTarget.value.path, mode: chmodTarget.value.mode })
    chmodTarget.value = null
    notify('chmod OK')
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function saveChown() {
  busy.value = true
  try {
    await api.post(`/api/files/${selectedRoot.value}/chown`, { path: chownTarget.value.path, owner: chownTarget.value.owner })
    chownTarget.value = null
    notify('chown OK')
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function saveRename() {
  busy.value = true
  try {
    await api.post(`/api/files/${selectedRoot.value}/rename`, { path: renameTarget.value.path, new_name: renameTarget.value.newName })
    renameTarget.value = null
    notify('Direname')
    await loadFiles()
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function download(entry) {
  try {
    const blob = await api.blob(`/api/files/${selectedRoot.value}/download`, { params: { path: entry.path } })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = entry.is_dir ? `${entry.name}.zip` : entry.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { notifyErr(e) }
}

function formatSize(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

onMounted(loadFiles)
</script>

<template>
  <section>
    <div class="head">
      <h3>File Manager (Generic)</h3>
      <div class="fm-root-select">
        <label>Root:</label>
        <select v-model="selectedRoot" @change="changeRoot(selectedRoot)">
          <option v-for="r in ROOT_OPTIONS" :key="r.key" :value="r.key">{{ r.label }}</option>
        </select>
      </div>
    </div>

    <div class="fm-toolbar">
      <span class="fm-path">
        <a @click="filePath = ''; loadFiles()">{{ selectedRoot === 'wwwroot' ? 'wwwroot' : 'project' }}</a>
        <template v-for="(part, i) in filePath.split('/').filter(Boolean)" :key="i">
          <span>/</span>
          <a @click="filePath = filePath.split('/').filter(Boolean).slice(0, i + 1).join('/'); loadFiles()">{{ part }}</a>
        </template>
      </span>
      <span class="fm-spacer"></span>
      <button @click="goUp" :disabled="!filePath">⬆ Naik</button>
      <label class="upload-btn">
        Upload
        <input type="file" @change="uploadFile" hidden />
      </label>
      <button class="primary" @click="showMkdir = true">+ Folder</button>
    </div>

    <div v-if="editor" class="fm-editor">
      <h4>Edit: {{ editor.name }}</h4>
      <textarea v-model="editor.content" rows="28" spellcheck="false"></textarea>
      <div class="fm-editor-actions">
        <button @click="editor = null">Batal</button>
        <button class="primary" @click="saveEditor" :disabled="editorBusy">Simpan</button>
      </div>
    </div>

    <table v-else>
      <thead><tr><th>Nama</th><th>Tipe</th><th>Ukuran</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="f in files" :key="f.path">
          <td><a @click="enterDir(f)">{{ f.name }}{{ f.is_dir ? '/' : '' }}</a></td>
          <td>{{ f.is_dir ? 'folder' : 'file' }}</td>
          <td>{{ formatSize(f.size) }}</td>
          <td class="actions">
            <template v-if="!f.is_dir">
              <button @click="openEditor(f)">Edit</button>
              <button v-if="/\.(zip|tar|tar\.gz|tgz|tar\.bz2|tbz2|tar\.xz|txz)$/i.test(f.name)" @click="extractFile(f)">Extract</button>
            </template>
            <button @click="renameTarget = { path: f.path, name: f.name, newName: f.name }">Rename</button>
            <button @click="chmodTarget = { path: f.path, name: f.name, mode: '755' }">chmod</button>
            <button @click="chownTarget = { path: f.path, name: f.name, owner: '' }">chown</button>
            <button @click="download(f)">Download</button>
            <button class="danger" @click="deleteFile(f)">Hapus</button>
          </td>
        </tr>
        <tr v-if="!files.length"><td colspan="4" class="empty">Folder kosong</td></tr>
      </tbody>
    </table>

    <!-- Modal mkdir -->
    <div v-if="showMkdir" class="modal-backdrop" @click.self="showMkdir = false">
      <form class="modal" @submit.prevent="createFolder">
        <h3>Buat Folder Baru</h3>
        <div class="field">
          <label>Nama folder</label>
          <input v-model="newFolderName" required autofocus />
        </div>
        <div class="modal-actions">
          <button type="button" @click="showMkdir = false">Batal</button>
          <button class="primary" type="submit" :disabled="busy">Buat</button>
        </div>
      </form>
    </div>

    <!-- Modal rename -->
    <div v-if="renameTarget" class="modal-backdrop" @click.self="renameTarget = null">
      <form class="modal" @submit.prevent="saveRename">
        <h3>Rename: {{ renameTarget.name }}</h3>
        <div class="field">
          <label>Nama baru</label>
          <input v-model="renameTarget.newName" required autofocus />
        </div>
        <div class="modal-actions">
          <button type="button" @click="renameTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">Rename</button>
        </div>
      </form>
    </div>

    <!-- Modal chmod -->
    <div v-if="chmodTarget" class="modal-backdrop" @click.self="chmodTarget = null">
      <form class="modal" @submit.prevent="saveChmod">
        <h3>chmod: {{ chmodTarget.name }}</h3>
        <div class="field">
          <label>Mode (oktal, cth: 755, 0644)</label>
          <input v-model="chmodTarget.mode" required autofocus />
        </div>
        <div class="modal-actions">
          <button type="button" @click="chmodTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">OK</button>
        </div>
      </form>
    </div>

    <!-- Modal chown -->
    <div v-if="chownTarget" class="modal-backdrop" @click.self="chownTarget = null">
      <form class="modal" @submit.prevent="saveChown">
        <h3>chown: {{ chownTarget.name }}</h3>
        <div class="field">
          <label>Owner (user, user:group, atau :group)</label>
          <input v-model="chownTarget.owner" required autofocus />
        </div>
        <div class="modal-actions">
          <button type="button" @click="chownTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">OK</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
.fm-root-select select { padding: 0.4rem; border: 1px solid #ccc; border-radius: 4px; }
.fm-toolbar { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
.fm-path { font-family: monospace; font-size: 0.9rem; color: #333; }
.fm-path a { color: #0066cc; text-decoration: none; cursor: pointer; }
.fm-path a:hover { text-decoration: underline; }
.fm-spacer { flex: 1; }
.upload-btn { cursor: pointer; }
.fm-editor { border: 1px solid #ddd; border-radius: 4px; padding: 1rem; margin-bottom: 1rem; }
.fm-editor textarea { width: 100%; font-family: monospace; font-size: 0.9rem; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
.fm-editor-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 0.5rem; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 0.5rem; text-align: left; border-bottom: 1px solid #eee; }
th { background: #f5f5f5; }
.actions { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.actions button { padding: 0.2rem 0.5rem; font-size: 0.8rem; }
.empty { text-align: center; color: #999; padding: 2rem; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: white; padding: 1.5rem; border-radius: 8px; min-width: 300px; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
.modal .field { margin-bottom: 1rem; }
.modal .field label { display: block; margin-bottom: 0.3rem; font-weight: 500; }
.modal .field input { width: 100%; padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
.modal-actions { display: flex; gap: 0.5rem; justify-content: flex-end; }
.primary { background: #0066cc; color: white; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; }
.primary:disabled { opacity: 0.6; cursor: not-allowed; }
.danger { background: #cc0000; color: white; border: none; padding: 0.2rem 0.5rem; border-radius: 4px; cursor: pointer; }
button { background: #f0f0f0; border: 1px solid #ccc; padding: 0.2rem 0.5rem; border-radius: 4px; cursor: pointer; }
button:hover { background: #e0e0e0; }
</style>