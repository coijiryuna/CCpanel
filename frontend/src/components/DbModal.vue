<script setup>
import { ref } from 'vue'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const emit = defineEmits(['created'])
const props = defineProps({ sites: Array })

const showModal = ref(false)
const showPw = ref(false)
const newDb = ref({ db_name: '', db_user: '', password: '', host: 'localhost', ip: '', site_id: null, db_type: 'mysql' })

function genPassword() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_'
  let s = ''
  for (let i = 0; i < 16; i++) s += chars[Math.floor(Math.random() * chars.length)]
  newDb.value.password = s
}

async function createDb() {
  const host = newDb.value.host === 'ip' ? newDb.value.ip : newDb.value.host
  const body = { db_name: newDb.value.db_name, host, site_id: newDb.value.site_id, db_type: newDb.value.db_type }
  if (newDb.value.db_user) body.db_user = newDb.value.db_user
  if (newDb.value.password) body.password = newDb.value.password
  try {
    await api.post('/api/dbs', body)
    showModal.value = false
    newDb.value = { db_name: '', db_user: '', password: '', host: 'localhost', ip: '', site_id: null, db_type: 'mysql' }
    showPw.value = false
    notify('DB dibuat')
    emit('created')
  } catch (e) { notify(e.message, false) }
}
</script>

<template>
  <button class="primary" @click="showModal = true">+ Buat DB</button>

  <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
    <form class="modal" @submit.prevent="createDb">
      <h3>Buat Database</h3>
      <div class="field">
        <label>Tipe Database</label>
        <select v-model="newDb.db_type">
          <option value="mysql">MySQL / MariaDB</option>
          <option value="postgresql">PostgreSQL</option>
          <option value="mongodb">MongoDB (Stub)</option>
          <option value="redis">Redis (Stub)</option>
        </select>
      </div>
      <div class="field">
        <label>Nama DB (a-z, 0-9, _)</label>
        <input v-model="newDb.db_name" placeholder="app_web" required />
      </div>
      <div class="field">
        <label>Username (kosong = nama DB)</label>
        <input v-model="newDb.db_user" placeholder="app_web" />
      </div>
      <div class="field">
        <label>Password</label>
        <div class="pw">
          <input :type="showPw ? 'text' : 'password'" v-model="newDb.password" placeholder="kosong = random" />
          <button type="button" @click="showPw = !showPw">{{ showPw ? 'Sembunyi' : 'Lihat' }}</button>
          <button type="button" @click="genPassword()">Generate</button>
        </div>
      </div>
      <div class="field">
        <label>Permission</label>
        <select v-model="newDb.host">
          <option value="localhost">Localhost saja</option>
          <option value="%">Semua host (%)</option>
          <option value="ip">IP tertentu</option>
        </select>
        <input v-if="newDb.host === 'ip'" v-model="newDb.ip" placeholder="1.2.3.4" />
      </div>
      <div class="field">
        <label>Site (opsional)</label>
        <select v-model="newDb.site_id">
          <option :value="null">— tanpa site —</option>
          <option v-for="s in props.sites" :key="s.id" :value="s.id">{{ s.domain }}</option>
        </select>
      </div>
      <div class="modal-actions">
        <button type="button" @click="showModal = false">Batal</button>
        <button class="primary" type="submit">Buat</button>
      </div>
    </form>
  </div>
</template>
