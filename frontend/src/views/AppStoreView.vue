<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()

const CATEGORIES = [
  { key: 'php', label: 'PHP' },
  { key: 'node', label: 'Node.js' },
  { key: 'go', label: 'Go' },
  { key: 'app', label: 'Aplikasi' },
]
const activeTab = ref('php')
const items = ref([])
const busyId = ref(null)

const visibleItems = computed(() => items.value.filter(i => i.category === activeTab.value))

onMounted(refresh)

async function refresh() {
  try {
    const r = await api.get('/api/appstore')
    items.value = r.items || []
  } catch (e) { notify(e.message, false) }
}

async function act(item, action) {
  busyId.value = item.id
  try {
    await api.post(`/api/appstore/${item.id}/${action}`)
    notify(`${item.name} ${action === 'install' ? 'terinstall' : 'dihapus'}`, true)
    await refresh()
  } catch (e) { notify(e.message, false) }
  finally { busyId.value = null }
}
</script>

<template>
  <div class="page">
    <h1>App Store</h1>
    <p class="muted">Pasang runtime &amp; aplikasi pendukung server.</p>

    <div class="tabs">
      <button v-for="c in CATEGORIES" :key="c.key"
        :class="['tab', { active: activeTab === c.key }]"
        @click="activeTab = c.key">{{ c.label }}</button>
    </div>

    <table class="table">
      <thead>
        <tr><th>Nama</th><th>Deskripsi</th><th>Status</th><th>Aksi</th></tr>
      </thead>
      <tbody>
        <tr v-for="i in visibleItems" :key="i.id">
          <td>{{ i.name }}</td>
          <td>{{ i.desc }}</td>
          <td>
            <span :class="['badge', i.installed ? 'ok' : 'muted']">
              {{ i.installed ? 'Terinstall' : 'Belum' }}
            </span>
          </td>
          <td>
            <button v-if="!i.installed" class="btn btn-primary"
              :disabled="busyId === i.id" @click="act(i, 'install')">Install</button>
            <button v-else class="btn btn-danger"
              :disabled="busyId === i.id" @click="act(i, 'uninstall')">Uninstall</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>