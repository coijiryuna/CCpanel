<script setup>
import { useToast } from '../composables/useToast.js'
const { toast } = useToast()
</script>

<template>
  <div v-if="toast" class="toast" :class="toast.ok ? 'ok' : 'error'">{{ toast.msg }}</div>
</template>
