<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const users = ref([])
const showModal = ref(false)
const showPw = ref(false)
const newUser = ref({ username: '', password: '', role: 'client' })

function genPassword() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_'
  let s = ''
  for (let i = 0; i < 16; i++) s += chars[Math.floor(Math.random() * chars.length)]
  newUser.value.password = s
}

async function refresh() {
  try {
    users.value = await api.get('/api/users')
  } catch (e) { notify(e.message, false) }
}

async function createUser() {
  try {
    const r = await api.post('/api/users', { ...newUser.value })
    notify(`User ${r.username} dibuat`)
    showModal.value = false
    newUser.value = { username: '', password: '', role: 'client' }
    showPw.value = false
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function resetPw(u) {
  if (!confirm(`Reset password untuk ${u.username}?`)) return
  try {
    const r = await api.post(`/api/users/${u.id}/reset-password`)
    notify(`Password baru ${u.username}: ${r.password}`)
  } catch (e) { notify(e.message, false) }
}

async function del(u) {
  if (!confirm(`Hapus user ${u.username}? Site miliknya jadi tak bertuan.`)) return
  try {
    await api.delete(`/api/users/${u.id}`)
    notify('User dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Users</h3>
      <button class="primary" @click="showModal = true">+ Buat User</button>
    </div>
    <table>
      <thead><tr><th>Username</th><th>Role</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}</td>
          <td><span class="badge" :class="u.role === 'admin' ? 'on' : 'off'">{{ u.role }}</span></td>
          <td>
            <button @click="resetPw(u)">Reset Password</button>
            <button class="danger" @click="del(u)" :disabled="u.username === 'admin'">Hapus</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
      <form class="modal" @submit.prevent="createUser">
        <h3>Buat User</h3>
        <div class="field">
          <label>Username (a-z, 0-9, _)</label>
          <input v-model="newUser.username" required />
        </div>
        <div class="field">
          <label>Role</label>
          <select v-model="newUser.role">
            <option value="client">Client</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div class="field">
          <label>Password</label>
          <div class="pw">
            <input :type="showPw ? 'text' : 'password'" v-model="newUser.password" placeholder="min 6 char" required />
            <button type="button" @click="showPw = !showPw">{{ showPw ? 'Sembunyi' : 'Lihat' }}</button>
            <button type="button" @click="genPassword()">Generate</button>
          </div>
        </div>
        <div class="modal-actions">
          <button type="button" @click="showModal = false">Batal</button>
          <button class="primary" type="submit">Buat</button>
        </div>
      </form>
    </div>
  </section>
</template>
