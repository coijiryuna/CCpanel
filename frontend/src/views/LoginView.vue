<script setup>
import { useToast } from '../composables/useToast.js'
import { setToken } from '../api.js'
import { useRouter } from 'vue-router'

const { notify } = useToast()
const router = useRouter()

async function doLogin(e) {
  const fd = new FormData(e.target)
  try {
    const r = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: fd.get('username'), password: fd.get('password') }),
    })
    if (!r.ok) throw new Error('Username atau password salah')
    const j = await r.json()
    setToken(j.token)
    const me = await fetch('/api/me', { headers: { Authorization: `Bearer ${j.token}` } }).then(x => x.json())
    setToken(j.token, me.role)
    router.push({ name: 'dashboard' })
  } catch (err) {
    notify(err.message, false)
  }
}
</script>

<template>
  <div class="login-wrap">
    <form class="login" @submit.prevent="doLogin">
      <h1>CCPanel</h1>
      <div class="field">
        <label>Username</label>
        <input name="username" autocomplete="username" required />
      </div>
      <div class="field">
        <label>Password</label>
        <input name="password" type="password" autocomplete="current-password" required />
      </div>
      <button class="primary" type="submit" style="width:100%">Login</button>
    </form>
  </div>
</template>
