<script setup>
import { ref } from 'vue'
import { useToast } from '../composables/useToast.js'
import { api } from '../api.js'

const { notify } = useToast()
const emit = defineEmits(['changed'])

const showModal = ref(false)
const site = ref(null)
const content = ref('')
const path = ref('')
const engine = ref('')
const busy = ref(false)

async function open(s) {
  site.value = s
  try {
    const r = await api.get(`/api/sites/${s.id}/vhost-config`)
    content.value = r.content
    path.value = r.path
    engine.value = r.engine
    showModal.value = true
  } catch (e) { notify(e.message, false) }
}

async function save() {
  busy.value = true
  try {
    await api.put(`/api/sites/${site.value.id}/vhost-config`, { content: content.value })
    notify('Konfigurasi disimpan + reload')
    showModal.value = false
    emit('changed')
  } catch (e) { notify(e.message, false) } finally { busy.value = false }
}

defineExpose({ open })
</script>

<template>
  <div v-if="showModal" class="modal-backdrop" @click.self="showModal = false">
    <div class="modal modal-wide">
      <h3>Edit Config — {{ site.domain }} <span class="badge">{{ engine }}</span></h3>
      <p class="muted">{{ path }}</p>
      <textarea v-model="content" class="code-editor" rows="22" spellcheck="false"></textarea>
      <div class="modal-actions">
        <button @click="showModal = false">Batal</button>
        <button class="primary" type="submit" :disabled="busy" @click="save">Simpan &amp; Reload</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-wide { width: 90%; max-width: 900px; }
.code-editor {
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.5;
  background: var(--bg, #1e1e1e);
  color: var(--fg, #d4d4d4);
  border: 1px solid var(--border, #444);
  border-radius: 6px;
  padding: 10px;
  resize: vertical;
}
.muted { color: var(--muted, #999); font-size: 12px; margin: 2px 0 8px; }
</style>
