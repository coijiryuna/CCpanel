<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const accounts = ref([])
const sites = ref([])
const showModal = ref(false)
const showPw = ref(false)
const newAcc = ref({ username: '', password: '', site_id: null })

function genPassword() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_'
  let s = ''
  for (let i = 0; i < 16; i++) s += chars[Math.floor(Math.random() * chars.length)]
  newAcc.value.password = s
}

async function refresh() {
  try {
    const [a, s] = await Promise.all([api.get('/api/ftp'), api.get('/api/sites')])
    accounts.value = a
    sites.value = s
    if (!newAcc.value.site_id && s.length) newAcc.value.site_id = s[0].id
  } catch (e) { notify(e.message, false) }
}

async function createAcc() {
  const body = { username: newAcc.value.username, site_id: newAcc.value.site_id }
  if (newAcc.value.password) body.password = newAcc.value.password
  try {
    const r = await api.post('/api/ftp', body)
    notify(`Akun FTP dibuat: ${r.username}`)
    showModal.value = false
    newAcc.value = { username: '', password: '', site_id: null }
    showPw.value = false
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function resetPw(acc) {
  if (!confirm(`Reset password untuk ${acc.username}?`)) return
  try {
    const r = await api.post(`/api/ftp/${acc.id}/reset-password`)
    acc.password = r.password
    notify('Password direset')
  } catch (e) { notify(e.message, false) }
}

async function del(acc) {
  if (!confirm(`Hapus akun FTP ${acc.username}?`)) return
  try {
    await api.delete(`/api/ftp/${acc.id}`)
    notify('Akun FTP dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

function siteName(acc) {
  return acc.site_domain || '—'
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>FTP</h3>
      <button @click="refresh">Segarkan</button>
    </div>

    <div class="card" v-if="sites.length">
      <h4>Buat akun FTP</h4>
      <div class="field">
        <label>Site</label>
        <select v-model="newAcc.site_id" required>
          <option v-for="s in sites" :key="s.id" :value="s.id">{{ s.domain }}</option>
        </select>
      </div>
      <div class="field">
        <label>Username (a-z, 0-9, _)</label>
        <input v-model="newAcc.username" placeholder="ftp_user" required />
      </div>
      <div class="field">
        <label>Password</label>
        <div class="pw">
          <input :type="showPw ? 'text' : 'password'" v-model="newAcc.password" placeholder="kosong = random" />
          <button type="button" @click="showPw = !showPw">{{ showPw ? 'Sembunyi' : 'Lihat' }}</button>
          <button type="button" @click="genPassword()">Generate</button>
        </div>
      </div>
      <div class="modal-actions">
        <button class="primary" @click="createAcc">Buat</button>
      </div>
    </div>
    <p v-else class="muted">Belum ada site — buat site dulu untuk akun FTP.</p>

    <h4 style="margin: 18px 0 10px">Daftar akun</h4>
    <table>
      <thead><tr><th>Username</th><th>Site</th><th>Password</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="a in accounts" :key="a.id">
          <td>{{ a.username }}</td>
          <td>{{ siteName(a) }}</td>
          <td>
            <span class="pw">
              <input :type="a.show ? 'text' : 'password'" :value="a.password" readonly />
              <button type="button" @click="a.show = !a.show">{{ a.show ? 'Sembunyi' : 'Lihat' }}</button>
            </span>
          </td>
          <td>
            <button @click="resetPw(a)">Reset Password</button>
            <button class="danger" @click="del(a)">Hapus</button>
          </td>
        </tr>
        <tr v-if="!accounts.length"><td colspan="4" class="empty">Belum ada akun FTP</td></tr>
      </tbody>
    </table>
  </section>
</template>
