<template>
  <div class="flex flex-col gap-3">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <h3 class="font-semibold truncate">Edit HTML + Live Preview — {{ filename }}</h3>
      <div class="flex gap-2 shrink-0">
        <button @click="$emit('close')"
          class="px-2 py-1 bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-sm cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600">Batal</button>
        <button @click="saveCode"
          class="bg-blue-600 text-white border-0 px-4 py-1 rounded-sm cursor-pointer disabled:opacity-60"
          :disabled="saving">Simpan</button>
      </div>
    </div>

    <!-- Editor HTML -->
    <div class="border border-gray-300 dark:border-gray-600 rounded-sm overflow-hidden">
      <div class="px-3 py-2 bg-gray-100 dark:bg-gray-800 border-b border-gray-300 dark:border-gray-600 font-bold text-sm">📄 HTML</div>
      <codemirror v-model="htmlCode" :extensions="[html(), oneDark]" :style="{ height: '280px' }"
        @update="schedulePreview" />
    </div>

    <!-- Live Preview -->
    <div class="flex-1 flex flex-col border border-gray-300 dark:border-gray-600 rounded-sm overflow-hidden">
      <div class="px-3 py-2 bg-gray-100 dark:bg-gray-800 border-b border-gray-300 dark:border-gray-600 font-bold text-sm">💻 Live Preview</div>
      <iframe ref="previewFrame" sandbox="allow-scripts allow-modals" class="w-full flex-1 min-h-80 border-0 bg-white"></iframe>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { html } from '@codemirror/lang-html'
import { oneDark } from '@codemirror/theme-one-dark'

const props = defineProps<{
  content: string
  filename: string
}>()
const emit = defineEmits<{
  (e: 'save', content: string): void
  (e: 'close'): void
}>()

const htmlCode = ref(props.content)
const previewFrame = ref<HTMLIFrameElement | null>(null)
const saving = ref(false)

let debounce: ReturnType<typeof setTimeout> | null = null

// preview live, di-debounce biar tak render tiap ketikan
function schedulePreview() {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(updatePreview, 300)
}

function updatePreview() {
  if (!previewFrame.value) return
  // ekstrak <style> ke head, sisanya jadi body — preview mandiri
  const styleMatch = htmlCode.value.match(/<style[^>]*>([\s\S]*?)<\/style>/i)
  const bodyHtml = htmlCode.value.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
  // srcdoc: browser render sendiri; hindari akses contentDocument (iframe sandbox = origin unik)
  previewFrame.value.srcdoc = `<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<style>${styleMatch?.[1] || ''}</style>
</head>
<body>
${bodyHtml}
</body>
</html>`
}

function saveCode() {
  saving.value = true
  emit('save', htmlCode.value)
  saving.value = false
}

watch(() => props.content, (v) => { htmlCode.value = v; updatePreview() })

onMounted(updatePreview)
onBeforeUnmount(() => { if (debounce) clearTimeout(debounce) })
</script>
