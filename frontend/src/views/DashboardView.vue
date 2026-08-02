<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const data = ref(null)

function fmtSize(n) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleDateString()
}

function sslBadge(exp) {
  if (!exp) return { cls: 'off', txt: 'Tanpa SSL' }
  const days = Math.ceil((new Date(exp) - new Date()) / 86400000)
  if (days < 0) return { cls: 'danger', txt: `Kadaluarsa ${-days} hari` }
  if (days < 14) return { cls: 'warn', txt: `${days} hari lagi` }
  return { cls: 'on', txt: `${days} hari lagi` }
}

async function refresh() {
  try {
    data.value = await api.get('/api/dashboard')
  } catch (e) { notify(e.message, false) }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Dashboard</h3>
      <button @click="refresh">Segarkan</button>
    </div>

    <div v-if="data" class="cards">
      <div class="card"><h4>Website</h4><p class="big">{{ data.counts.sites }}</p></div>
      <div class="card"><h4>Database</h4><p class="big">{{ data.counts.dbs }}</p></div>
      <div class="card"><h4>Akun FTP</h4><p class="big">{{ data.counts.ftp }}</p></div>
      <div class="card"><h4>Total Ukuran</h4><p class="big">{{ fmtSize(data.total_size) }}</p></div>
    </div>

    <h4 style="margin: 18px 0 10px">Status Site</h4>
    <table>
      <thead><tr><th>Domain</th><th>Status</th><th>WAF</th><th>SSL</th><th>Ukuran</th><th>Dibuat</th></tr></thead>
      <tbody>
        <tr v-for="s in data?.sites" :key="s.id">
          <td>{{ s.domain }}</td>
          <td><span class="badge" :class="s.enabled ? 'on' : 'off'">{{ s.enabled ? 'aktif' : 'nonaktif' }}</span></td>
          <td><span class="badge" :class="s.waf_enabled ? 'on' : 'off'">{{ s.waf_enabled ? 'ON' : 'OFF' }}</span></td>
          <td><span class="badge" :class="sslBadge(s.ssl_expiry).cls">{{ sslBadge(s.ssl_expiry).txt }}</span></td>
          <td>{{ fmtSize(s.size) }}</td>
          <td class="muted">{{ fmtDate(s.created_at) }}</td>
        </tr>
        <tr v-if="data && !data.sites.length"><td colspan="6" class="empty">Belum ada site</td></tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.cards .card { text-align: center; }
.cards .big { font-size: 2rem; font-weight: 700; margin: 6px 0 0; }
.badge.warn { background: #f59e0b33; color: #b45309; }
.badge.danger { background: #ef444433; color: #b91c1c; }
</style>
