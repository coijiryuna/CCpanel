<script setup>
import { useRouter } from 'vue-router'
import AppToast from './components/AppToast.vue'
import { api, logout, getRole } from './api.js'
import { notify } from './composables/useToast.js'

const router = useRouter()
const isAdmin = getRole() === 'admin'

function doLogout() {
  logout()
  router.push({ name: 'login' })
}

async function renewSsl() {
  if (!confirm('Renew semua sertifikat SSL?')) return
  try {
    await api.post('/api/ssl/renew')
    notify('SSL renewed')
  } catch (e) { notify(e.message, false) }
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <h2>CCPanel</h2>
      <nav>
        <RouterLink to="/">Dashboard</RouterLink>
        <RouterLink to="/sites">Websites</RouterLink>
        <RouterLink to="/projects">Projects</RouterLink>
        <RouterLink to="/appstore">App Store</RouterLink>
        <RouterLink to="/files">Files</RouterLink>
        <RouterLink to="/databases">Databases</RouterLink>
        <RouterLink v-if="isAdmin" to="/trash">Trash</RouterLink>
        <RouterLink v-if="isAdmin" to="/logs">Logs</RouterLink>
        <RouterLink v-if="isAdmin" to="/terminal">Terminal</RouterLink>
        <RouterLink v-if="isAdmin" to="/backup">Backup</RouterLink>
        <RouterLink to="/ftp">FTP</RouterLink>
        <RouterLink v-if="isAdmin" to="/settings">Settings</RouterLink>
        <RouterLink v-if="isAdmin" to="/users">Users</RouterLink>
      </nav>
      <button v-if="isAdmin" class="logout" @click="renewSsl">Renew SSL</button>
      <button class="logout" @click="doLogout">Logout</button>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>

  <AppToast />
</template>
