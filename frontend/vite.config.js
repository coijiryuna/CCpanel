import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Build langsung ke ../static (diserve backend FastAPI).
export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
