import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const certDir = fileURLToPath(new URL('./.cert', import.meta.url))
const USE_HTTPS = false;

const MACHINE_TARGET = 'http://localhost:8000';
const SYSTEM_TARGET = 'http://localhost:8001';

// Two-backend routing (machine :8000 / system :8001 — see
// backend/machine/main.py and backend/system/main.py). Keys are
// checked in this order; a leading "^" is compiled as a RegExp
// (Vite convention), everything else is a literal prefix match — so
// the macro-start regex exception and the system-owned prefixes must
// stay above the generic "/api" fallback.
const DEV_PROXY = {
  '^/api/v1/modules/macros/[^/]+/start$': { target: MACHINE_TARGET, changeOrigin: true },

  // Remove the trailing slashes here:
  '/api/v1/system': { target: SYSTEM_TARGET, changeOrigin: true },
  '/api/v1/programs': { target: SYSTEM_TARGET, changeOrigin: true },
  '/api/v1/modules/machineconfig': { target: SYSTEM_TARGET, changeOrigin: true },
  '/api/v1/modules/macros': { target: SYSTEM_TARGET, changeOrigin: true },

  '/api': { target: MACHINE_TARGET, changeOrigin: true },
  '/ws': { target: MACHINE_TARGET.replace('http', 'ws'), ws: true },
};

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
    // Mirrors the nginx routing split in install.sh: the system
    // service (:8001) owns machine-lifecycle-independent config
    // domains, the machine backend (:8000) owns everything else plus
    // the WebSocket. Order matters — Vite matches these top to
    // bottom (a leading "^" key is a RegExp, checked first-match-wins),
    // so the macros "/start" exception and the :8001 prefixes must
    // come before the generic "/api" fallback.
    proxy: DEV_PROXY,
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    https: {
      key: `${certDir}/localhost-key.pem`,
      cert: `${certDir}/localhost.pem`,
    },
    allowedHosts: true,
    proxy: DEV_PROXY,
  },
})
