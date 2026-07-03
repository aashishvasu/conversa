import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'

// Version shown in the sidebar footer: latest git tag, or APP_VERSION where there's
// no .git (container builds pass it as a build arg). Empty → footer shows no version.
let version = process.env.APP_VERSION || ''
try {
  version ||= execSync('git describe --tags --abbrev=0', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
} catch { /* no git or no tags yet */ }

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: {
    // Dev: proxy API calls to the FastAPI backend so the browser sees one origin.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
