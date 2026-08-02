<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const backups = ref([])
const sites = ref([])
const dbs = ref([])
const busy = ref(false)

async function refresh() {
  try {
    const [b, s, d] = await Promise.all([
      api.get('/api/backups'),
      api.get('/api/sites'),
      api.get('/api/dbs'),
    ])
    backups.value = b
    sites.value = s
    dbs.value = d
  } catch (e) { notify(e.message, false) }
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString()
}

function label(item) {
  return item.type === 'site' ? 'Site' : 'Database'
}

async function backupSite(site) {
  busy.value = true
  try {
    const r = await api.post(`/api/backups/site/${site.id}`)
    notify(`Backup site ${site.domain}: ${r.name}`)
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function backupDb(db) {
  busy.value = true
  try {
    const r = await api.post(`/api/backups/db/${db.id}`)
    notify(`Backup DB ${db.db_name}: ${r.name}`)
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function restore(item) {
  const isSite = item.type === 'site'
  if (!confirm(`Restore ${item.name}? ${isSite ? 'Folder akan diextract + vhost aktif (kalau belum ada).' : 'Database harus sudah ada — restore data ke DB yang sama.'}`)) return
  busy.value = true
  try {
    const r = await api.post(`/api/backups/${encodeURIComponent(item.name)}/restore`)
    notify(`Restore OK: ${isSite ? r.domain : r.db_name}`)
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function del(item) {
  if (!confirm(`Hapus backup ${item.name}?`)) return
  busy.value = true
  try {
    await api.delete(`/api/backups/${encodeURIComponent(item.name)}`)
    notify('Backup dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Backup</h3>
      <button @click="refresh" :disabled="busy">Segarkan</button>
    </div>

    <div class="card" v-if="sites.length || dbs.length">
      <h4>Buat backup</h4>
      <div class="backup-row" v-for="s in sites" :key="s.id">
        <span>Site: <b>{{ s.domain }}</b></span>
        <button class="primary" @click="backupSite(s)" :disabled="busy">Backup</button>
      </div>
      <div class="backup-row" v-for="d in dbs" :key="d.id">
        <span>DB: <b>{{ d.db_name }}</b> <span class="muted">({{ d.db_user }})</span></span>
        <button class="primary" @click="backupDb(d)" :disabled="busy">Backup</button>
      </div>
    </div>

    <h4 style="margin: 18px 0 10px">Daftar backup</h4>
    <table>
      <thead><tr><th>Nama</th><th>Tipe</th><th>Ukuran</th><th>Waktu</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="item in backups" :key="item.name">
          <td>{{ item.name }}</td>
          <td><span class="badge" :class="item.type === 'site' ? 'on' : 'off'">{{ label(item) }}</span></td>
          <td>{{ fmtSize(item.size) }}</td>
          <td class="muted">{{ fmtTime(item.mtime) }}</td>
          <td class="actions">
            <button @click="restore(item)" :disabled="busy">Restore</button>
            <button class="danger" @click="del(item)" :disabled="busy">Hapus</button>
          </td>
        </tr>
        <tr v-if="!backups.length"><td colspan="5" class="empty">Belum ada backup</td></tr>
      </tbody>
    </table>
  </section>
</template>
