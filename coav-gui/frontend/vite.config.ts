import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  test: {
    environment: 'node',
  },
  plugins: [vue()],
  // sockjs-client is a CJS module that references Node.js `global` — polyfill it for the browser
  define: { global: 'globalThis' },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8080',
      '/ws': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true
      }
    }
  }
})
