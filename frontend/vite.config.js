import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(),tailwindcss(),],
  server: {
    host: '0.0.0.0',
    proxy: {
      // Change '/api' to whatever your backend routes start with. 
      // If it's just '/status', use that.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // If your backend routes don't actually start with /api, 
        // you might need a rewrite rule here.
      },
      // Proxy WebSocket requests for the telemetry stream
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      }
    }
  }
})
