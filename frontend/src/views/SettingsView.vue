<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const status = ref(null)
const busy = ref(false)
const ws = ref(null)
const db = ref(null)

const ENGINES = [
  { id: 'nginx', name: 'Nginx', desc: 'Default. Cepat, ringan, konfig per-site di conf.d.' },
  { id: 'apache', name: 'Apache', desc: 'Fleksibel, .htaccess didukung penuh. Config di sites-available.' },
  { id: 'litespeed', name: 'OpenLiteSpeed', desc: 'Kompatibel .htaccess + performa tinggi. Config per-vhost.' },
]

const DB_ENGINES = [
  { id: 'mysql', name: 'MySQL / MariaDB', desc: 'Default. Relasional populer.' },
  { id: 'postgresql', name: 'PostgreSQL', desc: 'Relasional tangguh.' },
  { id: 'mongodb', name: 'MongoDB', desc: 'NoSQL dokumen. (Stub)' },
  { id: 'redis', name: 'Redis', desc: 'In-memory key-value. (Stub)' },
]

async function refresh() {
  status.value = await api.get('/api/cron/status')
  ws.value = await api.get('/api/settings/webserver')
  db.value = await api.get('/api/settings/database')
}

async function setEngine(engine) {
  if (!confirm(`Ganti web server ke ${engine.name}? Site baru pakai engine ini. Site lama tetap di engine aslinya.`)) return
  busy.value = true
  try {
    await api.post('/api/settings/webserver', { engine: engine.id })
    notify(`Web server: ${engine.name}`)
    ws.value = await api.get('/api/settings/webserver')
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function setDbEngine(engine) {
  if (!confirm(`Ganti database default ke ${engine.name}? DB baru pakai engine ini.`)) return
  busy.value = true
  try {
    await api.post('/api/settings/database', { engine: engine.id })
    notify(`Database: ${engine.name}`)
    db.value = await api.get('/api/settings/database')
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function install() {
  if (!confirm('Pasang auto-renew SSL? Cron tiap hari 03:00, jalan certbot renew + reload nginx.')) return
  busy.value = true
  try {
    await api.post('/api/cron/install')
    notify('Auto-renew SSL terpasang')
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

async function uninstall() {
  if (!confirm('Hapus auto-renew SSL? Cron + script akan dihapus.')) return
  busy.value = true
  try {
    await api.post('/api/cron/uninstall')
    notify('Auto-renew SSL dihapus')
    await refresh()
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Settings</h3>
      <button @click="refresh" :disabled="busy">Segarkan</button>
    </div>

    <div class="card">
      <h4>Web Server</h4>
      <p class="muted">Engine untuk site baru. Site yang sudah ada tetap di engine aslinya sampai dihapus/restore.</p>
      <div v-for="e in ENGINES" :key="e.id" class="engine-row">
        <div>
          <strong>{{ e.name }}</strong>
          <span class="muted"> — {{ e.desc }}</span>
        </div>
        <button
          class="primary"
          :disabled="busy || ws?.engine === e.id"
          @click="setEngine(e)"
        >{{ ws?.engine === e.id ? 'Aktif' : 'Gunakan' }}</button>
      </div>
    </div>

    <div class="card">
      <h4>Database Default</h4>
      <p class="muted">Tipe database default untuk DB baru.</p>
      <div v-for="e in DB_ENGINES" :key="e.id" class="engine-row">
        <div>
          <strong>{{ e.name }}</strong>
          <span class="muted"> — {{ e.desc }}</span>
        </div>
        <button
          class="primary"
          :disabled="busy || db?.engine === e.id"
          @click="setDbEngine(e)"
        >{{ db?.engine === e.id ? 'Aktif' : 'Gunakan' }}</button>
      </div>
    </div>

    <div class="card">
      <h4>Auto-renew SSL</h4>
      <p class="muted">Jalankan <code>certbot renew</code> setiap hari 03:00 via crontab root. Sertifikat mendekati expiry (30 hari) di-renew otomatis, nginx di-reload, hasil dicatat ke <code>data/ssl-renew.log</code>.</p>
      <p v-if="status">
        Status: <span class="badge" :class="status.installed ? 'on' : 'off'">{{ status.installed ? 'Terpasang' : 'Belum terpasang' }}</span>
        <span v-if="status.script" class="muted"> — {{ status.script }}</span>
      </p>
      <div class="actions">
        <button class="primary" @click="install" :disabled="busy || (status && status.installed)">Pasang</button>
        <button class="danger" @click="uninstall" :disabled="busy || !(status && status.installed)">Hapus</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.engine-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border, #e5e7eb);
}
.engine-row:last-child { border-bottom: none; }
</style>
