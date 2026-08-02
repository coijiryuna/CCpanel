<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'
import SiteModal from '../components/SiteModal.vue'
import AppManager from '../components/AppManager.vue'
import VhostEditor from '../components/VhostEditor.vue'

const { notify } = useToast()
const router = useRouter()

const PROJECT_TABS = ['static', 'php', 'node', 'python', 'go', 'docker']
const activeTab = ref('static')

const sites = ref([])
const appm = ref(null) // ref ke AppManager untuk kelola aplikasi
const vhe = ref(null) // ref ke VhostEditor untuk edit config

function openFiles(site) {
  router.push({ name: 'files', params: { siteId: site.id } })
}

const visibleSites = computed(() => sites.value.filter(s => s.project_type === activeTab.value))

// modal inline (browser headless tidak dukung window.prompt)
const portModal = ref(null) // { site, port }
const domainModal = ref(null) // { site, domain }
const portBusy = ref(false)
const domainBusy = ref(false)

async function refresh() {
  sites.value = await api.get('/api/sites')
}

async function siteAction(site, action) {
  try {
    if (action === 'delete') {
      if (!confirm(`Hapus ${site.domain}? Folder dipindah ke trash (bukan permanen).`)) return
      await api.delete(`/api/sites/${site.id}`)
    } else if (action === 'enable' || action === 'disable') {
      await api.post(`/api/sites/${site.id}/${action}`)
    } else if (action === 'waf') {
      await api.post(`/api/sites/${site.id}/waf`)
    } else if (action === 'ssl') {
      if (!confirm(`Pasang SSL untuk ${site.domain}? Butuh DNS A record.`)) return
      await api.post(`/api/sites/${site.id}/ssl`)
    }
    notify('OK')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

const PHP_VERSIONS = ['static', 'php8.1', 'php8.2', 'php8.3']

async function changePhp(site, version) {
  try {
    await api.put(`/api/sites/${site.id}/php`, { php_version: version })
    notify('PHP version diubah')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function toggleProxy(site) {
  try {
    await api.post(`/api/sites/${site.id}/proxy`, { enabled: !site.proxy_enabled })
    notify(site.proxy_enabled ? 'Proxy OFF' : 'Proxy ON')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

async function setPort(site) {
  portModal.value = { site, port: site.port || 8000 }
}

async function savePort() {
  const m = portModal.value
  portBusy.value = true
  try {
    await api.put(`/api/sites/${m.site.id}/port`, { port: Number(m.port) })
    notify('Port diupdate')
    portModal.value = null
    await refresh()
  } catch (e) { notify(e.message, false) } finally { portBusy.value = false }
}

function addDomain(site) {
  domainModal.value = { site, domain: '' }
}

async function saveDomain() {
  const m = domainModal.value
  domainBusy.value = true
  try {
    await api.post(`/api/sites/${m.site.id}/domains`, { domain: m.domain })
    notify('Domain ditambahkan')
    domainModal.value = null
    await refresh()
  } catch (e) { notify(e.message, false) } finally { domainBusy.value = false }
}

async function removeDomain(site, domain) {
  if (!confirm(`Lepas domain ${domain} dari ${site.domain}?`)) return
  try {
    await api.delete(`/api/sites/${site.id}/domains/${encodeURIComponent(domain)}`)
    notify('Domain dilepas')
    await refresh()
  } catch (e) { notify(e.message, false) }
}

onMounted(refresh)
</script>

<template>
  <section>
    <div class="head">
      <h3>Websites</h3>
      <SiteModal @created="refresh" />
    </div>
    <div class="tabs">
      <button v-for="t in PROJECT_TABS" :key="t" class="tab" :class="{ active: activeTab === t }" @click="activeTab = t">
        {{ t }}
      </button>
    </div>
    <table>
      <thead>
        <tr><th>Domain</th><th>Port</th><th>PHP</th><th>Status</th><th>Deskripsi</th><th>Kategori</th><th>Aksi</th></tr>
      </thead>
      <tbody>
        <tr v-for="s in visibleSites" :key="s.id">
          <td>
            {{ s.domain }}
            <span v-for="d in s.extra_domains" :key="d" class="alias" :title="'Klik untuk lepas ' + d" @click="removeDomain(s, d)">+{{ d }}</span>
            <button class="link" @click="addDomain(s)" title="Tambah domain">+ alias</button>
          </td>
          <td>
            <span v-if="s.port" :class="s.proxy_enabled ? 'badge on' : 'badge'">{{ s.port }} {{ s.proxy_enabled ? '(proxy)' : '' }}</span>
            <span v-else class="dim">—</span>
            <button class="link" @click="setPort(s)">ubah</button>
          </td>
          <td>
            <select :value="s.php_version" @change="changePhp(s, $event.target.value)">
              <option v-for="v in PHP_VERSIONS" :key="v" :value="v">{{ v }}</option>
            </select>
          </td>
          <td><span class="badge" :class="s.enabled ? 'on' : 'off'">{{ s.enabled ? 'aktif' : 'nonaktif' }}</span></td>
          <td class="dim">{{ s.description || '—' }}</td>
          <td>{{ s.category ? s.category : '—' }}</td>
          <td class="actions">
            <button @click="siteAction(s, 'enable')" :disabled="s.enabled">Enable</button>
            <button @click="siteAction(s, 'disable')" :disabled="!s.enabled">Disable</button>
            <button @click="toggleProxy(s)" :class="s.proxy_enabled ? 'primary' : ''" :disabled="!s.port && !s.proxy_enabled" title="Proxy penuh: nginx listen port → app localhost">Proxy {{ s.proxy_enabled ? 'ON' : 'OFF' }}</button>
            <button @click="siteAction(s, 'waf')" :class="s.waf_enabled ? 'primary' : ''" :title="s.waf_enabled ? 'WAF aktif — klik untuk nonaktif' : 'WAF nonaktif — klik untuk aktif'">WAF {{ s.waf_enabled ? 'ON' : 'OFF' }}</button>
            <button @click="siteAction(s, 'ssl')">SSL</button>
            <button @click="openFiles(s)">Files</button>
            <button @click="appm.open(s)" :class="s.app ? 'primary' : ''">App {{ s.app ? s.app.app_type : 'Pasang' }}</button>
            <button @click="vhe.open(s)">Config</button>
            <button class="danger" @click="siteAction(s, 'delete')">Hapus</button>
          </td>
        </tr>
        <tr v-if="!visibleSites.length"><td colspan="7" class="empty">Tidak ada site {{ activeTab }} — klik "+ Buat Site"</td></tr>
      </tbody>
    </table>
    <AppManager ref="appm" @changed="refresh" />
    <VhostEditor ref="vhe" @changed="refresh" />

    <div v-if="portModal" class="modal-backdrop" @click.self="portModal = null">
      <form class="modal" @submit.prevent="savePort">
        <h3>Port — {{ portModal.site.domain }}</h3>
        <div class="field">
          <label>Port (localhost) untuk proxy project</label>
          <input v-model.number="portModal.port" type="number" min="1" max="65535" required />
        </div>
        <div class="modal-actions">
          <button type="button" @click="portModal = null">Batal</button>
          <button class="primary" type="submit" :disabled="portBusy">Simpan</button>
        </div>
      </form>
    </div>

    <div v-if="domainModal" class="modal-backdrop" @click.self="domainModal = null">
      <form class="modal" @submit.prevent="saveDomain">
        <h3>Domain tambahan — {{ domainModal.site.domain }}</h3>
        <div class="field">
          <label>Domain alias (contoh: www.example.com)</label>
          <input v-model="domainModal.domain" placeholder="www.example.com" required />
        </div>
        <div class="modal-actions">
          <button type="button" @click="domainModal = null">Batal</button>
          <button class="primary" type="submit" :disabled="domainBusy">Tambah</button>
        </div>
      </form>
    </div>
  </section>
</template>
