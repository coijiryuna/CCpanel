<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const route = useRoute()
const router = useRouter()

const sites = ref([])
const fileSite = ref(null) // site aktif
const filePath = ref('')
const files = ref([])
const loading = ref(false)

// modal kecil (aksi per-item tetap pakai modal — container utama full page)
const showMkdir = ref(false)
const newFolderName = ref('')
const editor = ref(null) // { path, name, content } — inline besar
const editorBusy = ref(false)
const chmodTarget = ref(null)
const chownTarget = ref(null)
const renameTarget = ref(null)
const busy = ref(false)

const selectedSiteId = computed({
  get: () => fileSite.value?.id ?? null,
  set: (v) => { if (v) openSite(v) },
})

function notifyErr(e) { notify(e.message, false) }

async function loadSites() {
  try {
    sites.value = await api.get('/api/sites')
    const want = Number(route.params.siteId)
    const target = sites.value.find(s => s.id === want) || sites.value[0]
    if (target) openSite(target.id)
  } catch (e) { notifyErr(e) }
}

async function loadFiles() {
  if (!fileSite.value) return
  loading.value = true
  try {
    files.value = await api.get(`/api/sites/${fileSite.value.id}/files`, { params: { path: filePath.value } })
  } catch (e) { notifyErr(e) } finally { loading.value = false }
}

function openSite(id) {
  const s = sites.value.find(x => x.id === id)
  if (!s) return
  fileSite.value = s
  filePath.value = ''
  router.replace({ name: 'files', params: { siteId: id } })
  loadFiles()
}

function switchSite() {
  openSite(selectedSiteId.value)
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
    await api.post(`/api/sites/${fileSite.value.id}/files`, fd, {
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
    await api.delete(`/api/sites/${fileSite.value.id}/files`, { params: { path: entry.path } })
    notify('Dihapus')
    await loadFiles()
  } catch (e) { notifyErr(e) }
}

async function createFolder() {
  busy.value = true
  try {
    await api.post(`/api/sites/${fileSite.value.id}/files/mkdir`, { path: filePath.value, name: newFolderName.value })
    newFolderName.value = ''
    showMkdir.value = false
    notify('Folder dibuat')
    await loadFiles()
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function openEditor(entry) {
  try {
    const r = await api.get(`/api/sites/${fileSite.value.id}/files/content`, { params: { path: entry.path } })
    editor.value = { path: entry.path, name: entry.name, content: r.content }
  } catch (e) { notifyErr(e) }
}

async function saveEditor() {
  editorBusy.value = true
  try {
    await api.put(`/api/sites/${fileSite.value.id}/files/content`, {
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
    await api.post(`/api/sites/${fileSite.value.id}/files/extract`, null, { params: { path: entry.path } })
    notify('Diekstrak')
    await loadFiles()
  } catch (e) { notifyErr(e) }
}

async function saveChmod() {
  busy.value = true
  try {
    await api.post(`/api/sites/${fileSite.value.id}/files/chmod`, { path: chmodTarget.value.path, mode: chmodTarget.value.mode })
    chmodTarget.value = null
    notify('chmod OK')
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function saveChown() {
  busy.value = true
  try {
    await api.post(`/api/sites/${fileSite.value.id}/files/chown`, { path: chownTarget.value.path, owner: chownTarget.value.owner })
    chownTarget.value = null
    notify('chown OK')
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function saveRename() {
  busy.value = true
  try {
    await api.post(`/api/sites/${fileSite.value.id}/files/rename`, { path: renameTarget.value.path, new_name: renameTarget.value.newName })
    renameTarget.value = null
    notify('Direname')
    await loadFiles()
  } catch (e) { notifyErr(e) } finally { busy.value = false }
}

async function download(entry) {
  try {
    const blob = await api.blob(`/api/sites/${fileSite.value.id}/files/download`, { params: { path: entry.path } })
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

onMounted(loadSites)
</script>

<template>
  <section>
    <div class="head">
      <h3>File Manager</h3>
      <div class="fm-site-select">
        <label>Site:</label>
        <select v-model="selectedSiteId" @change="switchSite">
          <option v-for="s in sites" :key="s.id" :value="s.id">{{ s.domain }}</option>
        </select>
      </div>
    </div>

    <template v-if="fileSite">
      <div class="fm-toolbar">
        <span class="fm-path">
          <a @click="filePath = ''; loadFiles()">{{ fileSite.domain }}</a>
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

      <!-- editor teks inline (full-width, ganti tabel) -->
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
          <tr v-if="!files.length && !loading"><td colspan="4" class="empty">Folder kosong</td></tr>
          <tr v-if="loading"><td colspan="4" class="empty">Memuat…</td></tr>
        </tbody>
      </table>
    </template>

    <div v-else class="card">
      <p>Pilih site untuk mengelola file.</p>
    </div>

    <!-- buat folder -->
    <div v-if="showMkdir" class="modal-backdrop" @click.self="showMkdir = false">
      <form class="modal" @submit.prevent="createFolder">
        <h3>Buat Folder — /{{ filePath }}</h3>
        <div class="field"><label>Nama folder</label><input v-model="newFolderName" required autofocus /></div>
        <div class="modal-actions">
          <button type="button" @click="showMkdir = false">Batal</button>
          <button class="primary" type="submit" :disabled="busy">Buat</button>
        </div>
      </form>
    </div>

    <!-- rename -->
    <div v-if="renameTarget" class="modal-backdrop" @click.self="renameTarget = null">
      <form class="modal" @submit.prevent="saveRename">
        <h3>Rename — {{ renameTarget.name }}</h3>
        <div class="field"><label>Nama baru</label><input v-model="renameTarget.newName" required autofocus /></div>
        <div class="modal-actions">
          <button type="button" @click="renameTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">Rename</button>
        </div>
      </form>
    </div>

    <!-- chmod -->
    <div v-if="chmodTarget" class="modal-backdrop" @click.self="chmodTarget = null">
      <form class="modal" @submit.prevent="saveChmod">
        <h3>chmod — {{ chmodTarget.name }}</h3>
        <div class="field"><label>Mode oktal (755, 0644)</label><input v-model="chmodTarget.mode" placeholder="755" required autofocus /></div>
        <div class="modal-actions">
          <button type="button" @click="chmodTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">chmod</button>
        </div>
      </form>
    </div>

    <!-- chown -->
    <div v-if="chownTarget" class="modal-backdrop" @click.self="chownTarget = null">
      <form class="modal" @submit.prevent="saveChown">
        <h3>chown — {{ chownTarget.name }}</h3>
        <div class="field"><label>Owner (user, user:group, atau :group)</label><input v-model="chownTarget.owner" placeholder="www-data:www-data" required autofocus /></div>
        <div class="modal-actions">
          <button type="button" @click="chownTarget = null">Batal</button>
          <button class="primary" type="submit" :disabled="busy">chown</button>
        </div>
      </form>
    </div>
  </section>
</template>
