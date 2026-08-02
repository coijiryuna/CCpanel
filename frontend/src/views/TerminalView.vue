<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'
import { useToast } from '../composables/useToast.js'

const { notify } = useToast()
const lines = ref([])
const cmd = ref('')
const running = ref(false)

function push(text) {
  lines.value.push(text)
  if (lines.value.length > 500) lines.value.splice(0, lines.value.length - 500)
}

async function run() {
  const c = cmd.value.trim()
  if (!c || running.value) return
  running.value = true
  push(`$ ${c}`)
  try {
    const r = await api.post('/api/terminal/exec', { cmd: c })
    if (r.output) push(r.output.replace(/\n$/, ''))
    if (r.exit_code !== 0) push(`[exit ${r.exit_code}]`)
  } catch (e) {
    push(`[error] ${e.message}`)
  } finally {
    running.value = false
    cmd.value = ''
  }
}

function onKey(e) {
  if (e.key === 'Enter') run()
}

onMounted(() => document.getElementById('term-input')?.focus())
</script>

<template>
  <section>
    <div class="head">
      <h3>Terminal</h3>
      <button @click="lines = []" :disabled="running">Bersihkan</button>
    </div>
    <div class="term">
      <pre class="term-out"><span v-for="(l, i) in lines" :key="i">{{ l }}<br></span><span v-if="!lines.length" class="muted">Jalankan perintah shell (root). Semua eksekusi dicatat di Logs.</span></pre>
      <div class="term-in">
        <span class="prompt">root@panel:~$</span>
        <input id="term-input" v-model="cmd" @keydown="onKey" :disabled="running" placeholder="contoh: ls -la /www/wwwroot" autocomplete="off" spellcheck="false" />
      </div>
    </div>
  </section>
</template>
