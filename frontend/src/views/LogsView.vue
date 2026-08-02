<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const logs = ref([])
const limit = ref(100)

async function refresh() {
  try {
    logs.value = await api.get('/api/logs', { params: { limit: limit.value } })
  } catch (e) { notify(e.message, false) }
}

function fmtTime(ts) {
  return new Date(ts).toLocaleString()
}

const ACTION_LABEL = {
  'login': 'Login',
  'site.create': 'Buat site',
  'site.delete': 'Hapus site',
  'site.enable': 'Enable site',
  'site.disable': 'Disable site',
  'ssl.install': 'Pasang SSL',
  'ssl.renew': 'Renew SSL',
  'db.create': 'Buat DB',
  'db.delete': 'Hapus DB',
  'db.reset-password': 'Reset password DB',
  'trash.restore': 'Restore trash',
  'trash.purge': 'Hapus permanen',
  'cron.install': 'Pasang cron',
  'cron.uninstall': 'Hapus cron',
}

function label(action) {
  return ACTION_LABEL[action] || action
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Log Aktivitas</h3>
      <div class="fm-toolbar">
        <select v-model.number="limit" @change="refresh">
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
        </select>
        <button @click="refresh">Segarkan</button>
      </div>
    </div>
    <table>
      <thead><tr><th>Waktu</th><th>User</th><th>Aksi</th><th>Detail</th></tr></thead>
      <tbody>
        <tr v-for="l in logs" :key="l.id">
          <td class="muted">{{ fmtTime(l.ts) }}</td>
          <td>{{ l.user }}</td>
          <td>{{ label(l.action) }}</td>
          <td class="muted">{{ l.detail }}</td>
        </tr>
        <tr v-if="!logs.length"><td colspan="4" class="empty">Belum ada log</td></tr>
      </tbody>
    </table>
  </section>
</template>
