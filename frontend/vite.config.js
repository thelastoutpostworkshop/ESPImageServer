import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/ui/',
  plugins: [vue()],
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/server-info': 'http://127.0.0.1:8000',
      '/display': 'http://127.0.0.1:8000',
      '/generate': 'http://127.0.0.1:8000',
      '/assets': 'http://127.0.0.1:8000'
    }
  }
})
