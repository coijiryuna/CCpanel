import { ref } from 'vue'

// Toast global: panggil notify(msg, ok) dari komponen mana pun.
const toast = ref(null)
let timer = null

export function notify(msg, ok = true) {
  toast.value = { msg, ok }
  clearTimeout(timer)
  timer = setTimeout(() => (toast.value = null), 3500)
}

export function useToast() {
  return { toast, notify }
}
