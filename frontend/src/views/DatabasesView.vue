<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'
import DbModal from '../components/DbModal.vue'

const { notify } = useToast()

const dbs = ref([])
const sites = ref([])

async function refresh() {
  const [d, s] = await Promise.all([api.get('/api/dbs'), api.get('/api/sites')])
  dbs.value = d
  sites.value = s
}

async function deleteDb(db) {
  if (!confirm(`Hapus database ${db.db_name}? Data hilang permanen.`)) return
  try {
    await api.delete(`/api/dbs/${db.id}`)
    notify('DB dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function resetDbPassword(db) {
  if (!confirm(`Reset password untuk ${db.db_name}? Aplikasi yang terhubung harus diperbarui.`)) return
  try {
    const r = await api.post(`/api/dbs/${db.id}/reset-password`)
    db.db_pass = r.db_pass
    notify('Password direset')
  } catch (e) { notify(e.message, false) }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Databases</h3>
      <DbModal :sites="sites" @created="refresh" />
    </div>
    <table>
      <thead><tr><th>Nama</th><th>Tipe</th><th>User</th><th>Password</th><th>Permission</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="d in dbs" :key="d.id">
          <td>{{ d.db_name }}</td>
          <td><span class="badge on">{{ d.db_type }}</span></td>
          <td>{{ d.db_user }}@{{ d.db_host }}</td>
          <td>
            <span class="pw">
              <input :type="d.show ? 'text' : 'password'" :value="d.db_pass" readonly />
              <button type="button" @click="d.show = !d.show">{{ d.show ? 'Sembunyi' : 'Lihat' }}</button>
            </span>
          </td>
          <td>{{ d.db_host === '%' ? 'Semua (%)' : d.db_host }}</td>
          <td>
            <button @click="resetDbPassword(d)">Reset Password</button>
            <button class="danger" @click="deleteDb(d)">Hapus</button>
          </td>
        </tr>
        <tr v-if="!dbs.length"><td colspan="6" class="empty">Belum ada database</td></tr>
      </tbody>
    </table>
  </section>
</template>
