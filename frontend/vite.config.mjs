import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const certDir = fileURLToPath(new URL('./.cert', import.meta.url))
const USE_HTTPS = true;
// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
    VitePWA({
      injectRegister: false,
      registerType: 'autoUpdate',
      manifest: {
        name: 'LinuxCNC Interface',
        short_name: 'CNC UI',
        description: 'Web interface for LinuxCNC',
        theme_color: '#000000',
        background_color: '#0f172a',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          {
            src: 'icon-192x192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any'
          },
          {
            src: 'icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable'
          }
        ]
      }
    })
  ],
  resolve: {
    alias: {
      '@codemirror/lang-ini': fileURLToPath(
        new URL('./src/utils/codemirror-lang-ini.ts', import.meta.url),
      ),
    },
  },
  server: {
    host: '0.0.0.0',
    https: USE_HTTPS ? {
    key: `${certDir}/localhost-key.pem`,
    cert: `${certDir}/localhost.pem`,
  } : false,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    https: {
      key: `${certDir}/localhost-key.pem`,
      cert: `${certDir}/localhost.pem`,
    },
    allowedHosts: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws':  { target: 'ws://localhost:8000', ws: true },
    },
  },
})
