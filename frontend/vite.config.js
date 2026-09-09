import vue from '@vitejs/plugin-vue'
import VueI18nPlugin from '@intlify/unplugin-vue-i18n/vite'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'
import pkg from './package.json' with { type: 'json' }

export default defineConfig({
  plugins: [
    vue(),
    VueI18nPlugin({ include: './src/locales/**', module: 'petite-vue-i18n' }),
    tailwindcss(),
    // vite-plugin-pwa emits the manifest and app-shell service worker; Vite has neither.
    VitePWA({
      registerType: 'prompt',
      manifestFilename: 'manifest.json',
      manifest: {
        name: 'conversa',
        short_name: 'conversa',
        description: 'A local-first chat client for Claude, GPT, and DeepSeek.',
        theme_color: '#09090b',
        background_color: '#09090b',
        display: 'standalone',
        icons: [
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      // App-shell precache only. Caching /api would buffer its unending SSE responses.
      workbox: { navigateFallbackDenylist: [/^\/api/] },
    }),
  ],
  // Version shown in the sidebar footer.
  // Single source: package.json "version", bumped manually when tagging a release.
  define: { __APP_VERSION__: JSON.stringify(`v${pkg.version}`) },
  server: {
    // Dev: proxy API calls to the FastAPI backend so the browser sees one origin.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
