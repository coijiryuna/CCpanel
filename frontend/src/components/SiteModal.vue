<script setup>
import { ref, onMounted } from 'vue'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const emit = defineEmits(['created'])

const showModal = ref(false)
const PROJECT_TYPES = ['static', 'php']
const PHP_VERSIONS = ref([])
const CATEGORIES = ['', 'Blog', 'Toko Online', 'Company Profile', 'Portofolio', 'Landing Page', 'Lainnya']
const newSite = ref({
  domain: '',
  project_type: 'static',
  port: 0,
  apply_ssl: false,
  description: '',
  category: '',
  php_version: 'static',
  create_ftp: false,
  ftp_username: '',
  create_db: false,
  db_name: '',
  db_user: '',
  db_pass: '',
})
const busy = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const r = await api.get('/api/php/versions')
    PHP_VERSIONS.value = r.versions || []
  } catch { PHP_VERSIONS.value = [] }
})

function open() {
  error.value = ''
  showModal.value = true
}

function close() {
  showModal.value = false
  newSite.value = {
    domain: '', project_type: 'static', port: 0,
    apply_ssl: false, description: '', category: '', php_version: 'static',
    create_ftp: false, ftp_username: '', create_db: false, db_name: '', db_user: '', db_pass: '',
  }
}

async function createSite() {
  busy.value = true
  error.value = ''
  try {
    // textarea multi-line: baris pertama = domain utama, sisanya = alias
    const lines = newSite.value.domain.split('\n').map(s => s.trim()).filter(Boolean)
    if (!lines.length) throw new Error('Domain wajib diisi')
    const domain = lines[0]
    const extra = lines.slice(1)
    await api.post('/api/sites', {
      domain,
      project_type: newSite.value.project_type,
      port: Number(newSite.value.port) || 0,
      extra_domains: extra,
      apply_ssl: newSite.value.apply_ssl,
      description: newSite.value.description,
      category: newSite.value.category,
      php_version: newSite.value.php_version,
      create_ftp: newSite.value.create_ftp,
      ftp_username: newSite.value.ftp_username,
      create_db: newSite.value.create_db,
      db_name: newSite.value.db_name,
      db_user: newSite.value.db_user,
      db_pass: newSite.value.db_pass,
    })
    close()
    notify('Site dibuat')
    emit('created')
  } catch (e) {
    error.value = e.message || 'Gagal membuat site'
  } finally { busy.value = false }
}
function onTypeChange() {
  if (newSite.value.project_type !== 'php') newSite.value.php_version = 'static'
}
const isPhp = () => newSite.value.project_type === 'php'
</script>

<template>
  <button class="primary" @click="open">+ Buat Site</button>

  <div v-if="showModal" class="modal-backdrop" @click.self="close">
    <form class="modal wide" @submit.prevent="createSite">
      <h3>Buat Website</h3>

      <div class="field">
        <label>Domain (satu per baris; baris pertama = domain utama)</label>
        <textarea v-model="newSite.domain" rows="3" placeholder="example.com&#10;www.example.com" required></textarea>
      </div>

      <div class="field">
        <label>Tipe Proyek</label>
        <select v-model="newSite.project_type" @change="onTypeChange">
          <option v-for="t in PROJECT_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
      </div>

      <div v-if="isPhp()" class="field">
        <label>Versi PHP</label>
        <select v-model="newSite.php_version">
          <option v-for="v in PHP_VERSIONS" :key="v" :value="v">{{ v }}</option>
        </select>
      </div>

      <div class="field">
        <label>Port (0 = tanpa port; isi untuk proxy project)</label>
        <input v-model.number="newSite.port" type="number" min="0" max="65535" />
      </div>

      <div class="field">
        <label>Deskripsi (opsional)</label>
        <input v-model="newSite.description" placeholder="Catatan singkat tentang situs" />
      </div>

      <div class="field">
        <label>Kategori</label>
        <select v-model="newSite.category">
          <option v-for="c in CATEGORIES" :key="c" :value="c">{{ c || '— Tanpa kategori —' }}</option>
        </select>
      </div>

      <label class="check">
        <input type="checkbox" v-model="newSite.apply_ssl" /> Apply for SSL (certbot)
      </label>

      <div class="field">
        <label>FTP</label>
        <select v-model="newSite.create_ftp">
          <option :value="false">Not create</option>
          <option :value="true">Create FTP account</option>
        </select>
        <input v-if="newSite.create_ftp" v-model="newSite.ftp_username"
               placeholder="Username FTP (kosong = dari domain)" />
      </div>

      <div class="field">
        <label>Database</label>
        <select v-model="newSite.create_db">
          <option :value="false">Not create</option>
          <option :value="true">Create MySQL database</option>
        </select>
        <div v-if="newSite.create_db" class="db-fields">
          <input v-model="newSite.db_name" placeholder="Nama DB (kosong = dari domain)" />
          <input v-model="newSite.db_user" placeholder="User DB (kosong = nama DB)" />
          <input v-model="newSite.db_pass" placeholder="Password (kosong = acak)" />
        </div>
      </div>

      <p v-if="error" class="form-error">{{ error }}</p>

      <div class="modal-actions">
        <button type="button" @click="close">Batal</button>
        <button class="primary" type="submit" :disabled="busy">Buat</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.modal.wide { width: min(620px, 92vw); max-height: 90vh; overflow-y: auto; }
.field { margin-bottom: 12px; }
.field textarea { width: 100%; font-family: inherit; padding: 8px; border: 1px solid #d0d7de; border-radius: 6px; }
.db-fields { display: grid; gap: 8px; margin-top: 8px; }
.db-fields input { width: 100%; }
.check { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
.form-error { color: #d1242f; margin: 8px 0; }
</style>
