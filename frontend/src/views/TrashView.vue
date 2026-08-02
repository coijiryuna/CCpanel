<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const items = ref([])

function fmtSize(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString()
}

async function refresh() {
  items.value = await api.get('/api/trash')
}

async function restore(item) {
  if (!confirm(`Restore ${item.name}? Site akan aktif kembali di panel.`)) return
  try {
    const r = await api.post(`/api/trash/${encodeURIComponent(item.name)}/restore`)
    notify(`Site ${r.domain} direstore`)
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function purge(item) {
  if (!confirm(`Hapus PERMANEN ${item.name}? Data tidak bisa dikembalikan.`)) return
  try {
    await api.delete(`/api/trash/${encodeURIComponent(item.name)}`)
    notify('Dihapus permanen')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Trash</h3>
      <button @click="refresh">Segarkan</button>
    </div>
    <table>
      <thead><tr><th>Nama</th><th>Ukuran</th><th>Dihapus</th><th>Aksi</th></tr></thead>
      <tbody>
        <tr v-for="item in items" :key="item.name">
          <td>{{ item.name }}</td>
          <td>{{ fmtSize(item.size) }}</td>
          <td>{{ fmtTime(item.mtime) }}</td>
          <td>
            <button @click="restore(item)">Restore</button>
            <button class="danger" @click="purge(item)">Hapus Permanen</button>
          </td>
        </tr>
        <tr v-if="!items.length"><td colspan="4" class="empty">Trash kosong</td></tr>
      </tbody>
    </table>
  </section>
</template>
